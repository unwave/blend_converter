from __future__ import annotations

import math
import operator
import random
import typing
import uuid
from .. import tool_settings
from .. import utils

from . import bake_settings
from . import bpy_context
from . import bpy_node
from . import bpy_utils
from . import bpy_uv
from . import bpy_modifier



if utils.is_in_blender():

    import bpy
    import mathutils

elif not typing.TYPE_CHECKING:

    bpy = utils.Dummy()
    mathutils = utils.Dummy()



NORMAL_SOCKETS = {
    'Normal',
    'Tangent',
    'Clearcoat Normal',
    'Coat Normal',
}


def get_default_material() -> bpy.types.Material:

    material = bpy.data.materials.get('__bc_default_material')
    if not material:
        material = bpy.data.materials.new('__bc_default_material')
        if bpy.app.version < (5, 0):
            material.use_nodes = True

    return material


def get_gltf_settings_node_tree():
    node_tree = bpy.data.node_groups.get('glTF Settings')
    if node_tree:
        return node_tree

    node_tree: bpy.types.ShaderNodeTree = bpy.data.node_groups.new('glTF Settings', 'ShaderNodeTree')

    if hasattr(node_tree, 'interface'):
        node_tree.interface.new_socket(name='Occlusion', in_out='INPUT', socket_type='NodeSocketFloat')
        node_tree.interface.items_tree['Occlusion'].default_value = 0.5
    else:
        node_tree.inputs.new('NodeSocketFloatFactor', 'Occlusion')
        node_tree.inputs['Occlusion'].default_value = 0.5

    return node_tree


def create_material(
            name: str,
            uv_layer: str,
            images: typing.Iterable[bpy.types.Image],
            material: typing.Optional[bpy.types.Material] = None,
            k_map_identifier = tool_settings.S_Bake._K_MAP_IDENTIFIER
        ):

    do_reset = False

    if not material:
        material = bpy.data.materials.new(name)
        if bpy.app.version < (5, 0):
            material.use_nodes = True
    else:
        do_reset = True

    tree = bpy_node.Shader_Tree_Wrapper(material.node_tree)
    if do_reset:
        tree.reset_nodes()

    principled = tree.output['Surface']

    uv_node = tree.new('ShaderNodeUVMap')
    uv_node.uv_map = uv_layer
    x, y = uv_node.location
    uv_node.location = (x - 500, y)


    def get_gltf_settings_node():
        node = tree.bl_tree.nodes.get('glTF Settings')
        if node:
            return tree[node]

        node = tree.new('ShaderNodeGroup', node_tree = get_gltf_settings_node_tree())
        node.name = 'glTF Settings'
        return node


    def get_input(identifier):
        if identifier == bake_settings._S_AO._identifier:
            return get_gltf_settings_node().inputs[0]
        else:
            socket = principled.inputs.get(identifier)
            if socket is None:
                print("Unexpected image type:", map_identifier)
                return tree.new('NodeReroute').inputs[0]
            else:
                return socket


    for image in images:

        map_identifier = list(image[k_map_identifier].keys())

        if len(map_identifier) in (1,2):
            input = get_input(map_identifier[0])

            image_node = input.new('ShaderNodeTexImage', image = image)

            uv_node.outputs[0].join(image_node.inputs['Vector'], False)

            if map_identifier[0] in NORMAL_SOCKETS:
                normal_map_node = image_node.outputs[0].new('ShaderNodeNormalMap', 'Color')
                normal_map_node.uv_map = uv_layer
                normal_map_node.outputs[0].join(input)

        elif len(map_identifier) in (3, 4):

            for index, _identifier in enumerate(map_identifier[:3]):
                if _identifier:
                    non_none_index = index
                    break
            else:
                continue

            input = get_input(map_identifier[non_none_index])

            separate_rgb = input.new(bpy_node.Shader_Node_Type.SEPARATE_RGB)

            image_node = separate_rgb.inputs[non_none_index].new('ShaderNodeTexImage', image = image)
            uv_node.outputs[0].join(image_node.inputs['Vector'], False)

            for index, _identifier in enumerate(map_identifier[:3]):

                if not _identifier:
                    continue

                separate_rgb.outputs[index].join(get_input(_identifier), move = False)

        if len(map_identifier) in (2, 4):
            image_node.outputs[1].join(get_input(map_identifier[-1]))

    if principled['Alpha']:
        material.blend_method = 'HASHED'

    if principled[bpy_node.Socket_Identifier.EMISSION]:
        if 'Emission Strength' in principled.inputs.identifiers and not principled['Emission Strength']:
            principled['Emission Strength'] = 1

    if principled['Base Color']:
        tree.bl_tree.nodes.active = principled['Base Color'].bl_node

    return material




