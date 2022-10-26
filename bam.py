import typing
import uuid
import tempfile
import os

from . import common
from . import utils



DIR = os.path.dirname(__file__)
BLENDER_EXPORT_GLTF = os.path.join(DIR, 'scripts', 'blender_export_gltf.py')


class Settings_Blender_GLTF(common.Settings):
    """
    The arguments for `bpy.ops.export_scene.gltf()` 
    Version: `1.8.19`
    
    These are used if only explicitly specified.
    """

    filepath: str
    """
    File Path, Filepath used for exporting the file

    #### Default:
    * `blender`: `""`
    """

    check_existing: bool
    """
    Check Existing, Check and warn on overwriting existing files

    #### Default:
    * `blender`: `True`
    """

    export_format: typing.Union[int, str]
    """
    Format, Output format and embedding options. Binary is most efficient, but JSON (embedded or separate) may be easier to edit later 
    * `GLB` glTF Binary (.glb) -- Exports a single file, with all data packed in binary form. Most efficient and portable, but more difficult to edit later. 
    * `GLTF_SEPARATE` glTF Separate (.gltf + .bin + textures) -- Exports multiple files, with separate JSON, binary and texture data. Easiest to edit later. 
    * `GLTF_EMBEDDED` glTF Embedded (.gltf) -- Exports a single file, with all data packed in JSON. Less efficient than binary, but easier to edit later.

    #### Default:
    * `blender`: `'GLB'`
    * `blend2bam`: `'GLTF_EMBEDDED' if settings['textures'] == 'embed' else 'GLTF_SEPARATE'`
    """

    ui_tab: typing.Union[int, str]
    """
    ui_tab, Export setting categories 
    * `GENERAL` General -- General settings. 
    * `MESHES` Meshes -- Mesh settings. 
    * `OBJECTS` Objects -- Object settings. 
    * `ANIMATION` Animation -- Animation settings.

    #### Default:
    * `blender`: `'GENERAL'`
    """

    export_copyright: str
    """
    Copyright, Legal rights and conditions for the model

    #### Default:
    * `blender`: `""`
    """

    export_image_format: typing.Union[int, str]
    """
    Images, Output format for images. PNG is lossless and generally preferred, but JPEG might be preferable for web applications due to the smaller file size. Alternatively they can be omitted if they are not needed
    * `AUTO` Automatic -- Save PNGs as PNGs and JPEGs as JPEGs. If neither one, use PNG. 
    * `JPEG` JPEG Format (.jpg) -- Save images as JPEGs. (Images that need alpha are saved as PNGs though.) Be aware of a possible loss in quality.
    * `NONE` None -- Don't export images.

    #### Default:
    * `blender`: `'AUTO'`
    """

    export_texture_dir: str
    """
    Textures, Folder to place texture files in. Relative to the .gltf file

    #### Default:
    * `blender`: `""`
    """

    export_keep_originals: bool
    """
    Keep original, Keep original textures files if possible. 
    
    #### WARNING: if you use more than one texture, where pbr standard requires only one, only one texture will be used. This can lead to unexpected results

    #### Default:
    * `blender`: `False`
    """

    export_texcoords: bool
    """
    UVs, Export UVs (texture coordinates) with meshes

    #### Default:
    * `blender`: `True`
    """

    export_normals: bool
    """
    Normals, Export vertex normals with meshes

    #### Default:
    * `blender`: `True`
    """

    export_draco_mesh_compression_enable: bool
    """
    Draco mesh compression, Compress mesh using Draco

    #### Default:
    * `blender`: `False`
    """

    export_draco_mesh_compression_level: int
    """
    Compression level, Compression level (0 = most speed, 6 = most compression, higher values currently not supported)

    #### Default:
    * `blender`: `6`
    """

    export_draco_position_quantization: int
    """
    Position quantization bits, Quantization bits for position values (0 = no quantization)

    #### Default:
    * `blender`: `14`
    """

    export_draco_normal_quantization: int
    """
    Normal quantization bits, Quantization bits for normal values (0 = no quantization)

    #### Default:
    * `blender`: `10`
    """

    export_draco_texcoord_quantization: int
    """
    Texcoord quantization bits, Quantization bits for texture coordinate values (0 = no quantization)

    #### Default:
    * `blender`: `12`
    """

    export_draco_color_quantization: int
    """
    Color quantization bits, Quantization bits for color values (0 = no quantization)

    #### Default:
    * `blender`: `10`
    """

    export_draco_generic_quantization: int
    """
    Generic quantization bits, Quantization bits for generic coordinate values like weights or joints (0 = no quantization)

    #### Default:
    * `blender`: `12`
    """

    export_tangents: bool
    """
    Tangents, Export vertex tangents with meshes

    #### Default:
    * `blender`: `False`
    * `blend2bam`: `True`
    """

    export_materials: typing.Union[int, str]
    """
    Materials, Export materials 
    * `EXPORT` Export -- Export all materials used by included objects. 
    * `PLACEHOLDER` Placeholder -- Do not export materials, but write multiple primitive groups per mesh, keeping material slot information. 
    * `NONE` No export -- Do not export materials, and combine mesh primitive groups, losing material slot information.

    #### Default:
    * `blender`: `'EXPORT'`
    """

    export_colors: bool
    """
    Vertex Colors, Export vertex colors with meshes

    #### Default:
    * `blender`: `True`
    """

    use_mesh_edges: bool
    """
    Loose Edges, Export loose edges as lines, using the material from the first material slot

    #### Default:
    * `blender`: `False`
    """

    use_mesh_vertices: bool
    """
    Loose Points, Export loose points as glTF points, using the material from the first material slot

    #### Default:
    * `blender`: `False`
    """

    export_cameras: bool
    """
    Cameras, Export cameras

    #### Default:
    * `blender`: `False`
    * `blend2bam`: `True`
    """

    use_selection: bool
    """
    Selected Objects, Export selected objects only

    #### Default:
    * `blender`: `False`
    """

    use_visible: bool
    """
    Visible Objects, Export visible objects only

    #### Default:
    * `blender`: `False`
    """

    use_renderable: bool
    """
    Renderable Objects, Export renderable objects only

    #### Default:
    * `blender`: `False`
    """

    use_active_collection: bool
    """
    Active Collection, Export objects in the active collection only

    #### Default:
    * `blender`: `False`
    """

    export_extras: bool
    """
    Custom Properties, Export custom properties as glTF extras

    #### Default:
    * `blender`: `False`
    * `blend2bam`: `True`
    """

    export_yup: bool
    """
    +Y Up, Export using glTF convention, +Y up

    #### Default: 
    * `blender`: `True`
    * `blend2bam`: `False`
    """

    export_apply: bool
    """
    Apply Modifiers, Apply modifiers (excluding Armatures) to mesh objects 
    
    #### WARNING: prevents exporting shape keys

    #### Default:
    * `blender`: `False`
    * `blend2bam`: `True`
    """

    export_animations: bool
    """

    Animations, Exports active actions and NLA tracks as glTF animations

    #### Default:
    * `blender`: `True`
    * `blend2bam`: `settings['animations'] != 'skip'`
    """

    export_frame_range: bool
    """
    Limit to Playback Range, Clips animations to selected playback range

    #### Default:
    * `blender`: `True`
    """

    export_frame_step: int
    """
    Sampling Rate, How often to evaluate animated values (in frames)

    #### Default:
    * `blender`: `1`
    """

    export_force_sampling: bool
    """
    Always Sample Animations, Apply sampling to all animations

    #### Default:
    * `blender`: `True`
    * `blend2bam`: `True`
    """

    export_nla_strips: bool
    """
    Group by NLA Track, When on, multiple actions become part of the same glTF animation if they're pushed onto NLA tracks with the same name. When off, all the currently assigned actions become one glTF animation

    #### Default:
    * `blender`: `True`
    """

    export_def_bones: bool
    """
    Export Deformation Bones Only, Export Deformation bones only (and needed bones for hierarchy)

    #### Default:
    * `blender`: `False`
    """

    optimize_animation_size: bool
    """
    Optimize Animation Size, Reduce exported file-size by removing duplicate keyframes Can cause problems with stepped animation
    
    #### Default:
    * `blender`: `False`
    """

    export_current_frame: bool
    """
    Use Current Frame, Export the scene in the current animation frame

    #### Default:
    * `blender`: `False`
    """

    export_skins: bool
    """
    Skinning, Export skinning (armature) data

    #### Default:
    * `blender`: `True`
    """

    export_all_influences: bool
    """
    Include All Bone Influences, Allow >4 joint vertex influences. Models may appear incorrectly in many viewers

    #### Default:
    * `blender`: `False`
    """

    export_morph: bool
    """
    Shape Keys, Export shape keys (morph targets)

    #### Default:
    * `blender`: `True`
    """

    export_morph_normal: bool
    """
    Shape Key Normals, Export vertex normals with shape keys (morph targets)

    #### Default:
    * `blender`: `True`
    """

    export_morph_tangent: bool
    """
    Shape Key Tangents, Export vertex tangents with shape keys (morph targets)

    #### Default:
    * `blender`: `False`
    """

    export_lights: bool
    """
    Punctual Lights, Export directional, point, and spot lights. Uses "KHR_lights_punctual" glTF extension

    #### Default:
    * `blender`: `False`
    * `blend2bam`: `True`
    """

    export_displacement: bool
    """
    Displacement Textures (EXPERIMENTAL)
    
    #### EXPERIMENTAL: Export displacement textures. Uses incomplete "KHR_materials_displacement" glTF extension

    #### Default:
    * `blender`: `False`
    """

    will_save_settings: bool
    """
    Remember Export Settings, Store glTF export settings in the Blender project

    #### Default:
    * `blender`: `False`
    """

    filter_glob: str
    """
    filter_glob, Blender's file dialog setting

    #### Default:
    * `blender`: `"*.glb;*.gltf"`
    """


