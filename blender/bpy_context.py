""" All sorts of context managers. """


import traceback
import typing
import uuid
import operator
import json
import re
import math
import collections

import bpy
from bpy import utils as b_utils
import mathutils

from . import bpy_node
from . import bpy_utils
from . import bpy_data
from . import blend_inspector

from .. import utils
from .. import tool_settings


TOPOLOGY_CHANGING_MODIFIER_TYPES = {
    'ARRAY',
    'BEVEL',
    'BOOLEAN',
    'BUILD',
    'DECIMATE',
    'EDGE_SPLIT',
    'NODES',
    'MASK',
    'MIRROR',
    'MULTIRES',
    'REMESH',
    'SCREW',
    'SKIN',
    'SOLIDIFY',
    'SUBSURF',
    'TRIANGULATE',
    'VOLUME_TO_MESH',
    'WELD',
    'WIREFRAME',
    'EXPLODE',
    'FLUID',
    'OCEAN',
    'PARTICLE_INSTANCE'
}


PRINT_CONTEXT_CHANGES = False



def format_call_error(name, reason, func, args, kwargs, override):
    return "\n".join([name, f"reason: {reason}", f"func: {repr(func)}", f"args: {args}", f"kwargs: {kwargs}", f"override: {override}"])


def call(override: typing.Dict[str, typing.Any], func: typing.Callable, *args, can_be_canceled = False, **kwargs):

    try:
        if bpy.app.version > (3,2,0):
            with bpy.context.temp_override(**override):
                result = func(*args, **kwargs)
        else:
            result =  func(override, *args, **kwargs)

    except Exception as e:
        raise Exception(format_call_error('ERROR', e, func, args, kwargs, override)) from e

    if not can_be_canceled and 'CANCELLED' in result:
        raise Exception(format_call_error('CANCELLED', 'unknown', func, args, kwargs, override))

    return result


def get_view3d():
    for window_manager in bpy.data.window_managers:
        for window in window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'VIEW_3D':
                    for region in area.regions:
                        if region.type == 'WINDOW':
                            return dict(window=window, workspace=window.workspace, screen=window.screen, area=area, region=region)

    raise Exception('View3D context not found.')


def call_in_view3d(func: typing.Callable, *args, **kwargs):
    return call(get_view3d(), func, *args, **kwargs)


def call_for_object(object: 'bpy.types.Object', func: typing.Callable, *args, can_be_canceled = False, **kwargs):

    override = dict(
        selectable_objects = [object],
        selected_objects = [object],
        selected_editable_objects = [object],
        editable_objects = [object],
        visible_objects = [object],
        active_object = object,
        object = object
    )

    return call(override, func, *args, can_be_canceled = can_be_canceled, **kwargs)


def call_for_objects(active_object: 'bpy.types.Object', objects: typing.List['bpy.types.Object'], func: typing.Callable, *args, can_be_canceled = False, **kwargs):

    if not active_object in objects:
        objects.append(active_object)

    override = dict(
        selectable_objects = objects,
        selected_objects = objects,
        selected_editable_objects = objects,
        editable_objects = objects,
        visible_objects = objects,
        active_object = active_object,
        object = active_object
    )

    return call(override, func, *args, can_be_canceled = can_be_canceled, **kwargs)


def get_local_view_objects(context: bpy.types.Context):
    """
    Regression: object.local_view_get and object.visible_in_viewport_get() always returns False
    https://developer.blender.org/T95197
    """

    space_view_3d = context.space_data

    if type(space_view_3d) != bpy.types.SpaceView3D: # will crash if space_view_3d is None
        raise TypeError(f'The context is incorrect. For context.space_data expected a SpaceView3D type, not {type(space_view_3d)}')

    depsgraph = context.evaluated_depsgraph_get()

    if bpy.data.objects and hasattr(bpy.data.objects[0], 'visible_in_viewport_get'):
        return [object for object in bpy.data.objects if object.evaluated_get(depsgraph).visible_in_viewport_get(space_view_3d)]
    else:
        return [object for object in bpy.data.objects if object.evaluated_get(depsgraph).local_view_get(space_view_3d)]


def delete_scene_collection(name: str):
    getattr(bpy.context.scene, name).clear()
    delattr(bpy.types.Scene, name)
    for scene in bpy.data.scenes:
        if name in scene.keys():
            del scene[name]


def get_embedded_id_data_and_path(object: bpy.types.bpy_struct):
    """
    #129393 - Python API: Can not assign bpy.types.Collection as PointerProperty - blender - Blender Projects
    https://projects.blender.org/blender/blender/issues/129393

    PointerProperty for NodeTree broke - Coding / Python Support - Blender Artists Community
    https://blenderartists.org/t/pointerproperty-for-nodetree-broke/1549830
    """

    id_data = object.id_data

    if isinstance(id_data, bpy.types.ShaderNodeTree):

        name = re.match(r"bpy\.data\.materials\['(.+?)'\]\.node_tree", repr(object)).group(1)
        material = bpy.data.materials[name]

        if object is id_data:
            return material, 'node_tree'
        else:
            return material, f'node_tree.{object.path_from_id()}'

    elif isinstance(id_data, bpy.types.CompositorNodeTree):

        name = re.match(r"bpy\.data\.scenes\['(.+?)'\]\.node_tree", repr(object)).group(1)
        scene = bpy.data.scenes[name]

        if object is id_data:
            return scene, 'node_tree'
        else:
            return scene, f'node_tree.{object.path_from_id()}'

    else:
        raise NotImplementedError(repr(object))


def get_id_data_and_path(object: typing.Union[bpy.types.bpy_struct, bpy.types.bpy_prop_array, bpy.types.bpy_prop_collection]):

    id_data: bpy.types.ID = object.id_data

    if id_data.is_embedded_data:
        return get_embedded_id_data_and_path(object)
    elif object == id_data:
        return id_data, ''
    elif isinstance(object, bpy.types.NlaTrack):
        return id_data, f'animation_data.nla_tracks["{b_utils.escape_identifier(object.name)}"]'
    elif isinstance(object, bpy.types.FCurve):
        # TODO: this may not be adequate, try search by data_path
        index = list(id_data.animation_data.drivers).index(object)
        return id_data, f'animation_data.drivers[{index}]'
    elif isinstance(object, bpy.types.Area):
        assert isinstance(id_data, bpy.types.Screen)
        index = list(id_data.areas).index(object)
        return id_data, f'areas.[{index}]'
    # TODO: ⚓ T51096 path_from_id does not work on subproperties of a custom node
    # https://developer.blender.org/T51096
    else:
        return id_data, object.path_from_id()


def is_bpy_struct(object):

    # underlying bpy data structures
    if not isinstance(object, (bpy.types.bpy_struct, bpy.types.bpy_prop_array, bpy.types.bpy_prop_collection)):
        return False

    id_data = object.id_data

    # bpy.types.Preferences.id_data is None
    # bpy.types.PreferencesEdit.id_data is None
    # returns None after assigning to an ID pointer property
    if id_data is None:
        return False

    assert isinstance(id_data, bpy.types.ID)

    return True


