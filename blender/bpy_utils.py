import typing
import os
import sys
import traceback
import math
import collections
import random
import uuid
import operator
import hashlib
import re
import itertools
import contextlib


import bpy
from bpy import utils as b_utils
import mathutils
import bmesh

from . import bpy_bake
from . import bpy_context
from . import bake_settings as tool_settings_bake
from . import bpy_node
from . import bpy_uv
from . import bpy_modifier

from .. import tool_settings
from .. import utils


T_Objects = typing.TypeVar('T_Objects', bpy.types.Object, typing.List[bpy.types.Object], typing.Iterable[bpy.types.Object])


def get_view_layer_objects(view_layer: typing.Optional['bpy.types.ViewLayer'] = None) -> typing.List[bpy.types.Object]:
    """
    #113378 - Regression: Deleting Objects in a View Layer leaves None in the View Layer's .objects for the script duration
    https://projects.blender.org/blender/blender/issues/113378
    """
    if view_layer is None:
        return list(filter(None, bpy.context.view_layer.objects))
    else:
        return list(filter(None, view_layer.objects))


def iter_bone_names(action: bpy.types.Action):
    """ Iterate through bones names associated with the action. """

    re_bone_animation = re.compile(r'pose.bones\["(.+)"\]')

    for fcurve in action.fcurves:
        match = re_bone_animation.match(fcurve.data_path)
        if match:
            yield b_utils.unescape_identifier(match.group(1))


def duplicates_make_real():
    """ Convert particles to objects. """

    if bpy.app.version > (2,80,0):
        select_func = lambda object: object.select_set(True)
    else:
        select_func = lambda object: setattr(object, 'select', True)

    for object in get_view_layer_objects():

        if not any(modifier for modifier in object.modifiers if modifier.type == 'PARTICLE_SYSTEM' and modifier.show_viewport):
            continue

        bpy.ops.object.select_all(action='DESELECT')
        select_func(object)

        bpy.ops.object.duplicates_make_real()


if bpy.app.version >= (4, 0, 0):
    def get_visible_armature_bones(armature: bpy.types.Armature):
        visible_armature_collections = {c for c in armature.collections_all if c.is_visible}
        return tuple(bone.name for bone in armature.bones if not bone.hide and (not visible_armature_collections.isdisjoint(bone.collections) or not bone.collections))
else:
    def get_visible_armature_bones(armature: bpy.types.Armature):
        armature_layers = armature.layers
        return tuple(bone.name for bone in armature.bones if not bone.hide and any(a and b for a, b in zip(armature_layers, bone.layers)))


def get_armature(object: bpy.types.Object):
    """ Get an armature associated with the object. """

    if object.type == 'ARMATURE':
        return object
    else:
        return object.find_armature()


def get_actions(armature: bpy.types.Object) -> typing.List[bpy.types.Action]:
    """ Get actions associated with the armature object. """

    armature_bones_names = set(get_visible_armature_bones(armature.data))
    if not armature_bones_names:
        return []

    return [action for action in bpy.data.actions if not armature_bones_names.isdisjoint(iter_bone_names(action))]


TO_MESH_COMPATIBLE_OBJECT_TYPES = {
    'MESH',
    'CURVE',
    'SURFACE',
    'META',
    'FONT',
}


TO_MESH_INCOMPATIBLE_OBJECT_TYPES = {
    'CURVES',
    'POINTCLOUD',
    'VOLUME',
    'GPENCIL',
    'GREASEPENCIL',
    'ARMATURE',
    'LATTICE',
    'EMPTY',
    'LIGHT',
    'LIGHT_PROBE',
    'CAMERA',
    'SPEAKER',
}


def get_meshable_objects(objects: typing.List[bpy.types.Object]):
    """
    Filter out objects that cannot be directly converted to meshes.
    See `TO_MESH_COMPATIBLE_OBJECT_TYPES`.

    If `objects` is `None` then `view_layer.objects` is used.
    """
    return [object for object in objects if object.type in TO_MESH_COMPATIBLE_OBJECT_TYPES]


def _convert_to_mesh(objects: typing.List[bpy.types.Object]):

    metaball_family = f"__metaball_family_{uuid.uuid1().hex}"

    with bpy_context.Focus(objects):

        bpy.ops.object.make_local(type='SELECT_OBDATA')

        for object_type, objects_of_type in utils.list_by_key(objects, lambda x: x.type).items():
            if object_type == 'META':
                for index, metaball in enumerate(objects_of_type):
                    metaball.name = f"{metaball_family}_{index}"
            else:
                make_object_data_independent_from_other(objects_of_type)

        try:
            result = bpy.ops.object.convert(target = 'MESH', keep_original = False)
            if 'CANCELLED' in result:
                raise Exception(f"Conversion to mesh has been cancelled.")
        except Exception as e:
            raise Exception(f"Cannot convert to meshes: {objects}") from e

        # TODO: metaball conversion keeps the metaball object despite `keep_original = False`

        return bpy.context.selected_objects


