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
import multiprocessing


from . import utils
from . import tool_settings
from . import settings_base


SENTINEL = object()

K_INSTRUCTION_IDENTIFIER = '_bc_instruction_identifier'


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
    def dir(self):
        return os.path.dirname(self.path)


    @property
    def dir_name(self):
        return os.path.basename(os.path.dirname(self.path))


class Instruction:


    def __init__(self, identifier: str, executor, func: typing.Callable, *args, **kwargs):

        self.func = func
        self.identifier = identifier
        self.executor = executor
        self.filepath: str = os.path.realpath(func.__code__.co_filename)
        self.module_name = func.__module__
        self.name: str = func.__name__
        self.args: typing.List[typing.Any] = list(args)
        self.kwargs: typing.Dict[str, typing.Any] = kwargs
        self.sha256: str = utils.get_function_sha256(func)
        self.code: str = utils.get_source(func)


    def _to_dict(self):
        return dict(
            _type = type(self).__name__,
            identifier = self.identifier,
            executor = self.executor,
            filepath = self.filepath,
            module_name = self.module_name,
            name = self.name,
            args = self.args,
            kwargs = self.kwargs,
            sha256 = self.sha256,
            code = self.code,
        )

    def __repr__(self):
        return json.dumps(self._to_dict(), indent = 4, ensure_ascii = False, default = lambda x: x._to_dict())


    def iter_arguments(self):

        signature = inspect.signature(self.func)

        arguments = {name: value for name, value in zip(signature.parameters.keys(), self.args)}
        arguments.update(self.kwargs)

        instruction_path = [self.identifier]

        for argument_name, argument in arguments.items():

            argument_path = instruction_path + [argument_name]

            if isinstance(argument, settings_base.Settings):
                for key in argument.__class__.__dict__:

                    if key.startswith('_'):
                        continue

                    spec = argument._get_attribute_spec(key)
                    value = getattr(argument, key, spec.default)

                    yield argument_path + [key], value, spec

            elif isinstance(argument, (bool, int, float, str)):
                spec = settings_base.Attribute_Spec(name = argument_name, type = type(argument), default = argument)
                yield argument_path, argument, spec


