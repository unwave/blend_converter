import sys
import os

module_path = sys.argv[1]
object_name = sys.argv[2]

other_args = sys.argv[3:]

import sys
import importlib.util
import os

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


model: common.Generic_Exporter = getattr(module, '__blends__')[object_name]

model._inspect = 'inspect' in other_args
model._profile = 'profile' in other_args
model._debug = 'debug' in other_args
model._inspect_all = 'inspect_all' in other_args
model._ignore_inspect = 'ignore_inspect' in other_args
model._skip = 'skip' in other_args
model._ignore_breakpoint = 'ignore_breakpoint' in other_args


OPTIONS = dict(
    where = "show the source file in the explorer and do nothing else",
    result = "shows the result file in the explorer and do nothing else",
    show = "show the result in the explorer after the execution",
    open = "open the result after the execution",
    inspect = "save and open the final blend file",
    profile = "profile the execution and open snakeviz",
    debug = "connect to the process with debugpy",
    skip = "skip some time consuming operations, the result will be broken but the code will run",
    inspect_all = "inspect_blend after each script",
    ignore_inspect = "ignore inspect_blend calls",
    ignore_breakpoint = "ignore breakpoint calls",
    check = "do not perform a forced update",
    help = "print this help and do nothing else",
)

invalid_arg = next((arg for arg in other_args if arg not in OPTIONS), False)

if invalid_arg or 'help' in other_args:

    print()

    for key, value in OPTIONS.items():
        print(f"{key}\n\t{value}")

    if invalid_arg:
        print()
        utils.print_in_color(utils.get_foreground_color_code(255,0,0), f"Invalid argument: {invalid_arg}", file=sys.stderr)
        raise SystemExit(1)


elif 'where' in other_args:
    utils.print_in_color(utils.get_foreground_color_code(0,191,255), model.blend_path)
    utils.os_show(model.blend_path)

elif 'result' in other_args:
    if os.path.exists(model.result_path):
        utils.print_in_color(utils.get_foreground_color_code(0,191,255), model.result_path)
        utils.os_show(model.result_path)
    elif os.path.exists(model.result_dir):
        utils.print_in_color(utils.get_foreground_color_code(0,191,255), model.result_dir)
        utils.os_show(model.result_dir)
    else:
        utils.print_in_color(utils.get_color_code(255,0,0, 0,0,0), 'The result folder does not exist yet.')

else:
    model.update(forced='check' not in other_args)

    if 'show' in other_args:
        utils.os_show(model.result_path)

    if 'open' in other_args:
        utils.open_blender_detached(model.blender_executable, model.result_path)
