import typing
import itertools
import operator
import collections
import math

import bpy

from .. import tool_settings

from . import bpy_context


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

    TODO: there is an extra processing which this code does not cover
    it will give incorrect results in corner cases
    """

    armature_space_matrix = armature.matrix_world.inverted() @ mesh.matrix_world

    for name, sub_bone_names in bendy_bone_to_segments.items():

        index_to_group = [mesh.vertex_groups.new(name=name) for name in sub_bone_names]

        bone_vertex_group = mesh.vertex_groups[name]
        pose_bone = armature.pose.bones[name]

        for vert in mesh.data.vertices:

            if not any(bone_vertex_group.index == g.group for g in vert.groups):
                continue

            weight = bone_vertex_group.weight(vert.index)

            index: int
            index, blend_next = pose_bone.bbone_segment_index(armature_space_matrix @ vert.co)

            if index + 1 == len(index_to_group):
                index_to_group[index].add([vert.index], weight, 'REPLACE')
            else:
                index_to_group[index].add([vert.index], weight * (1 - blend_next), 'REPLACE')
                index_to_group[index + 1].add([vert.index], weight * blend_next, 'REPLACE')


def create_simplified_armature_and_constrain(armature: bpy.types.Object, mesh: bpy.types.Object):


    new = armature.copy()
    new.data = armature.data.copy()


    new.animation_data_clear()
    new.id_properties_clear()

    new.data.animation_data_clear()
    new.data.id_properties_clear()


    new.data.display_type = 'BBONE'
    new.data.show_bone_custom_shapes = False


    for collection in list(new.data.collections):
        new.data.collections.remove(collection)

    regular_bone_collection = new.data.collections.new("Deform")
    bendy_bone_collection = new.data.collections.new("Deform Bendy Bones")


    for bone in new.pose.bones:
        for constraint in list(bone.constraints):
            bone.constraints.remove(constraint)


    bendy_bone_to_segments: typing.Dict[str, typing.List[str]] = collections.defaultdict(list)


    with bpy_context.Focus_Objects(new, 'EDIT'):

        for bone in new.data.edit_bones:

            if not bone.use_deform:
                continue

            if bone.bbone_segments == 1:

                regular_bone_collection.assign(bone)

                bone.use_local_location = True
                bone.use_inherit_rotation = True
                bone.inherit_scale = 'FULL'

                bone.id_properties_clear()

            else:

                for index in range(bone.bbone_segments):

                    segment = new.data.edit_bones.new(bone.name + '.BB')

                    segment.matrix = bone.matrix @ new.pose.bones[bone.name].bbone_segment_matrix(index, rest=True)

                    segment.length = bone.length / bone.bbone_segments
                    segment.bbone_x = bone.bbone_x
                    segment.bbone_z = bone.bbone_z

                    bendy_bone_collection.assign(segment)
                    bendy_bone_to_segments[bone.name].append(segment.name)


        for bone in list(new.data.edit_bones):
            if not bone.use_deform:
                new.data.edit_bones.remove(bone)

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

        bone.id_properties_clear()


        subtarget = armature.data.bones[bone.name].name

        segment_names = bendy_bone_to_segments.get(bone.name)
        if not segment_names:

            constraint: bpy.types.CopyTransformsConstraint = bone.constraints.new('COPY_TRANSFORMS')
            constraint.target = armature
            constraint.subtarget = subtarget

            continue

        for index, name in enumerate(segment_names):

            segment = new.pose.bones[name]

            constraint: bpy.types.CopyTransformsConstraint = segment.constraints.new('COPY_TRANSFORMS')
            constraint.target = armature
            constraint.subtarget = subtarget
            constraint.head_tail = index / len(segment_names)
            constraint.use_bbone_shape = True

            constraint: bpy.types.DampedTrackConstraint = segment.constraints.new('DAMPED_TRACK')
            constraint.target = armature
            constraint.subtarget = subtarget
            constraint.head_tail = index / (len(segment_names) - 1)
            constraint.use_bbone_shape = True

            if index == 0:
                constraint.head_tail = 0.0001


    with bpy_context.Bpy_State() as state:

        state.set(armature.data, 'pose_position','REST')

        with bpy_context.Focus_Objects(new, 'POSE'):
            bpy.ops.pose.reveal()
            bpy.ops.pose.select_all(action='DESELECT')
            for bone in new.data.bones:
                bone.select = bone.name in bendy_bone_replacements
            bpy.ops.pose.armature_apply(selected=True)

        if mesh:
            assign_bendy_bone_segments_weights(armature, mesh, bendy_bone_to_segments)


    with bpy_context.Focus_Objects(new, 'EDIT'):
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


    with bpy_context.Focus_Objects(objects), bpy_context.Bpy_State() as state:

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
