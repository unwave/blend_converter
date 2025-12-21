from __future__ import annotations

import math
import operator
import typing

import bpy

if typing.TYPE_CHECKING:
    import typing_extensions


from . import bpy_context


VALIDATE_NEW_LINKS = True
""" Validate newly crated links. If `True` and a link is invalid — an exception is raised. """


DEFAULT_ATTRS = {
    '__doc__',
    '__module__',
    '__slots__',
    'bl_description',
    'bl_height_default',
    'bl_height_max',
    'bl_height_min',
    'bl_icon',
    'bl_idname',
    'bl_label',
    'bl_rna',
    'bl_static_type',
    'bl_width_default',
    'bl_width_max',
    'bl_width_min',
    'color',
    'dimensions',
    'draw_buttons',
    'draw_buttons_ext',
    'height',
    'hide',
    'input_template',
    'inputs',
    'internal_links',
    'is_registered_node_type',
    'label',
    'location',
    'mute',
    'name',
    'output_template',
    'outputs',
    'parent',
    'poll',
    'poll_instance',
    'rna_type',
    'select',
    'show_options',
    'show_preview',
    'show_texture',
    'socket_value_update',
    'type',
    'update',
    'use_custom_color',
    'width',
    'width_hidden',
}

INNER_ATTRS = {'texture_mapping', 'color_mapping'}
NOT_EXPOSED_ATTRS  = DEFAULT_ATTRS | INNER_ATTRS


SHADER_BLENDING_NODES = {
    'ShaderNodeAddShader',
    'ShaderNodeMixShader',
}


SHADER_OUTPUTTING_NODES = {

    # blending
    'ShaderNodeAddShader',
    'ShaderNodeMixShader',

    # world
    'ShaderNodeBackground',

    # principled
    'ShaderNodeBsdfPrincipled',

    # main
    'ShaderNodeBsdfAnisotropic',
    'ShaderNodeBsdfDiffuse',
    'ShaderNodeBsdfGlass',
    'ShaderNodeBsdfHair',
    'ShaderNodeBsdfHairPrincipled',
    'ShaderNodeBsdfRefraction',
    'ShaderNodeBsdfToon',
    'ShaderNodeBsdfTranslucent',
    'ShaderNodeBsdfTransparent',
    'ShaderNodeEmission',
    'ShaderNodeHoldout',
    'ShaderNodeSubsurfaceScattering',
    # removed
    'ShaderNodeBsdfGlossy',
    'ShaderNodeBsdfVelvet',
    # new
    'ShaderNodeBsdfSheen',
    'ShaderNodeBsdfRayPortal',

    # EEVEE only
    'ShaderNodeEeveeSpecular',

    # volume
    'ShaderNodeVolumeAbsorption',
    'ShaderNodeVolumePrincipled',
    'ShaderNodeVolumeScatter',
}


class Socket_Identifier:

    if bpy.app.version >= (4, 0, 0):
        EMISSION = 'Emission Color'
        SPECULAR_IOR = 'Specular IOR Level'
        SUBSURFACE = 'Subsurface Weight'
        TRANSMISSION = 'Transmission'
        CLEARCOAT = 'Coat Weight'
        SHEEN = 'Sheen Weight'
    else:
        EMISSION = 'Emission'
        SPECULAR_IOR = 'Specular'
        SUBSURFACE = 'Subsurface'
        TRANSMISSION = 'Transmission'
        CLEARCOAT = 'Clearcoat'
        SHEEN = 'Sheen'

class Compositor_Node_Type:
    """
    Nodes: Remove legacy combine/separate nodes #135376
    https://projects.blender.org/blender/blender/pulls/135376
    """

    if bpy.app.version >= (5, 0):
        COMBINE_RGBA = 'CompositorNodeCombineColor'
        SEPARATE_RGBA = 'CompositorNodeSeparateColor'
        MATH = 'ShaderNodeMath'
    else:
        COMBINE_RGBA = 'CompositorNodeCombRGBA'
        SEPARATE_RGBA = 'CompositorNodeSepRGBA'
        MATH = 'CompositorNodeMath'


class Shader_Node_Type:

    if bpy.app.version >= (5, 0):
        SEPARATE_RGB = 'ShaderNodeSeparateColor'
    else:
        SEPARATE_RGB = 'ShaderNodeSeparateRGB'


NODE_GROUP_TYPE_NAMES = ('ShaderNodeGroup', 'CompositorNodeGroup', 'GeometryNodeGroup')

# there are 3 copies for socket, node and tree because the type checking system were confused
_S_SOCKET = typing.TypeVar('_S_SOCKET', '_Shader_Socket_Wrapper', '_Compositor_Socket_Wrapper')
_S_NODE = typing.TypeVar('_S_NODE', '_Shader_Node_Wrapper', '_Compositor_Node_Wrapper')
# _S_TREE = typing.TypeVar('_S_TREE', '_Tree_Wrapper', 'Shader_Tree_Wrapper', 'Compositor_Tree_Wrapper')

_N_SOCKET = typing.TypeVar('_N_SOCKET', '_Shader_Socket_Wrapper', '_Compositor_Socket_Wrapper')
# _N_NODE = typing.TypeVar('_N_NODE', '_Shader_Node_Wrapper', '_Compositor_Node_Wrapper')
_N_TREE = typing.TypeVar('_N_TREE', 'Shader_Tree_Wrapper', 'Compositor_Tree_Wrapper')

_T_SOCKET = typing.TypeVar('_T_SOCKET', '_Shader_Socket_Wrapper', '_Compositor_Socket_Wrapper')
_T_NODE = typing.TypeVar('_T_NODE', '_Shader_Node_Wrapper', '_Compositor_Node_Wrapper')
# _T_TREE = typing.TypeVar('_T_TREE', 'Shader_Tree_Wrapper', 'Compositor_Tree_Wrapper')


_BL_NODE = typing.TypeVar('_BL_NODE', bpy.types.Node, bpy.types.ShaderNode, bpy.types.CompositorNode)
_BL_TREE = typing.TypeVar('_BL_TREE', bpy.types.NodeTree, bpy.types.ShaderNodeTree, bpy.types.CompositorNodeTree)



ALLOW_NODE_MOVE = True


class _No_Type:
    """ To fix "Cannot create consistent method ordering" """
    pass


