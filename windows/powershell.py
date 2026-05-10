import subprocess
import json
import os
import atexit

from .. import root
PS_SCRIPT_PATH = os.path.join(root.PATH, 'windows', 'powershell.ps1')


class PowerShell:

    def __init__(self):

        self.process = subprocess.Popen(
            [
                'powershell',
                '-NoProfile',
                '-ExecutionPolicy', 'Bypass',
                '-File', PS_SCRIPT_PATH,
            ],
            stdin = subprocess.PIPE,
            stdout = subprocess.PIPE,
            text = True,
            bufsize = 1,
        )

        atexit.register(self.terminate)


    def request(self, command: str, **arguments):

        self.process.stdin.write(json.dumps(dict(command = command, arguments = arguments)) + '\n')
        self.process.stdin.flush()

        raw_response = self.process.stdout.readline()

        try:
            return json.loads(raw_response)
        except json.decoder.JSONDecodeError:
            raise Exception(f"Fail to read a JSON string: {raw_response}")


    def terminate(self):

        try:
            self.process.stdin.write(json.dumps(dict(command = 'Exit', arguments = {})) + '\n')
            self.process.stdin.flush()
            self.process.stdin.close()
        except Exception:
            pass

        self.process.terminate()