class Settings_GLTF(common.Settings):
    """ `blend2bam`'s .blend to .bam settings """

    physics_engine = 'builtin' 
    """
    The physics engine to build collision solids for: `builtin` or `bullet`.

    #### Default: `builtin`
    """

    print_scene = False 
    """
    Print the converted scene graph to stdout.

    #### Default: `False`
    """

    skip_axis_conversion = True 
    """
    Do not perform axis-conversion (useful if glTF data is already Z-Up).

    #### Default: `True`
    """

    no_srgb = False 
    """
    Do not load textures as sRGB textures (only for glTF pipelines).

    If `False`: do not load textures as sRGB.

    #### Default: `False`
    """

    textures = 'ref' 
    """
    How to handle external textures: `ref` or `copy` or `embed`.

    If `ref`: reference external textures.

    #### Default: `ref`
    """

    legacy_materials = False 
    """
    If `False`, use PBR materials.

    #### Default: `False`
    """

    animations = 'embed' 
    """
    How to handle animation data: `embed` or `separate` or `skip`.

    If `embed`: keep animations in the same BAM file.

    #### Default: `embed`
    """

    invisible_collisions_collection = 'InvisibleCollisions' 
    """
    Name of a collection in blender whose collision objects will be exported without a visible geom node.

    #### Default: `InvisibleCollisions`
    """


