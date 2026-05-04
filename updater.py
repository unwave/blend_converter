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
import traceback
import socket
import collections


from watchdog import events as watchdog_events
from watchdog import observers as watchdog_observers
import psutil

from . import common
from . import serialization
from . import utils
from . import communication
from . import update_process


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
    SLEEPING = 'sleeping'

STATUS_ICON = {
    Status.OK: '👍',
    Status.STALE: '🦕',
    Status.UPDATING: '🔨',
    Status.YIELDING: '⛔',
    Status.ERROR: '❗',
    Status.DOES_NOT_EXIST: '👻',
    Status.WAITING_FOR_DEPENDENCY: '🔒',
    Status.UNKNOWN: '❓',
    Status.SLEEPING: '💤',
}


def get_status(program: common.Program):

    if not program.blend_path:
        return Status.UNKNOWN
    elif os.path.exists(program.blend_path):
        if program.are_instructions_changed:
            return Status.STALE
        else:
            return Status.OK
    else:
        return Status.DOES_NOT_EXIST


class Program_Entry:


    def __init__(self, programs_getter: serialization.Function, keyword_arguments: dict):

        self.entry_id = uuid.uuid1().hex

        self.program = common.Program(blend_path = '', result_path = '', blender_executable = '')

        self.stdout_file = ''
        self.stderr_file = ''

        self.status = Status.UNKNOWN

        self.is_live_update = True

        self.is_manual_update = False


        self.keyword_arguments = keyword_arguments
        """ The program keyword arguments. """

        self.programs_getter = programs_getter
        """ The function that will return the program. """

        self.lock = threading.RLock()

        self.stdout_lines = []
        self.stderr_lines = []

        self.psutil_process: psutil.Process = None

        self.post_initialized = False

        self.running: threading.Thread = None


    def post_init(self):

        with self.lock:

            if self.post_initialized:
                return

            report_stem = os.path.splitext(os.path.basename(self.program.report_path))[0]

            self.stdout_file = os.path.join(LOG_DIR, f"{report_stem}_stdout_{uuid.uuid1().hex}.txt")
            self.stderr_file = os.path.join(LOG_DIR, f"{report_stem}_stderr_{uuid.uuid1().hex}.txt")

            self.stdout_queue = multiprocessing.SimpleQueue()
            self.stderr_queue = multiprocessing.SimpleQueue()

            self.updater_response_queue: 'multiprocessing.SimpleQueue[dict]' = multiprocessing.SimpleQueue()

            self.execution_context = common.Execution_Context()

            self.post_initialized = True


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
                    execution_context = self.execution_context,
                    programs_getter = self.programs_getter,
                    keyword_arguments = self.keyword_arguments,
                ),
                daemon=True,
            )
            process.start()

            self.psutil_process = psutil.Process(process.pid)


        exit_func = atexit.register(utils.kill_process, self.psutil_process)

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

        with self.execution_context.lock:
            self.execution_context.no_pending_children.value = True
            self.execution_context.is_process_running.value = False
            self.execution_context.lock.notify_all()

        if is_superseded:
            return

        is_ok = process.exitcode == 0

        if is_ok:
            print(f"Done [{time.strftime('%H:%M:%S %Y-%m-%d')}]:", self.program)
        else:
            print(f"Error [{time.strftime('%H:%M:%S %Y-%m-%d')}]:", self.program)

        callback(self, is_ok, thread_identity)


    def update(self, *, updater_command_queue: 'multiprocessing.SimpleQueue[dict]' = None, callback: typing.Optional[typing.Callable] = None):

        print(f"Processing [{time.strftime('%H:%M:%S %Y-%m-%d')}]:", self)

        with self.lock:

            self.post_init()

            self.thread_identity = uuid.uuid4()

            self.terminate()

            if self.running is not None:
                self.running.join()

            with self.execution_context.lock:

                self.execution_context.no_pending_children.value = False
                self.execution_context.is_process_running.value = True
                self.execution_context.lock.notify_all()

            self.running = threading.Thread(
                target=self._run,
                kwargs=dict(
                    callback=callback,
                    thread_identity = self.thread_identity,
                    updater_command_queue = updater_command_queue
                ),
                daemon = True
            )

            self.running.start()

            self.status = Status.UPDATING


    def terminate(self):

        print(f"Terminating: {self.entry_id}")

        with self.lock:

            if self.psutil_process is None:
                return

            if not self.psutil_process.is_running():
                return

            with self.execution_context.lock:
                self.execution_context.is_process_running.value = False
                self.execution_context.lock.notify_all()

            utils.kill_process(self.psutil_process)

            self.stderr_lines.append(f"The process has been terminated: {time.strftime('%H:%M:%S %Y-%m-%d')}")
            stderr_line_printed(self)

            print(f"Terminated: {self.entry_id}")


    def suspend(self):

        print(f"Suspending: {self.entry_id}")

        with self.lock:

            if self.psutil_process is None:
                return

            if not self.psutil_process.is_running():
                return

            with self.execution_context.lock:

                self.execution_context.is_process_running.value = False
                self.execution_context.lock.notify_all()

                self.execution_context.lock.wait_for(
                    lambda: self.execution_context.are_executors_stopped.value or self.execution_context.no_pending_children.value
                )

            try:

                for child in self.psutil_process.children(recursive=True):
                    try:
                        child.suspend()
                    except psutil.Error as e:
                        print(e)

            except psutil.Error as e:
                print(e)

            print(f"Suspended: {self.entry_id}")


    def resume(self):

        print(f"Resuming: {self.entry_id}")

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

            with self.execution_context.lock:
                self.execution_context.is_process_running.value = True
                self.execution_context.lock.notify_all()

            print(f"Resumed: {self.entry_id}")


    def __repr__(self):
        return f"<Entry {self.entry_id}: {self.programs_getter}::({self.keyword_arguments})>"


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


