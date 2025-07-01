""" All sorts of context managers. """


import traceback
import typing
import uuid
import operator
import json
import re
import math

import bpy
from bpy import utils as b_utils
import mathutils

from . import bpy_node
from . import utils
from . import bpy_utils

if typing.TYPE_CHECKING:
    from . import tool_settings


TOPOLOGY_CHANGING_MODIFIER_TYPES = {
    'ARRAY',
    'BEVEL',
    'BOOLEAN',
    'BUILD',
    'DECIMATE',
    'EDGE_SPLIT',
    'NODES',
    'MASK',
    'MIRROR',
    'MULTIRES',
    'REMESH',
    'SCREW',
    'SKIN',
    'SOLIDIFY',
    'SUBSURF',
    'TRIANGULATE',
    'VOLUME_TO_MESH',
    'WELD',
    'WIREFRAME',
    'EXPLODE',
    'FLUID',
    'OCEAN',
    'PARTICLE_INSTANCE'
}


PRINT_CONTEXT_CHANGES = False



def format_call_error(name, reason, func, args, kwargs, override):
    return "\n".join([name, f"reason: {reason}", f"func: {repr(func)}", f"args: {args}", f"kwargs: {kwargs}", f"override: {override}"])


def call(override: typing.Dict[str, typing.Any], func: typing.Callable, *args, can_be_canceled = False, **kwargs):

    try:
        if bpy.app.version > (3,2,0):
            with bpy.context.temp_override(**override):
                result = func(*args, **kwargs)
        else:
            result =  func(override, *args, **kwargs)

    except Exception as e:
        raise Exception(format_call_error('ERROR', e, func, args, kwargs, override)) from e

    if not can_be_canceled and 'CANCELLED' in result:
        raise Exception(format_call_error('CANCELLED', 'unknown', func, args, kwargs, override))

    return result


def get_view3d():
    for window_manager in bpy.data.window_managers:
        for window in window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'VIEW_3D':
                    for region in area.regions:
                        if region.type == 'WINDOW':
                            return dict(window=window, workspace=window.workspace, screen=window.screen, area=area, region=region)

    raise Exception('View3D context not found.')


def call_in_view3d(func: typing.Callable, *args, **kwargs):
    return call(get_view3d(), func, *args, **kwargs)


def call_with_object_override(active_object: 'bpy.types.Object', objects: typing.List['bpy.types.Object'], func: typing.Callable, *args, can_be_canceled = False, **kwargs):

    if not active_object in objects:
        objects.append(active_object)

    override = dict(
        selectable_objects = objects,
        selected_objects = objects,
        selected_editable_objects = objects,
        editable_objects = objects,
        visible_objects = objects,
        active_object = active_object,
        object = active_object
    )

    return call(override, func, *args, can_be_canceled = can_be_canceled, **kwargs)


def get_local_view_objects(context: bpy.types.Context):
    """
    Regression: object.local_view_get and object.visible_in_viewport_get() always returns False
    https://developer.blender.org/T95197
    """

    space_view_3d = context.space_data

    if type(space_view_3d) != bpy.types.SpaceView3D: # will crash if space_view_3d is None
        raise TypeError(f'The context is incorrect. For context.space_data expected a SpaceView3D type, not {type(space_view_3d)}')

    depsgraph = context.evaluated_depsgraph_get()

    if bpy.data.objects and hasattr(bpy.data.objects[0], 'visible_in_viewport_get'):
        return [object for object in bpy.data.objects if object.evaluated_get(depsgraph).visible_in_viewport_get(space_view_3d)]
    else:
        return [object for object in bpy.data.objects if object.evaluated_get(depsgraph).local_view_get(space_view_3d)]


class State:

    print_color_code = utils.get_color_code(256,0,128, 0,0,0)

    def __init__(self, settings: typing.Optional[typing.List[typing.Tuple[typing.Any, str, typing.Any]]] = None, print = PRINT_CONTEXT_CHANGES):
        self.init_state: typing.List[tuple[object, str, typing.Any]] = []
        self.pre_settings = settings
        self.print = print


    def __enter__(self):

        if  self.pre_settings is not None:
            for object, attr, value in self.pre_settings:
                self.set(object, attr, value)

        return self


    def set(self, object: object, name: str, value):
        self.init_state.append((object, name, getattr(object, name)))
        setattr(object, name, value)
        if self.print:
            utils.print_in_color(self.print_color_code, f"{repr(object)}.{name} = {repr(value)}")


    def __exit__(self, type, value, traceback):
        for object, name, value in reversed(self.init_state):
            setattr(object, name, value)


def del_scene_prop(key: str):
    for scene in bpy.data.scenes:
        if key in scene.keys():
            del scene[key]



def get_embedded_id_data_and_path(object: bpy.types.bpy_struct):
    """
    #129393 - Python API: Can not assign bpy.types.Collection as PointerProperty - blender - Blender Projects
    https://projects.blender.org/blender/blender/issues/129393

    PointerProperty for NodeTree broke - Coding / Python Support - Blender Artists Community
    https://blenderartists.org/t/pointerproperty-for-nodetree-broke/1549830
    """

    id_data = object.id_data

    if isinstance(id_data, bpy.types.ShaderNodeTree):

        name = re.match(r"bpy\.data\.materials\['(.+?)'\]\.node_tree", repr(object)).group(1)
        material = bpy.data.materials[name]

        if object is id_data:
            return material, 'node_tree'
        else:
            return material, f'node_tree.{object.path_from_id()}'

    elif isinstance(id_data, bpy.types.CompositorNodeTree):

        name = re.match(r"bpy\.data\.scenes\['(.+?)'\]\.node_tree", repr(object)).group(1)
        scene = bpy.data.scenes[name]

        if object is id_data:
            return scene, 'node_tree'
        else:
            return scene, f'node_tree.{object.path_from_id()}'

    else:
        raise NotImplementedError(repr(object))


def get_id_data_and_path(object: typing.Union[bpy.types.bpy_struct, bpy.types.bpy_prop_array, bpy.types.bpy_prop_collection]):

    id_data: bpy.types.ID = object.id_data

    if id_data.is_embedded_data:
        return get_embedded_id_data_and_path(object)
    else:
        if object == id_data:
            return id_data, ''
        else:
            if isinstance(object, bpy.types.NlaTrack):
                return id_data, f'animation_data.nla_tracks["{b_utils.escape_identifier(object.name)}"]'
            elif isinstance(object, bpy.types.FCurve):
                # TODO: this may not be adequate, try search by data_path
                index = list(id_data.animation_data.drivers).index(object)
                return id_data, f'animation_data.drivers[{index}]'
            else:
                return id_data, object.path_from_id()


