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

from .format import common
from . import utils

UPDATE_DELAY = 2

# MAX_AMOUNT_OF_UPDATING_ENTRIES = multiprocessing.cpu_count() - 1
MAX_AMOUNT_OF_UPDATING_ENTRIES = 2

TIMEOUT = None

LOG_DIR = r'D:\Desktop\temp_log_location_bc'


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


class Model_Entry:


    def __init__(self, model: common.Blend_Base, module = None):
        self.model = model

        self.poke_time = 0

        self.stem = os.path.splitext(os.path.basename(model.blend_path))[0]

        self.stdout_file = os.path.join(LOG_DIR, f"{self.stem}_stdout_{uuid.uuid1().hex}.txt")
        self.stderr_file = os.path.join(LOG_DIR, f"{self.stem}_stderr_{uuid.uuid1().hex}.txt")

        self.status: typing.Literal['ok', 'needs_update', 'updating', 'error', 'does_not_exist', 'waiting_for_dependency', 'unknown'] = 'unknown'

        self.process: typing.Optional[multiprocessing.Process] = None

        self.is_live_update = True

        self.is_manual_update = False

        self.module = module
        """ A module where the model was collected from. """

        self.result_path = model.result_path
        self.blend_path = model.blend_path

        self.path_list = os.path.realpath(model.blend_path).split(os.path.sep)

        self.lock = multiprocessing.Lock()

        self.timeout: typing.Optional[float] = TIMEOUT

        self.stdout_queue = multiprocessing.Queue()
        self.stderr_queue = multiprocessing.Queue()

        self.stdout_lines = []
        self.stderr_lines = []


    def poke(self, has_non_updated_dependency: bool):

        if has_non_updated_dependency:
            self.status = 'waiting_for_dependency'
        elif os.path.exists(self.blend_path):
            if self.model.needs_update:
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

        def stdout_capture_job():
            with open(self.stdout_file, 'a+', encoding='utf-8') as f:
                for line in iter(stdout_capture.lines.get, None):
                    self.stdout_queue.put_nowait(line)
                    f.write(line)

        def stderr_capture_job():
            with open(self.stderr_file, 'a+', encoding='utf-8') as f:
                for line in iter(stderr_capture.lines.get, None):
                    self.stderr_queue.put_nowait(line)
                    f.write(line)

        stdout_capture_thread = threading.Thread(target=stdout_capture_job, daemon=True)
        stderr_capture_thread = threading.Thread(target=stderr_capture_job, daemon=True)

        with utils.Capture_Stdout() as stdout_capture, utils.Capture_Stderr() as stderr_capture:
            stderr_capture_thread.start()
            stdout_capture_thread.start()
            try:
                self.model.update(True)
            except Exception as e:
                raise Exception(f"Failed to convert the blend: {self.model.blend_path}") from e
            finally:
                stdout_capture.lines.put_nowait(None)
                stdout_capture_thread.join()
                stderr_capture.lines.put_nowait(None)
                stderr_capture_thread.join()


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
            return

        if process.exitcode == 0:
            self.status = 'ok'
            print(f"Done [{time.strftime('%H:%M:%S %Y-%m-%d')}]:", self.blend_path)
        elif process.exitcode == None:
            self.status = 'error'
            print(f"Timeout [{time.strftime('%H:%M:%S %Y-%m-%d')}]:", self.blend_path)
        else:
            self.status = 'error'
            print(f"Error [{time.strftime('%H:%M:%S %Y-%m-%d')}]:", self.blend_path)


        if callback:
            callback()

        update_ui()


    def update(self, callback: typing.Optional[typing.Callable]):

        with self.lock:

            print(f"Processing [{time.strftime('%H:%M:%S %Y-%m-%d')}]:", self.blend_path)

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


class Updater:

    def __init__(self):

        self.is_paused = True

        self.entries: list[Model_Entry] = []

        self.modules: list[types.ModuleType] = []

        self.init_modules = set(sys.modules)
        self.imported_modules = set()

        self.init_files = []


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

        dirs = set(os.path.dirname(entry.blend_path) for entry in self.entries)
        for dir in dirs:
            os.makedirs(dir, exist_ok=True)
            self.observer.schedule(self.event_handler, dir, recursive=True)


    def reload_files(self, files: list[str]):

        if self.imported_modules:

            # TODO: there are stale copies of blend_converter parts somewhere and importlib.reloads needs a fix for multiprocessing pickling
            for imported_module in self.imported_modules:
                try:
                    del sys.modules[imported_module]
                except KeyError:
                    traceback.print_exc()

            importlib.invalidate_caches()

        self.modules.clear()

        dirs = set(os.path.dirname(file) for file in files)
        for dir in dirs:
            if not dir in sys.path:
                sys.path.append(dir)

        for file in files:
            module = utils.import_module_from_file(file)
            self.modules.append(module)

        self.imported_modules = set(sys.modules) - self.init_modules

        self.init_files = files

        print(self.imported_modules)


    @classmethod
    def from_files(cls, files: list[str]):

        updater = cls()

        updater.reload_files(files)
        updater.set_entires_from_modules()
        updater.poke_all()
        updater.init_observer()
        updater.schedule_observer()

        update_ui()

        return updater

    def set_entires_from_modules(self):

        for entry in self.entries:
            entry.terminate()

        self.entries.clear()

        for module in self.modules:
            for key, value in getattr(module, '__blends__').items():
                if isinstance(value, common.Blend_Base):
                    self.entries.append(Model_Entry(value))
                else:
                    utils.print_in_color(utils.get_color_code(255,255,255,128,0,0,), f"`{key}` is not a model: {repr(value)}", file=sys.stderr)



    def has_non_updated_dependency(self, entry: Model_Entry):
        return any(
            _entry.result_path == entry.blend_path
            for _entry in self.entries
            if not _entry is entry and _entry.status != 'ok'
        )

    def poke_entry(self, entry: Model_Entry):
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

    def reload_targets(self):

        for entry in self.entries:
            entry.terminate()

        self.observer.unschedule_all()

        with self.queue.mutex:
            self.queue.queue.clear()

        self.reload_files([module.__file__ for module in self.modules])
        self.set_entires_from_modules()

        self.poke_all()
        self.schedule_observer()

        print(f"Targets reloaded {utils.get_time_str_from(time.time())}")

        update_ui()

    def poking(self):
        for path in iter(self.queue.get, None):
            for entry in self.entries:
                if entry.blend_path == path:
                    self.poke_entry(entry)

    def max_updating_entries_exceeded(self):
        updating_entires = len([entry for entry in self.entries if entry.status == 'updating'])
        return updating_entires >= MAX_AMOUNT_OF_UPDATING_ENTRIES

    def despatching(self):

        while 1:

            time.sleep(1)

            if self.max_updating_entries_exceeded():
                continue

            for entry in self.entries:

                if entry.is_manual_update:
                    entry.is_manual_update = False
                    entry.update(self.poke_waiting_for_dependency)

            if not self.is_paused:

                for entry in self.entries:

                    if entry.status != 'needs_update':
                        continue

                    if entry.is_live_update and entry.poke_timeout:
                        entry.update(self.poke_waiting_for_dependency)




    def terminate_observer(self):
        self.observer.unschedule_all()
        self.observer.stop()
        self.observer.join()


def update_ui():
    """ Replace it with a custom update function. """
    pass


def stdout_line_printed():
    pass


def stderr_line_printed():
    pass