class _Socket_Wrapper(bpy.types.NodeSocketColor if typing.TYPE_CHECKING else _No_Type, typing.Generic[_S_NODE]):

    __slots__ = ('bl_socket', 'connections', 'node')


    bl_socket: typing.Union[bpy.types.NodeSocketColor, bpy.types.NodeSocketFloat, bpy.types.NodeSocketVector]
    node: _S_NODE
    connections: typing.List['typing_extensions.Self']
    """ List of connected sockets. """


    def __init__(self, bl_socket: typing.Union[bpy.types.NodeSocketColor, bpy.types.NodeSocketFloat, bpy.types.NodeSocketVector], node: _S_NODE):
        object.__setattr__(self, 'bl_socket', bl_socket)
        object.__setattr__(self, 'connections', [])
        object.__setattr__(self, 'node', node)


    if not typing.TYPE_CHECKING:


        def __getattr__(self, attr):
            return getattr(self.bl_socket, attr)


        def __setattr__(self, attr, value):
            setattr(self.bl_socket, attr, value)


    def __repr__(self):
        return f"""< {self.bl_idname} "{self.identifier}" >"""


    def new(self, type, identifier: typing.Union[str, int] = 0, **attributes) -> _S_NODE:
        """
        `type`: node type to create
        `identifier`: socket identifier of the created node
        `attributes`: attributes to set for the node on creating like the math operator type, node_tree, etc.
        """

        tree = self.node.tree
        bl_tree: bpy.types.NodeTree = tree.bl_tree

        new_bl_node = bl_tree.nodes.new(type)
        for attr_key, attr_value in attributes.items():
            setattr(new_bl_node, attr_key, attr_value)

        new_node = tree._node_class(new_bl_node, tree)
        tree[new_bl_node] = new_node
        tree._new_nodes.append(new_node)

        if self.is_output:
            new_socket = new_node.inputs[identifier]
        else:
            new_socket = new_node.outputs[identifier]

        if new_socket == None:
            bl_tree.nodes.remove(new_bl_node)
            raise KeyError(f'No {"input" if self.is_output else "output"} socket "{identifier}" in the node "{new_node.name}"')


        if self.is_output:
            self.join(new_socket, move = False)
            if ALLOW_NODE_MOVE:
                x, y = self.get_location()
                new_node.location = (x + 200, y)
        else:
            self.join(new_socket)

        return new_node


    def insert_new(self, type, identifier: typing.Union[str, int] = 0, new_node_identifier: typing.Union[str, int] = 0, **attributes) -> _S_NODE:
        """
        The same as `new()` but preserves the links by plugging it to the new node.

        `type`: node type to create
        `identifier`: socket identifier of the created node
        `new_node_identifier`: re-plugging target on the new node
        `attributes`: attributes to set for the node on creating like the math operator type, node_tree, etc.
        """

        connected_sockets = self.connections.copy()

        new_node = self.new(type, identifier, **attributes)

        if self.is_output:
            for socket in connected_sockets:
                new_node.outputs[new_node_identifier].join(socket, move = False)
        else:
            for socket in connected_sockets:
                new_node.inputs[new_node_identifier].join(socket, move = False)

        return new_node


    def disconnect(self):

        if self.is_output:
            raise ValueError('Can only disconnect inputs.')

        if not self.connections:
            return

        self.connections[0].connections.remove(self)
        self.connections.clear()

        tree = self.node.tree
        bl_link = tree.input_bl_socket_to_link_map[self.bl_socket]
        del tree.input_bl_socket_to_link_map[self.bl_socket]
        tree.bl_tree.links.remove(bl_link)


    def join(self, socket: 'typing_extensions.Self', move = True):

        # reroute sockets are being rebuild when connected to a socket of a different type invalidating the wrapper
        self_pointer = self.as_pointer()
        socket_pointer = socket.as_pointer()


        if socket.is_output:
            bl_link = self.bl_socket.id_data.links.new(self.bl_socket, socket.bl_socket)


            if self_pointer != bl_link.to_socket.as_pointer():
                object.__setattr__(self, 'bl_socket', bl_link.to_socket)

            if socket_pointer != bl_link.from_socket.as_pointer():
                object.__setattr__(socket, 'bl_socket', bl_link.from_socket)


            if VALIDATE_NEW_LINKS and not bl_link.is_valid:
                raise RuntimeError(f"Invalid link created: from node: '{socket.node.name}' [{socket.node.bl_idname}] and socket: '{socket.identifier}' to node: '{self.node.name}' [{self.node.bl_idname}] and socket: '{self.identifier}'")

            # only one input is allowed
            for _socket in self.connections:
                _socket.connections.remove(self)
            self.connections.clear()

            self.connections.append(socket)

            socket.connections.append(self)

            self.node.tree.input_bl_socket_to_link_map[self.bl_socket] = bl_link

            if ALLOW_NODE_MOVE and move:
                x, y = self.get_location()
                x -= 100
                shift = tuple(map(operator.sub, (x, y), socket.get_location()))
                socket.node.location = tuple(map(operator.add, socket.node.location, shift))
                for node in socket.node.descendants:
                    node.location = tuple(map(operator.add, node.location, shift))

        else:
            bl_link = self.bl_socket.id_data.links.new(socket.bl_socket, self.bl_socket)


            if self_pointer != bl_link.from_socket.as_pointer():
                object.__setattr__(self, 'bl_socket', bl_link.from_socket)

            if socket_pointer != bl_link.to_socket.as_pointer():
                object.__setattr__(socket, 'bl_socket', bl_link.to_socket)


            if VALIDATE_NEW_LINKS and not bl_link.is_valid:
                raise RuntimeError(f"Invalid link created: from node: '{self.node.name}' [{self.node.bl_idname}] and socket: '{self.identifier}' to node: '{socket.node.name}' [{socket.node.bl_idname}] and socket: '{socket.identifier}'")

            # only one input is allowed
            for _socket in socket.connections:
                _socket.connections.remove(socket)
            socket.connections.clear()

            self.connections.append(socket)

            socket.connections.append(self)

            self.node.tree.input_bl_socket_to_link_map[socket.bl_socket] = bl_link

            if ALLOW_NODE_MOVE and move:
                x, y = socket.get_location()
                x -= 100
                shift = tuple(map(operator.sub, (x, y), self.get_location()))
                self.node.location = tuple(map(operator.add, self.node.location, shift))
                for node in self.node.descendants:
                    node.location = tuple(map(operator.add, node.location, shift))


    def get_location(self):
        """ https://developer.blender.org/D12695 """

        node = self.node
        x, y = node.location

        if node.bl_idname in NODE_GROUP_TYPE_NAMES:
            identifier = self.name
        else:
            identifier = self.identifier

        if self.is_output:
            index = node.bl_node.outputs.find(identifier)
            x = x + node.width
            y = y - 35 - 21.5 * index
        else:
            index = node.bl_node.inputs.find(identifier)

            attrs = [attr for attr in dir(self.node.bl_node) if attr not in NOT_EXPOSED_ATTRS]
            if not attrs or node.show_options == False:
                attr_gap = 0
            elif len(attrs) == 1:
                attr_gap = 30
            else:
                attr_gap = 30 + (len(attrs) - 1) * 24.5

            y = y - 35 - 21.5*len(node.bl_node.outputs) - 3 - attr_gap - 21.5 * index

        return x, y


    def set_default_value(self, value):

        type = self.bl_socket.type
        value_len = len(value) if isinstance(value, typing.Sized) else 1

        if type in ('VALUE', 'INT'):
            if value_len == 1:  # VALUE
                self.bl_socket.default_value = value
            elif value_len == 3:  # VECTOR
                self.bl_socket.default_value = sum(value)/3
            else:  # RGBA
                self.bl_socket.default_value = value[0]*0.2126 + value[1]*0.7152 + value[2]*0.0722
        elif type == 'RGBA':
            if value_len == 1:  # VALUE
                self.bl_socket.default_value = (value, value, value, 1) # negative color not possible
            elif value_len == 3:  # VECTOR
                self.bl_socket.default_value = (*value, 1) # negative color not possible
            else:  # RGBA
                self.bl_socket.default_value = value
        elif type == 'VECTOR':
            if value_len == 1:  # VALUE
                self.bl_socket.default_value = (value, value, value)[:len(self.bl_socket.default_value)]
            elif value_len == 3:  # VECTOR
                self.bl_socket.default_value = value[:len(self.bl_socket.default_value)]
            else:  # RGBA
                self.bl_socket.default_value = value[:3][:len(self.bl_socket.default_value)]
        else:
            raise ValueError(f"Unexpected socket type: {type}")


    @property
    def descendants(self) -> typing.List[_S_NODE]:

        if self.is_output:
            raise ValueError('Only for input sockets.')

        nodes = []

        for socket in self.connections:
            nodes.append(socket.node)
            nodes.extend(socket.node.descendants)

        return list(dict.fromkeys(nodes))


    @property
    def ancestors(self) -> typing.List[_S_NODE]:

        if not self.is_output:
            raise ValueError('Only for output sockets.')

        nodes = []

        for socket in self.connections:
            nodes.append(socket.node)
            nodes.extend(socket.node.ancestors)

        return list(dict.fromkeys(nodes))


    def is_close(self, value: typing.Union[float, typing.Iterable[float]], rel_tol = 1e-6):

        if isinstance(value, typing.Iterable):
            return all(math.isclose(a, b, rel_tol=rel_tol) for a, b in zip(value, self.default_value))
        else:
            return math.isclose(value, self.default_value, rel_tol=rel_tol)


    def is_equal(self, other: 'typing_extensions.Self'):

        if self is other:
            return True

        if self.is_output != other.is_output:
            return False

        if self.bl_idname != other.bl_idname:
            return False

        if self.connections or other.connections:
            return set(self.connections) == set(other.connections)

        return self.default_value == other.default_value


    def __hash__(self):
        return id(self)


    def be(self, value: typing.Union[str, typing.Container[str], 'bpy.types.bpy_struct']):

        if isinstance(value, str):
            return self.bl_idname == value
        elif isinstance(value, typing.Container):
            return self.bl_idname in value
        else:
            return isinstance(self.bl_socket, value)


