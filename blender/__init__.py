import json
import os
import typing

from .. import utils
from .. import common


BLENDER_SCRIPT_RUNNER = os.path.join(common.ROOT_DIR, 'blender', 'scripts', 'process_scripts.py')


def remove_code(value):
    """ FileNotFoundError: [WinError 206] The filename or extension is too long """

    if isinstance(value, list):

        for sub_value in value:
            remove_code(sub_value)

    elif isinstance(value, dict):

        if value.get('_type') == 'Instruction':
            value['code'] = ''

        for sub_value in value.values():
            remove_code(sub_value)


class Blender:


    def __init__(self, binary_path: str, stdout = None):

        self.binary_path = binary_path
        self.stdout = None


    def run(self, *,
            instructions: typing.List[common.Instruction],
            return_values_file: str,
            inspect_identifiers: set,
            inspect_values: dict,
            debug: bool,
            profile: bool,
        ):

        args = json.dumps(dict(
                instructions = instructions,
                return_values_file = return_values_file,
                inspect_identifiers = list(inspect_identifiers),
                inspect_values = dict(inspect_values),
                debug = debug,
                profile = profile,
        ), default = lambda x: x._to_dict())


        args = json.loads(args)

        remove_code(args)

        command = [
            '--python',
            BLENDER_SCRIPT_RUNNER,
            '--',
            '-json_args',
            json.dumps(args),
        ]

        utils.run_blender(self.binary_path, command, stdout = self.stdout)


    def _to_dict(self):
        return dict(
            binary_path = self.binary_path,
            mtime = os.path.getmtime(self.binary_path),
            size = os.path.getsize(self.binary_path),
        )
