import pytest
import os
import time


DIR = os.path.dirname(os.path.realpath(__file__))

BLEND_DIRS = [file.path for file in os.scandir(os.path.join(DIR, 'blend')) if file.is_dir() and not file.name.startswith('_')]

RESULTS_DIR = os.path.join(DIR, '_result')


def get_result_dir(blend_dir):
    result_dir = os.path.join(RESULTS_DIR, os.path.basename(blend_dir) + f"_{time.strftime('%Y%m%d_%H%M%S')}")
    os.makedirs(result_dir, exist_ok=True)
    return result_dir


@pytest.mark.parametrize('blend_dir', BLEND_DIRS)
def test_simple_gltf(blend_dir, blender_executable):

    from blend_converter.format import gltf
    from blend_converter import utils
    from blend_converter import bc_script

    model = gltf.Gltf(utils.get_last_blend(blend_dir), get_result_dir(blend_dir))

    model.settings.export_apply = True

    model.blender_executable = blender_executable

    model.run(bc_script.merge_objects_and_bake_materials, model.run(bc_script.get_view_layer_objects), image_dir=os.path.join(model.result_dir, 'textures'), resolution=128)

    model.run(bc_script.save_blend_as_copy, os.path.join(model.result_dir, '_debug.blend'))

    model.update(True)