def convert_to_mesh(objects: T_Objects) -> T_Objects:
    """ Convert objects to mesh objects using `bpy.ops.object.convert`. """
    if isinstance(objects, typing.Iterable):
        if objects:
            return _convert_to_mesh(objects)
        else:
            utils.print_in_color(utils.get_color_code(245, 115, 30, 10, 10, 10), "No objects to convert to mesh were provided.")
            return []
    else:
        return _convert_to_mesh([objects])[0]


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


def make_object_data_unique(objects: bpy.types.Object):
    """ Make all data block unique. """

    for object in objects:

        if not object.data:
            continue

        if object.data.users - object.data.use_fake_user == 1:
            continue

        object.data = object.data.copy()


def make_object_data_independent_from_other(objects: bpy.types.Object):
    """ Make the data independent from not included objects. """

    objects_by_data = utils.list_by_key(objects, operator.attrgetter('data'))

    for data, objects in objects_by_data.items():

        if not data:
            continue

        assert not data.users - data.use_fake_user < len(objects)

        if data.users - data.use_fake_user == len(objects):
            continue

        data_copy = data.copy()
        for object in objects:
            object.data = data_copy


def _focus(objects: typing.List[bpy.types.Object], view_layer: 'bpy.types.ViewLayer'):

    view_layer.update()
    view_layer_objects = get_view_layer_objects(view_layer)

    for object in view_layer_objects:
        if object in objects:
            object.hide_set(False, view_layer=view_layer)
            object.hide_viewport = False
            object.hide_select = False
            object.select_set(True, view_layer=view_layer)
        else:
            object.select_set(False, view_layer=view_layer)

    if objects:
        for object in objects:
            if object in view_layer_objects:
                view_layer.objects.active = object
                break

    return objects


def focus(objects: T_Objects, view_layer: 'bpy.types.ViewLayer' = None) -> T_Objects:
    """
    Deselect, unhide, select and make active the objects according to `view_layer`.

    If `view_layer` is `None` — `bpy.context.view_layer` is used.

    Returns the focused objects (the input).
    """

    if view_layer is None:
        view_layer = bpy.context.view_layer

    if isinstance(objects, typing.Iterable):
        return _focus(objects, view_layer)
    else:
        return _focus([objects], view_layer)[0]


def get_all_data_blocks():

    blocks = []
    for attr in dir(bpy.data):
        value = getattr(bpy.data, attr)
        if isinstance(value, bpy.types.bpy_prop_collection):
            blocks.extend(value)

    return blocks


def get_common_name(id_blocks: typing.Iterable[bpy.types.ID], default: typing.Optional[str] = None):

    name = utils.get_longest_substring((re.sub(r'\.\d+$', '', block.name) for block in id_blocks))

    if len(name) < 1:
        if default is None:
            if id_blocks:
                name = id_blocks[0].name
            else:
                name = 'UNNAMED'
        else:
            name = default

    # https://docs.blender.org/manual/en/latest/compositing/types/output/file_output.html
    # https://docs.blender.org/manual/en/latest/render/output/properties/output.html
    name = name.replace('#', '_')

    return name


def get_joinable_objects(objects: typing.List[bpy.types.Object]):
    return [object for object in objects if object.data and (object.type != 'OBJECT' or object.data.vertices)]


K_JOINED_OBJECTS_INFO = 'bc_joined_objects_info'


def get_object_info_key(object: bpy.types.Object):
    name = object.name[:62-16]
    return name + '@' + hashlib.sha256(object.name_full.encode()).hexdigest()[:62-len(name)]


def copy_custom_properties(object: bpy.types.Object):

    properties = {}

    for key, value in object.items():

        if hasattr(value, 'to_dict'):
            properties[key] = value.to_dict()
        elif hasattr(value, 'to_list'):
            properties[key] = value.to_list()
        elif isinstance(value, mathutils.Vector):
            properties[key] = tuple(value)
        else:
            properties[key] = value

    return properties


def get_object_info(object: bpy.types.Object):
    return dict(
        name = object.name,
        name_full = object.name_full,
        location = list(object.location),
        scale = list(object.scale),
        rotation_euler = list(object.rotation_euler),
        custom_properties = copy_custom_properties(object),
    )


