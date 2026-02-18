""" Utilities for mesh objects. """

import typing

import bpy
import bmesh
import mathutils
import math

from . import bpy_context
from . import bpy_utils
from . import bpy_modifier


def create_object_from_selected_edit_mode_geometry():

    objects_in_edit_mode = [o for o in bpy.context.selected_objects if o.mode == 'EDIT']
    if not objects_in_edit_mode:
        raise Exception("No objects in edit mode.")

    objects_in_edit_mode = [o.copy() for o in objects_in_edit_mode]

    with bpy_context.Focus(objects_in_edit_mode):

        new_object = bpy.data.objects.new('collision_shape', bpy.data.meshes.new(name='collision_shape'))

        object = bpy_utils.join_objects(bpy_utils.convert_to_mesh(objects_in_edit_mode), join_into=new_object)

        with bpy_context.Focus(object, 'EDIT'):

            bm = bmesh.from_edit_mesh(object.data)

            bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.select], context='VERTS')

            bmesh.update_edit_mesh(object.data)

    return object


def create_object_from_selected_objects():

    selected_objects_copy = [o.copy() for o in bpy.context.selected_objects]
    if not selected_objects_copy:
        raise Exception("No selected objects.")

    with bpy_context.Focus(selected_objects_copy):

        new_object = bpy.data.objects.new('collision_shape', bpy.data.meshes.new(name='collision_shape'))

        object = bpy_utils.join_objects(bpy_utils.convert_to_mesh(selected_objects_copy), join_into=new_object)


    return object


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


    with bpy_context.Focus(low_poly, mode='EDIT'):
        bpy.ops.mesh.select_mode(use_extend=False, use_expand=False, type='VERT')
        bpy.ops.mesh.reveal()
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.delete_loose(use_faces=True)
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.dissolve_degenerate()


    return low_poly


def make_bake_cage(object: bpy.types.Object, cage_offset_ratio = 0.05, voxel_count = 200, number_of_steps = 3, solid_guide_object: typing.Optional[bpy.types.Object] = None):


    bake_cage = copy_object(object, '__bc_cage')

    if solid_guide_object:
        guide_cage = copy_object(solid_guide_object, '__bc_cage_guide')
    else:
        guide_cage = copy_object(object, '__bc_cage_guide')

    with bpy_context.Focus(guide_cage):
        bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')
        bpy.ops.object.transform_apply()

    dimensions = guide_cage.evaluated_get(bpy.context.evaluated_depsgraph_get()).dimensions
    quadratic_mean = math.sqrt((dimensions.x ** 2 + dimensions.y ** 2 + dimensions.z ** 2) / 3)

    voxel_size = quadratic_mean / voxel_count
    cage_offset = quadratic_mean * cage_offset_ratio

    if not solid_guide_object:
        bpy_modifier.apply_solidify(guide_cage, voxel_size * 2)  # TODO: a better way to make it solid for the remesh to work


    bpy_modifier.apply_remesh(guide_cage, voxel_size)


    for i in range(number_of_steps):

        print(f"Step: {i + 1}/{number_of_steps}")

        bpy_modifier.apply_displace(guide_cage, cage_offset / number_of_steps)
        bpy_modifier.apply_remesh(guide_cage, voxel_size)


        smooth: bpy.types.CorrectiveSmoothModifier = bake_cage.modifiers.new(name = '', type='CORRECTIVE_SMOOTH')
        smooth.rest_source = 'BIND'
        smooth.use_pin_boundary = True
        bpy_context.call_for_object(bake_cage, bpy.ops.object.correctivesmooth_bind, modifier=smooth.name)

        shrinkwrap: bpy.types.ShrinkwrapModifier = bake_cage.modifiers.new(name = '', type='SHRINKWRAP')
        shrinkwrap.target = guide_cage
        bpy_modifier.move_modifier_to_first(shrinkwrap)

        bpy_utils.convert_to_mesh(bake_cage)


    bpy.data.objects.remove(guide_cage)

    return bake_cage


def bisect(object: bpy.types.Object, axis = 'X', flip = False, mirror_object: typing.Optional[bpy.types.Object] = None, threshold = 0.001):

    if not mirror_object:
        mirror_object = object

    rotation_euler = mathutils.Euler(mirror_object.evaluated_get(bpy.context.evaluated_depsgraph_get()).matrix_world.to_euler('XYZ'), 'XYZ')
    plane_no = mathutils.Vector((axis == 'X', axis == 'Y' , axis == 'Z'))
    plane_no.rotate(rotation_euler)

    with bpy_context.Focus(object, 'EDIT'):

        bpy.ops.mesh.reveal()
        bpy.ops.mesh.select_all(action = 'SELECT')

        bpy.ops.mesh.bisect(
            plane_co = mirror_object.location,
            plane_no = plane_no,
            clear_inner = True,
            threshold = threshold,
            flip = flip,
        )


