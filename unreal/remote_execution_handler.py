import json
import uuid
import socket
import typing
import inspect
import textwrap

class UE_Remote_Execution_Handler:


    def __init__(
            self,
            multicast_group_address = '239.0.0.1',
            multicast_group_port = 6766,
            multicast_bind_address = '127.0.0.1',
            receive_buffer_size = 2 * 2 ** 20,
            multicast_ttl = 0,
            command_endpoint = ('127.0.0.1', 6776),
            ):

        self.multicast_group_address = multicast_group_address
        self.multicast_group_port = multicast_group_port
        self.multicast_bind_address = multicast_bind_address

        self.receive_buffer_size = receive_buffer_size
        self.multicast_ttl = multicast_ttl

        self.command_endpoint = command_endpoint


    @property
    def multicast_group_endpoint(self):
        return (self.multicast_group_address, self.multicast_group_port)


    @property
    def multicast_endpoint(self):
        return (self.multicast_bind_address, self.multicast_group_port)


    def __enter__(self):

        self._caller_id = str(uuid.uuid4())

        self._init_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self._init_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, True)
        self._init_socket.setsockopt(socket.IPPROTO_UDP, socket.TCP_NODELAY, True)
        self._init_socket.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, self.multicast_ttl)
        self._init_socket.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, socket.inet_aton(self.multicast_group_address) + socket.inet_aton(self.multicast_bind_address))
        self._init_socket.settimeout(1)
        self._init_socket.bind(self.multicast_endpoint)

        data = {
            "version": 1,
            "magic": "ue_py",
            "type": "ping",
            "source": self._caller_id
        }
        data = json.dumps(data).encode('utf-8')

        self._init_socket.sendto(data, self.multicast_group_endpoint)

        # ping
        _ = self._init_socket.recv(self.receive_buffer_size)

        # pong
        message = self._init_socket.recv(self.receive_buffer_size)
        message = json.loads(message)

        assert message['type'] == 'pong', json.dumps(message, indent = 4)
        self._unreal_engine_instance_id = message['source']

        self._command_init_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP)
        self._command_init_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, True)
        self._command_init_socket.bind(self.command_endpoint)
        self._command_init_socket.listen()

        message = {
            "version": 1,
            "magic": "ue_py",
            "type": "open_connection",
            "source": self._caller_id,
            "dest": self._unreal_engine_instance_id,
            "data": {
                "command_ip": self.command_endpoint[0],
                "command_port": self.command_endpoint[1]
            }
        }
        message = json.dumps(message).encode('utf-8')
        self._init_socket.sendto(message, self.multicast_group_endpoint)

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

        self._command_socket.sendto(data, self.multicast_endpoint)

        message = self._command_socket.recv(self.receive_buffer_size)
        message = json.loads(message)

        return message