class State:

    print_color_bpy = utils.get_color_code(256,128,0, 0,0,0)
    print_color_python = utils.get_color_code(256,0,128, 0,0,0)

    error_color = utils.get_color_code(222,93,84, 0,0,0)


    @property
    def id_blocks_collection(self) -> bpy.types.CollectionProperty:
        return getattr(bpy.context.scene, self.collection_name)


    def __init__(self,
                settings: typing.Optional[typing.List[typing.Tuple[bpy.types.bpy_struct, str, typing.Any]]] = None,
                except_exit_errors = False,
                print = PRINT_CONTEXT_CHANGES
            ):

        self.collection_name = 'Bpy_Struct_State_collection_' + uuid.uuid1().hex
        setattr(bpy.types.Scene, self.collection_name, bpy.props.CollectionProperty(type = Bpy_ID_Pointer))

        self.except_exit_errors = except_exit_errors
        self.pre_settings = settings
        self.print = print

        self._index_id_blocks = 0
        self._index_bpy_structs = 0
        self._index_python_values = 0

        self.bpy_structs = []
        self.python_values = []

        self.states = []


    def __enter__(self):

        if self.pre_settings is not None:
            for object, attr, value in self.pre_settings:
                self.set(object, attr, value)

        return self


    def add_id_block(self, id_block: bpy.types.ID):

        pointer: Bpy_ID_Pointer

        for block_index, pointer in enumerate(self.id_blocks_collection):
            if id_block is pointer.target:
                return block_index
        else:
            pointer = self.id_blocks_collection.add()  # type: ignore
            pointer.target = id_block

            self._index_id_blocks += 1
            return self._index_id_blocks - 1


    def add_bpy_struct(self, bpy_struct: bpy.types.bpy_struct):

        id_data, path_from_id = get_id_data_and_path(bpy_struct)

        self.bpy_structs.append(
            (
                self.add_id_block(id_data),
                path_from_id,
                repr(bpy_struct),
            )
        )

        self._index_bpy_structs += 1
        return self._index_bpy_structs - 1


    def add_python_value(self, value: object):

        self.python_values.append(value)

        self._index_python_values += 1
        return self._index_python_values - 1


    def remember(self, object: bpy.types.bpy_struct, name: str):

        init_value = getattr(object, name)

        if isinstance(init_value, (mathutils.Color, mathutils.Euler, mathutils.Matrix, mathutils.Quaternion, mathutils.Vector)):
            init_value =  init_value.copy()


        object_is_bpy_struct = is_bpy_struct(object)

        if object_is_bpy_struct:
            object_index = self.add_bpy_struct(object)
        else:
            object_index = self.add_python_value(object)


        value_is_bpy_struct = is_bpy_struct(init_value)

        if value_is_bpy_struct:
            value_index = self.add_bpy_struct(init_value)
        else:
            value_index = self.add_python_value(init_value)


        state = (
            object_index,
            object_is_bpy_struct,
            name,
            value_index,
            value_is_bpy_struct,
        )

        self.states.append(state)

        return state


    def set(self, object: bpy.types.bpy_struct, name: str, value):

        state = self.remember(object, name)

        setattr(object, name, value)

        if self.print:
            utils.print_in_color(self.print_color_bpy if state[1] else self.print_color_python, f"{repr(object)}.{name} = {repr(value)}")


    def get_bpy_struct(self, index: int):

        id_block_index, path_from_id, representation = self.bpy_structs[index]

        pointer: Bpy_ID_Pointer = self.id_blocks_collection[id_block_index]

        if pointer.target is None:

            if path_from_id and representation.endswith(path_from_id):
                id = representation[:-len(path_from_id)]
            else:
                id = representation

            raise Exception(
                "Underling ID data block has been removed."
                "\n\t"  f"ID: {id}"
                "\n\t"  f"path_from_id: {repr(path_from_id)}"
            )
        elif path_from_id:
            try:
                return pointer.target.path_resolve(path_from_id)
            except ValueError as e:
                raise Exception(
                    "Fail to resolve path from id."
                    "\n\t" f"ID: {repr(pointer.target)}"
                    "\n\t" f"Path: {path_from_id}"
                )  from e
        else:
            return pointer.target


    def __exit__(self, exc_type, exc_value, exc_traceback):

        for object_index, object_is_bpy_struct, name, value_index, value_is_bpy_struct in reversed(self.states):

            try:
                setattr(
                    self.get_bpy_struct(object_index) if object_is_bpy_struct else self.python_values[object_index],
                    name,
                    self.get_bpy_struct(value_index) if value_is_bpy_struct else self.python_values[value_index],
                )
            except Exception as e:

                if self.except_exit_errors:
                    utils.print_in_color(self.error_color, traceback.format_exc())
                else:
                    raise Exception(
                        "Fail to unset property."
                        "\n\t" f"Object: {self.bpy_structs[object_index][2] if object_is_bpy_struct else self.python_values[object_index]}"
                        "\n\t" f"Name: {name}"
                        "\n\t" f"Value: {self.bpy_structs[value_index][2] if value_is_bpy_struct else self.python_values[value_index]}"
                    ) from e

        delete_scene_collection(self.collection_name)


class Bpy_ID_Pointer(bpy.types.PropertyGroup):

    if typing.TYPE_CHECKING:
        target: typing.Union[bpy.types.ID, None]
    else:
        target: bpy.props.PointerProperty(type = bpy.types.ID)


try:
    bpy.utils.unregister_class(Bpy_ID_Pointer)
except RuntimeError:
    pass
finally:
    bpy.utils.register_class(Bpy_ID_Pointer)


class Bpy_Reference_Collection:


    def __init__(self):
        self._collection_name = 'Bpy_Reference_collection_' + uuid.uuid1().hex
        setattr(bpy.types.Scene, self._collection_name, bpy.props.CollectionProperty(type = Bpy_ID_Pointer))
        self._index = 0


    @property
    def items(self) -> typing.Union[bpy.types.CollectionProperty, typing.List[Bpy_ID_Pointer]]:
        return getattr(bpy.context.scene, self._collection_name)


    def __enter__(self):
        return self


    def __exit__(self, type, value, traceback):
        delete_scene_collection(self._collection_name)


    def append(self, value: bpy.types.bpy_struct):
        pointer: Bpy_ID_Pointer = self.items.add()  # type: ignore
        pointer.name = str(self._index)
        pointer.target = value

        self._index += 1

        return self._index - 1


    def extend(self, values: typing.Iterable):
        for value in values:
            self.append(value)


    def __getitem__(self, index: int):
        return self.items[index].target


    def __iter__(self):
        for item in self.items:
            yield item.target


class Bake_Settings(State):


    def __init__(self, bake_settings: 'tool_settings.Bake'):
        super().__init__()
        self.bake_settings = bake_settings


    def __enter__(self):
        super().__enter__()

        context = bpy.context
        cycles = context.scene.cycles  # type: typing.Any
        render = context.scene.render

        self.set(render, 'engine', 'CYCLES')
        self.set(cycles, 'bake_type', 'EMIT')
        self.set(render.bake, 'use_clear', False)
        self.set(render.bake, 'margin', self.bake_settings.margin)

        if not self.bake_settings.use_global_bake_settings:
            return

        if bpy.app.version >= (5, 0):
            self.set(render.bake, 'use_multires', False)
        else:
            self.set(render, 'use_bake_multires', False)

        self.set(cycles, 'samples', self.bake_settings.samples)

        self.set(render, 'use_compositing', True)
        self.set(render, 'use_sequencer', False)

        self.set(render.bake, 'use_selected_to_active', self.bake_settings.use_selected_to_active)
        if self.bake_settings.cage_object_name:
            self.set(render.bake, 'use_cage', True)
            self.set(render.bake, 'cage_object', bpy.data.objects[self.bake_settings.cage_object_name])
            self.set(render.bake, 'max_ray_distance', self.bake_settings.max_ray_distance)

        self.set(context.view_layer, 'pass_alpha_threshold', 0.5)

        tile_size = max(self.bake_settings._actual_width, self.bake_settings._actual_height)

        blender_version_dependent_properties = [
            (render.bake, 'margin_type', self.bake_settings.margin_type),
            (cycles, 'use_denoising', False),
            (cycles, 'adaptive_min_samples', 0),
            (cycles, 'use_adaptive_sampling', False),
            (cycles, 'use_auto_tile', True),
            (cycles, 'tile_size', tile_size),
            (render.bake, 'target', 'IMAGE_TEXTURES'), # ? check
            (render, 'tile_x', tile_size),
            (render, 'tile_y', tile_size),
            (cycles, 'time_limit', 0),
            (cycles, 'sampling_pattern', 'TABULATED_SOBOL'),  # otherwise causes strange square artifacts that break the denoiser
        ]

        for property in blender_version_dependent_properties:
            try:
                self.set(*property)
            except (AttributeError, TypeError):
                pass

        self.set(render, 'use_persistent_data', True)
        self.set(cycles, 'light_sampling_threshold', 0)
        self.set(cycles, 'sample_clamp_direct', 0)
        self.set(cycles, 'sample_clamp_indirect', 0)
        self.set(cycles, 'blur_glossy', 0)

        self.set(cycles, 'caustics_reflective', False)
        self.set(cycles, 'caustics_refractive', False)

        self.set(cycles, 'max_bounces', 0)
        self.set(cycles, 'diffuse_bounces', 0)
        self.set(cycles, 'glossy_bounces', 0)
        self.set(cycles, 'transmission_bounces', 0)
        self.set(cycles, 'volume_bounces', 0)

        return self


