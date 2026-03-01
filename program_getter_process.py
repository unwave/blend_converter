import typing
import os
import sys
import importlib
import importlib.util


if typing.TYPE_CHECKING:
    from . import common


def import_module_from_file(file_path: str, module_name: typing.Optional[str] = None):

    file_path = os.path.realpath(file_path)

    if module_name is None:
        if os.path.basename(file_path) == '__init__.py':
            module_name = os.path.basename(os.path.dirname(file_path))
        else:
            module_name = os.path.splitext(os.path.basename(file_path))[0]

    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None:
        raise Exception(f"Spec not found: {module_name}, {file_path}")

    module = importlib.util.module_from_spec(spec)

    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    return module


def get_program(*, module_file_path: str, program_getter_name: str, keyword_arguments: dict) -> 'common.Program':

    module = import_module_from_file(module_file_path)

    program_getter = getattr(module, program_getter_name)

    return program_getter(**keyword_arguments)
