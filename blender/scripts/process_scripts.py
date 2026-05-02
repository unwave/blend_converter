import time

start_time = time.perf_counter()
print("BLENDER START", time.strftime('%H:%M:%S %Y-%m-%d'))

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


BC_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

SENTINEL = object()


if 'bpy' in sys.modules:
    # TODO: open the blend as a home file and remap paths to prevent overwriting it by mistake
    import bpy

    if hasattr(bpy.context, 'preferences'):
        bpy.context.preferences.filepaths.save_version = 32
    else:  # 2.79-
        bpy.context.user_preferences.filepaths.save_version = 32


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

        env = os.environ.copy()
        env['PYTHONWARNINGS'] = '0'

        try:
            subprocess.Popen(['python', '-m', 'snakeviz', self.profile_path], start_new_session = True, **kwargs, env=env)
        except Exception as e:
            print(e)

            import pstats
            p = pstats.Stats(self.profile_path)
            p.strip_dirs().sort_stats(1).print_stats(20)


def append_sys_path(path: str):
    if not path in sys.path:
        sys.path.append(path)


CANONICAL_NAME = 'blend_converter'

if typing.TYPE_CHECKING:
    import blend_converter
else:
    blend_converter = import_module_from_file(os.path.join(BC_ROOT, '__init__.py'), CANONICAL_NAME)


from blend_converter import utils
from blend_converter import common
from blend_converter.blender import blend_inspector

from blend_converter.blender import communication

return_values = {}
ARGS = get_args()

blend_inspector.add_identifier(*ARGS['inspect_identifiers'])
blend_inspector.add_value(**ARGS['inspect_values'])


if any(arg.startswith('inspect:func') for arg in ARGS['inspect_identifiers']):
    blend_inspector.make_top_functions_inspectable()

utils.disable_buffering()

INSTRUCTIONS: typing.List[dict]

def process():

    global INSTRUCTIONS
    INSTRUCTIONS = communication.send_and_get({communication.Key.COMMAND: communication.Command.INSTRUCTIONS})[communication.Key.DATA]

    for index, instruction in enumerate(INSTRUCTIONS):

        try:

            blend_inspector.inspect_if_has_identifier(f"inspect:script:pre={instruction['name']}")

            utils.print_separator(char='█')
            utils.print_in_color(utils.get_color_code(256,256,256, 0, 150, 255), 'SCRIPT:', instruction['name'], "...", flush=True)

            script_start_time = time.perf_counter()

            if instruction['module_name'] != '__main__':
                append_sys_path(os.path.dirname(instruction['package_file']))
                module = importlib.import_module(instruction['module_name'])
            else:
                append_sys_path(os.path.dirname(instruction['filepath']))
                module = import_module_from_file(instruction['filepath'])

            result = getattr(module, instruction['name'])(*common.replace_return_value(instruction['args'], return_values, INSTRUCTIONS), **common.replace_return_value(instruction['kwargs'], return_values, INSTRUCTIONS))
            return_values[instruction['identifier']] = result

            utils.print_in_color(utils.get_color_code(56, 199, 134, 0, 0, 0), f"Processed in {round(time.perf_counter() - script_start_time, 2)} seconds.", flush=True)


            blend_inspector.inspect_if_has_identifier(blend_inspector.COMMON.INSPECT_SCRIPT_ALL, f"inspect:script:post={instruction['name']}", name = instruction['name'])

        except Exception as e:

            # TODO: collect errors

            error_type, error_value, error_tb = sys.exc_info()

            traceback_text = traceback.format_exc()
            exception_text = ''.join(traceback.format_exception_only(error_type, error_value))

            if traceback_text.endswith(exception_text):
                traceback_text = traceback_text[:-len(exception_text)]

            print()
            utils.print_in_color(utils.get_color_code(255,255,255,128,0,0,), f"Fail at script: {instruction['name']}", file=sys.stderr)
            utils.print_in_color(utils.get_color_code(180,0,0,0,0,0,), traceback_text, file=sys.stderr)
            utils.print_in_color(utils.get_color_code(255,255,255,128,0,0,), exception_text, file=sys.stderr)
            print()

            blend_inspector.inspect_if_has_identifier(blend_inspector.COMMON.INSPECT_SCRIPT_ALL)

            blend_inspector.inspect_if_has_identifier(blend_inspector.COMMON.INSPECT_BLEND_FINAL)

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

    with communication.Connection((ARGS['host'], ARGS['port'])):
        if ARGS['profile']:
            with Profiled() as prof:
                prof.profile.runcall(process)
        else:
            process()

    with open(ARGS['return_values_file'], 'w', encoding='utf-8') as return_values_file:
        json.dump(return_values, return_values_file, indent = 4, ensure_ascii = False, default = lambda x: repr(x))


    utils.print_in_color(utils.get_color_code(256,256,256, 34, 139, 34), f"BLENDER HAS EXECUTED IN {round(time.perf_counter() - start_time, 2)} SECONDS.", flush=True)


    blend_inspector.inspect_if_has_identifier(blend_inspector.COMMON.INSPECT_BLEND_FINAL)
