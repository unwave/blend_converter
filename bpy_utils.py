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

import bpy
import mathutils

from . import bpy_bake
from . import tool_settings
from . import bpy_context
from . import bake_settings as tool_settings_bake
from . import bpy_node
from . import bpy_uv
from . import utils


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

    import re
    from bpy.utils import unescape_identifier
    re_bone_animation = re.compile(r'pose.bones\["(.+)"\]')

    for fcurve in action.fcurves:
        match = re_bone_animation.match(fcurve.data_path)
        if match:
            yield unescape_identifier(match.group(1))


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


def get_visible_armature_bones(armature: bpy.types.Object):
    """ Get a set of visible bones. """

    if bpy.app.version >= (4, 0, 0):
        armature_collections = {c for c in armature.data.collections if c.is_visible}
        return {bone.name for bone in armature.pose.bones if not armature_collections.isdisjoint(bone.bone.collections)}
    else:
        armature_layers = armature.data.layers
        return {bone.name for bone in armature.pose.bones if any(a and b for a, b in zip(armature_layers, bone.bone.layers))}


def get_armature(object: bpy.types.Object):
    """ Get an armature associated with the object. """

    if object.type == 'ARMATURE':
        return object
    else:
        return object.find_armature()


def get_actions(armature: bpy.types.Object) -> typing.List[bpy.types.Action]:
    """ Get actions associated with the armature object. """

    armature_bones_names = get_visible_armature_bones(armature)
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

    # prevent modifying the data of the not included objects
    object_by_data = utils.list_by_key(objects, operator.attrgetter('data'))
    for data, _objects in object_by_data.items():

        if not data:
            continue

        if data.users - data.use_fake_user == 1:
            continue

        data_copy = _objects[0].data.copy()
        for _object in _objects:
            _object.data = data_copy

    with bpy_context.Focus_Objects(objects):

        try:
            result = bpy.ops.object.convert(target = 'MESH', keep_original = False)
            if 'CANCELLED' in result:
                raise Exception(f"Converting to mesh has been cancelled: {objects}")
        except Exception as e:
            raise Exception(f"Cannot convert to meshes: {objects}") from e

        # TODO: metaball conversion keeps the metaball object despite `keep_original = False`
        # init_objects = context.init_objects

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


def make_meshes_unique(objects: typing.List[bpy.types.Object]):
    """ Make a unique copy of a mesh data for each mesh object. """

    for object in objects:

        if object.type != 'MESH':
            continue

        if not object.data:
            continue

        if object.data.users - object.data.use_fake_user == 1:
            continue

        object.data = object.data.copy()


def _focus(objects: typing.List[bpy.types.Object], view_layer: bpy.types.ViewLayer):

    view_layer.update()
    view_layer_objects = get_view_layer_objects(view_layer)

    for object in view_layer_objects:
        if object in objects:
            object.hide_set(False)
            object.hide_viewport = False
            object.hide_select = False
            object.select_set(True)
        else:
            object.select_set(False)

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


def merge_objects(objects: typing.List[bpy.types.Object], object_name: str = None):

    objects = get_joinable_objects(objects)
    if not objects:
        return

    def make_data_unique(objects: bpy.types.Object):

        for object in objects:

            if not object.data:
                continue

            if object.data.users - object.data.use_fake_user == 1:
                continue

            object.data = object.data.copy()

    metaball_family = f"__metaball_family_{uuid.uuid1().hex}"

    with bpy_context.Focus_Objects(objects):

        bpy.ops.object.make_local(type='ALL')

        for object_type, objects_of_type in utils.list_by_key(objects, lambda x: x.type).items():
            if object_type == 'META':
                for index, metaball in enumerate(objects_of_type):
                    metaball.name = f"{metaball_family}_{index}"
            else:
                make_data_unique(objects)

        objects = convert_to_mesh(objects)


    with bpy_context.Focus_Objects(objects):
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
        merged_object = bpy.context.view_layer.objects.active
        bpy.ops.object.join()
        # #126278 - Joining some meshes shows warning "Call save() to ensure ..." in console - blender - Blender Projects
        # https://projects.blender.org/blender/blender/issues/126278


    if object_name is not None:
        merged_object.name = object_name

    return merged_object


