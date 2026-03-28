""" Utilities for `bpy.data` and blend files.  """

import os
import typing


from .. import common
from .. import utils


from . import blend_inspector


if utils.is_in_blender():

    import bpy

elif not typing.TYPE_CHECKING:

    bpy = utils.Dummy()



def load_compositor_node_tree(name: str) -> bpy.types.CompositorNodeTree:

    data_file = os.path.join(common.ROOT_DIR, 'blender', 'blends', 'compositor_node_groups_2_93.blend')

    node_group = bpy.data.node_groups.get(name)
    if node_group:
        return node_group

    with bpy.data.libraries.load(data_file) as (data_from, data_to):
        data_to.node_groups = [name]

    node_group = data_to.node_groups[0]

    if not node_group:
        raise Exception(f"Fail to load: {name}")

    return node_group


def open_mainfile(filepath: str, load_ui = True, use_scripts = False):

    try:
        bpy.ops.wm.open_mainfile(filepath=filepath, load_ui=load_ui, use_scripts=use_scripts)
    except RuntimeError as e:
        print(e)

    blend_inspector.inspect_if_has_identifier(blend_inspector.COMMON.INSPECT_BLEND_OPEN)


def save_as_mainfile(filepath: str, compress = True, relative_remap = True, copy = False):

    if bpy.app.version >= (2, 80):
        bpy.context.preferences.use_preferences_save = False
        bpy.context.preferences.filepaths.save_version = 0
    else:
        bpy.context.user_preferences.filepaths.save_version = 0

    if (
                bpy.data.filepath
                and
                os.path.exists(filepath)
                and
                os.path.exists(bpy.data.filepath)
                and
                os.path.samefile(filepath, bpy.data.filepath)
            ):
        raise Exception(f"Should not save the blend file in the same location: {filepath}")

    os.makedirs(os.path.dirname(filepath), exist_ok = True)

    try:
        bpy.ops.wm.save_as_mainfile(filepath=filepath, compress=compress, relative_remap=relative_remap, copy=copy)
    except RuntimeError as e:
        if 'Unable to pack file' in str(e):
            pass
        elif "has an invalid 'from' pointer (0000000000000000), it will be deleted" in str(e):
            # https://projects.blender.org/blender/blender/issues/111905
            pass
        else:
            raise e

    print(f"Blend is saved in path: {filepath}")