class Global_Optimizations(State):

    @staticmethod
    def dummy_view_layer_update(_):
        return

    def __enter__(self):
        super().__enter__()

        self.set(bpy.context.preferences, 'use_preferences_save', False)
        self.set(bpy.context.preferences.edit, 'undo_steps', 0)
        self.set(bpy.context.preferences.edit, 'use_global_undo', False)

        if bpy.app.version >= (2, 93):
            self.set(bpy.ops._BPyOpsSubModOp, '_view_layer_update', self.dummy_view_layer_update)

        self.set(bpy_node, 'ALLOW_NODE_MOVE', False)

        return self


class Armature_Disabled(State):

    def __init__(self, object: bpy.types.Object):
        super().__init__()
        self.object = object

    def __enter__(self):

        armatures: set[bpy.types.Object] = set()
        for modifier in self.object.modifiers:

            if not isinstance(modifier, bpy.types.ArmatureModifier):
                continue

            armature = modifier.object  # type: ignore
            if armature:
                armatures.add(armature)

        for object in bpy.data.objects:
            for modifier in object.modifiers:

                if not isinstance(modifier, bpy.types.ArmatureModifier):
                    continue

                if modifier.object in armatures:
                    self.set(modifier, 'show_viewport', False)
                    self.set(modifier, 'show_render', False)

            if object.parent and object.parent in armatures:
                self.set(object, 'matrix_parent_inverse', mathutils.Matrix())
                self.set(object, 'parent', None)


class Temp_Image:

    uuid_key = 'blend_converter_uuid1_hex'

    def __init__(self, x, y):
        self.width = x
        self.height = y

    def __enter__(self):

        self.uuid_hex = uuid.uuid1().hex

        image = bpy.data.images.new(self.uuid_hex, width=self.width, height=self.height, float_buffer=True, is_data=True)
        image[self.uuid_key] = self.uuid_hex

        return image

    def __exit__(self, type, value, traceback):

        for image in list(bpy.data.images):
            if image.get(self.uuid_key) == self.uuid_hex:
                break
        else:
            raise Exception(f"Temp image not found: {self.uuid_hex}")

        bpy.data.images.remove(image, do_unlink=True)


class UV_Override:

    def __init__(self, material: bpy.types.Material, uv_image):
        self.material = material
        self.uv_image = uv_image

    def __enter__(self):

        def get_node_trees(starting_node_tree: bpy.types.ShaderNodeTree, node_trees: typing.Set[bpy.types.ShaderNodeTree] = None):
            if node_trees == None:
                node_trees = set()
            node_trees.add(starting_node_tree)
            for node in starting_node_tree.nodes:
                if node.bl_idname == 'ShaderNodeGroup' and node.node_tree != None:
                    get_node_trees(node.node_tree, node_trees)
            return node_trees

        node_trees = list(get_node_trees(self.material.node_tree))

        self.initial_links = {node_tree: [] for node_tree in node_trees}
        self.temp_nodes = {node_tree: [] for node_tree in node_trees}

        for node_tree in node_trees:
            nodes = node_tree.nodes
            links = node_tree.links

            uv_image_node = nodes.new('ShaderNodeTexImage')
            uv_image_node.image = self.uv_image
            uv_image_node.interpolation = 'Closest'

            self.temp_nodes[node_tree].append(uv_image_node)
            uv_output = uv_image_node.outputs[0]

            for link in links:
                node_type = link.from_node.type
                if node_type == 'UVMAP':
                    self.initial_links[node_tree].append((link.from_socket, link.to_socket))
                    links.new(uv_output, link.to_socket)
                elif node_type == 'TEX_COORD' and link.from_socket.name == 'UV':
                    self.initial_links[node_tree].append((link.from_socket, link.to_socket))
                    links.new(uv_output, link.to_socket)

            for node in [node for node in nodes if node.type == 'TEX_IMAGE' and node != uv_image_node and not node.inputs[0].links]:
                links.new(uv_output, node.inputs[0])

    def __exit__(self, type, value, traceback):
        for node_tree, initial_links in self.initial_links.items():
            links = node_tree.links
            for link in initial_links:
                links.new(link[0], link[1])

        for node_tree, temp_nodes in self.temp_nodes.items():
            nodes = node_tree.nodes
            for temp_node in temp_nodes:
                temp_node.image = None # fixes blender.exe image_acquire_ibuf EXCEPTION_ACCESS_VIOLATION crash
                nodes.remove(temp_node)


class Baking_Image_Node:

    def __init__(self, material: bpy.types.Material, image: bpy.types.Image):
        self.nodes = material.node_tree.nodes
        self.image = image

    def __enter__(self):
        image_node = self.nodes.new('ShaderNodeTexImage')
        image_node.image = self.image
        image_node.select = True
        self.initial_active_node = self.nodes.active
        self.nodes.active = image_node
        self.image_node = image_node

    def __exit__(self, type, value, traceback):
        self.nodes.remove(self.image_node)
        self.nodes.active = self.initial_active_node


class No_Active_Image:

    def __init__(self, material: bpy.types.Material):
        self.nodes = material.node_tree.nodes

    def __enter__(self):
        for node in self.nodes:
            node.select = False
        self.image_node = self.nodes.new('ShaderNodeTexImage')
        self.image_node.select = True
        self.initial_active_node = self.nodes.active
        self.nodes.active = self.image_node

    def __exit__(self, type, value, traceback):
        self.nodes.remove(self.image_node)
        self.nodes.active = self.initial_active_node


class Output_Override:


    def __init__(self, material: bpy.types.Material, target_socket_output: bpy.types.NodeSocketStandard):

        self.tree = bpy_node.Shader_Tree_Wrapper(material.node_tree)

        assert target_socket_output.is_output if target_socket_output else True, f"R cannel {target_socket_output} should be an output socket."
        self.target_socket_output = self.tree.get_socket_wrapper(target_socket_output)


    def __enter__(self):

        if self.tree.surface_input.connections:
            self.initial_output = self.tree.surface_input.connections[0]
        else:
            self.initial_output = None

        if self.target_socket_output.be('NodeSocketShader'):
            self.tree.surface_input.join(self.target_socket_output, move=False)
        else:
            self.tree.surface_input.new('ShaderNodeEmission').inputs[0].join(self.target_socket_output, move=False)


    def __exit__(self, type, value, traceback):
        self.tree.delete_new_nodes()

        if self.initial_output:
            self.initial_output.join(self.tree.surface_input, move = False)


class Output_Override_Combine_RGB:


    def __init__(self, material: bpy.types.Material, r: typing.Optional[bpy.types.NodeSocketStandard], g: typing.Optional[bpy.types.NodeSocketStandard], b: typing.Optional[bpy.types.NodeSocketStandard]):

        assert r.is_output if r else True, f'R cannel {r} should be an output socket.'
        assert g.is_output if g else True, f'G cannel {g} should be an output socket.'
        assert b.is_output if b else True, f'B cannel {b} should be an output socket.'

        self.tree = bpy_node.Shader_Tree_Wrapper(material.node_tree)

        self.r = self.tree.get_socket_wrapper(r) if r else None
        self.g = self.tree.get_socket_wrapper(g) if g else None
        self.b = self.tree.get_socket_wrapper(b) if b else None


    def __enter__(self):

        if self.tree.surface_input.connections:
            self.initial_output = self.tree.surface_input.connections[0]
        else:
            self.initial_output = None

        node = self.tree.surface_input.new('ShaderNodeEmission')

        combine_xyz = node.inputs[0].new('ShaderNodeCombineXYZ')

        if self.r:
            combine_xyz.inputs[0].join(self.r, False)
        if self.g:
            combine_xyz.inputs[1].join(self.g, False)
        if self.b:
            combine_xyz.inputs[2].join(self.b, False)


    def __exit__(self, type, value, traceback):
        self.tree.delete_new_nodes()

        if self.initial_output:
            self.initial_output.join(self.tree.surface_input, move = False)


