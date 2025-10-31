import os


def ensure_addon(name: str, zip_url: str):
    """ Download an addon zip file and put into Blender's `script/addons` directory. """

    import bpy

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

    script_path_user = bpy.utils.script_path_user()
    assert script_path_user is not None

    addon_dir = os.path.join(script_path_user, 'addons')
    os.makedirs(addon_dir, exist_ok=True)
    zip_file.extractall(addon_dir)

    root_dir = os.path.commonpath([os.path.join(addon_dir, name) for name in namelist])
    assert os.path.isdir(root_dir)

    new_root_dir = os.path.join(os.path.dirname(root_dir), name)
    os.rename(root_dir, new_root_dir)

    importlib.invalidate_caches()


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


def export_egg(settings: dict):

    import bpy

    bpy.context.preferences.use_preferences_save = False

    # Not found
    # url = r'https://github.com/kergalym/PRPEE/archive/7a11e066e99735229284beca830c95f33385e5ce.zip'
    # ensure_addon('prpee', url)

    def handle_error(exc):
        raise exc

    import addon_utils
    addon_utils.enable(module_name = 'prpee', default_set = True, persistent = True, handle_error = handle_error)

    from prpee import egg_writer  # type: ignore

    errors = call_anyway(egg_writer.write_out, settings)

    if errors:
        rep_msg = ''
        if 'ERR_UNEXPECTED' in errors:
            rep_msg += 'Unexpected error during export! See console for traceback.\n'
        if 'ERR_MK_HIERARCHY' in errors:
            rep_msg += 'Error while creating hierarchy. Check parent objects and armatures.'
        if 'ERR_MK_OBJ' in errors:
            rep_msg += 'Unexpected error while creating object. See console for traceback.'
        raise Exception(rep_msg)
