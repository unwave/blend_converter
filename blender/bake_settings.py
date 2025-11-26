import typing
import contextlib
import sys


if __package__:
    from . import bpy_node
    from .. import tool_settings
    from . import bpy_context
    from . import blend_inspector
else:
    from blend_converter import tool_settings
    from blend_converter import blend_inspector


if typing.TYPE_CHECKING:
    # need only __init__ hints
    from dataclasses import dataclass
else:
    dataclass = lambda x: x


if 'bpy' in sys.modules:
    import bpy


def _get_value_from_color(color: typing.Collection[float]):
    return color[0] * 0.2126 + color[1] * 0.7152 + color[2] * 0.0722


class _Socket_Type:
    COLOR = 'color'
    VALUE = 'value'
    VECTOR = 'vector'
    SHADER = 'shader'


@dataclass
class _Bake_Type(tool_settings.Settings):


    _requires_principled_bsdf = False
    """ Whether or not a Principled BSDF is assumed. """


    _default_color = (0.0, 0.0, 0.0)
    """ A default fill color. """


    _socket_type = _Socket_Type.COLOR
    """ A string identifier of the shader socket type. See `Socket_Type`. """


    _identifier = ''
    """ A name of the texture type. """


    _is_srgb = False
    """ True if the baked image must be saved as sRGB. """


    use_denoise: bool = False
    """ Denoise the image in the compositor. """


    @property
    def _default_value(self) -> float:
        """ A default fill value. """
        return _get_value_from_color(self._default_color)


    def _get_setup_context(self) -> typing.ContextManager:
        """ Returns a context that will be entered once before the baking process. """
        return contextlib.nullcontext()


    def _get_material_context(self, material: 'bpy.types.Material') -> typing.ContextManager:
        """ Returns a context that will be entered for each material. The `__enter__` method should return an output socket that will be baked. """
        return contextlib.nullcontext(_get_shader_output_socket(material))


    def _get_compositor_context(self, input_socket: typing.Union['bpy.types.NodeSocketFloat', 'bpy.types.NodeSocketColor'], images: typing.Union['bpy.types.Image', typing.List['bpy.types.Image']], channel: int) -> typing.ContextManager:
        """ Returns a context that will be entered when composing and saving the image. """

        if isinstance(images, bpy.types.Image):
            image = images
        else:
            image = images[0]

        return bpy_context.Compositor_Input_Default(input_socket, image, channel, use_denoise = self.use_denoise)


def get_margin():
    return blend_inspector.get_value('denoise_margin', bpy.context.scene.render.bake.margin)


# https://github.com/blender/blender/blob/main/source/blender/blenloader/intern/versioning_400.cc
# version_principled_bsdf_rename_sockets
BSDF_RENAME_SOCKETS_DICT = {
    'Emission': 'Emission Color',
    'Specular': 'Specular IOR Level',
    'Subsurface': 'Subsurface Weight',
    'Transmission': 'Transmission Weight',
    'Coat': 'Coat Weight',
    'Clearcoat': 'Coat Weight',
    'Sheen': 'Sheen Weight',
}


def _get_versioned_socket_identifier(identifier):
    if bpy.app.version > (4, 0, 0):
        return BSDF_RENAME_SOCKETS_DICT.get(identifier, identifier)
    else:
        return identifier



def _get_shader_output_socket(material: 'bpy.types.Material') -> 'bpy.types.NodeSocketShader':
    tree = bpy_node.Shader_Tree_Wrapper(material.node_tree)
    return tree.surface_input.connections[0].bl_socket


def _get_principled_socket(material: 'bpy.types.Material', identifier: str) -> typing.Union['bpy.types.NodeSocketColor', 'bpy.types.NodeSocketFloat', 'bpy.types.NodeSocketVector']:
    tree = bpy_node.Shader_Tree_Wrapper(material.node_tree)
    return tree.output['Surface'].inputs[identifier].as_output().bl_socket