def join_objects(objects: typing.List[bpy.types.Object], *, join_into: typing.Optional[bpy.types.Object] = None, name: str = None, generate_joined_objects_info = False):


    if join_into is not None:
        if not join_into in objects:
            objects = list(objects) + [join_into]
    else:
        if not objects:
            raise Exception("No objects to join were provided.")
        join_into = objects[0]


    incompatible_objects = set(objects) - set(get_joinable_objects(objects))
    if incompatible_objects:
        raise ValueError(
            f"Specified objects cannot be joined: {[o.name_full for o in objects]}"
            "\n\t" f"Incompatible: {[o.name_full for o in incompatible_objects]}"
        )


    if generate_joined_objects_info:

        joined_objects_info = {}

        for object in objects:
            joined_objects_info[get_object_info_key(object)] = get_object_info(object)


    objects = convert_to_mesh(objects)


    # if there are more than 8 unique uv layer names among the objects there are not going to be preserved
    uv_layers = []

    for object in objects:
        for uv_layer in object.data.uv_layers:
            uv_layers.append(uv_layer.name)

    uv_layers = utils.deduplicate(uv_layers)

    if len(uv_layers) > 8:
        raise RuntimeError(f"Fail to joint objects, more than 8 uv layers total: {[o.name_full for o in objects]}")


    make_object_data_unique(objects)

    if generate_joined_objects_info:

        for object in objects:
            vertex_group = object.vertex_groups.new(name=get_object_info_key(object))
            vertex_group.add(range(len(object.data.vertices)), 1, 'REPLACE')


    with bpy_context.Focus(objects):
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        bpy.context.view_layer.objects.active = result = join_into
        bpy.ops.object.join()
        # #126278 - Joining some meshes shows warning "Call save() to ensure ..." in console - blender - Blender Projects
        # https://projects.blender.org/blender/blender/issues/126278


    if name is not None:
        result.name = name


    if generate_joined_objects_info:

        info = result.get(K_JOINED_OBJECTS_INFO)
        if info is None:
            info = result[K_JOINED_OBJECTS_INFO] = {}

        info.update(joined_objects_info)
        result[K_JOINED_OBJECTS_INFO] = info


    return result


def abspath(path, library: typing.Union[bpy.types.Library, None] = None):
    return os.path.realpath(bpy.path.abspath(path, library = library))  # type: ignore


def get_block_abspath(block: typing.Union[bpy.types.Library, bpy.types.Image]):
    return abspath(block.filepath, block.library)  # type: ignore



def group_objects_by_material(objects: typing.List[bpy.types.Object]):

    objects_by_material: typing.Dict[bpy.types.Material, typing.List[bpy.types.Object]] = collections.defaultdict(list)

    for object in objects:
        for slot in object.material_slots:
            objects_by_material[slot.material].append(object)

    return dict((material, list(dict.fromkeys(objects))) for material, objects in objects_by_material.items())


def copy_action_range(action: bpy.types.Action, from_frame: float, to_frame: float, from_fps: typing.Optional[float] = None, to_fps: typing.Optional[float] = None, name: typing.Optional[str] = None):
    """ Copy the action from the specified range and fps and move to the zero frame. """

    action = action.copy()
    action.use_fake_user = True

    if name is not None:
        action.name = name

    scene_fps = bpy.context.scene.render.fps / bpy.context.scene.render.fps_base

    if from_fps is None:
        from_fps = scene_fps

    if to_fps is None:
        to_fps = scene_fps

    multiplayer = to_fps/from_fps

    for fc in action.fcurves:

        keyframe_to_delete = [keyframe for keyframe in fc.keyframe_points if keyframe.co[0] < from_frame or keyframe.co[0] > to_frame]
        for keyframe in reversed(keyframe_to_delete):
            fc.keyframe_points.remove(keyframe)

        if not fc.keyframe_points:
            continue

        min_keyframe = min(fc.keyframe_points, key = lambda x: x.co[0])
        offset = min_keyframe.co[0]

        for keyframe in fc.keyframe_points:
            keyframe.co_ui[0] = (keyframe.co_ui[0] - offset) * multiplayer

    return action


def get_compatible_armature_actions(objects: typing.List[bpy.types.Object]) -> typing.List[bpy.types.Action]:
    """ Get actions compatible with visible armature bones. """

    armatures = set(filter(None, (get_armature(object) for object in objects)))

    actions = []
    for armature in armatures:
        actions.extend(get_actions(armature))

    return actions

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
        with bpy_context.Focus(objects) as context:
            object_with_materials = next((object for object in context.view_layer.objects if hasattr(object, 'material_slots') and object.material_slots), None)
            if object_with_materials is not None:
                context.view_layer.objects.active = object_with_materials
                bpy.ops.object.material_slot_remove_unused()


    # assign a default material to empty material slots and objects with no materials
    for object in objects:

        if not hasattr(object, 'material_slots'):
            continue

        if not object.material_slots:
            object.data.materials.append(bpy_bake.get_default_material())
            continue

        for slot in object.material_slots:
            if slot.material is None:
                slot.material = bpy_bake.get_default_material()


    materials = list(group_objects_by_material(objects))


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

    for material in group_objects_by_material(objects):
        if material[Material_Bake_Type.HAS_ALPHA]:
            material[alpha_material_key] = True
        else:
            material[opaque_material_key] = True

    return alpha_material_key, opaque_material_key