def get_property_rgba(object: bpy.types.Object, name: str):
    """
    find_rna_property_rgba
    https://github.com/blender/blender/blob/ce0b3d98205dabaed87f6212aa0f0f1f2656092b/source/blender/blenkernel/intern/object_dupli.cc#L1866
    """

    value = object.get(name, None)
    if value is None:
        try:
            value = object.path_resolve(name)
        except ValueError:
            return None

    if isinstance(value, (float, int, bool)):
        return (float(value), float(value), float(value), 1.0)
    else:
        try:
            _value = [0.0, 0.0, 0.0, 1.0]
            for i, n in zip(range(4), value):
                _value[i] = float(n)
            return tuple(_value)
        except (TypeError, ValueError):
            return None


def find_attribute_rgba(object: bpy.types.Object, name: str):
    """
    BKE_object_dupli_find_rgba_attribute
    https://github.com/blender/blender/blob/ce0b3d98205dabaed87f6212aa0f0f1f2656092b/source/blender/blenkernel/intern/object_dupli.cc#L1942

    currently now handling the instance part as those should be used when making instances real and read from the objects
    """

    value = get_property_rgba(object, name)
    if value is not None:
        return value

    if object.data:
        value = get_property_rgba(object.data, name)
        if value is not None:
            return value

    return (0.0, 0.0, 0.0, 0.0)



def get_empty():

    empty = bpy.data.objects.new(name='__bc_temp_texture_coordinate', object_data=None)
    empty.empty_display_type = 'ARROWS'

    return empty


def get_texture_coordinates_object_empty(object: bpy.types.Object):
    empty = get_empty()
    empty.matrix_world = object.matrix_world
    return empty


def get_texture_coordinates_generated_empty(object: bpy.types.Object):
    """
    BKE_mesh_texspace_calc
    https://github.com/blender/blender/blob/ce0b3d98205dabaed87f6212aa0f0f1f2656092b/source/blender/blenkernel/intern/mesh.cc#L934
    """

    empty = get_empty()

    matrix_world = object.matrix_world
    empty.matrix_world = matrix_world

    translation = matrix_world.to_translation()
    quaternion = matrix_world.to_quaternion()
    scale = matrix_world.to_scale()

    if object.data:
        texspace_location = object.data.texspace_location
        texspace_size = object.data.texspace_size
    else:
        texspace_location = mathutils.Vector((0,0,0))
        texspace_size = mathutils.Vector((1,1,1))

    x = quaternion @ (scale * texspace_location)
    y = quaternion @ (scale * texspace_size)

    empty.location = translation - y + x
    empty.scale *= texspace_size * 2

    return empty


GENERATED_COORDINATES_TEXTURE_NODE = {
    'ShaderNodeTexBrick',
    'ShaderNodeTexChecker',
    'ShaderNodeTexGradient',
    'ShaderNodeTexMagic',
    'ShaderNodeTexNoise',
    'ShaderNodeTexVoronoi',
    'ShaderNodeTexWave',
    'ShaderNodeTexWhiteNoise',
}


