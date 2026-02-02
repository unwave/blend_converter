import os
import time
import tempfile
import uuid

DIR = os.path.dirname(os.path.realpath(__file__))

BLEND_DIRS = [file.path for file in os.scandir(os.path.join(DIR, 'blend')) if file.is_dir() and not file.name.startswith('_')]


def get_result_dir(blend_dir):
    return os.path.join(tempfile.tempdir, 'blend_converter', 'test', os.path.basename(blend_dir) + '_' + uuid.uuid1().hex)


def get_bake_program(blend_dir: str, blender_executable: str):

    from blend_converter.blender.formats.blend import open_mainfile, save_as_mainfile
    from blend_converter.blender import bc_script
    from blend_converter.blender.executor import Blender
    from blend_converter import common
    from blend_converter import utils
    from blend_converter import tool_settings


    blend_path = common.File(utils.get_last_blend(blend_dir))
    result_dir = get_result_dir(blend_dir)
    result_path = os.path.join(result_dir, blend_path.dir_name + '.blend')

    blender = Blender(blender_executable)

    program = common.Program(
        blend_path = blend_path,
        result_path = result_path,
        blender_executable = blender.binary_path
    )

    program.run(blender, open_mainfile, blend_path, load_ui = False)

    objects = program.run(blender, bc_script.get_meshable_objects, program.run(blender, bc_script.get_view_layer_objects))

    uv_layer_name = program.run(blender, bc_script.get_uuid1_hex)

    program.run(blender, bc_script.unwrap, objects, uv_layer_name)

    settings = tool_settings.Bake_Materials(
        uv_layer_bake = uv_layer_name,
        image_dir = os.path.join(result_dir, 'textures'),
        texel_density = 64,
        max_resolution = 128,
    )



    program.run(blender, bc_script.scale_uv_to_world_per_uv_island, objects, uv_layer_name)

    program.run(blender, bc_script.scale_uv_to_world_per_uv_layout, objects, uv_layer_name)

    program.run(blender, bc_script.apply_modifiers, objects)

    program.run(blender, bc_script.pack_copy_bake, objects, settings)


    program.run(blender, bc_script.select_uv_layer, objects, uv_layer_name)

    program.run(blender, bc_script.scene_clean_up)

    program.run(blender, bc_script.remove_all_node_groups_from_materials)

    program.run(blender, save_as_mainfile, result_path)


    return program
