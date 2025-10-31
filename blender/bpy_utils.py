import typing
import os
import sys
import traceback
import math
import collections
import tempfile
import subprocess
import random
import uuid
import operator
import hashlib
import re

import bpy
from bpy import utils as b_utils
import mathutils
import bmesh

from . import bpy_bake
from . import bpy_context
from . import bake_settings as tool_settings_bake
from . import bpy_node
from . import bpy_uv

from .. import tool_settings
from .. import utils


T_Objects = typing.TypeVar('T_Objects', bpy.types.Object, typing.List[bpy.types.Object], typing.Iterable[bpy.types.Object])


def get_view_layer_objects(view_layer: typing.Optional[bpy.types.ViewLayer] = None) -> typing.List[bpy.types.Object]:
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

    with bpy_context.Focus_Objects(objects):

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
        return _convert_to_mesh(objects)
    else:
        return _convert_to_mesh([objects])[0]


def make_materials_unique(objects: typing.List[bpy.types.Object], filter_func: typing.Optional[typing.Callable[[bpy.types.Material], bool]] = None):
    """ Make a unique copy of a material for each material slot of an object. """

    for object in objects:
        for slot in object.material_slots:

            if not slot.material:
                continue

            if slot.material.users - slot.material.use_fake_user == 1:
                continue

            if filter_func is not None:
                if not filter_func(slot.material):
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


def _focus(objects: typing.List[bpy.types.Object], view_layer: bpy.types.ViewLayer):

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


def focus(objects: T_Objects, view_layer: bpy.types.ViewLayer = None) -> T_Objects:
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


def get_joinable_objects(objects: typing.List[bpy.types.Object]):
    return [object for object in objects if object.data and (object.type != 'OBJECT' or object.data.vertices)]


K_MERGED_OBJECTS_INFO = 'bc_merged_objects_info'


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


def merge_objects(objects: typing.List[bpy.types.Object], *, merge_into: typing.Optional[bpy.types.Object] = None, name: str = None, generate_merged_objects_info = False):


    if merge_into is not None:
        if not merge_into in objects:
            objects = list(objects) + [merge_into]
    else:
        merge_into = objects[0]


    incompatible_objects = set(objects) - set(get_joinable_objects(objects))
    if incompatible_objects:
        raise ValueError(f"Specified objects cannot be merged: {[o.name_full for o in objects]}\nIncompatible: {[o.name_full for o in incompatible_objects]}")


    if generate_merged_objects_info:
        current_merge_objects_info = {}

        for object in objects:
            current_merge_objects_info[get_object_info_key(object)] = get_object_info(object)


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

    if generate_merged_objects_info:
        for object in objects:
            vertex_group = object.vertex_groups.new(name=get_object_info_key(object))
            vertex_group.add(range(len(object.data.vertices)), 1, 'REPLACE')


    with bpy_context.Focus_Objects(objects):
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        bpy.context.view_layer.objects.active = merged_object = merge_into
        bpy.ops.object.join()
        # #126278 - Joining some meshes shows warning "Call save() to ensure ..." in console - blender - Blender Projects
        # https://projects.blender.org/blender/blender/issues/126278


    if name is not None:
        merged_object.name = name


    if generate_merged_objects_info:
        bc_merged_objects_info = merged_object.get(K_MERGED_OBJECTS_INFO)
        if bc_merged_objects_info is None:
            bc_merged_objects_info = merged_object[K_MERGED_OBJECTS_INFO] = {}
        bc_merged_objects_info.update(current_merge_objects_info)
        merged_object[K_MERGED_OBJECTS_INFO] = bc_merged_objects_info


    return merged_object


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