@contextlib.contextmanager
def _Output_Socket_Principled(material: 'bpy.types.Material', identifier: str) -> typing.Union['bpy.types.NodeSocketColor', 'bpy.types.NodeSocketFloat', 'bpy.types.NodeSocketVector']:
    try:
        tree = bpy_node.Shader_Tree_Wrapper(material.node_tree)
        yield tree.output['Surface'].inputs[identifier].as_output().bl_socket
    finally:
        tree.delete_new_nodes()


@contextlib.contextmanager
def _Output_Socket_Fill_Color(material: 'bpy.types.Material', default_color: typing.Union[float, typing.Collection[float]]) -> 'bpy.types.NodeSocketShader':

    try:
        tree = bpy_node.Shader_Tree_Wrapper(material.node_tree)

        node = tree.new('ShaderNodeRGB')
        node.outputs[0].set_default_value(default_color)

        yield node.outputs[0].bl_socket
    finally:
        tree.delete_new_nodes()


@dataclass
class Fill_Color(_Bake_Type, tool_settings.Settings):

    default_color: tuple = (0.0, 0.0, 0.0)

    _socket_type = _Socket_Type.COLOR
    _identifier = 'None'

    @property
    def _default_color(self) -> float:
        return self.default_color


    def _get_material_context(self, material):
        return _Output_Socket_Fill_Color(material, self.default_color)


    def _get_compositor_context(self, input_socket, images, channel):

        if isinstance(images, bpy.types.Image):
            image = images
        else:
            image = images[0]

        return bpy_context.Compositor_Input_Fill_Color(input_socket, image)


@dataclass
class _Principled_Input(_Bake_Type, tool_settings.Settings):

    if typing.TYPE_CHECKING:
        _not_versioned_socket_identifier = ''

    _requires_principled_bsdf = True


    @property
    def _socket_identifier(self):
        return _get_versioned_socket_identifier(self._not_versioned_socket_identifier)


    def _get_setup_context(self):

        settings = []

        if self.use_denoise:
            settings.append((bpy.context.scene.render.bake, 'margin', get_margin()))

            if hasattr(bpy.context.scene.render.bake, 'margin_type'):
                settings.append((bpy.context.scene.render.bake, 'margin_type', 'ADJACENT_FACES'))

        return bpy_context.Bpy_State(settings)


    def _get_material_context(self, material: 'bpy.types.Material'):
        return _Output_Socket_Principled(material, self._socket_identifier)


    @property
    def _identifier(self):
        return self._socket_identifier




@dataclass
class Normal(_Principled_Input):
    """ Tangent space normals. """

    _not_versioned_socket_identifier = 'Normal'

    _socket_type = _Socket_Type.VECTOR

    _default_color = (0.5, 0.5, 1.0)

    uv_layer: str = tool_settings.Bake.uv_layer_name
    """
    Name of the UV layer to use for the tangent space.

    #### Default: `tool_settings.Bake.uv_layer_name`
    """

    use_remove_inward_normals: bool = False

    denoise_mix_factor: float = 1.0


    def _get_compositor_context(self, input_socket, images, channel):

        if isinstance(images, bpy.types.Image):
            image = images
        else:
            image = images[0]

        return bpy_context.Compositor_Input_Normal(
            input_socket,
            image,
            use_denoise = self.use_denoise,
            use_remove_inward_normals = self.use_remove_inward_normals,
            denoise_mix_factor = self.denoise_mix_factor,
        )


    def _get_setup_context(self):
        """
        ⚓ T96942 Bake Normal problem when adjoining faces have different UV orientation
        https://developer.blender.org/T96942
        """

        settings = []

        if self.use_denoise:
            settings.append((bpy.context.scene.render.bake, 'margin', 1))

        if hasattr(bpy.context.scene.render.bake, 'margin_type'):
            settings.append((bpy.context.scene.render.bake, 'margin_type', 'EXTEND'))

        return bpy_context.Bpy_State(settings)


    def _get_material_context(self, material: 'bpy.types.Material'):
        return bpy_context.Output_Socket_World_Space_To_Tangent_Space(material, _get_principled_socket(material, 'Normal'), self.uv_layer)


@dataclass
class Base_Color(_Principled_Input):

    _not_versioned_socket_identifier = 'Base Color'
    _socket_type = _Socket_Type.COLOR
    _default_color = (0.8, 0.8, 0.8)

    _is_srgb = True