class Bpy_State_Item(bpy.types.PropertyGroup):

    attr_name: bpy.props.StringProperty()

    object_id_data: bpy.props.PointerProperty(type = bpy.types.ID)
    object_path_from_id: bpy.props.StringProperty()

    init_value_id_data: bpy.props.PointerProperty(type = bpy.types.ID)
    init_value_path_from_id: bpy.props.StringProperty()

    # ⚓ T51096 path_from_id does not work on subproperties of a custom node
    # https://developer.blender.org/T51096


    @property
    def target(self):

        if self.object_id_data is None:
            if '_target_repr' in self.keys():
                raise Exception(f"The underling id data has been removed: {self['_target_repr']}")
            else:
                return self['_target']
        else:
            if self.object_path_from_id:
                return self.object_id_data.path_resolve(self.object_path_from_id)
            else:
                return self.object_id_data


    @target.setter
    def target(self, object):

        if isinstance(object, (bpy.types.bpy_struct, bpy.types.bpy_prop_array, bpy.types.bpy_prop_collection)):
            self.object_id_data, self.object_path_from_id = get_id_data_and_path(object)
            self['_target_repr'] = repr(self.object_id_data)
        else:
            self['_target'] = object


    @property
    def init_value(self):

        if self.init_value_id_data is None:
            if '_value_repr' in self.keys():
                raise Exception(f"The underling value id data has been removed: {self['_value_repr']}")
            else:
                return self.get('_init_value')
        else:
            if self.init_value_path_from_id:
                return self.init_value_id_data.path_resolve(self.init_value_path_from_id)
            else:
                return self.init_value_id_data


    @init_value.setter
    def init_value(self, value):

        if isinstance(value, (bpy.types.bpy_struct, bpy.types.bpy_prop_array, bpy.types.bpy_prop_collection)):
            self.init_value_id_data, self.init_value_path_from_id = get_id_data_and_path(value)
            self['_value_repr'] = repr(self.init_value_id_data)
        else:
            self['_init_value'] = value



try:
    bpy.utils.unregister_class(Bpy_State_Item)
except RuntimeError:
    pass
finally:
    bpy.utils.register_class(Bpy_State_Item)


class Bpy_State:

    print_color = utils.get_color_code(256,128,0, 0,0,0)
    error_color = utils.get_color_code(222,93,84, 0,0,0)


    @property
    def items(self) -> bpy.types.CollectionProperty:
        return getattr(bpy.context.scene, self.collection_name)


    def __init__(self, settings: typing.Optional[typing.List[typing.Tuple[bpy.types.bpy_struct, str, typing.Any]]] = None, except_exit_errors = False, print = PRINT_CONTEXT_CHANGES):
        self.collection_name = 'Bpy_Struct_State_collection_' + uuid.uuid1().hex
        setattr(bpy.types.Scene, self.collection_name, bpy.props.CollectionProperty(type = Bpy_State_Item))
        self.except_exit_errors = except_exit_errors

        self.pre_settings = settings

        self.print = print


    def __enter__(self):

        if self.pre_settings is not None:
            for object, attr, value in self.pre_settings:
                self.set(object, attr, value)

        return self


    def set(self, object: bpy.types.bpy_struct, name: str, value):

        init_value = getattr(object, name)

        pointer: Bpy_State_Item = self.items.add()  # type: ignore
        pointer.target = object
        pointer.attr_name = name
        pointer.init_value = init_value

        setattr(object, name, value)

        if self.print:
            utils.print_in_color(self.print_color, f"{repr(object)}.{name} = {repr(value)}")


    def __exit__(self, exc_type, exc_value, exc_traceback):
        pointer: Bpy_State_Item

        if self.except_exit_errors or exc_type:
            for pointer in reversed(self.items.values()):
                try:
                    setattr(pointer.target, pointer.attr_name, pointer.init_value)
                except Exception:
                    utils.print_in_color(self.error_color, traceback.format_exc())
        else:
            for pointer in reversed(self.items.values()):
                setattr(pointer.target, pointer.attr_name, pointer.init_value)

        del_scene_prop(self.collection_name)
        delattr(bpy.types.Scene, self.collection_name)


class Bpy_Reference_Base:

    def __init__(self):
        import uuid
        self._collection_name = 'Bpy_Reference_collection_' + uuid.uuid1().hex
        setattr(bpy.types.Scene, self._collection_name, bpy.props.CollectionProperty(type = Bpy_State_Item))

    @property
    def items(self) -> typing.Union[bpy.types.CollectionProperty, typing.List[Bpy_State_Item]]:
        return getattr(bpy.context.scene, self._collection_name)

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        del_scene_prop(self._collection_name)
        delattr(bpy.types.Scene, self._collection_name)


class Bpy_Reference_Dict(Bpy_Reference_Base):

    def __init__(self):
        super().__init__()
        self._item_map = {}
        self._item_index = 0

    def __getitem__(self, key: str):
        pointer: Bpy_State_Item = self.items[self._item_map[key]]
        return pointer.target

    def __setitem__(self, key: str, value: bpy.types.bpy_struct):
        pointer: Bpy_State_Item = self.items.add()  # type: ignore
        pointer.name = key
        pointer.target = value

        self._item_map[key] = self._item_index
        self._item_index += 1


class Bpy_Reference_List(Bpy_Reference_Base):

    def __init__(self):
        super().__init__()
        self._index = 0

    def append(self, value: bpy.types.bpy_struct):
        pointer: Bpy_State_Item = self.items.add()  # type: ignore
        pointer.name = str(self._index)
        pointer.target = value

        self._index += 1

        return self._index - 1

    def extend(self, values: typing.Iterable):
        for value in values:
            self.append(value)

    def __getitem__(self, index: int):
        return self.items[index].target

    def __iter__(self):
        for item in self.items:
            yield item.target



class Bake_Settings(Bpy_State):


    def __init__(self, bake_settings: 'tool_settings.Bake'):
        super().__init__()
        self.bake_settings = bake_settings


    def __enter__(self):
        super().__enter__()

        context = bpy.context
        cycles = context.scene.cycles  # type: typing.Any
        render = context.scene.render

        self.set(render, 'engine', 'CYCLES')
        self.set(cycles, 'bake_type', 'EMIT')
        self.set(render.bake, 'use_clear', False)
        self.set(render.bake, 'margin', self.bake_settings.margin)

        if not self.bake_settings.use_global_bake_settings:
            return

        self.set(render, 'use_bake_multires', False)
        self.set(cycles, 'samples', self.bake_settings.samples)

        self.set(render, 'use_compositing', True)
        self.set(render, 'use_sequencer', False)

        self.set(render.bake, 'use_selected_to_active', False)

        self.set(context.view_layer, 'pass_alpha_threshold', 0.5)

        tile_size = max(self.bake_settings._actual_width, self.bake_settings._actual_height)

        blender_version_dependent_properties = [
            (render.bake, 'margin_type', self.bake_settings.margin_type),
            (cycles, 'use_denoising', False),
            (cycles, 'adaptive_min_samples', 0),
            (cycles, 'use_adaptive_sampling', False),
            (cycles, 'use_auto_tile', True),
            (cycles, 'tile_size', tile_size),
            (render.bake, 'target', 'IMAGE_TEXTURES'), # ? check
            (render, 'tile_x', tile_size),
            (render, 'tile_y', tile_size),
            (cycles, 'time_limit', 0),
            (cycles, 'sampling_pattern', 'TABULATED_SOBOL'),  # otherwise causes strange square artifacts that break the denoiser
        ]

        for property in blender_version_dependent_properties:
            try:
                self.set(*property)
            except (AttributeError, TypeError):
                pass

        self.set(render, 'use_persistent_data', True)
        self.set(cycles, 'light_sampling_threshold', 0)
        self.set(cycles, 'sample_clamp_direct', 0)
        self.set(cycles, 'sample_clamp_indirect', 0)
        self.set(cycles, 'blur_glossy', 0)

        self.set(cycles, 'caustics_reflective', False)
        self.set(cycles, 'caustics_refractive', False)

        self.set(cycles, 'max_bounces', 0)
        self.set(cycles, 'diffuse_bounces', 0)
        self.set(cycles, 'glossy_bounces', 0)
        self.set(cycles, 'transmission_bounces', 0)
        self.set(cycles, 'volume_bounces', 0)

        return self


