import json
import os
import typing
import time
import sys
import subprocess

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


    def __init__(self, binary_path: str, memory_limit_in_gigabytes = 8, stdout = None):

        self.binary_path = binary_path
        self.stdout = None
        self.memory_limit = memory_limit_in_gigabytes


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

        run_blender(self.binary_path, command, memory_limit = self.memory_limit, stdout = self.stdout)


    def _to_dict(self):
        return dict(
            binary_path = self.binary_path,
            mtime = os.path.getmtime(self.binary_path),
            size = os.path.getsize(self.binary_path),
        )


def run_blender(
        executable: typing.Union[str, typing.List[str]],
        arguments: typing.List[str],
        argv: typing.Optional[typing.List[str]] = None,
        stdout = None,
        use_system_env = False,
        memory_limit = 8,
    ):

    if not isinstance(executable, list):
        executable = [executable]

    env = os.environ.copy()
    env['PYTHONPATH'] = ''
    env['PYTHONUNBUFFERED'] = '1'
    env['PYTHONWARNINGS'] = 'error'

    command = [
        *executable,

        '-b',
        '-noaudio',
        *(['--python-use-system-env'] if use_system_env else []),
        '--factory-startup',
        '--python-exit-code',
        '1',

        *arguments,
    ]

    if argv:
        command.extend(argv)

    bytes_in_gb = 1024 ** 3
    memory_limit_in_bytes = memory_limit * bytes_in_gb

    import psutil

    blender = subprocess.Popen(command, stdout = stdout, text = True, env = env)

    process = psutil.Process(blender.pid)

    while blender.poll() is None:

        if process.memory_info().vms > memory_limit_in_bytes:
            process.kill()

            raise Exception(f"Memory limit exceeded: {memory_limit_in_bytes/bytes_in_gb} Gb")

        time.sleep(1)

    if blender.returncode != 0:

        utils.print_in_color(utils.CONSOLE_COLOR.RED, "Blender has exited with an error.", file=sys.stderr)
        raise SystemExit('BLENDER')