@dataclass
class Roughness(_Principled_Input):

    _not_versioned_socket_identifier = 'Roughness'
    _socket_type = _Socket_Type.VALUE
    _default_color = ( 0.5, 0.5, 0.5)


@dataclass
class Metallic(_Principled_Input):

    _not_versioned_socket_identifier = 'Metallic'
    _socket_type = _Socket_Type.VALUE
    _default_color = (0.0, 0.0, 0.0)


@dataclass
class Alpha(_Principled_Input):

    _not_versioned_socket_identifier = 'Alpha'
    _socket_type = _Socket_Type.VALUE
    _default_color = (1.0, 1.0, 1.0)


@contextlib.contextmanager
def _Output_Socket_Emission(material: 'bpy.types.Material') -> 'bpy.types.NodeSocketShader':

    try:
        tree = bpy_node.Shader_Tree_Wrapper(material.node_tree)

        principled = tree.output['Surface']

        if 'Emission Strength' in principled.inputs.identifiers:

            mix_node = tree.new('ShaderNodeVectorMath', operation = 'MULTIPLY')
            mix_node[0] = principled.inputs[bpy_node.Socket_Identifier.EMISSION].as_output()
            mix_node[1] = principled.inputs['Emission Strength'].as_output()

            yield mix_node.outputs[0].bl_socket
        else:
            yield principled.inputs[bpy_node.Socket_Identifier.EMISSION].as_output().bl_socket
    finally:
        tree.delete_new_nodes()


@dataclass
class Emission(_Principled_Input):

    _not_versioned_socket_identifier = 'Emission'
    _socket_type = _Socket_Type.COLOR
    _default_color = (0.0, 0.0, 0.0)

    _is_srgb = True

    def _get_material_context(self, material: 'bpy.types.Material'):
        return _Output_Socket_Emission(material)



@dataclass
class _AO(_Bake_Type, tool_settings.Settings):

    _identifier = 'Ambient Occlusion'
    _default_color = (1.0, 1.0, 1.0)
    _requires_principled_bsdf = True



@dataclass
class AO_Node(_AO):
    """ Uses the Ambient Occlusion shader node: `ShaderNodeAmbientOcclusion`. """

    _socket_type = _Socket_Type.VALUE


    use_denoise: bool = True


    only_local: bool = False
    """
    When `True` does not produce the occlusion between objects.

    #### Default: `False`
    """

    samples: int = 16
    """
    A number of samples per render sample.

    #### Default: `16`
    """


    def _get_setup_context(self):

        settings = []

        if self.use_denoise:
            settings.append((bpy.context.scene.render.bake, 'margin', get_margin()))

            if hasattr(bpy.context.scene.render.bake, 'margin_type'):
                settings.append((bpy.context.scene.render.bake, 'margin_type', 'ADJACENT_FACES'))

        return bpy_context.Bpy_State(settings)


    def _get_material_context(self, material: 'bpy.types.Material'):
        return bpy_context.Output_Socket_Ambient_Occlusion(material, _get_principled_socket(material, 'Normal'), self.only_local, self.samples)



@dataclass
class AO_Diffuse(_AO):
    """ Uses a diffuse shader to bake the occlusion. Respects the usual shaders properties like transparency, emission, transmission, etc. """

    _socket_type = _Socket_Type.SHADER


    samples: int = 16
    """
    A number of render samples.

    #### Default: `16`
    """

    faster: bool = True
    """
    A faster AO bake, sacrificing quality.

    `samples` will set to a square root of the value.

    #### Default: `True`
    """

    environment_has_transparent_materials: bool = False
    """
    Assume the environment has transparent materials.

    #### Default: `True`
    """

    ignore_backface: bool = False
    """
    Ignore backfacing.

    #### Default: `False`
    """


    use_normals: bool = True
    """
    Use the material normals.

    #### Default: `True`
    """


    def _get_setup_context(self):
        return bpy_context.Diffuse_AO_Bake_Settings(self.samples, self.faster)


    def _get_material_context(self, material: 'bpy.types.Material'):
        return bpy_context.Output_Socket_Diffuse_AO(material, self.ignore_backface, self.faster, self.environment_has_transparent_materials, self.use_normals)


    def _get_compositor_context(self, input_socket, images, channel):

        if isinstance(images, bpy.types.Image):
            image = images
        else:
            image = images[0]

        return bpy_context.Compositor_Input_AO_Diffuse(input_socket, image)



