
def export_gltf(settings: dict):

    import bpy

    bpy.context.preferences.use_preferences_save = False
    bpy.ops.preferences.addon_enable(module='io_scene_gltf2')

    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter('default')

        bpy.ops.export_scene.gltf(**settings)
