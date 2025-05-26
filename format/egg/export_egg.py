import bpy
import os
import sys
import argparse

parser = argparse.ArgumentParser()
parser.add_argument('-caller_script_dir')

args = sys.argv[sys.argv.index('--') + 1:]
args = parser.parse_args(args)

CALLER_SCRIPT_DIR: str = args.caller_script_dir


def ensure_addon(name: str, zip_url: str):

    import importlib
    import importlib.util

    if importlib.util.find_spec(name):
        return

    import requests
    import zipfile
    import io

    response = requests.get(zip_url)
    zip_file = zipfile.ZipFile(io.BytesIO(response.content))
    namelist = zip_file.namelist()

    addon_dir = os.path.join(bpy.utils.script_path_user(), 'addons')
    os.makedirs(addon_dir, exist_ok=True)
    zip_file.extractall(addon_dir)

    root_dir = os.path.commonpath([os.path.join(addon_dir, name) for name in namelist])
    assert os.path.isdir(root_dir)

    new_root_dir = os.path.join(os.path.dirname(root_dir), name)
    os.rename(root_dir, new_root_dir)

    importlib.invalidate_caches()

PRPEE_URL = r'https://github.com/kergalym/PRPEE/archive/7a11e066e99735229284beca830c95f33385e5ce.zip'
ensure_addon('prpee', PRPEE_URL)

import addon_utils
addon_utils.enable("prpee", persistent = True)

from prpee import egg_writer # type: ignore

def call_anyway(func, kwargs: dict, sentinel = object()):
    new_kwargs = {}

    import inspect

    for argument in inspect.signature(func).parameters.values():
        name = argument.name

        value = kwargs.get(name, sentinel)
        if value != sentinel:
            new_kwargs[name] = value
            continue

        if argument.default == argument.empty:
            new_kwargs[name] = None

    return func(**new_kwargs)

job = get_job() # type: ignore
errors = call_anyway(egg_writer.write_out, job)

if errors:
    rep_msg = ''
    if 'ERR_UNEXPECTED' in errors:
        rep_msg += 'Unexpected error during export! See console for traceback.\n'
    if 'ERR_MK_HIERARCHY' in errors:
        rep_msg += 'Error while creating hierarchy. Check parent objects and armatures.'
    if 'ERR_MK_OBJ' in errors:
        rep_msg += 'Unexpected error while creating object. See console for traceback.'
    raise BaseException(rep_msg)