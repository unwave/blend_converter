import typing
import os
import tempfile
import uuid
import textwrap
import inspect


from .. import common
from . import remote_execution_handler
from .. import utils
from .. import fbx


SCRIPT_RUNNER_PATH = os.path.join(utils.ROOT_DIR, 'format', 'unreal', 'script_runner.py')


def runner_bootstrap(script_runner_path: str, data: dict):

    import sys
    import os
    import importlib
    import importlib.util

    module_name = os.path.splitext(os.path.basename(script_runner_path))[0]

    spec = importlib.util.spec_from_file_location(module_name, script_runner_path)

    module = importlib.util.module_from_spec(spec)

    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    getattr(module, 'run')(data)


T = typing.TypeVar('T')

if typing.TYPE_CHECKING:
    from typing_extensions import ParamSpec
    P = ParamSpec('P')
else:
    class Fake_ParamSpec:
        args = None
        kwargs = None
    P = Fake_ParamSpec()




class Unreal(common.Generic_Exporter):
    """ Needs an open Unreal Engine instance. """

    _file_extension = 'unreal'


    def __init__(self, blend_path: str, result_dir: str):
        super().__init__(blend_path, result_dir)

        self.unreal_scripts = []

        self.fbx_settings = fbx.Settings_Fbx()


    def get_current_stats(self):

        stats = {}

        stats['blend_stat'] = common.get_file_stat(self.blend_path)

        stats['blender_executable_stat'] = common.get_file_stat(self.blender_executable)

        stats['scripts'] = self._get_scripts()

        stats['unreal_scripts'] = self._get_unreal_scripts()

        return stats


    def get_json_stats(self):

        info = self.get_json()

        stats = {}

        stats['blend_stat'] = info.get('blend_stat')

        stats['blender_executable_stat'] = common.get_file_stat(self.blender_executable)

        stats['scripts'] = self._get_scripts()

        stats['unreal_scripts'] = info.get('unreal_scripts')

        return stats


    @property
    def fbx_path(self):
        return os.path.realpath(os.path.join(self.result_dir, self.stem + '.fbx'))


    def get_fbx_export_script(self):
        return self._get_function_script(fbx.export_fbx.export_fbx, dict(filepath = self.fbx_path, **self.fbx_settings._to_dict()))


    def _get_scripts(self):
        return self.scripts + [self.get_fbx_export_script()]


    def _get_unreal_scripts(self):
        return self.unreal_scripts


    @staticmethod
    def _get_unreal_function_script(func: typing.Callable, *args, **kwargs):
        filepath = os.path.realpath(func.__code__.co_filename)
        return {
            'filepath': filepath,
            'name': func.__name__,
            'args': list(args),
            'kwargs': kwargs,
            'sha256': utils.get_function_sha256(func),
            'code': textwrap.dedent(inspect.getsource(func)),
        }


    def run_unreal(self, func: 'typing.Callable[P, T]', *args: P.args, **kwargs: P.kwargs) -> T:
        """
        The function will be executed inside an Unreal instance.

        `args` and `kwargs` must be JSON serializable.
        """

        script = self._get_unreal_function_script(func, *args, **kwargs)

        self.unreal_scripts.append(script)

        return script


    def update(self, forced = False):

        if not (forced or self.needs_update):
            return

        if self.blender_executable is None:
            raise Exception('Blender executable is not specified.')


        os.makedirs(os.path.dirname(self.result_path), exist_ok = True)

        with tempfile.TemporaryDirectory() as temp_dir:

            self.return_values_file = os.path.join(temp_dir, uuid.uuid1().hex)
            self._run_blender()



        def set_result(args: typing.Union[list, dict]):
            """ Provide result of the Blender function to Unreal functions. """

            args = args.copy()

            if isinstance(args, list):
                for arg in args:
                    if arg in self.scripts:
                        args[args.index(arg)] = self.result[self.scripts.index(arg)]
            elif isinstance(args, dict):
                for key, arg in args.items():
                    if arg in self.scripts:
                        args[key] = self.result[self.scripts.index(arg)]
            else:
                raise Exception(f"Unexpected args type: {args}")

            return args


        for script in self.unreal_scripts:
            set_result(script['args'])
            set_result(script['kwargs'])


        with remote_execution_handler.UE_Remote_Execution_Handler() as handler:
            utils.print_in_color(utils.get_color_code(96, 154, 247, 0,0,0), "UNREAL ENGINE EXECUTION")
            utils.print_in_color(utils.get_color_code(255, 139, 51, 0,0,0), "The output is delayed until all scripts are finished.")
            handler.exec_func(runner_bootstrap, SCRIPT_RUNNER_PATH, dict(scripts = self.unreal_scripts))


        self._write_final_json()