class Output_Socket_World_Space_To_Tangent_Space:


    def __init__(self, material: bpy.types.Material, target_socket_output: bpy.types.NodeSocketStandard, uv_layer_name: str):

        assert target_socket_output.is_output, 'target_socket_output should be an output socket.'

        self.tree = bpy_node.Shader_Tree_Wrapper(material.node_tree)
        self.target_socket_output = self.tree.get_socket_wrapper(target_socket_output)
        self.uv_layer_name = uv_layer_name


    def __enter__(self):

        first_node = self.tree.new('ShaderNodeVectorMath', operation = 'ADD')
        first_node[1] = (0.5, 0.5, 0.5)

        node = first_node.inputs[0].new('ShaderNodeVectorMath', operation = 'MULTIPLY')
        node[1] = (0.5, 0.5, 0.5)

        combine_xyz = node.inputs[0].new('ShaderNodeCombineXYZ')

        dot_product_1 = combine_xyz.inputs[0].new('ShaderNodeVectorMath', 'Value', operation = 'DOT_PRODUCT')
        dot_product_2 = combine_xyz.inputs[1].new('ShaderNodeVectorMath', 'Value', operation = 'DOT_PRODUCT')
        dot_product_3 = combine_xyz.inputs[2].new('ShaderNodeVectorMath', 'Value', operation = 'DOT_PRODUCT')

        dot_product_1.inputs[0].join(self.target_socket_output, move=False)
        dot_product_2.inputs[0].join(self.target_socket_output, move=False)
        dot_product_3.inputs[0].join(self.target_socket_output, move=False)

        tangent = dot_product_1.inputs[1].new('ShaderNodeTangent')
        tangent.direction_type = 'UV_MAP'
        tangent.uv_map = self.uv_layer_name

        node = dot_product_2.inputs[1].new('ShaderNodeVectorMath', operation = 'MULTIPLY')

        attr_node = node.inputs[1].new('ShaderNodeAttribute')
        attr_node.attribute_type = 'GEOMETRY'
        attr_node.attribute_name = self.uv_layer_name + '.tangent_sign'

        node = node.inputs[0].new('ShaderNodeVectorMath', operation = 'CROSS_PRODUCT')

        node.inputs[1].join(tangent.outputs[0], move=False)

        geometry = node.inputs[0].new('ShaderNodeNewGeometry', 'Normal')
        geometry.outputs['Normal'].join(dot_product_3.inputs[1])

        return first_node.outputs[0].bl_socket


    def __exit__(self, type, value, traceback):
        self.tree.delete_new_nodes()


class Output_Socket_Ambient_Occlusion:

    def __init__(self, material: bpy.types.Material, normal_output: bpy.types.NodeSocketStandard, only_local = False, samples = 16):

        self.tree = bpy_node.Shader_Tree_Wrapper(material.node_tree)

        self.only_local = only_local
        self.samples = samples

        if normal_output:
            self.normal_output = self.tree.get_socket_wrapper(normal_output)
        else:
            self.normal_output = None

    def __enter__(self):

        ao_node = self.tree.new('ShaderNodeAmbientOcclusion')
        ao_node.only_local = self.only_local
        ao_node.samples = self.samples

        if self.normal_output:
            ao_node.inputs['Normal'].join(self.normal_output, move = False)

        return ao_node.outputs['AO'].bl_socket

    def __exit__(self, type, value, traceback):
        self.tree.delete_new_nodes()


class Output_Socket_Diffuse_AO:
    """ Diffuse based AO. """

    node_tree_name = '__blend_converter_diffuse_ao_bake'


    def __init__(self, material: bpy.types.Material, ignore_backface = False, faster = True, environment_has_alpha = True, use_normals = True):
        """ Assumes a Principled BSDF material. """

        self.tree = bpy_node.Shader_Tree_Wrapper(material.node_tree)

        self.ignore_backface = ignore_backface

        self.faster = faster
        self.environment_has_alpha = environment_has_alpha

        self.use_normals = use_normals


    def get_diffuse_mixin_node_tree(self, has_alpha: bool):

        bl_tree = bpy.data.node_groups.get(self.node_tree_name)
        if bl_tree:
            return bl_tree

        tree = bpy_node.Shader_Tree_Wrapper(bpy.data.node_groups.new(self.node_tree_name, 'ShaderNodeTree'))

        if hasattr(tree.bl_tree, 'interface'):
            tree.bl_tree.interface.new_socket(name='Shader', in_out='INPUT', socket_type='NodeSocketShader')
            tree.bl_tree.interface.new_socket(name='Normal', in_out='INPUT', socket_type='NodeSocketVector')
            tree.bl_tree.interface.new_socket(name='Shader', in_out='OUTPUT', socket_type='NodeSocketShader')
        else:
            tree.bl_tree.inputs.new('NodeSocketShader', 'Shader')
            tree.bl_tree.inputs.new('NodeSocketVector', 'Normal')
            tree.bl_tree.outputs.new('NodeSocketShader', 'Shader')

        output = tree.new('NodeGroupOutput')
        mix_shader = output.inputs[0].new('ShaderNodeMixShader')

        # TODO: instead of using the full shader, make a simple one using only the material's transparency for a faster bake

        mix_shader.inputs[0].new('ShaderNodeLightPath', 'Is Camera Ray')
        diffuse_node = mix_shader.inputs[2].new('ShaderNodeBsdfDiffuse')
        diffuse_node['Color'] = (1,1,1,1)

        node_group_input = mix_shader.inputs[1].new('NodeGroupInput')  # this is expensive

        if self.use_normals:
            diffuse_node.inputs['Normal'].join(node_group_input.outputs[1], move = False)

        if self.faster and not (self.environment_has_alpha or has_alpha):
            mix_shader.inputs[1].new('ShaderNodeBsdfDiffuse').inputs['Color'].set_default_value(0)

        if self.ignore_backface:
            mix_shader_2 = mix_shader.inputs[1].insert_new('ShaderNodeMixShader', new_node_identifier = 1)
            mix_shader_2.inputs[2].new('ShaderNodeBsdfTransparent')
            mix_shader_2.inputs[0].new('ShaderNodeNewGeometry', 'Backfacing')
        else:  # a lossy workaround to avoid artifacts, requires the inpaint
            mix_shader_2 = mix_shader.outputs[0].insert_new('ShaderNodeMixShader', 1)
            mix_shader_2.inputs[2].new('ShaderNodeBsdfTransparent')
            math_multiply = mix_shader_2.inputs[0].new('ShaderNodeMath', operation='MULTIPLY')
            geometry = math_multiply.inputs[1].new('ShaderNodeNewGeometry', 'Backfacing')
            math_less_than = math_multiply.inputs[0].new('ShaderNodeMath', operation='LESS_THAN')
            math_less_than.inputs[1].default_value = 0
            math_dot_product = math_less_than.inputs[0].new('ShaderNodeVectorMath', 'Value', operation='DOT_PRODUCT')
            geometry.outputs['Normal'].join(math_dot_product.inputs[0], False)
            geometry.outputs['True Normal'].join(math_dot_product.inputs[1], False)

        return tree.bl_tree


    def __enter__(self) -> bpy.types.NodeSocketShader:

        principled = self.tree.output[0]

        has_alpha = principled.inputs['Alpha'].connections or not principled.inputs['Alpha'].is_close(1)

        node_group = principled.outputs[0].new('ShaderNodeGroup', node_tree = self.get_diffuse_mixin_node_tree(has_alpha))

        if principled['Normal']:
            node_group.inputs[1].join(principled.inputs['Normal'].as_output(), move = False)

        return node_group.outputs[0].bl_socket


    def __exit__(self, type, value, traceback):
        self.tree.delete_new_nodes()


