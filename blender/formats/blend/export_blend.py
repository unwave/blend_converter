

def export_blend(settings: dict):

    import bpy

    if bpy.app.version >= (2, 80):
        bpy.context.preferences.use_preferences_save = False
        bpy.context.preferences.filepaths.save_version = 0
    else:
        bpy.context.user_preferences.filepaths.save_version = 0

    filepath = settings.pop('filepath')

    if bpy.data.filepath:
        import os
        if os.path.exists(filepath) and os.path.samefile(filepath, bpy.data.filepath):
            raise Exception(f"Should not save the blend file in the same location: {filepath}")

    try:
        bpy.ops.wm.save_as_mainfile(filepath=filepath, **settings)
    except RuntimeError as e:
        if 'Unable to pack file' in str(e):
            print(e)
        else:
            raise e

    print(f"Blend saved in path: {filepath}")
