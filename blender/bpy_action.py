import typing
import itertools
import operator
import collections
import math
import heapq


import bpy
import bmesh
import mathutils

from .. import tool_settings

from . import bpy_context
from . import bpy_utils


if typing.TYPE_CHECKING:
    # We only need __init__ hints.
    # dataclass has special meaning for Python type checkers.
    import dataclasses
else:
    class dataclasses:
        dataclass = lambda x: x


def assign_bendy_bone_segments_weights(armature: bpy.types.Object, mesh: bpy.types.Object, bendy_bone_to_segments: typing.Dict[str, typing.List[str]]):
    """
    Expects the armature in the rest pose.
    """

    map_vertex_to_group = {vert.index: set(map(operator.attrgetter('group'), vert.groups)) for vert in mesh.data.vertices}

    armature_space_matrix = armature.matrix_world.inverted() @ mesh.matrix_world

    for name, sub_bone_names in bendy_bone_to_segments.items():

        bone_vertex_group = mesh.vertex_groups.get(name)
        if not bone_vertex_group:
            continue

        index_to_group = [mesh.vertex_groups.new(name=name) for name in sub_bone_names]

        pose_bone = armature.pose.bones[name]

        group_index = bone_vertex_group.index
        segment_group_index: int

        for vert in mesh.data.vertices:

            if not group_index in map_vertex_to_group[vert.index]:
                continue

            weight = bone_vertex_group.weight(vert.index)

            segment_group_index, blend_next = pose_bone.bbone_segment_index(armature_space_matrix @ vert.co)

            index_to_group[segment_group_index].add([vert.index], weight * (1 - blend_next), 'REPLACE')
            index_to_group[segment_group_index + 1].add([vert.index], weight * blend_next, 'REPLACE')


