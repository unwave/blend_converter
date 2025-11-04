""" Utilities for working with modifiers. """


import bpy
import math
import os

from . import bpy_context


def apply_modifier(modifier: bpy.types.Modifier):
    object = modifier.id_data
    print(modifier.name + "...")
    bpy_context.call_for_object(object, bpy.ops.object.modifier_apply, modifier = modifier.name, single_user = True)


def apply_collapse(object: bpy.types.Object, ratio: float):
    modifier: bpy.types.DecimateModifier = object.modifiers.new(name = '_', type='DECIMATE')
    modifier.decimate_type = 'COLLAPSE'
    modifier.ratio = ratio
    modifier.use_collapse_triangulate = True

    modifier.name = modifier.type + ' ' + modifier.decimate_type
    apply_modifier(modifier)


def apply_dissolve(object: bpy.types.Object, degrees: float):
    modifier: bpy.types.DecimateModifier = object.modifiers.new(name = '_', type='DECIMATE')
    modifier.decimate_type = 'DISSOLVE'
    modifier.angle_limit = math.radians(degrees)

    modifier.name = modifier.type + ' ' + modifier.decimate_type
    apply_modifier(modifier)


def apply_shrinkwrap(object: bpy.types.Object, target: bpy.types.Object):
    modifier: bpy.types.ShrinkwrapModifier = object.modifiers.new(name = '_', type='SHRINKWRAP')
    modifier.target = target

    modifier.name = modifier.type
    apply_modifier(modifier)


def apply_weld(object: bpy.types.Object, merge_threshold: float):
    modifier: bpy.types.WeldModifier = object.modifiers.new(name = '_', type='WELD')
    modifier.merge_threshold = merge_threshold
    modifier.mode = 'CONNECTED'

    modifier.name = modifier.type + ' ' + modifier.mode
    apply_modifier(modifier)


def apply_weighted_normal(object: bpy.types.Object, keep_sharp = False, mode = 'FACE_AREA'):
    modifier: bpy.types.WeightedNormalModifier = object.modifiers.new(name = '_', type='WEIGHTED_NORMAL')
    modifier.keep_sharp = keep_sharp
    modifier.mode = mode

    modifier.name = modifier.type
    apply_modifier(modifier)


def apply_solidify(object: bpy.types.Object, thickness: float):
    modifier: bpy.types.SolidifyModifier = object.modifiers.new(name = '_', type='SOLIDIFY')
    modifier.thickness = thickness

    modifier.name = modifier.type
    apply_modifier(modifier)


def apply_displace(object: bpy.types.Object, strength: float):
    modifier: bpy.types.DisplaceModifier = object.modifiers.new(name = '_', type='DISPLACE')
    modifier.strength = strength

    modifier.name = modifier.type
    apply_modifier(modifier)


def apply_remesh(object: bpy.types.Object, voxel_size: float):
    modifier: bpy.types.RemeshModifier = object.modifiers.new(name = '_', type='REMESH')
    modifier.mode = 'VOXEL'
    modifier.voxel_size = voxel_size

    modifier.name = modifier.type
    apply_modifier(modifier)


def apply_triangulate(object: bpy.types.Object):
    modifier: bpy.types.TriangulateModifier = object.modifiers.new(name = '_', type='TRIANGULATE')
    modifier.quad_method = 'BEAUTY'
    modifier.ngon_method = 'BEAUTY'

    modifier.name = modifier.type
    apply_modifier(modifier)


def apply_smooth_by_angle(object: bpy.types.Object, degrees: float):
    """ https://projects.blender.org/blender/blender/issues/117399 """

    node_group_name = 'Smooth by Angle'

    node_group = bpy.data.node_groups.get(node_group_name)
    if not node_group:
        path = os.path.join(
            os.path.dirname(bpy.app.binary_path),
            f'{bpy.app.version[0]}.{bpy.app.version[1]}',
            'datafiles', 'assets', 'geometry_nodes', 'smooth_by_angle.blend'
        )
        with bpy.data.libraries.load(path) as (data_from, data_to):
            data_to.node_groups = [node_group_name]

        node_group = data_to.node_groups[0]

    modifier: bpy.types.NodesModifier = object.modifiers.new(name = '_', type = 'NODES')
    modifier.node_group = node_group
    modifier['Input_1'] = math.radians(degrees)  # Angle
    modifier['Socket_1'] = True  # Ignore Sharp


    modifier.name = node_group_name
    apply_modifier(modifier)
