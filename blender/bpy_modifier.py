""" Utilities for working with modifiers. """


import bpy
import math
import os

from . import bpy_context
from . import bpy_utils
from . import bpy_node
from . import bpy_mesh


def _apply_modifier(object: bpy.types.Object, name: str):

    if not object.modifiers.get(name):
        raise Exception(
            "The object has no modifier with the name specified."
            "\t\n" f"Object: {object.name_full}"
            "\t\n" f"Name: {name}"
        )

    print(f"{object.modifiers[name].type}: {repr(object.name_full)} {repr(name)}")

    override = dict(selected_objects = [object], active_object = object, object = object)

    try:
        if bpy.app.version > (3,2,0):
            with bpy.context.temp_override(**override):
                result = bpy.ops.object.modifier_apply(modifier = name, single_user = True)
        else:
            result =  bpy.ops.object.modifier_apply(override, modifier = name, single_user = True)

        if 'CANCELLED' in result:
            raise RuntimeError('CANCELLED')

    except RuntimeError as e:

        if 'Modifier is disabled, skipping apply' in str(e):
            object.modifiers.remove(object.modifiers[name])
        else:
            raise Exception(f"Fail to apply {object.modifiers[name].type} modifier '{name}' to object '{object.name_full}'.") from e


def apply_modifier(modifier: bpy.types.Modifier):

    object: bpy.types.Object = modifier.id_data

    if object.data.shape_keys and object.data.shape_keys.key_blocks:
        apply_modifier_with_shape_keys(object, modifier.name)
    else:
        _apply_modifier(object, modifier.name)


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


def apply_triangulate(object: bpy.types.Object, keep_custom_normals = False, min_vertices = 4, quad_method = 'BEAUTY', ngon_method = 'BEAUTY'):
    modifier: bpy.types.TriangulateModifier = object.modifiers.new(name = '_', type='TRIANGULATE')
    modifier.quad_method = quad_method
    modifier.ngon_method = ngon_method
    modifier.keep_custom_normals = keep_custom_normals
    modifier.min_vertices = min_vertices

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


POSITION_SENSITIVE_TOPOLOGY_MODIFIERS = {
    'ARRAY',  # optional
    'BEVEL',
    'BOOLEAN',
    # 'BUILD',
    'DECIMATE',
    'EDGE_SPLIT',
    'NODES',
    # 'MASK',
    'MIRROR',  # optional
    # 'MULTIRES',
    'REMESH',
    'SCREW',  # optional
    'SKIN',
    # 'SOLIDIFY',
    # 'SUBSURF',
    'TRIANGULATE',
    'VOLUME_TO_MESH',
    'WELD',
    # 'WIREFRAME',
    'EXPLODE',
    'FLUID',
    # 'OCEAN',
    # 'PARTICLE_INSTANCE'
}
""" Anything that leads to a topology being changed depending on the vertex positions. """


def get_bind_correction_geometry_tree():
    """ https://docs.blender.org/manual/en/latest/modeling/modifiers/deform/surface_deform.html#options """

    bl_tree = bpy.data.node_groups.get('__bc_bind_correction')
    if bl_tree:
        return bl_tree

    bl_tree: bpy.types.GeometryNodeTree = bpy.data.node_groups.new(name='__bc_bind_correction', type='GeometryNodeTree')

    bl_tree.use_fake_user = True
    bl_tree.is_modifier = True
    bl_tree.interface.new_socket('Geometry', in_out = 'INPUT', socket_type = 'NodeSocketGeometry')
    bl_tree.interface.new_socket('Geometry', in_out = 'OUTPUT', socket_type = 'NodeSocketGeometry')

    tree = bpy_node.Geometry_Tree_Wrapper(bl_tree)

    output = tree.new('NodeGroupOutput')

    delete_geometry = output.inputs[0].insert_new('GeometryNodeTriangulate').inputs[0].insert_new('GeometryNodeDeleteGeometry')
    delete_geometry.domain = 'EDGE'

    delete_geometry.inputs[0].new('NodeGroupInput', 0)

    # delete_geometry.inputs[0].insert_new('GeometryNodeMergeByDistance')  # this creates invalid geometry

    random = output.inputs[0].insert_new('GeometryNodeSetPosition').inputs[3].new('FunctionNodeRandomValue', data_type = 'FLOAT_VECTOR')
    random.inputs[0].set_default_value(-0.00001/2)
    random.inputs[1].set_default_value(0.00001/2)

    compare = delete_geometry.inputs[1].new('FunctionNodeCompare')
    compare.data_type = 'INT'
    compare.operation = 'GREATER_THAN'
    compare.inputs[3].default_value = 2

    compare.inputs[2].new('GeometryNodeInputMeshEdgeNeighbors')

    return bl_tree


