
import bpy
import bmesh

from . import bpy_context
from . import bpy_utils


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
