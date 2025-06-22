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
def test_merge_and_bake_gltf(blend_dir, blender_executable):
    """ this test is not meant for evaluating the quality of the results, just for code being executed without errors """

    from blend_converter.format import gltf
    from blend_converter import utils
    from blend_converter import bc_script

    model = gltf.Gltf(utils.get_last_blend(blend_dir), get_result_dir(blend_dir))

    model.settings.export_apply = True

    model.blender_executable = blender_executable

    model.run(bc_script.merge_objects_and_bake_materials, model.run(bc_script.get_view_layer_objects), image_dir=os.path.join(model.result_dir, 'textures'), resolution=128)

    model.run(bc_script.save_blend_as_copy, os.path.join(model.result_dir, '_debug.blend'))

    model.run(bc_script.scene_clean_up)

    model.run(bc_script.remove_all_node_groups_from_materials)

    model.update(True)


@pytest.mark.parametrize('blend_dir', BLEND_DIRS)
def test_copy_and_bake_gltf(blend_dir, blender_executable):
    """ this test is not meant for evaluating the quality of the results, just for code being executed without errors """

    from blend_converter.format import gltf
    from blend_converter import utils
    from blend_converter import bc_script
    from blend_converter import tool_settings

    model = gltf.Gltf(utils.get_last_blend(blend_dir), get_result_dir(blend_dir))

    model.settings.export_apply = True

    model.blender_executable = blender_executable

    objects = model.run(bc_script.get_meshable_objects, model.run(bc_script.get_view_layer_objects))

    settings = tool_settings.Bake_Materials(
        image_dir = os.path.join(model.result_dir, 'textures'),
        texel_density = 64,
        max_resolution = 128,
        faster_ao_bake = True,
        bake_original_topology=True,
    )

    model.run(bc_script.copy_and_bake_materials, objects, settings)

    model.run(bc_script.save_blend_as_copy, os.path.join(model.result_dir, '_debug.blend'))

    model.run(bc_script.scene_clean_up)

    model.run(bc_script.remove_all_node_groups_from_materials)

    model.update(True)
