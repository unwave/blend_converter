from .export_blend import save_as_mainfile
from ... import blend_inspector


def open_mainfile(filepath: str, load_ui = True, use_scripts = False):

    import bpy

    try:
        bpy.ops.wm.open_mainfile(filepath=filepath, load_ui=load_ui, use_scripts=use_scripts)
    except RuntimeError as e:
        print(e)

    blend_inspector.inspect_if_has_identifier(blend_inspector.COMMON.INSPECT_BLEND_OPEN)
