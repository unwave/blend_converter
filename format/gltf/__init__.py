import typing

from .. import common
from . import export_gltf
from ... import tool_settings


if typing.TYPE_CHECKING:
    import dataclasses
else:
    class dataclasses:
        dataclass = lambda x: x


@dataclasses.dataclass
class Settings_GLTF(tool_settings.Settings):
    """
    The arguments for `bpy.ops.export_scene.gltf()`
    Version: `1.8.19`

    These are used if only explicitly specified.
    """


    check_existing: bool
    """
    Check Existing, Check and warn on overwriting existing files

    #### Default: `True`
    """

    export_format: typing.Union[int, str]
    """
    Format, Output format and embedding options. Binary is most efficient, but JSON (embedded or separate) may be easier to edit later
    * `GLB` glTF Binary (.glb) -- Exports a single file, with all data packed in binary form. Most efficient and portable, but more difficult to edit later.
    * `GLTF_SEPARATE` glTF Separate (.gltf + .bin + textures) -- Exports multiple files, with separate JSON, binary and texture data. Easiest to edit later.
    * `GLTF_EMBEDDED` glTF Embedded (.gltf) -- Exports a single file, with all data packed in JSON. Less efficient than binary, but easier to edit later.

    #### Default: `'GLB'`
    """

    ui_tab: typing.Union[int, str]
    """
    ui_tab, Export setting categories
    * `GENERAL` General -- General settings.
    * `MESHES` Meshes -- Mesh settings.
    * `OBJECTS` Objects -- Object settings.
    * `ANIMATION` Animation -- Animation settings.

    #### Default: `'GENERAL'`
    """

    export_copyright: str
    """
    Copyright, Legal rights and conditions for the model

    #### Default: `""`
    """

    export_image_format: typing.Union[int, str]
    """
    Images, Output format for images. PNG is lossless and generally preferred, but JPEG might be preferable for web applications due to the smaller file size. Alternatively they can be omitted if they are not needed
    * `AUTO` Automatic -- Save PNGs as PNGs and JPEGs as JPEGs. If neither one, use PNG.
    * `JPEG` JPEG Format (.jpg) -- Save images as JPEGs. (Images that need alpha are saved as PNGs though.) Be aware of a possible loss in quality.
    * `NONE` None -- Don't export images.

    #### Default: `'AUTO'`
    """

    export_texture_dir: str
    """
    Textures, Folder to place texture files in. Relative to the .gltf file

    #### Default: `""`
    """

    export_keep_originals: bool
    """
    Keep original, Keep original textures files if possible.

    #### WARNING: if you use more than one texture, where pbr standard requires only one, only one texture will be used. This can lead to unexpected results

    #### Default: `False`
    """

    export_texcoords: bool
    """
    UVs, Export UVs (texture coordinates) with meshes

    #### Default: `True`
    """

    export_normals: bool
    """
    Normals, Export vertex normals with meshes

    #### Default: `True`
    """

    export_draco_mesh_compression_enable: bool
    """
    Draco mesh compression, Compress mesh using Draco

    #### Default: `False`
    """

    export_draco_mesh_compression_level: int
    """
    Compression level, Compression level (0 = most speed, 6 = most compression, higher values currently not supported)

    #### Default: `6`
    """

    export_draco_position_quantization: int
    """
    Position quantization bits, Quantization bits for position values (0 = no quantization)

    #### Default: `14`
    """

    export_draco_normal_quantization: int
    """
    Normal quantization bits, Quantization bits for normal values (0 = no quantization)

    #### Default: `10`
    """

    export_draco_texcoord_quantization: int
    """
    Texcoord quantization bits, Quantization bits for texture coordinate values (0 = no quantization)

    #### Default: `12`
    """

    export_draco_color_quantization: int
    """
    Color quantization bits, Quantization bits for color values (0 = no quantization)

    #### Default: `10`
    """

    export_draco_generic_quantization: int
    """
    Generic quantization bits, Quantization bits for generic coordinate values like weights or joints (0 = no quantization)

    #### Default: `12`
    """

    export_tangents: bool
    """
    Tangents, Export vertex tangents with meshes

    #### Default: `False`
    """

    export_materials: typing.Union[int, str]
    """
    Materials, Export materials
    * `EXPORT` Export -- Export all materials used by included objects.
    * `PLACEHOLDER` Placeholder -- Do not export materials, but write multiple primitive groups per mesh, keeping material slot information.
    * `NONE` No export -- Do not export materials, and combine mesh primitive groups, losing material slot information.

    #### Default: `'EXPORT'`
    """

    export_colors: bool
    """
    Vertex Colors, Export vertex colors with meshes

    #### Default: `True`
    """

    use_mesh_edges: bool
    """
    Loose Edges, Export loose edges as lines, using the material from the first material slot

    #### Default: `False`
    """

    use_mesh_vertices: bool
    """
    Loose Points, Export loose points as glTF points, using the material from the first material slot

    #### Default: `False`
    """

    export_cameras: bool
    """
    Cameras, Export cameras

    #### Default: `False`
    """

    use_selection: bool
    """
    Selected Objects, Export selected objects only

    #### Default: `False`
    """

    use_visible: bool
    """
    Visible Objects, Export visible objects only

    #### Default: `False`
    """

    use_renderable: bool
    """
    Renderable Objects, Export renderable objects only

    #### Default: `False`
    """

    use_active_collection: bool
    """
    Active Collection, Export objects in the active collection only

    #### Default: `False`
    """

    export_extras: bool
    """
    Custom Properties, Export custom properties as glTF extras

    #### Default: `False`
    """

    export_yup: bool
    """
    +Y Up, Export using glTF convention, +Y up

    #### Default: `True`
    """

    export_apply: bool
    """
    Apply Modifiers, Apply modifiers (excluding Armatures) to mesh objects

    #### WARNING: prevents exporting shape keys

    #### Default: `False`
    """

    export_animations: bool
    """

    Animations, Exports active actions and NLA tracks as glTF animations

    #### Default: `True`
    """

    export_frame_range: bool
    """
    Limit to Playback Range, Clips animations to selected playback range

    #### Default: `True`
    """

    export_frame_step: int
    """
    Sampling Rate, How often to evaluate animated values (in frames)

    #### Default: `1`
    """

    export_force_sampling: bool
    """
    Always Sample Animations, Apply sampling to all animations

    #### Default: `True`
    """

    export_nla_strips: bool
    """
    Group by NLA Track, When on, multiple actions become part of the same glTF animation if they're pushed onto NLA tracks with the same name. When off, all the currently assigned actions become one glTF animation

    #### Default: `True`
    """

    export_def_bones: bool
    """
    Export Deformation Bones Only, Export Deformation bones only (and needed bones for hierarchy)

    #### Default: `False`
    """

    optimize_animation_size: bool
    """
    Optimize Animation Size, Reduce exported file-size by removing duplicate keyframes Can cause problems with stepped animation

    #### Default: `False`
    """

    export_current_frame: bool
    """
    Use Current Frame, Export the scene in the current animation frame

    #### Default: `False`
    """

    export_skins: bool
    """
    Skinning, Export skinning (armature) data

    #### Default: `True`
    """

    export_all_influences: bool
    """
    Include All Bone Influences, Allow >4 joint vertex influences. Models may appear incorrectly in many viewers

    #### Default: `False`
    """

    export_morph: bool
    """
    Shape Keys, Export shape keys (morph targets)

    #### Default: `True`
    """

    export_morph_normal: bool
    """
    Shape Key Normals, Export vertex normals with shape keys (morph targets)

    #### Default: `True`
    """

    export_morph_tangent: bool
    """
    Shape Key Tangents, Export vertex tangents with shape keys (morph targets)

    #### Default: `False`
    """

    export_lights: bool
    """
    Punctual Lights, Export directional, point, and spot lights. Uses "KHR_lights_punctual" glTF extension

    #### Default: `False`
    """

    export_displacement: bool
    """
    Displacement Textures (EXPERIMENTAL)

    #### EXPERIMENTAL: Export displacement textures. Uses incomplete "KHR_materials_displacement" glTF extension

    #### Default: `False`
    """

    will_save_settings: bool
    """
    Remember Export Settings, Store glTF export settings in the Blender project

    #### Default: `False`
    """

    filter_glob: str
    """
    filter_glob, Blender's file dialog setting

    #### Default: `"*.glb;*.gltf"`
    """



class Gltf(common.Generic_Exporter):
    """ `.blend` to `.gltf` handler """

    settings: Settings_GLTF

    @property
    def _file_extension(self):
        if getattr(self.settings, 'export_format', 'GLB') == 'GLB':
            return 'glb'
        else:
            return 'gltf'

    def __init__(self, source_path: str, result_dir: str, **kwargs):
        super().__init__(source_path, result_dir, **kwargs)

        self.settings = Settings_GLTF()
        """
        The arguments for `bpy.ops.export_scene.gltf()`
        Version: `1.8.19`
        """

    def get_export_script(self):
        return self._get_function_script(export_gltf.export_gltf, dict(filepath = self.result_path, **self.settings._to_dict()))
