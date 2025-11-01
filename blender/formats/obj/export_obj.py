

def export_obj(filepath: str, settings = dict()):

    import bpy

    bpy.context.preferences.use_preferences_save = False
    bpy.ops.preferences.addon_enable(module='io_scene_obj')

    import os
    os.makedirs(os.path.dirname(filepath), exist_ok = True)

    bpy.ops.wm.obj_export(**settings)
