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


from . import bpy_bake
from . import bpy_context
from . import bake_settings as tool_settings_bake
from . import bpy_node
from . import bpy_uv
from . import bpy_modifier
from . import bpy_material
from . import bpy_mesh
from . import communication
from . import bpy_data

from .. import tool_settings
from .. import utils


if utils.is_in_blender():

    import bpy
    from bpy import utils as b_utils
    import mathutils
    import bmesh

elif not typing.TYPE_CHECKING:

    bpy = utils.Dummy()
    b_utils = utils.Dummy()
    mathutils = utils.Dummy()
    bmesh = utils.Dummy()


if typing.TYPE_CHECKING:
    # need only __init__ hints
    from dataclasses import dataclass
else:
    dataclass = lambda x: x


T_Objects = typing.TypeVar('T_Objects', bpy.types.Object, typing.List[bpy.types.Object], typing.Iterable[bpy.types.Object])


def get_view_layer_objects(view_layer: typing.Optional['bpy.types.ViewLayer'] = None) -> typing.List[bpy.types.Object]:
    """
    #113378 - Regression: Deleting Objects in a View Layer leaves None in the View Layer's .objects for the script duration
    https://projects.blender.org/blender/blender/issues/113378
    """
    if view_layer is None:
        view_layer =  bpy.context.view_layer

    view_layer.update()

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

    objects = list(objects)

    if join_into is not None:
        if not join_into in objects:
            objects = objects + [join_into]
    else:
        if not objects:
            raise Exception("No objects to join were provided.")
        join_into = objects[0]


    incompatible_objects = set(objects) - set(o for o in objects if o.type == 'MESH' and (o.data.vertices or o == join_into))
    if incompatible_objects:
        raise ValueError(
            f"Specified objects cannot be joined: {[o.name_full for o in objects]}"
            "\n\t" f"Incompatible: {[o.name_full for o in incompatible_objects]}"
        )


    if generate_joined_objects_info:

        joined_objects_info = {}

        for object in objects:
            joined_objects_info[get_object_info_key(object)] = get_object_info(object)


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


def get_closest_power_of_two(resolution: float, min_res = 64, max_res = 4096) -> int:

    variants = []

    def get_power_of_2(n):
        return round(math.log(n)/math.log(2))

    for i in range(get_power_of_2(min_res), get_power_of_2(max_res) + 1):
        n = pow(2, i)
        variants.append((n - resolution, n))

    closest_resolution = min(variants, key = lambda x: abs(x[0]))

    return closest_resolution[1]


def get_texture_resolution(
        objects: typing.List[bpy.types.Object],
        *,
        uv_layer_name = '',
        materials: typing.Optional[typing.List[bpy.types.Material]] = None,
        px_per_meter = 1024,
    ):
    """ Get a texture resolution needed to achieve the given texel density. """

    from mathutils.geometry import area_tri


    with bpy_context.Focus(objects), bpy_context.State() as state:

        if uv_layer_name:
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


        total_face_area = sum(itertools.filterfalse(math.isnan, face_areas))
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


        uv_resolution = bpy_uv.get_weighted_percentile(texel_densities, 0.5, weights)
        surface_resolution = math.sqrt(total_face_area) * px_per_meter

        return uv_resolution, surface_resolution, total_uv_area


def suggest_udim_layout(
        target_resolution: int,
        uv_coverage: float,
        *,
        min_resolution = 64,
        max_resolution = 4096,
        min_udim_count = 1,
        max_udim_count = 4,
        undershoot_tolerance = 0.05,
        udim_cost = 0.25,
        min_resolution_for_udim = 2048,
    ):


    def get_power_of_2(n):
        return round(math.log(n)/math.log(2))

    target_pixels = target_resolution ** 2

    class Variant(typing.NamedTuple):
        resolution: int
        udim_count: int

    variants: typing.List[Variant] = []


    for i in range(get_power_of_2(min_resolution), get_power_of_2(max_resolution) + 1):

        resolution = pow(2, i)

        for udim_count in range(min_udim_count, max_udim_count + 1):

            variants.append(Variant(resolution, udim_count))

            if resolution < min_resolution_for_udim:
                break

    any_match = False

    def score(variant: Variant):
        resolution, udim_count = variant

        pixels = resolution ** 2 * udim_count

        delta = target_pixels - pixels * uv_coverage
        is_undershoot = 1 if delta > (target_pixels * undershoot_tolerance) else 0

        nonlocal any_match
        any_match = any_match or not is_undershoot

        return (is_undershoot, pixels / target_pixels + (udim_count - 1) * udim_cost + abs(delta) / target_pixels)


    variants.sort(key = score)

    if not any_match:
        print(f"An impossible UDIM layout for the resolution specified: {target_resolution}", file = sys.stderr)
        return max_resolution, max_udim_count

    return variants[0].resolution, variants[0].udim_count



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


