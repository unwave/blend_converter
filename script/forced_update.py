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


model: common.Generic_Exporter = getattr(module, '__blends__')[object_name]

model._inspect = 'inspect' in other_args
model._profile = 'profile' in other_args
model._debug = 'debug' in other_args
model._inspect_all = 'inspect_all' in other_args

if 'help' in other_args or '-h' in other_args or '--help' in other_args or '/h' in other_args:
    print()
    print(f"inspect: save and open the final blend file")
    print(f"profile: profile the execution and open snakeviz")
    print(f"debug: connect to the process with debugpy")
    print(f"inspect_all: inspect_blend after each script")
    print()
    input('Press Enter to exit...')
else:
    model.update(forced='check' not in other_args)