def abspath(path, library: typing.Union[bpy.types.Library, None] = None):
    return os.path.realpath(bpy.path.abspath(path, library = library))  # type: ignore


def get_block_abspath(block: typing.Union[bpy.types.Library, bpy.types.Image]):
    return abspath(block.filepath, block.library)  # type: ignore


def inspect_blend(blender_executable: typing.Optional[str] = None, exit_after = False,):
    """ Blocking blend file inspection. """

    if blender_executable is None:
        blender_executable = bpy.app.binary_path

    with tempfile.TemporaryDirectory() as temp_dir:
        filepath = os.path.join(temp_dir, f'DEBUG_{utils.ensure_valid_basename(bpy.context.scene.name)}.blend')

        for image in bpy.data.images:
            if image.source == 'GENERATED' and image.is_dirty:
                image.pack()

        try:
            bpy.ops.wm.save_as_mainfile(filepath = filepath, copy = True)
        except RuntimeError as e:
            print(e, file=sys.stderr)

        subprocess.run([blender_executable, filepath])

    if exit_after:
        raise SystemExit('DEBUG EXIT')


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


def unwrap_ministry_of_flat_with_fallback(objects: typing.List[bpy.types.Object], settings: 'tool_settings.UVs'):

    ministry_of_flat_settings = tool_settings.Ministry_Of_Flat(vertex_weld=False, rasterization_resolution=1, packing_iterations=1)

    with tempfile.TemporaryDirectory() as temp_dir:
        for object in objects:
            try:
                bpy_uv.unwrap_ministry_of_flat(object, temp_dir, settings = ministry_of_flat_settings, uv_layer_name = settings.uv_layer_name)
            except utils.Fallback as e:
                utils.print_in_color(utils.get_color_code(240,0,0, 0,0,0), f"Fallback to smart_project: {e}")

                with bpy_context.Focus_Objects(object, mode='EDIT'), bpy_context.Bpy_State() as bpy_state:

                    bpy_state.set(object.data.uv_layers, 'active', object.data.uv_layers[settings.uv_layer_name])

                    bpy.ops.mesh.reveal()
                    if not bpy.ops.uv.reveal.poll():
                        import bmesh
                        if not bmesh.from_edit_mesh(object.data).faces:
                            continue
                    bpy.ops.uv.reveal()
                    bpy.ops.mesh.select_all(action='SELECT')
                    bpy.ops.uv.select_all(action='SELECT')
                    bpy.ops.uv.pin(clear=True)
                    bpy.ops.uv.smart_project(island_margin = settings._uv_island_margin_fraction / 0.8, angle_limit = math.radians(settings.smart_project_angle_limit))


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
        print('pre_convert_materials:', material.name_full)

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

    with bpy_context.Global_Bake_Optimizations(), bpy_context.Bpy_State() as bpy_state_0:

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


def open_homefile(blend_file):

    blend_dir = os.path.dirname(blend_file)

    try:
        bpy.ops.wm.read_homefile(filepath=blend_file, load_ui=False)
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

    empty = bpy.data.objects.new(name='__texture_coordinate__', object_data=None)
    empty.empty_display_type = 'ARROWS'

    collection = bpy.data.collections.get('__texture_coordinate__')
    if collection is None:
        collection = bpy.data.collections.new('__texture_coordinate__')
        bpy.context.view_layer.layer_collection.collection.children.link(collection)

    collection.objects.link(empty)

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


