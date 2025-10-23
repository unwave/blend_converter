import time

start_time = time.perf_counter()
print("CONVERSION STARTED", time.strftime('%H:%M:%S %Y-%m-%d'))

import argparse
import functools
import importlib
import importlib.util
import json
import os
import sys
import traceback
import typing
import warnings
import builtins


DIR = os.path.dirname(os.path.realpath(__file__))
BLEND_CONVERTER_INIT_PY = os.path.join(os.path.dirname(DIR), '__init__.py')

SENTINEL = object()


if 'bpy' in sys.modules:
    # TODO: open the blend as a home file and remap paths to prevent overwriting it somewhere in the scripts by mistake
    import bpy
    bpy.context.preferences.filepaths.save_version = 32


def remove_PYTHONPATH():
    """
    #115648 - New Windows install, multiple Blender versions crash: EXCEPTION_ACCESS_VIOLATION (Python 3.12.0 conflict?)
    https://projects.blender.org/blender/blender/issues/115648
    """
    for pythonpath in filter(None, os.environ.get('PYTHONPATH', "").split(os.pathsep)):
        if pythonpath in sys.path:
            sys.path.remove(pythonpath)

    importlib.invalidate_caches()


def get_args() -> dict:

    parser = argparse.ArgumentParser()
    parser.add_argument('-json_args')

    args = sys.argv[sys.argv.index('--') + 1:]
    args, _ = parser.parse_known_args(args)

    return json.loads(args.json_args)


@functools.lru_cache(None)
def import_module_from_file(file_path: str, module_name: typing.Optional[str] = None):

    if not os.path.isabs(file_path):
        raise Exception(f"Path to file must be absolute: {file_path}")

    if module_name is None:
        module_name = os.path.splitext(os.path.basename(file_path))[0]

    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None:
        raise Exception(f"Spec not found: {module_name}, {file_path}")

    module = importlib.util.module_from_spec(spec)

    sys.modules[module_name] = module
    spec.loader.exec_module(module)  # type: ignore[reportOptionalMemberAccess]

    return module


class Profiled:


    def __enter__(self):

        import cProfile
        import time
        import tempfile

        prifiles_paths = os.path.join(tempfile.gettempdir(), 'profiles')
        os.makedirs(prifiles_paths, exist_ok=True)
        self.profile_path = os.path.join(prifiles_paths, f"blend_converter_{time.strftime('%y%m%d_%H%M%S')}.prof")

        self.profile = cProfile.Profile()

        return self


    def __exit__(self, *args):

        self.profile.dump_stats(self.profile_path)
        print(f'PROFILE: {self.profile_path}')

        import subprocess
        from blend_converter import utils

        if os.name == 'nt':
            kwargs = dict(creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS)

        try:
            subprocess.Popen(['python', '-m', 'snakeviz', self.profile_path], start_new_session = True, **kwargs, shell=True, text=True)
        except Exception as e:
            print(e)

            import pstats
            p = pstats.Stats(self.profile_path)
            p.strip_dirs().sort_stats(1).print_stats(20)


def append_sys_path(path: str):
    if not path in sys.path:
        sys.path.append(path)


def replace_return_values(args):
    """ Substitute previous function return values. """

    if isinstance(args, list):

        _args = []

        for arg in args:
            if arg in ARGS['scripts']:
                _args.append(return_values[ARGS['scripts'].index(arg)])
            else:
                _args.append(arg)

        return _args

    elif isinstance(args, dict):

        _kwargs = {}

        for key, arg in args.items():
            if arg in ARGS['scripts']:
                _kwargs[key] = return_values[ARGS['scripts'].index(arg)]
            else:
                _kwargs[key] = arg

        return _kwargs

    else:
        raise Exception(f"Unexpected args type: {args}")




if typing.TYPE_CHECKING:
    import blend_converter
else:
    blend_converter = import_module_from_file(BLEND_CONVERTER_INIT_PY, 'blend_converter')


from blend_converter import utils
from blend_converter import blend_inspector

return_values = {}
ARGS = get_args()

blend_inspector.add_identifier(*ARGS['inspect_identifiers'])

def process():


    if blend_inspector.has_identifier(blend_inspector.COMMON.INSPECT_BLEND_ORIG):
        blend_inspector.inspect_blend()


    for magic_key, magic_value in ARGS['builtin_kwargs'].items():
        setattr(builtins, magic_key, magic_value)


    for index, script in enumerate(ARGS['scripts']):

        try:

            if blend_inspector.has_identifier(f"inspect:script:pre={script['name']}"):
                blend_inspector.inspect_blend()


            append_sys_path(os.path.dirname(script['filepath']))

            utils.print_separator(char='█')
            utils.print_in_color(utils.get_color_code(256,256,256, 0, 150, 255), 'SCRIPT:', script['name'], "...", flush=True)

            script_start_time = time.perf_counter()

            module = import_module_from_file(script['filepath'])
            result = getattr(module, script['name'])(*replace_return_values(script['args']), **replace_return_values(script['kwargs']))
            return_values[index] = result

            utils.print_in_color(utils.get_color_code(56, 199, 134, 0, 0, 0), f"Processed in {round(time.perf_counter() - script_start_time, 2)} seconds.", flush=True)


            if blend_inspector.has_identifier(blend_inspector.COMMON.INSPECT_SCRIPT_ALL, f"inspect:script:post={script['name']}"):
                blend_inspector.inspect_blend()

        except Exception as e:

            # TODO: collect errors

            error_type, error_value, error_tb = sys.exc_info()

            print()
            utils.print_in_color(utils.get_color_code(255,255,255,128,0,0,), f"Fail at script: {script['name']}", file=sys.stderr)
            utils.print_in_color(utils.get_color_code(180,0,0,0,0,0,), ''.join(traceback.format_tb(error_tb)), file=sys.stderr)
            utils.print_in_color(utils.get_color_code(255,255,255,128,0,0,), ''.join(traceback.format_exception_only(error_type, error_value)), file=sys.stderr)
            print()

            if blend_inspector.has_identifier(blend_inspector.COMMON.INSPECT_SCRIPT_ALL):
                blend_inspector.inspect_blend()

            raise SystemExit(1)


if __name__ == '__main__':

    if ARGS['debug']:

        import debugpy

        if not debugpy.is_client_connected():
            debugpy.listen(5679)
            print(f"Waiting for a debugger to attach to port: {5679}")
            debugpy.wait_for_client()
            debugpy.breakpoint()


    remove_PYTHONPATH() # for testing pursues

    warnings.filterwarnings('error')
    warnings.simplefilter('error')


    setattr(builtins, 'binspect', blend_inspector.inspect_blend)


    if blend_inspector.has_identifier(blend_inspector.COMMON.SKIP_BREAKPOINT):

        import builtins

        def dummy_breakpoint(*args, **kwargs):
            pass

        setattr(builtins, 'breakpoint', dummy_breakpoint)

    if ARGS['profile']:
        with Profiled() as prof:
            prof.profile.runcall(process)
    else:
        process()

    with open(ARGS['return_values_file'], 'w', encoding='utf-8') as return_values_file:
        json.dump(return_values, return_values_file, indent = 4, ensure_ascii = False, default = lambda x: repr(x))


    utils.print_in_color(utils.get_color_code(256,256,256, 34, 139, 34), f"CONVERTED IN {round(time.perf_counter() - start_time, 2)} SECONDS.", flush=True)


    if blend_inspector.has_identifier(blend_inspector.COMMON.INSPECT_BLEND_FINAL):
        blend_inspector.inspect_blend()
