import json
import os
import queue
import socket
import subprocess
import sys
import threading
import time
import traceback
import typing

from . import utils

SENTINEL = object()

BLENDER_SERVER_SCRIPT_PATH = utils.get_blender_script_path('blender_server')


class Blender_Server:

    def __init__(self, blender_executable: str, factory_startup = False, background = False):

        self.thread: typing.Optional[threading.Thread] = None
        self.client_socket: typing.Optional[socket.socket] = None
        self.message_queue: typing.Optional[queue.Queue] = None

        self.blender_executable = blender_executable
        self.factory_startup = factory_startup
        self.background = background

        self.lock = threading.Lock()


    def ensure(self):
        if self.thread is None or not self.thread.is_alive():
            self.thread = threading.Thread(target=self.main, daemon=True)
            self.thread.start()


    def main(self):

        self.lock.acquire()

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listening_socket:

            host = 'localhost'
            listening_socket.bind((host, 0))
            port = listening_socket.getsockname()[1]

            command = [
                self.blender_executable,
                '--python-exit-code',
                '1',
                *(['--factory-startup'] if self.factory_startup else []),
                *(['-b'] if self.background else []),
                '--python',
                BLENDER_SERVER_SCRIPT_PATH,
                '--',
                '-json_args',
                json.dumps(dict(host = host, port = port))
            ]

            if os.name == 'nt':
                kwargs = dict(creationflags = subprocess.CREATE_NEW_CONSOLE)
            else:
                kwargs = dict(start_new_session = True)


            with subprocess.Popen(command, **kwargs) as blender_process:

                listening_socket.listen()

                self.client_socket, addr = listening_socket.accept()
                self.client_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, True)

                self.message_queue = queue.Queue()
                threading.Thread(target=self.message_processing, args=[self.message_queue], daemon=True).start()
                threading.Thread(target=self.message_receiving, args=[self.client_socket, self.message_queue], daemon=True).start()

                self.lock.release()

                blender_process.wait()


    def send(self, __code: str, /, **kwargs: dict):

        with self.lock:
            data = {'__code': __code, **kwargs}
            print("CLIENT SENDING:", data)
            self.client_socket.sendall(json.dumps(data).encode() + b'\0')


    def terminate(self):
        self.send('kill')


    def message_processing(self, message_queue: queue.Queue, sentinel = SENTINEL):

        for job in iter(message_queue.get, sentinel):

            try:
                data: dict = json.loads(job)
            except json.decoder.JSONDecodeError:
                traceback.print_exc()
                print(job)
                continue

            print('SERVER_GETTING' + str(data))


    def message_receiving(self, socket_for_recv: socket.socket, message_queue: queue.Queue):

        truncated_message = None
        message = None

        while socket_for_recv:

            try:
                message = socket_for_recv.recv(1024 * 8)
            except Exception:
                return

            if not message:
                continue

            messages = message.split(b'\0')

            if truncated_message is not None:
                messages[0] = truncated_message + messages[0]

            if messages[-1] == b'':
                truncated_message = None
            else:
                truncated_message = messages[-1]

            for message in messages[:-1]:
                message_queue.put_nowait(message)


    def open_mainfile(self, filepath: str):
        self.send('open_mainfile', filepath=filepath, load_ui=False)