class _Sockets_Wrapper(typing.Generic[_S_SOCKET, _S_NODE], typing.Dict[str, _S_SOCKET]):

    __slots__ = ('identifiers', )


    def __init__(self, node: _S_NODE, socket_class: _Socket_Wrapper, is_output: bool):

        if is_output:
            dict.__init__(self, ((bl_socket.identifier, socket_class(bl_socket, node)) for bl_socket in node.bl_node.outputs))
        else:
            dict.__init__(self, ((bl_socket.identifier, socket_class(bl_socket, node)) for bl_socket in node.bl_node.inputs))

        object.__setattr__(self, 'identifiers', tuple(self.keys()))


    def __getitem__(self, key: typing.Union[int, str]) -> _S_SOCKET:
        if isinstance(key, int):
            return dict.__getitem__(self, self.identifiers[key])
        else:
            return dict.__getitem__(self, key)


    def __iter__(self):
        return iter(self.values())


    def get(self, key: typing.Union[int, str], default = None) -> _S_SOCKET:
        if isinstance(key, int):
            if key >= len(self.identifiers):
                return default
            return dict.get(self, self.identifiers[key], default)
        else:
            return dict.get(self, key, default)



class _Node_Wrapper(bpy.types.Node if typing.TYPE_CHECKING else _No_Type, typing.Generic[_N_TREE, _N_SOCKET, _BL_TREE, _BL_NODE]):

    __slots__ = ('bl_node', 'tree', 'outputs', 'inputs')

    bl_node: _BL_NODE
    tree: _N_TREE

    outputs: _Sockets_Wrapper[_N_SOCKET, 'typing_extensions.Self']
    inputs: _Sockets_Wrapper[_N_SOCKET, 'typing_extensions.Self']


    def __init__(self, bl_node: _BL_NODE, tree: _N_TREE):
        object.__setattr__(self, 'bl_node', bl_node)
        object.__setattr__(self, 'tree', tree)
        object.__setattr__(self, 'outputs', _Sockets_Wrapper(self, tree._socket_class, True))
        object.__setattr__(self, 'inputs', _Sockets_Wrapper(self, tree._socket_class, False))


    if not typing.TYPE_CHECKING:

        def __getattr__(self, attr):
            return getattr(self.bl_node, attr)


        def __setattr__(self, attr, value):
            setattr(self.bl_node, attr, value)


    @property
    def node_tree(self) -> _BL_TREE:
        """ Only for node groups. """
        return self.bl_node.node_tree


    @node_tree.setter
    def node_tree(self, node_tree: _BL_TREE):
        self.bl_node.node_tree = node_tree
        self.update_sockets()


    def update_sockets(self):

        new_outputs: _Sockets_Wrapper[_N_SOCKET, 'typing_extensions.Self'] = _Sockets_Wrapper(self, self.tree._socket_class, True)
        for socket in self.outputs:
            if socket.identifier in new_outputs:
                object.__setattr__(new_outputs[socket.identifier], 'connections', socket.connections)
        object.__setattr__(self, 'outputs', new_outputs)

        new_inputs: _Sockets_Wrapper[_N_SOCKET, 'typing_extensions.Self'] = _Sockets_Wrapper(self, self.tree._socket_class, False)
        for socket in self.inputs:
            if socket.identifier in new_inputs:
                object.__setattr__(new_inputs[socket.identifier], 'connections', socket.connections)
        object.__setattr__(self, 'inputs', new_inputs)


    def __repr__(self):
        return f"""< {self.bl_idname} "{self.name}" >"""


    def __getitem__(self, key) -> typing.Optional['typing_extensions.Self']:

        if isinstance(key, int):
            socket = self.inputs[self.bl_node.inputs[key].identifier]
        else:
            socket = self.inputs[key]

        if socket.connections:
            return socket.connections[0].node
        else:
            return None


    def __setitem__(self, key: typing.Union[int, str], value):

        if isinstance(key, int):
            socket = self.inputs[self.bl_node.inputs[key].identifier]
        else:
            socket = self.inputs[key]

        if socket.is_output:
            raise ValueError('Can only set inputs.')

        if isinstance(value, _Socket_Wrapper):
            socket.join(value, move = False)
        else:
            socket.set_default_value(value)
            socket.disconnect()


    def get_value(self, identifier: typing.Union[int, str] , convert = True):
        if isinstance(identifier, int):
            value = self.bl_node.inputs[identifier].default_value
        else:
            if identifier in self.inputs.keys():
                value = self.inputs[identifier].bl_socket.default_value
            else:
                return None
        try:
            return tuple(value)
        except Exception:
            return value


    def delete(self):

        bl_tree = self.tree.bl_tree
        bl_node = self.bl_node

        del self.tree[bl_node]

        bl_tree.nodes.remove(bl_node)

        if self in self.tree._new_nodes:
            self.tree._new_nodes.remove(self)

        children: typing.List['typing_extensions.Self']
        children = []
        parents: typing.List['typing_extensions.Self']
        parents = []

        for input_socket in self.inputs.values():
            for socket in input_socket.connections:
                children.append(socket.node)
                socket.connections.remove(input_socket)

        for output_socket in self.outputs.values():
            for socket in output_socket.connections:
                parents.append(socket.node)
                socket.connections.remove(output_socket)

        return children, parents


    @property
    def children(self):
        return [other_socket.node for socket in self.inputs.values() for other_socket in socket.connections]


    @property
    def descendants(self) -> typing.List['typing_extensions.Self']:

        nodes = []
        seen = set()
        pool = self.children
        nodes.extend(pool)

        while pool:
            node = pool.pop()

            if node in seen:
                continue
            seen.add(node)

            children = node.children
            nodes.extend(children)
            pool.extend(children)

        return list(dict.fromkeys(nodes))


    @property
    def parents(self):
        return [other_socket.node for socket in self.outputs.values() for other_socket in socket.connections]


    @property
    def ancestors(self) -> typing.List['typing_extensions.Self']:

        nodes = []
        seen = set()
        pool = self.parents
        nodes.extend(pool)

        while pool:
            node = pool.pop()

            if node in seen:
                continue
            seen.add(node)

            parents = node.parents
            nodes.extend(parents)
            pool.extend(parents)

        return list(dict.fromkeys(nodes))


    def get_input(self, key: typing.Union[int, str], socket_only = False):
        """ Get the socket inputting socket or a value if the socket is not connected. """

        socket = self.inputs[key]
        if socket.connections:
            return socket.connections[0]
        else:
            if socket_only:
                return None
            return self.get_value(key)


    def set_input(self, key, value):
        """ If no such socket when the value is ignored. Does not disconnect when setting a constant value. """
        socket = self.inputs.get(key)
        if socket:
            if isinstance(value, _Socket_Wrapper):
                socket.join(value)
            else:
                socket.bl_socket.default_value = value


    def set_inputs(self, settings):

        attributes = settings.pop('Attributes', None)

        if attributes:
            for attribute, value in attributes.items():
                if hasattr(self.bl_node, attribute):
                    setattr(self.bl_node, attribute, value)

        for key, value in settings.items():
            if value is not None:
                self.set_input(key, value)


    @property
    def has_inputs(self):
        return any(len(input.connections) != 0 for input in self.inputs)


    def shift(self, x: float, y: float):
        a, b = self.location
        self.location = (a + x, b + y)


    def be(self, value: typing.Union[str, typing.Container[str], 'bpy.types.bpy_struct']):

        if isinstance(value, str):
            return self.bl_idname == value
        elif isinstance(value, typing.Container):
            return self.bl_idname in value
        else:
            return isinstance(self.bl_node, value)


    def get_input_by_name(self, name: str):
        for socket in self.inputs:
            if socket.name == name:
                return socket
        else:
            return None