def unify_color_attributes_format(objects: typing.List[bpy.types.Object]):
    """ Workaround inconsistent results when merging objects with color attributes of different data formats. """

    objects = [object for object in bpy_utils.get_unique_data_objects(objects) if hasattr(object.data, 'color_attributes')]

    color_attributes = {}

    for object in objects:
        for color_attribute in object.data.color_attributes:
            format = (color_attribute.data_type, color_attribute.domain)
            color_attributes.setdefault(color_attribute.name, set(format)).add(format)

    for color_attribute_name, formats in color_attributes.items():

        if len(formats) <= 1:
            continue

        with bpy_context.Focus(objects):

            for object in objects:

                if not color_attribute_name in object.data.color_attributes.keys():
                    continue

                object.data.color_attributes.active_color = object.data.color_attributes[color_attribute_name]
                bpy_context.call_for_object(object, bpy.ops.geometry.color_attribute_convert, domain='CORNER', data_type='FLOAT_COLOR')


def make_materials_unique(object: bpy.types.Object, filter_func: typing.Optional[typing.Callable[[bpy.types.MaterialSlot], bool]] = None):
    """ Make a unique copy of a material for each material slot of an object. """

    for slot in object.material_slots:

        if not slot.material:
            continue

        if slot.material.users - slot.material.use_fake_user == 1:
            continue

        if filter_func and not filter_func(slot):
            continue

        slot.material = slot.material.copy()


class Material_Bake_Type:
    PREFIX = '__bc_'
    HAS_BASE_COLOR = PREFIX + 'has_base_color'
    HAS_NORMALS =  PREFIX + 'has_normals'
    HAS_ROUGHNESS =  PREFIX + 'has_roughness'
    HAS_METALLIC =  PREFIX + 'has_metallic'
    HAS_ALPHA =  PREFIX + 'has_alpha'
    HAS_EMISSION =  PREFIX + 'has_emission'


def convert_materials_to_principled(objects: typing.List[bpy.types.Object], remove_unused = True):
    print(f"{convert_materials_to_principled.__name__}...")


    if remove_unused:

        with bpy_context.Focus(objects):

            for object in objects:

                if not hasattr(object, 'material_slots'):
                    continue

                if not object.material_slots:
                    continue

                bpy_context.simple_select(object)
                bpy.ops.object.material_slot_remove_unused()


    # assign a default material to empty material slots and objects with no materials
    for object in objects:

        if not hasattr(object, 'material_slots'):
            continue

        if not object.material_slots:
            object.data.materials.append(get_default_material())
            continue

        for slot in object.material_slots:
            if slot.material is None:
                slot.material = get_default_material()


    materials = list(bpy_utils.group_objects_by_material(objects))


    # convert all non-node materials to nodes
    for material in materials:

        if bpy.app.version >= (5, 0):
            # Nodes: remove "Use Nodes" in Shader Editor #141278
            # https://projects.blender.org/blender/blender/pulls/141278
            continue

        if material.use_nodes:
            continue

        material.use_nodes = True

        tree = bpy_node.Shader_Tree_Wrapper(material.node_tree)

        tree.reset_nodes()

        principled = tree.output[0]

        principled['Base Color'] = material.diffuse_color
        principled['Metallic'] = material.metallic
        principled[bpy_node.Socket_Identifier.SPECULAR_IOR] = material.specular_intensity
        principled['Roughness'] = material.roughness


    for material in materials:
        print('convert_to_pbr:', material.name_full)

        tree = bpy_node.Shader_Tree_Wrapper(material.node_tree)

        tree.convert_to_pbr()

        principled = tree.output[0]

        material[Material_Bake_Type.HAS_ALPHA] = bool(principled['Alpha'] or principled.inputs['Alpha'].default_value != 1)
        material[Material_Bake_Type.HAS_EMISSION] = bool((principled[bpy_node.Socket_Identifier.EMISSION] or not all(map(math.isclose, principled.inputs[bpy_node.Socket_Identifier.EMISSION].default_value, (0, 0, 0)))) and principled.inputs['Emission Strength'].default_value != 0)
        material[Material_Bake_Type.HAS_NORMALS] = bool(principled['Normal'])


