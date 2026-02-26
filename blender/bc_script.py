"""
The content of this module is meant to be directly used to build a conversion pipeline.

```python
from blend_converter.blender import bc_script
program.run(bc_script.some_script)
```

Module Rules:
1. The module must be importable without any site-packages.
2. Function parameters must accept json-serializable arguments.
3. blend_converter itself should not import from this module.

If a object does not adhere to the rules it must be moved into an appropriate `bpy_` file.
"""

import typing
import sys


T = typing.TypeVar('T')

def wraps(func: T) -> typing.Callable[[T], T]:
    return lambda f: f


if 'bpy' in sys.modules:

    import re
    import bpy

    from blend_converter.blender import bpy_context
    from blend_converter.blender import bpy_utils
    from blend_converter.blender import bpy_mesh
    from blend_converter.blender import bpy_modifier
    from blend_converter.blender import bpy_material




if typing.TYPE_CHECKING:
    from typing_extensions import TypeAlias as _TypeAlias
    Objects_Like: _TypeAlias = typing.Union[None, str, typing.Tuple[str, str], bpy.types.Object, typing.Iterable[typing.Union[str, typing.Sequence[str], bpy.types.Object]]]
else:
    Objects_Like = type


def get_objects(objects: Objects_Like) -> typing.List['bpy.types.Object']:
    """
    Get a list of `bpy.types.Object` from different kinds of notations.

    `str`: an object name.
    `bpy.types.Object`: a Blender's Object class instance.
    `typing.Tuple[str, str]`: an object name and a library path.
    """

    if isinstance(objects, str):
        return [bpy.data.objects[objects]]
    elif isinstance(objects, tuple) and objects and isinstance(objects[0], str):
        return [bpy.data.objects[objects[0], objects[1]]]
    elif isinstance(objects, bpy.types.Object):
        return [objects]
    elif objects is None:
        return []
    else:

        bpy_objects: typing.List[bpy.types.Object] = []

        for object in objects:
            if isinstance(object, str):
                bpy_objects.append(bpy.data.objects[object])
            elif isinstance(object, typing.Sequence):
                bpy_objects.append(bpy.data.objects[object[0], object[1]])  # type: ignore
            elif isinstance(object, bpy.types.Object):
                bpy_objects.append(object)
            elif object is None:
                # bpy.context.view_layer.objects can return list containing None
                pass
            else:
                raise Exception(f"Not supported object identity notation: {object}")

        return bpy_objects


def get_objects_fallback(objects: Objects_Like = None):
    """
    Get a list of `bpy.types.Object` from different kinds of notations.

    Same as `get_objects` but with a fallback to `bpy_utils.get_view_layer_objects` if `objects` is `None`.
    """
    if objects is None:
        return bpy_utils.get_view_layer_objects()
    else:
        return get_objects(objects)


def apply_scale(objects: Objects_Like = None):

    objects = get_objects_fallback(objects)

    bpy_utils.make_object_data_unique(objects)

    with bpy_context.Focus(objects):
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)



def add_actions_to_nla(regex: typing.Optional[str] = None):
    """
    Add all associated with the visible armature bones actions to NLA.

    `regex`: `re.search` on `bpy.types.Action.name`
    """

    for object in bpy.data.objects:

        armature = bpy_utils.get_armature(object)
        if not armature:
            return

        if armature.animation_data is None:
            armature.animation_data_create()

        if armature.animation_data.nla_tracks:
            return

        armature_bones_names = set(bpy_utils.get_visible_armature_bones(armature.data))
        if not armature_bones_names:
            return

        actions: typing.List[bpy.types.Action] = [action for action in bpy.data.actions if not armature_bones_names.isdisjoint(bpy_utils.iter_bone_names(action))]

        nla_tracks = armature.animation_data.nla_tracks

        for action in actions:

            if regex is not None and not re.search(regex, action.name):
                continue

            track = nla_tracks.new()
            track.name = action.name
            track.strips.new(action.name, 0, action)


def use_backface_culling():
    """ Set `use_backface_culling` to `True` for all materials. """

    for material in bpy.data.materials:
        material.use_backface_culling = True


def create_default_root_bone():
    """ Create a default root bone and an according weight group to prevent a faulty armature handling by the gltf exporter. """

    def get_armatures(object: bpy.types.Object):
        return  [modifier.object for modifier in object.modifiers if isinstance(modifier, bpy.types.ArmatureModifier) and modifier.object]

    def are_all_vertices_have_groups(object: bpy.types.Object, bone_names: set[str]):
        return all(not set(object.vertex_groups[group.group].name for group in v.groups).isdisjoint(bone_names) for v in object.data.vertices)

    def get_bone_names(armature: bpy.types.Object):
        return {bone.name for bone in armature.pose.bones}

    def create_root_vertex_group(object: bpy.types.Object, bone_names: set[str], root_bone_name: str):
        default_group = object.vertex_groups.new(name = root_bone_name)
        default_group.add([v.index for v in object.data.vertices if set(object.vertex_groups[group.group].name for group in v.groups).isdisjoint(bone_names)], 1, 'ADD')

    def deselect_all():
        for object in filter(None, bpy.context.view_layer.objects):
            object.select_set(False)

    for object in filter(None, bpy.context.view_layer.objects):

        if not isinstance(object.data, bpy.types.Mesh):
            continue

        armatures = get_armatures(object)
        if not armatures:
            continue

        for armature in armatures:

            bone_names = get_bone_names(armature)

            if are_all_vertices_have_groups(object, bone_names):
                continue

            root_bone_name = f"{armature.name}_default_root_bone"

            create_root_vertex_group(object, bone_names, root_bone_name)

            deselect_all()
            armature.select_set(True)
            bpy.context.view_layer.objects.active =armature

            bpy.ops.object.mode_set(mode='EDIT', toggle=False)

            edit_bones = armature.data.edit_bones

            root_bone = edit_bones.new(root_bone_name)
            root_bone.head = (0, 0, 1)
            root_bone.tail = (0, 0, 0)

            for bone in edit_bones:
                if not bone.parent:
                    bone.parent = root_bone

            bpy.ops.object.mode_set(mode='OBJECT', toggle=False)