def pack_and_task(
            objects: typing.List[bpy.types.Object],
            settings: tool_settings.S_Bake_Materials,
            *,
            bake_settings: typing.Optional[tool_settings.S_Bake] = None,
            pack_settings: typing.Optional[tool_settings.S_Pack_UVs] = None,
        ):


    with bpy_context.Global_Optimizations(), bpy_context.Focus(objects):

        ## process the materials

        # this is needed in order to split_into_alpha_and_non_alpha_groups to work
        # and for the bake itself
        # TODO: it might be possible to convert the materials on the bake proxy and leave the original intact
        # but to sort them into alpha and non-alpha they should be converter first

        bpy_material.convert_materials_to_principled(objects, remove_unused=False)
        bpy_material.set_out_of_range_material_indexes_to_zero(objects)
        bpy_material.merge_material_slots_with_the_same_materials(objects)

        alpha_material_key, opaque_material_key = bpy_material.split_into_alpha_and_non_alpha_groups(objects)


        ## uv pack

        # doing the pack inside the function because it depends on the material groups

        materials = list(group_objects_by_material(objects))

        def pack_uvs(resolution: int, material_key: str):

            _pack_settings = tool_settings.S_Pack_UVs(
                resolution = resolution,
                uv_layer_name = settings.uv_layer_bake,
                material_key = material_key,
                average_uv_scale = False,
            )._update(pack_settings)

            bpy_uv.pack(objects, _pack_settings)


        def ensure_pixel_per_island(resolution: int, material_key: str):

            _pack_settings = tool_settings.S_Pack_UVs(
                    resolution = resolution,
                    uv_layer_name = settings.uv_layer_bake,
                    material_key = material_key,
                )

            bpy_uv.ensure_pixel_per_island(objects, _pack_settings)




        ## collect bake settings

        pre_bake_tasks: typing.List[tool_settings.S_Bake] = []
        bake_tasks: typing.List[tool_settings.S_Bake] = []

        # TODO: this only works for the materials that has been processed, not others in the scene
        environment_has_transparent_materials = any(m for m in bpy.data.materials if m.get(alpha_material_key))

        for material_key in (opaque_material_key, alpha_material_key):

            material_group = [m for m in materials if m.get(material_key)]
            if not material_group:
                continue


            _bake_settings = tool_settings.S_Bake(uv_layer_name = settings.uv_layer_bake, image_dir = settings.image_dir)._update(bake_settings)

            if settings.resolution:
                # the final resolution is hard set
                _bake_settings.resolution = settings.resolution
            else:
                # pre packing to calculate the texel density
                # to match the final resolution, we have to pack a second time for preciseness
                pack_uvs(get_closest_power_of_two((settings.min_resolution + settings.max_resolution)/2), material_key)

                # calculate target resolution
                uv_resolution, surface_resolution, uv_coverage = get_texture_resolution(
                    objects,
                    uv_layer_name = settings.uv_layer_bake,
                    materials = material_group,
                    px_per_meter = settings.texel_density,
                )

                resolution, udim_count = suggest_udim_layout(
                    uv_resolution,
                    uv_coverage,
                    min_resolution = settings.min_resolution,
                    max_resolution = settings.max_resolution,
                    max_udim_count = 1,
                )

                _bake_settings.resolution = resolution


            pack_uvs(_bake_settings.resolution, material_key)
            ensure_pixel_per_island(_bake_settings.resolution, material_key)


            def does_need_denoise(
                        identifier: str,
                        trees: typing.List[bpy_node.Shader_Tree_Wrapper] = [bpy_node.Shader_Tree_Wrapper(m.node_tree) for m in material_group]
                    ):

                for tree in trees:
                    for node in tree.output['Surface'].inputs[identifier].iter_descendant_nodes_recursive():
                        if node.bl_idname in ('ShaderNodeAmbientOcclusion', 'ShaderNodeBevel'):
                            return True

                return False

            need_denoise = dict(
                Normal = does_need_denoise(tool_settings_bake.S_Normal()._identifier),
                Roughness = does_need_denoise(tool_settings_bake.S_Roughness()._identifier),
                Metallic = does_need_denoise(tool_settings_bake.S_Metallic()._identifier),
                Alpha = does_need_denoise(tool_settings_bake.S_Alpha()._identifier),
                Emission = does_need_denoise(tool_settings_bake.S_Emission()._identifier),
                Base_Color = does_need_denoise(tool_settings_bake.S_Base_Color()._identifier),
            )

            need_denoise = {key: (value and settings.denoise_all) for key, value in need_denoise.items()}


            if any(need_denoise.values()):

                view_space_normals_bake_type = tool_settings_bake.S_View_Space_Normal(use_denoise=need_denoise['Normal'])

                pre_bake_settings = _bake_settings._get_copy()

                pre_bake_settings.image_dir = os.path.join(bpy.app.tempdir, '__bc_pre_baked')
                pre_bake_settings.do_downscale = False
                pre_bake_settings.use_anti_aliasing = False
                pre_bake_settings.material_key = material_key
                pre_bake_settings.bake_types = [view_space_normals_bake_type]
                pre_bake_settings.texture_name_prefix = uuid.uuid1().hex

                pre_bake_tasks.append(pre_bake_settings)

                _bake_settings.view_space_normals_id = view_space_normals_bake_type._uuid


            bake_types = []

            orma = [
                tool_settings_bake.S_AO_Diffuse(
                    faster = settings.faster_ao_bake,
                    environment_has_transparent_materials = environment_has_transparent_materials,
                    use_normals = settings.ao_bake_use_normals,
                ),
                tool_settings_bake.S_Roughness(use_denoise=need_denoise['Roughness']),
                tool_settings_bake.S_Metallic(use_denoise=need_denoise['Metallic'])
            ]

            if material_key == alpha_material_key:
                orma.append(tool_settings_bake.S_Alpha(use_denoise=need_denoise['Alpha']))

            bake_types.append(orma)


            if any(material[bpy_material.Material_Bake_Type.HAS_EMISSION] for material in material_group):
                bake_types.append(tool_settings_bake.S_Emission(use_denoise=need_denoise['Emission']))

            if any(material[bpy_material.Material_Bake_Type.HAS_NORMALS] for material in material_group):
                bake_types.append(tool_settings_bake.S_Normal(uv_layer=_bake_settings.uv_layer_name, use_denoise=need_denoise['Normal']))


            bake_types.append([tool_settings_bake.S_Base_Color(use_denoise=need_denoise['Base_Color'])])


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


    return bake_tasks, pre_bake_tasks


