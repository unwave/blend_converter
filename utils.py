import functools
import inspect
import os
import platform
import subprocess
import sys
import time
import typing
import textwrap

from . import bl_script

DIR = os.path.dirname(__file__)

def get_files(path: os.PathLike , recursively = True, get_folders = False):
    files: typing.List[os.DirEntry] = []

    for file in os.scandir(path):
        if file.is_file():
            files.append(file)
        else:
            if get_folders:
                files.append(file)
            if recursively:
                files.extend(get_files(file, recursively, get_folders))
                
    return files

def get_expr(func: typing.Callable):
    return textwrap.dedent(inspect.getsource(func)) + f"{func.__name__}()"


def get_blender_binary():
    try:
        return _get_binpath(locate_blenderdir(), blenderbin = 'blender')[0]
    except:

        import shutil
        if shutil.which('blender'):
            return 'blender'

        print('Blender is not found! Need to be specified manually')
        return None

BLENDER_BINARY = get_blender_binary()

# https://github.com/Moguri/blend2bam/blob/master/blend2bam/blend2gltf
def _get_binpath(blenderdir, blenderbin):
    if blenderdir.startswith('flatpak run'):
        binpath = blenderdir.split()
    elif sys.platform == "darwin":
        binpath = os.path.join(blenderdir, 'Contents', 'MacOS', blenderbin)
    else:
        binpath = os.path.join(blenderdir, blenderbin)
        if sys.platform == "win32" and not binpath.endswith('.exe'):
            binpath += ".exe"

    if not isinstance(binpath, list):
        binpath = [binpath]
    return binpath


# https://github.com/Moguri/blend2bam/blob/master/blend2bam/blend2gltf
@functools.lru_cache
def locate_blenderdir():
    system = platform.system()
    if system == 'Windows':
        # pylint: disable=import-error
        import winreg

        # See if the blend extension is registered
        try:
            regpath = r'SOFTWARE\Classes\blendfile\shell\open\command'
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, regpath) as regkey:
                command, _ = winreg.QueryValueEx(regkey, '')
            cmddir = os.path.dirname(command.replace('"', '').replace(' %1', ''))
            return cmddir
        except OSError:
            pass

        # See if there is a Steam version installed
        try:
            regpath = r'SOFTWARE\Valve\Steam'
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, regpath) as regkey:
                steamloc, _ = winreg.QueryValueEx(regkey, 'InstallPath')
            steampath = os.path.join(steamloc, 'steamapps', 'common', 'Blender')
            if os.path.exists(steampath):
                return steampath
        except OSError:
            pass

    elif system == 'Darwin':
        if os.path.isfile('/Applications/Blender.app/Contents/MacOS/Blender'):
            return '/Applications/Blender.app'

    # Check for flatpak Blender
    try:
        flatpakloc = 'flatpak run --filesystem=/tmp org.blender.Blender'
        subprocess.check_call(flatpakloc.split() + ['--version'], stdout=None)
        return flatpakloc
    except subprocess.CalledProcessError:
        pass

    # Couldn't find anything better
    return ''



def run_blender(arguments: list, argv: list = None, stdout = None, blender_binary = 'blender'):
    """
        Parameters
        ----------

        arguments: Blender's command line arguments
        
        argv: Blender's `--` arguments accessed via `sys.argv`

        stdout: `subprocess` stdout argument

        blender_binary: Blender's binary
    """

    args = [
        blender_binary,
        '-b',
        '--python-use-system-env',
        '--factory-startup',
        '--python-exit-code',
        '1',

        '--python-expr',
        get_expr(bl_script._set_builtins),

        *arguments,
    ]

    args.append('--')
    args.extend(('-caller_script_dir', DIR))
        
    if argv:
        args.extend(argv)

    return subprocess.run(args, stdout = stdout, check = True, text = True)


T = typing.TypeVar('T')
T2 = typing.TypeVar('T2')

def list_by_key(items: typing.Collection[T], key_func: typing.Callable[[T], T2]) -> typing.Dict[T2, typing.List[T]]:
    dict = {} # type: typing.Dict[T2, typing.List[T]]
    for item in items:
        key = key_func(item)
        try:
            dict[key].append(item)
        except KeyError:
            dict[key] = [item]
    return dict


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

    if type(files) is str:
        files = [files]

    if sys.platform != 'win32':
        for directory in deduplicate([os.path.dirname(file) for file in files]):
            os_open(operator, directory)
        return

    files = [file.lower() for file in files]
    directories = list_by_key(files, os.path.dirname)

    import ctypes
    import ctypes.wintypes

    prototype = ctypes.WINFUNCTYPE(ctypes.POINTER(ctypes.c_int), ctypes.wintypes.LPCWSTR)
    paramflags = (1, "pszPath"),
    ILCreateFromPathW = prototype(("ILCreateFromPathW", ctypes.windll.shell32), paramflags)

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

    if len(strings) == 1:
        return  list(strings)[0]

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

    if not mega_set:
        return ""

    return max(mega_set, key=len)


def split_path(path) -> typing.Tuple[str]:
    return (os.path.dirname(path), * os.path.splitext(os.path.basename(path)))

def conform_file_name_letter_case(target_path: str, paths: typing.List[str]):

    target_path = split_path(target_path)
    paths = [split_path(os.path.realpath(path)) for path in paths]

    target_prefix_name = target_path[1]
    prefix_name = get_longest_substring([path[1] for path in paths], from_beginning = True)
    if prefix_name == target_prefix_name:
        return

    for path in paths:

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
