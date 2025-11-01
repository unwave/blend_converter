import json
import os
import typing

from .. import utils
from .. import common


BLENDER_SCRIPT_RUNNER = os.path.join(common.ROOT_DIR, 'blender', 'scripts', 'process_scripts.py')


class Blender:


    def __init__(self, binary_path: str, stdout = None):

        self.binary_path = binary_path
        self.stdout = None


    def run(self, instructions: typing.List[common.Instruction], return_values_file: str, inspect_identifiers: set, debug = False, profile = False):

        command = [
            '--python',
            BLENDER_SCRIPT_RUNNER,
            '--',
            '-json_args',
            json.dumps(dict(
                instructions = instructions,
                return_values_file = return_values_file,
                inspect_identifiers = list(inspect_identifiers),
                debug = debug,
                profile = profile,
            ), default = lambda x: x._to_dict()),
        ]

        utils.run_blender(self.binary_path, command, stdout = self.stdout)


    def _to_dict(self):
        return dict(
            binary_path = self.binary_path,
            mtime = os.path.getmtime(self.binary_path),
            size = os.path.getsize(self.binary_path),
        )