def split_into_alpha_and_non_alpha_groups(objects: typing.List[bpy.types.Object]):

    alpha_material_key = f"__bc_alpha_material_{uuid.uuid1().hex}"
    opaque_material_key = f"__bc_opaque_material_{uuid.uuid1().hex}"

    for material in bpy_utils.group_objects_by_material(objects):
        if material[Material_Bake_Type.HAS_ALPHA]:
            material[alpha_material_key] = True
        else:
            material[opaque_material_key] = True

    return alpha_material_key, opaque_material_key


def make_node_tree_independent_from_object(object: bpy.types.Object, node_tree: bpy.types.ShaderNodeTree, texture_coordinates_collection: 'bpy.types.Collection', check_only = False):
    """ Make a shader node tree independent from its object. """

    tree = bpy_node.Shader_Tree_Wrapper(node_tree)


    if not check_only:
        if tree.is_material:
            name_full = bpy_context.get_embedded_id_data_and_path(node_tree)[0].name_full
        else:
            name_full = node_tree.name_full
        print(f"Making node tree unique: {name_full}")

    if not tree.root:
        print(f"Empty tree: {repr(tree.bl_tree)}")
        return

    warning_color = utils.get_color_code(217, 69, 143, 0,0,0)

    def warn(*args):
        utils.print_in_color(warning_color, 'WARNING:', *args)


    def is_valid_uv_map(uv_map: str, object: bpy.types.Object):

        # TODO: handle non mesh objects

        if not object.data:
            return False

        if not hasattr(object.data, 'uv_layers'):
            return False

        return uv_map in object.data.uv_layers.keys()


    if bpy_uv.get_active_render_uv_layer(object):

        # Joining objects deletes UV map #64245
        # https://projects.blender.org/blender/blender/issues/64245

        render_uv_layer = bpy_uv.get_active_render_uv_layer(object).name

        for node in reversed(tree.root.descendants):
            if node.be('ShaderNodeTexImage') and not node.inputs['Vector'].connections:

                if check_only:
                    return True

                node.inputs['Vector'].new('ShaderNodeUVMap', uv_map=render_uv_layer)


    for node in reversed(tree.root.descendants):
        if node.be(GENERATED_COORDINATES_TEXTURE_NODE) and not node.inputs['Vector'].connections and node.inputs['Vector'].enabled:

            if check_only:
                return True

            node.inputs['Vector'].new('ShaderNodeTexCoord', 'Generated')


    for node in reversed(tree.root.descendants):

        if node.be('ShaderNodeAttribute') and node.attribute_type in ('OBJECT', 'INSTANCER'):

            if node.attribute_type == 'INSTANCER':
                warn("ShaderNodeAttribute.attribute_type == 'INSTANCER' handled as 'OBJECT'")

            rgba = find_attribute_rgba(object, node.attribute_name)

            for output in node.outputs:

                if not output.connections:
                    continue

                if check_only:
                    return True

                if output.identifier in ('Color', 'Vector'):
                    replacement_node = tree.new('ShaderNodeCombineXYZ')
                    for i in range(3):
                        replacement_node.inputs[i].set_default_value(rgba[i])
                elif output.identifier == 'Fac':
                    replacement_node = tree.new('ShaderNodeValue')
                    replacement_node.outputs[0].set_default_value(rgba[:3])
                elif output.identifier == 'Alpha':
                    replacement_node = tree.new('ShaderNodeValue')
                    replacement_node.outputs[0].set_default_value(rgba[3])
                else:
                    raise Exception(f"Unexpected identifier: {output.identifier}")

                for other_socket in output.connections:
                    replacement_node.outputs[0].join(other_socket, move=False)

        elif node.be('ShaderNodeObjectInfo'):

            for output in node.outputs:

                if not output.connections:
                    continue

                if output.identifier == 'Material Index':
                    continue

                if check_only:
                    return True

                if output.identifier == 'Location':
                    replacement_node = tree.new('ShaderNodeCombineXYZ')
                    location = object.matrix_world.translation
                    for i in range(3):
                        replacement_node.inputs[i].set_default_value(location[i])
                elif output.identifier == 'Color':
                    replacement_node = tree.new('ShaderNodeCombineXYZ')
                    for i in range(3):
                        replacement_node.inputs[i].set_default_value(object.color[i])
                elif output.identifier == 'Alpha':
                    replacement_node = tree.new('ShaderNodeValue')
                    replacement_node.outputs[0].set_default_value(object.color[3])
                elif output.identifier == 'Object Index':
                    replacement_node = tree.new('ShaderNodeValue')
                    replacement_node.outputs[0].set_default_value(object.pass_index)
                elif output.identifier == 'Random':
                    # TODO: this is not the same random value
                    replacement_node = tree.new('ShaderNodeValue')
                    replacement_node.outputs[0].set_default_value(random.random())
                else:
                    raise Exception(f"Unexpected identifier: {output.identifier}")

                for other_socket in output.connections:
                    replacement_node.outputs[0].join(other_socket, move=False)

        elif node.be('ShaderNodeUVMap'):

            if bpy_uv.get_active_render_uv_layer(object):
                if node.uv_map and is_valid_uv_map(node.uv_map, object):
                    pass
                else:

                    if check_only:
                        return True

                    node.uv_map = bpy_uv.get_active_render_uv_layer(object).name

            elif object.type == 'MESH':

                if check_only:
                    return True

                warn(f"A mesh does not have any uv layers the output of the UV socket is (0, 0, 0): {object.data.name_full}")
                replacement_node = tree.new('ShaderNodeCombineXYZ')
                for other_socket in node.outputs[0].connections.copy():
                    replacement_node.outputs[0].join(other_socket, move=False)

            else:

                if check_only:
                    return True

                # TODO: to test, this should work for curves
                node.uv_map = 'UVMap'

        elif node.be('ShaderNodeNormalMap') and node.space == 'TANGENT':

            if bpy_uv.get_active_render_uv_layer(object):
                if node.uv_map and is_valid_uv_map(node.uv_map, object):
                    pass
                else:

                    if check_only:
                        return True

                    node.uv_map = bpy_uv.get_active_render_uv_layer(object).name

            elif object.type == 'MESH':
                # TODO: undefined behavior
                warn(f"A mesh does not have any uv layers for tangent space: {object.data.name_full}")

            else:

                if check_only:
                    return True

                # TODO: to test, this should work for curves
                node.uv_map = 'UVMap'

        elif node.be('ShaderNodeTexCoord') and node.object is None:

            if node.from_instancer:
                warn("ShaderNodeTexCoord.from_instancer not handled.")

            for output in node.outputs:

                if not output.connections:
                    continue

                if output.identifier == 'Generated':

                    if check_only:
                        return True

                    replacement_node = tree.new('ShaderNodeTexCoord')
                    replacement_node.object = get_texture_coordinates_generated_empty(object)
                    texture_coordinates_collection.objects.link(replacement_node.object)

                    if object.data and hasattr(object.data, 'texture_mesh') and object.data.texture_mesh:
                        warn("texture_mesh is not handled.")

                    for other_socket in output.connections:
                        replacement_node.outputs['Object'].join(other_socket, move=False)

                elif output.identifier == 'Object':

                    if check_only:
                        return True

                    replacement_node = tree.new('ShaderNodeNewGeometry').outputs['Position'].new('ShaderNodeMapping', vector_type='TEXTURE')

                    location, rotation, scale = object.matrix_world.decompose()

                    replacement_node['Location'] = location
                    replacement_node['Rotation'] = rotation.to_euler()
                    replacement_node['Scale'] = scale

                    for other_socket in output.connections:
                        replacement_node.outputs[0].join(other_socket, move=False)

                elif output.identifier == 'UV':

                    if check_only:
                        return True

                    if bpy_uv.get_active_render_uv_layer(object):
                        replacement_node = tree.new('ShaderNodeUVMap')
                        replacement_node.uv_map = bpy_uv.get_active_render_uv_layer(object).name
                    elif object.type == 'MESH':
                        warn(f"A mesh does not have any uv layers the output of the UV socket is (0, 0, 0): {object.data.name_full}")
                        replacement_node = tree.new('ShaderNodeCombineXYZ')
                    else:
                        # TODO: to test, this should work for curves
                        replacement_node = tree.new('ShaderNodeUVMap')
                        replacement_node.uv_map = 'UVMap'

                    for other_socket in output.connections:
                        replacement_node.outputs[0].join(other_socket, move=False)


        elif node.be('ShaderNodeAmbientOcclusion') and node.only_local == True:
            # TODO: as the node ignores all the shader context a way is to explode the mesh
            # separating all the parts belonging to other meshes
            # but in this case you cannot have nodes with and without this option
            # TODO: possible solution is to pre-bake all the Ambient Occlusion nodes
            # the pre-baking can be a general solution to all problems
            warn("No handling for only_local Ambient Occlusion node.")

        elif node.be('ShaderNodeTexImage') and node.projection == 'BOX':

            if check_only:
                return True

            # TODO: to preserve the projection is to recreate the node using 3 texture nodes
            # it uses the object's matrix to convert normals to object space to drive the projection
            # so when the rotation is applied — the projection changes to be world oriented
            # https://github.com/blender/blender/blob/af4974dfaa165ff1be0819c52afc99217d3627ba/source/blender/nodes/shader/nodes/node_shader_tex_image.cc#L115
            # https://github.com/blender/blender/blob/af4974dfaa165ff1be0819c52afc99217d3627ba/source/blender/gpu/shaders/material/gpu_shader_material_tex_image.glsl#L77
            mapping = node.inputs['Vector'].insert_new('ShaderNodeMapping')
            mapping.inputs['Rotation'].set_default_value(object.matrix_world.to_euler())

        elif node.be('ShaderNodeVertexColor'):

            if node.layer_name == '' and object.data.color_attributes.active_color_name:
                node.layer_name = object.data.color_attributes.active_color_name

            elif node.layer_name not in object.data.color_attributes:
                # after joining the objects the color attribute data is filled with white
                # instead of remaining black when as when the attribute is missing

                replacement_node = tree.new('ShaderNodeValue')

                for output in node.outputs:
                    for other_socket in output.connections:
                        replacement_node.outputs[0].join(other_socket, move=False)


    if check_only:
        return False


