import typing
import os
import sys
import subprocess
import uuid
import tempfile
import json


from .. import common
from .. import root

SCRIPT_RUNNER_PATH = os.path.join(root.PATH, 'python', 'script_runner.py')


class Python:


    execution_context: common.Execution_Context


    def __init__(self, python_executable: str):

        self.python_executable = python_executable


    def run(self, *,
            instructions: typing.List[common.Instruction],
            return_values_file: str,
            inspect_identifiers: set,
            inspect_values: dict,
            debug: bool,
            profile: bool,
        ):


        input_files = os.path.join(tempfile.gettempdir(), 'blend_converter', 'python')
        os.makedirs(input_files, exist_ok = True)

        input_file = os.path.join(input_files, uuid.uuid1().hex + '.json')
        with open(input_file, 'w') as f:
            json.dump(dict(instructions = instructions, return_values_file = return_values_file), f, default = lambda x: x._to_dict())

        command = [self.python_executable, SCRIPT_RUNNER_PATH, input_file]


        with subprocess.Popen(command) as process:

            with self.execution_context.lock:
                self.execution_context.no_pending_children.value = True
                self.execution_context.lock.notify_all()

            process.wait()

            if process.returncode != 0:
                raise Exception("Python interpreter has existed with an error.")


        with self.execution_context.lock:
            self.execution_context.no_pending_children.value = False
            self.execution_context.lock.notify_all()


    def _to_dict(self):
        return dict(
            binary_path = self.python_executable,
            mtime = os.path.getmtime(self.python_executable),
            size = os.path.getsize(self.python_executable),
        )