def copy_and_bake(
        objects: typing.List[bpy.types.Object],
        tasks: typing.Tuple[typing.List[tool_settings.S_Bake], typing.List[tool_settings.S_Bake]],
        pre_bake_labels: typing.List[str] = tuple(),
        isolate_object_hierarchies = False,
        split_faces_by_materials = True,
    ):
    """
    `pre_bake_labels`: Bakes and replaces the nodes with the labels specified. See `label_mix_shader_nodes` and `bake_by_label`.

    `isolate_object_hierarchies``: Space out object hierarchies, grouped by a top common parent, before baking.
    To prevent them affecting each other, aka exploded bake.

    `split_faces_by_materials`: Split the bake mesh faces by materials.
    To negate the effect of the `ADJACENT_FACES` margin generation bleeding between different materials.
    """


    if not objects:
        utils.print_in_color(utils.get_color_code(245, 115, 30, 10, 10, 10), "No objects were provided for baking.")
        return


    with bpy_context.Global_Optimizations(), bpy_context.Focus(objects), bpy_context.State() as state:


        ## disable animation for consistency
        for object in objects:
            if object.animation_data:

                for driver in object.animation_data.drivers:
                    state.set(driver, 'mute', True)

                for nla_track in object.animation_data.nla_tracks:
                    state.set(nla_track, 'mute', True)


        ## join the bake proxy object
        objects_copy = deep_copy_objects(objects)

        texture_coordinates_collection = bpy_material.make_material_independent_from_object(objects_copy)

        convert_to_mesh(objects_copy)

        if isolate_object_hierarchies:
            space_out_objects(objects_copy)

        bake_proxy = join_objects(objects_copy, name = '__bc_bake')


        if split_faces_by_materials:
            bpy_material.split_faces_by_materials(bake_proxy)


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
        bake_tasks, pre_bake_tasks = tasks

        with communication.Suspend_Others():

            for pre_bake_settings in pre_bake_tasks:
                bpy_bake.bake([bake_proxy], pre_bake_settings)

            for bake_settings in bake_tasks:

                apply_uv_texture_jitter([bake_proxy], bake_settings)

                with Pre_Baked([bake_proxy], pre_bake_labels, bake_settings):
                    bpy_bake.bake([bake_proxy], bake_settings)


        ## delete temporal objects
        bpy.data.batch_remove((bake_proxy.data, bake_proxy))

        bpy.data.batch_remove(set(texture_coordinates_collection.objects))
        bpy.data.collections.remove(texture_coordinates_collection)


