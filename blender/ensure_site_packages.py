""" Installing dependencies using pip for Blender. """

import importlib
import importlib.util
import os
import sys
import typing

import bpy


if bpy.app.version < (2, 91, 0):
    PYTHON_BINARY = bpy.app.binary_path_python
else:
    PYTHON_BINARY = sys.executable

BLENDER_EXECUTABLE = bpy.app.binary_path

STATUS_DLL_NOT_FOUND = 3221225781
""" The WindowsApps' rights restriction affects DLLs discovery in PATH """


def pip_fallback(modules_to_install, directory):
    """ A fallback to install using a Blender's executable. """

    from pip._internal import main
    return main(['install', '--upgrade', *modules_to_install, "--target", directory, '--verbose'])


def ensurepip_fallback():
    """ A fallback to install using a Blender's executable. """

    import ensurepip
    ensurepip.bootstrap(verbosity=1)


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


def get_terminal_width(fallback = 80):

    try:
        value = int(os.environ['COLUMNS'])
    except Exception:
        try:
            value = os.get_terminal_size(sys.__stdout__.fileno()).columns
        except Exception:
            value = fallback

    return value


def print_separator(*values: object, sep: str = ' '):

    width = get_terminal_width() - 1

    text = sep.join((str(value) for value in values))

    if text:
        text = ' ' + text + ' '

    text_len = len(text)
    rest_of_width = width - text_len
    half_rest_of_width = int(rest_of_width / 2)

    print('=' * half_rest_of_width, text, '=' * (width - (half_rest_of_width + text_len)), sep='', flush=True)


def get_os_environ():

    env = os.environ.copy()

    PATH = env['PATH']
    paths = PATH.split(os.pathsep)

    def add_to_PATH(path):

        if not os.path.exists(path):
            return

        path = os.path.realpath(path)
        if path in paths:
            return

        paths.insert(0, path)

    blender_dir = os.path.dirname(BLENDER_EXECUTABLE)
    # vcruntime140.dll
    blender_crt = os.path.join(blender_dir, 'blender.crt')

    add_to_PATH(blender_crt)
    add_to_PATH(blender_dir)

    env['PATH'] = os.pathsep.join(paths)

    return env


def get_relative_site_packages_directory(subdir = 'deps', root_dir: str = os.path.dirname(os.path.realpath(__file__))):
    version = sys.version_info
    return os.path.join(root_dir, subdir, f"v{version[0]}{version[1]}")


def get_missing_site_packages(packages: typing.List[typing.Tuple[str, str]], directory: str):
    """ Returns a list of missing packages in `packages`. """

    directory = os.path.abspath(directory)
    if not directory in sys.path and os.path.exists(directory):
        sys.path.append(directory)

    return [package for package in packages if not importlib.util.find_spec(package[0])]


def ensure_site_packages(packages: typing.List[typing.Tuple[str, str]], directory: typing.Union[str, os.PathLike], ignore_installed = False):
    """
    `packages`: list of tuples (<import name>, <pip name>)
    `directory`: a folder for site packages, will be created if does not exist and added to `sys.path`
    `ignore_installed`: call `pip install` with all the packages specified, even if `importlib.util.find_spec` finds the package
    """

    if not packages:
        return


    if not isinstance(packages, list):
        raise TypeError(f"Invalid packages parameter: {repr(item)}. Must be a list.")


    for item in packages:
        if not isinstance(item, tuple) or len(item) != 2 or type(item[0]) is not str or type(item[1]) is not str:
            raise TypeError(f"Invalid packages parameter item: {repr(item)}. Must be a tuple with two strings.")


    directory = os.path.abspath(directory)

    os.makedirs(directory, exist_ok = True)
    if not directory in sys.path:
        sys.path.append(directory)


    if ignore_installed:
        modules_to_install = [module[1] for module in packages]

    else:

        modules_to_install = [module[1] for module in packages if not importlib.util.find_spec(module[0])]
        if not modules_to_install:
            return

        # double check before installing
        importlib.invalidate_caches()

        modules_to_install = [module[1] for module in packages if not importlib.util.find_spec(module[0])]
        if not modules_to_install:
            return


    print_separator('START ensure_site_packages')

    import subprocess
    import traceback

    env = get_os_environ()
    env['PYTHONPATH'] = directory


    # all new blender versions have pip but some old one don't
    # ensurepip might be not present but pip still available (v2.82)
    # TODO: possibly rewrite to ensure the installed pip will be available in the following execution
    if not importlib.util.find_spec('pip'):
        print_separator('ensurepip')
        try:
            # will default to --user if cannot install into normal location
            subprocess.run([PYTHON_BINARY, '-m', 'ensurepip', '--verbose'], check=True, env=env)

        except subprocess.CalledProcessError as e:

            if e.returncode == STATUS_DLL_NOT_FOUND:
                # this will probably also not work as it uses subprocess and sys.executable
                subprocess.run([BLENDER_EXECUTABLE, '--python-use-system-env', '--factory-startup', '-b', '--python-expr', get_python_expr(ensurepip_fallback)], check=True, env=env)
            else:
                traceback.print_exc()

        except Exception:
            traceback.print_exc()


    # If --target is set, all pip does is: Set ignore-installed to true. (So that stuff already in site-packages doesn't block the install).
    # https://github.com/pypa/pip/issues/1489#issuecomment-53972933


    # some packages like opencv can require a newer pip version
    # updating pip might fail but the existing pip could suffice
    print_separator('upgrade pip')
    try:
        subprocess.run([PYTHON_BINARY, '-m', 'pip', 'install', '--upgrade', 'pip', "--target", directory, '--verbose'], check=True, env=env)

    except subprocess.CalledProcessError as e:

        if e.returncode == STATUS_DLL_NOT_FOUND:
            subprocess.run([BLENDER_EXECUTABLE, '--python-use-system-env', '--factory-startup', '-b', '--python-expr', get_python_expr(pip_fallback, ['pip'], directory)], check=True, env=env)
        else:
            print_separator("trying to force reinstall pip")
            try:
                subprocess.run([PYTHON_BINARY, '-m', 'pip', 'install', '--upgrade', '--ignore-installed', 'pip', "--target", directory, '--verbose'], check=True)
            except Exception:
                traceback.print_exc()

    except Exception:
        traceback.print_exc()


    print_separator('install dependencies')
    try:
        subprocess.run([PYTHON_BINARY, '-s', '-m', 'pip', 'install', '--upgrade', *modules_to_install, "--target", directory, '--verbose'], check=True, env=env)

    except subprocess.CalledProcessError as e:

        if e.returncode == STATUS_DLL_NOT_FOUND:
            subprocess.run([BLENDER_EXECUTABLE, '--python-use-system-env', '--factory-startup', '-b', '--python-expr', get_python_expr(pip_fallback, modules_to_install, directory)], check=True, env=env)
        else:
            print_separator("trying with the shipped pip")
            env['PYTHONPATH'] = ''
            subprocess.run([PYTHON_BINARY, '-s', '-m', 'pip', 'install', '--upgrade', *modules_to_install, "--target", directory, '--verbose'], check=True, env=env)


    importlib.invalidate_caches()

    missing_packages = [package for package in packages if not importlib.util.find_spec(package[0])]
    if missing_packages:
        raise Exception(f'Fail to install dependencies: {missing_packages}')

    print_separator('END ensure_site_packages')
