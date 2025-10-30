import typing
import uuid
import tempfile
import os
import json
import traceback
import sys


from .. import common
from ... import utils
from .. import gltf
from ... import tool_settings


if typing.TYPE_CHECKING:
    import dataclasses
else:
    class dataclasses:
        dataclass = lambda x: x


BLENDER_EXPORT_GLTF = os.path.join(os.path.dirname(__file__), 'export_gltf.py')


@dataclasses.dataclass
class Settings_Blender_Gltf(gltf.Settings_GLTF):


    export_format: typing.Union[int, str]
    """
    Format, Output format and embedding options. Binary is most efficient, but JSON (embedded or separate) may be easier to edit later
    * `GLB` glTF Binary (.glb) -- Exports a single file, with all data packed in binary form. Most efficient and portable, but more difficult to edit later.
    * `GLTF_SEPARATE` glTF Separate (.gltf + .bin + textures) -- Exports multiple files, with separate JSON, binary and texture data. Easiest to edit later.
    * `GLTF_EMBEDDED` glTF Embedded (.gltf) -- Exports a single file, with all data packed in JSON. Less efficient than binary, but easier to edit later.

    #### Default:
    * `blender`: `'GLB'`
    * `panda3d-gltf`: `'GLTF_EMBEDDED' if settings['textures'] == 'embed' else 'GLTF_SEPARATE'`
    """

    export_tangents: bool
    """
    Tangents, Export vertex tangents with meshes

    #### Default:
    * `blender`: `False`
    * `panda3d-gltf`: `True`
    """

    export_cameras: bool
    """
    Cameras, Export cameras

    #### Default:
    * `blender`: `False`
    * `panda3d-gltf`: `True`
    """

    export_extras: bool
    """
    Custom Properties, Export custom properties as glTF extras

    #### Default:
    * `blender`: `False`
    * `panda3d-gltf`: `True`
    """

    export_yup: bool
    """
    +Y Up, Export using glTF convention, +Y up

    #### Default:
    * `blender`: `True`
    * `panda3d-gltf`: `False`
    """

    export_apply: bool
    """
    Apply Modifiers, Apply modifiers (excluding Armatures) to mesh objects

    #### WARNING: prevents exporting shape keys

    #### Default:
    * `blender`: `False`
    * `panda3d-gltf`: `True`
    """

    export_animations: bool
    """

    Animations, Exports active actions and NLA tracks as glTF animations

    #### Default:
    * `blender`: `True`
    * `panda3d-gltf`: `settings['animations'] != 'skip'`
    """

    export_force_sampling: bool
    """
    Always Sample Animations, Apply sampling to all animations

    #### Default:
    * `blender`: `True`
    * `panda3d-gltf`: `True`
    """

    export_lights: bool
    """
    Punctual Lights, Export directional, point, and spot lights. Uses "KHR_lights_punctual" glTF extension

    #### Default:
    * `blender`: `False`
    * `panda3d-gltf`: `True`
    """


@dataclasses.dataclass
class Settings_Gltf_2_Bam(tool_settings.Settings):
    """ `panda3d-gltf`'s .gltf to .bam settings """


    collision_shapes: str = 'builtin'
    """
    The physics engine to build collision solids for: `'builtin'` or `'bullet'`.

    #### Default: `'builtin'`
    `cmd`: `--collision-shapes`
    """

    print_scene: bool = False
    """
    Print the converted scene graph to stdout.

    #### Default: `False`
    `cmd`: `--print-scene`
    """

    skip_axis_conversion: bool = False
    """
    Do not perform axis-conversion (useful if glTF data is already Z-Up).

    #### Default: `False`
    `cmd`: `--skip-axis-conversion`
    """

    no_srgb: bool = False
    """
    Do not load textures as sRGB textures (only for glTF pipelines).

    If `False`: do not load textures as sRGB.

    #### Default: `False`
    `cmd`: `--no-srgb`
    """

    textures: str = 'ref'
    """
    How to handle external textures: `'ref'` or `'copy'`.

    * `ref`: ref — reference external textures
    * `copy`: copy — copy textures

    embedded textures will remain embedded

    #### Default: `'ref'`
    `cmd`: `--textures`
    """

    legacy_materials: bool = False
    """
    If `False`, use PBR materials.

    #### Default: `False`
    `cmd`: `--legacy-materials`
    """

    animations: str = 'embed'
    """
    How to handle animation data: `'embed'` or `'separate'` or `'skip'`.

    If `embed`: keep animations in the same BAM file.

    #### Default: `'embed'`
    `cmd`: `--animations`
    """

    flatten_nodes: bool = False
    """
    Attempt to flatten resulting node structure.

    #### Default: `False`
    `cmd`: `--flatten-nodes`
    """

    invisible_collisions_collection: str = 'InvisibleCollisions'
    """
    Name of a collection in blender whose collision objects will be exported without a visible geom node.

    #### Default: `InvisibleCollisions`
    """


    def _get_cli_command(self):

        command: typing.List[str] = []

        for key, value in self._to_dict().items():

            if key in ('invisible_collisions_collection', 'allow_double_sided_materials'):
                continue

            argument = f"--{key.replace('_', '-')}"

            if isinstance(value, bool):
                if value:
                    command.append(argument)
            elif isinstance(value, str):
                command.append(argument)
                command.append(value)
            else:
                raise Exception(f"Unexpected attribute: {key} {value}")

        return command