def assign_new_materials(
            objects: typing.List[bpy.types.Object],
            tasks: typing.Tuple[typing.List[tool_settings.S_Bake], typing.List[tool_settings.S_Bake]],
        ):


    bake_tasks, _ = tasks


    with bpy_context.Focus(objects):

        ## create new materials
        new_materials = {}

        for bake_settings in bake_tasks:

            material_name = bake_settings.texture_name_prefix
            if not material_name:
                material_name = get_common_name(objects)

            new_materials[bake_settings.material_key] = bpy_material.create_material(
                material_name,
                bake_settings.uv_layer_name,
                bake_settings._images,
                k_map_identifier = bake_settings._K_MAP_IDENTIFIER
            )


        ## assign the materials
        for object in objects:
            for material_slot in object.material_slots:
                for material_key in new_materials:
                    if material_slot.material.get(material_key):
                        material_slot.material = new_materials[material_key]

        bpy_material.merge_material_slots_with_the_same_materials(objects)


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

    with bpy_context.Focus(objects):

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

            if not modifiers_to_apply:
                continue


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
def Pre_Baked(objects: typing.List[bpy.types.Object], prebake_labels: typing.List[str], settings: tool_settings.S_Bake = None):

    original_material_key = settings.material_key

    settings = tool_settings.S_Bake()._update(settings)
    settings.do_downscale = False
    settings.use_anti_aliasing = False
    settings.image_dir = os.path.join(bpy.app.tempdir, '__bc_pre_baked')

    affected_materials: typing.Set[bpy.types.Material] = set()

    pre_baked_images  = tuple()  # handled skipped bake

    for prebake_label in prebake_labels:

        materials = [m for m in get_unique_materials(objects) if m.get(prebake_label) and m.get(original_material_key)]

        use_denoise = False

        _materials: typing.List[bpy.types.Material] = []
        for material in materials:
            tree = bpy_node.Shader_Tree_Wrapper(material.node_tree)

            for node in tree.output.inputs[0].descendants:

                if node.label != prebake_label:
                    continue

                _materials.append(material)

                use_denoise = use_denoise or any(n.bl_idname in ('ShaderNodeAmbientOcclusion', 'ShaderNodeBevel') for n in node.inputs[0].iter_descendant_nodes_recursive())

                break

        materials = _materials

        map_id = uuid.uuid1().hex

        for material in materials:
            material[map_id] = True

        settings.bake_types = [tool_settings_bake.S_Buffer_Factor(node_label=prebake_label, _identifier = 'buffer' + map_id, use_denoise = use_denoise)]

        settings.material_key = map_id

        pre_baked_images = bpy_bake.bake(objects, settings)


        # replace nodes with baked images
        for material in materials:

            if not pre_baked_images:
                print("No image baked for the pre-bake stage. Possibly skipped.")
                break

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

        if not pre_baked_images:
            return

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