def unwrap_ministry_of_flat_with_fallback(objects: typing.List[bpy.types.Object], settings: tool_settings.UVs, ministry_of_flat_settings: typing.Optional[tool_settings.Ministry_Of_Flat] = None):

    ministry_of_flat_settings = tool_settings.Ministry_Of_Flat(vertex_weld=False, rasterization_resolution=1, packing_iterations=1)._update(ministry_of_flat_settings)

    for object in objects:

        if not object.data.polygons:
            utils.print_in_color(utils.get_foreground_color_code(217, 103, 41), f"Object has no faces: {object.name_full}")
            continue

        object_copy = bpy_uv.get_object_copy_for_uv_unwrap(object)
        object_copy.name = "UV_UNWRAP_" + object_copy.name

        with bpy_context.Isolate_Focus([object_copy], mode='EDIT'):

            bpy.ops.mesh.reveal()
            bpy.ops.uv.reveal()
            bpy_context.call_in_uv_editor(bpy.ops.uv.select_mode, type='VERTEX', can_be_canceled = True)
            bpy.context.scene.tool_settings.use_uv_select_sync = False

            # mark seams by materials
            bpy.ops.mesh.select_mode(use_extend=False, use_expand=False, type='EDGE')
            bpy.ops.mesh.select_all(action='DESELECT')

            for material_index in range(len(object_copy.material_slots)):

                object_copy.active_material_index = material_index

                bpy.ops.mesh.select_all(action='DESELECT')
                bpy.ops.object.material_slot_select()
                bpy.ops.mesh.region_to_loop()
                bpy.ops.mesh.mark_seam(clear=False)

            b_mesh = bmesh.from_edit_mesh(object_copy.data)
            b_mesh.edges.ensure_lookup_table()

            edges = [edge for edge in b_mesh.edges if edge.seam]
            bmesh.ops.split_edges(b_mesh, edges = edges)

            bmesh.update_edit_mesh(object_copy.data, loop_triangles=False, destructive=False)

            # unwrapping
            try:
                with tempfile.TemporaryDirectory() as temp_dir:

                    bpy_uv.unwrap_ministry_of_flat(object_copy, temp_dir, settings = ministry_of_flat_settings, uv_layer_name = settings.uv_layer_name)
            except utils.Fallback as e:

                utils.print_in_color(utils.get_color_code(240,0,0, 0,0,0), f"Fallback to smart_project: {e}")

                object_copy.data.uv_layers.active = object_copy.data.uv_layers[settings.uv_layer_name]

                bpy.ops.mesh.select_all(action='SELECT')
                bpy.ops.uv.select_all(action='SELECT')
                bpy.ops.uv.pin(clear=True)
                bpy.ops.uv.smart_project(island_margin = settings._uv_island_margin_fraction / 0.8, angle_limit = math.radians(settings.smart_project_angle_limit))

            do_reunwrap = settings.reunwrap_bad_uvs_with_minimal_stretch or settings.reunwrap_all_with_minimal_stretch

            if do_reunwrap and 'iterations' in repr(bpy.ops.uv.unwrap):

                bpy_uv.mark_seams_from_islands(object_copy, settings.uv_layer_name)

                if settings.reunwrap_all_with_minimal_stretch:
                    bpy.ops.mesh.select_all(action='SELECT')
                    bpy.ops.uv.select_all(action='SELECT')
                    bpy_context.call_in_uv_editor(bpy.ops.uv.unwrap, method='MINIMUM_STRETCH', fill_holes=True, no_flip=True, can_be_canceled=True)

                bpy_uv.reunwrap_bad_uvs([object_copy])


        bpy_uv.copy_uv(object_copy, object, settings.uv_layer_name)

        bpy.data.objects.remove(object_copy)

        if settings.mark_seams_from_islands:
            bpy_uv.mark_seams_from_islands(object, settings.uv_layer_name)


def create_uvs(objects: typing.List[bpy.types.Object], resolution: int, material_keys: typing.Optional[typing.List[str]] = None):
    print(f"{create_uvs.__name__}...")

    settings = tool_settings.UVs(resolution=resolution)
    settings._set_suggested_padding()

    objects = get_unique_mesh_objects(objects)

    with bpy_context.State() as state, bpy_context.Bpy_State() as bpy_state:

        for object in objects:
            if object.animation_data:
                for driver in object.animation_data.drivers:
                    state.set(driver, 'mute', True)

        for object in objects:
            for modifier in object.modifiers:
                bpy_state.set(modifier, 'show_viewport', False)

        bpy_uv.ensure_uv_layer(objects, settings.uv_layer_name)

        if tool_settings.Ministry_Of_Flat._executable_exists:
            unwrap_ministry_of_flat_with_fallback(objects, settings)
            settings.do_unwrap = False
        else:
            settings.do_unwrap = True

        if settings.merge:
            if material_keys:
                for material_key in material_keys:
                    settings.material_key = material_key
                    bpy_uv.unwrap_and_pack(objects, settings)
            else:
                bpy_uv.unwrap_and_pack(objects, settings)

        else:
            for material, _objects in group_objects_by_material(objects).items():

                if material_keys and not any(material.get(key) for key in material_keys):
                    continue

                bpy_uv.unwrap_and_pack(_objects, settings)

        bpy_uv.ensure_pixel_per_island(objects, settings)

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
        with bpy_context.Focus_Objects(objects) as context:
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

        if material.use_nodes:
            continue

        material.use_nodes = True

        tree = bpy_node.Shader_Tree_Wrapper(material.node_tree)

        tree.reset_nodes()

        principled = tree.output[0]

        principled.set_input('Base Color', material.diffuse_color)
        principled.set_input('Metallic', material.metallic)
        principled.set_input('Specular', material.specular_intensity)
        principled.set_input('Roughness', material.roughness)


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
    opaque_material_key = f"__bc_non_alpha_material_{uuid.uuid1().hex}"

    for material in group_objects_by_material(objects):
        if material[Material_Bake_Type.HAS_ALPHA]:
            material[alpha_material_key] = True
        else:
            material[opaque_material_key] = True

    return alpha_material_key, opaque_material_key


def bake_materials(objects: typing.List[bpy.types.Object], image_dir: str, resolution: int, **bake_kwargs):

    with bpy_context.Global_Optimizations(), bpy_context.Bpy_State() as bpy_state_0:

        # this can help to reduce `Dependency cycle detected` spam in rigs
        for o in bpy.data.objects:
            if o.type == 'ARMATURE':
                bpy_state_0.set(o.pose, 'ik_solver', 'LEGACY')


        convert_materials_to_principled(objects)

        set_out_of_range_material_indexes_to_zero(objects)

        alpha_material_key, opaque_material_key = split_into_alpha_and_non_alpha_groups(objects)


        create_uvs(objects, resolution, (alpha_material_key, opaque_material_key))


        bake_settings = tool_settings.Bake(image_dir = image_dir, resolution = resolution, **bake_kwargs)
        bake_object_by_material_key(objects, alpha_material_key, opaque_material_key, bake_settings)


        merge_material_slots_with_the_same_materials(objects)


def read_homefile(blend_file, load_ui = True):

    blend_dir = os.path.dirname(blend_file)

    try:
        bpy.ops.wm.read_homefile(filepath=blend_file, load_ui = load_ui)
    except RuntimeError:
        traceback.print_exc(file=sys.stderr)

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


