"""
The content of this module is meant to be directly used to build a conversion pipeline.

```python
from blend_converter import bc_script
model.run(bc_script.some_script)
```

Module Rules:
1. The module must be importable without any site-packages.
2. Function parameters must accept json-serializable arguments.
3. blend_converter itself should not import from this module.

If a object does not adhere to the rules it must be moved into an appropriate `bpy_` file.
"""

import typing
import sys


if 'bpy' in sys.modules:

    import re
    import bpy
    import mathutils

    from blend_converter import bpy_context
    from blend_converter import bpy_utils



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


def get_view_layer_objects():
    return bpy_utils.get_view_layer_objects()


def get_objects_fallback(objects: Objects_Like = None):
    """
    Get a list of `bpy.types.Object` from different kinds of notations.

    Same as `get_objects` but with a fallback to `get_view_layer_objects` if `objects` is `None`.
    """
    if objects is None:
        return get_view_layer_objects()
    else:
        return get_objects(objects)


def duplicates_make_real():
    """ Convert particles to objects. """

    if bpy.app.version > (2,80,0):
        select_func = lambda object: object.select_set(True)
    else:
        select_func = lambda object: setattr(object, 'select', True)

    for object in get_view_layer_objects():

        if not any(modifier for modifier in object.modifiers if modifier.type == 'PARTICLE_SYSTEM' and modifier.show_viewport):
            continue

        bpy.ops.object.select_all(action='DESELECT')
        select_func(object)

        bpy.ops.object.duplicates_make_real()


def apply_scale(objects: Objects_Like = None):
    """ Apply object scale, non uniform scale cause bugs in bullet physics. """

    objects = get_objects_fallback(objects)

    if bpy.app.version > (4, 0, 0):  # supports multi-user meshes, but result can be different
        with bpy_context.Focus_Objects(objects):
            bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        return

    for object in objects:

        translation, rotation, scale = object.matrix_basis.decompose()

        scale_matrix = mathutils.Matrix.Diagonal(scale).to_4x4()

        if hasattr(object.data, "transform"):
            object.data.transform(scale_matrix)

        for child in object.children:
            child.matrix_local = scale_matrix @ child.matrix_local

        object.matrix_basis = mathutils.Matrix.Translation(translation) @ rotation.to_matrix().to_4x4()


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

        armature_bones_names = bpy_utils.get_visible_armature_bones(armature)
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


def convert_to_mesh(objects: Objects_Like):
    """ Convert objects to mesh objects using `bpy.ops.object.convert`. """
    return bpy_utils.convert_to_mesh(get_objects(objects))


def make_materials_unique(objects: Objects_Like):
    """ Make a unique copy of a material for each material slot of an object. """
    bpy_utils.make_materials_unique(get_objects(objects))


def make_meshes_unique(objects: Objects_Like = None):
    """ Make a unique copy of a mesh data for each mesh object. """
    bpy_utils.make_meshes_unique(get_objects_fallback(objects))


def focus(objects: Objects_Like = None):
    """
    Deselect, unhide, select and make active the objects according to `bpy.context.view_layer`.

    If `objects` is `None` then all objects will be used.

    Returns the focused objects.
    """
    return bpy_utils.focus(get_objects_fallback(objects))


def delete_objects_not_mentioned(objects: Objects_Like):
    bpy.data.batch_remove(set(bpy.data.objects) - set(get_objects(objects)))


def merge_objects(objects: Objects_Like = None, object_name: str = None):
    """
    `bpy.ops.object.join` the objects.

    If `objects` is `None` then `view_layer.objects` is used.

    Returns the merged object.
    """
    return bpy_utils.merge_objects(objects=get_objects_fallback(objects), object_name=object_name)


def inspect_blend(exit_after = False, executable: typing.Optional[str] = None):
    """ Blocking blend file inspection. """
    bpy_utils.inspect_blend(exit_after=exit_after, blender_executable=executable)


def bake_materials(objects: Objects_Like, image_dir: str, resolution: int, **bake_kwargs):
    bpy_utils.bake_materials(get_objects(objects), image_dir, resolution, **bake_kwargs)


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


def merge_objects_respect_materials(objects: Objects_Like):
    return bpy_utils.merge_objects_respect_materials(get_objects(objects))


def merge_objects_and_bake_materials(objects: Objects_Like, image_dir: str, resolution: int, **extra_settings):
    bpy_utils.merge_objects_and_bake_materials(get_objects(objects), image_dir, resolution, **extra_settings)


def ensure_debugpy():

    from . import ensure_site_packages
    import site
    ensure_site_packages.ensure_site_packages([('debugpy', 'debugpy')], directory=site.getusersitepackages())


def save_blend_as_copy(filepath: str, compress=True):
    bpy.ops.wm.save_as_mainfile(filepath=filepath, copy=True, compress=compress)