class Global_Optimizations(State):

    @staticmethod
    def dummy_view_layer_update(_):
        return

    def __enter__(self):
        super().__enter__()

        self.set(bpy.context.preferences, 'use_preferences_save', False)
        self.set(bpy.context.preferences.edit, 'undo_steps', 0)
        self.set(bpy.context.preferences.edit, 'use_global_undo', False)

        if bpy.app.version >= (2, 93):
            self.set(bpy.ops._BPyOpsSubModOp, '_view_layer_update', self.dummy_view_layer_update)

        self.set(bpy_node, 'ALLOW_NODE_MOVE', False)

        return self


class Armature_Disabled(Bpy_State):

    def __init__(self, object: bpy.types.Object):
        super().__init__()
        self.object = object
        self.matrix_parent_inverse = None

    def __enter__(self):

        armatures: set[bpy.types.Object] = set()
        for modifier in self.object.modifiers:

            if not isinstance(modifier, bpy.types.ArmatureModifier):
                continue

            armature = modifier.object  # type: ignore
            if armature:
                armatures.add(armature)

        for object in bpy.data.objects:
            for modifier in object.modifiers:

                if not isinstance(modifier, bpy.types.ArmatureModifier):
                    continue

                if modifier.object in armatures:
                    self.set(modifier, 'show_viewport', False)
                    self.set(modifier, 'show_render', False)

            if object.parent and object.parent in armatures:
                self.matrix_parent_inverse = tuple(tuple(vec) for vec in object.matrix_parent_inverse)
                self.set(object, 'parent', None)

    def __exit__(self, type, value, traceback):

        pointer: Bpy_State_Item

        for pointer in reversed(self.items.values()):  # type: ignore
            setattr(pointer.target, pointer.attr_name, pointer.init_value)

            if isinstance(pointer.target, bpy.types.Object) and self.matrix_parent_inverse:
                pointer.target.matrix_parent_inverse = mathutils.Matrix(self.matrix_parent_inverse)

        delattr(bpy.types.Scene, self.collection_name)


class Temp_Image:

    uuid_key = 'blend_converter_uuid1_hex'

    def __init__(self, x, y):
        self.width = x
        self.height = y

    def __enter__(self):

        self.uuid_hex = uuid.uuid1().hex

        image = bpy.data.images.new(self.uuid_hex, width=self.width, height=self.height, float_buffer=True, is_data=True)
        image[self.uuid_key] = self.uuid_hex

        return image

    def __exit__(self, type, value, traceback):

        for image in list(bpy.data.images):
            if image.get(self.uuid_key) == self.uuid_hex:
                break
        else:
            raise Exception(f"Temp image not found: {self.uuid_hex}")

        bpy.data.images.remove(image, do_unlink=True)


class UV_Override:

    def __init__(self, material: bpy.types.Material, uv_image):
        self.material = material
        self.uv_image = uv_image

    def __enter__(self):

        def get_node_trees(starting_node_tree: bpy.types.ShaderNodeTree, node_trees: typing.Set[bpy.types.ShaderNodeTree] = None):
            if node_trees == None:
                node_trees = set()
            node_trees.add(starting_node_tree)
            for node in starting_node_tree.nodes:
                if node.bl_idname == 'ShaderNodeGroup' and node.node_tree != None:
                    get_node_trees(node.node_tree, node_trees)
            return node_trees

        node_trees = list(get_node_trees(self.material.node_tree))

        self.initial_links = {node_tree: [] for node_tree in node_trees}
        self.temp_nodes = {node_tree: [] for node_tree in node_trees}

        for node_tree in node_trees:
            nodes = node_tree.nodes
            links = node_tree.links

            uv_image_node = nodes.new('ShaderNodeTexImage')
            uv_image_node.image = self.uv_image
            uv_image_node.interpolation = 'Closest'

            self.temp_nodes[node_tree].append(uv_image_node)
            uv_output = uv_image_node.outputs[0]

            for link in links:
                node_type = link.from_node.type
                if node_type == 'UVMAP':
                    self.initial_links[node_tree].append((link.from_socket, link.to_socket))
                    links.new(uv_output, link.to_socket)
                elif node_type == 'TEX_COORD' and link.from_socket.name == 'UV':
                    self.initial_links[node_tree].append((link.from_socket, link.to_socket))
                    links.new(uv_output, link.to_socket)

            for node in [node for node in nodes if node.type == 'TEX_IMAGE' and node != uv_image_node and not node.inputs[0].links]:
                links.new(uv_output, node.inputs[0])

    def __exit__(self, type, value, traceback):
        for node_tree, initial_links in self.initial_links.items():
            links = node_tree.links
            for link in initial_links:
                links.new(link[0], link[1])

        for node_tree, temp_nodes in self.temp_nodes.items():
            nodes = node_tree.nodes
            for temp_node in temp_nodes:
                temp_node.image = None # fixes blender.exe image_acquire_ibuf EXCEPTION_ACCESS_VIOLATION crash
                nodes.remove(temp_node)


class Baking_Image_Node:

    def __init__(self, material: bpy.types.Material, image: bpy.types.Image):
        self.nodes = material.node_tree.nodes
        self.image = image

    def __enter__(self):
        image_node = self.nodes.new('ShaderNodeTexImage')
        image_node.image = self.image
        image_node.select = True
        self.initial_active_node = self.nodes.active
        self.nodes.active = image_node
        self.image_node = image_node

    def __exit__(self, type, value, traceback):
        self.nodes.remove(self.image_node)
        self.nodes.active = self.initial_active_node