def get_view_layer_materials(view_layer: typing.Optional[bpy.types.ViewLayer] = None):
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
                bpy_context.call_for_object(object, bpy.ops.geometry.color_attribute_convert, domain='POINT', data_type='FLOAT_COLOR')


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
    make_materials_unique(objects_with_materials)

    warning_color = utils.get_color_code(217, 69, 143, 0,0,0)

    def warn(*args):
         utils.print_in_color(warning_color, 'WARNING:', *args)


    unify_color_attributes_format(objects_with_materials)


    def get_active_render_uv_layer(object: bpy.types.Object):

        if not object.data:
            return

        if not hasattr(object.data, 'uv_layers'):
            return

        for layer in object.data.uv_layers:
            if layer.active_render:
                return layer

    def is_valid_uv_map(uv_map: str, object: bpy.types.Object):

        # TODO: handle non mesh objects

        if not object.data:
            return False

        if not hasattr(object.data, 'uv_layers'):
            return False

        return uv_map in object.data.uv_layers.keys()


    depsgraph = bpy.context.evaluated_depsgraph_get()

    for object in objects_with_materials:

        evaluated_object = object.evaluated_get(depsgraph)

        for slot in object.material_slots:

            if not slot.material:
                continue

            if not slot.material.node_tree:
                continue

            tree = bpy_node.Shader_Tree_Wrapper(slot.material.node_tree)

            if tree.output is None:
                continue

            def get_groups():
                return [node for node in tree.surface_input.descendants if node.be('ShaderNodeGroup')]

            groups = get_groups()
            while groups:
                tree.ungroup(groups)
                groups = get_groups()


            if get_active_render_uv_layer(object):

                # Joining objects deletes UV map #64245
                # https://projects.blender.org/blender/blender/issues/64245

                render_uv_layer = get_active_render_uv_layer(object).name

                for node in reversed(tree.surface_input.descendants):
                    if node.be('ShaderNodeTexImage') and not node.inputs['Vector'].connections:
                        node.inputs['Vector'].new('ShaderNodeUVMap', uv_map=render_uv_layer)


            for node in reversed(tree.surface_input.descendants):
                if node.be(GENERATED_COORDINATES_TEXTURE_NODE) and not node.inputs['Vector'].connections and node.inputs['Vector'].enabled:
                    node.inputs['Vector'].new('ShaderNodeTexCoord', 'Generated')


            for node in reversed(tree.surface_input.descendants):

                if node.be('ShaderNodeAttribute') and node.attribute_type in ('OBJECT', 'INSTANCER'):

                    if node.attribute_type == 'INSTANCER':
                        warn("ShaderNodeAttribute.attribute_type == 'INSTANCER' handled as 'OBJECT'")

                    rgba = find_attribute_rgba(object, node.attribute_name)

                    for output in node.outputs:

                        if not output.connections:
                            continue

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

                        if output.identifier == 'Location':
                            replacement_node = tree.new('ShaderNodeCombineXYZ')
                            location = evaluated_object.matrix_world.translation
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
                        elif output.identifier == 'Material Index':
                            continue
                        elif output.identifier == 'Random':
                            # TODO: this is not the same random value
                            replacement_node = tree.new('ShaderNodeValue')
                            replacement_node.outputs[0].set_default_value(random.random())
                        else:
                            raise Exception(f"Unexpected identifier: {output.identifier}")

                        for other_socket in output.connections:
                            replacement_node.outputs[0].join(other_socket, move=False)

                elif node.be('ShaderNodeUVMap'):

                    if get_active_render_uv_layer(object):
                        if node.uv_map and is_valid_uv_map(node.uv_map, object):
                            pass
                        else:
                            node.uv_map = get_active_render_uv_layer(object).name
                    elif object.type == 'MESH':
                        warn(f"A mesh does not have any uv layers the output of the UV socket is (0, 0, 0): {object.data.name_full}")
                        replacement_node = tree.new('ShaderNodeCombineXYZ')
                        for other_socket in node.outputs[0].connections.copy():
                            replacement_node.outputs[0].join(other_socket, move=False)
                    else:
                        # TODO: to test, this should work for curves
                        node.uv_map = 'UVMap'

                elif node.be('ShaderNodeNormalMap') and node.space == 'TANGENT':

                    if get_active_render_uv_layer(object):
                        if node.uv_map and is_valid_uv_map(node.uv_map, object):
                            pass
                        else:
                            node.uv_map = get_active_render_uv_layer(object).name
                    elif object.type == 'MESH':
                        # TODO: undefined behavior
                        warn(f"A mesh does not have any uv layers for tangent space: {object.data.name_full}")
                    else:
                        # TODO: to test, this should work for curves
                        node.uv_map = 'UVMap'

                elif node.be('ShaderNodeTexCoord') and node.object is None:

                    if node.from_instancer:
                        warn("ShaderNodeTexCoord.from_instancer not handled.")

                    for output in node.outputs:

                        if not output.connections:
                            continue

                        if output.identifier == 'Generated':
                            replacement_node = tree.new('ShaderNodeTexCoord')
                            replacement_node.object = get_texture_coordinates_generated_empty(evaluated_object)
                            texture_coordinates_collection.objects.link(replacement_node.object)

                            if object.data and hasattr(object.data, 'texture_mesh') and object.data.texture_mesh:
                                warn("texture_mesh is not handled.")

                            for other_socket in output.connections:
                                replacement_node.outputs['Object'].join(other_socket, move=False)

                        elif output.identifier == 'Object':

                            replacement_node = tree.new('ShaderNodeNewGeometry').outputs['Position'].new('ShaderNodeMapping', vector_type='TEXTURE')

                            location, rotation, scale = evaluated_object.matrix_world.decompose()

                            replacement_node['Location'] = location
                            replacement_node['Rotation'] = rotation.to_euler()
                            replacement_node['Scale'] = scale

                            for other_socket in output.connections:
                                replacement_node.outputs[0].join(other_socket, move=False)

                        elif output.identifier == 'UV':

                            if get_active_render_uv_layer(object):
                                replacement_node = tree.new('ShaderNodeUVMap')
                                replacement_node.uv_map = get_active_render_uv_layer(object).name
                            elif object.type == 'MESH':
                                warn(f"A mesh does not have any uv layers the output of the UV socket is (0, 0, 0): {object.data.name_full}")
                                replacement_node = tree.new('ShaderNodeCombineXYZ')
                            else:
                                # TODO: to test, this should work for curves
                                replacement_node = tree.new('ShaderNodeUVMap')
                                replacement_node.uv_map = 'UVMap'

                            for other_socket in output.connections:
                                replacement_node.outputs[0].join(other_socket, move=False)


                elif node.be('Ambient Occlusion') and node.only_local == True:
                   # TODO: as the node ignores all the shader context a way is to explode the mesh
                   # separating all the parts belonging to other meshes
                   # but in this case you cannot have nodes with and without this option
                   # TODO: possible solution is to pre-bake all the Ambient Occlusion nodes
                   # the pre-baking can be a general solution to all problems
                   warn("No handling for only_local Ambient Occlusion node.")

                elif node.be('ShaderNodeTexImage') and node.projection == 'BOX':
                    # TODO: to preserve the projection is to recreate the node using 3 texture nodes
                    # it uses the object's matrix to convert normals to object space to drive the projection
                    # so when the rotation is applied — the projection changes to be world oriented
                    # https://github.com/blender/blender/blob/af4974dfaa165ff1be0819c52afc99217d3627ba/source/blender/nodes/shader/nodes/node_shader_tex_image.cc#L115
                    # https://github.com/blender/blender/blob/af4974dfaa165ff1be0819c52afc99217d3627ba/source/blender/gpu/shaders/material/gpu_shader_material_tex_image.glsl#L77
                    mapping = node.inputs['Vector'].insert_new('ShaderNodeMapping')
                    mapping.inputs['Rotation'].set_default_value(evaluated_object.matrix_world.to_euler())

    return texture_coordinates_collection