def merge_objects_respect_materials(objects: typing.List[bpy.types.Object]):
    """
    Try to modify materials so when the objects are joined the materials look the same.

    The main use case is speedup texture baking.
    """

    objects = get_meshable_objects(objects)

    objects_with_materials = [object for object in objects if hasattr(object, 'material_slots') and any(slot.material for slot in object.material_slots)]
    make_materials_unique(objects_with_materials)

    warning_color = utils.get_color_code(217, 69, 143, 0,0,0)

    def warn(*args):
         utils.print_in_color(warning_color, 'WARNING:', *args)


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


            if hasattr(object.data, 'uv_layers') and object.data.uv_layers:

                # Joining objects deletes UV map #64245
                # https://projects.blender.org/blender/blender/issues/64245

                render_uv_layer = next(layer.name for layer in object.data.uv_layers if layer.active_render)

                for node in reversed(tree.surface_input.descendants):
                    if node.be('ShaderNodeTexImage') and not node.inputs['Vector'].connections:
                        node.inputs['Vector'].new('ShaderNodeUVMap', uv_map=render_uv_layer)


            for node in reversed(tree.surface_input.descendants):
                if node.be(GENERATED_COORDINATES_TEXTURE_NODE) and not node.inputs['Vector'].connections:
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
                            raise Exception("Unexpected identifier: {output.identifier}")

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
                            raise Exception("Unexpected identifier: {output.identifier}")

                        for other_socket in output.connections:
                            replacement_node.outputs[0].join(other_socket, move=False)

                elif node.be('ShaderNodeTexCoord') and node.object is None:

                    if node.from_instancer:
                        warn("ShaderNodeTexCoord.from_instancer not handled.")

                    for output in node.outputs:

                        if not output.connections:
                            continue

                        if output.identifier == 'Generated':
                            replacement_node = tree.new('ShaderNodeTexCoord')
                            replacement_node.object = get_texture_coordinates_generated_empty(evaluated_object)

                            if object.data and hasattr(object.data, 'texture_mesh') and object.data.texture_mesh:
                                warn("texture_mesh is not handled.")

                        elif output.identifier == 'Object':
                            replacement_node = tree.new('ShaderNodeTexCoord')
                            replacement_node.object = get_texture_coordinates_object_empty(evaluated_object)

                        elif output.identifier == 'UV':

                            if object.data and hasattr(object.data, 'uv_layers') and object.data.uv_layers.active:
                                replacement_node = tree.new('ShaderNodeUVMap')
                                replacement_node.uv_map = object.data.uv_layers.active.name
                            elif object.type == 'MESH':
                                # TODO: add a warning
                                # if a mesh object does not have any uv layers the output of the UV socket is (0, 0, 0)
                                replacement_node = tree.new('ShaderNodeCombineXYZ')
                            else:
                                # this should work for curves
                                replacement_node = tree.new('ShaderNodeUVMap')
                                replacement_node.uv_map = 'UVMap'


                            for other_socket in output.connections:
                                replacement_node.outputs[0].join(other_socket, move=False)

                            continue

                        else:
                            continue

                        for other_socket in output.connections:
                            replacement_node.outputs['Object'].join(other_socket, move=False)

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


    return merge_objects(objects)


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


    with bpy_context.Global_Bake_Optimizations(), bpy_context.Bpy_State() as bpy_state_0:

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

        with bpy_context.State() as state, bpy_context.Bpy_State() as bpy_state:

            for object in objects_to_unwrap:
                if object.animation_data:
                    for driver in object.animation_data.drivers:
                        state.set(driver, 'mute', True)

            for object in objects_to_unwrap:
                for modifier in object.modifiers:
                    bpy_state.set(modifier, 'show_viewport', False)

            bpy_uv.ensure_uv_layer(objects_to_unwrap, settings.uv_layer_name)

            for object in objects_to_unwrap:
                bpy_state.set(object.data.uv_layers, 'active', object.data.uv_layers[settings.uv_layer_name])
                # object.data.uv_layers.active = object.data.uv_layers[settings.uv_layer_name]

            unwrap_ministry_of_flat_with_fallback(objects_to_unwrap, settings)

            bpy_uv.scale_uv_to_world_per_uv_layout(objects_to_unwrap)

        ## merge
        bpy.context.view_layer.update()
        merged_object = merge_objects_respect_materials(objects)


        ## pack
        merged_uvs_settings = settings._get_copy()
        merged_uvs_settings.uv_layer_name = uv_layer_bake
        bpy_uv.ensure_uv_layer([merged_object], merged_uvs_settings.uv_layer_name, do_init = True)


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
        bake_settings = tool_settings.Bake(image_dir = image_dir, make_materials_single_user=False)

        if additional_bake_settings:
            for key, value in additional_bake_settings.items():
                setattr(bake_settings, key, value)

        bake_settings.uv_layer_name = uv_layer_bake

        has_alpha_materials = any(m for m in bpy.data.materials if m.get(alpha_material_key))

        for material_key in (opaque_material_key, alpha_material_key):

            material_group = [m for m in bpy.data.materials if m.get(material_key)]
            if not material_group:
                continue

            bake_types = [[tool_settings_bake.AO_Diffuse(faster=faster_ao_bake, environment_has_alpha = has_alpha_materials), tool_settings_bake.Roughness(use_denoise=denoise_all), tool_settings_bake.Metallic(use_denoise=denoise_all)]]

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
        temp_collection = bpy.data.collections.get('__texture_coordinate__')
        if temp_collection:
            bpy.data.batch_remove(set(temp_collection.objects))
            bpy.data.collections.remove(temp_collection)

        merge_material_slots_with_the_same_materials([merged_object])


        return merged_object


