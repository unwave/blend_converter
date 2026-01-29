import os
import queue
import threading
import typing
import time
import multiprocessing
import sys
import uuid
import types
import atexit
import re
import importlib
import traceback
import socket

from watchdog import events as watchdog_events
from watchdog import observers as watchdog_observers
import psutil

from . import common
from . import utils
from .blender import communication
from . import update_process

UPDATE_DELAY = 2
""" For update debouncing. """

SENTINEL = object()

LOG_DIR = os.path.join(utils.BLEND_CONVERTER_USER_DIR, 'logs')


class Status:

    OK = 'ok'
    STALE = 'stale'
    UPDATING = 'updating'
    YIELDING = 'yielding'
    ERROR = 'error'
    DOES_NOT_EXIST = 'does_not_exist'
    WAITING_FOR_DEPENDENCY = 'waiting_for_dependency'
    UNKNOWN = 'unknown'

STATUS_ICON = {
    Status.OK: '✔️',
    Status.STALE: '🦕',
    Status.UPDATING: '🔨',
    Status.YIELDING: '⛔',
    Status.ERROR: '❌',
    Status.DOES_NOT_EXIST: '👻',
    Status.WAITING_FOR_DEPENDENCY: '🔒',
    Status.UNKNOWN: '❓',
}

class Program_Entry:


    def __init__(self, program: common.Program, from_module_file: str, programs_getter_name: str, keyword_arguments: dict):

        self.entry_id = uuid.uuid1().hex

        self.program = program

        self.poke_time = 0

        report_stem = os.path.splitext(os.path.basename(program.report_path))[0]

        self.stdout_file = os.path.join(LOG_DIR, f"{report_stem}_stdout_{uuid.uuid1().hex}.txt")
        self.stderr_file = os.path.join(LOG_DIR, f"{report_stem}_stderr_{uuid.uuid1().hex}.txt")

        self.status = Status.UNKNOWN

        self.is_live_update = True

        self.is_manual_update = False


        self.keyword_arguments = keyword_arguments
        """ The program keyword arguments. """

        self.from_module_file = from_module_file
        """ A module file which the common.Program was collected from. """

        self.programs_getter_name = programs_getter_name
        """ Name of a function that will return a dictionary with programs """


        # self.path_list = os.path.realpath(program.blend_path).split(os.path.sep)

        self.lock = threading.RLock()

        self.stdout_queue = multiprocessing.SimpleQueue()
        self.stderr_queue = multiprocessing.SimpleQueue()

        self.stdout_lines = []
        self.stderr_lines = []

        self.updater_response_queue: 'multiprocessing.SimpleQueue[dict]' = multiprocessing.SimpleQueue()

        self.psutil_process: psutil.Process = None


    def poke(self, has_non_updated_dependency: bool):

        if has_non_updated_dependency:
            self.status = Status.WAITING_FOR_DEPENDENCY
        elif os.path.exists(self.program.blend_path):
            if self.program.are_instructions_changed:
                self.status = Status.STALE
            else:
                self.status = Status.OK
        else:
            self.status = Status.DOES_NOT_EXIST

        self.poke_time = time.time()

        update_ui()


    @property
    def poke_timeout(self):
        return (time.time() - self.poke_time) > UPDATE_DELAY


    def _run(self, *, callback: typing.Callable, thread_identity: uuid.UUID, updater_command_queue: 'multiprocessing.SimpleQueue[dict]' = None):

        def read_stdout():
            for line in iter(self.stdout_queue.get, None):
                self.stdout_lines.append(line)
                stdout_line_printed(self)

        def read_stderr():
            for line in iter(self.stderr_queue.get, None):
                self.stderr_lines.append(line)
                stderr_line_printed(self)


        read_stdout_thread = threading.Thread(target=read_stdout, daemon=True)
        read_stderr_thread = threading.Thread(target=read_stderr, daemon=True)

        read_stdout_thread.start()
        read_stderr_thread.start()


        with self.lock:
            process = multiprocessing.Process(
                target = update_process.run,
                kwargs = dict(
                    stdout_file = self.stdout_file,
                    stderr_file = self.stderr_file,
                    stdout_queue = self.stdout_queue,
                    stderr_queue = self.stderr_queue,
                    entry_id = self.entry_id,
                    updater_command_queue = updater_command_queue,
                    updater_response_queue = self.updater_response_queue,
                    program = self.program,
                ),
                daemon=True,
            )
            process.start()

            self.psutil_process = psutil.Process(process.pid)


        exit_func = atexit.register(self.terminate)

        process.join()

        if process.exitcode == None:
            self.terminate()

        is_superseded = thread_identity != self.thread_identity

        if is_superseded:
            self.stderr_queue.put(f"THE UPDATE HAS BEEN SUPERSEDED: {thread_identity}")

        atexit.unregister(exit_func)

        self.stdout_queue.put(None)
        read_stdout_thread.join()

        self.stderr_queue.put(None)
        read_stderr_thread.join()

        if is_superseded:
            update_ui()
            return

        if process.exitcode == 0:
            self.status = Status.OK
            print(f"Done [{time.strftime('%H:%M:%S %Y-%m-%d')}]:", self.program)
        else:
            self.status = Status.ERROR
            print(f"Error [{time.strftime('%H:%M:%S %Y-%m-%d')}]:", self.program)


        if callback:
            callback()

        update_ui()


    def update(self, *, updater_command_queue: 'multiprocessing.SimpleQueue[dict]' = None, callback: typing.Optional[typing.Callable] = None):

        with self.lock:

            print(f"Processing [{time.strftime('%H:%M:%S %Y-%m-%d')}]:", self.program)

            self.status = Status.UPDATING

            self.thread_identity = uuid.uuid4()

            self.terminate()

            threading.Thread(target=self._run, kwargs=dict(callback=callback, thread_identity = self.thread_identity, updater_command_queue = updater_command_queue), daemon = True).start()

            update_ui()


    def terminate(self):

        with self.lock:

            if self.psutil_process is None:
                return

            utils.kill_process(self.psutil_process)


    def suspend(self):

        with self.lock:

            if self.psutil_process is None:
                return

            if not self.psutil_process.is_running():
                return

            try:

                for child in self.psutil_process.children(recursive=True):
                    try:
                        child.suspend()
                    except psutil.Error as e:
                        print(e)

            except psutil.Error as e:
                print(e)


    def resume(self):

        with self.lock:

            if self.psutil_process is None:
                return

            if not self.psutil_process.is_running():
                return

            try:

                for child in self.psutil_process.children(recursive=True):
                    try:
                        child.resume()
                    except psutil.Error as e:
                        print(e)

            except psutil.Error as e:
                print(e)