def merge_material_slots_with_the_same_materials(objects: typing.List[bpy.types.Object]):

    for mesh in get_unique_meshes(objects):

        index_to_polygons = utils.list_by_key(mesh.polygons.values(), operator.attrgetter('material_index'))
        material_to_indexes = utils.list_by_key(index_to_polygons, lambda i: mesh.materials[i])

        index_to_new_index = {}
        mesh.materials.clear()
        for new_index, (material, indexes) in enumerate(material_to_indexes.items()):
            mesh.materials.append(material)
            for index in indexes:
                index_to_new_index[index] = new_index

        for index, polygons in index_to_polygons.items():
            for polygon in polygons:
                polygon.material_index = index_to_new_index[index]


def bake_object_by_material_key(objects: typing.List[bpy.types.Object], alpha_material_key: str, opaque_material_key: str, bake_settings: 'tool_settings.Bake'):

    for material_key in (alpha_material_key, opaque_material_key):

        material_group = [m for m in bpy.data.materials if m.get(material_key)]
        if not material_group:
            continue

        bake_types = [[tool_settings_bake.AO_Diffuse(), tool_settings_bake.Roughness(), tool_settings_bake.Metallic()]]

        if any(material[Material_Bake_Type.HAS_EMISSION] for material in material_group):
            bake_types.append(tool_settings_bake.Emission())

        if any(material[Material_Bake_Type.HAS_NORMALS] for material in material_group):
            bake_types.append(tool_settings_bake.Normal(uv_layer=bake_settings.uv_layer_name))

        if material_key == alpha_material_key:
            bake_types.append([tool_settings_bake.Base_Color(), tool_settings_bake.Alpha()])
        else:
            bake_types.append(tool_settings_bake.Base_Color())

        bake_settings.material_key = material_key
        bake_settings.bake_types = bake_types
        bpy_bake.bake(objects, bake_settings)


def set_out_of_range_material_indexes_to_zero(objects: typing.List[bpy.types.Object]):

    for object in get_unique_mesh_objects(objects):
        max_index = len(object.data.materials) - 1
        for polygon in object.data.polygons:
            if polygon.material_index > max_index:
                polygon.material_index = 0


