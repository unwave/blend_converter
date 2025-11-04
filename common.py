from __future__ import annotations

import json
import os
import typing
import uuid
import tempfile
from datetime import datetime
import configparser
import textwrap
import inspect
import time


from . import utils
from . import tool_settings


ROOT_DIR = os.path.dirname(__file__)

def get_script_path(name: str):
    return os.path.join(ROOT_DIR, 'script', f'{name}.py')

def get_blender_script_path(name: str):
    return os.path.join(ROOT_DIR, 'blender', 'scripts', f'{name}.py')


T = typing.TypeVar('T')

if typing.TYPE_CHECKING:
    from typing_extensions import ParamSpec
    P = ParamSpec('P')
else:
    class Fake_ParamSpec:
        args: None
        kwargs: None
    P = Fake_ParamSpec()


class Stat_Dict(typing.TypedDict if typing.TYPE_CHECKING else dict):
    mtime: float
    size: int


def get_file_stat(path: str) -> Stat_Dict:
    stat = os.stat(path)
    return {
        'mtime': stat.st_mtime,
        'size': stat.st_size
    }


class File:

    def __init__(self, *path: str):
        self.path = os.path.join(*path)


    def __fspath__(self):
        return self.path


    def _to_dict(self):
        stat = os.stat(self.path)

        return dict(
            _type = type(self).__name__,
            path = self.path,
            mtime = stat.st_mtime,
            size = stat.st_size,
        )


    @property
    def name(self):
        return os.path.basename(self.path)


    @property
    def stem(self):
        return os.path.splitext(os.path.basename(self.path))[0]


    @property
    def ext(self):
        return os.path.splitext(self.path)[1]


    @property
    def dirname(self):
        return os.path.dirname(self.path)


    @property
    def dir_basename(self):
        return os.path.basename(os.path.dirname(self.path))


    @property
    def dir_based_name(self):
        return self.dir_basename + self.ext



class Instruction:


    def __init__(self, executor, func: typing.Callable, *args, **kwargs):

        self.func = func

        self.executor = executor
        self.filepath: str = os.path.realpath(func.__code__.co_filename)
        self.name: str = func.__name__
        self.args: typing.List[typing.Any] = list(args)
        self.kwargs: typing.Dict[str, typing.Any] = kwargs
        self.sha256: str = utils.get_function_sha256(func)
        self.code: str = textwrap.dedent(inspect.getsource(func))


    def _to_dict(self):
        return dict(
            _type = type(self).__name__,
            executor = self.executor,
            filepath = self.filepath,
            name = self.name,
            args = self.args,
            kwargs = self.kwargs,
            sha256 = self.sha256,
            code = self.code,
        )

    def __repr__(self):
        return json.dumps(self._to_dict(), indent = 4, ensure_ascii = False, default = lambda x: x._to_dict())


