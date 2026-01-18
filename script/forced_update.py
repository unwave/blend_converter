import sys
import os

programs = sys.argv[1]

ARGS = sys.argv[2:]

import sys
import importlib.util
import os
import typing
import re
import json
import traceback


def import_module(module_path: str):

    module_dir = os.path.dirname(module_path)
    if not module_dir in sys.path:
        sys.path.append(module_dir)

    module_name = os.path.splitext(os.path.basename(module_path))[0]

    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None:
        raise Exception(f"Spec not found: {module_name}, {module_path}")

    module = importlib.util.module_from_spec(spec)

    sys.modules[module_name] = module
    spec.loader.exec_module(module)  # type: ignore[reportOptionalMemberAccess]

    return module


from blend_converter import common

from blend_converter import diff_utils

from blend_converter import utils

from blend_converter.blender import blend_inspector




inspect_options: typing.List[str] = []
skip_options: typing.List[str] = []

for key, value in blend_inspector.COMMON.__dict__.items():
    if key.startswith('_'):
        continue
    elif value.startswith('inspect'):
        inspect_options.append(value)
    elif value.startswith('skip'):
        skip_options.append(value)


_indented_new_line = '\n\t'
_double_indented_new_line = '\n\t\t'


inspect_regex_options = [
    'inspect:bake:map=',

    'inspect:func:pre=',
    'inspect:func:post=',

    'inspect:script:pre=',
    'inspect:script:post=',
]

skip_regex_options = [
    'skip:bake:map='
]


regex_options = tuple(inspect_regex_options + skip_regex_options)


OPTIONS = {
    'help': "print this help [does not convert]",
    'from': "show the source file in the explorer [does not convert]",
    'to': "show the result file in the explorer [does not convert]",

    'open:from': "open the source file [does not convert]",
    'open:to': "open the result file [does not convert]",

    'validate': "validate commands and do nothing else [does not convert]",

    'diff': "show diff based on the written json file, uses VSCode [does not convert] ['code' must be in the PATH environment variable]",
    'makeupdated': "rewrite the json file as up to date, so it won't trigger the update [does not convert] [requires confirmation]",

    'show': "show the result in the explorer [after the execution]",
    'open': "open the result [after the execution]",
    'check': "do not execute if up to date",

    'profile': "profile the execution and open with snakeviz [snakeviz must be installed]",
    'debug': "connect to the process with debugpy [debugpy must be installed]",

    'inspect:<OPTIONS> OR i:<OPTIONS>':
        "open a copy of the blend file being processed at a stage"
        "\n\t\t"
        f"{_double_indented_new_line.join(inspect_options + [x + '<REGEX>' for x in inspect_regex_options])}",

        'skip:<OPTIONS> OR s:<OPTIONS>': f"skip a stage, for some — unless specified by inspect:<OPTIONS>`"
        "\n\t\t"
        f"{_double_indented_new_line.join(skip_options + [x + '<REGEX>' for x in skip_regex_options])}",

    'set:<NAME>=<VALUE>':
        "Set an inspect variable named <NAME> to value <VALUE> in a way so:"
        "\n\t\t"
        "blend_inspector.get_value(<NAME>, default = 15000) == <VALUE>",
}


def print_help():
    for key, value in OPTIONS.items():
        print()
        print(f"{key}{_indented_new_line}{value}")
    print()
    print("Escape the regex options according to the environment.")
    print('\t', "E.g. in Windows CMD")
    print('\t\t', r'inspect:bake:map=normal^|color', "->", "inspect:bake:map=normal|color")
    print('\t\t', r'skip:bake:map="(?<!No).+\"Such Name\" Anyway$"', "->", 'skip:bake:map=(?<!No).+"Such Name" Anyway$')
    print()
    print("Putting # as the first character of a command will skip it.")


def error(*reason: str):
    if 'help' in ARGS:
        print()
        print_help()
    print()
    utils.print_in_color(utils.get_foreground_color_code(255,0,0), '\n'.join(str(x) for x in reason), file=sys.stderr)
    print()
    if not 'help' in ARGS:
        print("Type 'help' to show all options.")
    raise SystemExit(1)


def color_print(fg_rgb: list, bg_rgb: list, *args, **kwargs):
    utils.print_in_color(utils.get_color_code(*fg_rgb, *bg_rgb), *args, **kwargs)


non_convert_options = {
    'help',
    'from',
    'to',
    'diff',
    'makeupdated',
    'validate',
    'open:from',
    'open:to',
}


def unshorten(arg: str):
    """ Make the shortcut not short. """

    if arg.startswith('i:'):
        return 'inspect:' + arg[2:]

    if arg.startswith('s:'):
        return 'skip:' + arg[2:]

    return arg


_profile = False
_debug = False
_inspect_identifiers = set()
_inspect_values = {}