def apply_scale(objects: typing.List[bpy.types.Object]):

    make_object_data_unique(objects)

    with bpy_context.Focus(objects):
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)


def add_actions_to_nla(regex: typing.Optional[str] = None):
    """
    Add all associated with the visible armature bones actions to NLA.

    `regex`: `re.search` on `bpy.types.Action.name`
    """

    for object in bpy.data.objects:

        armature = get_armature(object)
        if not armature:
            return

        if armature.animation_data is None:
            armature.animation_data_create()

        if armature.animation_data.nla_tracks:
            return

        armature_bones_names = set(get_visible_armature_bones(armature.data))
        if not armature_bones_names:
            return

        actions: typing.List[bpy.types.Action] = [action for action in bpy.data.actions if not armature_bones_names.isdisjoint(iter_bone_names(action))]

        nla_tracks = armature.animation_data.nla_tracks

        for action in actions:

            if regex is not None and not re.search(regex, action.name):
                continue

            track = nla_tracks.new()
            track.name = action.name
            track.strips.new(action.name, 0, action)


def use_backface_culling():
    """ Set `use_backface_culling` to `True` for all materials. """

    for material in bpy.data.materials:
        material.use_backface_culling = True


def create_default_root_bone():
    """ Create a default root bone and an according weight group to prevent a faulty armature handling by the gltf exporter. """

    def get_armatures(object: bpy.types.Object):
        return  [modifier.object for modifier in object.modifiers if isinstance(modifier, bpy.types.ArmatureModifier) and modifier.object]

    def are_all_vertices_have_groups(object: bpy.types.Object, bone_names: set[str]):
        return all(not set(object.vertex_groups[group.group].name for group in v.groups).isdisjoint(bone_names) for v in object.data.vertices)

    def get_bone_names(armature: bpy.types.Object):
        return {bone.name for bone in armature.pose.bones}

    def create_root_vertex_group(object: bpy.types.Object, bone_names: set[str], root_bone_name: str):
        default_group = object.vertex_groups.new(name = root_bone_name)
        default_group.add([v.index for v in object.data.vertices if set(object.vertex_groups[group.group].name for group in v.groups).isdisjoint(bone_names)], 1, 'ADD')

    def deselect_all():
        for object in filter(None, bpy.context.view_layer.objects):
            object.select_set(False)

    for object in filter(None, bpy.context.view_layer.objects):

        if not isinstance(object.data, bpy.types.Mesh):
            continue

        armatures = get_armatures(object)
        if not armatures:
            continue

        for armature in armatures:

            bone_names = get_bone_names(armature)

            if are_all_vertices_have_groups(object, bone_names):
                continue

            root_bone_name = f"{armature.name}_default_root_bone"

            create_root_vertex_group(object, bone_names, root_bone_name)

            deselect_all()
            armature.select_set(True)
            bpy.context.view_layer.objects.active =armature

            bpy.ops.object.mode_set(mode='EDIT', toggle=False)

            edit_bones = armature.data.edit_bones

            root_bone = edit_bones.new(root_bone_name)
            root_bone.head = (0, 0, 1)
            root_bone.tail = (0, 0, 0)

            for bone in edit_bones:
                if not bone.parent:
                    bone.parent = root_bone

            bpy.ops.object.mode_set(mode='OBJECT', toggle=False)


def remove_all_node_groups_from_materials():
    """
    the gltf exporter's method of nodes inspection takes an absurd amount of time
    https://github.com/KhronosGroup/glTF-Blender-IO/issues/2356
    Finished glTF 2.0 export in 294.57832312583923 s
    Finished glTF 2.0 export in 0.05988144874572754 s

    > TODO: cache these searches
    https://github.com/KhronosGroup/glTF-Blender-IO/blob/cee66f781491c0e65ea3d65f465a445333788bd7/addons/io_scene_gltf2/blender/exp/material/search_node_tree.py#L71

    > For now, not caching it. If we encounter performance issue, we will see later
    https://github.com/KhronosGroup/glTF-Blender-IO/blob/cee66f781491c0e65ea3d65f465a445333788bd7/addons/io_scene_gltf2/blender/exp/material/search_node_tree.py#L159
    """

    for material in bpy.data.materials:

        if not material.node_tree:
            continue

        nodes = material.node_tree.nodes

        for node in nodes:
            if node.bl_idname == 'ShaderNodeGroup' and not 'glTF Settings' in node.name:
                nodes.remove(node)


