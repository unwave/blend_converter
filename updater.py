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

from watchdog import events as watchdog_events
from watchdog import observers as watchdog_observers
import psutil

from . import common
from . import utils

UPDATE_DELAY = 2
""" For update debouncing. """


LOG_DIR = os.path.join(utils.BLEND_CONVERTER_USER_DIR, 'logs')


def kill_process(process: multiprocessing.Process):

    print(f"Killing process: {repr(process)}")

    try:
        parent_process = psutil.Process(process.pid)
    except ProcessLookupError:
        import traceback
        traceback.print_exc()
        return

    for child in parent_process.children(recursive=True):
        child.kill()

    parent_process.kill()


class Program_Entry:


    def __init__(self, program: common.Program, from_module_file: str, programs_getter_name: str, dictionary_key: str):

        self.program = program

        self.poke_time = 0

        report_stem = os.path.splitext(os.path.basename(program.report_path))[0]

        self.stdout_file = os.path.join(LOG_DIR, f"{report_stem}_stdout_{uuid.uuid1().hex}.txt")
        self.stderr_file = os.path.join(LOG_DIR, f"{report_stem}_stderr_{uuid.uuid1().hex}.txt")

        self.status: typing.Literal['ok', 'needs_update', 'updating', 'error', 'does_not_exist', 'waiting_for_dependency', 'unknown'] = 'unknown'

        self.process: typing.Optional[multiprocessing.Process] = None

        self.is_live_update = True

        self.is_manual_update = False


        self.dictionary_key = dictionary_key
        """ Key of the program in the programs dictionary. """

        self.from_module_file = from_module_file
        """ A module file which the common.Program was collected from. """

        self.programs_getter_name = programs_getter_name
        """ Name of a function that will return a dictionary with programs """


        # self.path_list = os.path.realpath(program.blend_path).split(os.path.sep)

        self.lock = multiprocessing.Lock()

        self.timeout: typing.Optional[float] = program.timeout

        self.stdout_queue = multiprocessing.Queue()
        self.stderr_queue = multiprocessing.Queue()

        self.stdout_lines = []
        self.stderr_lines = []


    def poke(self, has_non_updated_dependency: bool):

        if has_non_updated_dependency:
            self.status = 'waiting_for_dependency'
        elif os.path.exists(self.program.blend_path):
            if self.program.are_instructions_changed:
                self.status = 'needs_update'
            else:
                self.status = 'ok'
        else:
            self.status = 'does_not_exist'

        self.poke_time = time.time()

        update_ui()


    @property
    def poke_timeout(self):
        return (time.time() - self.poke_time) > UPDATE_DELAY


    def update_job(self):
        """ This function is run in `multiprocessing.Process` """

        from . import utils
        utils.print_in_color = utils.dummy_print_in_color

        os.makedirs(os.path.dirname(self.stdout_file), exist_ok=True)
        os.makedirs(os.path.dirname(self.stderr_file), exist_ok=True)

        def stdout_capture_job():

            with open(self.stdout_file, 'w', encoding='utf-8') as f:

                f.reconfigure(line_buffering = True)

                for line in iter(stdout_capture.lines.get, None):

                    self.stdout_queue.put_nowait(line)
                    f.write(f"[{time.strftime('%H:%M:%S %Y-%m-%d')}]: {line.rstrip()}\n")

        def stderr_capture_job():

            with open(self.stderr_file, 'w', encoding='utf-8') as f:

                f.reconfigure(line_buffering = True)

                for line in iter(stderr_capture.lines.get, None):
                    self.stderr_queue.put_nowait(line)
                    f.write(f"[{time.strftime('%H:%M:%S %Y-%m-%d')}]: {line.rstrip()}\n")

        stdout_capture_thread = threading.Thread(target=stdout_capture_job, daemon=True)
        stderr_capture_thread = threading.Thread(target=stderr_capture_job, daemon=True)

        error = None

        with utils.Capture_Stdout(line_buffering = True) as stdout_capture, utils.Capture_Stderr(line_buffering = True) as stderr_capture:

            stderr_capture_thread.start()
            stdout_capture_thread.start()

            try:
                self.program.execute()
            except BaseException as e:
                error = e
                if str(e) != 'BLENDER':
                    traceback.print_exc()

        stdout_capture.lines.put_nowait(None)
        stdout_capture_thread.join()
        stderr_capture.lines.put_nowait(None)
        stderr_capture_thread.join()

        if error:
            raise SystemExit(1)


    def _run(self, callback: typing.Callable, thread_identity: uuid.UUID):

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

        process = multiprocessing.Process(target=self.update_job, daemon=True)
        self.process = process
        process.start()

        exit_func = atexit.register(lambda: kill_process(process))

        process.join(timeout = self.timeout)

        if process.exitcode == None:
            kill_process(process)

        is_superseded = thread_identity != self.thread_identity

        if is_superseded:
            self.stderr_queue.put_nowait(f"THE UPDATE HAS BEEN SUPERSEDED: {thread_identity}")
        else:
            self.process = None

        atexit.unregister(exit_func)

        self.stdout_queue.put_nowait(None)
        read_stdout_thread.join()

        self.stderr_queue.put_nowait(None)
        read_stderr_thread.join()

        if is_superseded:
            update_ui()
            return

        if process.exitcode == 0:
            self.status = 'ok'
            print(f"Done [{time.strftime('%H:%M:%S %Y-%m-%d')}]:", self.program)
        elif process.exitcode == None:
            self.status = 'error'
            print(f"Timeout [{time.strftime('%H:%M:%S %Y-%m-%d')}]:", self.program)
        else:
            self.status = 'error'
            print(f"Error [{time.strftime('%H:%M:%S %Y-%m-%d')}]:", self.program)


        if callback:
            callback()

        update_ui()


    def update(self, callback: typing.Optional[typing.Callable]):

        with self.lock:

            print(f"Processing [{time.strftime('%H:%M:%S %Y-%m-%d')}]:", self.program)

            self.status = 'updating'

            self.is_dirty = False

            self.thread_identity = uuid.uuid4()

            if self.process:
                kill_process(self.process)

            threading.Thread(target=self._run, kwargs=dict(callback=callback, thread_identity = self.thread_identity), daemon = True).start()

            update_ui()


    def terminate(self):

        with self.lock:
            if self.process:
                kill_process(self.process)