@dataclass
class Diffuse(_Bake_Type, tool_settings.Settings):


    _socket_type = _Socket_Type.SHADER
    _identifier = 'Diffuse'
    _default_color = (0.5, 0.5, 0.5)

    _is_srgb = True

    use_pass_direct: bool = True
    use_pass_indirect: bool = True
    use_pass_color: bool = True

    use_denoise: bool = True


    samples: int = 16
    """
    A number of render samples.

    #### Default: `16`
    """

    def _get_setup_context(self):

        settings = [(bpy.context.scene.cycles, 'bake_type', 'DIFFUSE')]

        if 'use_pass_direct' in self._has_been_set:
            settings.append((bpy.context.scene.render.bake, 'use_pass_direct', self.use_pass_direct))

        if 'use_pass_indirect' in self._has_been_set:
            settings.append((bpy.context.scene.render.bake, 'use_pass_indirect', self.use_pass_indirect))

        if 'use_pass_color' in self._has_been_set:
            settings.append((bpy.context.scene.render.bake, 'use_pass_color', self.use_pass_color))

        if 'samples' in self._has_been_set:
            settings.append((bpy.context.scene.cycles, 'samples', self.samples))

        if self.use_denoise:
            settings.append((bpy.context.scene.render.bake, 'margin', get_margin()))

        return bpy_context.Bpy_State(settings)



@dataclass
class Glossy(_Bake_Type, tool_settings.Settings):


    _socket_type = _Socket_Type.SHADER
    _identifier = 'Glossy'
    _default_color = (0.5, 0.5, 0.5)

    _is_srgb = True

    use_pass_direct: bool = True
    use_pass_indirect: bool = True
    use_pass_color: bool = True

    use_denoise: bool = True


    samples: int = 16
    """
    A number of render samples.

    #### Default: `16`
    """


    def _get_setup_context(self):

        settings = [(bpy.context.scene.cycles, 'bake_type', 'GLOSSY')]

        if 'use_pass_direct' in self._has_been_set:
            settings.append((bpy.context.scene.render.bake, 'use_pass_direct', self.use_pass_direct))

        if 'use_pass_indirect' in self._has_been_set:
            settings.append((bpy.context.scene.render.bake, 'use_pass_indirect', self.use_pass_indirect))

        if 'use_pass_color' in self._has_been_set:
            settings.append((bpy.context.scene.render.bake, 'use_pass_color', self.use_pass_color))

        if 'samples' in self._has_been_set:
            settings.append((bpy.context.scene.cycles, 'samples', self.samples))

        if self.use_denoise:
            settings.append((bpy.context.scene.render.bake, 'margin', get_margin()))

        return bpy_context.Bpy_State(settings)




@contextlib.contextmanager
def _Output_Socket_AOV(material: 'bpy.types.Material', aov_name: str, is_color: bool, default_color: typing.Union[float, typing.Collection[float]]) -> 'bpy.types.NodeSocketShader':

    try:
        tree = bpy_node.Shader_Tree_Wrapper(material.node_tree)

        prev_output = None

        if is_color:
            input_index = 0
        else:
            input_index = 1

        for node in tree.get_by_bl_idname('ShaderNodeOutputAOV'):

            if node.mute:
                continue

            if node.aov_name != aov_name:
                continue

            if not node.inputs[input_index].connections:
                node.inputs[input_index].get_default_value_as_node()

            if prev_output is None:
                prev_output = node.inputs[input_index].connections[0]
            else:
                vector_math = prev_output.new('ShaderNodeVectorMath')
                vector_math.inputs[1].join(node.inputs[input_index].connections[0])
                prev_output = vector_math.inputs[0].connections[0]


        if prev_output is None:
            if input_index == 0:
                node = tree.new('ShaderNodeRGB')
                node.outputs[0].set_default_value(default_color)
                prev_output = node.outputs[0]
            else:
                node = tree.new('ShaderNodeValue')
                node.outputs[0].set_default_value(default_color)
                prev_output = node.outputs[0]

        yield prev_output
    finally:
        tree.delete_new_nodes()


