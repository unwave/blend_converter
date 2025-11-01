import textwrap
import typing
import os
import importlib
import importlib.util
import sys


INDENT = ' ' * 4

IMPORTS = """
import typing


if __spec__.name == __name__:
    from blend_converter import tool_settings
else:
    from .... import tool_settings


if typing.TYPE_CHECKING:
    import dataclasses
else:
    class dataclasses:
        dataclass = lambda x: x
"""

CLASS_DECORATOR = '@dataclasses.dataclass'


def get_class_signature(name: str):
    return fr'class {name}(tool_settings.Settings):'


def get_class_lines(name: str, docs_string: str, properties: object):

    from blend_converter.blender import type_utils

    lines = []

    lines.append(CLASS_DECORATOR)
    lines.append(get_class_signature(name))
    lines.append(textwrap.indent(f'""" {docs_string} """', INDENT))
    lines.append('')
    lines.append('')
    lines.append(textwrap.indent(type_utils.get_docs_from_properties(properties), INDENT))

    return lines


def write_settings(file_path: str):

    import bpy

    lines = []

    lines.append(IMPORTS)
    lines.append('')
    lines.append('')

    lines.extend(get_class_lines('Settings_Image', "`bpy.context.scene.render.image_settings`", bpy.context.scene.render.image_settings.bl_rna.properties))
    lines.extend(get_class_lines('Settings_Render', "`bpy.context.scene.render`", bpy.context.scene.render.bl_rna.properties))
    lines.extend(get_class_lines('Settings_Cycles', "`bpy.context.scene.cycles`", bpy.context.scene.cycles.bl_rna.properties))
    lines.extend(get_class_lines('Settings_Eevee', "`bpy.context.scene.eevee`", bpy.context.scene.eevee.bl_rna.properties))
    lines.extend(get_class_lines('Settings_View', "`bpy.context.scene.view_settings`", bpy.context.scene.view_settings.bl_rna.properties))


    with open(file_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines).strip() + '\n')


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


LIB_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
BLEND_CONVERTER_INIT_PY = os.path.join(LIB_ROOT_DIR, '__init__.py')


if __name__ == '__main__':

    if typing.TYPE_CHECKING:
        import blend_converter
    else:
        blend_converter = import_module_from_file(BLEND_CONVERTER_INIT_PY, 'blend_converter')

    from blend_converter import utils

    if 'bpy' in sys.modules:
        current_dir = os.path.dirname(os.path.realpath(__file__))
        file_path = os.path.join(current_dir, '_generated.py')

        write_settings(file_path)

    else:

        if len(sys.argv) == 1:
            blender_executable = input("Enter Blender executable path:")
        else:
            blender_executable = sys.argv[1]

        utils.run_blender(blender_executable, ['--python', os.path.realpath(__file__)])