class Blend_Event_Handler(watchdog_events.PatternMatchingEventHandler):

    def __init__(self, queue: queue.SimpleQueue,  *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.queue = queue

    def on_any_event(self, event):

        if not isinstance(event, watchdog_events.FileMovedEvent):
            return

        if event.is_directory:
            return

        if not event.src_path == event.dest_path + '@':
            return

        self.queue.put(event.dest_path)


def import_files(files: typing.List[str]):

    modules: typing.Dict[str, types.ModuleType] = {}

    files = utils.deduplicate(os.path.realpath(f) for f in files)
    dirs = utils.deduplicate(os.path.dirname(f) for f in files)

    for dir in dirs:
        if not dir in sys.path:
            sys.path.append(dir)

    for file in files:
        modules[file] = utils.import_module_from_file(file)

    return modules


def get_program_entries(program_definitions: typing.List[typing.Tuple[str, str, str]]):

    entries = []

    path_to_module_map = import_files([p[0] for p in program_definitions])

    for file_name, program_getter_name, arguments_getter_name in program_definitions:

        module = path_to_module_map[os.path.realpath(file_name)]

        program_getter = getattr(module, program_getter_name)
        if not isinstance(program_getter, typing.Callable):
            raise Exception(
                f"A program_getter must be a function, got: {repr(program_getter)}"
                "\n\t" f"file_name = {file_name}"
                "\n\t" f"program_getter_name = {program_getter_name}"
            )

        arguments_getter = getattr(module, arguments_getter_name)
        if not isinstance(arguments_getter, typing.Callable):
            raise Exception(
                f"An arguments_getter must be a function, got: {repr(arguments_getter)}"
                "\n\t" f"file_name = {file_name}"
                "\n\t" f"arguments_getter_name = {arguments_getter_name}"
            )

        for kwargs in arguments_getter():

            program = program_getter(**kwargs)

            if not isinstance(program, common.Program):
                raise Exception(
                    f"A program_getter function must return a common.Program, got: {repr(program)}"
                    "\n\t" f"file_name = {file_name}"
                    "\n\t" f"program_getter_name = {program_getter_name}"
                    "\n\t" f"kwargs = {kwargs}"
                )

            entries.append(Program_Entry(program, module.__file__, program_getter_name, kwargs))

    return entries



class Updater:

    def __init__(self):

        self.is_paused = True

        self.entries: list[Program_Entry] = []

        self.max_parallel_execution_per_tag = {}

        self.default_max_parallel_executions = 2
        """  Max parallel executions for programs with no limiting tags. """

        self.total_max_parallel_executions = 2
        """ Total max parallel executions. """

        self.shared_failure_tags = set()
        """ See `set_shared_failure_by_tag`. """

        self.updater_command_queue: 'multiprocessing.SimpleQueue[dict]' = multiprocessing.SimpleQueue()

        threading.Thread(target = self.command_queue_runner, daemon=True).start()


    def init_observer(self):

        self.queue = queue.SimpleQueue()
        self.event_handler = Blend_Event_Handler(self.queue, patterns=['*.blend'])

        self.observer = watchdog_observers.Observer()
        self.observer.start()

        self.poker = threading.Thread(target=self.poking, daemon=True)
        self.poker.start()

        self.dispatcher = threading.Thread(target=self.despatching, daemon=True)
        self.dispatcher.start()


    def schedule_observer(self):

        self.observer.unschedule_all()

        dirs = set(os.path.dirname(entry.program.blend_path) for entry in self.entries)
        for dir in dirs:
            os.makedirs(dir, exist_ok=True)
            self.observer.schedule(self.event_handler, dir, recursive=True)


    @classmethod
    def from_files(cls, program_definitions: typing.List[typing.Tuple[str, str, str]]):

        updater = cls()

        updater.entries = get_program_entries(program_definitions)

        updater.poke_all()

        updater.init_observer()
        updater.schedule_observer()

        update_ui()

        return updater


    def has_non_updated_dependency(self, entry: Program_Entry):
        return any(
            _entry.program.result_path == entry.program.blend_path
            for _entry in self.entries
            if not _entry is entry and _entry.status != Status.OK
        )

    def poke_entry(self, entry: Program_Entry):
        entry.poke(self.has_non_updated_dependency(entry))

    def poke_waiting_for_dependency(self):

        for entry in self.entries:
            if entry.status == Status.WAITING_FOR_DEPENDENCY:
                self.poke_entry(entry)

    def poke_all(self):

        entries = list(self.entries)

        # at the start entries has unknown status
        # TODO: dependency map
        entries.sort(key = self.has_non_updated_dependency)

        for entry in entries:
            self.poke_entry(entry)


    def poking(self):
        for path in iter(self.queue.get, None):
            for entry in self.entries:
                if entry.program.blend_path == path:
                    self.poke_entry(entry)


    def total_max_parallel_executions_exceeded(self):
        return sum(entry.status in (Status.UPDATING, Status.YIELDING) for entry in self.entries) >= self.total_max_parallel_executions


    def despatching(self):

        while 1:

            time.sleep(1)


            failed_tags = set()

            for entry in self.entries:

                if entry.status != Status.ERROR:
                    continue

                failed_tags.update(self.shared_failure_tags.intersection(entry.program.tags))

            if failed_tags:

                for entry in self.entries:
                    if not entry.program.tags.isdisjoint(failed_tags):
                        entry.status = Status.ERROR

                update_ui()


            for entry in self.entries:

                if not entry.is_manual_update:
                    continue

                if self.total_max_parallel_executions_exceeded():
                    break

                if self.max_executions_per_tag_exceeded(entry.program.tags):
                    continue

                if self.has_non_updated_dependency(entry):
                    self.poke_entry(entry)
                    continue

                entry.is_manual_update = False
                entry.update(updater_command_queue = self.updater_command_queue, callback = self.poke_waiting_for_dependency)


            if self.is_paused:
                continue


            for entry in self.entries:

                if not entry.is_live_update:
                    continue

                if entry.status != Status.STALE:
                    continue

                if self.total_max_parallel_executions_exceeded():
                    break

                if self.max_executions_per_tag_exceeded(entry.program.tags):
                    continue

                if self.has_non_updated_dependency(entry):
                    self.poke_entry(entry)
                    continue

                if not entry.poke_timeout:
                    continue

                entry.update(updater_command_queue = self.updater_command_queue, callback = self.poke_waiting_for_dependency)


    def terminate_observer(self):
        self.observer.unschedule_all()
        self.observer.stop()
        self.observer.join()


    def set_max_parallel_executions_per_program_tag(self, tag: str, count: int):
        self.max_parallel_execution_per_tag[tag] = count


    def max_executions_per_tag_exceeded(self, tags: typing.Iterable[str]):

        updating_entries = [entry for entry in self.entries if entry.status in (Status.UPDATING, Status.YIELDING)]

        execution_limiting_tags = [tag for tag in tags if tag in self.max_parallel_execution_per_tag]
        if not execution_limiting_tags:
            return self.default_max_parallel_executions <= len(updating_entries)

        for tag in execution_limiting_tags:
            if self.max_parallel_execution_per_tag[tag] <= sum(tag in entry.program.tags for entry in updating_entries):
                return True

        return False


    def set_shared_failure_by_tag(self, tag: str):
        """ If a program with the tag gets an `error` status then all the programs with that tag also get the `error` status. """
        self.shared_failure_tags.add(tag)


    def command_queue_runner(self):


        for item in iter(self.updater_command_queue.get, SENTINEL):

            print("[updater got]:", item)

            command = item.get(communication.Command_Key.COMMAND)

            if command == communication.Command.REQUEST_ALL_CORES:

                for entry in self.entries:

                    if entry.status != Status.UPDATING:
                        continue

                    if entry.entry_id == item['entry_id']:
                        continue

                    entry.suspend()
                    entry.status = Status.YIELDING


                running_entry = next(entry for entry in self.entries if entry.entry_id == item['entry_id'])
                print('Acquired cores:', running_entry.program.blend_path)
                update_ui()


                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listening_socket:

                    host = 'localhost'
                    listening_socket.bind((host, 0))
                    port = listening_socket.getsockname()[1]

                    running_entry.updater_response_queue.put({communication.Command_Key.RESULT: True, "address": (host, port)})

                    listening_socket.listen()

                    client_socket, addr = listening_socket.accept()
                    client_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, True)

                    try:
                        client_socket.recv(1)
                    except ConnectionResetError as e:
                        print(e)

                    for entry in self.entries:

                        if entry.status != Status.YIELDING:
                            continue

                        if entry.entry_id == running_entry.entry_id:
                            continue

                        entry.resume()
                        entry.status = Status.UPDATING


                print('Released cores:', running_entry.program.blend_path)
                update_ui()


def update_ui():
    """ Replace it with a custom update function. """
    pass


def stdout_line_printed():
    pass


def stderr_line_printed():
    pass
