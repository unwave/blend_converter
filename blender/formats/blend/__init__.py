import os

if __spec__.name == __name__:
    from blend_converter.blender.formats.blend.export_blend import save_as_mainfile
else:
    from .export_blend import save_as_mainfile


def open_mainfile(filepath: str, load_ui = True, use_scripts = False):

    import bpy

    bpy.ops.wm.open_mainfile(filepath=filepath, load_ui=load_ui, use_scripts=use_scripts)
