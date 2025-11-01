import os
import importlib
import importlib.util
import typing
import sys
import json


BLEND_CONVERTER_INIT = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), '__init__.py')


def import_module_from_file(file_path: str, module_name: typing.Optional[str] = None):

    if not os.path.isabs(file_path):
        raise Exception(f"Path to file must be absolute: {file_path}")

    if module_name is None:
        module_name = os.path.splitext(os.path.basename(file_path))[0]

    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None:
        raise Exception(f"Spec not found: {module_name}, {file_path}")

    module = importlib.util.module_from_spec(spec)

    sys.modules[module_name] = module
    spec.loader.exec_module(module)  # type: ignore[reportOptionalMemberAccess]

    return module


if typing.TYPE_CHECKING:
    import blend_converter
else:
    blend_converter = import_module_from_file(BLEND_CONVERTER_INIT, 'blend_converter')



if 'bpy' in sys.modules:
    import bpy


def delete_other(object_names):

    from blend_converter.blender import bpy_context

    with bpy_context.Focus_Objects([object for object in bpy.data.objects if object.name in object_names]):
        bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')

    bpy.data.batch_remove(set(object for object in bpy.data.objects if object.name not in object_names))


def make_everything_local():

    bpy.ops.object.make_local(type='ALL')


if __name__ == '__main__':

    ARGS = json.loads(sys.argv[1])

    blend_path: str = ARGS['blend_path']
    object_names: list = ARGS['object_names']
    temp_dir: str = ARGS['temp_dir']
    bake_settings: dict = ARGS['bake_settings']
    update_model_json_info: str = ARGS['update_model_json_info']
    model_type: str = ARGS['model_type']
    blender_executable: str = ARGS['blender_executable']

    bullet_physics: str = ARGS['bullet_physics']

    from blend_converter import common
    from blend_converter.blender import Blender
    from blend_converter.blender import bc_script
    from blend_converter.blender.formats.blend import open_mainfile

    blender = Blender(blender_executable)

    program = common.Program(blend_path='', result_path='', blender_executable='', report_path = os.path.join(temp_dir, 'report.json'))

    program.run(blender, open_mainfile, blend_path)

    program.run(blender, make_everything_local)

    if not bullet_physics:

        kwargs = dict(image_dir = temp_dir, resolution = 1024)
        kwargs.update(bake_settings)
        program.run(blender, bc_script.merge_objects_and_bake_materials, object_names, **kwargs)

        program.run(blender, delete_other, object_names)

    if False and model_type == 'Bam':

        from blend_converter.blender.formats.bam import Bam

        from blend_converter.blender.formats.bam import post_conversion, pre_conversion

        program.run(pre_conversion.assign_curve_placeholders)
        program.run(pre_conversion.assign_collision_placeholders)

        program.run_bam_function(post_conversion.convert_curve_placeholders)
        program.run_bam_function(post_conversion.convert_collision_placeholders)

    elif model_type == 'Gltf':
        from blend_converter.blender.formats.gltf import export_gltf, Settings_GLTF

        result_path = os.path.join(temp_dir, 'converted.gltf')

        program.run(blender, export_gltf, result_path, Settings_GLTF(export_format = 'GLTF_SEPARATE'))

    else:
        raise Exception(f"Unknown file type: {model_type}")


    program.execute()


    with open(update_model_json_info, 'w', encoding='utf-8') as file:
        json.dump({'path': result_path}, file)