class Diffuse_AO_Bake_Settings(State):

    ao_bake_world_name = '__blend_converter_ao_bake_world_name'


    def __init__(self, samples = 16, faster = False):
        super().__init__()

        context = bpy.context
        scene = context.scene
        cycles = context.scene.cycles  # type: typing.Any
        render = context.scene.render

        self.set(render, 'engine', 'CYCLES')

        self.set(scene, 'world', self.get_world())

        if faster:

            self.set(cycles, 'samples', int(math.sqrt(samples)))

            if bpy.app.version >= (2, 93):
                self.set(cycles, 'use_fast_gi', True)
                self.set(cycles, 'ao_bounces', 2)
                self.set(cycles, 'ao_bounces_render', 2)
                self.set(scene.world.light_settings, 'ao_factor', 1)
                self.set(scene.world.light_settings, 'distance', 10)
                self.set(cycles, 'fast_gi_method', 'REPLACE')

            self.set(cycles, 'caustics_refractive', False)
            self.set(cycles, 'caustics_reflective', False)

            self.set(cycles, 'max_bounces', 8)
            self.set(cycles, 'diffuse_bounces', 4)
            self.set(cycles, 'glossy_bounces', 2)
            self.set(cycles, 'transmission_bounces', 8)
            self.set(cycles, 'volume_bounces', 0)
            self.set(cycles, 'transparent_max_bounces', 8)

        else:

            self.set(cycles, 'samples', samples)

            if bpy.app.version >= (2, 93):
                self.set(cycles, 'use_fast_gi', False)

            self.set(cycles, 'caustics_refractive', True)
            self.set(cycles, 'caustics_reflective', True)

            self.set(cycles, 'max_bounces', 12)
            self.set(cycles, 'diffuse_bounces', 8)
            self.set(cycles, 'glossy_bounces', 4)
            self.set(cycles, 'transmission_bounces', 12)
            self.set(cycles, 'volume_bounces', 0)
            self.set(cycles, 'transparent_max_bounces', 8)


        try:
            self.set(render.bake, 'view_from', 'ABOVE_SURFACE')
        except AttributeError:
            pass

        self.set(cycles, 'bake_type', 'COMBINED')

        self.set(render.bake, 'use_pass_direct', True)
        self.set(render.bake, 'use_pass_indirect', True)
        self.set(render.bake, 'use_pass_diffuse', True)
        self.set(render.bake, 'use_pass_glossy', True)
        self.set(render.bake, 'use_pass_transmission', True)

        self.set(render.bake, 'margin', blend_inspector.get_value('ao_denoise_margin', 1))

        self.set(render.bake, 'use_pass_emit', False)
        for object in bpy.data.objects:
            if object.type == 'LIGHT':
                self.set(object, 'hide_render', True)


    def get_world(self):

        world = bpy.data.worlds.get(self.ao_bake_world_name)
        if world:
            return world

        world = bpy.data.worlds.new(name=self.ao_bake_world_name)

        if bpy.app.version < (5, 0):
            # Nodes: Remove "Use Nodes" in Shader Editor for World #142342
            # https://projects.blender.org/blender/blender/pulls/142342
            world.use_nodes = True

        background = next(bl_node for bl_node in world.node_tree.nodes if bl_node.bl_idname == 'ShaderNodeBackground')
        background.inputs[0].default_value = (1, 1, 1, 1)

        return world


class Compositor_Input_Raw:


    def __init__(self, input_socket: typing.Union['bpy.types.NodeSocketFloat', 'bpy.types.NodeSocketColor'], image: bpy.types.Image, channel: int):

        self.tree = bpy_node.Compositor_Tree_Wrapper.from_scene(bpy.context.scene)
        self.input_socket = self.tree.get_socket_wrapper(input_socket)
        self.image = image

        self.channel = channel

    def __enter__(self):

        image_node = self.input_socket.new('CompositorNodeImage', image = self.image)

        if self.channel == -1:
            pass
        elif self.channel in (0, 1, 2):
            image_node.outputs[0].insert_new(bpy_node.Compositor_Node_Type.SEPARATE_RGBA, new_node_identifier = self.channel)
        else:
            raise Exception(f"Unexpected image channel: {self.channel}")


    def __exit__(self, type, value, traceback):
        self.tree.delete_new_nodes()


class Compositor_Input_Default:


    def __init__(self, input_socket: typing.Union['bpy.types.NodeSocketFloat', 'bpy.types.NodeSocketColor'], image: bpy.types.Image, channel: int, use_denoise = False):

        self.tree = bpy_node.Compositor_Tree_Wrapper.from_scene(bpy.context.scene)
        self.input_socket = self.tree.get_socket_wrapper(input_socket)
        self.image = image

        self.use_denoise = use_denoise
        self.channel = channel


    def __enter__(self):

        image_node = self.input_socket.new('CompositorNodeImage', image = self.image)

        inpaint_distance = max(self.image.generated_height, self.image.generated_width)
        inpaint_distance = min(inpaint_distance, 512)

        if self.use_denoise:

            denoise_tree = bpy_data.load_compositor_node_tree('BC_C_Denoise_Default')
            set_denoise_tree_settings(denoise_tree, inpaint_distance)

            denoise_group = image_node.outputs[0].insert_new('CompositorNodeGroup', node_tree = denoise_tree)

            image_node.outputs[1].join(denoise_group.inputs[1])  # connect Alpha


        else:

            set_alpha_node = image_node.outputs[0].insert_new('CompositorNodeSetAlpha')

            math_node = image_node.outputs[1].new(bpy_node.Compositor_Node_Type.MATH, operation = 'GREATER_THAN')
            math_node.inputs[1].default_value = 0.9999
            math_node.outputs[0].join(set_alpha_node.inputs[1])

            inpaint_node = set_alpha_node.outputs[0].insert_new('CompositorNodeInpaint')

            if bpy.app.version >= (5, 0):
                inpaint_node.inputs[1].default_value = inpaint_distance
            else:
                inpaint_node.distance = inpaint_distance

        if self.channel == -1:
            pass
        elif self.channel in (0, 1, 2):
            image_node.outputs[0].insert_new(bpy_node.Compositor_Node_Type.SEPARATE_RGBA, new_node_identifier = self.channel)
        else:
            raise Exception(f"Unexpected image channel: {self.channel}")


    def __exit__(self, type, value, traceback):
        self.tree.delete_new_nodes()


class Compositor_Input_Fill_Color:
    """ TODO: The compositor render is not triggered if the first image is not an image file. A bug? """


    def __init__(self, input_socket: typing.Union['bpy.types.NodeSocketFloat', 'bpy.types.NodeSocketColor'], image: bpy.types.Image):

        self.tree = bpy_node.Compositor_Tree_Wrapper.from_scene(bpy.context.scene)
        self.input_socket = self.tree.get_socket_wrapper(input_socket)
        self.image = image


    def __enter__(self):
        self.input_socket.new('CompositorNodeImage', image = self.image)


    def __exit__(self, type, value, traceback):
        self.tree.delete_new_nodes()


class Compositor_Input_AO_Diffuse:


    def __init__(self, input_socket: typing.Union['bpy.types.NodeSocketFloat', 'bpy.types.NodeSocketColor'], image: bpy.types.Image):

        self.tree = bpy_node.Compositor_Tree_Wrapper.from_scene(bpy.context.scene)
        self.input_socket = self.tree.get_socket_wrapper(input_socket)
        self.image = image


    def __enter__(self):

        image_node = self.input_socket.new('CompositorNodeImage', image = self.image)

        inpaint_distance = max(self.image.generated_height, self.image.generated_width)
        inpaint_distance = min(inpaint_distance, 512)

        denoise_tree = bpy_data.load_compositor_node_tree('BC_C_Denoise_AO_Diffuse')
        set_denoise_tree_settings(denoise_tree, inpaint_distance, quality = 'HIGH')

        denoise_group = image_node.outputs[0].insert_new('CompositorNodeGroup', node_tree = denoise_tree)

        image_node.outputs[1].join(denoise_group.inputs[1])  # connect Alpha


    def __exit__(self, type, value, traceback):
        self.tree.delete_new_nodes()



