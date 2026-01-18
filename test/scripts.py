

def save_debug_blend(dir):
    import bpy
    import os

    bpy.ops.wm.save_as_mainfile(copy=True, filepath=os.path.join(dir, '_debug.blend'))
