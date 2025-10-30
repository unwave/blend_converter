

def export_obj(settings: dict):

    import bpy

    bpy.context.preferences.use_preferences_save = False
    bpy.ops.preferences.addon_enable(module='io_scene_obj')

    bpy.ops.wm.obj_export(**settings)