def remove_vertex_colors(objects: typing.List[bpy.types.Object]):

    for object in objects:

        data = object.data
        if not isinstance(data, bpy.types.Mesh):
            continue

        vertex_color_names = [vertex_color.name for vertex_color in data.vertex_colors]
        for name in vertex_color_names:
            data.vertex_colors.remove(data.vertex_colors[name])  # type: ignore


def ensure_debugpy():

    from . import ensure_site_packages
    import site
    ensure_site_packages.ensure_site_packages([('debugpy', 'debugpy')], directory=site.getusersitepackages())


def reset_ui_layout():
    """ A workaround to reset the blend file UI layout. """

    filepath = bpy.data.filepath
    bpy.ops.wm.read_homefile(app_template="")

    try:
        bpy.ops.wm.open_mainfile(filepath = filepath, load_ui=False)
    except RuntimeError as e:
        print(e)


def scene_clean_up():
    """ Remove all objects and collection starting from `#` and purge unused. """

    for object in list(bpy.data.objects):
        if object.name.startswith('#'):
            bpy.data.objects.remove(object)

    for layer in list(bpy.context.view_layer.layer_collection.children):

        if layer.collection.name.startswith('#'):

            bpy.data.batch_remove(set(layer.collection.all_objects))
            bpy.data.collections.remove(layer.collection)

        elif layer.exclude:
            layer.exclude = False

    bpy.ops.outliner.orphans_purge()


def bisect_by_mirror_modifiers(objects: typing.List[bpy.types.Object]):
    for object in objects:
        bpy_mesh.bisect_by_mirror_modifiers(object)


def clean_up_topology_and_triangulate_ngons(objects: typing.List[bpy.types.Object], split_concave_faces = True, tris_to_quads = True):
    """ The Ministry of Flat unwrapping can produce bad results if ngons or loose geometry is present. """

    objects = get_unique_mesh_objects(objects)

    if not objects:
        utils.print_in_color(utils.get_color_code(245, 115, 30, 10, 10, 10), "No mesh objects to cleanup.")
        return

    with bpy_context.Focus(objects):

        with bpy_context.Focus(objects, mode = 'EDIT'):
            bpy.ops.mesh.reveal()
            bpy.ops.mesh.select_all(action='SELECT')
            bpy.ops.mesh.delete_loose()
            bpy.ops.mesh.select_all(action='SELECT')
            bpy.ops.mesh.dissolve_degenerate()

        for object in objects:
            bpy_modifier.apply_triangulate(object, keep_custom_normals = True, min_vertices = 5)

        if not (split_concave_faces or tris_to_quads):
            return

        with bpy_context.Focus(objects, mode = 'EDIT'):
            bpy.ops.mesh.select_all(action='SELECT')
            if tris_to_quads:
                # TODO: ideally should be applied only to the former ngons
                bpy.ops.mesh.tris_convert_to_quads(uvs=True, vcols=True, seam=True, sharp=True, materials=True)
            if split_concave_faces:
                # might not be necessary but just in case
                bpy.ops.mesh.vert_connect_concave()


def do_nothing(*args, **kwargs):
    pass


def select_uv_layer(objects: typing.List[bpy.types.Object], name: str,):

    for object in objects:
        if hasattr(object.data, 'uv_layers'):
            index = object.data.uv_layers.find(name)
            if index >= 0:
                object.data.uv_layers.active_index = index


def get_uuid1_hex(prefix = '__bc_'):
    return prefix + uuid.uuid1().hex



