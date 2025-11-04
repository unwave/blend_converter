import typing
import os
import tempfile
import uuid
import textwrap
import inspect


from .. import common
from . import remote_execution_handler
from .. import utils



SCRIPT_RUNNER_PATH = os.path.join(common.ROOT_DIR, 'unreal', 'script_runner.py')


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


class Unreal:
    """ Needs an open Unreal Engine instance. """


    def run(self, *,
            instructions: typing.List[common.Instruction],
            return_values_file: str,
            inspect_identifiers: set,
            inspect_values: dict,
            debug: bool,
            profile: bool,
        ):

        with remote_execution_handler.UE_Remote_Execution_Handler() as handler:
            utils.print_in_color(utils.get_color_code(96, 154, 247, 0,0,0), "UNREAL ENGINE EXECUTION", flush = True)
            utils.print_in_color(utils.get_color_code(255, 139, 51, 0,0,0), "The output is delayed until all instructions are done.", flush = True)
            handler.exec_func(runner_bootstrap, SCRIPT_RUNNER_PATH, dict(instructions = instructions))


    def _to_dict(self):
        return dict(
            _type = 'Unreal'
        )
