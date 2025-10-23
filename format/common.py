from __future__ import annotations

import json
import os
import typing
import itertools
import uuid
import tempfile
from datetime import datetime
import shutil
import configparser
import textwrap
import inspect


from .. import utils
from .. import tool_settings

T = typing.TypeVar('T')

if typing.TYPE_CHECKING:
    from typing_extensions import ParamSpec
    P = ParamSpec('P')
else:
    class Fake_ParamSpec:
        args: None
        kwargs: None
    P = Fake_ParamSpec()

PROCESS_SCRIPTS_PY = utils.get_script_path('process_scripts')


class Stat_Dict(typing.TypedDict if typing.TYPE_CHECKING else dict):
    mtime: float
    size: int


def get_file_stat(path: str) -> Stat_Dict:
    stat = os.stat(path)
    return {
        'mtime': stat.st_mtime,
        'size': stat.st_size
    }


class Function_Script_Dict(typing.TypedDict if typing.TYPE_CHECKING else dict):
    type: str
    filepath: str
    name: str
    args: typing.List[typing.Any]
    kwargs: typing.Dict[str, typing.Any]
    sha256: str
    code: str


class Blend_Base:
    """ Base `.blend` handler """


    _file_extension = 'none'

    blender_executable = shutil.which(utils.get_blender_executable())
    """ Blender's binary path to run commands with."""

    blender_stdout = None
    """ Blender's console output. """


    def __init__(self, source_path: str, result_dir: str, is_dir = False, is_import = False):
        """
        Parameters
        ----------
        source_path: A file path or a directory of the source file. By default the `.blend` file path is expected.

        result_dir: directory where the result files will be placed.
        """

        self._source_path = os.path.abspath(source_path)
        """ A file path or a directory of the source file. """

        self.result_dir = os.path.abspath(result_dir)
        """ Directory where files will be placed."""

        self._is_dir = is_dir
        """ If `True` the actual blend file is the last modified one. """

        self._is_import = is_import
        """ `True` if the blend file is generated from importing other formats. """

        self._stem = None
        """
        A name for the generate files.

        By default the same as the `.blend`'s base name without the file extension.
        """

        self.config: typing.Optional[Config_Base] = None
        """
        Pre model configuration.
        """


    @classmethod
    def from_dir(cls, source_path: str, result_dir: str):
        """
        Use the last modified `.blend` file from the directory as the source file.

        The result file name is the name for the directory.
        """
        return cls(source_path, result_dir, is_dir = True, is_import = False)


    @classmethod
    def from_import(cls, source_path: str, result_dir: str):
        raise NotImplementedError('Not yet implemented.')
        return cls(source_path, result_dir, is_dir = False, is_import = True)


    @classmethod
    def from_dir_import(cls, source_path: str, result_dir: str):
        raise NotImplementedError('Not yet implemented.')
        return cls(source_path, result_dir, is_dir = True, is_import = True)


    @property
    def blend_path(self):
        if self._is_dir:
            try:
                return utils.get_last_blend(self._source_path)
            except (FileNotFoundError, ValueError):
                return os.path.join(self._source_path, 'DOES_NOT_EXISTS.blend')
        else:
            return self._source_path


    @property
    def stem(self):
        if self._stem is None:
            if self._is_dir:
                return os.path.basename(self._source_path)
            else:
                return os.path.splitext(os.path.basename(self._source_path))[0]
        else:
            return self._stem


    @stem.setter
    def stem(self, value: str):
        self._stem = value


    @property
    def json_path(self):
        return os.path.join(self.result_dir, self.stem + f".{self._file_extension}" + '.json')


    def get_json(self):
        """ Read the json file with the information about how the converted file was created. """

        if not os.path.exists(self.json_path):
            return {}

        with open(self.json_path, encoding='utf-8') as json_file:
            try:
                return json.load(json_file)
            except json.decoder.JSONDecodeError:
                return {}


    def _write_json(self, **kwargs):

        info = self.get_json()

        info.update(kwargs)

        info['blender_executable'] = self.blender_executable
        info['blender_executable_stat'] = get_file_stat(self.blender_executable)

        info['blend_path'] = os.path.realpath(self.blend_path)
        info['blend_stat'] = get_file_stat(self.blend_path)

        now = datetime.now()

        if not info.get('ctime'):
            info['ctime'] = info['mtime'] = now.timestamp()
            info['ctime_str'] = info['mtime_str'] = now.astimezone().isoformat(' ', 'seconds')
        else:
            info['mtime'] = now.timestamp()
            info['mtime_str'] = now.astimezone().isoformat(' ', 'seconds')

        info['write_count'] = info.get('write_count', 0) + 1
        info['write_times'] = info.get('write_times', []) + [now.timestamp()]

        temp_json_name = self.json_path + uuid.uuid1().hex

        with open(temp_json_name, 'w', encoding='utf-8') as json_file:
            json.dump(info, json_file, indent=4, ensure_ascii=False, default=lambda x: x._to_dict())

        os.replace(temp_json_name, self.json_path)


    @property
    def result_path(self):
        return os.path.realpath(os.path.join(self.result_dir, self.stem + '.' + self._file_extension))


    def update(self, forced = False):
        raise NotImplementedError('This function updates the target file.')


    @property
    def needs_update(self):
        raise NotImplementedError('This function returns True is the target file should be updated.')


    def __fspath__(self):
        return self.result_path


