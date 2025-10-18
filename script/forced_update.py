import sys
import os

module_path = sys.argv[1]
object_name = sys.argv[2]

ARGS = sys.argv[3:]

import sys
import importlib.util
import os
import typing

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


from blend_converter.format import common

from blend_converter import utils

from blend_converter import blend_inspector

model: common.Generic_Exporter = getattr(module, '__blends__')[object_name]


inspect_options: typing.List[str] = []
skip_options: typing.List[str] = []

for key, value in blend_inspector.COMMON.__dict__.items():
    if key.startswith('_'):
        continue
    elif value.startswith('inspect'):
        inspect_options.append(value)
    elif value.startswith('skip'):
        skip_options.append(value)

_new_line = '\n\t'

inspect_options.append('inspect:bake:map=<REGEX>')
skip_options.append('skip:bake:map=<REGEX>')

regex_options = tuple([option.replace('<REGEX>', '') for option in inspect_options + skip_options if option.endswith('<REGEX>')])

OPTIONS = {
    'help': "print this help and do not convert",
    'from': "show the source file in the explorer and do not convert",
    'to': "show the result file in the explorer and do not convert",

    'show': "show the result in the explorer after the execution",
    'open': "open the result after the execution",
    'check': "do not perform a forced update",

    'profile': "profile the execution and open snakeviz",
    'debug': "connect to the process with debugpy",

    'inspect:<OPTIONS>': f"open a copy the blend file being processed at a stage{_new_line}{_new_line.join(inspect_options)}",
    'skip:<OPTIONS>': f"skip things{_new_line}{_new_line.join(skip_options)}",
}


def print_help():
    for key, value in OPTIONS.items():
        print(f"{key}{_new_line}{value}")


def error(reason: str):
    print()
    print_help()
    print()
    utils.print_in_color(utils.get_foreground_color_code(255,0,0), reason, file=sys.stderr)
    raise SystemExit(1)


for arg in ARGS:

    if arg in ('help', 'from', 'to', 'show', 'open', 'check'):
        continue

    if arg == 'profile':
        model._profile = True
        continue

    if arg == 'debug':
        model._debug = True
        continue

    if arg in inspect_options:
        model._inspect_identifiers.add(arg)
        continue

    if arg in skip_options:
        model._inspect_identifiers.add(arg)
        continue

    if arg.startswith(regex_options):
        model._inspect_identifiers.add(arg)
        continue

    error(f"Invalid argument: {arg}")



if not {'help', 'from', 'to'}.isdisjoint(ARGS):

    if 'help' in ARGS:
        print_help()

    if 'from' in ARGS:
        utils.print_in_color(utils.get_foreground_color_code(0,191,255), model.blend_path)
        utils.os_show(model.blend_path)

    if 'to' in ARGS:
        if os.path.exists(model.result_path):
            utils.print_in_color(utils.get_foreground_color_code(0,191,255), model.result_path)
            utils.os_show(model.result_path)
        elif os.path.exists(model.result_dir):
            utils.print_in_color(utils.get_foreground_color_code(0,191,255), model.result_dir)
            utils.os_show(model.result_dir)
        else:
            utils.print_in_color(utils.get_color_code(255,0,0, 0,0,0), 'The result folder does not exist yet.')

    raise SystemExit(0)


model.update(forced='check' not in ARGS)

if 'show' in ARGS:
    utils.os_show(model.result_path)

if 'open' in ARGS:
    utils.open_blender_detached(model.blender_executable, model.result_path)