def merge_objects_and_bake_materials(objects: typing.List[bpy.types.Object], image_dir: str, *,
        px_per_meter = 1024,
        min_res = 64,
        max_res = 4096,
        resolution = 0,
        uv_layer_bake = '_bc_bake',
        uv_layer_reuse = '_bc_bake',
        faster_ao_bake = False,
        denoise_all = False,
        additional_bake_settings: typing.Optional[dict] = None
    ):

    if not get_meshable_objects(objects):
        raise Exception(f"No valid objects provided, object types must be MESH or convertible to MESH: {[o.name_full for o in objects]}")


    objects = get_meshable_objects(objects)


    with bpy_context.Global_Optimizations(), bpy_context.Bpy_State() as bpy_state_0:

        # this can help to reduce `Dependency cycle detected` spam in rigs
        for o in bpy.data.objects:
            if o.type == 'ARMATURE':
                bpy_state_0.set(o.pose, 'ik_solver', 'LEGACY')


        convert_materials_to_principled(objects, remove_unused=False)

        set_out_of_range_material_indexes_to_zero(objects)

        alpha_material_key, opaque_material_key = split_into_alpha_and_non_alpha_groups(objects)


        ## unwrap
        settings = tool_settings.UVs(resolution = 1024 if resolution == 0 else resolution, do_unwrap=False, average_uv_scale=False)
        settings._set_suggested_padding()
        settings.uv_layer_name = uv_layer_reuse

        # TODO: check results for non mesh objects, they supposed to have valid auto-generated UVs, like curves do
        objects_to_unwrap = get_unique_mesh_objects([object for object in objects if hasattr(object.data, 'uv_layers') and not uv_layer_reuse in object.data.uv_layers])

        with bpy_context.Bpy_State() as bpy_state:

            for object in objects_to_unwrap:
                if object.animation_data:
                    for driver in object.animation_data.drivers:
                        bpy_state.set(driver, 'mute', True)

            for object in objects_to_unwrap:
                for modifier in object.modifiers:
                    bpy_state.set(modifier, 'show_viewport', False)

            bpy_uv.ensure_uv_layer(objects_to_unwrap, settings.uv_layer_name)

            for object in objects_to_unwrap:
                bpy_state.set(object.data.uv_layers, 'active', object.data.uv_layers[settings.uv_layer_name])

            unwrap_ministry_of_flat_with_fallback(objects_to_unwrap, settings)

            bpy_uv.scale_uv_to_world_per_uv_layout(objects_to_unwrap)

        ## merge
        bpy.context.view_layer.update()
        texture_coordinates_collection = make_material_independent_from_object(objects)
        merged_object = merge_objects(objects)


        ## pack
        merged_uvs_settings = settings._get_copy()
        merged_uvs_settings.uv_layer_name = uv_layer_bake
        bpy_uv.ensure_uv_layer([merged_object], merged_uvs_settings.uv_layer_name, init_from=settings.uv_layer_name)


        with bpy_context.Focus_Objects(merged_object, mode='EDIT'), bpy_context.Bpy_State() as bpy_state:

            bpy_state.set(merged_object.data.uv_layers, 'active', merged_object.data.uv_layers[uv_layer_bake])

            bpy.ops.mesh.select_all(action='SELECT')
            bpy.ops.uv.reveal()
            bpy.ops.uv.select_all(action='SELECT')

            bpy.ops.uv.average_islands_scale()

        for material_key in (alpha_material_key, opaque_material_key):
            merged_uvs_settings.material_key = material_key
            merged_uvs_settings.average_uv_scale = False
            merged_uvs_settings.uvp_rescale = True
            bpy_uv.unwrap_and_pack([merged_object], merged_uvs_settings)


        bpy_uv.ensure_pixel_per_island([merged_object], settings)


        ## bake
        bake_settings = tool_settings.Bake(image_dir = image_dir)

        if additional_bake_settings:
            for key, value in additional_bake_settings.items():
                setattr(bake_settings, key, value)

        bake_settings.uv_layer_name = uv_layer_bake

        has_alpha_materials = any(m for m in bpy.data.materials if m.get(alpha_material_key))

        for material_key in (opaque_material_key, alpha_material_key):

            material_group = [m for m in bpy.data.materials if m.get(material_key)]
            if not material_group:
                continue

            bake_types = [[tool_settings_bake.AO_Diffuse(faster=faster_ao_bake, environment_has_transparent_materials = has_alpha_materials), tool_settings_bake.Roughness(use_denoise=denoise_all), tool_settings_bake.Metallic(use_denoise=denoise_all)]]

            if any(material[Material_Bake_Type.HAS_EMISSION] for material in material_group):
                bake_types.append(tool_settings_bake.Emission(use_denoise=denoise_all))

            if any(material[Material_Bake_Type.HAS_NORMALS] for material in material_group):
                # TODO: denoising the normals destroys details
                bake_types.append(tool_settings_bake.Normal(uv_layer=bake_settings.uv_layer_name))

            if material_key == alpha_material_key:
                bake_types.append([tool_settings_bake.Base_Color(use_denoise=denoise_all), tool_settings_bake.Alpha(use_denoise=denoise_all)])
            else:
                bake_types.append(tool_settings_bake.Base_Color(use_denoise=denoise_all))

            bake_settings.material_key = material_key
            bake_settings.bake_types = bake_types

            if resolution == 0:
                bake_settings.resolution = get_texture_resolution(merged_object, uv_layer_bake, material_group, px_per_meter, min_res, max_res)
            else:
                bake_settings.resolution = resolution

            bpy_bake.bake([merged_object], bake_settings)

        ## delete temp objects
        bpy.data.batch_remove(set(texture_coordinates_collection.objects))
        bpy.data.collections.remove(texture_coordinates_collection)

        merge_material_slots_with_the_same_materials([merged_object])


        return merged_object


def get_closest_power_of_two(resolution: float, min_res = 64, max_res = 4096) -> int:

    variants = []

    def get_power_of_2(n):
        return round(math.log(n)/math.log(2))

    for i in range(get_power_of_2(min_res), get_power_of_2(max_res) + 1):
        n = pow(2, i)
        variants.append((n - resolution, n))

    closest_resolution = min(variants, key = lambda x: abs(x[0]))

    return closest_resolution[1]


