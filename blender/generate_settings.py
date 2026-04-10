import textwrap
import typing
import os
import sys


if 'bpy' in sys.modules:
    import bpy


INDENT = ' ' * 4

IMPORTS = """
import typing


from ... import tool_settings


if typing.TYPE_CHECKING:
    import dataclasses
else:
    class dataclasses:
        dataclass = lambda x: x
"""

CLASS_DECORATOR = '@dataclasses.dataclass'


def get_class_signature(name: str):
    return fr'class {name}(tool_settings.Settings):'


def get_gltf_export_format():

    # from io_scene_gltf2 import get_format_items  # type: ignore
    # items = get_format_items(None, None)

    items = [
        ('GLB', 'glTF Binary (.glb)',
        'Exports a single file, with all data packed in binary form. '
        'Most efficient and portable, but more difficult to edit later'),
        ('GLTF_SEPARATE', 'glTF Separate (.gltf + .bin + textures)',
        'Exports multiple files, with separate JSON, binary and texture data. '
        'Easiest to edit later'),
        ('GLTF_EMBEDDED', 'glTF Embedded (.gltf)',
        'Exports a single file, with all data packed in JSON. '
        'Less efficient than binary, but easier to edit later'),
    ]

    lines = []
    lines.append('export_format: str')
    lines.append('"""')
    lines.append("Output format. Binary is most efficient, but JSON may be easier to edit later")
    lines.append("Options:")

    for item in items:
        lines.append(f"* `{item[0]}`: {item[1]}{' — ' + item[2] if item[2] else ''}")

    lines.append('')
    lines.append('')
    lines.append("#### Default: `'GLB'`")

    lines.append('"""')
    lines.append('')
    lines.append('')

    return  '\n'.join(lines)


def get_class_lines(name: str, docs_string: str, properties: object, ignore = set()):

    from blend_converter.blender import type_utils


    property_lines = []

    for key, value in type_utils.get_docs_from_properties(properties).items():

        if key in ignore:
            continue

        if name == 'S_GLTF' and key == 'export_format':

            try:
                value = get_gltf_export_format()
            except Exception as e:
                print(e)

        property_lines.extend(value)


    docs = []
    docs.append('"""')
    docs.append(docs_string)
    docs.append('')
    docs.append(f"Blender {bpy.app.version_string}")
    docs.append('"""')

    lines = []

    lines.append(CLASS_DECORATOR)
    lines.append(get_class_signature(name))
    lines.append(textwrap.indent('\n'.join(docs), INDENT))
    lines.append('')
    lines.append('')
    lines.append(textwrap.indent('allow_missing_settings = True', INDENT))
    lines.append('')
    lines.append('')
    lines.append(textwrap.indent(''.join(property_lines), INDENT))

    return lines



def write_image_settings(file_path: str):

    lines = []

    lines.append(IMPORTS)
    lines.append('')
    lines.append('')

    lines.extend(get_class_lines('S_Image', "`bpy.context.scene.render.image_settings`", bpy.context.scene.render.image_settings.bl_rna.properties, {'filepath'}))
    lines.extend(get_class_lines('S_Render', "`bpy.context.scene.render`", bpy.context.scene.render.bl_rna.properties, {'filepath'}))
    lines.extend(get_class_lines('S_Cycles', "`bpy.context.scene.cycles`", bpy.context.scene.cycles.bl_rna.properties, {'filepath'}))
    lines.extend(get_class_lines('S_Eevee', "`bpy.context.scene.eevee`", bpy.context.scene.eevee.bl_rna.properties, {'filepath'}))
    lines.extend(get_class_lines('S_View', "`bpy.context.scene.view_settings`", bpy.context.scene.view_settings.bl_rna.properties, {'filepath'}))


    with open(file_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines).strip() + '\n')


def write_fbx_settings(file_path: str):

    lines = []

    lines.append(IMPORTS)
    lines.append('')
    lines.append('')

    lines.extend(get_class_lines('S_Fbx', "`bpy.ops.export_scene.fbx`", bpy.ops.export_scene.fbx.get_rna_type().properties, {'filepath'}))

    with open(file_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines).strip() + '\n')


def write_gltf_settings(file_path: str):

    lines = []

    lines.append(IMPORTS)
    lines.append('')
    lines.append('')

    lines.extend(get_class_lines('S_GLTF', "`bpy.ops.export_scene.gltf`", bpy.ops.export_scene.gltf.get_rna_type().properties, {'filepath'}))

    with open(file_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines).strip() + '\n')


def write_obj_settings(file_path: str):

    lines = []

    lines.append(IMPORTS)
    lines.append('')
    lines.append('')

    lines.extend(get_class_lines('S_Obj', "`bpy.ops.wm.obj_export`", bpy.ops.wm.obj_export.get_rna_type().properties, {'filepath'}))


    with open(file_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines).strip() + '\n')


def main(blender_executable: str):

    from .. import common
    from .. import root
    from .executor import Blender

    generated_dir = os.path.join(root.PATH, 'blender', 'generated')

    blender = Blender(blender_executable)

    program = common.Program(blend_path = '', result_path = '', blender_executable = '', report_path = os.path.join(generated_dir, 'report.json'))

    program.run(blender, write_image_settings, os.path.join(generated_dir, 'render_settings.py'))
    program.run(blender, write_fbx_settings, os.path.join(generated_dir, 'fbx_settings.py'))
    program.run(blender, write_gltf_settings, os.path.join(generated_dir, 'gltf_settings.py'))
    program.run(blender, write_obj_settings, os.path.join(generated_dir, 'obj_settings.py'))

    program.execute()
