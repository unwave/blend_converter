from __future__ import annotations

import json
import os
import tempfile
import typing
from datetime import datetime

try:
    from panda3d.core import Filename
except ModuleNotFoundError:
    print('panda3d is not available, panda3d style paths are not available')


from . import bl_script
from . import utils

DIR = os.path.dirname(__file__)
CALLER_MODULE_DIR = os.path.dirname(os.path.dirname(__file__))

BLENDER_BINARY = utils.get_blender_binary()

class Settings:

    @property
    def _dict(self):
        data = {key: value for key, value in self.__class__.__dict__.items() if not key.startswith('_')}
        data.update(self.__dict__)
        return data


class Script:

    use_dill = False
    """ 
    Pickle an object using `uqfoundation/dill`.

    #### The current Python's version should match the Blender's one.

    #### All the used modules should be available to import inside the Blender instance. You can use `add_site_package` to auto install them.

    #### Default: `False`
    """

    dill_protocol = None 
    """
    `protocol` is the pickler protocol, as defined for Python `pickle`.

    #### Default: `None`
    """

    dill_byref = None 
    """
    If `byref` = `True`, then dill behaves a lot more like pickle as certain
    objects (like modules) are pickled by reference as opposed to attempting
    to pickle the object itself.

    #### Default: `None`
    """

    dill_fmode = None 
    """
    `fmode`: (:const:`HANDLE_FMODE`, :const:`CONTENTS_FMODE`,
    or :const:`FILE_FMODE`) indicates how file handles will be pickled.
    For example, when pickling a data file handle for transfer to a remote
    compute service, `FILE_FMODE` will include the file contents in the
    pickle and cursor position so that a remote method can operate
    transparently on an object with an open file handle.

    #### Default: `None`
    """

    dill_recurse = True 
    """
    If `recurse`= `True`, then objects referred to in the global dictionary
    are recursively traced and pickled, instead of the default behavior
    of attempting to store the entire global dictionary. This is needed for
    functions defined via `exec()`.

    #### Default: `True`
    """


    dill_kwds = {} 
    """
    Default values for keyword arguments can be set in :mod:`dill.settings`.

    #### Default: `{}`
    """

    def __init__(self, func: typing.Callable, args, kwargs):
        self._func = func
        self._args = args
        self._kwargs = kwargs

        self._site_packages: typing.List[typing.Tuple[str, str]] = []
        """ python modules to install via pip, a list of tuples (<import name>, <pip name>)  """

        self._modules_from_file: typing.List[typing.Tuple[str, str]] = []

    def add_site_package(self, import_name: str, pip_name: str = None):
        """ Specify `pip_name` if it is different from `import_name`. """
        name = (pip_name if pip_name else import_name, import_name)
        if not name in self._site_packages:
            self._site_packages.append(name)
    
    @staticmethod
    def _get_expr(func: typing.Callable, *args, **kwargs):
        import inspect
        import textwrap
        return '\n'.join((
            textwrap.dedent(inspect.getsource(func)),
            'import json',
            f'args = json.loads(r"""{json.dumps(args, ensure_ascii = False, indent = 4)}""")',
            f'kwargs = json.loads(r"""{json.dumps(kwargs, ensure_ascii = False, indent = 4)}""")',
            f'{func.__name__}(*args, **kwargs)'
        ))

    def _encode_dill(self, object):
        import base64

        import dill

        # dumps results are not reproducible, roundtrip equality checking fails with closures · Issue #481 · uqfoundation/dill
        # https://github.com/uqfoundation/dill/issues/481
        unsorted_batch_setitems = dill.Pickler._batch_setitems

        def _batch_setitems(self, items):
            unsorted_batch_setitems(self, sorted(items))

        dill.Pickler._batch_setitems = _batch_setitems


        dump = dill.dumps(object, protocol = self.dill_protocol, byref = self.dill_byref, fmode = self.dill_fmode, recurse = self.dill_recurse, **self.dill_kwds)
        return base64.b64encode(dump).decode('utf-8')

    def _get_expr_dill(self, func: typing.Callable, *args, **kwargs):

        def run_func(func, args, kwargs):

            import base64
            import dill

            def decode(object):
                return dill.loads(base64.b64decode(object))

            decode(func)( *decode(args), **decode(kwargs) )

        return self._get_expr(run_func, self._encode_dill(func), self._encode_dill(args), self._encode_dill(kwargs))

    def execute(self):
        self._func(*self._args, **self._kwargs)

    def add_module_from_file(self, file_path, module_name: str = None):

        if not module_name:
            module_name = os.path.splitext(os.path.basename(file_path))[0]

        self._modules_from_file.append((file_path, module_name))

    @property
    def _script(self):
        script = []

        if self.use_dill:
            self.add_site_package('dill')

        if self._site_packages:
            script.append(self._get_expr(bl_script._ensure_site_packages, self._site_packages))

        if self._modules_from_file:
            for file_path, module_name in self._modules_from_file:
                script.append(self._get_expr(bl_script._import_module_from_file, file_path, module_name))

        if self.use_dill:
            script.append(self._get_expr_dill(self._func, *self._args, **self._kwargs))
        else:
            script.append(self._get_expr(self._func, *self._args, **self._kwargs))

        return '\n'.join(script)

    @property
    def _command(self):

        return ('--python-expr', self._script)


