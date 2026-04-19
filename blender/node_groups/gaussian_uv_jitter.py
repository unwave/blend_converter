import bpy


if __spec__ and __spec__.parent:
    from .. import bpy_node
else:
    from blend_converter.blender import bpy_node


SUFFIX = ''



def get_main_tree():
    return __bc_gaussian_uv_jitter()



def __bc_gaussian_uv_jitter():


    name = __bc_gaussian_uv_jitter.__name__ + SUFFIX


    bl_tree = bpy.data.node_groups.get(name)
    if bl_tree:
        return bl_tree


    bl_tree = bpy.data.node_groups.new(name, 'ShaderNodeTree')
    bl_tree.use_fake_user = True

    tree = bpy_node.Shader_Tree_Wrapper(bl_tree)



    tree.add_input_socket('NodeSocketVector', 'Vector')
    tree.add_input_socket('NodeSocketFloat', 'Sigma').default_value = 0.5
    tree.add_input_socket('NodeSocketVector', 'UV Scale')
    tree.add_input_socket('NodeSocketFloat', 'X Resolution').default_value = 1024.0
    tree.add_input_socket('NodeSocketFloat', 'Y Resolution').default_value = 1024.0

    tree.add_output_socket('NodeSocketVector', 'Vector')


    group_output = tree.new('NodeGroupOutput')
    vector_math_add = group_output.get_input_by_name('Vector').new('ShaderNodeVectorMath', operation = 'ADD')

    reroute = vector_math_add.inputs['Vector'].new('NodeReroute', socket_idname = 'NodeSocketVector')
    vector_math_divide = vector_math_add.inputs['Vector_001'].new('ShaderNodeVectorMath', operation = 'DIVIDE')

    reroute_2 = reroute.inputs['Input'].new('NodeReroute', socket_idname = 'NodeSocketVector')

    vector_math_multiply = vector_math_divide.inputs['Vector'].new('ShaderNodeVectorMath', operation = 'MULTIPLY')
    combine_xyz = vector_math_divide.inputs['Vector_001'].new('ShaderNodeCombineXYZ')

    vector_math_scale = vector_math_multiply.inputs['Vector'].new('ShaderNodeVectorMath', operation = 'SCALE')
    group_input = vector_math_multiply.inputs['Vector_001'].new('NodeGroupInput', 2)

    combine_xyz.inputs['X'].join(group_input.get_output_by_name('X Resolution'))
    combine_xyz.inputs['Y'].join(group_input.get_output_by_name('Y Resolution'))

    vector_math_normalize = vector_math_scale.inputs['Vector'].new('ShaderNodeVectorMath', operation = 'NORMALIZE')
    clamp = vector_math_scale.inputs['Scale'].new('ShaderNodeClamp')

    vector_math_scale_2 = vector_math_normalize.inputs['Vector'].new('ShaderNodeVectorMath', operation = 'SCALE')

    vector_math_length = clamp.inputs['Value'].new('ShaderNodeVectorMath', 'Value', operation = 'LENGTH')
    math_multiply = clamp.inputs['Max'].new('ShaderNodeMath', operation = 'MULTIPLY')
    math_multiply['Value_001'] = 1.5

    vector_math_length.inputs['Vector'].join(vector_math_scale_2.outputs['Vector'])

    math_multiply.inputs['Value'].join(group_input.get_output_by_name('Sigma'))

    group = vector_math_scale_2.inputs['Vector'].new('ShaderNodeGroup', node_tree = __bc_box_muller())
    vector_math_scale_2.inputs['Scale'].join(group_input.get_output_by_name('Sigma'))

    tex_white_noise = group.get_input_by_name('Vector').new('ShaderNodeTexWhiteNoise', 'Color', noise_dimensions = '2D')

    tex_white_noise.inputs['Vector'].join(group_input.get_output_by_name('Vector'))

    reroute_2.inputs['Input'].join(group_input.get_output_by_name('Vector'))



    node_locations = [
        (3153, 1383),
        (2845, 1378),
        (2031, 1631),
        (2236, 1014),
        (342, 1620),
        (1955, 1113),
        (1917, 888),
        (1591, 1430),
        (-265, 1188),
        (1158, 1473),
        (1392, 1304),
        (838, 1397),
        (1158, 1330),
        (917, 1239),
        (567, 1444),
        (309, 1470),
    ]

    for index, location in enumerate(node_locations):
        tree._new_nodes[index].location = location



    return bl_tree



def __bc_box_muller():


    name = __bc_box_muller.__name__ + SUFFIX


    bl_tree = bpy.data.node_groups.get(name)
    if bl_tree:
        return bl_tree


    bl_tree = bpy.data.node_groups.new(name, 'ShaderNodeTree')
    bl_tree.use_fake_user = True

    tree = bpy_node.Shader_Tree_Wrapper(bl_tree)



    tree.add_input_socket('NodeSocketVector', 'Vector')

    tree.add_output_socket('NodeSocketVector', 'Vector')


    group_output = tree.new('NodeGroupOutput')
    combine_xyz = group_output.get_input_by_name('Vector').new('ShaderNodeCombineXYZ')

    math_multiply = combine_xyz.inputs['X'].new('ShaderNodeMath', operation = 'MULTIPLY')
    math_multiply_2 = combine_xyz.inputs['Y'].new('ShaderNodeMath', operation = 'MULTIPLY')

    math_sqrt = math_multiply.inputs['Value'].new('ShaderNodeMath', operation = 'SQRT')
    math_cosine = math_multiply.inputs['Value_001'].new('ShaderNodeMath', operation = 'COSINE')

    math_multiply_2.inputs['Value'].join(math_sqrt.outputs['Value'])
    math_sine = math_multiply_2.inputs['Value_001'].new('ShaderNodeMath', operation = 'SINE')

    math_multiply_3 = math_sqrt.inputs['Value'].new('ShaderNodeMath', operation = 'MULTIPLY')
    math_multiply_3['Value'] = -2.0

    math_multiply_4 = math_sine.inputs['Value'].new('ShaderNodeMath', operation = 'MULTIPLY')

    separate_xyz = math_multiply_4.inputs['Value'].new('ShaderNodeSeparateXYZ', 'Y')
    math_multiply_5 = math_multiply_4.inputs['Value_001'].new('ShaderNodeMath', operation = 'MULTIPLY')
    math_multiply_5['Value'] = 2.0
    math_multiply_5['Value_001'] = 3.141590118408203

    separate_xyz.inputs['Vector'].new('NodeGroupInput')

    math_logarithm = math_multiply_3.inputs['Value_001'].new('ShaderNodeMath', operation = 'LOGARITHM')
    math_logarithm['Value_001'] = 2.7182817459106445

    math_logarithm.inputs['Value'].join(separate_xyz.outputs['X'])

    math_cosine.inputs['Value'].join(math_multiply_4.outputs['Value'])



    node_locations = [
        (723, 35),
        (460, 113),
        (188, 184),
        (190, 3),
        (-100, 188),
        (-107, -9),
        (-105, -168),
        (-276, 187),
        (-466, -83),
        (-692, -6),
        (-654, -212),
        (-892, 0),
        (-454, 192),
    ]

    for index, location in enumerate(node_locations):
        tree._new_nodes[index].location = location



    return bl_tree
