""" Pure Python utilities. """


from __future__ import annotations

import functools
import inspect
import os
import hashlib
import re
import shutil
import subprocess
import sys
import textwrap
import time
import typing
import tempfile
import uuid
import importlib
import importlib.util
import datetime
import io
import queue
import threading
import shelve
import traceback
import json
import collections
import ctypes


T = typing.TypeVar('T')
T2 = typing.TypeVar('T2')


def get_time_stamp():
    return time.strftime('%Y%m%d_%H%M%S')


def deduplicate(list_to_deduplicate: typing.List[T]) -> typing.List[T]:
        return list(dict.fromkeys(list_to_deduplicate))


def get_files(path, filter_func: typing.Optional[typing.Callable[[os.DirEntry], bool]] = None, recursively = True) -> typing.List[os.DirEntry]:

    list = []

    for item in os.scandir(path):

        if filter_func and not filter_func(item):
            continue

        list.append(item)

        if recursively and item.is_dir():
            list.extend(get_files(item.path, filter_func, recursively))

    return list


def is_blend_file(file: os.DirEntry):
    return file.is_file() and file.name.endswith('.blend') and not file.name.startswith('_')


def get_last_blend(dir) -> str:
    """ Get a last modified `.blend` file that does not start with underscore. """
    files = get_files(dir, recursively=False, filter_func=is_blend_file)
    return max(files, key=lambda x: (os.path.getmtime(x), os.path.getctime(x), x)).path


def get_expr(func: typing.Callable):
    return textwrap.dedent(inspect.getsource(func)) + f"{func.__name__}()"

def get_python_expr(func, *args, **kwargs):
    """ Does not work with `shell=True`. """

    import inspect
    import json
    import textwrap

    expr = [textwrap.dedent(inspect.getsource(func))]

    args_json = repr(json.dumps(args))
    kwargs_json = repr(json.dumps(kwargs))

    if args and kwargs:
        expr.append('import json')
        expr.append(f'args = json.loads({args_json})')
        expr.append(f'kwargs = json.loads({kwargs_json})')
        expr.append(f'{func.__name__}(*args, **kwargs)')
    elif args:
        expr.append('import json')
        expr.append(f'args = json.loads({args_json})')
        expr.append(f'{func.__name__}(*args)')
    elif kwargs:
        expr.append('import json')
        expr.append(f'kwargs = json.loads({kwargs_json})')
        expr.append(f'{func.__name__}(**kwargs)')
    else:
        expr.append(f'{func.__name__}()')

    return '\n'.join(expr)


