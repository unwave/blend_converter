""" This script will import and run the functions inside an Unreal Engine instance. """

import importlib
import importlib.util
import os
import sys
import typing


BC_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))


def import_module_from_file(file_path: str, module_name: typing.Optional[str] = None):

    if not os.path.isabs(file_path):
        raise Exception(f"Path to file must be absolute: {file_path}")

    if module_name is None:
        module_name = os.path.splitext(os.path.basename(file_path))[0]

    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None:
        raise Exception(f"Spec not found: {module_name}, {file_path}")

    module = importlib.util.module_from_spec(spec)

    sys.modules[module_name] = module
    spec.loader.exec_module(module)  # type: ignore[reportOptionalMemberAccess]

    return module


def append_sys_path(path: str):
    if not path in sys.path:
        sys.path.append(path)


def run(data: dict):

    # reimporting blend_converter as the module will be cached by python
    for module in list(sys.modules):
        if module.startswith('blend_converter'):
            del sys.modules[module]


    import_module_from_file(os.path.join(BC_ROOT, '__init__.py'), 'blend_converter')


    for script in data['instructions']:

        append_sys_path(os.path.dirname(script['filepath']))
        module = import_module_from_file(script['filepath'])
        getattr(module, script['name'])(*script['args'], **script['kwargs'])