class Blend_Event_Handler(watchdog_events.PatternMatchingEventHandler):

    def __init__(self, queue: queue.Queue,  *args, **kwargs):
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


def get_program_entries(file_and_getter_pairs):

    entries = []

    modules = import_files([p[0] for p in file_and_getter_pairs])

    for file_name, getter_name in file_and_getter_pairs:

        module = modules[os.path.realpath(file_name)]

        key_to_program: dict = getattr(module, getter_name)()

        for key, program in key_to_program.items():
            if isinstance(program, common.Program):
                entries.append(Program_Entry(program, module.__file__, getter_name, key))
            else:
                utils.print_in_color(utils.get_color_code(255,255,255,128,0,0,), f"`{key}` is not a common.Program: {repr(program)}", file=sys.stderr)

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


    def init_observer(self):

        self.queue = queue.Queue()
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
    def from_files(cls, file_and_getter_pairs: typing.List[typing.Tuple[str, str]]):

        updater = cls()

        updater.entries = get_program_entries(file_and_getter_pairs)

        updater.poke_all()

        updater.init_observer()
        updater.schedule_observer()

        update_ui()

        return updater


    def has_non_updated_dependency(self, entry: Program_Entry):
        return any(
            _entry.program.result_path == entry.program.blend_path
            for _entry in self.entries
            if not _entry is entry and _entry.status != 'ok'
        )

    def poke_entry(self, entry: Program_Entry):
        entry.poke(self.has_non_updated_dependency(entry))

    def poke_waiting_for_dependency(self):

        for entry in self.entries:
            if entry.status == 'waiting_for_dependency':
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
        return sum(entry.status == 'updating' for entry in self.entries) >= self.total_max_parallel_executions


    def despatching(self):

        while 1:

            time.sleep(1)


            failed_tags = set()

            for entry in self.entries:

                if entry.status != 'error':
                    continue

                failed_tags.update(self.shared_failure_tags.intersection(entry.program.tags))

            if failed_tags:

                for entry in self.entries:
                    if not entry.program.tags.isdisjoint(failed_tags):
                        entry.status = 'error'

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
                entry.update(self.poke_waiting_for_dependency)


            if self.is_paused:
                continue


            for entry in self.entries:

                if not entry.is_live_update:
                    continue

                if entry.status != 'needs_update':
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

                entry.update(self.poke_waiting_for_dependency)


    def terminate_observer(self):
        self.observer.unschedule_all()
        self.observer.stop()
        self.observer.join()


    def set_max_parallel_executions_per_program_tag(self, tag: str, count: int):
        self.max_parallel_execution_per_tag[tag] = count


    def max_executions_per_tag_exceeded(self, tags: typing.Iterable[str]):

        updating_entries = [entry for entry in self.entries if entry.status == 'updating']

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


def update_ui():
    """ Replace it with a custom update function. """
    pass


def stdout_line_printed():
    pass


def stderr_line_printed():
    pass
