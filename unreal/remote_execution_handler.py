import json
import uuid
import socket
import typing
import inspect
import textwrap

class UE_Remote_Execution_Handler:


    def __init__(
            self,
            MULTICAST_GROUP_ADDRESS = '239.0.0.1',
            MULTICAST_GROUP_PORT = 6766,
            MULTICAST_BIND_ADDRESS = '0.0.0.0',
            RECEIVE_BUFFER_SIZE = 2 * 2 ** 20,
            MULTICAST_TTL = 0,
            COMMAND_ENDPOINT = ('127.0.0.1', 6776),
            ):

        self.MULTICAST_GROUP_ADDRESS = MULTICAST_GROUP_ADDRESS
        self.MULTICAST_GROUP_PORT = MULTICAST_GROUP_PORT
        self.MULTICAST_BIND_ADDRESS = MULTICAST_BIND_ADDRESS

        self.RECEIVE_BUFFER_SIZE = RECEIVE_BUFFER_SIZE
        self.MULTICAST_TTL = MULTICAST_TTL

        self.COMMAND_ENDPOINT = COMMAND_ENDPOINT


    @property
    def MULTICAST_GROUP_ENDPOINT(self):
        return (self.MULTICAST_GROUP_ADDRESS, self.MULTICAST_GROUP_PORT)


    @property
    def MULTICAST_ENDPOINT(self):
        return (self.MULTICAST_BIND_ADDRESS, self.MULTICAST_GROUP_PORT)


    def __enter__(self):

        self._caller_id = str(uuid.uuid4())

        self._init_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self._init_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, True)
        self._init_socket.setsockopt(socket.IPPROTO_UDP, socket.TCP_NODELAY, True)
        self._init_socket.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, self.MULTICAST_TTL)
        self._init_socket.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, socket.inet_aton(self.MULTICAST_GROUP_ADDRESS) + socket.inet_aton(self.MULTICAST_BIND_ADDRESS))
        self._init_socket.settimeout(1)
        self._init_socket.bind(self.MULTICAST_ENDPOINT)

        data = {
            "version": 1,
            "magic": "ue_py",
            "type": "ping",
            "source": self._caller_id
        }
        data = json.dumps(data).encode('utf-8')

        self._init_socket.sendto(data, self.MULTICAST_GROUP_ENDPOINT)

        # ping
        _ = self._init_socket.recv(self.RECEIVE_BUFFER_SIZE)

        # pong
        message = self._init_socket.recv(self.RECEIVE_BUFFER_SIZE)
        message = json.loads(message)

        assert message['type'] == 'pong', json.dumps(message, indent = 4)
        self._unreal_engine_instance_id = message['source']

        self._command_init_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP)
        self._command_init_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, True)
        self._command_init_socket.bind(self.COMMAND_ENDPOINT)
        self._command_init_socket.listen()

        message = {
            "version": 1,
            "magic": "ue_py",
            "type": "open_connection",
            "source": self._caller_id,
            "dest": self._unreal_engine_instance_id,
            "data": {
                "command_ip": self.COMMAND_ENDPOINT[0],
                "command_port": self.COMMAND_ENDPOINT[1]
            }
        }
        message = json.dumps(message).encode('utf-8')
        self._init_socket.sendto(message, self.MULTICAST_GROUP_ENDPOINT)

        sock, address = self._command_init_socket.accept()
        self._command_socket = sock
        self._command_socket.setblocking(True)
        self._command_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, True)

        return self


    def __exit__(self, exc_type, exc_val, exc_tb):
        self._command_socket.close()
        self._command_init_socket.close()
        self._init_socket.close()


    def exec_func(self, func: typing.Callable, *args, **kwargs):
        expr = '\n'.join((
            textwrap.dedent(inspect.getsource(func)),
            'import json',
            f'args = json.loads(r"""{json.dumps(args, ensure_ascii = False, indent = 4, default= lambda x: x._to_dict())}""")',
            f'kwargs = json.loads(r"""{json.dumps(kwargs, ensure_ascii = False, indent = 4, default= lambda x: x._to_dict())}""")',
            f'{func.__name__}(*args, **kwargs)'
        ))

        return self.exec(expr)


    def exec(self, expr: str):

        data = {
            "version": 1,
            "magic": "ue_py",
            "type": "command",
            "source": self._caller_id,
            "dest": self._unreal_engine_instance_id,
            "data": {
                "command": expr,
                "unattended": True,
                "exec_mode": "ExecuteFile"
            }
        }
        data = json.dumps(data).encode('utf-8')

        self._command_socket.sendto(data, self.MULTICAST_ENDPOINT)

        message = self._command_socket.recv(self.RECEIVE_BUFFER_SIZE)
        message = json.loads(message)

        return message