def read_homefile(blend_file, load_ui = True):

    blend_dir = os.path.dirname(blend_file)

    try:
        bpy.ops.wm.read_homefile(filepath=blend_file, load_ui = load_ui)
    except RuntimeError:
        traceback.print_exc()

    for library in bpy.data.libraries:
        if library.filepath.startswith('//'):
            library.filepath = bpy.path.abspath(library.filepath, start=blend_dir, library=library.library)

    for image in bpy.data.images:
        if image.filepath.startswith('//'):
            image.filepath = bpy.path.abspath(image.filepath, start=blend_dir, library=image.library)

    for armature in bpy.context.view_layer.objects:

        if armature.type != 'ARMATURE':
            continue

        for bone in armature.pose.bones:
            bone.location = (0, 0, 0)
            bone.rotation_quaternion = (1, 0, 0, 0)
            bone.rotation_axis_angle = (0, 0, 1, 0)
            bone.rotation_euler = (0, 0, 0)
            bone.scale = (1, 1, 1)


def is_single_user(block: bpy.types.ID):
    return block.users - block.use_fake_user == 1


def get_unique_data_objects(objects: typing.List[bpy.types.Object]):
    return [objects_of_data[0] for data, objects_of_data in utils.list_by_key(objects, operator.attrgetter('data')).items() if data is not None]


def get_unique_mesh_objects(objects: typing.List[bpy.types.Object]):
    return [objects_of_data[0] for data, objects_of_data in utils.list_by_key(objects, operator.attrgetter('data')).items() if isinstance(data, bpy.types.Mesh)]


def get_unique_meshes(objects: typing.List[bpy.types.Object]) -> typing.List[bpy.types.Mesh]:
    return [object.data for object in get_unique_mesh_objects(objects)]


def get_view_layer_materials(view_layer: typing.Optional['bpy.types.ViewLayer'] = None):
    return [material for material in group_objects_by_material(get_view_layer_objects(view_layer)).keys() if material and not material.is_grease_pencil]



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

    objects = [object for object in get_unique_data_objects(objects) if hasattr(object.data, 'color_attributes')]

    color_attributes = {}

    for object in objects:
        for color_attribute in object.data.color_attributes:
            format = (color_attribute.data_type, color_attribute.domain)
            color_attributes.setdefault(color_attribute.name, set(format)).add(format)

    for color_attribute_name, formats in color_attributes.items():

        if len(formats) <= 1:
            continue

        for object in objects:
            if color_attribute_name in object.data.color_attributes.keys():
                object.data.color_attributes.active_color = object.data.color_attributes[color_attribute_name]
                bpy_context.call_for_object(object, bpy.ops.geometry.color_attribute_convert, domain='CORNER', data_type='FLOAT_COLOR')


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

            if is_single_user(node.node_tree):
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

    objects = get_meshable_objects(objects)

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

    for object in get_unique_data_objects(objects):

        index_to_polygons = utils.list_by_key(object.data.polygons.values(), operator.attrgetter('material_index'))
        material_to_indexes = utils.list_by_key(index_to_polygons, lambda i: object.material_slots[i].material)


        with bpy_context.Focus(object):
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

    for object in get_unique_mesh_objects(objects):
        max_index = len(object.material_slots) - 1
        for polygon in object.data.polygons:
            if polygon.material_index > max_index:
                polygon.material_index = 0


def get_closest_power_of_two(resolution: float, min_res = 64, max_res = 4096) -> int:

    variants = []

    def get_power_of_2(n):
        return round(math.log(n)/math.log(2))

    for i in range(get_power_of_2(min_res), get_power_of_2(max_res) + 1):
        n = pow(2, i)
        variants.append((n - resolution, n))

    closest_resolution = min(variants, key = lambda x: abs(x[0]))

    return closest_resolution[1]


def get_texture_resolution(objects: typing.List[bpy.types.Object], *, uv_layer_name: str, materials: typing.Optional[typing.List[bpy.types.Material]] = None, px_per_meter = 1024, min_res = 64, max_res = 4096):
    """ Get a texture resolution needed to achieve the given texel density. """

    from mathutils.geometry import area_tri


    with bpy_context.Focus(objects), bpy_context.State() as state:

        for object in objects:
            state.set(object.data.uv_layers, 'active', object.data.uv_layers[uv_layer_name])

        face_areas = []
        face_uv_areas = []

        for object in objects:

            if materials:
                material_indexes = set(index for index, material in enumerate(object.data.materials) if material in materials)
            else:
                material_indexes = None

            bm = bmesh.new()
            bm.from_mesh(object.data)
            bm.transform(object.matrix_world)

            face_to_uv_triangles = bpy_uv.get_uv_triangles(bm, bm.loops.layers.uv.verify())

            for face in bm.faces:

                if material_indexes is not None:
                    if face.material_index not in material_indexes:
                        continue

                face_areas.append(face.calc_area())
                face_uv_areas.append(sum(area_tri(*loop) for loop in face_to_uv_triangles[face]))

            bm.free()


        # total_face_area = sum(itertools.filterfalse(math.isnan, face_areas))
        total_uv_area = sum(itertools.filterfalse(math.isnan, face_uv_areas))

        texel_densities = []
        weights = []

        for face_area, face_area_uv in zip(face_areas, face_uv_areas):

            try:
                texel_density = math.sqrt(face_area / face_area_uv) * px_per_meter
                weight = face_area_uv / total_uv_area
            except ZeroDivisionError:
                continue

            texel_densities.append(texel_density)
            weights.append(weight)

        perfect_resolution = bpy_uv.get_weighted_percentile(texel_densities, 0.5, weights)

        print(f"Perfect resolution for {[o.name_full for o in objects]}:", round(perfect_resolution), 'px')

        final_resolution = get_closest_power_of_two(perfect_resolution, min_res, max_res)


    return final_resolution


