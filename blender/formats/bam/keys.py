PREFIX = 'bc_'


OBJECT_TYPE = PREFIX + 'blender_object_type'

class Object_Type:
    CURVE = 'CURVE'
    NURBS = 'NURBS'


CURVE_DATA = PREFIX + 'curves_data'

class Curve_Data:
    ORDER = 'order'
    KNOTS = 'knots'
    POINTS = 'points'


COLLISION_SHAPE_TYPE = PREFIX + 'collision_shape_type'

class Collision_Shape:
    SPHERE = 'SPHERE'
    BOX = 'BOX'
    CYLINDER = 'CYLINDER'
    CAPSULE = 'CAPSULE'
    CONE = 'CONE'
    MESH = 'MESH'
    CONVEX_HULL = 'CONVEX_HULL'
    COMPOUND = 'COMPOUND'


COLLISION_SHAPE_DATA = PREFIX + 'collision_shape_data'

class Collision_Shape_Data:
    MASS = 'mass'
    """ Used only for compound shape type. """

    X = 'x'
    Y = 'y'
    Z = 'z'
    RADIUS = 'radius'
    HEIGHT = 'height'


class Atool_Keys:
    COLLISION_SHAPE_TYPE = 'atool_collision_object_type'
    COLLISION_SHAPE_MASS = 'atool_collision_mass'