class Generic_Exporter(Blend_Base):


    settings: tool_settings.Settings


    def __init__(self, source_path: str, result_dir: str, **kwargs):
        super().__init__(source_path, result_dir, **kwargs)

        self.scripts: typing.List[Function_Script_Dict] = []
        self.result = {}

        self._debug = False

        self._profile = False

        self._inspect_identifiers = set()
        """ A set of inspect identifiers to pass to Blender. """

        self.return_values_file: typing.Optional[str] = None
        """ A file where the scripts return values will be written. """


    @property
    def needs_update(self):
        return self.get_current_stats() != self.get_json_stats()


    def get_current_stats(self):

        stats = {}

        stats['result_file_exists'] = os.path.exists(self.result_path)

        stats['blend_stat'] = get_file_stat(self.blend_path)

        stats['blender_executable_stat'] = get_file_stat(self.blender_executable)

        stats['scripts'] = self._get_scripts()

        return stats


    def get_json_stats(self):

        info = self.get_json()

        stats = {}

        stats['result_file_exists'] = True

        stats['blend_stat'] = info.get('blend_stat')

        stats['blender_executable_stat'] = info.get('blender_executable_stat')

        stats['scripts'] = info.get('scripts')

        return stats


    def _get_commands(self, **builtin_kwargs):

        return [
            self.blend_path,
            '--python',
            PROCESS_SCRIPTS_PY,
            '--',
            '-json_args',
            json.dumps(dict(
                scripts = self._get_scripts(),
                builtin_kwargs = builtin_kwargs,
                return_values_file = self.return_values_file,
                inspect_identifiers = list(self._inspect_identifiers),
                debug = self._debug,
                profile = self._profile,
            ), default= lambda x: x._to_dict()),
        ]


    def update(self, forced = False):

        if not (forced or self.needs_update):
            return

        if self.blender_executable is None:
            raise Exception('Blender executable is not specified.')

        if self._file_extension == 'blend' and os.path.exists(self.result_path) and os.path.samefile(self.blend_path, self.result_path):
            raise Exception(f"Should not save the blend file in the same location: {self.blend_path}")


        os.makedirs(os.path.dirname(self.result_path), exist_ok = True)

        with tempfile.TemporaryDirectory() as temp_dir:

            self.return_values_file = os.path.join(temp_dir, uuid.uuid1().hex)
            self._run_blender()

        self._write_final_json()


    def _write_final_json(self):
        self._write_json(scripts = self._get_scripts())


    @staticmethod
    def _get_function_script(func: typing.Callable, *args, **kwargs) -> Function_Script_Dict:
        filepath = os.path.realpath(func.__code__.co_filename)
        return {
            'filepath': filepath,
            'name': func.__name__,
            'args': list(args),
            'kwargs': kwargs,
            'sha256': utils.get_function_sha256(func),
            'code': textwrap.dedent(inspect.getsource(func)),
        }


    def run(self, func: typing.Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
        """
        The function will be executed before the file export.

        `args` and `kwargs` must be JSON serializable.
        """

        script = self._get_function_script(func, *args, **kwargs)

        self.scripts.append(script)

        return script


    def get_export_script(self):
        raise NotImplementedError('This function should return an export script.')


    def _get_scripts(self):
        """ Get a list of all the scripts that will be executed. """
        return self.scripts + [self.get_export_script()]


    def _run_blender(self, **builtin_kwargs):

        __tracebackhide__ = True

        utils.run_blender(self.blender_executable, self._get_commands(**builtin_kwargs), stdout = self.blender_stdout)

        if self.return_values_file is not None:
            with open(self.return_values_file, encoding='utf-8') as f:
                    self.result = {int(key): value for key, value in json.load(f).items()}


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