def get_texture_resolution(object: bpy.types.Object, *, uv_layer_name: str, materials: typing.Optional[typing.List[bpy.types.Material]] = None, px_per_meter = 1024, min_res = 64, max_res = 4096):
    """ Get a texture resolution needed to achieve the given texel density. """

    from mathutils.geometry import area_tri

    init_active = object.data.uv_layers.active

    object.data.uv_layers.active = object.data.uv_layers[uv_layer_name]

    bm = bmesh.new()
    bm.from_mesh(object.data)
    bm.transform(object.matrix_world)

    face_to_uv_triangles = bpy_uv.get_uv_triangles(bm, bm.loops.layers.uv.verify())


    face_areas = []
    face_uv_areas = []

    if materials:
        material_indexes = set(index for index, material in enumerate(object.data.materials) if material in materials)
    else:
        material_indexes = None

    for face in bm.faces:

        if material_indexes is not None:
            if face.material_index not in material_indexes:
                continue

        face_areas.append(face.calc_area())
        face_uv_areas.append(sum(area_tri(*loop) for loop in face_to_uv_triangles[face]))


    total_uv_area = sum(face_uv_areas)
    assert not math.isnan(total_uv_area)

    # texel_densities = []
    texel_densities_to_find = []
    weights = []

    # current_texture_size = 1024

    for face_area, face_area_uv in zip(face_areas, face_uv_areas):

        try:
            # texel_density = math.sqrt(pow(current_texture_size, 2) / face_area * face_area_uv)
            texel_density_to_find = math.sqrt(face_area / face_area_uv) * px_per_meter
            weight = face_area_uv / total_uv_area
        except ZeroDivisionError:
            continue

        # texel_densities.append(texel_density)
        texel_densities_to_find.append(texel_density_to_find)
        weights.append(weight)

    # total_mesh_area = sum(face_areas)
    # current_from_weighted_mean = sum(map(operator.mul, texel_densities, weights))/sum(weights)
    # current_from_total = math.sqrt(total_mesh_area / total_uv_area) * current_texture_size

    perfect_resolution = sum(map(operator.mul, texel_densities_to_find, weights))/sum(weights)

    final_resolution = get_closest_power_of_two(perfect_resolution, min_res, max_res)

    object.data.uv_layers.active = init_active

    return final_resolution


def get_visible_objects():
    return [object for object in get_view_layer_objects() if object.visible_get()]


def split_objects_into_pre_merged_objects(objects: typing.List[bpy.types.Object], do_cleanup = True, force_rename = False):
    """ Split objects into separate objects using information generated by `merge_objects`. """
    print("split_objects_into_pre_merged_objects...")

    new_objects: typing.List[bpy.types.Object] = []


    # separate objects
    for object in objects:

        merged_objects_info = object.get(K_MERGED_OBJECTS_INFO)
        if not merged_objects_info:
            continue

        with bpy_context.Focus_Objects(object, 'EDIT'):

            bpy.ops.mesh.reveal()

            for object_id, info in merged_objects_info.items():

                object.vertex_groups.active_index = object.vertex_groups[object_id].index

                bpy.ops.mesh.select_all(action='DESELECT')
                bpy.ops.object.vertex_group_select()
                bpy.ops.mesh.separate(type='SELECTED')

            new_objects.extend(bpy.context.selected_objects)
            new_objects.remove(object)


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
    for object in new_objects:

        merged_objects_info = object.get(K_MERGED_OBJECTS_INFO)
        if not merged_objects_info:
            continue

        if not object.data.vertices:
            continue

        vertex_group_name = get_vertex_group(object, set(merged_objects_info))
        object_info = merged_objects_info[vertex_group_name]

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
                traceback.print_exc(file=sys.stderr)

        with bpy_context.Focus_Objects(object):
            bpy.context.scene.cursor.location = object_info['location']
            bpy.ops.object.origin_set(type='ORIGIN_CURSOR', center='MEDIAN')


    # clean up
    if do_cleanup:
        for object in new_objects:

            merged_objects_info = object.get(K_MERGED_OBJECTS_INFO)
            if not merged_objects_info:
                continue

            for object_id, info in merged_objects_info.items():
                object.vertex_groups.remove(object.vertex_groups[object_id])

            del object[K_MERGED_OBJECTS_INFO]


    return new_objects



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

    with bpy_context.Focus_Objects(objects), bpy_context.State() as state:

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


def unwrap_unique_meshes(objects: typing.List[bpy.types.Object], settings: tool_settings.UVs, *,
            ministry_of_flat_settings: typing.Optional[tool_settings.Ministry_Of_Flat] = None
        ):

    objects = get_unique_mesh_objects(objects)

    with bpy_context.Bpy_State() as bpy_state:

        for object in objects:
            for modifier in object.modifiers:
                bpy_state.set(modifier, 'show_viewport', False)

        for object in objects:
            bpy_state.set(object.data.uv_layers, 'active', object.data.uv_layers[settings.uv_layer_name])

        with bpy_context.Empty_Scene():
            unwrap_ministry_of_flat_with_fallback(objects, settings, ministry_of_flat_settings)

            bpy_uv.scale_uv_to_world_per_uv_layout(objects)