class No_Active_Image:

    def __init__(self, material: bpy.types.Material):
        self.nodes = material.node_tree.nodes

    def __enter__(self):
        for node in self.nodes:
            node.select = False
        self.image_node = self.nodes.new('ShaderNodeTexImage')
        self.image_node.select = True
        self.initial_active_node = self.nodes.active
        self.nodes.active = self.image_node

    def __exit__(self, type, value, traceback):
        self.nodes.remove(self.image_node)
        self.nodes.active = self.initial_active_node


class Output_Override:


    def __init__(self, material: bpy.types.Material, target_socket_output: bpy.types.NodeSocketStandard):

        self.tree = bpy_node.Shader_Tree_Wrapper(material.node_tree)

        assert target_socket_output.is_output if target_socket_output else True, f"R cannel {target_socket_output} should be an output socket."
        self.target_socket_output = self.tree.get_socket_wrapper(target_socket_output)


    def __enter__(self):

        if self.tree.surface_input.connections:
            self.initial_output = self.tree.surface_input.connections[0]
        else:
            self.initial_output = None

        if self.target_socket_output.be('NodeSocketShader'):
            self.tree.surface_input.join(self.target_socket_output, move=False)
        else:
            self.tree.surface_input.new('ShaderNodeEmission').inputs[0].join(self.target_socket_output, move=False)


    def __exit__(self, type, value, traceback):
        self.tree.delete_new_nodes()

        if self.initial_output:
            self.initial_output.join(self.tree.surface_input, move = False)


class Output_Override_Combine_RGB:


    def __init__(self, material: bpy.types.Material, r: typing.Optional[bpy.types.NodeSocketStandard], g: typing.Optional[bpy.types.NodeSocketStandard], b: typing.Optional[bpy.types.NodeSocketStandard]):

        assert r.is_output if r else True, f'R cannel {r} should be an output socket.'
        assert g.is_output if g else True, f'G cannel {g} should be an output socket.'
        assert b.is_output if b else True, f'B cannel {b} should be an output socket.'

        self.tree = bpy_node.Shader_Tree_Wrapper(material.node_tree)

        self.r = self.tree.get_socket_wrapper(r) if r else None
        self.g = self.tree.get_socket_wrapper(g) if g else None
        self.b = self.tree.get_socket_wrapper(b) if b else None


    def __enter__(self):

        if self.tree.surface_input.connections:
            self.initial_output = self.tree.surface_input.connections[0]
        else:
            self.initial_output = None

        node = self.tree.surface_input.new('ShaderNodeEmission')

        combine_xyz = node.inputs[0].new('ShaderNodeCombineXYZ')

        if self.r:
            combine_xyz.inputs[0].join(self.r, False)
        if self.g:
            combine_xyz.inputs[1].join(self.g, False)
        if self.b:
            combine_xyz.inputs[2].join(self.b, False)


    def __exit__(self, type, value, traceback):
        self.tree.delete_new_nodes()

        if self.initial_output:
            self.initial_output.join(self.tree.surface_input, move = False)


class Output_Socket_World_Space_To_Tangent_Space:


    def __init__(self, material: bpy.types.Material, target_socket_output: bpy.types.NodeSocketStandard, uv_layer_name: str):

        assert target_socket_output.is_output, 'target_socket_output should be an output socket.'

        self.tree = bpy_node.Shader_Tree_Wrapper(material.node_tree)
        self.target_socket_output = self.tree.get_socket_wrapper(target_socket_output)
        self.uv_layer_name = uv_layer_name


    def __enter__(self):

        first_node = self.tree.new('ShaderNodeVectorMath', operation = 'ADD')
        first_node[1] = (0.5, 0.5, 0.5)

        node = first_node.inputs[0].new('ShaderNodeVectorMath', operation = 'MULTIPLY')
        node[1] = (0.5, 0.5, 0.5)

        combine_xyz = node.inputs[0].new('ShaderNodeCombineXYZ')

        dot_product_1 = combine_xyz.inputs[0].new('ShaderNodeVectorMath', 'Value', operation = 'DOT_PRODUCT')
        dot_product_2 = combine_xyz.inputs[1].new('ShaderNodeVectorMath', 'Value', operation = 'DOT_PRODUCT')
        dot_product_3 = combine_xyz.inputs[2].new('ShaderNodeVectorMath', 'Value', operation = 'DOT_PRODUCT')

        dot_product_1.inputs[0].join(self.target_socket_output, move=False)
        dot_product_2.inputs[0].join(self.target_socket_output, move=False)
        dot_product_3.inputs[0].join(self.target_socket_output, move=False)

        tangent = dot_product_1.inputs[1].new('ShaderNodeTangent')
        tangent.direction_type = 'UV_MAP'
        tangent.uv_map = self.uv_layer_name

        node = dot_product_2.inputs[1].new('ShaderNodeVectorMath', operation = 'MULTIPLY')

        attr_node = node.inputs[1].new('ShaderNodeAttribute')
        attr_node.attribute_type = 'GEOMETRY'
        attr_node.attribute_name = self.uv_layer_name + '.tangent_sign'

        node = node.inputs[0].new('ShaderNodeVectorMath', operation = 'CROSS_PRODUCT')

        node.inputs[1].join(tangent.outputs[0], move=False)

        geometry = node.inputs[0].new('ShaderNodeNewGeometry', 'Normal')
        geometry.outputs['Normal'].join(dot_product_3.inputs[1])

        return first_node.outputs[0].bl_socket


    def __exit__(self, type, value, traceback):
        self.tree.delete_new_nodes()


class Output_Socket_Ambient_Occlusion:

    def __init__(self, material: bpy.types.Material, normal_output: bpy.types.NodeSocketStandard, only_local = False, samples = 16):

        self.tree = bpy_node.Shader_Tree_Wrapper(material.node_tree)

        self.only_local = only_local
        self.samples = samples

        if normal_output:
            self.normal_output = self.tree.get_socket_wrapper(normal_output)
        else:
            self.normal_output = None

    def __enter__(self):

        ao_node = self.tree.new('ShaderNodeAmbientOcclusion')
        ao_node.only_local = self.only_local
        ao_node.samples = self.samples

        if self.normal_output:
            ao_node.inputs['Normal'].join(self.normal_output, move = False)

        return ao_node.outputs['AO'].bl_socket

    def __exit__(self, type, value, traceback):
        self.tree.delete_new_nodes()


