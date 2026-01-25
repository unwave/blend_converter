import os
import time
import threading
import queue
import traceback
import multiprocessing


from . import utils
from . import common


def run(*,
            stdout_file: str,
            stderr_file: str,
            stdout_queue: multiprocessing.Queue,
            stderr_queue: multiprocessing.Queue,
            entry_id: str,
            updater_command_queue: multiprocessing.Queue,
            updater_response_queue: multiprocessing.Queue,
            program: common.Program,
        ):


    utils.print_in_color = utils.dummy_print_in_color


    os.makedirs(os.path.dirname(stdout_file), exist_ok=True)
    os.makedirs(os.path.dirname(stderr_file), exist_ok=True)


    def stdout_capture_job():

        with open(stdout_file, 'w', encoding='utf-8') as f:

            f.reconfigure(line_buffering = True)

            for line in iter(stdout_capture.lines.get, None):

                stdout_queue.put(line)
                f.write(f"[{time.strftime('%H:%M:%S %Y-%m-%d')}]: {line.rstrip()}\n")

    def stderr_capture_job():

        with open(stderr_file, 'w', encoding='utf-8') as f:

            f.reconfigure(line_buffering = True)

            for line in iter(stderr_capture.lines.get, None):
                stderr_queue.put_nowait(line)
                f.write(f"[{time.strftime('%H:%M:%S %Y-%m-%d')}]: {line.rstrip()}\n")


    def propagate_command_queue():

        for item in iter(entry_command_queue.get, None):
            item['entry_id'] = entry_id
            updater_command_queue.put(item)


    stdout_capture_thread = threading.Thread(target=stdout_capture_job, daemon=True)
    stderr_capture_thread = threading.Thread(target=stderr_capture_job, daemon=True)

    entry_command_queue = queue.Queue()
    propagate_command_queue_thread = threading.Thread(target=propagate_command_queue, daemon=True)
    propagate_command_queue_thread.start()

    error = None

    with utils.Capture_Stdout(line_buffering = True) as stdout_capture, utils.Capture_Stderr(line_buffering = True) as stderr_capture:

        stderr_capture_thread.start()
        stdout_capture_thread.start()

        try:
            program.execute(entry_command_queue = entry_command_queue, updater_response_queue = updater_response_queue)
        except BaseException as e:
            error = e
            if str(e) != 'BLENDER':
                traceback.print_exc()

    stdout_capture.lines.put_nowait(None)
    stdout_capture_thread.join()
    stderr_capture.lines.put_nowait(None)
    stderr_capture_thread.join()

    entry_command_queue.put_nowait(None)
    propagate_command_queue_thread.join()

    if error:
        raise SystemExit(1)