def ensure_image_vector_inputs(material: bpy.types.Material):

    if not material.node_tree:
        return

    pool = [material.node_tree]
    seen = set()

    while pool:

        node_tree = pool.pop()

        if node_tree in seen:
            continue
        seen.add(node_tree)

        tree = bpy_node.Shader_Tree_Wrapper(node_tree)


        image_nodes: typing.List[bpy_node._Shader_Node_Wrapper] = []

        for node in tree.root.descendants:

            if node.be('ShaderNodeGroup') and node.node_tree:
                pool.append(node.node_tree)

            if node.be('ShaderNodeTexImage'):
                if not node.inputs['Vector'].connections:
                    image_nodes.append(node)


        # FIXME: handle the image node mapping
        uv_map = tree.new('ShaderNodeUVMap')

        for node in image_nodes:
            node.inputs['Vector'].join(uv_map.outputs[0])


def get_pixel_world_size_material(uv_map: str, name = '__bc_pixel_world_size'):

    material = bpy.data.materials.get(name)
    if material:
        return material

    material = bpy_data.get_new_material(name)

    tree = bpy_node.Shader_Tree_Wrapper(material.node_tree)

    from .node_groups import pixel_scale

    group = tree.root.inputs['Surface'].new('ShaderNodeGroup', node_tree = pixel_scale.get_main_tree())
    group.inputs[0].new('ShaderNodeUVMap', uv_map = uv_map)

    return material


