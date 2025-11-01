

def export_fbx(filepath: str, settings = dict()):

    import bpy

    if 'object_types' in settings:
        settings['object_types'] = set(settings['object_types'])

    bpy.context.preferences.use_preferences_save = False
    bpy.ops.preferences.addon_enable(module='io_scene_fbx')

    import os
    os.makedirs(os.path.dirname(filepath), exist_ok = True)

    bpy.ops.export_scene.fbx(filepath = filepath, **settings)