@dataclass
class AOV(_Bake_Type, tool_settings.Settings):

    name: str = ''
    is_color: bool = True

    use_denoise: bool = False


    @property
    def _identifier(self):
        return self.name


    @property
    def _socket_type(self):
        if self.is_color:
            return _Socket_Type.COLOR
        else:
            return _Socket_Type.VALUE


    def _get_material_context(self, material):
        return _Output_Socket_AOV(material, self.name, self.is_color, default_color = self._default_color)



@contextlib.contextmanager
def _Output_Socket_View_Space_Normals(material: 'bpy.types.Material') -> 'bpy.types.NodeSocketShader':

    try:
        tree = bpy_node.Shader_Tree_Wrapper(material.node_tree)

        input = tree.output['Surface'].inputs['Normal']

        if input.connections:
            output = input.connections[0]
        else:
            output = tree.new('ShaderNodeNewGeometry').outputs['Normal']

        yield output.new('ShaderNodeVectorTransform', vector_type = 'NORMAL', convert_to = 'CAMERA').outputs[0].bl_socket
    finally:
        tree.delete_new_nodes()


@dataclass
class View_Space_Normal(_Bake_Type, tool_settings.Settings):


    _default_color = (0.0, 0.0, 0.0)
    _identifier = 'View Space Normal'
    _socket_type = _Socket_Type.VECTOR
    _requires_principled_bsdf = True

    use_denoise: bool = False
    use_remove_inward_normals: bool = False


    def _get_setup_context(self):

        settings = [(bpy.context.scene.render.bake, 'margin', 1)]

        if hasattr(bpy.context.scene.render.bake, 'margin_type'):
            settings.append((bpy.context.scene.render.bake, 'margin_type', 'EXTEND'))

        return bpy_context.Bpy_State(settings)


    def _get_material_context(self, material):
        return _Output_Socket_View_Space_Normals(material)


    def _get_compositor_context(self, input_socket, images, channel):

        if isinstance(images, bpy.types.Image):
            image = images
        else:
            image = images[0]

        return bpy_context.Compositor_Input_View_Space_Normal(input_socket, image, self.use_denoise, self.use_remove_inward_normals)


@dataclass
class Lightmap(_Bake_Type, tool_settings.Settings):

        _socket_type = _Socket_Type.SHADER

        _identifier = 'Light Map'
        _default_color = (0.0, 0.0, 0.0)
        _requires_principled_bsdf = True


        samples: int = 16
        """
        A number of render samples.

        #### Default: `16`
        """

        use_normals: bool = False
        """
        Use the surface normals. Can introduce more noise coming from high frequency details.

        #### Default: `False`
        """

        def _get_setup_context(self):
            return bpy_context.Light_Map_Bake_Settings(self.samples)


        def _get_material_context(self, material: 'bpy.types.Material'):
            return bpy_context.Output_Lightmap(material)


        def _get_compositor_context(self, input_socket, images, channel):

            if isinstance(images, bpy.types.Image):
                image = images
            else:
                image = images[0]

            return bpy_context.Compositor_Input_Lightmap(input_socket, image)



@contextlib.contextmanager
def _Output_Label(material: 'bpy.types.Material', node_label: str, socket: typing.Union[str, int] = 0) -> typing.Union['bpy.types.NodeSocketColor', 'bpy.types.NodeSocketFloat', 'bpy.types.NodeSocketVector']:
    try:
        tree = bpy_node.Shader_Tree_Wrapper(material.node_tree)

        found = False

        for node in tree.output.inputs[0].descendants:
            if node.label == node_label:
                found = True
                yield node.outputs[socket].bl_socket

        if not found:
            raise RuntimeError(f"Node with label `{node_label}` not found in: {material.name_full}")

    finally:
        tree.delete_new_nodes()