@functools.lru_cache(None)
def get_blender_executable_windows():

    import winreg

    def get_value(key: int, sub_key: str, value_name: str):
        try:
            with winreg.OpenKey(key, sub_key) as key_handle:
                value, type_id = winreg.QueryValueEx(key_handle, value_name)
            return value
        except Exception:
            return None

    command = get_value(winreg.HKEY_CLASSES_ROOT, r'blendfile\shell\open\command', '')
    if command:
        path = command.split('"')[1] # "C:\blender\blender-3.1.2-windows-x64\blender-launcher.exe" "%1"
        path = os.path.join(os.path.dirname(path), 'blender.exe')
        if os.path.exists(path):
            return path

    def get_stream_blender(stream_path: str, re_library_path = re.compile(r'"path"\W+"(.+)"')):

        # C:\Program Files (x86)\Steam\steamapps\libraryfolders.vdf
        libraryfolders_vdf_path = os.path.join(stream_path, 'steamapps', 'libraryfolders.vdf')
        with open(libraryfolders_vdf_path) as file:
            libraryfolders_vdf = file.read()

        for folder in re_library_path.findall(libraryfolders_vdf):
            path = os.path.join(folder.replace('\\\\', '\\'), 'steamapps', 'common', 'Blender', 'blender.exe')
            if os.path.exists(path):
                return path

        return None

    steam_path = get_value(winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Wow6432Node\Valve\Steam', 'InstallPath')
    if steam_path:
        path = get_stream_blender(steam_path)
        if path:
            return path

    steam_path = get_value(winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Valve\Steam', 'InstallPath')
    if steam_path:
        path = get_stream_blender(steam_path)
        if path:
            return path

    return None


@functools.lru_cache(None)
def get_blender_executable():

    if shutil.which('blender'):
        return 'blender'

    if sys.platform == 'win32':
        path = get_blender_executable_windows()
        if path:
            return path

    elif sys.platform == "darwin":
        # https://docs.blender.org/manual/en/latest/advanced/command_line/launch/macos.html
        path = '/Applications/Blender.app/Contents/MacOS/Blender'
        if os.path.exists(path):
            return path

    else:
        # https://github.com/Moguri/blend2bam/blob/master/blend2bam/blenderutils.py
        try:
            command = ['flatpak', 'run', '--filesystem=/tmp', 'org.blender.Blender']
            subprocess.check_call(command + ['--version'], stdout=None)
            return ' '.join(command)
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass

    print('Blender is not found! The blender_executable path needs to be specified manually.')
    return None



def run_blender(executable: typing.Union[str, typing.List[str]], arguments: typing.List[str], argv: typing.Optional[typing.List[str]] = None, stdout = None, check = True):
    """
        Parameters
        ----------
        executable: Blender's executable path

        arguments: Blender's command line arguments

        argv: Blender's `--` arguments accessed via `sys.argv`

        stdout: `subprocess` stdout argument
    """

    __tracebackhide__ = True

    if not isinstance(executable, list):
        executable = [executable]

    env = os.environ.copy()
    env['PYTHONPATH'] = ''
    env['PYTHONUNBUFFERED'] = '1'
    env['PYTHONWARNINGS'] = 'error'

    command = [
        *executable,

        '-b',
        '-noaudio',
        '--python-use-system-env',
        '--factory-startup',
        '--python-exit-code',
        '1',

        *arguments,
    ]

    if argv:
        command.extend(argv)

    try:
        return subprocess.run(command, stdout = stdout, check = check, text = True, env = env)
    except subprocess.CalledProcessError as e:
        print_in_color(CONSOLE_COLOR.RED, "Blender has exited with an error.", file=sys.stderr)
        raise SystemExit(1)


def list_by_key(items: typing.Collection[T], key: typing.Callable[[T], T2]) -> typing.Dict[T2, typing.List[T]]:
    result = collections.defaultdict(list)
    for item in items:
        result[key(item)].append(item)
    return dict(result)


def os_open(path):
    platform = sys.platform

    if platform == 'win32':
        os.startfile(path)

    elif platform == 'darwin':
        subprocess.Popen(['open', path])
    else:
        try:
            subprocess.Popen(['xdg-open', path])
        except OSError:
            import traceback
            traceback.print_exc()

def os_show(files: typing.Union[str, typing.Iterable[str]]):

    if isinstance(files, (str, os.PathLike)):
        files = [files]

    files = [os.fspath(file) for file in files if os.path.exists(file)]

    if sys.platform != 'win32':
        for directory in deduplicate([os.path.dirname(file) for file in files]):
            os_open(operator, directory)
        return

    files = [file.lower() for file in files]
    directories = list_by_key(files, os.path.dirname)

    import ctypes
    import ctypes.wintypes

    prototype = ctypes.WINFUNCTYPE(ctypes.POINTER(ctypes.c_int), ctypes.wintypes.LPCWSTR)
    param_flags = (1, "pszPath"),
    ILCreateFromPathW = prototype(("ILCreateFromPathW", ctypes.windll.shell32), param_flags)

    ctypes.windll.ole32.CoInitialize(None)

    for directory, files in directories.items():

        directory_pidl = ILCreateFromPathW(directory)

        file_pidls = (ctypes.POINTER(ctypes.c_int) * len(files))()
        for index, file in enumerate(files):
            file_pidls[index] = ILCreateFromPathW(file)

        ctypes.windll.shell32.SHOpenFolderAndSelectItems(directory_pidl, len(file_pidls), file_pidls, 0)

        ctypes.windll.shell32.ILFree(directory_pidl)
        for file_pidl in file_pidls:
            ctypes.windll.shell32.ILFree(file_pidl)

    ctypes.windll.ole32.CoUninitialize()


def get_longest_substring(strings: typing.Iterable[str], from_beginning = False):

    sets = []
    if from_beginning:
        for string in strings:
            string_set = []
            string_len = len(string)
            for i in range(string_len):
                string_set.append(string[:i + 1])
            sets.append(set(string_set))
    else:
        for string in strings:
            string_set = []
            string_len = len(string)
            for i in range(string_len):
                for j in range(i + 1, string_len + 1):
                    string_set.append(string[i:j])
            sets.append(set(string_set))

    mega_set = set().union(*sets)

    for string_set in sets:
        mega_set.intersection_update(string_set)

    return max(sorted(mega_set), key=len, default = '')


def split_path(path) -> typing.Tuple[str, str, str]:
    return (os.path.dirname(path), *( (os.path.basename(path), "") if os.path.isdir(path) else os.path.splitext(os.path.basename(path)) ) )

def conform_file_name_letter_case(target_path: str, paths: typing.List[str]):

    target_path_splitted = split_path(target_path)
    paths_splitted = [split_path(os.path.realpath(path)) for path in paths]

    target_prefix_name = target_path_splitted[1]
    prefix_name = get_longest_substring([path[1] for path in paths_splitted], from_beginning = True)
    if prefix_name == target_prefix_name:
        return

    for path in paths_splitted:

        old_path = os.path.join(path[0], path[1] + path[2])
        new_path = os.path.join(path[0], path[1].replace(prefix_name, target_prefix_name, 1) + path[2])

        os.rename(old_path, new_path)


def get_common_attrs(source: object, target: object):

    target_attrs = [attr for attr in dir(target) if not attr.startswith('_')]
    source_attrs = [attr for attr in dir(source) if not attr.startswith('_')]

    result = {}
    for attr in source_attrs:
        if attr in target_attrs:
            result[attr] = getattr(source, attr)

    return result


class File_Change_Tracker:


    def __init__(self, dir: str, filter_func: typing.Callable[[os.DirEntry], bool]):
        self.dir = os.path.realpath(dir)
        self.filter_func = filter_func

    def __enter__(self):
        self.start_time = time.time()
        # self.pre_files = {path.path: os.path.getmtime(path) for path in filter(self.filter_func, utils.get_files(self.dir, recursively = False))}
        return self

    def __exit__(self, type, value, traceback):
        self.post_files = {path.path: os.path.getmtime(path) for path in filter(self.filter_func, get_files(self.dir, recursively = False))}
        self.end_time = time.time()

    def get_changed_files(self):

        files: typing.List[str] = []

        for path, mtime in self.post_files.items():

            if mtime < self.start_time:
                continue

            if mtime > self.end_time:
                continue

            files.append(path)

        return files


def get_time_str_from(stamp: float):
    return datetime.datetime.fromtimestamp(stamp).strftime('%Y.%m.%d %H:%M:%S')


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


class Blend_File_Path(os.PathLike):

    def __init__(self, path: typing.Union[str, os.PathLike]):
        self.path = os.path.realpath(path)
        self.name = os.path.basename(self.path)
        stem, ext = os.path.splitext(self.name)
        self.stem = stem
        self.ext = ext

    def is_file(self):
        return os.path.isfile(self.path)

    def is_dir(self):
        return os.path.isdir(self.path)

    def __fspath__(self):
        return self.path


def iter_blend_file(dir: str):

    for file in os.scandir(dir):

        if not file.is_file():
            continue

        if not file.name.endswith('.blend'):
            continue



        yield file.path



class CONSOLE_COLOR:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'

    YELLOW = '\033[33m'

    MAGENTA = '\033[35m'

    RED = '\033[93m'
    RED = '\033[91m'
    BG_RED = '\033[41m'

    RESET = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

    BG_GREEN = '\033[42m'


def get_color_code_simple(base):
    return f'\033[{base}m'

def get_foreground_color_code(r, g, b):
    return f'\033[38;2;{r};{g};{b}m'

def get_background_color_code(r, g, b):
    return f'\033[48;2;{r};{g};{b}m'

def get_color_code(r, g, b, _r, _g, _b):
    return f'\033[38;2;{r};{g};{b};48;2;{_r};{_g};{_b}m'


def dummy_print_in_color(color_code, *args, **kwargs):
    print(*args, **kwargs)

if hasattr(sys.stdout, 'isatty') and sys.stdout.isatty():

    if sys.platform == 'win32':
        os.system('')

    def print_in_color(color_code, *args, **kwargs):
        print(f"{color_code}{' '.join(str(arg) for arg in args)}{CONSOLE_COLOR.RESET}", **kwargs)

else:
    print_in_color = dummy_print_in_color


def get_terminal_width(fallback = 80):

    try:
        value = int(os.environ['COLUMNS'])
    except Exception:
        try:
            value = os.get_terminal_size(sys.__stdout__.fileno()).columns
        except Exception:
            value = fallback

    return value


def print_separator(*values: object, char = '=', sep: str = ' '):

    width = get_terminal_width() - 1

    text = sep.join((str(value) for value in values))

    if text:
        text = ' ' + text + ' '

    text_len = len(text)
    rest_of_width = width - text_len
    half_rest_of_width = int(rest_of_width / 2)

    pre = round(half_rest_of_width/len(char))
    post = round((width - (half_rest_of_width + text_len))/len(char))

    print(char * pre, text, char * post, sep='', flush=True)


def get_same_drive_tmp_dir(path: typing.Union[str, os.PathLike]):
    tmp_dir = os.path.join(os.sep, os.path.splitdrive(os.path.realpath(path))[0] + os.sep, 'tmp')
    os.makedirs(tmp_dir, exist_ok=True)
    return tmp_dir


@functools.lru_cache(None)
def get_function_sha256(func: typing.Callable):
    code = '\n'.join(filter(None, (line.rstrip() for line in textwrap.dedent(inspect.getsource(func)).splitlines())))
    return hashlib.sha256(code.encode()).hexdigest()


def get_temp_dir(filename: os.PathLike):
    temp_dir = os.path.join(tempfile.gettempdir(), 'blend_converter', f"{os.path.basename(filename)}_{uuid.uuid1().hex}_{get_time_stamp()}")
    os.makedirs(temp_dir, exist_ok=True)
    return temp_dir


WINDOWS_RESERVED_NAMES = {
'CON', 'PRN', 'AUX', 'NUL', 'COM0', 'COM1', 'COM2', 'COM3', 'COM4', 'COM5',
'COM6', 'COM7', 'COM8', 'COM9', 'COM¹', 'COM²', 'COM³', 'LPT0', 'LPT1', 'LPT2',
'LPT3', 'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9', 'LPT¹', 'LPT²', 'LPT³',
}

def is_windows_reserved(name: str):
    return name.upper().split('.', 1)[0] in WINDOWS_RESERVED_NAMES

def ensure_valid_basename(string: str, limit = 63):
    """ Returns a valid file basename. """

    # no special or non-printable characters
    string = re.sub(r'[\\/:*?"<>|\0-\31]', "_", string)
    # no trailing whitespaces
    string = string.strip()
    # no ending with dot or space
    string = string.rstrip('. ')
    # 63 is bpy.types.ID.name limit and there is the 260 path length limit
    string = string[:limit]

    if is_windows_reserved(string):
        string = f"{string[:3]}_{string[3:limit-1]}"

    if not string:
        string = get_time_stamp()

    return string


def reload_library():
    for name in list(sys.modules):
        if name.startswith(__package__ + '.') and not 'addon' in name:
            importlib.reload(sys.modules[name])


class Capture_Output:

    _std_output_name: str


    def __init__(self, is_dummy = False, use_set_other = True):
        self.lines = queue.Queue()
        self.is_dummy = is_dummy
        self.use_set_other = use_set_other


    def __enter__(self):

        if self.is_dummy:
            return self

        self.flush()


        std_output: io.TextIOWrapper = getattr(sys, self._std_output_name)

        self.prev_std_output = std_output

        self.file_descriptor = std_output.fileno()

        self.file_descriptor_copy = os.dup(self.file_descriptor)

        self.pipe_read_fileno, self.pipe_write_fileno = os.pipe()

        self.pipe_reading = threading.Thread(target=self.read_pipe)
        self.read_pipe_textwrapper = os.fdopen(self.pipe_read_fileno, encoding='utf-8')
        self.pipe_reading.start()

        os.dup2(self.pipe_write_fileno, self.file_descriptor)
        self.write_pipe_textwrapper = os.fdopen(self.pipe_write_fileno, 'w', encoding='utf-8')
        self.write_pipe_textwrapper.reconfigure(write_through=True, line_buffering=False)

        setattr(sys, self._std_output_name, self.write_pipe_textwrapper)

        if self.use_set_other:
            self.set_other(self.prev_std_output, self.write_pipe_textwrapper)

        return self


    def __exit__(self, exc_type, exc_value, _traceback):

        if self.is_dummy:
            return

        ctypes_flush_error, sys_flush_error = self.flush()


        os.dup2(self.file_descriptor_copy, self.file_descriptor)

        if self.do_need_recreate_windows_output():
            prev_std_output = self.copy_text_io_wrapper(self.file_descriptor, self.prev_std_output)
        else:
            prev_std_output = self.prev_std_output

        setattr(sys, self._std_output_name, prev_std_output)
        if self.use_set_other:
            self.set_other(self.write_pipe_textwrapper, prev_std_output)


        self.write_pipe_textwrapper.close()
        self.pipe_reading.join()
        self.read_pipe_textwrapper.close()

        if ctypes_flush_error is not None:
            print(ctypes_flush_error, file = sys.stderr)

        if sys_flush_error is not None:
            print(sys_flush_error, file = sys.stderr)

        os.close(self.file_descriptor_copy)


    def flush(self):
        """
        Theoretically `PYTHONUNBUFFERED=1` as an environment variable can be used instead.

        Use `flush=True` for time critical prints.
        """


        try:
            if os.name == 'nt':
                lib = ctypes.CDLL('api-ms-win-crt-stdio-l1-1-0.dll')
            else:
                lib = ctypes.CDLL('libc.so.6')  # not tested

            lib.fflush(None)

        except Exception as e:
            ctypes_flush_error = traceback.format_exc()
        else:
            ctypes_flush_error = None


        try:
            getattr(sys, self._std_output_name).flush()
        except Exception as e:
            sys_flush_error = traceback.format_exc()
        else:
            sys_flush_error = None


        return ctypes_flush_error, sys_flush_error


    def read_pipe(self):
        for line in self.read_pipe_textwrapper:
            self.lines.put_nowait(line)


    def copy_text_io_wrapper(self, fd: int, prev: io.TextIOWrapper):
        return io.TextIOWrapper(
            os.fdopen(fd, 'wb', -1 if hasattr(prev.buffer, 'raw') else 0),
            prev.encoding,
            prev.errors,
            prev.newlines,
            prev.line_buffering,
        )


    def do_need_recreate_windows_output(self):
        """
        bpo-30555: Fix WindowsConsoleIO errors in the presence of fd redirection
        https://github.com/python/cpython/pull/1927
        https://docs.python.org/3.10/whatsnew/changelog.html#id150
        """

        if os.name != 'nt':
            return False

        current_python_version = (sys.version_info.major, sys.version_info.minor)

        if current_python_version >= (3, 10):
            return False

        if current_python_version < (3, 6):
            return False

        if not hasattr(self.prev_std_output, 'buffer'):
            return False

        if hasattr(self.prev_std_output.buffer, 'raw'):
            buffer = self.prev_std_output.buffer.raw
        else:
            buffer = self.prev_std_output.buffer

        if not isinstance(buffer, io._WindowsConsoleIO):
            return False

        return True


    def set_other(self, prev_output, output):
        """ Replace other output targets. Patch this function if needed. """

        import logging

        for logger in logging.root.manager.loggerDict.values():
            for handler in getattr(logger, 'handlers', ()):
                if hasattr(handler, 'stream'):
                    if handler.stream is prev_output:
                        handler.stream = output


class Capture_Stdout(Capture_Output):
    _std_output_name = 'stdout'

class Capture_Stderr(Capture_Output):
    _std_output_name = 'stderr'


# shelve
USER_DIR = os.path.expanduser("~")
BLEND_CONVERTER_USER_DIR = os.path.join(USER_DIR, '.blend_converter')
shelve_files = {}


def shelved(shelve_filepath: str, hashable: str):

    os.makedirs(os.path.dirname(shelve_filepath), exist_ok=True)

    shelve_object = shelve_files.get(shelve_filepath)
    if shelve_object is None:
        shelve_object = shelve.open(shelve_filepath)
        shelve_files[shelve_filepath] = shelve_object

        import atexit
        atexit.register(shelve_object.close)

    def decorator(func):

        def wrapper(file_path):

            stat = os.stat(file_path)
            key = ' '.join(map(str, (stat.st_mtime, stat.st_size, hashlib.sha256(hashable.encode()).hexdigest())))

            if key not in shelve_object:
                shelve_object[key] = func(file_path)

            return shelve_object[key]

        return wrapper

    return decorator


def shelved_blend_stdout(shelve_filepath: str, post_func: typing.Optional[typing.Callable[[str]]] = None, executable: typing.Optional[str] = None):
    """
    TODO: This should be rewritten using the normal module import, not the function code copying.
    """

    if executable is None:
        executable = get_blender_executable()

    def decorator(func: typing.Callable):

        func_code = get_python_expr(func)

        # strip decorators
        for def_index, line in enumerate(func_code.splitlines()):
            if line.startswith('def '):
                break

        func_code = "\n".join(func_code.splitlines()[def_index:])

        @shelved(shelve_filepath, func_code)
        def wrapper(blend_path: str):

            result = run_blender(executable, [blend_path, '--python-expr', func_code], stdout=subprocess.PIPE, check = False)

            if result.returncode != 0:
                print(result.stdout, file=sys.stderr)
                return

            if post_func is None:
                return result.stdout
            else:
                return post_func(result.stdout)

        return wrapper

    return decorator


def open_blender_detached(executable: str, *command: str):

    _command = [executable]

    def set_windows_console():

        try:
            import ctypes

            SW_HIDE = 0
            console = ctypes.windll.kernel32.GetConsoleWindow()
            ctypes.windll.user32.ShowWindow(console, SW_HIDE)

            menu = ctypes.windll.user32.GetSystemMenu(console, 0)
            ctypes.windll.user32.DeleteMenu(menu, 0xF060, 0)
        except Exception:
            traceback.print_exc()

    _command.extend(command)

    if os.name == 'nt':
        # startupinfo = subprocess.STARTUPINFO(dwFlags=subprocess.STARTF_USESHOWWINDOW, wShowWindow=subprocess.SW_HIDE)
        # kwargs = dict(creationflags = subprocess.CREATE_NEW_CONSOLE, startupinfo = startupinfo)
        kwargs = dict(creationflags = subprocess.CREATE_NEW_CONSOLE)
        _command.extend(('--python-expr', get_python_expr(set_windows_console)))
    else:
        kwargs = dict(start_new_session = True)


    subprocess.Popen(_command, **kwargs)


def shelved_blend_json_magic(shelve_filepath, executable: typing.Optional[str] = None):
    """ Print `json.dumps({'__BC_MAGIC__': blends})` to get the result. """

    MAGIC = '__BC_MAGIC__'

    def get_result_data(stdout: str):

        for line in stdout.splitlines():
            if MAGIC in line:
                return json.loads(line)[MAGIC]

        print(stdout)

        raise Exception("The magic dict was not found. Use: print(json.dumps({'__BC_MAGIC__': blends}))")

    def decorator(func: typing.Callable) -> dict:
        return shelved_blend_stdout(shelve_filepath=shelve_filepath,  post_func=get_result_data, executable=executable)(func)

    return decorator


def get_command_from_list(command: typing.List[str]):
    if os.name == 'nt':
        return subprocess.list2cmdline(command)
    else:
        import shlex
        return ' '.join(shlex.quote(arg) for arg in command)


def get_function_decorator(func: typing.Callable, exit = False, **kwargs):

    def decorator(target_func):

        def wrapper(*target_args, **target_kwargs):

            func(**kwargs)

            if exit:
                raise SystemError('Not doing anything.')

            return target_func(*target_args, **target_kwargs)

        return wrapper

    return decorator


if os.name == 'nt':
    def get_desktop():
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as key:
            return winreg.QueryValueEx(key, "Desktop")[0]
else:
    def get_desktop():
        return os.path.expanduser("~/Desktop")


class Appendable_Dict(dict):

    def append(self, value):

        if isinstance(value, os.PathLike):
            name = os.path.splitext(os.path.basename(value))[0]
        else:
            name = value.__class__.__name__

        name = ensure_valid_basename(name)

        init_name = name
        index = 2
        while name in self:
            name = init_name + f'_{index}'
            index += 1

        self[name] = value

        return name

    def extend(self, values: typing.Iterable):
        for value in values:
            self.append(value)


def ensure_unique_path(path: typing.Union[str, os.PathLike]):

    path: str = os.fspath(path)

    if not os.path.exists(path):
        return path

    dir = os.path.dirname(path)

    if os.path.isdir(path):
        stem, ext = os.path.basename(path), ""
    else:
        stem, ext = os.path.splitext(os.path.basename(path))

    number = 2

    new_path = os.path.join(dir, stem + f"_{number}" + ext)
    while os.path.exists(new_path):
        number += 1
        new_path = os.path.join(dir, stem + f"_{number}" + ext)

    return new_path


class Fallback(Exception):
    pass


def attempt(func: typing.Callable[[typing.Any], T], *args, **kwargs) -> T:
    try:
        return func(*args, **kwargs)
    except Exception:
        traceback.print_exc()

class Console_Shown:
    """ Not on Windows does nothing. """


    def __init__(self, always_on_top = False):
        self.do_always_on_top = always_on_top
        self.was_shown = 0

        self.enabled = True

        if os.name != 'nt':
            self.enabled = False
            return

        import ctypes

        self.kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        self.user32 = ctypes.WinDLL('user32', use_last_error=True)

        if self.get_is_using_terminal():
            self.enabled = False
            return


    @staticmethod
    def get_is_using_terminal():
        return not {'PROMPT', 'TERM_PROGRAM', 'TERM', 'TERMINAL_EMULATOR'}.isdisjoint(os.environ)


    def get_last_error(self):
        import ctypes
        return ctypes.WinError(ctypes.get_last_error())


    def show(self, value: bool = True):

        if os.name != 'nt':
            return

        console = self.kernel32.GetConsoleWindow()

        SW_HIDE = 0
        SW_SHOWNORMAL = 1
        SW_SHOW = 5

        SW_RESTORE = 6
        SW_SHOWNOACTIVATE = 4
        SW_SHOWDEFAULT = 10

        was_shown: int = self.user32.ShowWindow(console, SW_SHOWNOACTIVATE if value else SW_HIDE)

        self.user32.BringWindowToTop(console)

        # disable exit button
        if not was_shown and not self.get_is_using_terminal():
            menu = self.user32.GetSystemMenu(console, 0)
            self.user32.DeleteMenu(menu, 0xF060, 0)

        return was_shown

    def always_on_top(self, value: bool = True):

        if os.name != 'nt':
            return

        HWND_TOPMOST = -1
        HWND_NOTOPMOST = -2

        SWP_NOSIZE = 0x0001
        SWP_NOMOVE = 0x0002
        SWP_NOACTIVATE = 0x0010
        SWP_NOZORDER = 0x0004
        SWP_NOOWNERZORDER = 0x0200

        flags = SWP_NOSIZE | SWP_NOMOVE

        from ctypes import wintypes

        console = self.kernel32.GetConsoleWindow()

        self.user32.SetWindowPos(console, wintypes.HWND(HWND_TOPMOST if value else HWND_NOTOPMOST), 0, 0, 0, 0, flags)

    def __enter__(self):

        if not self.enabled:
            return self

        self.was_shown = attempt(self.show, True)

        if self.do_always_on_top:
            attempt(self.always_on_top, True)

        return self

    def __exit__(self, type, value, traceback):

        if not self.enabled:
            return

        if self.do_always_on_top:
            attempt(self.always_on_top, False)

        if not self.was_shown and not value:
            attempt(self.show, False)

        import ctypes
        error_code = ctypes.get_last_error()
        if error_code:
            print(ctypes.WinError(error_code), file=sys.stderr)
