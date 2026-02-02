import socket
import json
import sys
import contextlib


SOCKET: socket.socket


@contextlib.contextmanager
def Connection(address: 'socket._Address'):

    global SOCKET

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as SOCKET:

        SOCKET.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, True)

        try:
            SOCKET.connect(address)
            yield

        finally:
            pass


def receive():

    truncated_message = None

    commands = []

    while True:

        raw = SOCKET.recv(1024 * 8)

        if raw == b'':
            SOCKET.close()
            if truncated_message:
                print("[communication leftover]:", truncated_message, file = sys.stderr)
            return []

        messages = raw.split(b'\0')

        if truncated_message is not None:
            messages[0] = truncated_message + messages[0]

        if messages[-1] == b'':
            truncated_message = None
        else:
            truncated_message = messages[-1]


        for message in messages[:-1]:
            try:
                commands.append(json.loads(message))
            except json.decoder.JSONDecodeError as e:
                print(e, file = sys.stderr)
                print(message, file = sys.stderr)

        if commands:
            return commands



def send_and_get(data: dict) ->  dict:

    SOCKET.sendall(json.dumps(data).encode() + b'\0')
    print('[communication send]:', data, flush=True)

    commands = receive()
    print('[communication got]:', commands, flush=True)

    # there should be only one command
    if len(commands) != 1:
        print(f"Unexpected amount of commands: {commands}", file = sys.stderr)

    if commands:
        return commands[0]
    else:
        return []


class Key:

    RESULT = 'result'
    COMMAND = 'command'
    ADDRESS = 'address'
    DATA = 'data'


class Command:

    INSTRUCTIONS = 'instructions'
    SUSPEND_OTHERS = 'suspend_others'


class Suspend_Others:


    def __init__(self, enabled = True):

        self.enabled = enabled


    def __enter__(self):

        if not self.enabled:
            return

        response = send_and_get({Key.COMMAND: Command.SUSPEND_OTHERS})

        if response.get('disabled') == True:
            return

        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, True)
        self.socket.connect(tuple(response[Key.ADDRESS]))


    def __exit__(self, type, value, traceback):

        if not self.enabled:
            return

        try:
            self.socket.sendall(b'\0')
            self.socket.close()
        except Exception as e:
            print(e)