def create_simplified_armature_and_constrain(armature: bpy.types.Object, deform_root: str, control_root: str = '', meshes: typing.Optional[typing.List[bpy.types.Object]] = None):


    # copy the armature
    new = armature.copy()
    new.data = armature.data.copy()


    # clear animation and custom properties data
    new.animation_data_clear()
    new.id_properties_clear()
    new.data.animation_data_clear()
    new.data.id_properties_clear()


    # set default visualization
    new.data.display_type = 'OCTAHEDRAL'
    new.data.show_bone_custom_shapes = False


    # create bone collections
    for collection in list(new.data.collections):
        new.data.collections.remove(collection)

    regular_bone_collection = new.data.collections.new("Deform")
    bendy_bone_collection = new.data.collections.new("Deform Bendy Bones")


    # delete constrains to avoid missing bones spam
    for bone in new.pose.bones:
        for constraint in list(bone.constraints):
            bone.constraints.remove(constraint)


    # bendy bone to bendy bone segments dictionary
    bendy_bone_to_segments: typing.Dict[str, typing.List[str]] = collections.defaultdict(list)


    # define parenting hierarchy
    with bpy_context.Focus(armature), bpy_context.State() as state:

        state.set(armature.data, 'pose_position','REST')
        armature.update_tag()
        bpy.context.view_layer.update()

        parent_map = get_bone_walk_parent_map(armature, deform_root)


    # convert edit bones
    with bpy_context.Focus(new, 'EDIT'), bpy_context.State() as state:

        state.set(new.data, 'pose_position','REST')
        new.update_tag()
        bpy.context.view_layer.update()


        # get control root bone
        if control_root:
            control_root_bone = new.data.edit_bones[control_root]
        else:
            control_root_bone = None


        # unset bones' data
        for bone in new.data.edit_bones:

            if not (bone.use_deform or bone == control_root_bone):  # other bones will be deleted anyway
                continue

            regular_bone_collection.assign(bone)

            bone.use_connect = False  # if not False will move bones while assigning parents
            bone.parent = None  # if not None circular parenting assignments will be ignored

            bone.use_local_location = True
            bone.use_inherit_rotation = True
            bone.inherit_scale = 'FULL'

            bone.display_type = 'ARMATURE_DEFINED'
            bone.color.palette = 'DEFAULT'

            bone.id_properties_clear()


        # assign deform bones parents
        for child, parent in parent_map.items():
            new.data.edit_bones[child].parent = new.data.edit_bones[parent]


        # assign control root bone
        if control_root_bone:
            for bone in new.data.edit_bones:
                if bone.use_deform and not bone.parent:
                    bone.parent = control_root_bone


        # create bendy bone segments
        for bone in new.data.edit_bones:

            if not bone.use_deform:
                continue

            if bone.bbone_segments == 1:
                continue

            prev_segment = None

            for index in range(bone.bbone_segments + 1):

                segment = new.data.edit_bones.new(bone.name + '.BB')

                segment.length = bone.length / bone.bbone_segments
                segment.bbone_x = bone.bbone_x
                segment.bbone_z = bone.bbone_z

                bendy_bone_collection.assign(segment)
                bendy_bone_to_segments[bone.name].append(segment.name)

                if index == 0:
                    segment.parent = bone.parent
                elif index == bone.bbone_segments:
                    for child in bone.children:
                        child.use_connect = False
                        child.parent = segment

                if prev_segment:
                    segment.parent = prev_segment

                prev_segment = segment

                segment.matrix = bone.matrix @ new.pose.bones[bone.name].bbone_segment_matrix(index, rest=True)


        # delete non deform bones
        for bone in list(new.data.edit_bones):

            if bone.use_deform or bone == control_root_bone:
                continue

            new.data.edit_bones.remove(bone)


    # assign bone constrains
    bendy_bone_replacements = set(itertools.chain.from_iterable(map(operator.itemgetter(1), bendy_bone_to_segments.items())))

    for bone in new.pose.bones:

        if bone.name in bendy_bone_replacements:
            continue


        bone.lock_location = (False, False, False)
        bone.lock_rotation = (False, False, False)
        bone.lock_rotations_4d = False
        bone.lock_rotation_w = False
        bone.lock_scale = (False, False, False)

        bone.custom_shape = None
        bone.color.palette = 'DEFAULT'

        bone.id_properties_clear()


        subtarget = armature.data.bones[bone.name].name

        segment_names = bendy_bone_to_segments.get(bone.name)
        if not segment_names:

            constraint: bpy.types.CopyTransformsConstraint = bone.constraints.new('COPY_TRANSFORMS')
            constraint.target = armature
            constraint.subtarget = subtarget

            continue

        for index, name in enumerate(segment_names):

            copy_transforms: bpy.types.CopyTransformsConstraint = new.pose.bones[name].constraints.new('COPY_TRANSFORMS')
            copy_transforms.target = armature
            copy_transforms.subtarget = subtarget
            copy_transforms.head_tail = index / (len(segment_names) - 1)
            copy_transforms.use_bbone_shape = True


    # transfer bendy bone segment weights
    if meshes and bendy_bone_to_segments:

        with bpy_context.State() as state:

            state.set(armature.data, 'pose_position','REST')

            for mesh in bpy_utils.get_unique_mesh_objects(meshes):
                assign_bendy_bone_segments_weights(armature, mesh, bendy_bone_to_segments)


    # remove converted bendy bones
    with bpy_context.Focus(new, 'EDIT'):
        for name in bendy_bone_to_segments:
            new.data.edit_bones.remove(new.data.edit_bones[name])


    return new


def reset_pose_to_rest(object: bpy.types.Object):

    if object.type != 'ARMATURE':
        return

    for bone in object.pose.bones:
        bone.location = (0, 0, 0)
        bone.rotation_quaternion = (1, 0, 0, 0)
        bone.rotation_axis_angle = (0, 0, 1, 0)
        bone.rotation_euler = (0, 0, 0)
        bone.scale = (1, 1, 1)


def move_action_keys_to_frame(action: bpy.types.Action, frame = 0):

    for fc in action.fcurves:

        if not fc.keyframe_points:
            continue

        min_keyframe = min(fc.keyframe_points, key = lambda x: x.co[0])
        offset = min_keyframe.co[0] - frame

        for keyframe in fc.keyframe_points:
            keyframe.co_ui[0] -= offset