class _Tree_Wrapper(bpy.types.NodeTree if typing.TYPE_CHECKING else _No_Type, typing.Generic[_T_NODE, _T_SOCKET, _BL_TREE, _BL_NODE], typing.Dict[_BL_NODE, _T_NODE]):

    _socket_class: _Socket_Wrapper
    _node_class: _T_NODE

    __slots__ = ('bl_tree', 'input_socket_to_link_map', '_new_nodes')


    def __init__(self, bl_tree: _BL_TREE):

        self.clear()

        self.bl_tree = bl_tree
        self.input_bl_socket_to_link_map: typing.Dict[bpy.types.NodeSocketStandard, bpy.types.NodeLink] = {}

        self._new_nodes: typing.List[_T_NODE] = []
        """ The nodes created via the wrapper. """

        super().__init__((node, self._node_class(node, self)) for node in bl_tree.nodes)

        for link in bl_tree.links:

            # TODO: deal with all the invalid links
            # hidden links are invalid but may exist and can become valid when you change properties
            # possible option is to remove all the invalid links when about to significantly changing the tree anyway
            # or find and remove all the cyclical dependency
            # check link.is_hidden

            if not link.is_valid:
                continue

            to_socket = link.to_socket
            from_socket = link.from_socket

            to_node = self[link.to_node]
            from_node = self[link.from_node]

            to_node.inputs[to_socket.identifier].connections.append(from_node.outputs[from_socket.identifier])
            from_node.outputs[from_socket.identifier].connections.append(to_node.inputs[to_socket.identifier])

            self.input_bl_socket_to_link_map[to_socket] = link


    if typing.TYPE_CHECKING:
        def __getitem__(self, key: _BL_NODE) -> _T_NODE: ...


    def __hash__(self):
        return id(self)


    def delete_new_nodes(self):
        """ Delete nodes created with the wrapper. """
        for node in list(self._new_nodes):
            node.delete()
        self._new_nodes.clear()


    def __iter__(self) -> typing.Iterator[_T_NODE]:
        return iter(self.values())


    def get_by_type(self, type: str) -> typing.List[_T_NODE]:
        return [node for node in self.values() if node.type == type]


    def get_by_bl_idname(self, bl_idname: typing.Union[str, typing.Iterable[str]]) -> typing.List[_T_NODE]:

        if isinstance(bl_idname, str):
            bl_idname = {bl_idname}

        return [node for node in self.values() if node.bl_idname in bl_idname]


    def new(self, type: str, **attributes) -> _T_NODE:

        bl_node = self.bl_tree.nodes.new(type)

        for attr_key, attr_value in attributes.items():
            setattr(bl_node, attr_key, attr_value)

        node = self._node_class(bl_node, self)
        self[bl_node] = node
        self._new_nodes.append(node)
        return node


    @property
    def active_node(self) -> _T_NODE:
        active = self.bl_tree.nodes.active
        if not active:
            return None
        return self[active]


    def get_socket_wrapper(self, socket: bpy.types.NodeSocketStandard):

        if isinstance(socket, _Socket_Wrapper):
            socket = socket.bl_socket

        if socket.is_output:
            return self[socket.node].outputs[socket.identifier]
        else:
            return self[socket.node].inputs[socket.identifier]



class _Shader_Socket_Wrapper(_Socket_Wrapper['_Shader_Node_Wrapper']):


    def get_default_value_as_node(self):

        if self.type in ('VALUE', 'INT'):
            node = self.new('ShaderNodeValue')
            node.outputs[0].bl_socket.default_value = self.bl_socket.default_value
            node.label = self.name
            return node

        elif self.type == 'RGBA':
            node = self.new('ShaderNodeRGB')
            node.outputs[0].bl_socket.default_value = self.bl_socket.default_value
            node.label = self.name
            return node

        elif self.type == 'VECTOR':
            node = self.new('ShaderNodeCombineXYZ')
            node.inputs['X'].bl_socket.default_value, node.inputs['Y'].bl_socket.default_value, node.inputs['Z'].bl_socket.default_value = tuple(self.bl_socket.default_value)
            node.label = self.name
            return node

        else:
            if self.type not in ('SHADER', 'STRING'):
                print(f"Unexpected socket type: {self.type}")

            node = self.new('ShaderNodeValue')
            node.outputs[0].bl_socket.default_value = 0
            node.label = self.name
            return node


    def as_output(self):

        if self.is_output:
            return self

        if self.connections:
            return self.connections[0]

        if self.identifier in ('Normal', 'Tangent', 'Clearcoat Normal', 'Coat Normal'):
            return self.new('ShaderNodeNormalMap').outputs[0]
        else:
            return self.get_default_value_as_node().outputs[0]