def get_texture_resolution(object: bpy.types.Object, uv_layer_name: str, materials: typing.Optional[typing.List[bpy.types.Material]] = None, px_per_meter = 1024, min_res = 64, max_res = 4096):
    """ Get a texture resolution needed to achieve the given textel density. """

    import bmesh
    from mathutils.geometry import area_tri

    init_active = object.data.uv_layers.active

    object.data.uv_layers.active = object.data.uv_layers[uv_layer_name]

    bm = bmesh.new()
    bm.from_mesh(object.data)
    bm.transform(object.matrix_world)

    face_to_uv_triangles = bpy_uv.get_uv_triangles(bm, bm.loops.layers.uv.verify())


    face_areas = []
    face_uv_areas = []

    if materials is not None:
        material_indexes = set(index for index, material in enumerate(object.data.materials) if material in materials)

    for face in bm.faces:

        if materials is not None and face.material_index not in material_indexes:
            continue

        face_areas.append(face.calc_area())
        face_uv_areas.append(sum(area_tri(*loop) for loop in face_to_uv_triangles[face]))


    total_uv_area = sum(face_uv_areas)
    assert not math.isnan(total_uv_area)

    texel_densities = []
    texel_densities_to_find = []
    weights = []

    current_texture_size = 1024

    for face_area, face_area_uv in zip(face_areas, face_uv_areas):

        try:
            texel_density = math.sqrt(pow(current_texture_size, 2) / face_area * face_area_uv)
            texel_density_to_find = math.sqrt(face_area / face_area_uv) * px_per_meter
            weight = face_area_uv / total_uv_area
        except ZeroDivisionError:
            continue

        texel_densities.append(texel_density)
        texel_densities_to_find.append(texel_density_to_find)
        weights.append(weight)


    total_mesh_area = sum(face_areas)
    current_from_weighted_mean = sum(map(operator.mul, texel_densities, weights))/sum(weights)
    current_from_total = math.sqrt(total_mesh_area / total_uv_area) * current_texture_size

    perfect_resolution = sum(map(operator.mul, texel_densities_to_find, weights))/sum(weights)

    variants = []

    def get_power_of_2(n):
        return round(math.log(n)/math.log(2))

    for i in range(get_power_of_2(min_res), get_power_of_2(max_res) + 1):
        n = pow(2, i)
        variants.append((n - perfect_resolution, n))

    res = min(variants, key = lambda x: abs(x[0]))

    object.data.uv_layers.active = init_active

    return res[1]