def get_visible_objects():
    return [object for object in get_view_layer_objects() if object.visible_get()]


def split_objects_into_pre_joined_objects(objects: typing.List[bpy.types.Object], do_cleanup = True, force_rename = False):
    """ Split objects into separate objects using information generated by `join_objects`. """
    print("split_objects_into_pre_joined_objects...")

    result: typing.List[bpy.types.Object] = []


    # separate objects
    for object in objects:

        joined_objects_info = object.get(K_JOINED_OBJECTS_INFO)
        if not joined_objects_info:
            continue

        with bpy_context.Focus(object, 'EDIT'):

            bpy.ops.mesh.reveal()

            for object_id in joined_objects_info:

                object.vertex_groups.active_index = object.vertex_groups[object_id].index

                bpy.ops.mesh.select_all(action='DESELECT')
                bpy.ops.object.vertex_group_select()
                bpy.ops.mesh.separate(type='SELECTED')

            result.extend(bpy.context.selected_objects)
            result.remove(object)


        bpy.data.objects.remove(object)



    def get_vertex_group(object: bpy.types.Object, vertex_group_names):

        for vertex in object.data.vertices:
            for group_element in vertex.groups:

                if group_element.weight != 1:
                    continue

                vertex_group_name = object.vertex_groups[group_element.group].name

                if vertex_group_name in vertex_group_names:
                    return vertex_group_name

        raise Exception(f"Geometry group not found for object: {object.name_full}")


    # move pivots, restore properties
    for object in result:

        joined_objects_info = object.get(K_JOINED_OBJECTS_INFO)
        if not joined_objects_info:
            continue

        if not object.data.vertices:
            continue

        vertex_group_name = get_vertex_group(object, set(joined_objects_info))
        object_info = joined_objects_info[vertex_group_name]

        if force_rename:
            other_object_with_the_same_name = bpy.data.objects.get(object_info['name'])
            if other_object_with_the_same_name:
                other_object_with_the_same_name.name = other_object_with_the_same_name.name + '1'

            object.name = object_info['name']

        for key, value in object_info['custom_properties'].items():

            if key == 'cycles':
                # Cannot assign a 'IDPropertyGroup' value to the existing 'cycles' Group IDProperty
                continue

            try:
                object[key] = value
            except TypeError:
                traceback.print_exc()

        with bpy_context.Focus(object):
            bpy.context.scene.cursor.location = object_info['location']
            bpy.ops.object.origin_set(type='ORIGIN_CURSOR', center='MEDIAN')


    # clean up
    if do_cleanup:

        for object in result:

            joined_objects_info = object.get(K_JOINED_OBJECTS_INFO)
            if not joined_objects_info:
                continue

            for object_id in joined_objects_info:
                object.vertex_groups.remove(object.vertex_groups[object_id])

            del object[K_JOINED_OBJECTS_INFO]


    return result



def get_object_group_by_parent(objects: typing.List[bpy.types.Object]):
    """ Assuming there is no cyclic dependency in object parenting. The algorithm is not efficient. """

    user_map = bpy.data.user_map(subset=objects, key_types={'OBJECT'}, value_types={'OBJECT'})

    sub_groups = []

    for key, items in user_map.items():

        for sub_group in sub_groups:
            if key in sub_group or any(item in sub_group for item in items):
                sub_group.add(key)
                sub_group.update(items)
                break
        else:
            sub_groups.append(set([key, *items]))

    group_by_parent = {}

    for group in sub_groups:
        for object in group:
            if object.parent is None:
                group_by_parent[object] = group
                break

    return group_by_parent


def get_aabb(objects: typing.List[bpy.types.Object]):

    depsgraph = bpy.context.evaluated_depsgraph_get()

    vertices = []
    for object in objects:
        evaluated_object = object.evaluated_get(depsgraph)
        bound_box = evaluated_object.bound_box
        matrix_world = evaluated_object.matrix_world
        vertices.extend([matrix_world @ mathutils.Vector(v) for v in bound_box])

    xs = []
    ys = []
    zs = []
    for v in vertices:
        xs.append(v[0])
        ys.append(v[1])
        zs.append(v[2])

    max_x = max(xs)
    min_x = min(xs)

    max_y = max(ys)
    min_y = min(ys)

    max_z = max(zs)
    min_z = min(zs)

    x = abs(max_x - min_x)
    y = abs(max_y - min_y)
    z = abs(max_z - min_z)

    loc_x = (max_x + min_x)/2
    loc_y = (max_y + min_y)/2
    loc_z = (max_z + min_z)/2

    return mathutils.Vector((x, y, z)), mathutils.Vector((loc_x, loc_y, loc_z))