class Bam(common.Blend):
    """ Lazy evaluated `.blend` to `.bam` handler """

    _file_extension = 'bam'

    def __init__(self, blend_path: str, target_dir: str):
        """
        Parameters
        ----------
        blend_path: `.blend` file path

        target_dir: directory where `.bam` files will be placed
        """

        super().__init__(blend_path, target_dir)

        self.settings_gltf = Settings_GLTF()
        """ `blend2bam`'s .blend to .bam settings """

        self.settings_blender_gltf = Settings_Blender_GLTF()
        """
        The arguments for `bpy.ops.export_scene.gltf()` 
        Version: `1.8.19`
        
        These are used if only are explicitly specified.
        """

        self._args_pre_gltf = []
        self._args_post_gltf = []

        self._scripts_post_bam: typing.List[common.Script] = []
        

    @property
    def args_pre_gltf(self):
        """ Blender's command line arguments before the glTF export """
        return self._unwrap_args(self._args_pre_gltf)

    @property
    def args_post_gltf(self):
        """ Blender's command line arguments after the glTF export before the `.bam` file export """
        return self._unwrap_args(self._args_post_gltf)

    @property
    def scripts_post_bam(self):
        """ The scripts that run after the `.bam` file export """
        return [script._script for script in self._scripts_post_bam]


    def attach_pre_gltf_script(self, func: typing.Callable, *args, **kwargs):
        """
        The scrip will be executed before the glTF export.

        By default:
        `func` must not use the scope where it was declared, as it will be evaluated in isolation.
        `args` and `kwargs` must be JSON serializable.
        Set `script.use_dill = True` to use `uqfoundation/dill` to bypass that.
        """

        script = common.Script(func, args, kwargs)
        self._args_pre_gltf.append(script)

        return script

    def attach_post_gltf_script(self, func: typing.Callable, *args, **kwargs):
        """
        The scrip will be executed after the glTF export before the `.bam` file export.

        By default:
        `func` must not use the scope where it is declared, as it will be evaluated in isolation.
        `args` and `kwargs` must be JSON serializable.
        Set `script.use_dill = True` to use `uqfoundation/dill` to bypass that.
        """

        script = common.Script(func, args, kwargs)
        self._args_post_gltf.append(script)

        return script

    def attach_post_bam_script(self, func: typing.Callable, *args, **kwargs):
        """
        The scrip will be executed after the `.bam` file export.

        `func` must not use the scope where it is declared. As it will be evaluated in isolation.

        `args` and `kwargs` must be JSON serializable.
        """

        script = common.Script(func, args, kwargs)
        self._scripts_post_bam.append(script)

        return script


    def _get_gltf_os_path(self, temp_dir: str):
        return os.path.join(temp_dir, self.stem + str(uuid.uuid4()) + '.gltf')

    @property
    def needs_update(self):

        if not os.path.exists(self.os_path_target):
            return True

        settings = self.file_settings

        if settings.get('blend_stat') != self._get_blend_stat():
            return True

        if settings.get('settings_gltf') != self.settings_gltf._dict:
            return True

        if settings.get('settings_blender_gltf') != self.settings_blender_gltf._dict:
            return True

        if settings.get('args_pre_gltf') != self.args_pre_gltf:
            return True

        if settings.get('args_post_gltf') != self.args_post_gltf:
            return True

        if settings.get('scripts_post_bam') != self.scripts_post_bam:
            return True

        return False


    def _get_job_gltf(self, gltf_path):
        return {
            'dst': gltf_path,
            'bam_dst': self.os_path_target,
            'settings_gltf': self.settings_gltf._dict,
            'settings_blender_gltf': self.settings_blender_gltf._dict
        }

    def _get_gltf_commands(self, gltf_path):
        return [
            self.blend_path,

            '--python-expr',
            self._get_job_expr(self._get_job_gltf(gltf_path)),

            *self.args_pre_gltf,

            '--python',
            BLENDER_EXPORT_GLTF,

            *self.args_post_gltf,
        ]

    def _write_json(self):
        super()._write_json({
            'settings_gltf': self.settings_gltf._dict,
            'settings_blender_gltf': self.settings_blender_gltf._dict,
            'args_pre_gltf': self.args_pre_gltf,
            'args_post_gltf': self.args_post_gltf,
            'scripts_post_bam': self.scripts_post_bam
        })

    def update(self, forced = False):

        if not (self.needs_update or forced):
            return
            
        with tempfile.TemporaryDirectory() as temp_dir:

            gltf_path = self._get_gltf_os_path(temp_dir)
            arguments = self._get_gltf_commands(gltf_path)
            utils.run_blender(arguments, stdout = self.blender_stdout, blender_binary = self.blender_binary)

            os.makedirs(os.path.dirname(self.os_path_target), exist_ok = True)

            from gltf import converter
            settings = converter.GltfSettings(**utils.get_common_attrs(self.settings_gltf, converter.GltfSettings))

            # prevents :express(warning): Filename is incorrect case: and writing extra .bam.pz if the file exists
            os_path_target = os.path.realpath(self.os_path_target)

            converter.convert(gltf_path, os_path_target, settings)

        for script in self._scripts_post_bam:
            script.execute()

        self._write_json()