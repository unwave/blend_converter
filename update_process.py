import os
import threading
import queue
import traceback
import multiprocessing

from datetime import datetime, timezone

from . import utils
from . import common


def capturing(*, file_path: str, capture_queue: queue.Queue, output_queue: multiprocessing.Queue):

    with open(file_path, 'w', encoding='utf-8') as f:

        f.reconfigure(line_buffering = True)

        for line in iter(capture_queue.get, None):

            output_queue.put(line)

            time = datetime.now(timezone.utc).astimezone().isoformat(' ', 'milliseconds')
            f.write(f"[{time}]: {line}")


def propagate_command_queue(*, entry_id: str, entry_command_queue: queue.Queue, updater_command_queue: multiprocessing.Queue):

    for item in iter(entry_command_queue.get, None):
        item['entry_id'] = entry_id
        updater_command_queue.put(item)


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


    entry_command_queue = queue.Queue()

    propagate_command_queue_thread = threading.Thread(
        target = propagate_command_queue,
        kwargs = dict(
            entry_id = entry_id,
            entry_command_queue = entry_command_queue,
            updater_command_queue = updater_command_queue,
        ),
        daemon = True
    )

    propagate_command_queue_thread.start()


    error = None

    with (
            utils.Capture_Stdout(line_buffering = True) as stdout_capture,
            utils.Capture_Stderr(line_buffering = True) as stderr_capture
        ):


        stdout_capturing = threading.Thread(
            target = capturing,
            kwargs = dict(
                file_path = stdout_file,
                capture_queue = stdout_capture.lines,
                output_queue = stdout_queue
            ),
            daemon = True
        )

        stderr_capturing = threading.Thread(
            target = capturing,
            kwargs = dict(
                file_path = stderr_file,
                capture_queue = stderr_capture.lines,
                output_queue = stderr_queue
            ),
            daemon = True
        )

        stderr_capturing.start()
        stdout_capturing.start()

        try:
            program.execute(entry_command_queue = entry_command_queue, updater_response_queue = updater_response_queue)
        except BaseException as e:
            error = e
            if str(e) != 'BLENDER':
                traceback.print_exc()


    stdout_capture.lines.put(None)
    stdout_capturing.join()
    stderr_capture.lines.put(None)
    stderr_capturing.join()

    entry_command_queue.put(None)
    propagate_command_queue_thread.join()


    if error:
        raise SystemExit(1)