K_EXPLODED_BAKE_ORIGINAL_LOCATION = 'bc_exploded_bake_original_location'


def space_out_objects(objects: typing.List[bpy.types.Object]):

    group_offset = 0

    for parent, group in get_object_group_by_parent(objects).items():

        dimensions, center = get_aabb(group)

        offset = parent.location - center

        new_location = mathutils.Vector((0, 0, 0)) + offset
        new_location.x = group_offset

        parent[K_EXPLODED_BAKE_ORIGINAL_LOCATION] = parent.location

        parent.location = new_location

        group_offset += max(4, dimensions[0] * dimensions[0])


def revert_space_out_objects(objects: typing.List[bpy.types.Object]):

    for object in objects:
        location = object.get(K_EXPLODED_BAKE_ORIGINAL_LOCATION)
        if location is not None:  # only top parent objects in groups have this property
            object.location = location


def deep_copy_objects(objects: typing.List[bpy.types.Object]):

    with bpy_context.Focus(objects), bpy_context.State() as state:

        for attr in dir(bpy.context.preferences.edit):
            if attr.startswith('use_duplicate_'):
                state.set(bpy.context.preferences.edit, attr, True)

        bpy.ops.object.duplicate()

        return bpy.context.selected_objects


def move_objects_to_new_collection(objects: typing.List[bpy.types.Object], collection_name: str):

    baked_copy_collection = bpy.data.collections.new(collection_name)
    bpy.context.scene.collection.children.link(baked_copy_collection)

    for layer_collection in bpy.context.view_layer.layer_collection.children:
        if layer_collection.collection == baked_copy_collection:
            break

    for object in objects:

        for collection in object.users_collection:
            collection.objects.unlink(object)

        baked_copy_collection.objects.link(object)

    return layer_collection


