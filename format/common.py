from __future__ import annotations

import json
import os
import typing
import itertools
import uuid
import tempfile
from datetime import datetime
import shutil

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
    stat: typing.Any


class Module_Script_Dict(typing.TypedDict if typing.TYPE_CHECKING else dict):
    type: str
    filepath: str
    kwargs: typing.Dict[str, typing.Any]
    stat: Stat_Dict



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

        self.scripts: typing.List[typing.Union[Function_Script_Dict, Module_Script_Dict]] = []
        self.result = {}

        self._profile = False
        self._inspect = False
        self._debug = False
        self._inspect_all = False

        self.return_values_file: typing.Optional[str] = None
        """ A file where the scripts return values will be written. """


    @property
    def needs_update(self):

        if not os.path.exists(self.result_path):
            return True

        info = self.get_json()

        if info.get('blend_stat') != get_file_stat(self.blend_path):
            return True

        if info.get('blender_executable_stat') != get_file_stat(self.blender_executable):
            return True

        if info.get('scripts') != self._get_scripts():
            return True

        return False


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
                profile = self._profile,
                inspect = self._inspect,
                debug = self._debug,
                inspect_all = self._inspect_all,
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

        self._write_json(scripts = self._get_scripts())


    @staticmethod
    def _get_function_script(func: typing.Callable, *args, **kwargs) -> Function_Script_Dict:
        filepath = os.path.realpath(func.__code__.co_filename)
        return {
            'type': 'function',
            'filepath': filepath,
            'name': func.__name__,
            'args': list(args),
            'kwargs': kwargs,
            'stat': dict(sha256=utils.get_function_sha256(func)),
        }


    @staticmethod
    def _get_module_script(filepath: str, **kwargs) -> Module_Script_Dict:
        filepath = os.path.realpath(filepath)
        return {
            'type': 'module',
            'filepath': filepath,
            'kwargs': kwargs,
            'stat': get_file_stat(filepath),
        }


    def run(self, func: typing.Callable[P], *args: P.args, **kwargs: P.kwargs):
        """
        The function will be executed before the file export.

        `args` and `kwargs` must be JSON serializable.
        """

        script = self._get_function_script(func, *args, **kwargs)

        self.scripts.append(script)

        return script


    def run_file(self, filepath: str, **kwargs):
        """
        The module will be executed before the file export.

        `kwargs` will be available as `__KWARGS__` built-in variable

        `kwargs` must be JSON serializable.
        """

        script = self._get_module_script(filepath, **kwargs)

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