def set_mode(objects: typing.List[bpy.types.Object], mode: str, view_layer: 'bpy.types.ViewLayer'):
    """
    `bpy.ops.object.mode_set` works for multiple selected objects, but.

    If the active object does not support the mode — it will error.
    `TypeError: Converting py args to operator properties: enum "EDIT" not found in ('OBJECT')`

    If a data has multiple users it will change the mode only for a single object that uses that data.

    If the active object already in the mode — it wont set the mode for the other objects.

    If the active object is hidden by its collection its mode can be changed but not the mode of other selected objects.

    blender/source/blender/editors/object/object_modes.cc::mode_compat_test
    https://github.com/blender/blender/blob/97f9e100546256b1f7432f85057de523724644eb/source/blender/editors/object/object_modes.cc#L99

    88051 - Context override of bpy.ops.object.mode_set does not work
    https://projects.blender.org/blender/blender/issues/88051

    If there are multiple objects in EDIT mode bpy.ops.object.mode_set(mode='OBJECT') will set the OBJECT mode for all of them.
    Even if they are not active and not selected.
    Practically means that first you have to set the OBJECT mode and then the EDIT mode.
    """

    for object_type, objects_of_type in utils.list_by_key(objects, operator.attrgetter('type')).items():


        if all(object.mode == mode for object in objects_of_type):
            continue


        for object in filter(None, view_layer.objects):
            object.select_set(object in objects_of_type, view_layer=view_layer)


        for object in objects_of_type:
            if object.mode != mode:
                view_layer.objects.active = object


        result = bpy.ops.object.mode_set(mode=mode)
        assert not 'CANCELLED' in result

        if all(object.mode == mode for object in objects_of_type):
            continue

        text = f"Fail to set '{mode}' mode for '{object_type}' objects: {[o.name_full for o in objects_of_type]}"

        if any(len(objects) > 1 for objects in utils.list_by_key(objects_of_type, lambda x: x.data).values()):
            info = json.dumps(utils.list_by_key(objects_of_type, lambda x: x.data.name_full), indent=4, default=lambda x: x.name_full)
            raise Exception(text + "\n\t" + f"Multiple data users: {info}")
        elif any(not o.visible_get(view_layer=view_layer) for o in objects_of_type):
            raise Exception(text + "\n\t" + f"Objects not visible: {[o.name_full for o in objects_of_type if not o.visible_get(view_layer=view_layer)]}")
        else:
            raise Exception(text + "\n\t" + "Unknown reason.")


class Focus:


    def __init__(self, objects: typing.Union[bpy.types.Object, typing.List[bpy.types.Object]], mode = 'OBJECT', view_layer: 'bpy.types.ViewLayer' = None):

        if view_layer is None:
            view_layer = bpy.context.view_layer

        self._view_layer = view_layer

        if isinstance(objects, bpy.types.Object):
            objects = [objects]

        self.focused_objects = list(dict.fromkeys(objects))

        self.mode = mode

        self.visibility_states = []


    @property
    def view_layer(self) -> 'bpy.types.ViewLayer':
        return self.references[0].path_resolve(self._view_layer_path_from_id)


    @property
    def visible_collection(self) -> 'bpy.types.Collection':
        return self.references[1]


    @property
    def init_active_object(self) -> bpy.types.Object:
        return self.references[2]


    @property
    def affected_objects(self) -> typing.List[bpy.types.Object]:
        return list(self.references)[3:]


    def __enter__(self):

        self.references = Bpy_Reference_Collection().__enter__()

        self._view_layer_path_from_id = self._view_layer.path_from_id()
        self.references.append(self._view_layer.id_data)

        view_layer = self.view_layer

        affected_objects = [object for object in bpy_utils.get_view_layer_objects(view_layer) if object.visible_get(view_layer=view_layer)] + self.focused_objects
        affected_objects = list(dict.fromkeys(affected_objects))

        visible_collection = bpy.data.collections.new('__bc_focus')
        view_layer.layer_collection.collection.children.link(visible_collection)
        self.references.append(visible_collection)

        self.references.append(view_layer.objects.active)

        for object in affected_objects:

            self.visibility_states.append((
                object.mode,
                object.visible_get(view_layer = view_layer),
                object.select_get(view_layer = view_layer),
                object.hide_get(view_layer = view_layer),
                object.hide_viewport,
                object.hide_select,
            ))

            self.references.append(object)

        for object in self.focused_objects:
            visible_collection.objects.link(object)
            object.hide_set(False, view_layer=view_layer)
            object.hide_viewport = False
            object.hide_select = False

        for object in self.focused_objects:
            if not object.visible_get(view_layer=view_layer):
                # TODO: objects can be hidden by drivers
                # TODO: what it we want to work with the object hidden
                raise Exception(f"Fail to focus object: not visible: {object.name_full}")

        set_mode(affected_objects, 'OBJECT', view_layer)
        set_mode(self.focused_objects, self.mode, view_layer)

        for object in affected_objects:
            object.select_set(object in self.focused_objects, view_layer=view_layer)

        view_layer.objects.active = self.focused_objects[0]

        return self


    def __exit__(self, type, value, traceback):

        view_layer = self.view_layer
        visible_collection = self.visible_collection

        affected = [item for item in zip(self.affected_objects, self.visibility_states) if not item[0] is None]
        affected_objects: typing.List[bpy.types.Object] = list(map(operator.itemgetter(0), affected))

        for object in affected_objects:
            if not object.visible_get(view_layer=view_layer):
                visible_collection.objects.link(object)

        set_mode(affected_objects, 'OBJECT', view_layer)

        mode_to_objects = collections.defaultdict(list)
        for object, state in affected:
            mode_to_objects[state[0]].append(object)

        for mode, objects_in_mode in mode_to_objects.items():
            set_mode(objects_in_mode, mode, view_layer)


        for object, state in affected:

            if object.mode != state[0]:
                raise Exception(f"Fail to reset '{state[0]}' mode: '{object.name_full}' in mode '{object.mode}'")

            object.select_set(state[2], view_layer = view_layer)
            object.hide_set(state[3], view_layer = view_layer)
            object.hide_viewport = state[4]
            object.hide_select = state[5]

        bpy.data.collections.remove(visible_collection)

        view_layer.update()
        scene_objects = set(list(filter(None, view_layer.objects)))

        for object, state in affected:
            if object in scene_objects and object.visible_get(view_layer=view_layer) != state[1]:
                raise Exception(f"Fail to revert visibility to {state[1]}: {object.name_full}")

        if self.init_active_object in scene_objects:
            view_layer.objects.active = self.init_active_object

        self.references.__exit__(type, value, traceback)


class Light_Map_Bake_Settings(State):


        def __init__(self, samples = 16):
            super().__init__()

            context = bpy.context
            scene = context.scene
            cycles = context.scene.cycles
            render = context.scene.render
            bake = render.bake

            self.set(render, 'engine', 'CYCLES')
            self.set(cycles, 'samples', samples)

            if bpy.app.version >= (2, 93):
                self.set(cycles, 'use_fast_gi', False)

            self.set(cycles, 'caustics_refractive', True)
            self.set(cycles, 'caustics_reflective', True)

            self.set(cycles, 'max_bounces', 12)
            self.set(cycles, 'diffuse_bounces', 8)
            self.set(cycles, 'glossy_bounces', 4)
            self.set(cycles, 'transmission_bounces', 12)
            self.set(cycles, 'volume_bounces', 0)
            self.set(cycles, 'transparent_max_bounces', 8)


            try:
                self.set(bake, 'view_from', 'ABOVE_SURFACE')
            except AttributeError:
                pass


            # ADJACENT_FACES can make the thing worse with direct lights
            # kind of the same it does to normals
            try:
                self.set(bake, 'margin_type', 'EXTEND')
            except AttributeError:
                pass
            self.set(bake, 'margin', 0)


            self.set(cycles, 'bake_type', 'COMBINED')

            self.set(bake, 'use_pass_direct', True)
            self.set(bake, 'use_pass_indirect', True)
            self.set(bake, 'use_pass_diffuse', True)
            self.set(bake, 'use_pass_glossy', True)
            self.set(bake, 'use_pass_transmission', True)
            self.set(bake, 'use_pass_emit', True)


