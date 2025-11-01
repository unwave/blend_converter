
def export_gltf(filepath: str, settings = dict()):

    import bpy

    bpy.context.preferences.use_preferences_save = False
    bpy.ops.preferences.addon_enable(module='io_scene_gltf2')

    import os
    os.makedirs(os.path.dirname(filepath), exist_ok = True)

    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter('default')

        bpy.ops.export_scene.gltf(filepath=filepath, **settings)

    print(f"glTF is exported in path: {filepath}")