@dataclasses.dataclass
class S_Action_Bake(tool_settings.Settings):


    only_selected: bool = False
    """
    Only bake selected bones.
    Only key selected bones (Pose baking only)

    #### Default: `False`
    """

    do_pose: bool = True
    """
    Bake pose channels.
    Bake bones transformations.

    #### Default: `True`
    """

    do_object: bool = False
    """
    Bake objects.
    Bake object transformations.

    #### Default: `False`
    """

    do_visual_keying: bool = True
    """
    Use the final transformations for baking ('visual keying').
    Keyframe from the final transformations (with constraints applied).

    #### Default: `True`
    """

    do_constraint_clear: bool = False
    """
    Remove all constraints from keyed object/bones after baking.
    To get a correct bake with this setting Visual Keying should be enabled.

    #### Default: `False`
    """

    do_parents_clear: bool = False
    """
    Unparent after baking objects.
    Bake animation onto the object then clear parents (objects only).

    #### Default: `False`
    """

    do_clean: bool = True
    """
    Remove redundant keyframes after baking.
    After baking curves, remove redundant keys.

    #### Default: `True`
    """

    do_location: bool = True
    """
    Bake location channels.

    #### Default: `True`
    """

    do_rotation: bool = True
    """
    Bake rotation channels.

    #### Default: `True`
    """

    do_scale: bool = True
    """
    Bake scale channels.

    #### Default: `True`
    """

    do_bbone: bool = True
    """
    Bake B-Bone channels.

    #### Default: `True`
    """

    do_custom_props: bool = True
    """
    Bake custom properties.

    #### Default: `True`
    """


def bake_actions(
        source_object_action_pairs: typing.List[typing.Tuple[bpy.types.Object, bpy.types.Action]],
        target_object_action_pairs: typing.List[typing.Tuple[bpy.types.Object, bpy.types.Action]],
        frame_start: typing.Optional[int] = None,
        frame_end: typing.Optional[int] = None,
        step = 1,
        do_reset_pose_to_rest = False,
        settings: S_Action_Bake = None
    ):
    """ https://github.com/blender/blender/blob/a3f04f9f0d24ae8eb59faa1e6c43ff41a4f74d4a/scripts/startup/bl_operators/anim.py#L274 """


    objects = list(map(operator.itemgetter(0), itertools.chain(source_object_action_pairs, target_object_action_pairs)))


    with bpy_context.Focus(objects), bpy_context.State() as state:

        if do_reset_pose_to_rest:
            for object in objects:
                reset_pose_to_rest(object)

        for object, action in source_object_action_pairs:
            if not object.animation_data:
                object.animation_data_create()
            object.animation_data.action = action

        for object, _ in target_object_action_pairs:
            if not object.animation_data:
                object.animation_data_create()

        if frame_start is None:
            frame_start = int(min(map(lambda pair: pair[1].frame_range[0], source_object_action_pairs)))

        if frame_end is None:
            frame_end = int(max(map(lambda pair: pair[1].frame_range[1], source_object_action_pairs)))


        settings = S_Action_Bake()._update(settings)
        for key in [key for key in S_Action_Bake.__dict__ if not key.startswith('_')]:
            setattr(settings, key, getattr(settings, key))


        from bpy_extras import anim_utils
        baked_actions = anim_utils.bake_action_objects(
            target_object_action_pairs,
            frames = range(frame_start, frame_end + 1, step),
            bake_options = anim_utils.BakeOptions(**settings._to_dict())
        )


        return baked_actions


def bake_single_action(
        source: bpy.types.Object,
        source_action: bpy.types.Action,
        target: bpy.types.Object,
        target_action: typing.Optional[bpy.types.Action] = None,
        do_reset_pose_to_rest = False,
    ):
    return bake_actions([(source, source_action)], [(target, target_action)], do_reset_pose_to_rest= do_reset_pose_to_rest)[0]


def get_assigned_weights_groups(object: bpy.types.Object):
    return {
        object.vertex_groups[group.group].name
        for vert in object.data.vertices
        for group in vert.groups
        if not math.isclose(group.weight, 0, rel_tol=1e-6, abs_tol=1e-6)
    }