class Program:


    def __init__(self, *, blend_path: str, result_path: str, blender_executable: str, report_path: typing.Optional[str] = None):


        # this is for the GUI
        self.blend_path = os.fspath(blend_path)
        self.result_path = os.fspath(result_path)
        self.blender_executable = os.fspath(blender_executable)

        if report_path is None:
            self.report_path = self.result_path + '.json'
        else:
            self.report_path = os.fspath(report_path)


        self.instructions: typing.List[Instruction] = []

        self._debug = False

        self._profile = False

        self._inspect_identifiers = set()
        """ A set of inspect identifiers to pass to tools. """

        self._inspect_values = dict()
        """ Values to set when inspecting and get like `blend_inspector.get_value('my_value', 100)` """

        self.return_values = {}

        self.return_values_file: typing.Optional[str] = None
        """ A file where the return values will be written. """

        self.config: typing.Optional[Config_Base] = None
        """ Pre execution configuration. """

        self.tags: typing.Set[str] = set()
        """ Use for differentiation. See `set_max_workers_by_program_tag`. """



    def read_report(self):
        """ Read the report json file with the instructions of a previous execution. """

        if not os.path.exists(self.report_path):
            return {}

        with open(self.report_path, encoding='utf-8') as json_file:
            try:
                return json.load(json_file)
            except json.decoder.JSONDecodeError:
                return {}


    def write_report(self):
        """ Write the current instructions with additional information. """

        report = self.read_report()

        report['instructions'] = self.instructions

        now = datetime.now()

        if not report.get('ctime'):
            report['ctime'] = report['mtime'] = now.timestamp()
            report['ctime_str'] = report['mtime_str'] = now.astimezone().isoformat(' ', 'seconds')
        else:
            report['mtime'] = now.timestamp()
            report['mtime_str'] = now.astimezone().isoformat(' ', 'seconds')

        report['write_count'] = report.get('write_count', 0) + 1
        report['write_times'] = report.get('write_times', []) + [now.timestamp()]
        report['write_times_str'] = report.get('write_times_str', []) + [now.astimezone().isoformat(' ', 'seconds')]

        os.makedirs(os.path.dirname(self.report_path), exist_ok = True)

        temp_report_name = self.report_path + uuid.uuid1().hex

        with open(temp_report_name, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=4, ensure_ascii=False, default=lambda x: x._to_dict())

        os.replace(temp_report_name, self.report_path)


    def __fspath__(self):
        return self.blend_path


    def __str__(self):
        return self.blend_path


    @property
    def are_instructions_changed(self):
        return self.get_next_report_diff() != self.get_prev_report_diff()


    def get_next_report_diff(self):
        return dict(
            instructions = json.loads(json.dumps(self.instructions, default = lambda x: x._to_dict())),
        )


    def get_prev_report_diff(self):
        return dict(
            instructions = self.read_report().get('instructions', []),
        )


    def replace_return_values(self, value: typing.Union[list, dict]):
        """ Provide result of one executor to the next. """

        value = value.copy()

        if isinstance(value, list):
            for index, sub_value in enumerate(value):
                if sub_value in self.instructions:
                    return_value = self.return_values.get(self.instructions.index(sub_value))
                    if return_value:
                        value[index] = return_value
                elif type(sub_value) in (list, dict):
                    value[index] = self.replace_return_values(value)
                elif isinstance(sub_value, tool_settings.Settings):
                    value[index] = self.replace_return_values(sub_value._to_dict())
        elif isinstance(value, dict):
            for key, sub_value in value.items():
                if sub_value in self.instructions:
                    return_value = self.return_values.get(self.instructions.index(sub_value))
                    if return_value:
                        value[key] = return_value
                elif type(sub_value) is (list, dict):
                    value[key] = self.replace_return_values(value)
                elif isinstance(sub_value, tool_settings.Settings):
                    value[key] = self.replace_return_values(sub_value._to_dict())
        else:
            raise Exception(f"Unexpected args type: {value}")

        return value


    def substitute_filepaths(self, value: typing.Union[list, dict]):

        if isinstance(value, list):
            for index, sub_value in enumerate(value):
                if type(sub_value) is File:
                    value[index] = sub_value.path
                elif type(sub_value) in (list, dict):
                    self.substitute_filepaths(sub_value)
        elif isinstance(value, dict):
            for key, sub_value in value.items():
                if type(sub_value) is File:
                    value[key] = sub_value.path
                elif type(sub_value) in (list, dict):
                    self.substitute_filepaths(sub_value)
        else:
            raise Exception(f"Unexpected value {repr(value)} or type {type(value)}")


    def execute(self):

        start_time = time.perf_counter()
        print("EXECUTION START:", time.strftime('%H:%M:%S %Y-%m-%d'), flush=True)

        with tempfile.TemporaryDirectory() as temp_dir:

            self.return_values_file = os.path.join(temp_dir, uuid.uuid1().hex)

            instructions_sorted = utils.list_by_key(self.instructions, lambda instruction: instruction.executor)

            for executor, instructions in instructions_sorted.items():

                substituted_instructions = []
                for instruction in instructions:

                    args = self.replace_return_values(instruction.args)
                    kwargs = self.replace_return_values(instruction.kwargs)
                    self.substitute_filepaths(args)
                    self.substitute_filepaths(kwargs)

                    substituted_instructions.append(Instruction(instruction.executor, instruction.func, *args, **kwargs))

                executor.run(
                    instructions = substituted_instructions,
                    return_values_file = self.return_values_file,
                    inspect_identifiers = self._inspect_identifiers,
                    inspect_values = self._inspect_values,
                    debug = self._debug,
                    profile = self._profile,
                )

                with open(self.return_values_file, encoding='utf-8') as f:
                    self.return_values = {int(key): value for key, value in json.load(f).items()}

        print("EXECUTION END:", time.strftime('%H:%M:%S %Y-%m-%d'), flush=True)
        print(f"TIME: {round(time.perf_counter() - start_time, 2)} SECONDS", flush=True)

        self.write_report()


    def run(self, executor, func: 'typing.Callable[P, T]', *args: P.args, **kwargs: P.kwargs) -> T:
        """ `args` and `kwargs` must be JSON serializable. """

        instruction = Instruction(executor, func, *args, **kwargs)
        self.instructions.append(instruction)

        return instruction


class Config_Base:


    def __init__(self, path: os.PathLike):

        self._path = path

        self._config = configparser.ConfigParser()
        self._config.read(self._path)

        for section_name, section_class in type(self).__annotations__.items():

            if section_name.startswith('_'):
                continue

            section_instance = section_class()
            setattr(self, section_name, section_instance)

            for option, fallback in section_class.__dict__.items():

                if option.startswith('_'):
                    continue

                if type(fallback) is int:
                    value = self._config.getint(section_name, option, fallback=fallback)
                elif type(fallback) is float:
                    value = self._config.getfloat(section_name, option, fallback=fallback)
                elif type(fallback) is bool:
                    value = self._config.getboolean(section_name, option, fallback=fallback)
                else:
                    value = self._config.get(section_name, option, fallback=fallback)

                setattr(section_instance, option, value)


    def iter_options(self):

        section: str
        option: str

        for section, section_instance in self.__dict__.items():

            if section.startswith('_'):
                continue

            for option, value in section_instance.__dict__.items():

                if option.startswith('_'):
                    continue

                yield section, option, value


    def set_option(self, section: str, option: str, value):
        setattr(getattr(self, section), option, value)


    def get_default(self, section: str, option: str):
        return type(getattr(self, section)).__dict__[option]


    def get_enum(self, section: str, option: str):
        option_type = type(getattr(self, section)).__annotations__[option]
        if typing.get_origin(option_type) is typing.Literal:
            return list(typing.get_args(option_type))
        else:
            return None


    def save(self):

        config = configparser.ConfigParser()

        for section, option, value in self.iter_options():

            if self.get_default(section, option) == value:
                continue

            if not config.has_section(section):
                config.add_section(section)

            config.set(section, option, str(value))

        with open(self._path, 'w', encoding='utf-8') as f:
            config.write(f)


    def to_ui_data(self):

        data = {}

        for section, option, value in self.iter_options():

            key = section + ' @ ' + option

            if isinstance(value, (int, float, bool)):
                data[key] = value
            else:
                enum = self.get_enum(section, option)
                if enum is None:
                    data[key] = value
                else:
                    data[key] = (enum, value)

        return data


    def from_ui_data(self, data: dict[str]):

        for key, value in data.items():

            section, option = key.split(' @ ', maxsplit= 1)

            self.set_option(section, option, value)
