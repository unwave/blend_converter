""" Utilities for `bpy.data` and blend files.  """

import bpy
import os

from .. import common


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