class Panda3D_Path_Mixin(object if not typing.TYPE_CHECKING else typing.Protocol):

    @property
    def result_path(args) -> str: ...

    @property
    def path_panda(self):
        """ Panda 3D style path """
        from panda3d.core import Filename
        return Filename.from_os_specific(self.result_path)

    def get_relpath_panda(self, start: str):
        """ Panda 3D style relative path """
        from panda3d.core import Filename
        return Filename.from_os_specific(self.result_path).make_relative_to(Filename.from_os_specific(start))


class Bam_Edit:

    def __init__(self, bam_path: str):
        self.bam_path = bam_path

    def __enter__(self):

        from panda3d import core

        loader: core.Loader = core.Loader.get_global_ptr()
        flags = core.LoaderOptions(core.LoaderOptions.LF_no_cache)

        bam_path = core.Filename.from_os_specific(self.bam_path)
        panda_node = loader.load_sync(bam_path, flags)

        self.root_node = core.NodePath(panda_node)

        return self.root_node

    def __exit__(self , type, value, traceback):

        from panda3d import core

        is_success = self.root_node.write_bam_file(core.Filename.from_os_specific(self.bam_path))
        if not is_success:
            raise Exception(f'Error writing file: {self.bam_path}')


class Bam(common.Generic_Exporter, Panda3D_Path_Mixin):
    """ `.blend` to `.bam` handler """

    _file_extension = 'bam'


    @property
    def _gltf_file_extension(self):
        if getattr(self.gltf_settings, 'export_format', 'GLB') == 'GLB':
            return 'glb'
        else:
            return 'gltf'


    def __init__(self, source_path: str, result_dir: str, **kwargs):
        super().__init__(source_path, result_dir, **kwargs)

        self.gltf2bam_settings = Settings_Gltf_2_Bam()
        """ `panda3d-gltf`'s `.gltf` to `.bam` settings """

        self.gltf2bam_settings.skip_axis_conversion = True


        self.gltf_settings = Settings_Blender_Gltf()
        """
        The arguments for `bpy.ops.export_scene.gltf()`
        Version: `1.8.19`
        """

        self.gltf_settings.export_format = 'GLTF_SEPARATE'
        self.gltf_settings.export_cameras = True
        self.gltf_settings.export_extras = True
        self.gltf_settings.export_yup = False
        self.gltf_settings.export_lights = True
        self.gltf_settings.export_force_sampling = True
        self.gltf_settings.export_apply = True
        self.gltf_settings.export_tangents = True

        self.bam_scripts = []
        """ Scripts added with `run_bam_function`. """


    def run_bam_function(self, func: typing.Callable, *args, **kwargs):
        """
        The function will be executed after the `.bam` file export.

        `args` and `kwargs` must be JSON serializable.

        The function should have one first positional parameter reserved for `panda3d.core.ModelRoot`.
        """

        script = self._get_function_script(func, *args, **kwargs)

        self.bam_scripts.append(script)

        return script


    def get_current_stats(self):

        stats = {}

        stats['result_file_exists'] = os.path.exists(self.result_path)

        stats['blend_stat'] = common.get_file_stat(self.blend_path)

        stats['blender_executable_stat'] = common.get_file_stat(self.blender_executable)

        stats['scripts'] = self._get_scripts()

        stats['bam_scripts'] = self.bam_scripts

        return stats


    def get_json_stats(self):

        info = self.get_json()

        stats = {}

        stats['result_file_exists'] = True

        stats['blend_stat'] = info.get('blend_stat')

        stats['blender_executable_stat'] = info.get('blender_executable_stat')

        stats['scripts'] = info.get('scripts')

        stats['bam_scripts'] = info.get('bam_scripts')

        return stats


    def get_export_script(self):
        return self._get_module_script(
            BLENDER_EXPORT_GLTF,
            bam_path = self.result_path,
            gltf2bam_settings = self.gltf2bam_settings,
            gltf_settings = self.gltf_settings,
        )


    def update(self, forced = False):

        if not (forced or self.needs_update):
            return

        if self.blender_executable is None:
            raise Exception('Blender executable is not specified.')


        os.makedirs(os.path.dirname(self.result_path), exist_ok = True)

        with tempfile.TemporaryDirectory(prefix = self.stem, dir = utils.get_same_drive_tmp_dir(self.result_path)) as temp_dir:

            # The gltf path is different every time. Passed as a builtin value.
            gltf_path = os.path.join(temp_dir, self.stem + '_' + str(uuid.uuid1()) + '.' + self._gltf_file_extension)

            self.return_values_file = os.path.join(temp_dir, uuid.uuid1().hex)

            self._run_blender(__GLTF_PATH__ = gltf_path)

            # prevents :express(warning): Filename is incorrect case: and writing extra .bam.pz if the file exists
            bam_path = os.path.realpath(self.result_path)

            cmd = ['gltf2bam', gltf_path, bam_path, *self.gltf2bam_settings._get_cli_command()]

            print("CMD:", utils.get_command_from_list(cmd))

            import subprocess
            subprocess.run(cmd, text=True, check=True)


        bam_scripts_results = {}

        def set_result(args: typing.Union[list, dict]):
            """ Substitute previous function return values. """

            args = args.copy()

            if isinstance(args, list):
                for arg in args:
                    if arg in self.scripts:
                        args[args.index(arg)] = self.result[self.scripts.index(arg)]
                    elif arg in self.bam_scripts:
                        args[args.index(arg)] = bam_scripts_results[self.bam_scripts.index(arg)]
            elif isinstance(args, dict):
                for key, arg in args.items():
                    if arg in self.scripts:
                        args[key] = self.result[self.scripts.index(arg)]
                    elif arg in self.bam_scripts:
                        args[key] = bam_scripts_results[self.bam_scripts.index(arg)]
            else:
                raise Exception(f"Unexpected args type: {args}")

            return args

        if self.bam_scripts:
            print('Editing the bam file. If panda3d.bullet is not imported in the editing process the bam will be written with losses.')
            with Bam_Edit(self.result_path) as model_root:
                for index, script in enumerate(self.bam_scripts):

                    try:
                        utils.print_in_color(utils.get_color_code(256,256,256, 0, 150, 255), 'SCRIPT:', script['name'], "...", flush=True)
                        module = utils.import_module_from_file(script['filepath'])
                        result = getattr(module, script['name'])(model_root, *set_result(script['args']), **set_result(script['kwargs']))
                    except Exception as e:

                        error_type, error_value, error_tb = sys.exc_info()

                        utils.print_in_color(utils.get_color_code(255,255,255,128,0,0,), f"Fail at script: {script['name']}", file=sys.stderr)
                        utils.print_in_color(utils.get_color_code(180,0,0,0,0,0,), ''.join(traceback.format_tb(error_tb)), file=sys.stderr)
                        utils.print_in_color(utils.get_color_code(255,255,255,128,0,0,), ''.join(traceback.format_exception_only(error_type, error_value)), file=sys.stderr)

                        raise SystemExit(1)


                    bam_scripts_results[index] = result

        self._write_final_json()


    def _write_final_json(self):
        self._write_json(scripts = self._get_scripts(), bam_scripts = self.bam_scripts)