class _Shader_Node_Wrapper(_Node_Wrapper['Shader_Tree_Wrapper', _Shader_Socket_Wrapper, bpy.types.ShaderNodeTree, bpy.types.ShaderNode], bpy.types.ShaderNode if typing.TYPE_CHECKING else object):

    outputs: _Sockets_Wrapper[_Shader_Socket_Wrapper, '_Shader_Node_Wrapper']
    inputs: _Sockets_Wrapper[_Shader_Socket_Wrapper, '_Shader_Node_Wrapper']


    def lerp_input(self, value, from_min = 0, from_max = 1, to_min = 0, to_max = 1, clamp = False, clamp_min = 0, clamp_max = 1):

        if isinstance(value, _Shader_Socket_Wrapper):
            map_range = value.new('ShaderNodeMapRange', 'Value')
            map_range.inputs['From Min'].bl_socket.default_value = from_min
            map_range.inputs['From Max'].bl_socket.default_value = from_max
            map_range.inputs['To Min'].bl_socket.default_value = to_min
            map_range.inputs['To Max'].bl_socket.default_value = to_max
            map_range.clamp = clamp
            value = map_range.outputs['Result']
        else:
            value = to_min + (value - from_min) / (from_max - from_min) * (to_max - to_min)
            if clamp:
                value = min(max(value, clamp_min), clamp_max)
        return value


    def get_principled_inputs(self):
        """
        Get all inputs that can be used in a Principled BSDF representation.

        Returns inputs that should be plugged to a Principled BSDF to resemble the shader node as close as possible.
        """

        bl_idname = self.bl_idname

        if bl_idname == 'ShaderNodeBsdfAnisotropic':
            pbr = {
                'Base Color': self.get_input('Color'),
                'Roughness': self.get_input('Roughness'),
                'Anisotropic': self.get_input('Anisotropy'),
                'Anisotropic Rotation': self.get_input('Rotation'), # need to add 0.25 to match
                'Normal': self.get_input('Normal', True),
                'Tangent': self.get_input('Tangent', True),
                'Metallic': 1
            }

            distribution = self.distribution
            if distribution not in ('GGX', 'MULTI_GGX'):
                distribution = 'GGX'

            pbr['Attributes'] = {'distribution': distribution}

            return pbr

        elif bl_idname == 'ShaderNodeBsdfDiffuse': # ✔️ kind of

            pbr = {
                'Base Color': self.get_input('Color'),
                'Roughness': self.get_input('Roughness'),
                'Normal': self.get_input('Normal', True),

                Socket_Identifier.SPECULAR_IOR: 0,
            }

            pbr['Roughness'] = self.lerp_input(pbr['Roughness'], to_min = 0.90, to_max = 1.33) # ?

            return pbr

        elif bl_idname == 'ShaderNodeBsdfGlass':
            pbr =  {
                'Base Color': self.get_input('Color'),
                'Roughness': self.get_input('Roughness'),
                'IOR': self.get_input('IOR'),
                'Normal': self.get_input('Normal', True),

                Socket_Identifier.TRANSMISSION: 1
            }

            distribution = self.distribution # just a copy from ShaderNodeBsdfGlossy, not tested
            if distribution == 'SHARP':
                pbr['Roughness'] = 0
            elif distribution in ('BECKMANN', 'ASHIKHMIN_SHIRLEY'):
                pbr['Roughness'] = self.lerp_input(pbr['Roughness'], to_max = 0.7)

            if distribution not in ('GGX', 'MULTI_GGX'):
                distribution = 'GGX'

            pbr['Attributes'] = {'distribution': distribution}

            return pbr

        elif bl_idname == 'ShaderNodeBsdfGlossy':
            pbr = {
                'Base Color': self.get_input('Color'),
                'Roughness': self.get_input('Roughness'),
                'Normal': self.get_input('Normal', True),
                'Metallic': 1
            }
            # SHARP BECKMANN GGX ASHIKHMIN_SHIRLEY MULTI_GGX
            distribution = self.distribution
            if distribution == 'SHARP':
                pbr['Roughness'] = 0
            elif distribution in ('BECKMANN', 'ASHIKHMIN_SHIRLEY'):
                pbr['Roughness'] = self.lerp_input(pbr['Roughness'], to_max = 0.7)

            if distribution not in ('GGX', 'MULTI_GGX'):
                distribution = 'GGX'

            pbr['Attributes'] = {'distribution': distribution}

            return pbr

        elif bl_idname == 'ShaderNodeBsdfRefraction':
            pbr = {
                'Base Color': self.get_input('Color'),
                'Roughness': self.get_input('Roughness'),
                'IOR': self.get_input('IOR'),
                'Normal': self.get_input('Normal', True),

                Socket_Identifier.TRANSMISSION: 1
            }

            distribution = self.distribution
            if distribution not in ('GGX', 'MULTI_GGX'):
                distribution = 'GGX'
            pbr['Attributes'] = {'distribution': distribution}

            return pbr

        elif bl_idname == 'ShaderNodeBsdfToon':
            return {
                'Base Color': self.get_input('Color'),
                #'Size': self.get_input('Size'),
                #'Smooth': self.get_input('Smooth'),
                'Normal': self.get_input('Normal', True),
                #'Attributes': {'component': self.component}
            }

        elif bl_idname == 'ShaderNodeBsdfTranslucent': # ✔️ cannot do that
            return {
                'Base Color': self.get_input('Color'),
                'Normal': self.get_input('Normal', True),

                'Attributes': {'distribution': 'MULTI_GGX'},
                'Specular Tint': self.get_input('Color') if bpy.app.version >= (4,0,0) else 1,
                'Roughness': 1,
                Socket_Identifier.TRANSMISSION: 1
            }

        elif bl_idname == 'ShaderNodeBsdfTransparent': # ✔️
            return {
                'Base Color': self.get_input('Color'),

                Socket_Identifier.SPECULAR_IOR: 0,
                'Roughness': 0,
                'IOR': 1,
                Socket_Identifier.TRANSMISSION: 1
            }

        elif bl_idname == 'ShaderNodeBsdfVelvet': # ✔️ not possible
            return {
                'Base Color': self.get_input('Color'),
                #Socket_Identifier.SHEEN: self.get_input('Sigma'),
                'Normal': self.get_input('Normal', True),

                Socket_Identifier.SPECULAR_IOR: 1/3,
                'Roughness': 1,
                Socket_Identifier.SHEEN: 2,
                Socket_Identifier.CLEARCOAT: 1,
                'Clearcoat Roughness': 1,
            }

        elif bl_idname in ('ShaderNodeEmission', 'ShaderNodeBackground'): # ✔️
            return {
                Socket_Identifier.EMISSION: self.get_input('Color'),
                'Emission Strength': self.get_input('Strength'),

                'Base Color': (0, 0, 0, 1),
                'Roughness': 0,
                Socket_Identifier.SPECULAR_IOR: 0,
            }

        elif bl_idname == 'ShaderNodeHoldout': # ✔️
            return {
                'Base Color': (0, 0, 0, 1),
                Socket_Identifier.SPECULAR_IOR: 0
            }

        elif bl_idname == 'ShaderNodeSubsurfaceScattering':
            pbr = {
                'Base Color': self.get_input('Color'),

                # Socket_Identifier.SUBSURFACE: self.get_input('Scale'),
                # 'Subsurface Radius': self.get_input('Radius'),

                #'Texture Blur': self.get_input('Texture Blur'),
                #'Sharpness': self.get_input('Sharpness'),

                'Normal': self.get_input('Normal', True),
                'Attributes': {'falloff': self.falloff},

                'Roughness': 1,
                # Socket_Identifier.SPECULAR_IOR: 0,
            }

            if bpy.app.version < (4, 0, 0):
                pbr['Subsurface Color'] = self.get_input('Color')

            pbr[Socket_Identifier.SUBSURFACE] = 1.0

            scale = self.get_input('Scale') # Subsurface
            radius = self.get_input('Radius') # Subsurface Radius

            if isinstance(scale, _Shader_Socket_Wrapper) or isinstance(radius, _Shader_Socket_Wrapper):
                vector_math = radius.insert_new('ShaderNodeVectorMath', operation = 'MULTIPLY')

                vector_math[0] = radius
                vector_math[1] = scale

                pbr['Subsurface Radius'] = vector_math.outputs[0]
            else:
                pbr['Subsurface Radius'] = (radius[0] * scale, radius[1] * scale, radius[2] * scale)

            return pbr

        elif bl_idname == 'ShaderNodeBsdfHairPrincipled': # not tested, just don't error
            return {
                'Base Color': self.get_input('Color'),
                'Roughness': self.get_input('Roughness'),
                Socket_Identifier.CLEARCOAT: self.get_input('Coat'),
                'IOR': self.get_input('IOR'),
                # ...
            }

        elif bl_idname == 'ShaderNodeBsdfHair': # not tested, just don't error
            return {
                'Base Color': self.get_input('Color'),
                'Roughness': self.get_input('RoughnessU'),
                'Tangent': self.get_input('Tangent', socket_only = True),
                # ...
            }


        if bl_idname in SHADER_OUTPUTTING_NODES:
            raise NotImplementedError(f"The node type is yet supported: {bl_idname}")
        else:
            raise ValueError(f"The node type is not shader outputting: {bl_idname}")


    def get_pbr_socket(self, map_type):
        if map_type == 'albedo':
            return self.inputs['Base Color']
        elif map_type == 'ambient_occlusion':
            pass
        elif map_type == 'bump':
            bump = self.inputs['Normal'].new('ShaderNodeBump')
            return bump.inputs['Height']
        elif map_type == 'diffuse':
            return self.inputs['Base Color']
        elif map_type == 'displacement':
            pass
        elif map_type == 'emissive':
            return self.inputs[Socket_Identifier.EMISSION]
        elif map_type == 'gloss':
            invert = self.inputs['Roughness'].new('ShaderNodeInvert')
            return invert.inputs['Color']
        elif map_type == 'metallic':
            return self.inputs['Metallic']
        elif map_type == 'normal':
            normal_map = self.inputs['Normal'].new('ShaderNodeNormalMap')
            return normal_map.inputs['Color']
        elif map_type == 'opacity':
            return self.inputs['Alpha']
        elif map_type == 'roughness':
            return self.inputs['Roughness']
        elif map_type == 'specular':
            return self.inputs[Socket_Identifier.SPECULAR_IOR]


    def convert_to_principled_bsdf(self):

        if self.be('ShaderNodeBsdfPrincipled'):
            return self

        if not self.be(SHADER_OUTPUTTING_NODES):
            raise ValueError(f'This node cannot be converted to Principled BSDF: {self.__repr__()}')

        principled_node = self.tree.new('ShaderNodeBsdfPrincipled')
        principled_node.location = self.location

        for socket in self.outputs[0].connections.copy():
            principled_node.outputs[0].join(socket, move = False)

        principled_node.set_inputs(self.get_principled_inputs())

        self.delete()

        return principled_node


    def copy(self):

        node_copy = self.tree.new(self.bl_idname)

        for attr in dir(node_copy.bl_node):

            if attr.startswith('_'):
                continue

            try:
                if node_copy.bl_node.is_property_readonly(attr):
                    continue
            except TypeError:
                continue

            setattr(node_copy.bl_node, attr, getattr(self.bl_node, attr))


        node_copy.set_inputs({input.identifier: self.get_input(input.identifier) for input in self.inputs})

        return node_copy