def pack_copy_bake(objects: typing.List[bpy.types.Object], settings: tool_settings.Bake_Materials, *,
            bake_settings: typing.Optional[tool_settings.Bake] = None,
            pack_settings: typing.Optional[tool_settings.Pack_UVs] = None,
        ):


    if not objects:
        utils.print_in_color(utils.get_color_code(245, 115, 30, 10, 10, 10), "No objects were provided for baking.")
        return []


    incompatible_objects = set(objects) - set(get_meshable_objects(objects))
    if incompatible_objects:
        raise ValueError(
            f"Specified objects cannot be baked, type must be MESH or convertible to MESH."
            "\n"
            f"Objects: {[o.name_full for o in objects]}"
            "\n"
            f"Incompatible: {[o.name_full for o in incompatible_objects]}"
        )


    with bpy_context.Global_Optimizations(), bpy_context.Focus(objects), bpy_context.State() as state:

        ## disable animation for consistency
        for object in objects:
            if object.animation_data:

                for driver in object.animation_data.drivers:
                    state.set(driver, 'mute', True)

                for nla_track in object.animation_data.nla_tracks:
                    state.set(nla_track, 'mute', True)


        ## process the materials

        # this is needed in order to split_into_alpha_and_non_alpha_groups to work
        # and for the bake itself
        # TODO: it might be possible to convert the materials on the bake proxy and leave the original intact
        # but to sort them into alpha and non-alpha they should be converter first

        if settings.convert_materials:
            convert_materials_to_principled(objects, remove_unused=False)

        set_out_of_range_material_indexes_to_zero(objects)
        merge_material_slots_with_the_same_materials(objects)

        alpha_material_key, opaque_material_key = split_into_alpha_and_non_alpha_groups(objects)


        ## uv pack

        # doing the pack inside the function because it depends on the material groups

        materials = list(group_objects_by_material(objects))

        def pack_uvs(resolution: int, material_key: str):

            _pack_settings = tool_settings.Pack_UVs(
                resolution = resolution,
                uv_layer_name = settings.uv_layer_bake,
                material_key = material_key,
                average_uv_scale = False,
            )._update(pack_settings)

            bpy_uv.pack(objects, _pack_settings)


        def ensure_pixel_per_island(resolution: int, material_key: str):

            _pack_settings = tool_settings.Pack_UVs(
                    resolution = resolution,
                    uv_layer_name = settings.uv_layer_bake,
                    material_key = material_key,
                )

            bpy_uv.ensure_pixel_per_island(objects, _pack_settings)




        ## collect bake settings

        pre_bake_tasks: typing.List[tool_settings.Bake] = []
        bake_tasks: typing.List[tool_settings.Bake] = []

        # TODO: this only works for the materials that has been processed, not others in the scene
        environment_has_transparent_materials = any(m for m in bpy.data.materials if m.get(alpha_material_key))

        for material_key in (opaque_material_key, alpha_material_key):

            material_group = [m for m in materials if m.get(material_key)]
            if not material_group:
                continue


            _bake_settings = tool_settings.Bake(uv_layer_name = settings.uv_layer_bake, image_dir = settings.image_dir)._update(bake_settings)

            if settings.resolution:
                # the final resolution is hard set
                _bake_settings.resolution = settings.resolution
            else:
                # pre packing to calculate the texel density
                # to match the final resolution, we have to pack a second time for preciseness
                pack_uvs(get_closest_power_of_two((settings.min_resolution + settings.max_resolution)/2), material_key)

                # calculate target resolution
                _bake_settings.resolution = get_texture_resolution(
                    objects,
                    uv_layer_name = settings.uv_layer_bake,
                    materials = material_group,
                    px_per_meter = settings.texel_density,
                    min_res = settings.min_resolution,
                    max_res = settings.max_resolution,
                )

            pack_uvs(_bake_settings.resolution, material_key)
            ensure_pixel_per_island(_bake_settings.resolution, material_key)


            if settings.denoise_all:

                view_space_normals_bake_type = tool_settings_bake.View_Space_Normal(use_denoise=settings.denoise_all)

                pre_bake_settings = _bake_settings._get_copy()

                pre_bake_settings.image_dir = os.path.join(bpy.app.tempdir, '__bc_pre_baked')
                pre_bake_settings.create_materials = False
                pre_bake_settings.do_downscale = False
                pre_bake_settings.use_anti_aliasing = False
                pre_bake_settings.material_key = material_key
                pre_bake_settings.bake_types = [view_space_normals_bake_type]
                pre_bake_settings.texture_name_prefix = uuid.uuid1().hex

                pre_bake_tasks.append(pre_bake_settings)

                _bake_settings.view_space_normals_id = view_space_normals_bake_type._uuid


            bake_types = []


            bake_types.append([
                tool_settings_bake.AO_Diffuse(faster=settings.faster_ao_bake, environment_has_transparent_materials = environment_has_transparent_materials),
                tool_settings_bake.Roughness(use_denoise=settings.denoise_all),
                tool_settings_bake.Metallic(use_denoise=settings.denoise_all)
            ])


            if any(material[Material_Bake_Type.HAS_EMISSION] for material in material_group):
                bake_types.append(tool_settings_bake.Emission(use_denoise=settings.denoise_all))

            if any(material[Material_Bake_Type.HAS_NORMALS] for material in material_group):
                bake_types.append(tool_settings_bake.Normal(uv_layer=_bake_settings.uv_layer_name, use_denoise=settings.denoise_all))

            if material_key == alpha_material_key:
                bake_types.append([tool_settings_bake.Base_Color(use_denoise=settings.denoise_all), tool_settings_bake.Alpha(use_denoise=settings.denoise_all)])
            else:
                bake_types.append(tool_settings_bake.Base_Color(use_denoise=settings.denoise_all))

            _bake_settings.material_key = material_key
            _bake_settings.bake_types = bake_types

            if _bake_settings.texture_name_prefix:
                if material_key == alpha_material_key:
                    _bake_settings.texture_name_prefix = _bake_settings.texture_name_prefix + '_alpha'
                else:
                    _bake_settings.texture_name_prefix = _bake_settings.texture_name_prefix
            else:
                if material_key == alpha_material_key:
                    _bake_settings.texture_name_prefix = get_common_name(objects, 'mesh') + '_alpha'
                else:
                    _bake_settings.texture_name_prefix = get_common_name(objects, 'mesh')


            bake_tasks.append(_bake_settings)


        ## join the bake proxy object


        objects_copy = deep_copy_objects(objects)

        if settings.convert_materials:
            texture_coordinates_collection = make_material_independent_from_object(objects_copy)

        convert_to_mesh(objects_copy)

        if settings.isolate_object_hierarchies:
            space_out_objects(objects_copy)

        bake_proxy = join_objects(objects_copy, name = '__bc_bake')


        if settings.split_faces_by_materials:
            split_faces_by_materials(bake_proxy)


        ## remove unused materials
        # Blender 5.0
        # merge_material_slots_with_the_same_materials can leave objects with 0 polygons without materials
        # joining the objects with no materials creates an empty material slot for them
        # the empty material slot fail the bake
        # related
        # https://projects.blender.org/blender/blender/issues/146878

        with bpy_context.Focus(bake_proxy):
            bpy.ops.object.material_slot_remove_unused()


        ## bake
        for pre_bake_settings in pre_bake_tasks:
            bpy_bake.bake([bake_proxy], pre_bake_settings)

        for bake_settings in bake_tasks:
            if settings.pre_bake_labels:
                with Pre_Baked([bake_proxy], settings.pre_bake_labels, bake_settings):
                    bpy_bake.bake([bake_proxy], bake_settings)
            else:
                bpy_bake.bake([bake_proxy], bake_settings)


        ## assign the baked materials

        def get_material(key: str):

            for slot in bake_proxy.material_slots:

                if not slot.material:
                    continue

                for bake_settings in bake_tasks:
                    if slot.material.get(bake_settings._K_MATERIAL_KEY) == key:
                        return slot.material


        for object in objects:
            for material_slot in object.material_slots:
                for material_key in (opaque_material_key, alpha_material_key):
                    if material_slot.material.get(material_key):
                        material_slot.material = get_material(material_key)


        merge_material_slots_with_the_same_materials(objects)


        ## delete temporal objects

        bpy.data.batch_remove((bake_proxy.data, bake_proxy))

        if settings.convert_materials:
            bpy.data.batch_remove(set(texture_coordinates_collection.objects))
            bpy.data.collections.remove(texture_coordinates_collection)


        return objects