class Output_Socket_Diffuse_AO:
    """ Diffuse based AO. """

    node_tree_name = '__blend_converter_diffuse_ao_bake'


    def __init__(self, material: bpy.types.Material, ignore_backface = False, faster = False, environment_has_alpha = True):
        """ Assumes a Principled BSDF material. """

        self.tree = bpy_node.Shader_Tree_Wrapper(material.node_tree)

        self.ignore_backface = ignore_backface

        self.faster = faster
        self.environment_has_alpha = environment_has_alpha


    def get_diffuse_mixin_node_tree(self, has_alpha: bool):

        bl_tree = bpy.data.node_groups.get(self.node_tree_name)
        if bl_tree:
            return bl_tree

        tree = bpy_node.Shader_Tree_Wrapper(bpy.data.node_groups.new(self.node_tree_name, 'ShaderNodeTree'))

        if hasattr(tree.bl_tree, 'interface'):
            tree.bl_tree.interface.new_socket(name='Shader', in_out='INPUT', socket_type='NodeSocketShader')
            tree.bl_tree.interface.new_socket(name='Normal', in_out='INPUT', socket_type='NodeSocketVector')
            tree.bl_tree.interface.new_socket(name='Shader', in_out='OUTPUT', socket_type='NodeSocketShader')
        else:
            tree.bl_tree.inputs.new('NodeSocketShader', 'Shader')
            tree.bl_tree.inputs.new('NodeSocketVector', 'Normal')
            tree.bl_tree.outputs.new('NodeSocketShader', 'Shader')

        output = tree.new('NodeGroupOutput')
        mix_shader = output.inputs[0].new('ShaderNodeMixShader')

        mix_shader.inputs[0].new('ShaderNodeLightPath', 'Is Camera Ray')
        diffuse_node = mix_shader.inputs[2].new('ShaderNodeBsdfDiffuse')
        diffuse_node.set_input('Color', (1,1,1,1))

        node_group_input = mix_shader.inputs[1].new('NodeGroupInput')  # this is expensive

        if not self.faster:
            diffuse_node.inputs['Normal'].join(node_group_input.outputs[1], move = False)

        if self.faster and not (self.environment_has_alpha or has_alpha):
            diffuse_node.outputs[0].join(mix_shader.inputs[1])

        if self.ignore_backface:
            mix_shader_2 = mix_shader.inputs[1].insert_new('ShaderNodeMixShader', new_node_identifier = 1)
            mix_shader_2.inputs[2].new('ShaderNodeBsdfTransparent')
            mix_shader_2.inputs[0].new('ShaderNodeNewGeometry', 'Backfacing')
        else:  # a lossy workaround to avoid artifacts, requires the inpaint
            mix_shader_2 = mix_shader.outputs[0].insert_new('ShaderNodeMixShader', 1)
            mix_shader_2.inputs[2].new('ShaderNodeBsdfTransparent')
            math_multiply = mix_shader_2.inputs[0].new('ShaderNodeMath', operation='MULTIPLY')
            geometry = math_multiply.inputs[1].new('ShaderNodeNewGeometry', 'Backfacing')
            math_less_than = math_multiply.inputs[0].new('ShaderNodeMath', operation='LESS_THAN')
            math_less_than.inputs[1].default_value = 0
            math_dot_product = math_less_than.inputs[0].new('ShaderNodeVectorMath', 'Value', operation='DOT_PRODUCT')
            geometry.outputs['Normal'].join(math_dot_product.inputs[0], False)
            geometry.outputs['True Normal'].join(math_dot_product.inputs[1], False)

        return tree.bl_tree


    def __enter__(self) -> bpy.types.NodeSocketShader:

        principled = self.tree.output[0]

        has_alpha = principled.inputs['Alpha'].connections or not principled.inputs['Alpha'].is_close(1)

        node_group = principled.outputs[0].new('ShaderNodeGroup', node_tree = self.get_diffuse_mixin_node_tree(has_alpha))

        if principled['Normal']:
            node_group.inputs[1].join(principled.inputs['Normal'].as_output(), move = False)

        return node_group.outputs[0].bl_socket


    def __exit__(self, type, value, traceback):
        self.tree.delete_new_nodes()


class Diffuse_AO_Bake_Settings(Bpy_State):

    ao_bake_world_name = '__blend_converter_ao_bake_world_name'


    def __init__(self, samples = 16, faster = False):
        super().__init__()

        context = bpy.context
        scene = context.scene
        cycles = context.scene.cycles  # type: typing.Any
        render = context.scene.render

        self.set(render, 'engine', 'CYCLES')

        self.set(scene, 'world', self.get_world())

        if faster:

            self.set(cycles, 'samples', int(math.sqrt(samples)))

            if bpy.app.version >= (2, 93):
                self.set(cycles, 'use_fast_gi', True)
                self.set(cycles, 'ao_bounces', 2)
                self.set(cycles, 'ao_bounces_render', 2)
                self.set(scene.world.light_settings, 'ao_factor', 1)
                self.set(scene.world.light_settings, 'distance', 10)
                self.set(cycles, 'fast_gi_method', 'REPLACE')

            self.set(cycles, 'caustics_refractive', False)
            self.set(cycles, 'caustics_reflective', False)

            self.set(cycles, 'max_bounces', 8)
            self.set(cycles, 'diffuse_bounces', 4)
            self.set(cycles, 'glossy_bounces', 2)
            self.set(cycles, 'transmission_bounces', 8)
            self.set(cycles, 'volume_bounces', 0)
            self.set(cycles, 'transparent_max_bounces', 8)

        else:

            self.set(cycles, 'samples', samples)

            if bpy.app.version >= (2, 93):
                self.set(cycles, 'use_fast_gi', False)

            self.set(cycles, 'caustics_refractive', True)
            self.set(cycles, 'caustics_reflective', True)

            self.set(cycles, 'max_bounces', 12)
            self.set(cycles, 'diffuse_bounces', 8)
            self.set(cycles, 'glossy_bounces', 4)
            self.set(cycles, 'transmission_bounces', 12)
            self.set(cycles, 'volume_bounces', 0)
            self.set(cycles, 'transparent_max_bounces', 8)


        try:
            self.set(render.bake, 'view_from', 'ABOVE_SURFACE')
        except AttributeError:
            pass

        self.set(cycles, 'bake_type', 'COMBINED')

        self.set(render.bake, 'use_pass_direct', True)
        self.set(render.bake, 'use_pass_indirect', True)
        self.set(render.bake, 'use_pass_diffuse', True)
        self.set(render.bake, 'use_pass_glossy', True)
        self.set(render.bake, 'use_pass_transmission', True)

        # self.set(render.bake, 'margin', 1)

        self.set(render.bake, 'use_pass_emit', False)
        for object in bpy.data.objects:
            if object.type == 'LIGHT':
                self.set(object, 'hide_render', True)


    def get_world(self):

        world = bpy.data.worlds.get(self.ao_bake_world_name)
        if world:
            return world

        world = bpy.data.worlds.new(name=self.ao_bake_world_name)
        world.use_nodes = True

        background = next(bl_node for bl_node in world.node_tree.nodes if bl_node.bl_idname == 'ShaderNodeBackground')
        background.inputs[0].default_value = (1, 1, 1, 1)

        return world