class Program:


    def __init__(self, *,
                blend_path: str,
                result_path: str,
                blender_executable: str,
                report_path: typing.Optional[str] = None,
                config: typing.Optional[Config_Base] = None,
                settings_path: str = None,
                tags: typing.Optional[typing.Set[str]] = None,
            ):


        self.blend_path = os.fspath(blend_path)
        """ Used for the GUI """

        self.result_path = os.fspath(result_path)
        """ Used for the GUI """

        self.blender_executable = os.fspath(blender_executable)
        """ Used for the GUI """

        if report_path is None:
            self.report_path = self.result_path + '.json'
        else:
            self.report_path = os.fspath(report_path)

        self.config: typing.Optional[Config_Base] = config
        """ Pre execution configuration. """

        self.settings_path = settings_path
        """ Post initialization per instructions argument override. """

        self._instructions_config = configparser.ConfigParser()
        if self.settings_path:
            self._instructions_config.read(settings_path)

        self.tags: typing.Set[str] = tags if tags else set()
        """ Use for differentiation. See `set_max_workers_by_program_tag`. """


        self.instructions: typing.List[Instruction] = []

        self._debug = False

        self._profile = False

        self._inspect_identifiers = set()
        """ A set of inspect identifiers to pass to tools. """

        self._inspect_values = dict()
        """ Values to set when inspecting and get like `blend_inspector.get_value('my_value', 100)` """

        self.return_values: typing.Dict[str, typing.Any] = {}
        """ This will be populated after the execution. """

        self.return_values_file: typing.Optional[str] = None
        """ A file where the return values will be written. """

        self._instruction_identifiers: typing.set[str] = set()


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

        report['instructions'] = self.get_next_report_diff()['instructions']

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

        instructions = json.loads(json.dumps(self.instructions, default = lambda x: x._to_dict()))

        for instruction, dictionary in zip(self.instructions, instructions):
            apply_instruction_settings(instruction, self._instructions_config, dictionary['args'], dictionary['kwargs'])

        return dict(
            instructions = instructions,
        )


    def get_prev_report_diff(self):
        return dict(
            instructions = self.read_report().get('instructions', []),
        )


    def get_return_value(self, value):

        if type(value) is list:
            return self.replace_return_values(value)

        elif type(value) is dict:

            identifier = value.get(K_INSTRUCTION_IDENTIFIER)
            if identifier is not None:
                return self.return_values.get(identifier, value)

            return self.replace_return_values(value)

        elif isinstance(value, settings_base.Settings):
            return self.replace_return_values(value._to_dict())

        else:
            return value


    def replace_return_values(self, value: typing.Union[list, dict]):
        """ Provide result of one executor to the next. """


        if isinstance(value, list):
            return [self.get_return_value(v) for v in value]

        elif isinstance(value, dict):
            return {k: self.get_return_value(v) for k, v in value.items()}

        else:
            raise Exception(f"Unexpected args type: {value}")


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


    def execute(self,
                *,
                entry_command_queue = None,
                updater_response_queue = None,
                execution_context: Execution_Context = None,
            ):

        start_time = time.perf_counter()
        print("EXECUTION START:", time.strftime('%H:%M:%S %Y-%m-%d'), flush=True)

        if execution_context is None:
            execution_context = utils.Dummy()

        with tempfile.TemporaryDirectory() as temp_dir:

            self.return_values_file = os.path.join(temp_dir, uuid.uuid1().hex)

            instructions_sorted = utils.list_by_key(self.instructions, lambda instruction: instruction.executor)

            for executor, instructions in instructions_sorted.items():

                with execution_context.lock:

                    if not execution_context.is_process_running.value:

                        execution_context.are_executors_stopped.value = True
                        execution_context.lock.notify_all()

                        execution_context.lock.wait_for(lambda: execution_context.is_process_running.value)

                        execution_context.are_executors_stopped.value = False
                        execution_context.lock.notify_all()


                executor.entry_command_queue = entry_command_queue
                executor.updater_response_queue = updater_response_queue
                executor.execution_context = execution_context

                substituted_instructions = []
                for instruction in instructions:

                    args = self.replace_return_values(instruction.args)
                    kwargs = self.replace_return_values(instruction.kwargs)
                    self.substitute_filepaths(args)
                    self.substitute_filepaths(kwargs)

                    apply_instruction_settings(instruction, self._instructions_config, args, kwargs)

                    substituted_instructions.append(Instruction(instruction.identifier, instruction.executor, instruction.func, *args, **kwargs))

                executor.run(
                    instructions = substituted_instructions,
                    return_values_file = self.return_values_file,
                    inspect_identifiers = self._inspect_identifiers,
                    inspect_values = self._inspect_values,
                    debug = self._debug,
                    profile = self._profile,
                )

                if not os.path.exists(self.return_values_file):
                    continue

                with open(self.return_values_file, encoding='utf-8') as f:
                    self.return_values.update(json.load(f).items())

        print("EXECUTION END:", time.strftime('%H:%M:%S %Y-%m-%d'), flush=True)
        print(f"TIME: {round(time.perf_counter() - start_time, 2)} SECONDS", flush=True)

        self.write_report()


    def run(self, executor, func: 'typing.Callable[P, T]', *args: P.args, **kwargs: P.kwargs) -> T:
        """ `args` and `kwargs` must be JSON serializable. """


        identifier = func.__name__
        index = 2

        while identifier in self._instruction_identifiers:
            identifier = func.__name__ + f'_{index}'
            index += 1

        self._instruction_identifiers.add(identifier)


        instruction = Instruction(identifier, executor, func, *args, **kwargs)
        self.instructions.append(instruction)


        return {K_INSTRUCTION_IDENTIFIER: instruction.identifier}



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