for index, arg in enumerate(ARGS):

    arg = arg.lower()

    if arg.startswith('#'):
        color_print([255, 255, 255], [127, 7, 148], f"Option skipped:", end=' ')
        print(arg)
        continue

    arg = unshorten(arg)

    if arg in non_convert_options:
        color_print([255, 255, 255], [37, 30, 207], arg)
        continue

    if arg in ('show', 'open', 'check'):
        color_print([0, 0, 0], [25, 161, 107], arg)
        continue

    if arg == 'profile':
        color_print([0, 0, 0], [223, 237, 48], arg)
        _profile = True
        continue

    if arg == 'debug':
        color_print([0, 0, 0], [230, 60, 60], arg)
        _debug = True
        continue

    if arg.startswith(regex_options):

        option, value = ARGS[index].split('=', 1)
        option = unshorten(option.lower())

        try:
            re.compile(value)
        except re.error as e:
            error(f"Invalid option: {ARGS[index]}", f"Invalid regex: {value}", e)

        formatted_option = option.lower() + '=' + value

        color_print([230, 226, 0], [8, 8, 8], f"REGEX:", end=' ')
        print(formatted_option)
        _inspect_identifiers.add(formatted_option)
        continue

    if arg in inspect_options:
        color_print([69, 222, 42], [8, 8, 8], f"Inspect:", end=' ')
        print(arg)
        _inspect_identifiers.add(arg)
        continue

    if arg in skip_options:
        color_print([230, 157, 0], [8, 8, 8], f"Skip:", end=' ')
        print(arg)
        _inspect_identifiers.add(arg)
        continue

    if arg.startswith('set:'):
        var_name, var_value = ARGS[index][len('set:'):].split('=')
        color_print([255, 255, 255], [48, 88, 138], f'{var_name} = {var_value}')
        _inspect_values[var_name] = var_value
        blend_inspector.add_value(**{var_name: var_value})
        continue

    error(f"Invalid option: {ARGS[index]}")  # Using index to print the original, possible shortened version of the command



def get_result_path(program: common.Program):

    if os.path.exists(program.result_path):
        return program.result_path
    elif os.path.exists(os.path.dirname(program.result_path)):
        return os.path.dirname(program.result_path)
    else:
        return None


def open_path(path: str, blender_executable: str):

    if path.endswith('.blend'):
        utils.open_blender_detached(blender_executable, path)
    else:
        utils.os_open(path)



def run_program(module_path, programs_getter_name, program_name):

    program: common.Program = getattr(import_module(module_path), programs_getter_name)()[program_name]

    program._profile = _profile
    program._debug = _debug

    program._inspect_identifiers.update(_inspect_identifiers)
    program._inspect_values.update(_inspect_values)


    if not non_convert_options.isdisjoint(ARGS):

        if 'help' in ARGS:
            print()
            print_help()

        if 'validate' in ARGS:
            print()
            color_print([75, 123, 227], [8, 8, 8], "The input is valid. Remove the 'validate' option to execute.")
            raise SystemExit(0)

        if 'diff' in ARGS:
            diff_utils.show_program_diff_vscode(program)

        if 'makeupdated' in ARGS:
            if input("Are you sure you want to set the json as up to date? (y/n)").lower() == 'y':
                program.write_report()


        if 'from' in ARGS:
            utils.print_in_color(utils.get_foreground_color_code(0,191,255), program.blend_path)
            utils.os_show(program.blend_path)

        if 'to' in ARGS:
            path = get_result_path(program)
            if path:
                utils.print_in_color(utils.get_foreground_color_code(0,191,255), program.result_path)
                utils.os_show(path)
            else:
                utils.print_in_color(utils.get_color_code(255,0,0, 0,0,0), "The result does not exist yet.")


        if 'open:from' in ARGS:
            utils.print_in_color(utils.get_foreground_color_code(0,191,255), program.blend_path)
            open_path(program.blend_path, program.blender_executable)

        if 'open:to' in ARGS:
            path = get_result_path(program)
            if path:
                utils.print_in_color(utils.get_foreground_color_code(0,191,255), program.result_path)
                open_path(path, program.blender_executable)
            else:
                utils.print_in_color(utils.get_color_code(255,0,0, 0,0,0), "The result does not exist yet.")


        raise SystemExit(0)


    if 'check' in ARGS:
        if program.are_instructions_changed:
            program.execute()
    else:
        program.execute()


    if 'show' in ARGS:
        utils.os_show(program.result_path)

    if 'open' in ARGS:
        open_path(program.result_path, program.blender_executable)


for module_path, programs_getter_name, name in json.loads(programs)['programs']:

    try:
        run_program(module_path, programs_getter_name, name)
    except Exception:

        error_type, error_value, error_tb = sys.exc_info()

        print()
        utils.print_in_color(utils.get_color_code(255,255,255,128,0,0,), f"{module_path}::{programs_getter_name}::{name}", file=sys.stderr)
        utils.print_in_color(utils.get_color_code(180,0,0,0,0,0,), ''.join(traceback.format_tb(error_tb)), file=sys.stderr)
        utils.print_in_color(utils.get_color_code(255,255,255,128,0,0,), ''.join(traceback.format_exception_only(error_type, error_value)), file=sys.stderr)
        print()

    except SystemExit as e:

        if e.code == 'BLENDER':
            continue
        else:
            raise e
