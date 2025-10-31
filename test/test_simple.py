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

    from blend_converter.blender.formats.gltf import export_gltf, Settings_GLTF
    from blend_converter.blender.formats.blend import open_mainfile
    from blend_converter.blender import bc_script
    from blend_converter.blender import Blender
    from blend_converter import common
    from blend_converter import utils

    blend_path = common.File(utils.get_last_blend(blend_dir))
    result_dir = get_result_dir(blend_dir)
    result_path = os.path.join(result_dir, blend_path.dir_basename + '.gltf')

    blender = Blender(blender_executable)

    program = common.Program(
        blend_path = blend_path,
        result_path = result_path,
        blender_executable = blender.binary_path
    )

    program.run(blender, open_mainfile, blend_path)

    program.run(blender, bc_script.reset_ui_layout)

    program.run(blender, bc_script.merge_objects_and_bake_materials, program.run(blender, bc_script.get_view_layer_objects), image_dir=os.path.join(result_dir, 'textures'), resolution=128)

    program.run(blender, bc_script.save_blend_as_copy, os.path.join(result_dir, f'{blend_path.stem}_debug.blend'))

    program.run(blender, bc_script.scene_clean_up)

    program.run(blender, bc_script.remove_all_node_groups_from_materials)

    program.run(blender, export_gltf, program.result_path, Settings_GLTF(export_apply=True))

    program.execute(True)


@pytest.mark.parametrize('blend_dir', BLEND_DIRS)
def test_copy_and_bake_gltf(blend_dir, blender_executable):
    """ this test is not meant for evaluating the quality of the results, just for code being executed without errors """

    from blend_converter.blender.formats.gltf import export_gltf, Settings_GLTF
    from blend_converter.blender.formats.blend import open_mainfile
    from blend_converter.blender import bc_script
    from blend_converter.blender import Blender
    from blend_converter import common
    from blend_converter import utils
    from blend_converter import tool_settings


    blend_path = common.File(utils.get_last_blend(blend_dir))
    result_dir = get_result_dir(blend_dir)
    result_path = os.path.join(result_dir, blend_path.dir_basename + '.gltf')

    blender = Blender(blender_executable)

    program = common.Program(
        blend_path = blend_path,
        result_path = result_path,
        blender_executable = blender.binary_path
    )

    program.run(blender, open_mainfile, blend_path)

    # TODO: getting a crash on `bpy_context.call_in_view3d(bpy.ops.transform.resize...` for an BLENDER_v249 file
    program.run(blender, bc_script.reset_ui_layout)

    objects = program.run(blender, bc_script.get_meshable_objects, program.run(blender, bc_script.get_view_layer_objects))

    settings = tool_settings.Bake_Materials(
        image_dir = os.path.join(result_dir, 'textures'),
        texel_density = 64,
        max_resolution = 128,
        faster_ao_bake = True,
        bake_original_topology=True,
    )

    program.run(blender, bc_script.copy_and_bake_materials, objects, settings)

    program.run(blender, bc_script.save_blend_as_copy, os.path.join(result_dir, f'{blend_path.stem}_debug.blend'))

    program.run(blender, bc_script.scene_clean_up)

    program.run(blender, bc_script.remove_all_node_groups_from_materials)

    program.run(blender, export_gltf, program.result_path, Settings_GLTF(export_apply=True))

    program.execute(True)