class Shader_Tree_Wrapper(_Tree_Wrapper[_Shader_Node_Wrapper, _Shader_Socket_Wrapper, bpy.types.ShaderNodeTree, bpy.types.ShaderNode], bpy.types.ShaderNodeTree if typing.TYPE_CHECKING else object):

    _socket_class = _Shader_Socket_Wrapper
    _node_class = _Shader_Node_Wrapper


    if bpy.app.version >= (2, 80, 0):
        @property
        def output(self) -> typing.Optional[_Shader_Node_Wrapper]:
            for target in ('ALL', 'CYCLES', 'EEVEE'):
                active_output = self.bl_tree.get_output_node(target)
                if active_output:
                    return self[active_output]
    else:
        @property
        def output(self) -> typing.Optional[_Shader_Node_Wrapper]:

            for bl_node in self.bl_tree.nodes:

                if bl_node.bl_idname != 'ShaderNodeOutputMaterial':
                    continue

                if bl_node.is_active_output:
                    return self[bl_node]


    @property
    def surface_input(self):
        """ Return the material's `Surface` socket. """
        return self.output.inputs['Surface']


    if bpy.app.version >= (2, 80, 0):
        @property
        def is_material(self):
            return self.bl_tree.bl_idname == 'ShaderNodeTree' and self.bl_tree.is_embedded_data
    else:
        @property
        def is_material(self):
            return any(material.node_tree == self.bl_tree  for material in bpy.data.materials)


    @property
    def root(self):
        if self.is_material:
            return self.output
        else:
            for node in self.get_by_bl_idname('NodeGroupOutput'):
                if node.is_active_output:
                    return node
        return None


    def get_height_input(self) -> _Shader_Socket_Wrapper:
        output = self.output

        displacement = output['Displacement']
        if displacement.be('ShaderNodeDisplacement'):
            return displacement.inputs['Height']

        displacement = output.inputs['Displacement'].new('ShaderNodeDisplacement', 'Displacement')
        displacement.space = 'WORLD'
        x, y = output.location
        displacement.location = (x, y - 150)

        return displacement.inputs['Height']


    def find_free_principled(self, create = False, ignore_inputs = False) -> _Shader_Node_Wrapper:

        active_node = self.active_node
        if active_node and active_node.be('ShaderNodeBsdfPrincipled') and not active_node.has_inputs:
            return active_node

        principled_nodes = self.get_by_type('BSDF_PRINCIPLED')

        for node in principled_nodes:

            if not node.select:
                continue

            if not ignore_inputs and node.has_inputs:
                continue

            return node

        if self.output:
            for node in self.output.descendants:

                if not node.be('ShaderNodeBsdfPrincipled'):
                    continue

                if not ignore_inputs and node.has_inputs:
                    continue

                return node

        for node in principled_nodes:

            if not ignore_inputs and node.has_inputs:
                continue

            return node

        if create:
            return self.new('ShaderNodeBsdfPrincipled')

        return None


    def convert_to_pbr(self):
        """
        Destructive conversion to use only one Principled BSDF node for the shader surface input.

        #### This function rebuilds the wrapper. Do not use any existed sub wrappers after calling it as they are invalid.
        """

        if not self.is_material:
            raise ValueError('Only for materials.')

        material_output = self.output
        if not material_output:
            material_output = self.new('ShaderNodeOutputMaterial')
            material_output.is_active_output = True

        # remove all muted nodes
        self.delete_nodes_with_reconnect([node for node in self.surface_input.descendants if node.mute])


        # ungroup all node groups that have shader sockets
        def get_node_group_with_shader_sockets(nodes: typing.List[_Shader_Node_Wrapper]):

            groups = []

            for node in nodes:

                if not node.be('ShaderNodeGroup'):
                    continue

                if not (any(input.be('NodeSocketShader') for input in node.inputs) or any(output.be('NodeSocketShader') for output in node.outputs)):
                    continue

                groups.append(node)

            return groups


        groups = get_node_group_with_shader_sockets(self.surface_input.descendants)
        while groups:
            self.ungroup(groups)
            groups = get_node_group_with_shader_sockets(self.surface_input.descendants)


        # remove all muted and NodeReroute nodes that are between shader sockets
        mute_nodes = set()
        for node in self.surface_input.descendants:
            if node.be(SHADER_OUTPUTTING_NODES):
                mute_nodes.update(node for node in node.ancestors if node.be('NodeReroute') or node.mute)

        self.delete_nodes_with_reconnect(mute_nodes)


        # leave mix shader factor markers
        # see label_mix_shader_nodes
        for node in self.surface_input.descendants:
            if node.be('ShaderNodeMixShader') and node.inputs[0].connections:
                marker = node.inputs[0].connections[0].insert_new('ShaderNodeVectorMath')
                marker.label = 'BC_PRE_BAKE_TARGET'


        surface_input = self.surface_input

        # empty shader input to zero value
        if not surface_input.connections:
            surface_input.new('ShaderNodeValue').outputs[0].set_default_value(0)

        for node in surface_input.descendants:
            for input in node.inputs:
                if input.be('NodeSocketShader') and not input.connections:
                    input.new('ShaderNodeValue').outputs[0].set_default_value(0)

        # join non shader output to shader input with ShaderNodeEmission
        for node in surface_input.descendants:
            for output_socket in node.outputs:
                for input_socket in output_socket.connections:
                    if input_socket.be('NodeSocketShader') and not output_socket.be('NodeSocketShader'):
                        output_socket.new('ShaderNodeEmission').outputs[0].join(input_socket, move = False)

        # convert all shader nodes to ShaderNodeBsdfPrincipled
        for node in surface_input.descendants:
            if node.be(SHADER_OUTPUTTING_NODES) and not node.be(SHADER_BLENDING_NODES):
                bl_idname = node.bl_idname
                node = node.convert_to_principled_bsdf()
                node.label = bl_idname

        # make every principled bsdf unique
        for node in surface_input.descendants:

            if not node.be('ShaderNodeBsdfPrincipled'):
                 continue

            for socket in node.outputs[0].connections[1:]:
                node.copy().outputs[0].join(socket)


        # pre-multiply emissions, solves an issues when mixing them
        for node in surface_input.descendants:

            if not node.be('ShaderNodeBsdfPrincipled'):
                continue

            if not 'Emission Strength' in node.inputs.identifiers:
                continue

            if (
                    (
                        not node.inputs['Emission Strength'].connections
                        and
                        node.inputs['Emission Strength'].is_close(0)
                    )
                    or
                    (
                        not node.inputs[Socket_Identifier.EMISSION].connections
                        and
                        node.inputs[Socket_Identifier.EMISSION].is_close((0, 0, 0))
                    )
                ):

                node.inputs[Socket_Identifier.EMISSION].disconnect()
                node.inputs[Socket_Identifier.EMISSION].set_default_value((1, 1, 1, 1))
                node.inputs['Emission Strength'].disconnect()
                node.inputs['Emission Strength'].set_default_value(0)
            else:
                emission_socket = node.inputs[Socket_Identifier.EMISSION]
                emission_source_socket = emission_socket.connections[0]

                mix_node = emission_socket.new('ShaderNodeVectorMath', operation = 'MULTIPLY')
                mix_node[0] = emission_source_socket
                mix_node[1] = node.inputs['Emission Strength'].as_output()

                node.inputs['Emission Strength'].disconnect()
                node.inputs['Emission Strength'].set_default_value(1)


        # merge descendants of ShaderNodeMixShader and ShaderNodeAddShader nodes
        for mix_add in reversed([node for node in surface_input.descendants if node.be(SHADER_BLENDING_NODES)]):


            principled_1 = mix_add['Shader']
            principled_2 = mix_add['Shader_001']

            labels_set = {principled_1.label, principled_2.label}


            def is_only_one(*bl_idnames):
                return sum(len([name for name in labels_set if name == bl_idname]) for bl_idname in bl_idnames) == 1


            def get_in_order(bl_idname):
                if principled_1.label == bl_idname:
                    return principled_1, principled_2
                else:
                    return principled_2, principled_1


            def is_any(*bl_idnames):
                return not labels_set.isdisjoint(bl_idnames)


            def finish(remain: _Shader_Node_Wrapper, delete: typing.Optional[_Shader_Node_Wrapper] = None):

                for input_socket in mix_add.outputs[0].connections.copy():
                    input_socket.join(remain.outputs[0], move = False)

                mix_add.delete()

                remain.label = 'ShaderNodeBsdfPrincipled'

                if delete is not None:
                    delete.delete()


            if mix_add.be('ShaderNodeMixShader'):

                # mixed with itself
                if principled_1 is principled_2:
                    finish(principled_1)
                    continue

                # only one input is used
                if not mix_add.inputs[0].connections:
                    if mix_add.inputs[0].is_close(0):
                        finish(principled_1, principled_2)
                        continue
                    elif mix_add.inputs[0].is_close(1):
                        finish(principled_2, principled_1)
                        continue


                # simple ShaderNodeBsdfTransparent
                def is_simple_transparent_mix():

                    # TODO: double ShaderNodeBsdfTransparent nodes

                    if not is_only_one('ShaderNodeBsdfTransparent'):
                        return False

                    transparent_node, other_node = get_in_order('ShaderNodeBsdfTransparent')

                    is_default_transparent = not transparent_node.inputs['Base Color'].connections and transparent_node.inputs['Base Color'].is_close((1, 1, 1))
                    no_principled_alpha_input = not other_node.inputs['Alpha'].connections and other_node.inputs['Alpha'].is_close(1)

                    return is_default_transparent and no_principled_alpha_input


                if is_simple_transparent_mix():

                    transparent_node, other_node = get_in_order('ShaderNodeBsdfTransparent')

                    other_node['Alpha'] = mix_add.get_input(0)

                    finish(other_node, transparent_node)
                    continue


                # simple Diffuse and Glossy mixed with Fresnel
                def is_simple_fresnel_mix():

                    if labels_set != {'ShaderNodeBsdfDiffuse', 'ShaderNodeBsdfGlossy'}:
                        return False

                    descendants_bl_idnames = {node.bl_idname for node in mix_add.inputs[0].descendants}

                    if descendants_bl_idnames.isdisjoint(('ShaderNodeLayerWeight', 'ShaderNodeFresnel')):
                        return False

                    if any(name.startswith('ShaderNodeTex') for name in descendants_bl_idnames):
                        return False

                    return True


                if is_simple_fresnel_mix():

                    diffuse_node, glossy_node = get_in_order('ShaderNodeBsdfDiffuse')

                    for identifier in ('Roughness', Socket_Identifier.SPECULAR_IOR):
                        diffuse_node[identifier] = glossy_node.get_input(identifier)

                    for identifier in ('Metallic', 'Base Color'):
                        glossy_node[identifier] = diffuse_node.get_input(identifier)


                # Subsurface Scattering mix
                if is_only_one('ShaderNodeSubsurfaceScattering') and not is_any('ShaderNodeBsdfPrincipled'):

                    scattering_node, other_node = get_in_order('ShaderNodeSubsurfaceScattering')
                    scattering_node['Roughness'] = other_node.get_input('Roughness')

                    if bpy.app.version < (4, 0, 0):
                        other_node['Subsurface Color'] = scattering_node.get_input('Subsurface Color')


                for identifier in principled_1.inputs.keys():

                    if principled_1.inputs[identifier].is_equal(principled_2.inputs[identifier]):
                        continue

                    socket_1 = principled_1.inputs[identifier].as_output()
                    socket_2 = principled_2.inputs[identifier].as_output()

                    mix_node = principled_1.inputs[identifier].new('ShaderNodeMixRGB', label = identifier)
                    mix_node[0] = mix_add.get_input(0)
                    mix_node[1] = socket_1
                    mix_node[2] = socket_2

                    if identifier in ('Normal', 'Clearcoat Normal', 'Tangent'):
                        mix_node.outputs[0].insert_new('ShaderNodeVectorMath', operation = 'NORMALIZE')


            elif mix_add.be('ShaderNodeAddShader'):


                # added emission
                if is_only_one('ShaderNodeEmission', 'ShaderNodeBackground') and is_any('ShaderNodeBsdfDiffuse', 'ShaderNodeBsdfGlossy'):

                    emission_node, other_node = get_in_order('ShaderNodeEmission')

                    for identifier in (Socket_Identifier.EMISSION, 'Emission Strength'):
                        other_node[identifier] = emission_node.get_input(identifier)

                    finish(other_node, emission_node)
                    continue


                for identifier in principled_1.inputs.keys():

                    socket_1 = principled_1.inputs[identifier].as_output()
                    socket_2 = principled_2.inputs[identifier].as_output()

                    mix_node = principled_1.inputs[identifier].new('ShaderNodeMixRGB', blend_type = 'ADD', label = identifier)
                    mix_node[0] = 1
                    mix_node[1] = socket_1
                    mix_node[2] = socket_2

                    if identifier in ('Normal', 'Clearcoat Normal', 'Tangent'):
                        mix_node.outputs[0].insert_new('ShaderNodeVectorMath', operation = 'NORMALIZE')


            finish(principled_1, principled_2)


        assert self.output['Surface'].be('ShaderNodeBsdfPrincipled')


    def delete_nodes_with_reconnect(self, nodes: typing.Iterable[_Shader_Node_Wrapper]):
        """
        #### This function rebuilds the wrapper. Do not use any existed sub wrappers after calling it.
        """

        if not nodes:
            return

        # ValueError: Area.path_from_id() does not support path creation for this type

        bl_nodes = {node.bl_node for node in nodes}
        bl_tree = self.bl_tree

        with bpy_context.Bpy_State() as state:

            state.set(bl_tree, 'tag', True)  # ensure the first index is the tree

            for node in bl_tree.nodes:

                if node in bl_nodes:
                    node.select = True  # will be deleted
                else:
                    state.set(node, 'select', False)

            area = bpy.data.window_managers[0].windows[0].screen.areas[0]
            state.set(area, 'type', 'NODE_EDITOR')

            if bpy.app.version >= (2, 80):
                state.set(area, 'ui_type', 'ShaderNodeTree')

            space_data = area.spaces[0]
            state.set(space_data, 'node_tree', bl_tree)

            override = dict(
                area = area,
                space_data = space_data,
                selected_nodes = list(bl_nodes),
            )

            bpy_context.call(override, bpy.ops.node.delete_reconnect)

            self.__init__(state.get_bpy_data(0))


    def ungroup(self, nodes: typing.List[_Shader_Node_Wrapper]):
        """
        Ungroup ShaderNodeGroup nodes.

        #### This function rebuilds the wrapper. Do not use any previous sub wrappers after calling it.
        """

        if not nodes:
            return

        for bl_node in nodes:

            if bl_node.bl_idname != 'ShaderNodeGroup':
                continue

            for input in bl_node.inputs:

                if input.connections:
                    continue

                input.get_default_value_as_node()

        bl_nodes = {node.bl_node for node in nodes if node.be('ShaderNodeGroup')}
        bl_tree = self.bl_tree

        with bpy_context.Bpy_State() as state:

            state.set(bl_tree, 'tag', True)  # ensure the first index is the tree

            area = bpy.data.window_managers[0].windows[0].screen.areas[0]
            state.set(area, 'type', 'NODE_EDITOR')

            if bpy.app.version >= (2, 80):
                state.set(area, 'ui_type', 'ShaderNodeTree')

            space_data = area.spaces[0]
            state.set(space_data, 'node_tree', bl_tree)

            override = dict(
                area = area,
                space_data = space_data,
                # selected_nodes = list(bl_nodes),
            )

            for bl_node in bl_tree.nodes:
                bl_node.select = bl_node in bl_nodes

            bl_tree.nodes.active = bl_node

            # TODO: check changed behavior in old versions, it only ungroups the active node
            bpy_context.call(override, bpy.ops.node.group_ungroup)

            self.__init__(state.get_bpy_data(0))


    def reset_nodes(self):
        """
        Delete all nodes and add the default Principled node.
        """

        self.bl_tree.nodes.clear()

        self.__init__(self.bl_tree)

        output = self.new('ShaderNodeOutputMaterial')
        output.name = 'Material Output'
        output.location = (300.0, 300.0)

        principled = output.inputs[0].new('ShaderNodeBsdfPrincipled')
        principled.name = 'Principled BSDF'
        principled.location = (10.0, 300.0)