def make_node_trees_unique(node_tree: bpy.types.ShaderNodeTree, filter_func: typing.Optional[typing.Callable[[bpy.types.ShaderNodeTree], bool]] = None):
    """ Recursively make `ShaderNodeGroup` node trees unique. """

    pool = [node_tree]
    processed = set()

    while pool:

        tree = pool.pop()

        if tree in processed:
            continue
        processed.add(tree)

        for node in tree.nodes:

            if node.bl_idname != 'ShaderNodeGroup':
                continue

            if not node.node_tree:
                continue

            if bpy_utils.is_single_user(node.node_tree):
                continue

            if filter_func and not filter_func(node.node_tree):
                continue

            node.node_tree = node.node_tree.copy()
            pool.append(node.node_tree)


def is_node_tree_object_dependent(object: bpy.types.Object, node_tree: bpy.types.ShaderNodeTree):
    """ Recursively checks if a shader node tree is object dependent. """

    if make_node_tree_independent_from_object(object, node_tree, None, check_only = True):
        return True

    for node in node_tree.nodes:

        if node.bl_idname != 'ShaderNodeGroup':
            continue

        if not node.node_tree:
            continue

        if is_node_tree_object_dependent(object, node.node_tree):
            return True

    return False


def make_node_tree_independent_recursive(object: bpy.types.Object, node_tree: bpy.types.ShaderNodeTree, texture_coordinates_collection: 'bpy.types.Collection'):
    """ Recursively call `make_node_tree_independent_from_object`. """

    make_node_tree_independent_from_object(object, node_tree, texture_coordinates_collection)

    for node in node_tree.nodes:

        if node.bl_idname != 'ShaderNodeGroup':
            continue

        if not node.node_tree:
            continue

        make_node_tree_independent_from_object(object, node.node_tree, texture_coordinates_collection)