def unassign_deform_bones_with_missing_weights(armature: bpy.types.Object, meshes: typing.List[bpy.types.Object]):

    vertex_group_names = set()

    for object in bpy_utils.get_unique_mesh_objects(meshes):
        vertex_group_names.update(get_assigned_weights_groups(object))

    with bpy_context.Focus(armature, 'EDIT'):

        for bone in armature.data.edit_bones:
            if bone.use_deform:
                bone.use_deform = bone.name in vertex_group_names


def get_bone_tree(object: bpy.types.Object):

    def traverse(bone: bpy.types.Bone):
        return [(child.name, traverse(child)) for child in bone.children]

    return ('', [(bone.name, traverse(bone)) for bone in object.data.bones if not bone.parent])


def get_bone_descendants(tree: typing.Tuple[str, typing.List[tuple]], name: str):

    def flatten(value: typing.List[tuple]):

        names = []
        pool = value.copy()

        while pool:
            parent, children = pool.pop()
            names.append(parent)
            pool.extend(children)

        return names

    pool = tree[1].copy()

    while pool:

        parent, children = pool.pop()

        if parent == name:
            return flatten(children)

        pool.extend(children)


def get_bone_walk_mesh(object: bpy.types.Object, step = 0.01):


    points: typing.List[mathutils.Vector] = []
    bone_to_indexes: typing.Dict[str, typing.List[int]] = collections.defaultdict(list)

    _index = 0
    def add_point(point: mathutils.Vector, name: str):
        nonlocal _index
        points.append(point)
        bone_to_indexes[name].append(_index)
        _index += 1
        return _index - 1

    links: typing.Set[typing.FrozenSet[int, int]] = set()
    def add_link(a: int, b: int):
        links.add(frozenset((a, b)))

    deform_bones = {bone.name for bone in object.data.bones if bone.use_deform}

    bone_tree = get_bone_tree(object)

    parent_of_deform = {bone.name for bone in object.data.bones if not deform_bones.isdisjoint(get_bone_descendants(bone_tree, bone.name))}

    deform_or_parent_of_deform = deform_bones | parent_of_deform

    for bone in object.pose.bones:

        if not bone.name in deform_or_parent_of_deform:
            continue

        a = add_point(bone.head, bone.name)
        b = add_point(bone.tail, bone.name)
        add_link(a, b)

    for name, indexes in bone_to_indexes.items():

        if not name in deform_or_parent_of_deform:
            continue

        bone = object.pose.bones[name]

        if bone.parent:
            add_link(bone_to_indexes[bone.parent.name][1], indexes[0])

    bone_to_points = {}
    for name, indexes in bone_to_indexes.items():
        bone_to_points[name] = [points[index] for index in indexes]

    points, links = merge_bone_walk_mesh_by_distance(points, links)

    return points, links, bone_to_points


def merge_bone_walk_mesh_by_distance(points: typing.List[mathutils.Vector], links: typing.List[typing.Tuple[int, int]]):

    mesh = bpy.data.meshes.new("__bc_bone_walk")
    mesh.from_pydata(points, links, [])

    bm = bmesh.new()
    bm.from_mesh(mesh)

    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.0001)

    vertices = list(map(mathutils.Vector, map(operator.attrgetter('co'), bm.verts)))
    edges = set(map(frozenset, (map(operator.attrgetter('index'), verts) for verts in map(operator.attrgetter('verts'), bm.edges))))

    bm.free()

    bpy.data.meshes.remove(mesh)

    return vertices, edges


def create_bone_walk_object(points, links, name = "Bone Walk"):
    """ For debugging. """

    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(points, links, [])

    object = bpy.data.objects.new(name, mesh)

    bpy.context.scene.collection.objects.link(object)

    return object


def get_bone_walk_graph(points: typing.List[mathutils.Vector], links: typing.List[typing.Tuple[int, int]]):

    graph: typing.Dict[int, typing.Dict[int, float]] = collections.defaultdict(dict)

    for a, b in links:
        graph[a][b] = graph[b][a] = (points[a] - points[b]).length

    return graph


