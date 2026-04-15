import os

import bpy


if __spec__ and __spec__.parent:
    from .. import bpy_node
else:
    from blend_converter.blender import bpy_node


SUFFIX = ''



def get_main_tree():
    return __bc_uv_derivatives()



def __bc_uv_derivatives():


    name = __bc_uv_derivatives.__name__ + SUFFIX


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

    group = combine_xyz.inputs['X'].new('ShaderNodeGroup', node_tree = __bc_bump_based_derivative())
    group_2 = combine_xyz.inputs['Y'].new('ShaderNodeGroup', node_tree = __bc_bump_based_derivative())

    separate_xyz = group.get_input_by_name('Value').new('ShaderNodeSeparateXYZ')

    group_2.get_input_by_name('Value').join(separate_xyz.outputs['Y'])

    separate_xyz.inputs['Vector'].new('NodeGroupInput')



    node_locations = [
        (483, 3),
        (271, 15),
        (-12, 59),
        (-10, -59),
        (-256, -19),
        (-468, 0),
    ]

    for index, location in enumerate(node_locations):
        tree._new_nodes[index].location = location



    return bl_tree



def __bc_bump_based_derivative():


    name = __bc_bump_based_derivative.__name__ + SUFFIX


    bl_tree = bpy.data.node_groups.get(name)
    if bl_tree:
        return bl_tree


    bl_tree = bpy.data.node_groups.new(name, 'ShaderNodeTree')
    bl_tree.use_fake_user = True

    tree = bpy_node.Shader_Tree_Wrapper(bl_tree)



    tree.add_input_socket('NodeSocketFloat', 'Value')

    tree.add_output_socket('NodeSocketFloat', 'Value')


    group_output = tree.new('NodeGroupOutput')
    math_divide = group_output.get_input_by_name('Value').new('ShaderNodeMath', operation = 'DIVIDE')

    math_sqrt = math_divide.inputs['Value'].new('ShaderNodeMath', operation = 'SQRT')
    vector_math_dot_product = math_divide.inputs['Value_001'].new('ShaderNodeVectorMath', 'Value', operation = 'DOT_PRODUCT')

    math_subtract = math_sqrt.inputs['Value'].new('ShaderNodeMath', operation = 'SUBTRACT')
    math_subtract['Value'] = 1.0

    bump = vector_math_dot_product.inputs['Vector'].new('ShaderNodeBump')
    bump['Distance'] = 1.0
    try:
        bump['Filter Width'] = 1.0
    except KeyError:
        pass
    new_geometry = vector_math_dot_product.inputs['Vector_001'].new('ShaderNodeNewGeometry', 'True Normal')

    bump.inputs['Height'].new('NodeGroupInput')
    bump.inputs['Normal'].join(new_geometry.outputs['True Normal'])

    math_power = math_subtract.inputs['Value_001'].new('ShaderNodeMath', operation = 'POWER')
    math_power['Value_001'] = 2.0

    math_power.inputs['Value'].join(vector_math_dot_product.outputs['Value'])



    node_locations = [
        (935, 203),
        (688, 222),
        (506, 254),
        (-133, 134),
        (318, 263),
        (-466, 189),
        (-698, -41),
        (-853, 66),
        (137, 255),
    ]

    for index, location in enumerate(node_locations):
        tree._new_nodes[index].location = location



    return bl_tree