@dataclass
class Buffer_Factor(_Bake_Type, tool_settings.Settings):

        _socket_type = _Socket_Type.VALUE

        _identifier = 'buffer_factor'

        use_denoise: bool = True

        node_label: str = ''


        def _get_setup_context(self):
            if hasattr(bpy.context.scene.render.bake, 'margin_type'):
                return bpy_context.Bpy_State([
                    (bpy.context.scene.render.bake, 'margin', 1),
                    (bpy.context.scene.render.bake, 'margin_type', 'ADJACENT_FACES'),
                ])
            else:
                return bpy_context.Bpy_State([(bpy.context.scene.render.bake, 'margin', 1)])


        def _get_material_context(self, material: 'bpy.types.Material'):
            return _Output_Label(material, self.node_label)


        def _get_compositor_context(self, input_socket, images, channel):

            if isinstance(images, bpy.types.Image):
                image = images
            else:
                image = images[0]

            return bpy_context.Compositor_Input_Factor(input_socket, image, channel, use_denoise=self.use_denoise)

@dataclass
class Normal_Native(_Bake_Type, tool_settings.Settings):
    """ The native Normal bake type. Use for baking from selected to active. """

    _default_color = (0.5, 0.5, 1.0)

    _socket_type = _Socket_Type.SHADER
    _identifier = 'Normal'

    use_denoise: bool = False
    use_remove_inward_normals: bool = False
    denoise_mix_factor: float = 1.0


    def _get_setup_context(self):
        return bpy_context.Bpy_State([(bpy.context.scene.cycles, 'bake_type', 'NORMAL')])


    def _get_compositor_context(self, input_socket, images, channel):

        if isinstance(images, bpy.types.Image):
            image = images
        else:
            image = images[0]

        return bpy_context.Compositor_Input_Normal(
            input_socket,
            image,
            use_denoise = self.use_denoise,
            use_remove_inward_normals = self.use_remove_inward_normals,
            denoise_mix_factor = self.denoise_mix_factor,
        )


@dataclass
class Combined(_Bake_Type, tool_settings.Settings):


    _socket_type = _Socket_Type.SHADER
    _identifier = 'Combined'
    _default_color = (0.5, 0.5, 0.5)

    _is_srgb = True

    use_pass_direct: bool = True
    use_pass_indirect: bool = True
    use_pass_diffuse: bool = True
    use_pass_glossy: bool = True
    use_pass_transmission: bool = True
    use_pass_emit: bool = True

    use_denoise: bool = True


    samples: int = 16
    """
    A number of render samples.

    #### Default: `16`
    """


    def _get_setup_context(self):

        settings = [(bpy.context.scene.cycles, 'bake_type', 'COMBINED')]

        for name in ['use_pass_direct', 'use_pass_indirect', 'use_pass_diffuse', 'use_pass_glossy', 'use_pass_transmission', 'use_pass_emit']:
            if name in self._has_been_set:
                settings.append((bpy.context.scene.render.bake, name, getattr(self, name)))

        if 'samples' in self._has_been_set:
            settings.append((bpy.context.scene.cycles, 'samples', self.samples))

        if self.use_denoise:
            settings.append((bpy.context.scene.render.bake, 'margin', get_margin()))

        return bpy_context.Bpy_State(settings)


@dataclass
class AO_Native(_Bake_Type, tool_settings.Settings):

    _socket_type = _Socket_Type.SHADER

    _identifier = 'Ambient Occlusion'
    _default_color = (1.0, 1.0, 1.0)

    use_denoise: bool = True

    samples: int = 16
    """
    A number of render samples.

    #### Default: `16`
    """

    def _get_setup_context(self):

        settings = [(bpy.context.scene.cycles, 'bake_type', 'AO')]

        if 'samples' in self._has_been_set:
            settings.append((bpy.context.scene.cycles, 'samples', self.samples))

        if self.use_denoise:
            settings.append((bpy.context.scene.render.bake, 'margin', get_margin()))

        return bpy_context.Bpy_State(settings)