def apply_modifier_with_shape_keys(object: bpy.types.Object, modifier_name: str):
    """
    Resolves `Error: Modifier cannot be applied to a mesh with shape keys`.
    Tries to resolve issues in case of a topology mismatch.
    """

    from . import utils
    utils.debug_print(object.name_full, modifier_name)


    def copy_object(object: bpy.types.Object, suffix: str):
        copy = object.copy()
        copy.name = object.name + suffix
        copy.data = object.data.copy()
        copy.data.name = copy.data.name + suffix
        bpy.context.scene.collection.objects.link(copy)
        return copy


    def apply_shape_key(object: bpy.types.Object, name: str = ''):

        if not name:
            name = object.data.shape_keys.key_blocks[0].name

        for key_block in reversed(object.data.shape_keys.key_blocks):
            if key_block.name != name:
                object.shape_key_remove(key_block)

        object.shape_key_remove(object.data.shape_keys.key_blocks[name])


    def add_surface_deform(object: bpy.types.Object, target: bpy.types.Object):

        modifier: bpy.types.SurfaceDeformModifier = object.modifiers.new(name = '_', type='SURFACE_DEFORM')
        modifier.name = modifier.type
        modifier.target = target

        def bind():
            bpy_context.call_for_object(object, bpy.ops.object.surfacedeform_bind, modifier = modifier.name)

        bind()
        if modifier.is_bound:
            return
        else:
            bind()  # unbind

        bind_correction: bpy.types.NodesModifier = target.modifiers.new(name = '__bc_bind_correction', type='NODES')
        bind_correction.node_group = get_bind_correction_geometry_tree()

        bpy_utils.move_modifier_to_first(bind_correction)

        bind()
        if modifier.is_bound:
            return bind_correction.name
        else:
            bind()  # unbind

        bpy_utils.move_modifier_to_last(bind_correction)

        bind()
        if not modifier.is_bound:
            raise Exception(f"Fail to bind Surface Deform: {object.name_full}")

        return bind_correction.name


    with bpy_context.Bpy_State() as state:


        ## disabling modifiers
        # otherwise they affect the join_shapes' results
        for modifier in object.modifiers:

            if modifier.name == modifier_name:
                modifier.show_viewport = False
            else:
                state.set(modifier, 'show_viewport', False)


        ## remember the shape keys settings
        state.set(object, 'show_only_shape_key', False)
        state.set(object, 'active_shape_key_index', False)

        state.remember(object.data.shape_keys, 'use_relative')
        state.remember(object.data.shape_keys, 'eval_time')

        if object.data.shape_keys.animation_data:
            state.remember(object.data.shape_keys.animation_data, 'action')
            if object.data.shape_keys.animation_data.action and hasattr(object.data.shape_keys.animation_data, 'action_slot'):
                state.remember(object.data.shape_keys.animation_data, 'action_slot')


        for key in object.data.shape_keys.key_blocks:

            for property in key.bl_rna.properties:

                if property.is_readonly:
                    continue

                if property.identifier == 'name':
                    continue

                state.remember(key, property.identifier)


        ## get the shape keys names
        basis_key_name = object.data.shape_keys.key_blocks[0].name
        names = [k.name for k in object.data.shape_keys.key_blocks[1:]]


        ## get the modifier's type
        modifier_type = object.modifiers[modifier_name].type


        ## make a copy of the object to store the shape keys
        copy = copy_object(object, '[copy]')


        if copy.data.shape_keys.animation_data:
            for driver in copy.data.shape_keys.animation_data.drivers:
                state.set(driver, 'mute', True)

        for shape_key in copy.data.shape_keys.key_blocks:
            shape_key.value = 0


        ## apply the modifier and clear the shape keys on the object
        apply_shape_key(object)
        _apply_modifier(object, modifier_name)


        ## modify the copy topology in order for SURFACE_DEFORM to work
        if modifier_type in POSITION_SENSITIVE_TOPOLOGY_MODIFIERS:

            bind_copy = copy_object(copy, '[bind_copy]')

            bind_copy.active_shape_key_index = 0

            if modifier_type == 'MIRROR':
                bpy_mesh.bisect_by_mirror_modifiers(bind_copy)

            with bpy_context.Focus_Objects(bind_copy, 'EDIT'):

                # TODO: edit the mesh only if you cannot bind because of the errors
                # https://docs.blender.org/manual/en/latest/modeling/modifiers/deform/surface_deform.html#options

                bpy.ops.mesh.reveal()

                # >must not contain concave faces
                # >Target contains concave polygons
                bpy.ops.mesh.select_all(action='SELECT')
                bpy.ops.mesh.vert_connect_concave()

                # >must not contain edges with more than two faces
                # >Target has edges with more than two polygons
                bpy.ops.mesh.select_all(action='DESELECT')
                bpy.ops.mesh.select_interior_faces()
                bpy.ops.mesh.delete(type='FACE')

                # >must not contain faces with collinear edges
                # >must not contain overlapping vertices (doubles)
                # >Target contains invalid polygons
                # https://projects.blender.org/blender/blender/issues/146912
                bpy.ops.mesh.select_all(action='SELECT')
                bpy.ops.transform.vertex_random(offset=0.000001)

        else:

            bind_copy = None


        for index, name in enumerate(names, start = 1):

            temp = copy_object(copy, '[temp]')

            # TODO: treat the modifiers that are not actually position sensitive as simple cases
            # e.g.: Bevel in a non-Angle mode, non-merging Mirror, etc.

            # this is rather a last resort
            # better to solve the issues with the shape keys themselves
            # like a mirror with merging when the shape key goes against the symmetry line
            # but some modifiers just won't work

            if modifier_type in POSITION_SENSITIVE_TOPOLOGY_MODIFIERS:

                apply_shape_key(temp)
                _apply_modifier(temp, modifier_name)

                temp.modifiers.clear()

                with bpy_context.Bpy_State() as state_2:

                    # TODO: add other exceptions when a modifier settings can be changed
                    # so it won't be modifying the topology in a position sensitive way
                    # like in case of a merge option

                    if modifier_type == 'MIRROR':
                        # otherwise the shape key is not mirrored
                        state_2.set(bind_copy.modifiers[modifier_name], 'show_viewport', True)
                        state_2.set(bind_copy.modifiers[modifier_name], 'use_mirror_merge', False)
                        state_2.set(bind_copy.modifiers[modifier_name], 'use_bisect_axis', [False, False, False])

                    post_bind_correction = add_surface_deform(temp, bind_copy)

                    state_2.set(bind_copy.data.shape_keys.key_blocks[name], 'value', 1)

                    for modifier in temp.modifiers:
                        _apply_modifier(temp, modifier.name)

                    if post_bind_correction:
                        bind_copy.modifiers.remove(bind_copy.modifiers[post_bind_correction])

            else:
                apply_shape_key(temp, name)
                _apply_modifier(temp, modifier_name)

            bpy_context.call_for_objects(object, [temp], bpy.ops.object.join_shapes)
            object.data.shape_keys.key_blocks[index].name = name

            bpy.data.batch_remove((temp, temp.data))


        ## transferring shape keys drivers to the original object
        if copy.data.shape_keys.animation_data:

            object.data.shape_keys.animation_data_create()

            for driver in copy.data.shape_keys.animation_data.drivers:
                object.data.shape_keys.animation_data.drivers.from_existing(src_driver=driver)


        ## ensure the Basis key
        # in case there was only one key
        if object.data.shape_keys is None:
            assert not names
            object.shape_key_add(name = basis_key_name, from_mix=False)


        # HACK: since we create a new bpy.types.Key block
        # and because it is distinct from the Mesh block
        # we replace the old one with the new one
        for item in state.id_blocks_collection:
            if isinstance(item.target, bpy.types.Key):
                item.target = object.data.shape_keys


    ## deleting the copies
    copy.data.shape_keys.use_fake_user = False
    copy.data.shape_keys.use_extra_user = False
    copy.shape_key_clear()
    bpy.data.batch_remove((copy, copy.data))

    if bind_copy:
        bind_copy.data.shape_keys.use_fake_user = False
        bind_copy.data.shape_keys.use_extra_user = False
        bind_copy.shape_key_clear()
        bpy.data.batch_remove((bind_copy, bind_copy.data))