def make_material_independent_from_object(objects: typing.List[bpy.types.Object]):
    """
    Try to modify materials so when the objects are joined the materials look the same.

    The main use case is speedup texture baking.
    """

    print(f"{make_material_independent_from_object.__name__}...")

    texture_coordinates_collection = bpy.data.collections.new(f'__bc_temp_texture_coordinates_{uuid.uuid1().hex}')
    bpy.context.view_layer.layer_collection.collection.children.link(texture_coordinates_collection)
    bpy.context.view_layer.layer_collection.children.get(texture_coordinates_collection.name).exclude = True

    objects = bpy_utils.get_meshable_objects(objects)

    objects_with_materials = [object for object in objects if hasattr(object, 'material_slots') and any(slot.material for slot in object.material_slots)]


    def is_slot_object_dependent(slot: bpy.types.MaterialSlot):

        if not slot.material:
            return False

        if not slot.material.node_tree:
            return False

        return is_node_tree_object_dependent(slot.id_data, slot.material.node_tree)


    unify_color_attributes_format(objects_with_materials)

    depsgraph = bpy.context.evaluated_depsgraph_get()

    for object in objects_with_materials:

        for slot in object.material_slots:

            if not is_slot_object_dependent(slot):
                continue

            slot.material = slot.material.copy()

            make_node_trees_unique(slot.material.node_tree, filter_func = lambda tree: is_node_tree_object_dependent(object, tree))

            evaluated_object = object.evaluated_get(depsgraph)  # for the world matrix to be correct

            make_node_tree_independent_recursive(evaluated_object, slot.material.node_tree, texture_coordinates_collection)


    return texture_coordinates_collection


