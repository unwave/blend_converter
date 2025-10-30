

def export_fbx(settings: dict):

    import bpy

    if 'object_types' in settings:
        settings['object_types'] = set(settings['object_types'])

    bpy.context.preferences.use_preferences_save = False
    bpy.ops.preferences.addon_enable(module='io_scene_fbx')

    bpy.ops.export_scene.fbx(**settings)
