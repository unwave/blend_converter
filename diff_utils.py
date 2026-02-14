import os
import tempfile
import json
import subprocess
import threading
import itertools
import shutil

from . import utils
from . import common


def write_file(dir: str, basename: str, text: str):

    filepath = os.path.join(dir, utils.ensure_valid_basename(basename))
    filepath = utils.ensure_unique_path(filepath)

    with open(filepath, 'w') as f:
        f.write(text)

    return filepath


def show_program_diff_vscode(program: common.Program):

    with tempfile.TemporaryDirectory() as temp_dir:

        a = program.get_prev_report_diff()
        b = program.get_next_report_diff()

        old = write_file(temp_dir, 'old.json', json.dumps(a, indent=4, default= lambda x: x._to_dict()))
        new = write_file(temp_dir, 'new.json', json.dumps(b, indent=4, default= lambda x: x._to_dict()))

        code = shutil.which('code')

        main_cmd = [code, '--new-window', '--wait', '--diff', old, new]

        commands = []

        instructions_a = utils.deduplicate([(script.get('filepath'), script.get('name', ''), script.get('sha256'), script.get('code', '')) for script in a.get('instructions', [])])
        instructions_b = utils.deduplicate([(script.get('filepath'), script.get('name', ''), script.get('sha256'), script.get('code', '')) for script in b.get('instructions', [])])

        for script_a, script_b in itertools.product(instructions_a, instructions_b):

            show_func_diff = (
                script_a[0] == script_b[0]
                and
                script_a[1] == script_b[1]
                and
                script_a[2] != script_b[2]
            )

            if show_func_diff:

                func1 = script_a[1] + '.py'
                func2 = script_b[1] + '.py'

                cmd = [
                    code,
                    '--reuse-window',
                    '--diff',
                    write_file(temp_dir, func1, script_a[3]),
                    write_file(temp_dir, func2, script_b[3]),
                ]
                commands.append(cmd)

        def open_others():
            import time
            time.sleep(1)
            for cmd in commands:
                subprocess.Popen(cmd)

        threading.Thread(target=open_others).start()

        subprocess.run(main_cmd)
