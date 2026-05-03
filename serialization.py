import os
import sys
import typing
import importlib
import importlib.util
import importlib.machinery


def get_top_package_file(func: typing.Callable):

    top_package_name = func.__module__.split('.')[0]
    top_package = sys.modules[top_package_name]

    func_file = func.__code__.co_filename
    if not os.path.exists(func_file):
        raise Exception(f"The file of the function must exist on disk: {func_file}")

    func_file = os.path.realpath(func_file)

    if not hasattr(top_package, '__path__'):
        return func_file

    if top_package.__file__:
        return top_package.__file__

    for path in top_package.__path__:

        path = os.path.realpath(path)

        try:
            common_path = os.path.commonpath([path, func_file])
        except ValueError:
            continue

        if common_path == path:
            return path


    raise Exception(f"Fail to find the source package of the function: {repr(func)}")


def import_module_from_file(file_path: str, module_name: str):

    if module_name in sys.modules:
        return sys.modules[module_name]

    file_path = os.path.realpath(file_path)

    if os.path.isdir(file_path):
        spec = importlib.machinery.ModuleSpec(module_name, None, is_package = True)
        spec.submodule_search_locations = [file_path]
    else:
        spec = importlib.util.spec_from_file_location(module_name, file_path)

    if spec is None:
        raise Exception(f"Spec not found: {module_name}, {file_path}")

    module = importlib.util.module_from_spec(spec)

    sys.modules[module_name] = module

    if spec.loader:
        spec.loader.exec_module(module)

    return module


class Function:


    name: str
    module_name: str
    package_file: str


    def get(self) -> typing.Callable:

        if self.module_name == '__main__':
            module = import_module_from_file(self.package_file, '__main__' + str(hash(self.package_file)))
        else:
            top_module = self.module_name.split('.')[0]
            import_module_from_file(self.package_file, top_module)
            module = importlib.import_module(self.module_name)

        return getattr(module, self.name)


    def _to_dict(self):
        return dict(
            name = self.name,
            module_name = self.module_name,
            package_file = self.package_file,
        )


    @classmethod
    def from_func(cls, func: typing.Callable):

        instance = cls()

        instance.name: str = func.__name__
        instance.module_name = func.__module__
        instance.package_file = get_top_package_file(func)

        return instance


    @classmethod
    def from_dict(cls, data: dict):

        instance = cls()

        instance.name = data['name']
        instance.module_name = data['module_name']
        instance.package_file = data['package_file']

        return instance


    def __repr__(self):
        return f"{self.package_file}::{self.module_name}::{self.name}"



BC_ROOT = os.path.dirname(os.path.realpath(__file__))
CANONICAL_NAME = 'blend_converter'

def bootstrap():
    import_module_from_file(os.path.join(BC_ROOT, '__init__.py'), CANONICAL_NAME)