def make_materials_unique(objects: Objects_Like):
    """ Make a unique copy of a material for each material slot of an object. """
    for object in get_objects(objects):
        bpy_material.make_materials_unique(object)


def remove_all_node_groups_from_materials():
    """
    the gltf exporter's method of nodes inspection takes an absurd amount of time
    https://github.com/KhronosGroup/glTF-Blender-IO/issues/2356
    Finished glTF 2.0 export in 294.57832312583923 s
    Finished glTF 2.0 export in 0.05988144874572754 s

    > TODO: cache these searches
    https://github.com/KhronosGroup/glTF-Blender-IO/blob/cee66f781491c0e65ea3d65f465a445333788bd7/addons/io_scene_gltf2/blender/exp/material/search_node_tree.py#L71

    > For now, not caching it. If we encounter performance issue, we will see later
    https://github.com/KhronosGroup/glTF-Blender-IO/blob/cee66f781491c0e65ea3d65f465a445333788bd7/addons/io_scene_gltf2/blender/exp/material/search_node_tree.py#L159
    """

    for material in bpy.data.materials:

        if not material.node_tree:
            continue

        nodes = material.node_tree.nodes

        for node in nodes:
            if node.bl_idname == 'ShaderNodeGroup' and not 'glTF Settings' in node.name:
                nodes.remove(node)


def remove_vertex_colors(objects: Objects_Like = None):

    for object in get_objects_fallback(objects):

        data = object.data
        if not isinstance(data, bpy.types.Mesh):
            continue

        vertex_color_names = [vertex_color.name for vertex_color in data.vertex_colors]
        for name in vertex_color_names:
            data.vertex_colors.remove(data.vertex_colors[name])  # type: ignore


def ensure_debugpy():

    from . import ensure_site_packages
    import site
    ensure_site_packages.ensure_site_packages([('debugpy', 'debugpy')], directory=site.getusersitepackages())


def reset_ui_layout():
    """ A workaround to reset the blend file UI layout. """

    filepath = bpy.data.filepath
    bpy.ops.wm.read_homefile(app_template="")

    try:
        bpy.ops.wm.open_mainfile(filepath = filepath, load_ui=False)
    except RuntimeError as e:
        print(e)


def scene_clean_up():
    """ Remove all objects and collection starting from `#` and purge unused. """

    for object in list(bpy.data.objects):
        if object.name.startswith('#'):
            bpy.data.objects.remove(object)

    for layer in list(bpy.context.view_layer.layer_collection.children):

        if layer.collection.name.startswith('#'):

            bpy.data.batch_remove(set(layer.collection.all_objects))
            bpy.data.collections.remove(layer.collection)

        elif layer.exclude:
            layer.exclude = False

    bpy.ops.outliner.orphans_purge()


@wraps(bpy_mesh.bisect_by_mirror_modifiers if typing.TYPE_CHECKING else object)
def bisect_by_mirror_modifiers(objects: Objects_Like):
    for object in get_objects(objects):
        bpy_mesh.bisect_by_mirror_modifiers(object)


def clean_up_topology_and_triangulate_ngons(objects: Objects_Like = None, split_concave_faces = True, tris_to_quads = True):
    """ The Ministry of Flat unwrapping can produce bad results if ngons or loose geometry is present. """

    objects = get_objects_fallback(objects)

    for object in bpy_utils.get_unique_mesh_objects(objects):

        with bpy_context.Focus(object):

            with bpy_context.Focus(object, mode = 'EDIT'):
                bpy.ops.mesh.reveal()
                bpy.ops.mesh.select_all(action='SELECT')
                bpy.ops.mesh.delete_loose()
                bpy.ops.mesh.select_all(action='SELECT')
                bpy.ops.mesh.dissolve_degenerate()

            bpy_modifier.apply_triangulate(object, keep_custom_normals = True, min_vertices = 5)

            if split_concave_faces or tris_to_quads:
                with bpy_context.Focus(object, mode = 'EDIT'):
                    bpy.ops.mesh.select_all(action='SELECT')
                    if tris_to_quads:
                        # TODO: ideally should be applied only to the former ngons
                        bpy.ops.mesh.tris_convert_to_quads(uvs=True, vcols=True, seam=True, sharp=True, materials=True)
                    if split_concave_faces:
                        # might not be necessary but just in case
                        bpy.ops.mesh.vert_connect_concave()


def do_nothing(*args, **kwargs):
    pass


def select_uv_layer(objects: Objects_Like, name: str,):

    for object in get_objects(objects):
        if hasattr(object.data, 'uv_layers'):
            index = object.data.uv_layers.find(name)
            if index >= 0:
                object.data.uv_layers.active_index = index


def get_uuid1_hex(prefix = '__bc_'):
    import uuid
    return prefix + uuid.uuid1().hex