class Composer_Input_Simple:


    def __init__(self, input_socket: typing.Union['bpy.types.NodeSocketFloat', 'bpy.types.NodeSocketColor'], image: bpy.types.Image, use_denoise = False):

        self.tree = bpy_node.Compositor_Tree_Wrapper(bpy.context.scene.node_tree)
        self.input_socket = self.tree.get_socket_wrapper(input_socket)
        self.image = image

        self.use_denoise = use_denoise


    def __enter__(self):

        image_node = self.input_socket.new('CompositorNodeImage', image = self.image)


        set_alpha_node = image_node.outputs[0].insert_new('CompositorNodeSetAlpha')

        math_node = image_node.outputs[1].new('CompositorNodeMath', operation = 'GREATER_THAN')
        math_node.inputs[1].default_value = 0.9999

        math_node.outputs[0].join(set_alpha_node.inputs[1])

        distance = max(self.image.generated_height, self.image.generated_width)
        distance = min(distance, 512)

        if self.use_denoise:
            denoise_node = set_alpha_node.outputs[0].insert_new('CompositorNodeDenoise')
            denoise_node.prefilter = 'NONE'
            denoise_node.use_hdr = False
            denoise_node.inputs['Albedo'].join(image_node.outputs['Alpha'], move=False)


            denoise_node.inputs[0].insert_new('CompositorNodeInpaint', distance=1)
            denoise_node.inputs[0].insert_new('CompositorNodeInpaint', distance=1)

            erode_node = math_node.outputs[0].new('CompositorNodeDilateErode', mode = 'DISTANCE', distance = -1 if bpy.context.scene.render.bake.margin > 1 else 0)
            set_alpha_node_2 = denoise_node.outputs[0].insert_new('CompositorNodeSetAlpha')
            erode_node.outputs[0].join(set_alpha_node_2.inputs[1])

            set_alpha_node_2.outputs[0].insert_new('CompositorNodeInpaint', distance = distance)

        else:
            set_alpha_node.outputs[0].insert_new('CompositorNodeInpaint', distance = distance)


    def __exit__(self, type, value, traceback):
        self.tree.delete_new_nodes()


class Composer_Input_Fill_Color:
    """ TODO: The composer render is not triggered if the first image is not an image file. A bug? """


    def __init__(self, input_socket: typing.Union['bpy.types.NodeSocketFloat', 'bpy.types.NodeSocketColor'], image: bpy.types.Image):

        self.tree = bpy_node.Compositor_Tree_Wrapper(bpy.context.scene.node_tree)
        self.input_socket = self.tree.get_socket_wrapper(input_socket)
        self.image = image


    def __enter__(self):
        self.input_socket.new('CompositorNodeImage', image = self.image)


    def __exit__(self, type, value, traceback):
        self.tree.delete_new_nodes()


class Composer_Input_AO_Diffuse:


    def __init__(self, input_socket: typing.Union['bpy.types.NodeSocketFloat', 'bpy.types.NodeSocketColor'], image: bpy.types.Image):

        self.tree = bpy_node.Compositor_Tree_Wrapper(bpy.context.scene.node_tree)
        self.input_socket = self.tree.get_socket_wrapper(input_socket)
        self.image = image


    def __enter__(self):

        image_node = self.input_socket.new('CompositorNodeImage', image = self.image)

        albedo_socket = image_node.outputs['Alpha']

        denoise_node = self.input_socket.insert_new('CompositorNodeDenoise')
        denoise_node.prefilter = 'NONE'
        denoise_node.use_hdr = False

        denoise_node.inputs['Albedo'].join(albedo_socket, move=False)


        denoise_node.inputs[0].insert_new('CompositorNodeInpaint', distance=1)
        denoise_node.inputs[0].insert_new('CompositorNodeInpaint', distance=1)
        denoise_node.inputs[0].insert_new('CompositorNodeInpaint', distance=1)
        denoise_node.inputs[0].insert_new('CompositorNodeInpaint', distance=1)

        denoise_node.inputs[2].insert_new('CompositorNodeBlur', filter_type = 'FAST_GAUSS', size_y = 2, size_x = 2)

        set_alpha_node = denoise_node.outputs[0].insert_new('CompositorNodeSetAlpha')

        erode_node = set_alpha_node.inputs[1].new('CompositorNodeDilateErode', mode = 'DISTANCE', distance = -1 if bpy.context.scene.render.bake.margin > 1 else 0)
        math_node = erode_node.inputs[0].new('CompositorNodeMath', operation = 'GREATER_THAN')
        math_node.inputs[0].join(albedo_socket)
        math_node.inputs[1].default_value = 0.9999

        distance = max(self.image.generated_height, self.image.generated_width)
        distance = min(distance, 512)

        inpaint_node = set_alpha_node.outputs[0].new('CompositorNodeInpaint', distance = distance)

        rgb_to_bw_node = inpaint_node.outputs[0].new('CompositorNodeRGBToBW')

        mix_rgb_node = rgb_to_bw_node.outputs[0].new('CompositorNodeMixRGB', 1)
        mix_rgb_node.outputs[0].join(self.input_socket)

        mix_rgb_node.inputs[0].new('CompositorNodeBlur', filter_type = 'CUBIC', size_y = 8, size_x = 8).inputs[0].new('CompositorNodeFilter', filter_type = 'SOBEL').inputs[1].join(rgb_to_bw_node.outputs[0])

        mix_rgb_node.inputs[2].new('CompositorNodeBlur', filter_type = 'CUBIC', size_y = 2, size_x = 2).inputs[0].new('CompositorNodeDilateErode', mode = 'DISTANCE', distance = 1).inputs[0].join(rgb_to_bw_node.outputs[0])


    def __exit__(self, type, value, traceback):
        self.tree.delete_new_nodes()


