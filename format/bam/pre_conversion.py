""" Collection of utilities that are meant to be run before the export process. """

import json
import sys


if 'bpy' in sys.modules:
    import bpy

    if __spec__.name == __name__:
        from blend_converter import bpy_utils
        from blend_converter.format.bam import keys
    else:
        from ... import bpy_utils
        from . import keys


def assign_curve_placeholders():
    """ Collect curves data information to be late recrated inside panda3d."""

    for object in bpy_utils.get_view_layer_objects():

        if not isinstance(object.data, bpy.types.Curve):
            continue

        object[keys.OBJECT_TYPE] = object.type

        splines = []

        for spline in object.data.splines:

            if spline.type not in (keys.Object_Type.NURBS,):
                raise NotImplementedError(f"Not supported curve type: {spline.type} in {object}")

            knots_num = spline.point_count_u + spline.order_u
            knots = [i/(knots_num - 1) for i in range(knots_num)]

            if spline.use_endpoint_u:

                for i in range(spline.order_u - 1):
                    knots[i] = 0.0
                    knots[-(i + 1)] = 1.0

                for i in range(knots_num - (spline.order_u * 2) + 2):
                    knots[i + spline.order_u - 1] = i/(knots_num - (spline.order_u * 2) + 1)

            splines.append({
                keys.Curve_Data.ORDER: spline.order_u,
                keys.Curve_Data.KNOTS: knots,
                keys.Curve_Data.POINTS: [tuple(point.co) for point in spline.points],  # type: ignore[reportArgumentType]
            })

        object[keys.CURVE_DATA] = json.dumps(splines)


def assign_collision_placeholders():

    for object in bpy_utils.get_view_layer_objects():

        collision_object_type = object.get(keys.Atool_Keys.COLLISION_SHAPE_TYPE)
        if not collision_object_type:
            continue

        bpy_utils.focus(object)
        bpy.ops.object.make_single_user(object=True, obdata=True)
        object.rotation_mode = 'XYZ'

        object[keys.COLLISION_SHAPE_TYPE] = collision_object_type

        if object.type in bpy_utils.TO_MESH_COMPATIBLE_OBJECT_TYPES:
            bpy_utils.convert_to_mesh(object)
            bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)

            vertices = object.data.vertices

            object[keys.COLLISION_SHAPE_DATA] = json.dumps({
                keys.Collision_Shape_Data.MASS: object.get(keys.Atool_Keys.COLLISION_SHAPE_MASS, 0),
                keys.Collision_Shape_Data.X: vertices[0].co[0] * 2,
                keys.Collision_Shape_Data.Y: vertices[1].co[1] * 2,
                keys.Collision_Shape_Data.Z: vertices[2].co[2] * 2,
                keys.Collision_Shape_Data.RADIUS: max(vertices[0].co[0], vertices[1].co[1]),
                keys.Collision_Shape_Data.HEIGHT: vertices[2].co[2] * 2,
            })

        # compound collision shapes
        else:
            object[keys.COLLISION_SHAPE_DATA] = json.dumps(dict(
                mass = object.get(keys.Atool_Keys.COLLISION_SHAPE_MASS, 0),
            ))
