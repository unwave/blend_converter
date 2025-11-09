""" inspect_blend related functionally and settings """

import os
import tempfile
import typing
import sys
import subprocess
import re
import functools
import inspect

from . import utils

_identifiers = set()


def add_identifier(*identifiers: str):
    _identifiers.update(identifiers)


def has_identifier(*identifiers: str) -> bool:
    return not _identifiers.isdisjoint(identifiers)


def search_identifier(regex: str):

    matches: typing.List[re.Match] = []

    for identifier in _identifiers:
        match = re.search(regex, identifier)
        if match:
            matches.append(match)

    return matches


class COMMON:

    INSPECT_SCRIPT_ALL = 'inspect:script:all'
    """ inspect after each script """

    INSPECT_BLEND_ORIG = 'inspect:blend:orig'
    """ inspect the original blend """

    INSPECT_BLEND_FINAL = 'inspect:blend:final'
    """ inspect the final blend """

    INSPECT_ERROR = 'inspect:error'
    """ inspect on a script error """

    INSPECT_BAKE_PRE = 'inspect:bake:pre'
    """ inspect before baking a texture """

    INSPECT_BAKE_AFTER = 'inspect:bake:after'
    """ inspect after baking a texture """

    INSPECT_BAKE_COMPOSER = 'inspect:bake:comp'
    """ inspect composer """


    INSPECT_UV_UNWRAP = 'inspect:uv:unwrap'
    """ after uv unwrapping """

    INSPECT_UV_PACK = 'inspect:uv:pack'
    """ after uv packing """

    # INSPECT_UV_ALL = 'inspect:uv:all'
    """ both after uv unwrapping and uv packing """


    # SKIP_ALL = 'skip:all'
    """ skip everything possible """


    SKIP_INSPECT = 'skip:inspect'
    """ skip inspect_blend() calls """

    SKIP_BREAKPOINT = 'skip:breakpoint'
    """ skip breakpoint() calls """


    SKIP_BAKE_ALL = 'skip:bake:all'
    """ skip baking all maps, except for maps specified using the inspect command """


    SKIP_BAKE_SAVE = 'skip:bake:save'
    """ skip composing and saving all maps"""


    SKIP_UV_PACK = 'skip:uv:pack'
    """ skip pack """

    SKIP_UV_UNWRAP = 'skip:uv:unwrap'
    """ skip unwrapping """

    SKIP_UV_ALL = 'skip:uv:all'
    """ skip uv unwrapping and uv packing """




def _inspect_blend(name = 'DEBUG', blender_executable: typing.Optional[str] = None, exit_after = False, detached = False):
    """ Blocking blend file inspection. """

    import bpy

    if blender_executable is None:
        blender_executable = bpy.app.binary_path

    if bpy.data.filepath:
        filepath_stem = ' ' + os.path.splitext(os.path.basename(bpy.data.filepath))[0]
    else:
        filepath_stem = ''

    with tempfile.TemporaryDirectory() as temp_dir:

        filename = utils.ensure_valid_basename(f'[{name}]{filepath_stem}.blend')

        if detached:
            filepath = os.path.join(bpy.app.tempdir, filename)
        else:
            filepath = os.path.join(temp_dir, filename)

        for image in bpy.data.images:
            if image.source == 'GENERATED' and image.is_dirty:
                image.pack()

        try:
            bpy.ops.wm.save_as_mainfile(filepath = filepath, copy = True)
        except RuntimeError as e:
            print(e, file=sys.stderr)

        if detached:
            utils.open_blender_detached(blender_executable, filepath)
        else:
            subprocess.run([blender_executable, filepath])

    if exit_after:
        raise SystemExit('DEBUG EXIT')


@functools.wraps(_inspect_blend)
def inspect_blend(*args, **kwargs):

    if get_value('confirm_inspect', False):

        print("Pending inspect", *args, **kwargs)

        import bpy
        print('bpy.data.filepath:', bpy.data.filepath)

        print("To disable the confirmation enter: disable")
        print("To ignore all inspections enter: noinspect")

        value = input("y/n?:").lower()
        if value == 'disable':
            add_value(confirm_inspect=False)
        elif value == 'noinspect':
            add_value(confirm_inspect=False)
            add_identifier(COMMON.SKIP_INSPECT)
            return
        elif value != 'y':
            return


    if has_identifier(COMMON.SKIP_INSPECT):
        print('Inspect skipped:', *args, **kwargs)
        return

    _inspect_blend(*args, **kwargs)


def inspectable(func):

    @functools.wraps(func)
    def wrapper(*args, **kwargs):

        inspect_if_has_identifier(f'inspect:func:pre={func.__name__}')

        if has_identifier(f'skip:func={func.__name__}'):
            print(f"Skipping: {func.__name__}")
            return

        try:
            depth = max(len(inspect.stack()) - 8, 0)

            args_print = ', '.join([repr(value) for value in args])
            kwargs_print = ', '.join([f"{key}={repr(value)}" for key, value in kwargs.items()])

            print('\t' * depth + f"{func.__name__}({args_print}, {kwargs_print})")
            return func(*args, **kwargs)
        finally:
            inspect_if_has_identifier(f'inspect:func:post={func.__name__}')

    return wrapper


def skipable(*identifier: str):

    def decorator(func):

        @functools.wraps(func)
        def wrapper(*args, **kwargs):

            if has_identifier(*identifier):
                print(f"Skipping: {func.__name__}")
                return

            return func(*args, **kwargs)

        return wrapper

    return decorator


def inspect_if_has_identifier(*identifier: str):
    if has_identifier(*identifier):
        inspect_blend(' | '.join(_identifiers & set(identifier)))
        return True
    else:
        return False


T = typing.TypeVar('T')

_values: typing.Dict[str, str] = {}

def get_value(key: str, default: typing.Optional[T]) -> T:
    return type(default)(_values.get(key, default))

def add_value(**kwargs):
    _values.update(kwargs)


def make_top_functions_inspectable():

    from . import bake_settings
    from . import bc_script
    from . import bpy_bake
    from . import bpy_context
    from . import bpy_data
    from . import bpy_mesh
    from . import bpy_modifier
    from . import bpy_node
    from . import bpy_utils
    from . import bpy_uv

    modules = [
        bake_settings,
        bc_script,
        bpy_bake,
        bpy_context,
        bpy_data,
        bpy_mesh,
        bpy_modifier,
        bpy_node,
        bpy_utils,
        bpy_uv,
    ]

    for module in modules:
        for name, object in module.__dict__.items():
            if inspect.isfunction(object):
                setattr(module, name, inspectable(object))