def apply_uv_texture_jitter(objects: typing.List[bpy.types.Object], settings: tool_settings.S_Bake = None):
    """ Add a UV jitter for every image texture node to resolve moire. """


    original_material_key = settings.material_key
    material_key = get_uuid1_hex('__bc_uv_scale')

    settings = tool_settings.S_Bake()._update(settings)
    settings.material_key = material_key
    settings.do_downscale = False
    settings.use_anti_aliasing = False
    settings.compose_and_save = False
    settings.image_dir = os.path.join(bpy.app.tempdir, '__bc_uv_scale')


    # expecting the materials to be unique, otherwise will be incorrect
    materials = [m for m in get_unique_materials(objects) if m.node_tree]

    if original_material_key:
        materials = [m for m in materials if m.get(original_material_key)]


    for material in materials:
        ensure_image_vector_inputs(material)


    def get_vector_socket(node: bpy_node._Shader_Node_Wrapper):

        socket = node.inputs['Vector'].connections[0]

        while socket.node.be('NodeReroute'):
            socket = socket.node.inputs[0].connections[0]

        return socket


    def get_identifier(index: str):
        return material_key + f'_{index}'


    from .node_groups import uv_derivatives
    uv_texture_scale_tree = uv_derivatives.get_main_tree()


    @dataclass
    class S_Pixel_Scale(tool_settings_bake._S_Bake_Type, tool_settings.Settings):

        _socket_type = tool_settings_bake._Socket_Type.VALUE
        _identifier = 'pixel_world_size'
        _is_float_buffer = True


        def _get_setup_context(self):
            return bpy_context.State([
                (bpy.context.scene.render.bake, 'margin_type', 'EXTEND'),
                (bpy.context.scene.render.bake, 'margin', 16),
                (bpy.context.scene.cycles, 'device', 'CPU'),
                (bpy.context.scene.cycles, 'shading_system', True),
                (bpy.context.scene.cycles, 'samples', 1),
                (bpy.context.view_layer, 'material_override', get_pixel_world_size_material(settings.uv_layer_name)),
            ])


        def _get_material_context(self, material):


            try:
                material_to_socket_path_tuples[material]
                return contextlib.nullcontext(tool_settings_bake._get_shader_output_socket(material))
            except IndexError:
                return contextlib.nullcontext(None)


    @dataclass
    class S_UV_Scale(tool_settings_bake._S_Bake_Type, tool_settings.Settings):

        _socket_type = tool_settings_bake._Socket_Type.VECTOR
        _is_srgb = False

        _is_float_buffer = True

        index: int = 0


        @property
        def _identifier(self):
            return get_identifier(self.index)


        def _get_setup_context(self):
            return bpy_context.State([
                (bpy.context.scene.render.bake, 'margin_type', 'EXTEND'),
                (bpy.context.scene.render.bake, 'margin', 16),
            ])


        def _get_material_context(self, material):

            try:
                socket, path = material_to_socket_path_tuples[material][self.index]
            except IndexError:
                return contextlib.nullcontext(None)

            @contextlib.contextmanager
            def context():

                tree = bpy_node.Shader_Tree_Wrapper(socket.id_data)


                try:
                    group = tree.get_socket_wrapper(socket).new('ShaderNodeGroup', node_tree = uv_texture_scale_tree)
                    scale = group.outputs[0].new('ShaderNodeVectorMath', operation = 'SCALE')
                    image_node = scale.inputs['Scale'].new('ShaderNodeTexImage', image = pixel_world_size_settings._raw_images[0])
                    image_node.interpolation = 'Closest'
                    image_node.inputs['Vector'].new('ShaderNodeUVMap', uv_map = settings.uv_layer_name)

                    yield scale.outputs[0], path
                finally:
                    tree.delete_new_nodes()

            return context()


    material_to_socket_path_tuples = {}

    for material in materials:

        socket_path_tuples = []

        for node, path in bpy_context.walk_tree(material.node_tree):

            if not (node.be('ShaderNodeTexImage') and node.image):
                continue

            socket_path_tuples.append((get_vector_socket(node), tuple(path)))


        if socket_path_tuples:
            material_to_socket_path_tuples[material] = utils.deduplicate(socket_path_tuples)
            material[material_key] = True


    bake_types_count = max((len(v) for v in material_to_socket_path_tuples.values()), default = 0)
    if not bake_types_count:
        return


    pixel_world_size_settings = settings._get_copy()
    pixel_world_size_settings.bake_types = [S_Pixel_Scale()]
    bpy_bake.bake(objects, pixel_world_size_settings)


    uv_scale_settings = settings._get_copy()
    uv_scale_settings.bake_types = [S_UV_Scale(index = i) for i in range(bake_types_count)]
    bpy_bake.bake(objects, uv_scale_settings)


    def ensure_tree_input(tree: bpy_node.Shader_Tree_Wrapper, socket_name: str):

        assert not tree.is_material

        for socket in tree.get_input_sockets():
            if socket.name == socket_name:
                return

        tree.add_input_socket('NodeSocketVector', socket_name)

        for node in tree.get_by_bl_idname('NodeGroupInput'):
            node.update_sockets()


    def ensure_input_node(tree: bpy_node.Shader_Tree_Wrapper):

        for node in tree.get_by_bl_idname('NodeGroupInput'):
            return node

        return tree.new('NodeGroupInput')


    def add_node_group(socket: bpy_node._Socket_Wrapper, uv_scale: bpy_node._Socket_Wrapper):

        from .node_groups import gaussian_uv_jitter

        group = socket.insert_new('ShaderNodeGroup', node_tree = gaussian_uv_jitter.get_main_tree())
        group.get_input_by_name('UV Scale').join(uv_scale)
        group.get_input_by_name('X Resolution').set_default_value(settings._actual_width)
        group.get_input_by_name('Y Resolution').set_default_value(settings._actual_height)


    for material, socket_path_tuples in material_to_socket_path_tuples.items():

        for index, (socket, path) in enumerate(socket_path_tuples):

            image = uv_scale_settings._raw_images[index]
            socket_name = get_identifier(index)


            # connect intermediate path
            for fragment in reversed(path[1:]):

                tree = bpy_node.Shader_Tree_Wrapper(fragment.tree)

                ensure_tree_input(tree, socket_name)
                tree[fragment.node_group].get_input_by_name(socket_name).join(ensure_input_node(tree).get_output_by_name(socket_name))


            # connect destination
            if path:
                tree = bpy_node.Shader_Tree_Wrapper(socket.id_data)
                ensure_tree_input(tree, socket_name)
                add_node_group(tree.get_socket_wrapper(socket), ensure_input_node(tree).get_output_by_name(socket_name))


            # connect material
            tree = bpy_node.Shader_Tree_Wrapper(material.node_tree)

            image_node = tree.new('ShaderNodeTexImage', image = image)
            image_node.inputs['Vector'].new('ShaderNodeUVMap', uv_map = settings.uv_layer_name)

            if path:
                tree[path[0].node_group].get_input_by_name(socket_name).join(image_node.outputs[0])
            else:
                add_node_group(tree.get_socket_wrapper(socket), image_node.outputs[0])
