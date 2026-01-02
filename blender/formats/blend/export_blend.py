

def save_as_mainfile(filepath: str, compress = True, relative_remap = True, copy = False):

    import bpy
    import os

    if bpy.app.version >= (2, 80):
        bpy.context.preferences.use_preferences_save = False
        bpy.context.preferences.filepaths.save_version = 0
    else:
        bpy.context.user_preferences.filepaths.save_version = 0

    if bpy.data.filepath and os.path.exists(filepath) and os.path.samefile(filepath, bpy.data.filepath):
        raise Exception(f"Should not save the blend file in the same location: {filepath}")

    os.makedirs(os.path.dirname(filepath), exist_ok = True)

    try:
        bpy.ops.wm.save_as_mainfile(filepath=filepath, compress=compress, relative_remap=relative_remap, copy=copy)
    except RuntimeError as e:
        if 'Unable to pack file' in str(e):
            pass
        elif "has an invalid 'from' pointer (0000000000000000), it will be deleted" in str(e):
            # https://projects.blender.org/blender/blender/issues/111905
            pass
        else:
            raise e

    print(f"Blend is saved in path: {filepath}")