class Program_Definition:

    def __init__(
                self,
                file_name: str,
                program_getter_name: str,
                arguments_getter_name: str,
                args: list = None,
                kwargs: dict = None,
            ):

        self.file_name = file_name
        self.program_getter_name = program_getter_name
        self.arguments_getter_name = arguments_getter_name

        self.args = [] if args is None else args
        self.kwargs = {} if kwargs is None else kwargs


    def __repr__(self):
        return str(self.__dict__)


class Execution_Context:

    def __init__(self):

        self.lock = multiprocessing.Condition()

        self.no_pending_children = multiprocessing.Value('b', False, lock = self.lock)
        self.is_process_running = multiprocessing.Value('b', False, lock = self.lock)
        self.are_executors_stopped = multiprocessing.Value('b', False, lock = self.lock)


def get_settings_class(name: str):
    return getattr(tool_settings, name, Unknown_Settings)


class Unknown_Settings(settings_base.Settings):

    allow_missing_settings = True


def get_new_return_value(value, return_values: dict, instructions: list):

    if type(value) is list:
        return replace_return_value(value, return_values, instructions)

    elif type(value) is dict:

        identifier = value.get(K_INSTRUCTION_IDENTIFIER)
        if identifier is not None:
            return return_values[identifier]

        settings_name = value.get(settings_base.K_CLASS_NAME)
        if settings_name:
            return replace_return_value(get_settings_class(settings_name)._from_dict(value), return_values, instructions)
        else:
            return replace_return_value(value, return_values, instructions)

    else:
        return value


def replace_return_value(value, return_values: dict, instructions: list):
    """ Substitute previous function return values. """

    if isinstance(value, list):
        return [get_new_return_value(sub_value, return_values, instructions) for sub_value in value]

    elif isinstance(value, dict):
        return {key: get_new_return_value(sub_value, return_values, instructions) for key, sub_value in value.items()}

    elif isinstance(value, settings_base.Settings):
        return type(value)._from_dict(
            {key: get_new_return_value(getattr(value, key), return_values, instructions) for key in value}
        )

    else:
        raise Exception(f"Unexpected args type: {value}")


def _replace_dictionary_argument_recursive(dictionary: typing.Dict, path: typing.List[str], value: typing.Any):

    current_path = path.copy()
    current_dictionary = dictionary

    while len(current_path) > 1:
        current_dictionary = current_dictionary[current_path[0]]
        current_path = current_path[1:]

    current_dictionary[current_path[0]] = value


def _replace_argument(arguments: typing.Union[list, dict], key: typing.Union[int, str], path: typing.List[str], value: typing.Any):

    if not path:
        arguments[key] = value
    else:
        _replace_dictionary_argument_recursive(arguments[key], path, value)


def apply_instruction_settings(instruction: Instruction, config: configparser.ConfigParser, args: list, kwargs: dict):
    """ Replace a dictionary based arguments. """

    positional_arguments = instruction.func.__code__.co_varnames[:len(instruction.args)]
    key_to_index = {key: index for index, key in enumerate(positional_arguments)}


    for path, current_value, spec in instruction.iter_arguments():

        section = path[0]
        option = '.'.join(path[1:])

        if not config.has_option(section, option):
            continue

        if spec.type is bool:
            value = config.getboolean(section, option)
        elif spec.type is int:
            value = config.getint(section, option)
        elif spec.type is float:
            value = config.getfloat(section, option)
        else:
            value = config.get(section, option)

        if value == current_value:
            continue

        positional_argument_index = key_to_index.get(path[1])

        if positional_argument_index is None:
            _replace_argument(kwargs, path[1], path[2:], value)
        else:
            _replace_argument(args, positional_argument_index, path[2:], value)