class Output_Lightmap:

    node_tree_name = '__blend_converter_lightmap_bake'


    def __init__(self, material: 'bpy.types.Material', use_normals = False):
        self.tree = bpy_node.Shader_Tree_Wrapper(material.node_tree)
        self.use_normals = use_normals


    def get_diffuse_mixin_node_tree(self):

        bl_tree = bpy.data.node_groups.get(self.node_tree_name)
        if bl_tree:
            return bl_tree

        tree = bpy_node.Shader_Tree_Wrapper(bpy.data.node_groups.new(self.node_tree_name, 'ShaderNodeTree'))

        if hasattr(tree.bl_tree, 'interface'):
            tree.bl_tree.interface.new_socket(name='Shader', in_out='INPUT', socket_type='NodeSocketShader')
            tree.bl_tree.interface.new_socket(name='Normal', in_out='INPUT', socket_type='NodeSocketVector')
            tree.bl_tree.interface.new_socket(name='Shader', in_out='OUTPUT', socket_type='NodeSocketShader')
        else:
            tree.bl_tree.inputs.new('NodeSocketShader', 'Shader')
            tree.bl_tree.inputs.new('NodeSocketVector', 'Normal')
            tree.bl_tree.outputs.new('NodeSocketShader', 'Shader')

        output = tree.new('NodeGroupOutput')
        mix_shader = output.inputs[0].new('ShaderNodeMixShader')

        mix_shader.inputs[0].new('ShaderNodeLightPath', 'Is Camera Ray')
        node_group_input = mix_shader.inputs[1].new('NodeGroupInput')
        diffuse_node = mix_shader.inputs[2].new('ShaderNodeBsdfDiffuse')
        diffuse_node['Color'] = (1,1,1,1)
        diffuse_node.inputs['Normal'].join(node_group_input.outputs[1], move = False)

        # a lossy workaround to avoid artifacts, requires the inpaint
        mix_shader_2 = mix_shader.outputs[0].insert_new('ShaderNodeMixShader', 1)
        mix_shader_2.inputs[2].new('ShaderNodeBsdfTransparent')
        math_multiply = mix_shader_2.inputs[0].new('ShaderNodeMath', operation='MULTIPLY')
        geometry = math_multiply.inputs[1].new('ShaderNodeNewGeometry', 'Backfacing')
        math_less_than = math_multiply.inputs[0].new('ShaderNodeMath', operation='LESS_THAN')
        math_less_than.inputs[1].default_value = 0
        math_dot_product = math_less_than.inputs[0].new('ShaderNodeVectorMath', 'Value', operation='DOT_PRODUCT')
        geometry.outputs['Normal'].join(math_dot_product.inputs[0], False)
        geometry.outputs['True Normal'].join(math_dot_product.inputs[1], False)

        return tree.bl_tree


    def __enter__(self) -> 'bpy.types.NodeSocketShader':

        principled = self.tree.output[0]

        node_group = principled.outputs[0].new('ShaderNodeGroup', node_tree = self.get_diffuse_mixin_node_tree())

        if principled['Normal'] and self.use_normals:
            node_group.inputs[1].join(principled.inputs['Normal'].as_output(), move = False)

        return node_group.outputs[0].bl_socket


    def __exit__(self, type, value, traceback):
        self.tree.delete_new_nodes()


class Compositor_Input_Lightmap:


    def __init__(self, input_socket: typing.Union['bpy.types.NodeSocketFloat', 'bpy.types.NodeSocketColor'], image: bpy.types.Image):

        self.tree = bpy_node.Compositor_Tree_Wrapper.from_scene(bpy.context.scene)
        self.input_socket = self.tree.get_socket_wrapper(input_socket)
        self.image = image

        self.init_dither_intensity = bpy.context.scene.render.dither_intensity


    def __enter__(self):

        bpy.context.scene.render.dither_intensity = 1.0

        distance = max(self.image.generated_height, self.image.generated_width)
        distance = min(distance, 512)

        inpaint = self.input_socket.new('CompositorNodeInpaint', distance = distance)

        set_alpha_1 = inpaint.inputs[0].new('CompositorNodeSetAlpha')

        denoise = set_alpha_1.inputs[0].new('CompositorNodeDenoise')

        if bpy.app.version >= (5, 0):
            denoise.inputs[3].default_value = False
            denoise.inputs[4].default_value = 'None'
        else:
            denoise.prefilter = 'NONE'
            denoise.use_hdr = False

        inpaint_px_1 = denoise.inputs['Image'].new('CompositorNodeInpaint', distance=1)
        # inpaint_px_1.outputs[0].new(bpy_node.Compositor_Node_Type.SEPARATE_RGBA).outputs[3].join(denoise.inputs['Albedo'])


        inpaint_px_2 = inpaint_px_1.inputs[0].new('CompositorNodeInpaint', distance=1)

        set_alpha_2 = inpaint_px_2.inputs[0].new('CompositorNodeSetAlpha')

        image_node = set_alpha_2.inputs['Image'].new('CompositorNodeImage', image = self.image)

        math_node = set_alpha_2.inputs['Alpha'].new(bpy_node.Compositor_Node_Type.MATH, operation = 'GREATER_THAN')
        math_node.inputs[0].join(image_node.outputs['Alpha'])
        math_node.inputs[1].default_value = 0.9999

        image_node.outputs['Alpha'].join(set_alpha_1.inputs['Alpha'])


    def __exit__(self, type, value, traceback):
        self.tree.delete_new_nodes()

        bpy.context.scene.render.dither_intensity = self.init_dither_intensity


def call_in_uv_editor(func, *args, can_be_canceled = False, **kwargs):
    """ Because some functionally of the operators can change depending on it."""

    with State() as state:

        window = bpy.data.window_managers[0].windows[0]

        area = window.screen.areas[0]
        state.set(area, 'type', 'IMAGE_EDITOR')
        state.set(area, 'ui_type', 'UV')

        space_data = area.spaces.active

        window_region = next(region for region in area.regions if region.type == 'WINDOW')

        override = dict(
            window=window,
            workspace=window.workspace,
            screen=window.screen,
            area = area,
            space_data = space_data,
            region = window_region,
        )

        call(override, func, *args, can_be_canceled = can_be_canceled, **kwargs)


class Empty_Scene:

    def __enter__(self):
        bpy.ops.scene.new(type='EMPTY')
        return self

    def __exit__(self, type, value, traceback):
        bpy.ops.scene.delete()


class Isolate_Focus:


    def __init__(self, objects: typing.List[bpy.types.Object], mode = 'OBJECT'):

        if type(objects) is bpy.types.Object:
            objects = [objects]

        self.objects = objects
        self.mode = mode


    def __enter__(self):

        bpy.ops.scene.new(type='EMPTY')
        bpy.ops.scene.view_layer_add(type='EMPTY')

        view_layer = bpy.context.view_layer

        for object in self.objects:
            bpy.context.scene.collection.objects.link(object)

        for object in self.objects:
            if not object.visible_get(view_layer=view_layer):
                raise Exception(f"Fail to focus object: not visible: {object.name_full}")

        set_mode(self.objects, self.mode, view_layer)

        for object in self.objects:
            object.select_set(True, view_layer=view_layer)

        view_layer.objects.active = self.objects[0]

        return self


    def __exit__(self, type, value, traceback):
        bpy.ops.scene.view_layer_remove()
        bpy.ops.scene.delete()



class Compositor_Input_Factor:


    def __init__(self, input_socket: typing.Union['bpy.types.NodeSocketFloat', 'bpy.types.NodeSocketColor'], image: bpy.types.Image, channel: int, use_denoise = False):

        self.tree = bpy_node.Compositor_Tree_Wrapper.from_scene(bpy.context.scene)
        self.input_socket = self.tree.get_socket_wrapper(input_socket)
        self.image = image

        self.use_denoise = use_denoise

        self.channel = channel


    def __enter__(self):

        image_node = self.input_socket.new('CompositorNodeImage', image = self.image)

        if self.use_denoise:

            denoise_tree = bpy_data.load_compositor_node_tree('BC_C_Denoise_Factor')
            set_denoise_tree_settings(denoise_tree, 16)

            denoise_group = image_node.outputs[0].insert_new('CompositorNodeGroup', node_tree = denoise_tree)
            image_node.outputs['Alpha'].join(denoise_group.inputs[1])
        else:
            init_alpha_node = image_node.outputs[0].insert_new('CompositorNodeSetAlpha')
            math_node = image_node.outputs['Alpha'].new(bpy_node.Compositor_Node_Type.MATH, operation = 'GREATER_THAN')
            math_node.inputs[1].default_value = 0.9999
            math_node.outputs[0].join(init_alpha_node.inputs[1])
            init_alpha_node.outputs[0].insert_new('CompositorNodeInpaint', distance = 16)

        if self.channel == -1:
            pass
        elif self.channel in (0, 1, 2):
            image_node.outputs[0].insert_new(bpy_node.Compositor_Node_Type.SEPARATE_RGBA, new_node_identifier = self.channel)
        else:
            raise Exception(f"Unexpected image channel: {self.channel}")


    def __exit__(self, type, value, traceback):
        self.tree.delete_new_nodes()