class Blend:
    """ Lazy evaluated `.blend` handler """

    _file_extension = None

    blender_binary = BLENDER_BINARY
    """ Blender's binary path to run commands with."""

    blender_stdout = None
    """ Blender's console output. """

    def __init__(self, blend_path: str, target_dir: str):
        """
        Parameters
        ----------
        blend_path: `.blend` file path

        target_dir: directory where files will be placed
        """
        self.blend_path = os.path.abspath(blend_path)

        self.target_directory = os.path.abspath(target_dir)
        """ Directory where files will be placed."""

        self.stem = os.path.splitext(os.path.basename(self.blend_path))[0]
        """ 
        A name for the generate files.
        
        By default the same as the `.blend`'s base name without the file extension. 
        """

    @staticmethod
    def _unwrap_args(args):
        unwrap_args = []
        for arg in args:
            if type(arg) is Script:
                unwrap_args.extend(arg._command)
            else:
                unwrap_args.append(arg)
        return unwrap_args


    def _get_job_expr(self, job: dict):
        return f"import builtins; builtins.__job__ = {job}"

    def _get_blend_stat(self):
        stat = os.stat(self.blend_path)
        return {
            'mtime': stat.st_mtime,
            'size': stat.st_size
        }


    @property
    def json_os_path_target(self):
        return os.path.join(self.target_directory, self.stem + '.json')

    @property
    def json(self):
        if not os.path.exists(self.json_os_path_target):
            return {}
        
        with open(self.json_os_path_target, 'r', encoding='utf-8') as json_file:
            try:
                return json.load(json_file)
            except json.decoder.JSONDecodeError:
                return {}

    @property
    def file_settings(self):
        return self.json.get(self._file_extension, {})

    def _write_json(self, data: dict):

        base_json_data = self.json

        settings = base_json_data.get(self._file_extension)
        if not settings:
            base_json_data[self._file_extension] = settings = {}

        settings.update(data)

        settings['write_count'] = settings.get('write_count', 0) + 1
        settings['blend_path'] = os.path.realpath(self.blend_path)
        settings['blend_stat'] = self._get_blend_stat()

        now = datetime.now()
        if not settings.get('ctime'):
            settings['ctime'] = settings['mtime'] = now.timestamp()
            settings['ctime_str'] = settings['mtime_str'] = now.astimezone().isoformat(' ', 'seconds')
        else:
            settings['mtime'] = now.timestamp()
            settings['mtime_str'] = now.astimezone().isoformat(' ', 'seconds')

        with open(self.json_os_path_target, 'w', encoding='utf-8') as json_file:
            json.dump(base_json_data, json_file, indent=4, ensure_ascii=False)

        utils.conform_file_name_letter_case(self.json_os_path_target, [self.json_os_path_target])

    @property
    def os_path_target(self):
        """ 
        OS style target path
        #### Does not update the files
        """
        return os.path.join(self.target_directory, self.stem + '.' + self._file_extension)

    def update(self):
        raise NotImplementedError('This function updates the target file.')

    @property
    def os_path(self):
        """ OS style path"""
        self.update()
        return os.path.realpath(self.os_path_target)

    def get_os_relpath(self, start: str):
        """ OS style relative path """
        return os.path.relpath(self.os_path, start)

    @property
    def path(self):
        """ Panda 3D style path """
        return Filename.from_os_specific(self.os_path)

    def get_relpath(self, start: str):
        """ Panda 3D style relative path """
        return Filename.from_os_specific(self.os_path).make_relative_to(Filename.from_os_specific(start))


class Pre_Post_Args_Mixin:

    def __init__(self):
        self._args_pre = []
        self._args_post = []

    @property
    def args_pre(self):
        """ Blender's command line arguments before the export script """
        return self._unwrap_args(self._args_pre)

    @property
    def args_post(self):
        """ Blender's command line arguments after the export script """
        return self._unwrap_args(self._args_post)


    def attach_pre_script(self, func: typing.Callable, *args, **kwargs):
        """
        The scrip will be executed before the file export.

        By default:
        `func` must not use the scope where it was declared, as it will be evaluated in isolation.
        `args` and `kwargs` must be JSON serializable.
        Set `script.use_dill = True` to use `uqfoundation/dill` to bypass that.
        """

        script = Script(func, args, kwargs)
        self._args_pre.append(script)

        return script

    def attach_post_script(self, func: typing.Callable, *args, **kwargs):
        """
        The scrip will be executed after the file export.

        By default:
        `func` must not use the scope where it was declared, as it will be evaluated in isolation.
        `args` and `kwargs` must be JSON serializable.
        Set `script.use_dill = True` to use `uqfoundation/dill` to bypass that.
        """

        script = Script(func, args, kwargs)
        self._args_post.append(script)

        return script