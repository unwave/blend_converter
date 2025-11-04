""" Utilities for mesh objects. """

import bpy
import bmesh
import typing

from . import bpy_context
from . import bpy_utils
from . import bpy_modifier


def create_object_from_selected_edit_mode_geometry():

    objects_in_edit_mode = [o for o in bpy.context.selected_objects if o.mode == 'EDIT']
    if not objects_in_edit_mode:
        raise Exception("No objects in edit mode.")

    objects_in_edit_mode = [o.copy() for o in objects_in_edit_mode]

    with bpy_context.Focus_Objects(objects_in_edit_mode):

        new_object = bpy.data.objects.new('collision_shape', bpy.data.meshes.new(name='collision_shape'))

        merged_object = bpy_utils.merge_objects(bpy_utils.convert_to_mesh(objects_in_edit_mode), merge_into=new_object)

        with bpy_context.Focus_Objects(merged_object, 'EDIT'):

            bm = bmesh.from_edit_mesh(merged_object.data)

            bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.select], context='VERTS')

            bmesh.update_edit_mesh(merged_object.data)

    return merged_object


def create_object_from_selected_objects():

    selected_objects_copy = [o.copy() for o in bpy.context.selected_objects]
    if not selected_objects_copy:
        raise Exception("No selected objects.")

    with bpy_context.Focus_Objects(selected_objects_copy):

        new_object = bpy.data.objects.new('collision_shape', bpy.data.meshes.new(name='collision_shape'))

        merged_object = bpy_utils.merge_objects(bpy_utils.convert_to_mesh(selected_objects_copy), merge_into=new_object)


    return merged_object


def copy_object(object: bpy.types.Object, name: str):

    copy = object.copy()
    bpy.context.scene.collection.objects.link(copy)
    copy.name = name
    copy.data = object.data.copy()
    copy.data.name = name

    return copy


def get_decimated_copy(high_poly: bpy.types.Object, target_triangles = 15000, steps = 3, keep_sharp_edges = False):


    def get_ratio(object: bpy.types.Object, target_triangles):
        return target_triangles / len(object.data.loop_triangle_polygons)


    low_poly = copy_object(high_poly, high_poly.name + 'decimated_copy')

    bpy_context.call_for_object(low_poly, bpy.ops.object.shade_smooth, keep_sharp_edges = keep_sharp_edges)

    # TODO: edge mask protected decimation as a first stage, may give better results

    bpy_modifier.apply_weld(low_poly, 0.001)


    for i in range(steps):
        print(f"Step: {i + 1}/{steps}")
        middle_triangle_count = (len(low_poly.data.loop_triangle_polygons) + target_triangles)/2
        print(f"Triangle count: {len(low_poly.data.loop_triangle_polygons)}")
        print(f"Collapsing to: {round(middle_triangle_count)} (50%)")
        bpy_modifier.apply_collapse(low_poly, get_ratio(low_poly, middle_triangle_count))
        bpy_modifier.apply_shrinkwrap(low_poly, high_poly)
        bpy_modifier.apply_dissolve(low_poly, 5)


    bpy_modifier.apply_collapse(low_poly, get_ratio(low_poly, target_triangles))

    bpy_modifier.apply_triangulate(low_poly)
    bpy_modifier.apply_weld(low_poly, 0.02)


    with bpy_context.Focus_Objects(low_poly, mode='EDIT'):
        bpy.ops.mesh.select_mode(use_extend=False, use_expand=False, type='VERT')
        bpy.ops.mesh.reveal()
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.delete_loose(use_faces=True)
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.dissolve_degenerate()


    return low_poly


def make_bake_cage(object: bpy.types.Object, cage_offset = 0.15, voxel_size = 0.02, number_of_steps = 3, solid_guide_object: typing.Optional[bpy.types.Object] = None):


    bake_cage = copy_object(object, '__bc_cage')

    if solid_guide_object:
        guide_cage = copy_object(solid_guide_object, '__bc_cage_guide')
    else:
        guide_cage = copy_object(object, '__bc_cage_guide')
        bpy_modifier.apply_solidify(guide_cage, voxel_size * 2)  # TODO: a better way to make it solid for the remesh to work


    bpy_modifier.apply_remesh(guide_cage, voxel_size)


    for i in range(number_of_steps):

        print(f"Step: {i + 1}/{number_of_steps}")

        bpy_modifier.apply_displace(guide_cage, cage_offset / number_of_steps)
        bpy_modifier.apply_remesh(guide_cage, voxel_size)


        smooth: bpy.types.CorrectiveSmoothModifier = bake_cage.modifiers.new(name = 'CORRECTIVE_SMOOTH', type='CORRECTIVE_SMOOTH')
        smooth.rest_source = 'BIND'
        smooth.use_pin_boundary = True
        bpy_context.call_for_object(bake_cage, bpy.ops.object.correctivesmooth_bind, modifier=smooth.name)

        shrinkwrap: bpy.types.ShrinkwrapModifier = bake_cage.modifiers.new(name = 'SHRINKWRAP', type='SHRINKWRAP')
        shrinkwrap.target = guide_cage
        bpy_utils.move_modifier_to_first(shrinkwrap)

        bpy_utils.convert_to_mesh(bake_cage)


    bpy.data.objects.remove(guide_cage)

    return bake_cage