def get_program_entries(definitions: typing.List[common.Program_Definition]):

    entries = []

    for d in definitions:

        for arguments in d.arguments_getter.get()(*d.args, **d.kwargs):

            entries.append(Program_Entry(d.program_getter, arguments))

    return entries



class Updater:

    def __init__(self):

        self.is_paused = True

        self.entries: list[Program_Entry] = []
        self.result_path_to_entry: typing.Dict[str, Program_Entry] = {}
        self.source_path_to_entry: typing.Dict[str, typing.List[Program_Entry]] = {}

        self.max_parallel_execution_per_tag = {}

        self.default_max_parallel_executions = 2
        """  Max parallel executions for programs with no limiting tags. """

        self.total_max_parallel_executions = 2
        """ Total max parallel executions. """

        self.shared_failure_tags = set()
        """ See `set_shared_failure_by_tag`. """

        self.updater_command_queue: 'multiprocessing.SimpleQueue[dict]' = multiprocessing.SimpleQueue()

        self.command_queue_running = threading.Thread(target = self.command_queue_runner, daemon=True)
        self.command_queue_running.start()

        self.program_getting_pool = multiprocessing.Pool(processes=os.cpu_count()//2)


    def update_entries(self):

        tasks = []

        for entry in self.entries:

            tasks.append(self.program_getting_pool.apply_async(
                load_program,
                kwds = dict(
                    function = entry.programs_getter._to_dict(),
                    kwargs = entry.keyword_arguments,
                )
            ))

        def final_callback():

            dirs_to_watch = []

            for task, entry in zip(tasks, self.entries):

                program, status = task.get()

                entry.program = program
                entry.status = status

                if entry.program.blend_path:
                    dirs_to_watch.append(os.path.dirname(entry.program.blend_path))

            for folder in utils.deduplicate(dirs_to_watch):
                self.observer.schedule(self.event_handler, folder)

            self.result_path_to_entry = {e.program.result_path: e for e in self.entries if e.program.result_path}

            self.source_path_to_entry = collections.defaultdict(list)
            for e in self.entries:
                self.source_path_to_entry[e.program.blend_path].append(e)

            for entry in self.entries:
                if self.has_non_updated_dependency(entry):
                    entry.status = Status.WAITING_FOR_DEPENDENCY

            self.despatch()


        threading.Thread(target=final_callback).start()



    def init_observer(self):

        self.queue = queue.SimpleQueue()
        self.event_handler = Blend_Event_Handler(self.queue, patterns=['*.blend'])

        self.observer = watchdog_observers.Observer()
        self.observer.start()


    @classmethod
    def from_entries(cls, entries: typing.List[Program_Entry]):

        updater = cls()

        updater.entries = entries

        updater.init_observer()


        return updater


    def has_non_updated_dependency(self, entry: Program_Entry):

        if not entry.program.blend_path:
            return False

        parent_entry = self.result_path_to_entry.get(entry.program.blend_path)
        if parent_entry is None:
            return False

        return parent_entry.status != Status.OK


    def poke_entries(self, entires: typing.Iterable[Program_Entry]):
        self.updater_command_queue.put({
            communication.Key.COMMAND: communication.Command.POKE,
            'entry_ids': [entry.entry_id for entry in entires]
        })


    def callback(self, entry: Program_Entry, status: str, thread_identity: uuid.UUID):

        self.updater_command_queue.put({
            communication.Key.COMMAND: communication.Command.JOIN,
            'entry_id': entry.entry_id,
            'is_ok': status,
            'thread_identity': thread_identity,
        })


    def total_max_parallel_executions_exceeded(self):
        return sum(entry.status in (Status.UPDATING, Status.YIELDING, Status.SLEEPING) for entry in self.entries) >= self.total_max_parallel_executions


    def _despatch(self):

        failed_tags = set()

        result: typing.List[Program_Entry] = []


        for entry in self.entries:

            if entry.status != Status.ERROR:
                continue

            failed_tags.update(self.shared_failure_tags.intersection(entry.program.tags))

        if failed_tags:

            for entry in self.entries:
                if not entry.program.tags.isdisjoint(failed_tags):
                    entry.status = Status.ERROR


        for entry in self.entries:

            if entry.status == Status.UNKNOWN:
                continue

            if not entry.is_manual_update:
                continue

            if self.total_max_parallel_executions_exceeded():
                break

            if self.max_executions_per_tag_exceeded(entry.program.tags):
                continue

            if self.has_non_updated_dependency(entry):
                continue

            entry.is_manual_update = False
            entry.update(updater_command_queue = self.updater_command_queue, callback = self.callback)
            result.append(entry)


        if self.is_paused:
            return result


        for entry in self.entries:

            if entry.status == Status.UNKNOWN:
                continue

            if not entry.is_live_update:
                continue

            if entry.status != Status.STALE:
                continue

            if self.total_max_parallel_executions_exceeded():
                break

            if self.max_executions_per_tag_exceeded(entry.program.tags):
                continue

            if self.has_non_updated_dependency(entry):
                continue


            entry.update(updater_command_queue = self.updater_command_queue, callback = self.callback)
            result.append(entry)

        return result


    def despatch(self):
        self.updater_command_queue.put({communication.Key.COMMAND: communication.Command.DESPATCH})


    def terminate_observer(self):
        self.observer.unschedule_all()
        self.observer.stop()
        self.observer.join()


    def set_max_parallel_executions_per_program_tag(self, tag: str, count: int):
        self.max_parallel_execution_per_tag[tag] = count


    def max_executions_per_tag_exceeded(self, tags: typing.Iterable[str]):

        updating_entries = [entry for entry in self.entries if entry.status in (Status.UPDATING, Status.YIELDING, Status.SLEEPING)]

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


        yielding_for: typing.Set[str] = set()


        def waiting_for_release(entry: Program_Entry):

            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listening_socket:

                host = 'localhost'
                listening_socket.bind((host, 0))
                port = listening_socket.getsockname()[1]

                entry.updater_response_queue.put({communication.Key.RESULT: True, communication.Key.ADDRESS: (host, port)})

                listening_socket.listen()

                client_socket, addr = listening_socket.accept()
                client_socket.settimeout(None)
                client_socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                client_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, True)

            with client_socket:

                try:
                    client_socket.recv(1)
                except ConnectionResetError as e:
                    print(e)
                finally:
                    self.updater_command_queue.put({
                        communication.Key.COMMAND: communication.Command.RESUME_OTHERS,
                        'entry_id': entry.entry_id,
                    })


        def show_error(message: str):
            utils.show_nt_message("Command Queue Logical Error", message)
            print('Command:', item)
            traceback.print_stack()


        def get_active_yield_target():

            entries = [e for e in self.entries if e.status == Status.UPDATING and e.entry_id in yielding_for]

            if entries:
                if len(entries) != 1:
                    show_error(f"Multiple active yield targets: {[e.program.blend_path for e in entries]}")
                return entries[0]
            else:
                return None


        def make_others_yield(target_entires: typing.List[Program_Entry]):

            others = [e for e in self.entries if not e in target_entires and e.status == Status.UPDATING]

            for entry in others:
                entry.suspend()
                entry.status = Status.YIELDING


        def release_yielding_others(target_entires: typing.List[Program_Entry]):

            others = [e for e in self.entries if not e in target_entires and e.status == Status.YIELDING]

            entry_to_yield_for = next((e for e in others if e.entry_id in yielding_for), None)
            if entry_to_yield_for:
                entry_to_yield_for.resume()
                entry_to_yield_for.status = Status.UPDATING
            else:
                for entry in others:
                    entry.resume()
                    entry.status = Status.UPDATING


        def put_into_sleep(target_entries: typing.List[Program_Entry]):

            for entry in target_entries:
                if entry.status == Status.UPDATING:
                    entry.suspend()
                entry.status = Status.SLEEPING


        def terminate(target_entries: typing.List[Program_Entry]):

            for entry in target_entries:
                entry.is_manual_update = False
                entry.terminate()
                yielding_for.discard(entry.entry_id)
                entry.status = Status.ERROR


        for item in iter(self.updater_command_queue.get, SENTINEL):

            print("[updater got]:", item)

            command = item.get(communication.Key.COMMAND)


            if command == communication.Command.SHUTDOWN:
                return


            elif command == communication.Command.DESPATCH:

                new_entries = self._despatch()

                if get_active_yield_target():
                    for entry in new_entries:
                        entry.suspend()
                        entry.status = Status.YIELDING


            elif command == communication.Command.SUSPEND_OTHERS:

                entry_to_yield_for = next(entry for entry in self.entries if entry.entry_id == item['entry_id'])

                if not get_active_yield_target() or get_active_yield_target() is entry_to_yield_for:
                    make_others_yield([entry_to_yield_for])

                yielding_for.add(entry_to_yield_for.entry_id)

                threading.Thread(target = waiting_for_release, args=[entry_to_yield_for], daemon = True).start()


            elif command == communication.Command.RESUME_OTHERS:

                entry_to_yield_for = next(entry for entry in self.entries if entry.entry_id == item['entry_id'])

                if get_active_yield_target() is entry_to_yield_for:
                    release_yielding_others([entry_to_yield_for])
                elif entry_to_yield_for.status != Status.ERROR:
                    show_error(f"Unexpected race condition for {entry_to_yield_for.entry_id}: {entry_to_yield_for.program.blend_path}")

                yielding_for.discard(entry_to_yield_for.entry_id)


            elif command == communication.Command.SLEEP:

                target_entries = [e for e in self.entries if e.status in (Status.UPDATING, Status.YIELDING) and e.entry_id in item['entry_ids']]


                if not target_entries:
                    pass

                elif get_active_yield_target() in target_entries:

                    put_into_sleep(target_entries)
                    release_yielding_others(target_entries)

                else:

                    put_into_sleep(target_entries)


            elif command == communication.Command.WAKE:

                target_sleeping_entries = [e for e in self.entries if e.status == Status.SLEEPING and e.entry_id in item['entry_ids']]


                if not target_sleeping_entries:
                    pass

                elif get_active_yield_target():

                    for entry in target_sleeping_entries:
                        entry.status = Status.YIELDING

                elif any(e.entry_id in yielding_for for e in target_sleeping_entries):

                    for entry in target_sleeping_entries:
                        entry.status = Status.YIELDING

                    make_others_yield([])

                    entry_to_yield_for = next(e for e in target_sleeping_entries if e.entry_id in yielding_for)
                    entry_to_yield_for.resume()
                    entry_to_yield_for.status = Status.UPDATING

                else:

                    for entry in target_sleeping_entries:
                        entry.resume()
                        entry.status = Status.UPDATING


            elif command == communication.Command.TERMINATE:

                for e in [e for e in self.entries if e.entry_id in item['entry_ids']]:
                    e.is_manual_update = False

                entries_to_terminate = [e for e in self.entries if e.status in (Status.UPDATING, Status.YIELDING, Status.SLEEPING) and e.entry_id in item['entry_ids']]


                if not entries_to_terminate:
                    pass

                elif get_active_yield_target() in entries_to_terminate:

                    terminate(entries_to_terminate)
                    release_yielding_others(entries_to_terminate)

                else:

                    terminate(entries_to_terminate)

            elif command == communication.Command.SET_AS_STALE:

                target_entries = [e for e in self.entries if e.status in (Status.OK, Status.ERROR) and e.entry_id in item['entry_ids']]

                for entry in target_entries:
                    entry.status = Status.STALE

            elif command == communication.Command.SET_AS_OK:

                target_entries = [e for e in self.entries if e.status in (Status.STALE, Status.ERROR) and e.entry_id in item['entry_ids']]

                for entry in target_entries:
                    entry.program.write_report()

            elif command == communication.Command.POKE:

                target_entries = [e for e in self.entries if e.status not in (Status.UPDATING, Status.YIELDING, Status.SLEEPING) and e.entry_id in item['entry_ids']]

                for entry in target_entries:
                    if self.has_non_updated_dependency(entry):
                        entry.status = Status.WAITING_FOR_DEPENDENCY
                    else:
                        entry.status = get_status(entry.program)

            elif command == communication.Command.JOIN:

                entry = next(e for e in self.entries if e.entry_id == item['entry_id'])

                if entry.thread_identity == item['thread_identity']:

                    if item['is_ok']:
                        entry.status = Status.OK
                    else:
                        entry.status = Status.ERROR

                    self.poke_entries(self.source_path_to_entry.get(entry.program.result_path, ()))

                    self.despatch()

            elif command == communication.Command.EXECUTE:

                entries = [e for e in self.entries if e.entry_id in item['entry_ids']]
                target_entries = [e for e in entries if e.status not in (Status.UPDATING, Status.YIELDING, Status.SLEEPING) and not e.is_manual_update]

                for entry in target_entries:
                    entry.is_manual_update = True

                self.despatch()


            get_active_yield_target()  # for validation
            update_ui()


def update_ui():
    """ Replace it with a custom update function. """
    pass


def update_item(entry):
    """ Replace it with a custom update function. """
    pass


def stdout_line_printed():
    pass


def stderr_line_printed():
    pass


def load_program(function: dict, kwargs: dict):
    program: common.Program = serialization.Function.from_dict(function).get()(**kwargs)
    return program, get_status(program)