def insert_normalize(node: 'bpy_node._Shader_Node_Wrapper', use_map_range = True):

    normalize_normal = node.outputs[0].insert_new('CompositorNodeGroup', node_tree = bpy_data.load_compositor_node_tree('BC_C_Normalize_Vector'))

    if not use_map_range:
        return

    map_range_1 = normalize_normal.inputs[0].insert_new('CompositorNodeGroup', node_tree = bpy_data.load_compositor_node_tree('BC_C_Map_Range_Image'))
    map_range_1[1] = 0
    map_range_1[2] = 1
    map_range_1[3] = -1
    map_range_1[4] = 1

    map_range_2 = normalize_normal.outputs[0].insert_new('CompositorNodeGroup', node_tree = bpy_data.load_compositor_node_tree('BC_C_Map_Range_Image'))
    map_range_2[1] = -1
    map_range_2[2] = 1
    map_range_2[3] = 0
    map_range_2[4] = 1

class Compositor_Input_Normal:


    def __init__(self,
                 input_socket: typing.Union['bpy.types.NodeSocketFloat', 'bpy.types.NodeSocketColor'],
                 image: bpy.types.Image,
                 use_denoise = False,
                 use_remove_inward_normals = False,
                 denoise_mix_factor = 1.0,
            ):

        self.tree = bpy_node.Compositor_Tree_Wrapper.from_scene(bpy.context.scene)
        self.input_socket = self.tree.get_socket_wrapper(input_socket)
        self.image = image

        self.use_denoise = use_denoise
        self.use_remove_inward_normals = use_remove_inward_normals
        self.denoise_mix_factor = denoise_mix_factor


    def __enter__(self):

        image_node = self.input_socket.new('CompositorNodeImage', image = self.image)

        inpaint_distance = max(self.image.generated_height, self.image.generated_width)
        inpaint_distance = min(inpaint_distance, 512)

        if self.use_denoise:

            denoise_tree = bpy_data.load_compositor_node_tree('BC_C_Denoise_Normal')
            set_denoise_tree_settings(denoise_tree, inpaint_distance)

            denoise_group = image_node.outputs[0].insert_new('CompositorNodeGroup', node_tree = denoise_tree)

            image_node.outputs[1].join(denoise_group.inputs[1])  # connect Alpha

            denoise_group.inputs[3].set_default_value(self.denoise_mix_factor)

            if self.use_remove_inward_normals:
                use_remove_inward_normals = image_node.outputs[0].insert_new('CompositorNodeGroup', node_tree = bpy_data.load_compositor_node_tree('BC_C_Remove_Inward_Normal'))
                insert_normalize(use_remove_inward_normals)

        else:

            set_alpha_node = image_node.outputs[0].insert_new('CompositorNodeSetAlpha')

            math_node = image_node.outputs[1].new(bpy_node.Compositor_Node_Type.MATH, operation = 'GREATER_THAN')
            math_node.inputs[1].default_value = 0.9999
            math_node.outputs[0].join(set_alpha_node.inputs[1])

            inpaint_node = set_alpha_node.outputs[0].insert_new('CompositorNodeInpaint')

            if bpy.app.version >= (5, 0):
                inpaint_node.inputs[1].default_value = inpaint_distance
            else:
                inpaint_node.distance = inpaint_distance

            if self.use_remove_inward_normals:
                use_remove_inward_normals = set_alpha_node.outputs[0].insert_new('CompositorNodeGroup', node_tree = bpy_data.load_compositor_node_tree('BC_C_Remove_Inward_Normal'))
                insert_normalize(use_remove_inward_normals)

            insert_normalize(inpaint_node)



    def __exit__(self, type, value, traceback):
        self.tree.delete_new_nodes()


class Compositor_Input_View_Space_Normal:


    def __init__(self,
                 input_socket: typing.Union['bpy.types.NodeSocketFloat', 'bpy.types.NodeSocketColor'],
                 image: bpy.types.Image,
                 use_denoise = True,
                 use_remove_inward_normals = False,
            ):

        self.tree = bpy_node.Compositor_Tree_Wrapper.from_scene(bpy.context.scene)
        self.input_socket = self.tree.get_socket_wrapper(input_socket)
        self.image = image

        self.use_denoise = use_denoise
        self.use_remove_inward_normals = use_remove_inward_normals


    def __enter__(self):

        image_node = self.input_socket.new('CompositorNodeImage', image = self.image)

        if self.use_denoise:

            denoise_tree = bpy_data.load_compositor_node_tree('BC_C_Denoise_View_Space_Normal')
            set_denoise_tree_settings(denoise_tree, 0, prefilter='ACCURATE')

            denoise_group = image_node.outputs[0].insert_new('CompositorNodeGroup', node_tree = denoise_tree)

            image_node.outputs[1].join(denoise_group.inputs[1])  # connect Alpha

            image_node.outputs[0].join(denoise_group.inputs[2])  # connect Normal

            if self.use_remove_inward_normals:
                use_remove_inward_normals = image_node.outputs[0].insert_new('CompositorNodeGroup', node_tree = bpy_data.load_compositor_node_tree('BC_C_Remove_Inward_Normal'))
                insert_normalize(use_remove_inward_normals)

        else:

            if self.use_remove_inward_normals:
                use_remove_inward_normals = image_node.outputs[0].insert_new('CompositorNodeGroup', node_tree = bpy_data.load_compositor_node_tree('BC_C_Remove_Inward_Normal'))
                insert_normalize(use_remove_inward_normals)


    def __exit__(self, type, value, traceback):
        self.tree.delete_new_nodes()



def set_denoise_tree_settings(bl_tree: bpy.types.CompositorNodeTree, inpaint_distance: int, prefilter = 'NONE', use_hdr = False, quality = 'BALANCED'):
    """
    Deprecated compositor nodes were removed. (#140355)
    Compositor: Remove deprecated compositor properties #140355
    https://projects.blender.org/blender/blender/pulls/140355
    """

    tree = bpy_node.Compositor_Tree_Wrapper(bl_tree)

    for node in tree.get_by_bl_idname('CompositorNodeInpaint'):

        if node.label == 'DO_NOT_CHANGE':
            continue

        node.inputs[1].default_value = inpaint_distance

    for node in tree.get_by_bl_idname('CompositorNodeDenoise'):

        if node.label == 'DO_NOT_CHANGE':
            continue

        node.inputs[3].default_value = use_hdr
        node.inputs[4].default_value = prefilter.replace('_', ' ').lower().title()

        node.inputs[5].default_value = quality.replace('_', ' ').lower().title()


def set_denoise_tree_settings_pre_5_0(bl_tree: bpy.types.CompositorNodeTree, inpaint_distance: int, prefilter = 'NONE', use_hdr = False, quality = 'BALANCED'):

    tree = bpy_node.Compositor_Tree_Wrapper(bl_tree)

    for node in tree.get_by_bl_idname('CompositorNodeInpaint'):

        if node.label == 'DO_NOT_CHANGE':
            continue

        node.distance = inpaint_distance

    for node in tree.get_by_bl_idname('CompositorNodeDenoise'):

        if node.label == 'DO_NOT_CHANGE':
            continue

        node.use_hdr = use_hdr
        node.prefilter = prefilter

        node.quality = quality


if bpy.app.version < (5, 0):
    set_denoise_tree_settings = set_denoise_tree_settings_pre_5_0