class Focus_Objects:


    SELECT_KEY = '__bc_init_select_'
    HIDE_KEY = '__bc_init_hide_'
    MODE_KEY = '__bc_init_mode_'
    VISIBLE_KEY = '__bc_visible_'
    HIDE_VIEWPORT_KEY = '__bc_init_hide_viewport_'


    def __init__(self, objects: typing.Union[bpy.types.Object, typing.List[bpy.types.Object]], mode = 'OBJECT', view_layer: bpy.types.ViewLayer = None):

        if view_layer is None:
            view_layer = bpy.context.view_layer

        self._view_layer = view_layer

        if isinstance(objects, bpy.types.Object):
            objects = [objects]

        self._objects = list(dict.fromkeys(objects))

        self.mode = mode

        self.context_id = uuid.uuid1().hex

        self.SELECT_KEY += self.context_id
        self.HIDE_KEY += self.context_id
        self.MODE_KEY += self.context_id
        self.HIDE_VIEWPORT_KEY += self.context_id
        self.VISIBLE_KEY += self.context_id

        self.init_object_indexes = set()


    @property
    def view_layer(self) -> bpy.types.ViewLayer:
        return self.ref_list[0]

    @property
    def hidden_by_hierarchy_collection(self) -> bpy.types.Collection:
        return self.ref_list[1]

    @property
    def init_active_object(self) -> bpy.types.Object:
        return self.ref_list[2]

    @property
    def affected_objects(self) -> typing.List[bpy.types.Object]:
        return list(filter(None, list(self.ref_list)[3:]))

    @property
    def init_objects(self) -> typing.List[bpy.types.Object]:
        return list(filter(None, (ref for index, ref in enumerate(self.ref_list) if index in self.init_object_indexes)))


    def set_mode(self, objects: typing.List[bpy.types.Object], mode: str):
        """
        `bpy.ops.object.mode_set` works for multiple selected objects, but.

        If the active object does not support the mode — it will error.
        `TypeError: Converting py args to operator properties: enum "EDIT" not found in ('OBJECT')`

        If a data has multiple users it will change the mode only for a single object that uses that data. Will error.

        If the active object already in the mode — it wont set the mode for the other objects. This case is handled.

        If the active object is hidden by its collection its mode can be changed but not the mode of other selected objects. Will error.

        blender/source/blender/editors/object/object_modes.cc::mode_compat_test
        https://github.com/blender/blender/blob/97f9e100546256b1f7432f85057de523724644eb/source/blender/editors/object/object_modes.cc#L99

        88051 - Context override of bpy.ops.object.mode_set does not work
        https://projects.blender.org/blender/blender/issues/88051
        """

        view_layer = self.view_layer

        for object_type, objects_of_type in utils.list_by_key(objects, operator.attrgetter('type')).items():


            bpy_utils.focus(objects_of_type, view_layer=view_layer)

            for object in objects_of_type:
                if not object.visible_get(view_layer=view_layer):
                    self.hidden_by_hierarchy_collection.objects.link(object)
                    object.hide_set(False)
                    object.hide_viewport = False
                    object.hide_select = False
                    object.select_set(True)


            for object in objects_of_type:
                if not object.visible_get(view_layer=view_layer):
                    raise Exception(f"Object is not visible, setting mode will fail: {object.name_full}")


            if all(object.mode == mode for object in objects_of_type):
                continue

            for object in objects_of_type:
                if object.mode != mode:
                    view_layer.objects.active = object


            result = bpy.ops.object.mode_set(mode=mode)
            assert not 'CANCELLED' in result

            if all(object.mode == mode for object in objects_of_type):
                continue

            if any(len(objects) > 1 for objects in utils.list_by_key(objects, lambda x: x.data).values()):
                info = json.dumps(utils.list_by_key(objects, lambda x: x.data.name_full), indent=4, default=lambda x: x.name_full)
                raise Exception(f"Fail to set '{mode}' mode for '{object_type}': multiple data users: {info}")
            else:
                info = '\n'.join([f"{o.name_full}: {o.mode}" for o in objects_of_type])
                raise Exception(f"Fail to set '{mode}' mode for '{object_type}': unknown reason: {info}")


    def __enter__(self):

        view_layer = self._view_layer
        affected_objects = [object for object in bpy_utils.get_view_layer_objects(view_layer) if object.visible_get(view_layer=view_layer)] + self._objects
        affected_objects = list(dict.fromkeys(affected_objects))

        self.ref_list = Bpy_Reference_List().__enter__()

        self.ref_list.append(view_layer)
        self.ref_list.append(bpy.data.collections.new('__bc_hidden_by_hierarchy' + self.context_id))
        self.ref_list.append(view_layer.objects.active)

        view_layer.layer_collection.collection.children.link(self.hidden_by_hierarchy_collection)


        for object in affected_objects:

            object[self.MODE_KEY] = object.mode

            object[self.VISIBLE_KEY] = object.visible_get(view_layer = view_layer)

            object[self.SELECT_KEY] = object.select_get(view_layer = view_layer)
            object[self.HIDE_KEY] = object.hide_get(view_layer = view_layer)
            object[self.HIDE_VIEWPORT_KEY] = object.hide_viewport

            index = self.ref_list.append(object)

            if object in  self._objects:
                self.init_object_indexes.add(index)


        if self.mode == 'OBJECT':
            self.set_mode(affected_objects, 'OBJECT')
        else:
            self.set_mode(tuple(object for object in affected_objects if object not in self._objects), 'OBJECT')
            self.set_mode(self._objects, self.mode)

        bpy_utils.focus(self._objects)

        for object in self._objects:
            if not object.visible_get(view_layer=view_layer):
                # TODO: objects can be hidden by drivers
                # TODO: what it we want to work with the object hidden
                raise Exception(f"Fail to focus object: not visible: {object.name_full}")

        return self


    def __exit__(self, type, value, traceback):

        view_layer = self.view_layer
        objects = self.affected_objects

        for mode, objects_in_mode in utils.list_by_key(objects, operator.itemgetter(self.MODE_KEY)).items():
            self.set_mode(objects_in_mode, mode)

        for object in objects:

            if object.mode != object[self.MODE_KEY]:
                raise Exception(f"Fail to reset '{object[self.MODE_KEY]}' mode: '{object.name_full}' in mode '{object.mode}'")

            object.select_set(object[self.SELECT_KEY], view_layer = view_layer)
            object.hide_viewport = object[self.HIDE_VIEWPORT_KEY]
            object.hide_set(object[self.HIDE_KEY], view_layer = view_layer)

            del object[self.SELECT_KEY]
            del object[self.HIDE_KEY]
            del object[self.HIDE_VIEWPORT_KEY]
            del object[self.MODE_KEY]

        bpy.data.collections.remove(self.hidden_by_hierarchy_collection)

        view_layer.update()
        scene_objects = set(bpy_utils.get_view_layer_objects(view_layer))
        # scene_objects = list(filter(None, view_layer.layer_collection.collection.all_objects))

        for object in objects:
            if object in scene_objects and object.visible_get(view_layer=view_layer) != object[self.VISIBLE_KEY]:
                raise Exception(f"Fail to revert visibility to {object[self.VISIBLE_KEY]}: {object.name_full}")

            del object[self.VISIBLE_KEY]

        if self.init_active_object in scene_objects:
            view_layer.objects.active = self.init_active_object

        self.ref_list.__exit__(type, value, traceback)