def copy_and_bake_materials(objects: typing.List[bpy.types.Object], settings: tool_settings.Bake_Materials, *,
            bake_settings: typing.Optional[tool_settings.Bake] = None,
            unwrap_settings: typing.Optional[tool_settings.UVs] = None,
            pack_settings: typing.Optional[tool_settings.UVs] = None,
            ministry_of_flat_settings: typing.Optional[tool_settings.Ministry_Of_Flat] = None,
        ):


    incompatible_objects = set(objects) - set(get_meshable_objects(objects))
    if incompatible_objects:
        raise ValueError(f"Specified objects cannot be baked, type must be MESH or convertible to MESH: {[o.name_full for o in objects]}\nIncompatible: {[o.name_full for o in incompatible_objects]}")


    with bpy_context.Global_Optimizations(), bpy_context.Focus_Objects(objects), bpy_context.Bpy_State() as bpy_state_0:

        # this can help to reduce `Dependency cycle detected` spam in rigs
        for object in bpy.data.objects:
            if object.type == 'ARMATURE':
                bpy_state_0.set(object.pose, 'ik_solver', 'LEGACY')


        for object in objects:

            if object.animation_data:

                for driver in object.animation_data.drivers:
                    bpy_state_0.set(driver, 'mute', True)

                for nla_track in object.animation_data.nla_tracks:
                    bpy_state_0.set(nla_track, 'mute', True)

        if settings.convert_materials:
            convert_materials_to_principled(objects, remove_unused=False)

        set_out_of_range_material_indexes_to_zero(objects)
        merge_material_slots_with_the_same_materials(objects)

        alpha_material_key, opaque_material_key = split_into_alpha_and_non_alpha_groups(objects)


        ## unwrap uvs
        _unwrap_settings = tool_settings.UVs(uv_layer_name = settings.uv_layer_bake)
        if unwrap_settings:
            _unwrap_settings._update(unwrap_settings)

        bpy_uv.ensure_uv_layer(objects, settings.uv_layer_bake, init_from = settings.uv_layer_reuse)

        for object in objects:
            object.data.uv_layers.active = object.data.uv_layers[settings.uv_layer_bake]


        def filter_objects_to_unwrap(objects: typing.List[bpy.types.Object]):
            # TODO: check results for non mesh objects, they supposed to have valid auto-generated UVs, like curves do
            return [object for object in objects if hasattr(object.data, 'uv_layers') and not settings.uv_layer_reuse in object.data.uv_layers]


        if settings.unwrap_original_topology:
            unwrap_unique_meshes(filter_objects_to_unwrap(objects), _unwrap_settings, ministry_of_flat_settings = ministry_of_flat_settings)


        ## copy identifiers
        K_OBJECT_COPY_ID = '__bc_temp_object_copy_id'

        for object in objects:
            object[K_OBJECT_COPY_ID] = uuid.uuid1().hex


        ## merge objects
        bpy.context.view_layer.update()

        objects_copy = deep_copy_objects(objects)

        if settings.convert_materials:
            texture_coordinates_collection = make_material_independent_from_object(objects_copy)

        if settings.bake_original_topology:
            for object in objects_copy:
                for modifier in object.modifiers:

                    if is_smooth_modifier(modifier):
                        continue

                    if modifier.type not in bpy_context.TOPOLOGY_CHANGING_MODIFIER_TYPES:
                        continue

                    modifier.show_viewport = False

        convert_to_mesh(objects_copy)


        # for object in objects_copy:
        #     edge_split_modifier: bpy.types.EdgeSplitModifier = object.modifiers.new(name='__bc_bake_edge_split', type='EDGE_SPLIT')
        #     edge_split_modifier.use_edge_angle = False


        if not settings.unwrap_original_topology:
            unwrap_unique_meshes(filter_objects_to_unwrap(objects_copy), _unwrap_settings, ministry_of_flat_settings = ministry_of_flat_settings)


        if settings.isolate_object_hierarchies:
            space_out_objects(objects_copy)

        merged_object = merge_objects(objects_copy, generate_merged_objects_info = True)
        merged_object.name = '__bc_bake'


        ## average uv islands scale
        with bpy_context.Focus_Objects(merged_object, mode='EDIT'), bpy_context.Bpy_State() as bpy_state:

            bpy_state.set(merged_object.data.uv_layers, 'active', merged_object.data.uv_layers[settings.uv_layer_bake])

            bpy.ops.mesh.select_all(action='SELECT')
            bpy.ops.uv.reveal()
            bpy.ops.uv.select_all(action='SELECT')

            if settings.non_uniform_average_uv_scale and 'scale_uv' in repr(bpy.ops.uv.average_islands_scale):
                bpy.ops.uv.average_islands_scale(scale_uv = True)
            else:
                bpy.ops.uv.average_islands_scale()


        ## uv pack

        materials = list(group_objects_by_material([merged_object]))

        def pack_uvs(resolution):
            for material_key in (opaque_material_key, alpha_material_key):

                if not any(m for m in materials if m.get(material_key)):
                    continue

                _pack_settings = tool_settings.UVs(
                    resolution = resolution,
                    uv_layer_name = settings.uv_layer_bake,
                    material_key = material_key,
                    average_uv_scale = False,
                    uvp_rescale = False,
                    do_unwrap = False,
                )

                if pack_settings:
                    _pack_settings._update(pack_settings)

                _pack_settings._set_suggested_padding()
                bpy_uv.unwrap_and_pack([merged_object], _pack_settings)
                bpy_uv.ensure_pixel_per_island([merged_object], _pack_settings)


        if settings.resolution:
            pack_uvs(settings.resolution)
        else:
            # pre packing
            # needed to calculate the texel density
            # but to match the final resolution, we have to pack a second time
            pack_uvs(get_closest_power_of_two((settings.min_resolution + settings.max_resolution)/2))

        ## bake materials

        # TODO: this only works for the processed objects, not others in the scene
        environment_has_transparent_materials = any(m for m in bpy.data.materials if m.get(alpha_material_key))

        for material_key in (opaque_material_key, alpha_material_key):

            material_group = [m for m in materials if m.get(material_key)]
            if not material_group:
                continue


            _bake_settings = tool_settings.Bake(uv_layer_name = settings.uv_layer_bake, image_dir = settings.image_dir)._update(bake_settings)

            if settings.resolution:
                _bake_settings.resolution = settings.resolution
            else:
                # calculate target resolution and repack
                _bake_settings.resolution = get_texture_resolution(
                    merged_object,
                    uv_layer_name = settings.uv_layer_bake,
                    materials = material_group,
                    px_per_meter = settings.texel_density,
                    min_res = settings.min_resolution,
                    max_res = settings.max_resolution,
                    )
                pack_uvs(_bake_settings.resolution)


            ## bake
            bake_types = [
                [
                    tool_settings_bake.AO_Diffuse(faster=settings.faster_ao_bake, environment_has_transparent_materials = environment_has_transparent_materials),
                    tool_settings_bake.Roughness(use_denoise=settings.denoise_all),
                    tool_settings_bake.Metallic(use_denoise=settings.denoise_all)
                ]
            ]

            if any(material[Material_Bake_Type.HAS_EMISSION] for material in material_group):
                bake_types.append(tool_settings_bake.Emission(use_denoise=settings.denoise_all))

            if any(material[Material_Bake_Type.HAS_NORMALS] for material in material_group):
                # TODO: denoising the normals destroys details
                bake_types.append(tool_settings_bake.Normal(uv_layer=_bake_settings.uv_layer_name))

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
                    _bake_settings.texture_name_prefix = merged_object.name + '_alpha'
                else:
                    _bake_settings.texture_name_prefix = merged_object.name

            bpy_bake.bake([merged_object], _bake_settings)


        ## split baked copy
        splitted_objects_copy = split_objects_into_pre_merged_objects([merged_object])

        if settings.isolate_object_hierarchies:
            revert_space_out_objects(splitted_objects_copy)

        map_copy_id_to_copy = {object[K_OBJECT_COPY_ID]: object for object in splitted_objects_copy}
        map_original_to_copy = {object: map_copy_id_to_copy[object[K_OBJECT_COPY_ID]] for object in objects}


        ## transfer packed uvs
        print('transferring the baked data to originals...')

        def add_data_transfer_modifier():

            modifier = orig.modifiers.new(f"__bc_temp_copy_uvs_{uuid.uuid1().hex}", type='DATA_TRANSFER')

            modifier.object = copy
            modifier.use_loop_data = True
            modifier.data_types_loops = {'UV'}
            modifier.loop_mapping = 'TOPOLOGY'
            modifier.layers_uv_select_src = settings.uv_layer_bake
            modifier.poly_mapping = 'TOPOLOGY'
            modifier.show_expanded = False

            return modifier

        for orig, copy in map_original_to_copy.items():

            if settings.bake_original_topology:
                bpy_uv.copy_uv(copy, orig, settings.uv_layer_bake)
            else:
                add_data_transfer_modifier()


        ## copy materials
        for orig, copy in map_original_to_copy.items():
            with bpy_context.Focus_Objects(copy):
                bpy.ops.object.material_slot_remove_unused()  # when called with call_for_objects returns CANCELLED
            bpy_context.call_for_objects(copy, [orig, copy], bpy.ops.object.material_slot_copy)

        merge_material_slots_with_the_same_materials(objects)
        merge_material_slots_with_the_same_materials(splitted_objects_copy)

        if settings.bake_original_topology:
            bpy.data.batch_remove(splitted_objects_copy)
        else:
            move_objects_to_new_collection(splitted_objects_copy, '__bc_baked_copy').exclude = True


        ## delete temp objects
        if settings.convert_materials:
            bpy.data.batch_remove(set(texture_coordinates_collection.objects))
            bpy.data.collections.remove(texture_coordinates_collection)


        return objects



