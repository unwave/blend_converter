import bpy


if __spec__ and __spec__.parent:
    from .. import bpy_node
else:
    from blend_converter.blender import bpy_node


SUFFIX = ''



def get_main_tree():
    engine = bpy.context.scene.render.engine
    bpy.context.scene.render.engine = 'CYCLES'
    tree = __bc_pixel_scale()
    bpy.context.scene.render.engine = engine
    return tree



def get_script(identifier: str):

    text = bpy.data.texts.get(identifier + SUFFIX)
    if text:
        return text

    text = bpy.data.texts.new(identifier + SUFFIX)
    text.from_string(globals()[identifier])

    return text


__bc_vector_derivatives_osl = r"""
shader vector_derivatives
(
    point Vector = vector(0.0, 0.0, 0.0),
    output vector DX = vector(0.0, 0.0, 0.0),
    output vector DY = vector(0.0, 0.0, 0.0),
    output vector DZ = vector(0.0, 0.0, 0.0),
    output vector Filterwidth = vector(0.0, 0.0, 0.0),
    output float Area = 0.0,
)
{
    DX = Dx(Vector);
    DY = Dy(Vector);
    DZ = Dz(Vector);
    Filterwidth = filterwidth(Vector);
    Area = area(Vector);
}
"""


def __bc_pixel_scale():


    name = __bc_pixel_scale.__name__ + SUFFIX


    bl_tree = bpy.data.node_groups.get(name)
    if bl_tree:
        return bl_tree


    bl_tree = bpy.data.node_groups.new(name, 'ShaderNodeTree')
    bl_tree.use_fake_user = True

    tree = bpy_node.Shader_Tree_Wrapper(bl_tree)



    tree.add_input_socket('NodeSocketVector', 'Vector')

    tree.add_output_socket('NodeSocketFloat', 'Value')


    group_output = tree.new('NodeGroupOutput')
    math_sqrt = group_output.get_input_by_name('Value').new('ShaderNodeMath', operation = 'SQRT')

    math_divide = math_sqrt.inputs['Value'].new('ShaderNodeMath', operation = 'DIVIDE')

    script = math_divide.inputs['Value'].new('ShaderNodeScript', 'Area', script = get_script('__bc_vector_derivatives_osl'))
    script_2 = math_divide.inputs['Value_001'].new('ShaderNodeScript', 'Area', script = get_script('__bc_vector_derivatives_osl'))

    script.inputs['Vector'].new('ShaderNodeNewGeometry')

    script_2.inputs['Vector'].new('NodeGroupInput')



    node_locations = [
        (542, 0),
        (352, 0),
        (184, 2),
        (-83, 119),
        (-82, -119),
        (-341, 61),
        (-562, -151),
    ]

    for index, location in enumerate(node_locations):
        tree._new_nodes[index].location = location



    return bl_tree