def merge_material_slots_with_the_same_materials(objects: typing.List[bpy.types.Object]):

    objects = bpy_utils.get_unique_data_objects(objects)

    with bpy_context.Focus(objects):

        for object in objects:
            bpy_context.simple_select(object)

            index_to_polygons = utils.list_by_key(object.data.polygons.values(), operator.attrgetter('material_index'))
            material_to_indexes = utils.list_by_key(index_to_polygons, lambda i: object.material_slots[i].material)

            bpy.ops.object.material_slot_remove_all()

            index_to_new_index = {}
            for new_index, (material, indexes) in enumerate(material_to_indexes.items()):

                bpy.ops.object.material_slot_add()
                object.material_slots[object.active_material_index].material = material

                for index in indexes:
                    index_to_new_index[index] = new_index

            for index, polygons in index_to_polygons.items():
                for polygon in polygons:
                    polygon.material_index = index_to_new_index[index]


def set_out_of_range_material_indexes_to_zero(objects: typing.List[bpy.types.Object]):

    for object in bpy_utils.get_unique_mesh_objects(objects):
        max_index = len(object.material_slots) - 1
        for polygon in object.data.polygons:
            if polygon.material_index > max_index:
                polygon.material_index = 0


def split_faces_by_materials(object: bpy.types.Object):

    copy = object.copy()
    copy.name = object.name + '(copy)'
    copy.data = object.data.copy()
    copy.data.name = object.data.name + '(copy)'


    with bpy_context.Focus(object, mode='EDIT'):

        bpy.ops.mesh.reveal()
        bpy.ops.mesh.select_mode(type='EDGE')

        for slot in object.material_slots:

            object.active_material_index = slot.slot_index

            bpy.ops.mesh.select_all(action='DESELECT')
            bpy.ops.object.material_slot_select()
            bpy.ops.mesh.split()


    def apply_data_transfer_modifier(from_object: bpy.types.Object, to_object: bpy.types.Object):

        modifier: bpy.types.DataTransferModifier = to_object.modifiers.new('', type='DATA_TRANSFER')

        modifier.object = from_object
        modifier.use_loop_data = True
        modifier.data_types_loops = {'CUSTOM_NORMAL'}

        bpy_modifier.apply_modifier(modifier)


    apply_data_transfer_modifier(copy, object)

    bpy.data.batch_remove((copy, copy.data))
