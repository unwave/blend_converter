import typing
import json
import sys


if 'panda3d' in sys.modules:
    from panda3d import core
    from panda3d import bullet

    if __spec__.name == __name__:
        from blend_converter.format.bam import keys
    else:
        from . import keys


def convert_curve_placeholders(node_path: 'core.NodePath'):

    for placeholder_np in node_path.find_all_matches(f'={keys.OBJECT_TYPE}={keys.Object_Type.CURVE}'):

        assert len(placeholder_np.children) == 0

        curve_data = json.loads(placeholder_np.get_tag(keys.CURVE_DATA))

        for spline in curve_data:

            curve = core.NurbsCurve()

            curve.set_order(spline[keys.Curve_Data.ORDER])

            for point in spline[keys.Curve_Data.POINTS]:
                curve.append_cv(core.LVector4f(*point))

            for index, knot in enumerate(spline[keys.Curve_Data.KNOTS]):
                curve.set_knot(index, knot)

            curve.recompute()

            placeholder_np.parent.attach_new_node(curve)

        placeholder_np.remove_node()


def get_bullet_shape(node_path: 'core.NodePath'):
    """ Gets the result of an export of `.blend` -> `.gltf` -> `.bam` for a shape place holder and constructs a panda3d bullet shape. """

    type = node_path.get_tag(keys.COLLISION_SHAPE_TYPE)
    data = json.loads(node_path.get_tag(keys.COLLISION_SHAPE_DATA))

    if type == keys.Collision_Shape.SPHERE:
        shape = bullet.BulletSphereShape(radius=data[keys.Collision_Shape_Data.RADIUS])
    elif type == keys.Collision_Shape.BOX:
        shape = bullet.BulletBoxShape(halfExtents=(data[keys.Collision_Shape_Data.X]/2, data[keys.Collision_Shape_Data.Y]/2, data[keys.Collision_Shape_Data.Z]/2))
    elif type == keys.Collision_Shape.CYLINDER:
        shape = bullet.BulletCylinderShape(radius=data[keys.Collision_Shape_Data.RADIUS], height=data[keys.Collision_Shape_Data.HEIGHT])
    elif type == keys.Collision_Shape.CAPSULE:
        shape = bullet.BulletCapsuleShape(radius=data[keys.Collision_Shape_Data.RADIUS], height=data[keys.Collision_Shape_Data.HEIGHT])
    elif type == keys.Collision_Shape.CONE:
        shape = bullet.BulletConeShape(radius=data[keys.Collision_Shape_Data.RADIUS], height=data[keys.Collision_Shape_Data.HEIGHT])

    elif type == keys.Collision_Shape.MESH:

        mesh_shape = bullet.BulletTriangleMesh()
        for geom_np in node_path.find_all_matches('**/+GeomNode'):
            for geom in geom_np.node().get_geoms():
                mesh_shape.add_geom(geom)

        shape = bullet.BulletTriangleMeshShape(mesh_shape, dynamic=False)

    elif type == keys.Collision_Shape.CONVEX_HULL:

        shape = bullet.BulletConvexHullShape()
        for geom_np in node_path.find_all_matches('**/+GeomNode'):
            for geom in geom_np.node().get_geoms():
                shape.add_geom(geom)

    else:
        raise NotImplementedError(f"Not expected collision shape: {type}")

    return shape


def convert_collision_placeholders(node_path: 'core.NodePath'):
    """ Find and replace all compound shape placeholders with BulletRigidBodyNode. """

    for compound_shape_np in node_path.find_all_matches(f'**/={keys.COLLISION_SHAPE_TYPE}={keys.Collision_Shape.COMPOUND};+h+s'):

        shapes: typing.List[bullet.BulletShape] = []
        shape_transforms: typing.List[core.TransformState] = []

        for shape_np in compound_shape_np.find_all_matches(f'**/={keys.COLLISION_SHAPE_TYPE};+h+s'):

            shape = get_bullet_shape(shape_np)

            shape_transforms.append(shape_np.get_transform(compound_shape_np))
            shapes.append(shape)

            shape_np.remove_node()

        if not shapes:
            shapes = [bullet.BulletBoxShape(core.Vec3(0.5, 0.5, 0.5))]

        bullet_node = bullet.BulletRigidBodyNode(compound_shape_np.name)
        collision_shape_center = compound_shape_np.get_pos()

        for shape, shape_transform in zip(shapes, shape_transforms):
            xform = shape_transform.set_pos(shape_transform.get_pos() - collision_shape_center)
            bullet_node.add_shape(shape, xform = xform)

        compound_shape_data = json.loads(compound_shape_np.get_tag(keys.COLLISION_SHAPE_DATA))
        bullet_node.set_mass(compound_shape_data[keys.Collision_Shape_Data.MASS])

        bullet_node_np = core.NodePath(bullet_node)
        bullet_node_np.set_pos(collision_shape_center)
        bullet_node_np.reparent_to(compound_shape_np.parent)

        for child in compound_shape_np.children:
            child.reparent_to(bullet_node_np)

        bullet_node.copy_tags(compound_shape_np.node())

        compound_shape_np.remove_node()
