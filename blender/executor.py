import json
import os
import typing
import time
import sys
import subprocess
import queue
import traceback
import threading
import socket
import multiprocessing


from .. import utils
from .. import common
from . import communication



SENTINEL = object()


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


    entry_command_queue: 'queue.SimpleQueue[dict]' = None
    updater_response_queue: 'multiprocessing.SimpleQueue[dict]' = None


    def __init__(self, binary_path: str, memory_limit = 8, timeout = 0):

        self.binary_path = binary_path


        self.memory_limit = memory_limit
        """
        A max amount of RAM in gigabytes.
        Including the swap file, the pagefile.sys on Windows.
        If it is exceeded — Blender will be terminated.
        """

        self.timeout = timeout
        """
        A max CPU execution time in seconds after which Blender will be terminated.
        This does not include the suspension time.
        If `0` — no timeout.
        """


    def run(self, *,
            instructions: typing.List[common.Instruction],
            return_values_file: str,
            inspect_identifiers: set,
            inspect_values: dict,
            debug: bool,
            profile: bool,
        ):


        ## convert to json compatible representation
        arguments = json.dumps(dict(
                instructions = instructions,
                return_values_file = return_values_file,
                inspect_identifiers = list(inspect_identifiers),
                inspect_values = dict(inspect_values),
                debug = debug,
                profile = profile,
        ), default = lambda x: x._to_dict())
        arguments: dict = json.loads(arguments)


        ## fix "The filename or extension is too long"
        remove_code(arguments)

        self.instructions = arguments.pop('instructions')


        self.run_blender(
            executable =  self.binary_path,
            arguments = arguments,
            memory_limit = self.memory_limit,
        )


    def _to_dict(self):
        return dict(
            binary_path = self.binary_path,
            mtime = os.path.getmtime(self.binary_path),
            size = os.path.getsize(self.binary_path),
        )


    def run_blender(self, *,
            executable: typing.Union[str, typing.List[str]],
            arguments: dict,
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

            '--python',
            BLENDER_SCRIPT_RUNNER,
        ]


        bytes_in_gb = 1024 ** 3
        memory_limit_in_bytes = memory_limit * bytes_in_gb

        import psutil

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listening_socket:


            host = 'localhost'
            listening_socket.bind((host, 0))
            port = listening_socket.getsockname()[1]

            arguments['host'] = host
            arguments['port'] = port

            command.extend(['--', '-json_args', json.dumps(arguments)])


            with subprocess.Popen(command, text = True, env = env) as blender:


                listening_socket.listen()

                self.client_socket, _ = listening_socket.accept()
                self.client_socket.settimeout(None)
                self.client_socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                self.client_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, True)

                self.message_queue = queue.SimpleQueue()

                message_processing = threading.Thread(target=self.message_processing, daemon=True)
                message_processing.start()
                message_receiving = threading.Thread(target=self.message_receiving, daemon=True)
                message_receiving.start()

                process = psutil.Process(blender.pid)
                process.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)


                start_time = time.monotonic()
                suspension_time = 0
                elapsed = 0
                INTERVAL = 1
                exception = None


                def checking():

                    nonlocal suspension_time
                    nonlocal elapsed
                    nonlocal exception

                    while process.is_running():

                        try:

                            # the executor's parent process should not be suspended
                            if process.status() == psutil.STATUS_STOPPED:
                                suspension_time += INTERVAL

                            elapsed = (time.monotonic() - start_time) - suspension_time

                            if self.timeout and elapsed > self.timeout:

                                utils.kill_process(process)
                                exception = Exception(f"Timeout: {self.timeout}")
                                return


                            if process.memory_info().vms > memory_limit_in_bytes:

                                utils.kill_process(process)
                                exception = Exception(f"Memory limit exceeded: {memory_limit_in_bytes/bytes_in_gb} Gb")
                                return

                        except psutil.NoSuchProcess as e:
                            print(e)
                            break

                        waiting.wait(INTERVAL)


                waiting = threading.Event()

                process_checking = threading.Thread(target=checking, daemon=True)
                process_checking.start()

                blender.wait()
                waiting.set()

                process_checking.join()

                self.client_socket.close()
                message_receiving.join()

                self.message_queue.put(SENTINEL)
                message_processing.join()

                print(f"Non suspended time: {round(elapsed, 2)}")


        if exception:
            raise exception

        elif blender.returncode != 0:

            utils.print_in_color(utils.CONSOLE_COLOR.RED, "Blender has exited with an error.", file=sys.stderr)
            raise SystemExit('BLENDER')


    def message_processing(self):

        for message in iter(self.message_queue.get, SENTINEL):

            try:
                data: dict = json.loads(message)
            except json.decoder.JSONDecodeError:
                traceback.print_exc()
                print(message)
                continue

            print('[blender executor got]:', data, flush=True)


            if data.get(communication.Key.COMMAND) == communication.Command.INSTRUCTIONS:
                self.send({communication.Key.RESULT: True, communication.Key.DATA: self.instructions})
                continue

            if self.entry_command_queue is None:
                self.send({"disabled": True})
                continue

            data['pid'] = os.getpid()

            self.entry_command_queue.put(data)
            self.send(self.updater_response_queue.get())


    def send(self, data: dict):
        print('[blender executor sent]:', data, flush=True)
        self.client_socket.sendall(json.dumps(data).encode() + b'\0')


    def message_receiving(self):

        truncated_message = None

        while self.client_socket:

            try:
                raw = self.client_socket.recv(1024 * 8)
            except OSError as e:
                print(e)
                return

            if raw == b'':
                self.client_socket.close()
                if truncated_message:
                    print("[blender executor leftover]:", truncated_message, file = sys.stderr)
                return

            messages = raw.split(b'\0')

            if truncated_message is not None:
                messages[0] = truncated_message + messages[0]

            if messages[-1] == b'':
                truncated_message = None
            else:
                truncated_message = messages[-1]

            for message in messages[:-1]:
                self.message_queue.put(message)
