
def test_bake_code(result_dir: str, resolution = 128):

    from blend_converter import bpy_utils

    objects = bpy_utils.get_view_layer_objects()

    bpy_utils.merge_objects_and_bake_materials(objects, image_dir=result_dir, resolution=resolution)


def save_debug_blend(dir):
    import bpy
    import os

    bpy.ops.wm.save_as_mainfile(copy=True, filepath=os.path.join(dir, '_debug.blend'))