def get_shortest_bone_walk_path(graph: typing.Dict[int, typing.Dict[int, float]], start_index: int, end_index: int):

    INFINITY = float('inf')

    distances = {}
    links = {}

    queue = [(0, start_index)]
    distances[start_index] = 0

    while queue:

        distance, index = heapq.heappop(queue)

        if distance > distances.get(index, INFINITY):
            continue

        if index == end_index:
            break

        for neighbor, length in graph[index].items():

            new_distance = distance + length

            if new_distance < distances.get(neighbor, INFINITY):
                distances[neighbor] = new_distance
                links[neighbor] = index
                heapq.heappush(queue, (new_distance, neighbor))


    shortest: float = distances.get(end_index, INFINITY)
    path: typing.List[int] = []

    if shortest == INFINITY:
        return shortest, path

    index = end_index
    while index != start_index:
        path.append(index)
        index = links[index]

    path.append(start_index)
    path.reverse()

    return shortest, path


def get_bone_walk_parent_map(object: bpy.types.Object, deform_root: str):


    points, links, bone_to_points = get_bone_walk_mesh(object)
    graph = get_bone_walk_graph(points, links)

    # create_bone_walk_object(points, links)

    kdtree = mathutils.kdtree.KDTree(len(points))

    for i, point in enumerate(points):
        kdtree.insert(point, i)

    kdtree.balance()


    def get_index(point: mathutils.Vector, radius = 0.0001):
        indexes = list(map(operator.itemgetter(1), kdtree.find_range(point, radius)))
        if len(indexes) != 1:
            print(
                f"Unexpected amount of indexes per point: {indexes}"
                "\n\t" f"Point: {point}"
                "\n\t" f"Object: {object.name_full}"
            )
        return indexes[0]


    deform_bones = {bone.name for bone in object.data.bones if bone.use_deform}


    bone_to_indexes = {}
    index_to_bones = collections.defaultdict(list)

    for bone, points in bone_to_points.items():

        if not bone in deform_bones:
            continue

        bone_to_indexes[bone] = list(map(get_index, points))

        for is_tail, index in enumerate(bone_to_indexes[bone]):
            index_to_bones[index].append((bone, is_tail))


    def get_head_index(name: str):
        return get_index(bone_to_points[name][0])


    def get_tail_index(name: str):
        return get_index(bone_to_points[name][1])


    def _get_parent(bone_path: typing.List[list], start: str):
        """ TODO: this does not cover all the corner cases """

        if len(bone_path) == 1:
            bone_path[0].remove((start, 0))
            return bone_path[0][0][0]  # direct child

        a = bone_path[0]
        b = bone_path[1]

        # print(a)
        # print(b)

        if len(a) == len(b) == 1:
            a.remove((start, 0))
            assert not a
            return b[0][0]  # simple disconnected child

        for x in a:
            for y in b:
                if x[0] == y[0]:

                    if x[0] == start:
                        for z in b:
                            if z[0] != start:
                                return z[0] # flipped connected child
                    else:
                        return x[0] # connected child

        for x in a:
            if x[1]:
                return x[0]  # bypassed connected child

        for x in b:
            if x[1]:
                return x[0]  # disconnected child


    def get_parent(name, root_index = get_tail_index(deform_root)):

        path = get_shortest_bone_walk_path(graph, get_head_index(name), root_index)

        bone_path = [index_to_bones.get(i, None) for i in path[1]]
        bone_path = list(filter(None, (bone_path)))

        if not bone_path:
            print(
                f"Unreachable bone: {name}"
                '\n\t' f"Path: {path}"
            )
            return None

        parent_name = _get_parent(bone_path, name)
        assert parent_name != name

        return parent_name


    parent_map: typing.Dict[str, str] = {}


    for bone in object.data.bones:

        if not bone.use_deform:
            continue

        if bone.name == deform_root:
            continue

        parent = get_parent(bone.name)
        if parent:
            parent_map[bone.name] = parent


    return parent_map