def bisect_by_mirror_modifiers(object: bpy.types.Object):

    modifier: bpy.types.MirrorModifier
    for modifier in object.modifiers:

        if modifier.type != 'MIRROR':
            continue

        for axis, use_axis, use_bisect_axis, flip in zip(['X', 'Y', 'Z'], modifier.use_axis, modifier.use_bisect_axis, modifier.use_bisect_flip_axis):

            if not use_axis:
                continue

            if not use_bisect_axis:
                continue

            bisect(object, axis, flip, modifier.mirror_object, modifier.bisect_threshold)


def get_selected_edges_groups(mesh: bmesh.types.BMesh):

    groups: typing.List[typing.List[bmesh.types.BMEdge]] = []
    processed = set()

    for init_edge in [edge for edge in mesh.edges if edge.select]:

        if init_edge in processed:
            continue

        processed.add(init_edge)
        group = [init_edge]
        pool = [init_edge]

        while pool:

            edge = pool.pop()

            for vert in edge.verts:
                for connected_edge in vert.link_edges:

                    if not connected_edge.select:
                        continue

                    if connected_edge in processed:
                        continue

                    processed.add(connected_edge)
                    group.append(connected_edge)
                    pool.append(connected_edge)

        groups.append(group)

    return groups


def make_manifold(object: bpy.types.Object):
    """
    For the voxel remesh not to fail.
    For the convex decomposition to avoid operating on the shell.
    """

    with bpy_context.Focus(object, 'EDIT'):

        bpy.ops.mesh.select_mode(type="VERT")
        bpy.ops.mesh.reveal()


        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.mesh.remove_doubles()

        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.mesh.delete_loose(use_verts=True, use_edges=True, use_faces=True)

        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.mesh.fill_holes(sides=4)

        mesh = bmesh.from_edit_mesh(object.data)
        mesh.edges.ensure_lookup_table()

        bpy.ops.mesh.select_all(action="DESELECT")
        bpy.ops.mesh.select_non_manifold()

        bpy.ops.ed.flush_edits()

        edge_groups = get_selected_edges_groups(mesh)

        bpy.ops.mesh.select_all(action="DESELECT")

        for edges in edge_groups:

            for edge in edges:
                edge.select = True

            bmesh.update_edit_mesh(object.data, loop_triangles=False, destructive=False)

            bpy.ops.mesh.extrude_region_shrink_fatten(
                MESH_OT_extrude_region={
                    "use_normal_flip":False,
                    "use_dissolve_ortho_edges":False,
                    "mirror":False
                },
                TRANSFORM_OT_shrink_fatten={
                    "value":-0.1,
                    "use_even_offset":False,
                    "mirror":False,
                    "use_proportional_edit":False,
                    "proportional_edit_falloff":'SMOOTH',
                    "proportional_size":1,
                    "use_proportional_connected":False,
                    "use_proportional_projected":False,
                    "snap":False,
                    "release_confirm":False,
                    "use_accurate":False
                })

            bpy.ops.mesh.fill()
            bpy.ops.mesh.vertices_smooth(factor=0.5, wait_for_input=False)

            bpy.ops.mesh.select_all(action="DESELECT")


        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.mesh.delete_loose(use_verts=True, use_edges=True, use_faces=True)

        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.mesh.remove_doubles()

        # this at some point just selects the whole mesh for a bad geometry
        # bpy.ops.mesh.select_all(action="DESELECT")
        # bpy.ops.mesh.select_interior_faces()
        # bpy.ops.mesh.delete(type="FACE")

        bpy.ops.mesh.select_all(action="DESELECT")
        bpy.ops.mesh.select_non_manifold()
        bpy.ops.mesh.delete(type="FACE")

        mesh = bmesh.from_edit_mesh(object.data)
        mesh.edges.ensure_lookup_table()

        bpy.ops.mesh.select_all(action="DESELECT")
        bpy.ops.mesh.select_non_manifold()

        bpy.ops.ed.flush_edits()

        edge_groups = get_selected_edges_groups(mesh)

        bpy.ops.mesh.select_all(action="DESELECT")

        for edges in edge_groups:

            for edge in edges:
                edge.select = True

            bmesh.update_edit_mesh(object.data, loop_triangles=False, destructive=False)

            bpy.ops.mesh.fill()

            bpy.ops.mesh.select_all(action="DESELECT")


        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.mesh.normals_make_consistent()