def move_modifier_to_first(modifier: bpy.types.Modifier):

    object: bpy.types.Object = modifier.id_data

    index = list(object.modifiers).index(modifier)
    if index == 0:
        return

    if bpy.app.version < (2,90,0):
        for _ in range(index):
            bpy_context.call_for_object(object, bpy.ops.object.modifier_move_up, modifier = modifier.name)
    else:
        bpy_context.call_for_object(object, bpy.ops.object.modifier_move_to_index, modifier = modifier.name, index=0)


def is_smooth_modifier(modifier: bpy.types.Modifier):

    if modifier.type != 'NODES':
        return False

    if not modifier.node_group:
        return False

    return 'Smooth by Angle' in modifier.node_group.name



def apply_modifiers(objects: typing.List[bpy.types.Object], *, ignore_name = '', include_name = '', ignore_type = set(), include_type = set(), ignore_canceled = False):
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

            modifiers_to_apply.append(modifier)


        if not modifiers_to_apply:
            continue


        with bpy_context.Isolate_Focus([object]):

            for modifier in modifiers_to_apply:

                result = bpy.ops.object.modifier_apply(modifier = modifier.name, single_user = True)

                if not ignore_canceled and 'CANCELLED' in result:
                    raise Exception(f"Fail to apply {modifier.type} modifier '{modifier.name}' to object '{object.name_full}'.")


def get_unique_materials(objects: typing.List[bpy.types.Object]):

    materials = []

    for object in objects:
        for slot in object.material_slots:
            if slot.material:
                materials.append(slot.material)

    return utils.deduplicate(materials)