def is_smooth_modifier(modifier: bpy.types.Modifier):

    if modifier.type != 'NODES':
        return False

    if not modifier.node_group:
        return False

    return 'Smooth by Angle' in modifier.node_group.name



def apply_modifiers(objects: typing.List[bpy.types.Object], *, ignore_name = '', include_name = '', ignore_type = set(), include_type = set()):
    """
    If `ignore_name` is not empty modifiers with names matching the regular expression will be ignored.

    E.g. `ignore_name = '@'` — ignore all modifiers starting with "@".
    """

    for object in objects:


        modifiers_to_apply = []

        for modifier in list(object.modifiers):

            if ignore_type and modifier.type in ignore_type:
                continue

            if include_type and modifier.type not in include_type:
                continue

            if ignore_name and re.match(ignore_name, modifier.name):
                continue

            if include_name and not re.match(include_name, modifier.name):
                continue

            modifiers_to_apply.append(modifier.name)

        with bpy_context.Focus(object):
            for name in modifiers_to_apply:
                bpy_modifier.apply_modifier(object.modifiers[name])



def get_unique_materials(objects: typing.List[bpy.types.Object]):

    materials: typing.List[bpy.types.Material] = []

    for object in objects:
        for slot in object.material_slots:
            if slot.material:
                materials.append(slot.material)

    return utils.deduplicate(materials)


def label_mix_shader_nodes(objects: typing.List[bpy.types.Object]):

    prebake_labels: typing.List[str] = []
    prebake_uuid = uuid.uuid1().hex


    def get_pre_bake_label(index: int):
        return 'prebake_' + str(index) + '_' + prebake_uuid


    for material in get_unique_materials(objects):

        if not material.node_tree:
            continue

        tree = bpy_node.Shader_Tree_Wrapper(material.node_tree)

        prebake_index = 0

        for node in reversed(tree.output.inputs[0].descendants):

            if not node.be('ShaderNodeVectorMath'):
                continue

            if not node.inputs[0].connections:
                continue

            if node.label != 'BC_PRE_BAKE_TARGET':
                continue

            factor_input_marker = node

            prebake_label = get_pre_bake_label(prebake_index)

            factor_input_marker.label = prebake_label

            if not prebake_label in prebake_labels:
                prebake_labels.append(prebake_label)

            material[prebake_label] = True

            prebake_index += 1


    return prebake_labels


@contextlib.contextmanager
def Pre_Baked(objects: typing.List[bpy.types.Object], prebake_labels: typing.List[str], settings: tool_settings.Bake = None):

    original_material_key = settings.material_key

    settings = tool_settings.Bake()._update(settings)
    settings.create_materials = False
    settings.do_downscale = False
    settings.use_anti_aliasing = False
    settings.image_dir = os.path.join(bpy.app.tempdir, '__bc_pre_baked')

    affected_materials: typing.Set[bpy.types.Material] = set()

    for prebake_label in prebake_labels:

        materials = [m for m in get_unique_materials(objects) if m.get(prebake_label) and m.get(original_material_key)]

        _materials: typing.List[bpy.types.Material] = []
        for material in materials:
            tree = bpy_node.Shader_Tree_Wrapper(material.node_tree)
            if any(node.label == prebake_label for node in tree.output.inputs[0].descendants):
                _materials.append(material)

        materials = _materials

        map_id = uuid.uuid1().hex

        for material in materials:
            material[map_id] = True

        settings.bake_types = [tool_settings_bake.Buffer_Factor(node_label=prebake_label, _identifier = 'buffer' + map_id)]

        settings.material_key = map_id

        pre_baked_images = bpy_bake.bake(objects, settings)


        # replace nodes with baked images
        for material in materials:

            tree = bpy_node.Shader_Tree_Wrapper(material.node_tree)

            image_texture = tree.new('ShaderNodeTexImage', image = pre_baked_images[0])

            image_texture.inputs[0].new('ShaderNodeUVMap', uv_map = settings.uv_layer_name)

            image_texture.label = 'BAKED' + prebake_label

            for node in tree:
                if node.label == prebake_label:
                    for other in node.outputs[0].connections:
                        image_texture.outputs[0].join(other)

            affected_materials.add(material)

    try:
        yield None

    finally:

        for prebake_label in prebake_labels:

            # revert the node replacement
            for material in affected_materials:

                tree = bpy_node.Shader_Tree_Wrapper(material.node_tree)

                def get_baked_image_node():
                    for node in tree:
                        if node.label == 'BAKED' + prebake_label:
                            return node

                for node in tree:
                    if node.label == prebake_label:
                        for other in get_baked_image_node().outputs[0].connections:
                            node.outputs[0].join(other)


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