class _Compositor_Socket_Wrapper(_Socket_Wrapper['_Compositor_Node_Wrapper']):
    pass


class _Compositor_Node_Wrapper(_Node_Wrapper['Compositor_Tree_Wrapper', _Compositor_Socket_Wrapper, bpy.types.CompositorNodeTree, bpy.types.CompositorNode], bpy.types.CompositorNode if typing.TYPE_CHECKING else object):

    outputs: _Sockets_Wrapper[_Compositor_Socket_Wrapper, '_Compositor_Node_Wrapper']
    inputs: _Sockets_Wrapper[_Compositor_Socket_Wrapper, '_Compositor_Node_Wrapper']


class Compositor_Tree_Wrapper(_Tree_Wrapper[_Compositor_Node_Wrapper, _Compositor_Socket_Wrapper, bpy.types.CompositorNodeTree, bpy.types.CompositorNode], bpy.types.CompositorNodeTree if typing.TYPE_CHECKING else object):

    _socket_class = _Compositor_Socket_Wrapper
    _node_class = _Compositor_Node_Wrapper


    @classmethod
    def from_scene(cls, scene: bpy.types.Scene):
        """
        Compositor: remove scene.node_tree from Python API
        https://projects.blender.org/blender/blender/pulls/143619
        """

        if bpy.app.version < (5, 0):
            return cls(scene.node_tree)
        else:

            tree = bpy.data.node_groups.get('__bc_compositor')
            if not tree:
                tree = bpy.data.node_groups.new('__bc_compositor', 'CompositorNodeTree')

            scene.compositing_node_group = tree

            return cls(tree)