class Light_Map_Bake_Settings(Bpy_State):


        def __init__(self, samples = 16):
            super().__init__()

            context = bpy.context
            scene = context.scene
            cycles = context.scene.cycles
            render = context.scene.render
            bake = render.bake

            self.set(render, 'engine', 'CYCLES')
            self.set(cycles, 'samples', samples)

            if bpy.app.version >= (2, 93):
                self.set(cycles, 'use_fast_gi', False)

            self.set(cycles, 'caustics_refractive', True)
            self.set(cycles, 'caustics_reflective', True)

            self.set(cycles, 'max_bounces', 12)
            self.set(cycles, 'diffuse_bounces', 8)
            self.set(cycles, 'glossy_bounces', 4)
            self.set(cycles, 'transmission_bounces', 12)
            self.set(cycles, 'volume_bounces', 0)
            self.set(cycles, 'transparent_max_bounces', 8)


            try:
                self.set(bake, 'view_from', 'ABOVE_SURFACE')
            except AttributeError:
                pass


            # ADJACENT_FACES can make the thing worse with direct lights
            # kind of the same it does to normals
            try:
                self.set(bake, 'margin_type', 'EXTEND')
            except AttributeError:
                pass
            self.set(bake, 'margin', 0)


            self.set(cycles, 'bake_type', 'COMBINED')

            self.set(bake, 'use_pass_direct', True)
            self.set(bake, 'use_pass_indirect', True)
            self.set(bake, 'use_pass_diffuse', True)
            self.set(bake, 'use_pass_glossy', True)
            self.set(bake, 'use_pass_transmission', True)
            self.set(bake, 'use_pass_emit', True)


class Output_Lightmap:

    node_tree_name = '__blend_converter_lightmap_bake'


    def __init__(self, material: 'bpy.types.Material', use_normals = False):
        self.tree = bpy_node.Shader_Tree_Wrapper(material.node_tree)
        self.use_normals = use_normals


    def get_diffuse_mixin_node_tree(self):

        bl_tree = bpy.data.node_groups.get(self.node_tree_name)
        if bl_tree:
            return bl_tree

        tree = bpy_node.Shader_Tree_Wrapper(bpy.data.node_groups.new(self.node_tree_name, 'ShaderNodeTree'))

        if hasattr(tree.bl_tree, 'interface'):
            tree.bl_tree.interface.new_socket(name='Shader', in_out='INPUT', socket_type='NodeSocketShader')
            tree.bl_tree.interface.new_socket(name='Normal', in_out='INPUT', socket_type='NodeSocketVector')
            tree.bl_tree.interface.new_socket(name='Shader', in_out='OUTPUT', socket_type='NodeSocketShader')
        else:
            tree.bl_tree.inputs.new('NodeSocketShader', 'Shader')
            tree.bl_tree.inputs.new('NodeSocketVector', 'Normal')
            tree.bl_tree.outputs.new('NodeSocketShader', 'Shader')

        output = tree.new('NodeGroupOutput')
        mix_shader = output.inputs[0].new('ShaderNodeMixShader')

        mix_shader.inputs[0].new('ShaderNodeLightPath', 'Is Camera Ray')
        node_group_input = mix_shader.inputs[1].new('NodeGroupInput')
        diffuse_node = mix_shader.inputs[2].new('ShaderNodeBsdfDiffuse')
        diffuse_node.set_input('Color', (1,1,1,1))
        diffuse_node.inputs['Normal'].join(node_group_input.outputs[1], move = False)

        # a lossy workaround to avoid artifacts, requires the inpaint
        mix_shader_2 = mix_shader.outputs[0].insert_new('ShaderNodeMixShader', 1)
        mix_shader_2.inputs[2].new('ShaderNodeBsdfTransparent')
        math_multiply = mix_shader_2.inputs[0].new('ShaderNodeMath', operation='MULTIPLY')
        geometry = math_multiply.inputs[1].new('ShaderNodeNewGeometry', 'Backfacing')
        math_less_than = math_multiply.inputs[0].new('ShaderNodeMath', operation='LESS_THAN')
        math_less_than.inputs[1].default_value = 0
        math_dot_product = math_less_than.inputs[0].new('ShaderNodeVectorMath', 'Value', operation='DOT_PRODUCT')
        geometry.outputs['Normal'].join(math_dot_product.inputs[0], False)
        geometry.outputs['True Normal'].join(math_dot_product.inputs[1], False)

        return tree.bl_tree


    def __enter__(self) -> 'bpy.types.NodeSocketShader':

        principled = self.tree.output[0]

        node_group = principled.outputs[0].new('ShaderNodeGroup', node_tree = self.get_diffuse_mixin_node_tree())

        if principled['Normal'] and self.use_normals:
            node_group.inputs[1].join(principled.inputs['Normal'].as_output(), move = False)

        return node_group.outputs[0].bl_socket


    def __exit__(self, type, value, traceback):
        self.tree.delete_new_nodes()


class Composer_Input_Lightmap:


    def __init__(self, input_socket: typing.Union['bpy.types.NodeSocketFloat', 'bpy.types.NodeSocketColor'], image: bpy.types.Image):

        self.tree = bpy_node.Compositor_Tree_Wrapper(bpy.context.scene.node_tree)
        self.input_socket = self.tree.get_socket_wrapper(input_socket)
        self.image = image

        self.init_dither_intensity = bpy.context.scene.render.dither_intensity


    def __enter__(self):

        bpy.context.scene.render.dither_intensity = 1.0

        distance = max(self.image.generated_height, self.image.generated_width)
        distance = min(distance, 512)

        inpaint = self.input_socket.new('CompositorNodeInpaint', distance = distance)

        set_alpha_1 = inpaint.inputs[0].new('CompositorNodeSetAlpha')

        denoise = set_alpha_1.inputs[0].new('CompositorNodeDenoise', prefilter = 'NONE', use_hdr = False)

        inpaint_px_1 = denoise.inputs['Image'].new('CompositorNodeInpaint', distance=1)
        # inpaint_px_1.outputs[0].new('CompositorNodeSepRGBA').outputs[3].join(denoise.inputs['Albedo'])

        inpaint_px_2 = inpaint_px_1.inputs[0].new('CompositorNodeInpaint', distance=1)

        set_alpha_2 = inpaint_px_2.inputs[0].new('CompositorNodeSetAlpha')

        image_node = set_alpha_2.inputs['Image'].new('CompositorNodeImage', image = self.image)

        math_node = set_alpha_2.inputs['Alpha'].new('CompositorNodeMath', operation = 'GREATER_THAN')
        math_node.inputs[0].join(image_node.outputs['Alpha'])
        math_node.inputs[1].default_value = 0.9999

        image_node.outputs['Alpha'].join(set_alpha_1.inputs['Alpha'])


    def __exit__(self, type, value, traceback):
        self.tree.delete_new_nodes()

        bpy.context.scene.render.dither_intensity = self.init_dither_intensity


def call_in_uv_editor(func, *args, can_be_canceled = False, **kwargs):
    """ Because some functionally of the operators can change depending on it."""

    with State() as state:

        window = bpy.data.window_managers[0].windows[0]

        area = window.screen.areas[0]
        state.set(area, 'type', 'IMAGE_EDITOR')
        state.set(area, 'ui_type', 'UV')

        space_data = area.spaces.active

        window_region = next(region for region in area.regions if region.type == 'WINDOW')

        override = dict(
            window=window,
            workspace=window.workspace,
            screen=window.screen,
            area = area,
            space_data = space_data,
            region = window_region,
        )

        call(override, func, *args, can_be_canceled = can_be_canceled, **kwargs)
