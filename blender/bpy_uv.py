from __future__ import annotations

import os
import typing
import math
import collections
import statistics
import subprocess
import time
import platform
import threading
import queue
import sys
import array
import traceback
import tempfile
import operator
import re
import itertools

import bpy
import mathutils
import bmesh

from . import bpy_context
from . import bpy_utils
from . import blend_inspector

from .. import utils
from .. import tool_settings


def ensure_uv_layer(objects: typing.List[bpy.types.Object], name: str, *, init_from: str = '', init_from_does_not_exist_ok = False):

    if not name:
        raise ValueError(f"The uv layer name cannot be empty: {[o.name_full for o in objects]}")

    # TODO: need to ensure the name is unique
    added_uvs_names = set()

    meshes: typing.List[bpy.types.Mesh] = [object.data for object in objects]
    meshes = utils.deduplicate(meshes)

    for mesh in meshes:

        if mesh.uv_layers.get(name) is not None:
            continue

        if len(mesh.uv_layers) >= 8:
            raise Exception(f"Fail to create uv layer: '{name}'. Only 8 UV maps maximum per mesh is allowed. The mesh already has the maximum: {mesh.name_full}")

        if init_from:
            if mesh.uv_layers.get(init_from):
                with bpy_context.Bpy_State() as bpy_state:
                    bpy_state.set(mesh.uv_layers, 'active', mesh.uv_layers[init_from])
                    uvs = mesh.uv_layers.new(name = name, do_init = True)
            elif init_from_does_not_exist_ok:
                uvs = mesh.uv_layers.new(name = name, do_init = False)
            else:
                raise Exception(f"The source uv layer `{init_from}` does not exist: {mesh.name_full}")
        else:
            uvs = mesh.uv_layers.new(name = name, do_init = False)

        added_uvs_names.add(uvs.name)

    if meshes and len(added_uvs_names) > 1:
        raise Exception(f"A UV map name overlap. {added_uvs_names}")

    return name


def pin_any_vertex(mesh: bpy.types.Mesh):

    # not in edit mode
    # mesh.uv_layers[uv_name].data[0].pin_uv = True
    # mesh.uv_layers[uv_name].pin[0].value = True # 3.5+

    b_mesh = bmesh.from_edit_mesh(mesh)
    uv_layer = b_mesh.loops.layers.uv.verify()

    for face in b_mesh.faces:
        for loop in face.loops:
            loop[uv_layer].pin_uv = True
            bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)
            return


def pin_largest_island(mesh: bpy.types.Mesh):

    from mathutils.geometry import area_tri

    b_mesh = bmesh.from_edit_mesh(mesh)
    uv_layer = b_mesh.loops.layers.uv.verify()

    linked_uv_islands = get_linked_uv_islands(b_mesh, uv_layer)

    face_to_uv_triangles = get_uv_triangles(b_mesh, b_mesh.loops.layers.uv.verify())

    def get_area(island):
        return sum(area_tri(*loop) for face in island for loop in face_to_uv_triangles[face])

    largest_island = sorted(linked_uv_islands, key=get_area)[-1]

    for face in largest_island:
        for loop in face.loops:
            loop[uv_layer].pin_uv = True

    bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)


def execute_uv_packer_addon(self: 'uv_packer.UVPackerPackButtonOperator', context: 'bpy.types.Context'):
    """ Make UV-Packer to execute non-modally. """

    if len(context.selected_objects) == 0:
        raise Exception("No objects are selected.")

    unique_objects = uv_packer.misc.get_unique_objects(context.selected_objects)
    meshes = uv_packer.misc.get_meshes(unique_objects)
    if len(meshes) == 0:
        raise Exception("None of the selected objects have UV data to pack.", "ERROR")

    self.timer = time.time()
    self.coverage = 0.0
    packer_props: uv_packer.UVPackProperty = context.scene.UVPackerProps

    if packer_props.uvp_create_channel:
        uv_packer.misc.set_map_name(packer_props.uvp_channel_name)
        uv_packer.misc.add_uv_channel_to_objects(unique_objects)

    options = {
        "PackMode": uv_packer.misc.resolve_engine(packer_props.uvp_engine),
        "Width": packer_props.uvp_width,
        "Height": packer_props.uvp_height,
        "Padding": packer_props.uvp_padding,
        "Rescale": packer_props.uvp_rescale,
        "PreRotate": packer_props.uvp_prerotate,
        "Rotation": int(packer_props.uvp_rotate),
        "FullRotation": packer_props.uvp_fullRotate,
        "Combine": packer_props.uvp_combine,
        "TilesX": packer_props.uvp_tilesX,
        "TilesY": packer_props.uvp_tilesY,
        "Selection": packer_props.uvp_selection_only
    }

    packerDir = "/Applications/UV-Packer-Blender.app/Contents/MacOS/"
    packerExe = "UV-Packer-Blender"
    if platform.system() == 'Windows':
        packerDir = os.path.dirname(os.path.realpath(uv_packer.__file__))
        packerExe = packerExe + ".exe"


    self.data_exchange_thread_error = None


    def data_exchange_thread():
        try:
            uv_packer.misc.data_exchange_thread(self.process, options, meshes, self.msg_queue)
        except Exception as e:
            self.process.terminate()
            self.data_exchange_thread_error = e


    messages = []

    with subprocess.Popen([packerDir + "/" + packerExe], stdin=subprocess.PIPE, stdout=subprocess.PIPE) as self.process:

        self.msg_queue = queue.SimpleQueue()

        self.packer_thread = threading.Thread(target=data_exchange_thread, daemon=True)
        self.packer_thread.start()

        def message_job():
            for message in iter(self.msg_queue.get, None):
                messages.append(message)
                if len(message) == 2 and message[0] == 1:
                    print(round(message[1] * 100, 3), "%")
                else:
                    print(message)

        message_thread = threading.Thread(target=message_job, daemon=True)
        message_thread.start()

        self.process.wait()

        if self.data_exchange_thread_error is not None:
            raise self.data_exchange_thread_error

        self.packer_thread.join()
        self.msg_queue.put_nowait(None)
        message_thread.join()

        for message in messages:

            if len(message) == 3 and message[2] == 2:
                raise Exception(message[1])

            if len(message) == 2 and message[0] == 2:
                self.coverage = message[1]

        print(f"{self.coverage}% ¦ {round(time.time() - self.timer, 2)}s")

    return {"FINISHED"}


def import_uv_packer_addon():

    uv_packer_path = r'D:\source\software\blender\scripts\addons\UV_Packer\__init__.py'
    if os.path.exists(uv_packer_path):
        return utils.import_module_from_file(uv_packer_path)

    # UV-Packer

    raise NotImplementedError('Here goes the usual import.')


def enable_uv_packer_addon():
    """ https://github.com/3d-io/uvpacker-blender-addon """

    if hasattr(bpy.types.Scene, 'UVPackerProps'):
        return True

    try:
        global uv_packer

        if typing.TYPE_CHECKING:
            # the addon was renamed to accommodate type checking
            import UV_Packer as uv_packer
        else:
            uv_packer = import_uv_packer_addon()

        uv_packer.register()
        uv_packer.UVPackerPackButtonOperator.execute = execute_uv_packer_addon
    except ImportError as e:
        print(e)
        return False
    else:
        return True


def get_island_margin(meshes: typing.Iterable[bpy.types.Mesh], settings: tool_settings.Pack_UVs):
    """
    For the `ADD` margin method. The UV islands should already exist in the meshes.

    blender-v2.93-release
    ED_uvedit_pack_islands_multi
    https://github.com/blender/blender/blob/cb886aba06d562ee629f2ee64f3692d008c68a35/source/blender/editors/uvedit/uvedit_islands.c#L447

    blender-v3.6-release
    calc_margin_from_aabb_length_sum
    https://github.com/blender/blender/blob/2c4589ca82eedede99cc060cdae27a1fa2fabb64/source/blender/geometry/intern/uv_pack.cc#L2014

    UV: unwrap. Margin size is not related to any useful measure #90782
    https://projects.blender.org/blender/blender/issues/90782
    """

    aabb_length_sum = 0

    for mesh in meshes:


        b_mesh = bmesh.from_edit_mesh(mesh)
        uv_layer = b_mesh.loops.layers.uv.verify()


        # non edit mode
        # https://docs.blender.org/api/2.83/bpy_extras.mesh_utils.html#bpy_extras.mesh_utils.mesh_linked_uv_islands
        linked_uv_islands = get_linked_uv_islands(b_mesh, uv_layer)

        for island in linked_uv_islands:
            xs, ys = zip(*(bm_loop[uv_layer].uv for face in island for bm_loop in face.loops))
            aabb_length_sum += math.sqrt((max(xs) - min(xs)) * (max(ys) - min(ys)))


    if aabb_length_sum == 0:
        return 0

    return settings._uv_island_margin_fraction / (aabb_length_sum * 0.1)


def mark_seams_from_islands(object: bpy.types.Object, uv_layer_name: typing.Optional[str] = None):

    with bpy_context.Focus_Objects(object, 'EDIT'), bpy_context.Bpy_State() as bpy_state:

        if uv_layer_name is not None:
            bpy_state.set(object.data.uv_layers, 'active', object.data.uv_layers[uv_layer_name])

        bpy.ops.mesh.reveal()
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.uv.reveal()
        bpy.ops.uv.select_all(action='SELECT')
        bpy.ops.uv.mark_seam(clear=True)
        bpy.ops.uv.seams_from_islands()


def get_object_copy_for_uv_unwrap(object: bpy.types.Object):

    with bpy_context.Focus_Objects(object):

        object_copy = object.copy()
        object_copy.data = object.data.copy()

        object_copy.rotation_mode = 'XYZ'
        object_copy.location = (0,0,0)

        object_copy.rotation_euler = (0,0,0)
        object_copy.delta_location = (0,0,0)
        object_copy.delta_rotation_euler = (0,0,0)

        bpy_utils.apply_modifiers([object_copy], include_name='Smooth by Angle', ignore_type=bpy_context.TOPOLOGY_CHANGING_MODIFIER_TYPES)

        object_copy.modifiers.clear()

        if object_copy.data.shape_keys:
            for key_block in reversed(object_copy.data.shape_keys.key_blocks):
                object_copy.shape_key_remove(key_block)

        bpy_context.call_for_object(object_copy, bpy.ops.object.transform_apply, location=False, rotation=False, scale=True)

    return object_copy


def unwrap_ministry_of_flat(object: bpy.types.Object, temp_dir: os.PathLike, settings: tool_settings.Ministry_Of_Flat, uv_layer_name: typing.Optional[str] = None):
    """ Currently operates on per mesh basis, so it is not possible to unwrap only a part of `bpy.types.Mesh`. """
    print(unwrap_ministry_of_flat.__name__, object.name_full)


    if object.type != 'MESH':
        raise Exception(f"Object is not of MESH type: {object.name_full}")


    if blend_inspector.has_identifier(blend_inspector.COMMON.SKIP_UV_ALL, blend_inspector.COMMON.SKIP_UV_UNWRAP):
        raise utils.Fallback('UV unwrapping is skipped!')


    def print_output(capture_stdout, capture_stderr, stderr_color = utils.get_color_code(255, 94, 14, 0,0,0)):
        for line in capture_stdout.lines.queue:
            print(line, end='')
        print()
        for line in capture_stderr.lines.queue:
            utils.print_in_color(stderr_color, line, end='')


    magenta_color = utils.get_color_code(255,128,255, 0,0,0)
    yellow_color = utils.get_color_code(219, 185, 61, 0,0,0)


    with bpy_context.Focus_Objects(object), bpy_context.Bpy_State() as bpy_state:

        object_copy = get_object_copy_for_uv_unwrap(object)
        object_copy.name = "EXPORT_" + object_copy.name

        with bpy_context.Focus_Objects(object_copy):


            with bpy_context.Focus_Objects(object_copy, 'EDIT'):

                bpy.ops.mesh.reveal()
                bpy.ops.mesh.select_all(action='SELECT')

                bpy_state.set(bpy.context.scene.tool_settings, 'transform_pivot_point', 'BOUNDING_BOX_CENTER')
                bpy_context.call_in_view3d(bpy.ops.transform.resize, value=(1/0.1, 1/0.1, 1/0.1), mirror=False, use_proportional_edit=False, snap=False)

                bpy_state.set(bpy.context.scene.tool_settings, 'transform_pivot_point', 'INDIVIDUAL_ORIGINS')
                bpy_context.call_in_view3d(bpy.ops.transform.resize, value=(0.1, 0.1, 0.1), mirror=False, use_proportional_edit=False, snap=False)


            filepath_input = utils.ensure_unique_path(os.path.join(temp_dir, utils.ensure_valid_basename(object.name_full + '.obj')))
            filepath_output = utils.ensure_unique_path(os.path.join(temp_dir, utils.ensure_valid_basename(object.name_full + '_unwrapped.obj')))

            print('\tobj_export ', end='')
            with utils.Capture_Stdout() as capture_stdout, utils.Capture_Stderr() as capture_stderr:
                try:
                    try:
                        bpy.ops.wm.obj_export(filepath=filepath_input, export_selected_objects=True, export_materials=False, export_uv=False, apply_modifiers=False)
                    except AttributeError:
                        bpy.ops.export_scene.obj(filepath=filepath_input, use_selection=True, use_materials=False, use_uvs=False, use_mesh_modifiers=False)
                except Exception as e:
                    print_output(capture_stdout, capture_stderr)
                    bpy.data.objects.remove(object_copy)
                    raise utils.Fallback('Fail to export obj.') from e


        cmd = settings._get_cmd(filepath_input, filepath_output)

        print('subprocess ', end='')
        try:
            process = subprocess.run(cmd, timeout=settings.timeout, text = True, capture_output=True, encoding='utf-8')
        except subprocess.TimeoutExpired as e:
            bpy.data.objects.remove(object_copy)
            raise utils.Fallback(f"Timeout: {object.name_full}") from e

        returncode = process.returncode

        if returncode == 1:
            pass
        elif returncode == 3221225786:
            bpy.data.objects.remove(object_copy)
            raise KeyboardInterrupt(f"STATUS_CONTROL_C_EXIT: {object.name_full}")
        elif returncode == 3221225477:
            bpy.data.objects.remove(object_copy)
            raise utils.Fallback(f"0xc0000005 Access Violation Error: {object.name_full}")
        else:
            print()
            utils.print_in_color(utils.get_color_code(0,0,0, 256,256,256), 'CMD:', utils.get_command_from_list(cmd))
            utils.print_in_color(yellow_color, process.stdout)
            utils.print_in_color(magenta_color, process.stderr)
            bpy.data.objects.remove(object_copy)
            raise utils.Fallback(f"Bad return code {returncode}: {object.name_full}")

        if not os.path.exists(filepath_output):
            bpy.data.objects.remove(object_copy)
            raise utils.Fallback(f"Output .obj file does not exist: {filepath_output}")

        bpy.ops.object.select_all(action='DESELECT')

        print('obj_import ', end='')
        with utils.Capture_Stdout() as capture_stdout, utils.Capture_Stderr() as capture_stderr:
            try:
                try:
                    bpy.ops.wm.obj_import(filepath=filepath_output, validate_meshes = True)
                except AttributeError:
                    bpy.ops.import_scene.obj(filepath=filepath_output)
            except Exception as e:
                print_output(capture_stdout, capture_stderr)
                bpy.data.objects.remove(object_copy)
                raise utils.Fallback('Fail to import obj.') from e


        imported_object = bpy.context.selected_objects[0]
        imported_object.name = "IMPORT_" + imported_object.name

        print('validate')
        with utils.Capture_Stdout() as capture_stdout:
            is_invalid_geometry = imported_object.data.validate(verbose=True)

        validation_lines: typing.List[str] = list(capture_stdout.lines.queue)

        if is_invalid_geometry:
            bpy.data.objects.remove(object_copy)
            bpy.data.objects.remove(imported_object)
            raise utils.Fallback('\n'.join(validation_lines))

        was_re_unwrapped = False

        for line in validation_lines:

            # CustomDataLayer type 49 has some invalid data
            if 'CustomDataLayer' in line and 'invalid data' in line:
                if was_re_unwrapped:
                    continue

                # TODO: it is better to find all verts that have (0,0) coords after the validation correction
                # pin all the rest and unwrap so the invalid uvs will take a better place

                # this really solves only bad overlapping, which ministry_of_flat does not produce

                utils.print_in_color(magenta_color, 'Failed validation. Re-unwrapping overlaps.')
                bpy.ops.object.editmode_toggle()
                bpy.ops.mesh.reveal()
                bpy.ops.uv.reveal()
                bpy.ops.mesh.select_all(action='SELECT')
                bpy.ops.uv.select_all(action='SELECT')
                aabb_pack(margin=0.1, merge_overlap=False)
                bpy.ops.uv.select_all(action='DESELECT')
                bpy.ops.uv.select_overlap()

                bpy_context.call_in_uv_editor(bpy.ops.uv.select_linked)
                bpy_context.call_in_uv_editor(bpy.ops.uv.unwrap, can_be_canceled = True)

                bpy.ops.uv.reveal()
                bpy.ops.object.editmode_toggle()

                was_re_unwrapped = True
            elif line.strip():
                bpy.data.objects.remove(imported_object)
                raise utils.Fallback(line)

        bpy_utils.focus(object)

        if not object.data.uv_layers:
            object.data.uv_layers.new(do_init=False)

        if uv_layer_name is None:
            uv_layer_name = object.data.uv_layers.active.name

        imported_object.data.uv_layers[0].name = uv_layer_name


        def apply_modifier(modifier: bpy.types.Modifier):
            object = modifier.id_data
            print(modifier.name + "...")
            bpy_context.call_for_object(object, bpy.ops.object.modifier_apply, modifier = modifier.name, single_user = True)


        def apply_uv_data_transfer_modifier(from_object: bpy.types.Object, to_object: bpy.types.Object, uv_layer_name: str):

            modifier: bpy.types.DataTransferModifier = to_object.modifiers.new('', type='DATA_TRANSFER')

            modifier.object = from_object
            modifier.use_loop_data = True
            modifier.data_types_loops = {'UV'}
            modifier.loop_mapping = 'NEAREST_POLYNOR'
            modifier.layers_uv_select_src = uv_layer_name
            modifier.show_expanded = False

            apply_modifier(modifier)

        try:
            copy_uv(imported_object, object, uv_layer_name)
        except ValueError:
            traceback.print_exc(file = sys.stderr)

            with bpy_context.Focus_Objects([imported_object, object_copy, object]):
                apply_uv_data_transfer_modifier(imported_object, object_copy, uv_layer_name)

                # loops that are failed to be transferred create overlaps
                re_unwrap_overlaps(object_copy, uv_layer_name)

                copy_uv(object_copy, object, uv_layer_name)
        finally:
            bpy.data.objects.remove(object_copy)
            bpy.data.objects.remove(imported_object)


def re_unwrap_overlaps(object: bpy.types.Object, uv_layer_name: str):

    with bpy_context.Focus_Objects(object, mode='EDIT'):
        object.data.uv_layers.active = object.data.uv_layers[uv_layer_name]

        bpy.ops.mesh.reveal()
        bpy.ops.uv.reveal()
        bpy_context.call_in_uv_editor(bpy.ops.uv.select_mode, type='VERTEX', can_be_canceled=True)
        bpy.ops.mesh.select_all(action='SELECT')

        bpy.ops.uv.select_all(action='SELECT')
        aabb_pack(margin=0.05, merge_overlap=False)
        bpy.ops.uv.select_all(action='DESELECT')

        if select_collapsed_islands(object, uv_layer_name):
            bpy.ops.uv.hide(unselected=False)  # hiding to save time on select_overlap
        bpy.ops.uv.select_all(action='DESELECT')

        print('bpy.ops.uv.select_overlap...', '[ can be long for badly overlapped uvs ]')
        bpy.ops.uv.select_overlap()

        bpy.ops.uv.reveal(select=True)

        bpy.ops.uv.select_all(action='INVERT')
        bpy.ops.uv.pin(clear=False)
        bpy.ops.uv.select_all(action='INVERT')
        bpy_context.call_in_uv_editor(bpy.ops.uv.unwrap, method='MINIMUM_STRETCH', fill_holes=True, no_flip=True, can_be_canceled=True, iterations=30)

        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.uv.select_all(action='SELECT')
        bpy.ops.uv.pin(clear=True)



def get_uv_triangles(b_mesh: bmesh.types.BMesh, uv_layer):

    face_to_uv_triangles: typing.Dict[bmesh.types.BMFace, typing.List[typing.Tuple[mathutils.Vector, mathutils.Vector, mathutils.Vector]]]
    face_to_uv_triangles = collections.defaultdict(list)

    for triangle_loops in b_mesh.calc_loop_triangles():
        # assert triangle_loops[0].face is triangle_loops[1].face and triangle_loops[0].face is triangle_loops[2].face
        face_to_uv_triangles[triangle_loops[0].face].append(tuple(loop[uv_layer].uv for loop in triangle_loops))

    return face_to_uv_triangles


def scale_uv_to_world_per_uv_island(objects: typing.List[bpy.types.Object], uv_layer_name: str = '', use_selected = False, divide_by_mean = True):
    """ Works on the active uv layer. """
    print(f"{scale_uv_to_world_per_uv_island.__name__}...")

    from mathutils.geometry import area_tri

    # https://github.com/blender/blender/blob/9d7bb542a88bffcd8ad1e7a9e7d61cc467c5fbf3/source/blender/geometry/intern/uv_parametrizer.cc#L4238

    for object in objects:

        # TODO: try to rewrite to not toggle on and off the edit mode
        # currently it is needed for bpy.ops.uv.unwrap to not unwrap other objects
        # https://docs.blender.org/api/current/mathutils.html#mathutils.Matrix.lerp
        with bpy_context.Focus_Objects(object, mode='EDIT'):

            bm = bmesh.from_edit_mesh(object.data)

            bm_copy = bm.copy()
            bm_copy.transform(object.matrix_world)

            bm_copy.faces.ensure_lookup_table()

            if uv_layer_name:
                uv_layer = bm.loops.layers.uv[uv_layer_name]
            else:
                uv_layer = bm.loops.layers.uv.verify()

            islands = get_linked_uv_islands(bm, uv_layer)
            if use_selected:
                islands = list(filter(None, [[face for face in island if face.select] for island in islands]))

            if not islands:
                continue

            face_to_uv_triangles = get_uv_triangles(bm, uv_layer)

            multipliers = []

            for island in islands:

                island_mesh_area = sum(bm_copy.faces[face.index].calc_area() for face in island)

                island_uv_area = sum(area_tri(*loop) for face in island for loop in face_to_uv_triangles[face])

                # #79775 - Something in Blender can generate invalid (Nan) values in UVMaps
                # https://projects.blender.org/blender/blender/issues/79775
                if math.isnan(island_uv_area):
                    island_uv_area = sum(area_tri(*loop) for face in island for loop in face_to_uv_triangles[face] if all(not map(math.isnan, vert) for vert in loop))

                try:
                    scale_multiplier = math.sqrt(island_mesh_area/island_uv_area)
                except ZeroDivisionError:
                    scale_multiplier = 0

                multipliers.append(scale_multiplier)


            mean = statistics.harmonic_mean([n for n in multipliers if n > 0])


            for scale_multiplier, island in zip(multipliers, islands):

                if scale_multiplier == 0:
                    scale_multiplier = mean

                island_vertices = [loop[uv_layer].uv for face in island for loop in face.loops]
                island_center = sum(island_vertices, mathutils.Vector((0,0)))/len(island_vertices)

                if not divide_by_mean:
                    mean = 1

                for face in island:
                    for loop in face.loops:
                        uv_loop = loop[uv_layer]
                        uv_loop.uv = (uv_loop.uv - island_center) * scale_multiplier / mean + island_center

            bpy.ops.ed.flush_edits()
            bmesh.update_edit_mesh(object.data, loop_triangles=False, destructive=False)

            bm_copy.free()


def scale_uv_to_world_per_uv_layout(objects: typing.List[bpy.types.Object], uv_layer_name = ''):
    """ Works on the active uv layer. """
    print(f"{scale_uv_to_world_per_uv_layout.__name__}...")

    from mathutils.geometry import area_tri

    objects = bpy_utils.get_unique_data_objects(objects)

    with bpy_context.Focus_Objects(objects, mode='EDIT'):

        for object in objects:

            bm = bmesh.from_edit_mesh(object.data)

            bm_copy = bm.copy()
            bm_copy.transform(object.matrix_world)

            if uv_layer_name:
                bm_copy_uv_layout = bm_copy.loops.layers.uv[uv_layer_name]
            else:
                bm_copy_uv_layout = bm_copy.loops.layers.uv.verify()

            bm_copy.faces.ensure_lookup_table()
            face_to_uv_triangles = get_uv_triangles(bm_copy, bm_copy_uv_layout)

            ratios = []

            for face in bm_copy.faces:

                face_area = face.calc_area()

                face_area_uv = sum(area_tri(*loop) for loop in face_to_uv_triangles[face])
                if math.isnan(face_area_uv):
                    continue

                if face_area == 0 or face_area_uv == 0:
                    continue

                ratios.append(face_area/face_area_uv)

            if not ratios:
                continue

            multiplier = math.sqrt(statistics.median(ratios))

            if uv_layer_name:
                uv_layer = bm.loops.layers.uv[uv_layer_name]
            else:
                uv_layer = bm.loops.layers.uv.verify()

            islands = get_linked_uv_islands(bm, uv_layer)
            for island in islands:

                island_vertices = [loop[uv_layer].uv for face in island for loop in face.loops]
                island_center = sum(island_vertices, mathutils.Vector((0,0)))/len(island_vertices)

                for face in island:
                    for loop in face.loops:
                        uv_loop = loop[uv_layer]
                        uv_loop.uv = (uv_loop.uv - island_center) * multiplier + island_center

            bmesh.update_edit_mesh(object.data, loop_triangles=False, destructive=False)

            bm_copy.free()



def scale_uv_islands_by_weight_group(object: bpy.types.Object, uv_layer_name: str, weight_group_name: str, factor = 1.0):
    print(f"{scale_uv_islands_by_weight_group.__name__}...")

    with bpy_context.Focus_Objects(object, mode='EDIT'):

        bm = bmesh.from_edit_mesh(object.data)

        deform_layer = bm.verts.layers.deform.verify()
        group_index = object.vertex_groups[weight_group_name].index

        uv_layer = bm.loops.layers.uv.get(uv_layer_name)
        islands = get_linked_uv_islands(bm, uv_layer)
        for island in islands:

            all_verts: typing.Set[bmesh.types.BMVert] = set()
            for face in island:
                all_verts.update(face.verts)

            average_weight = sum(vert[deform_layer].get(group_index, 0) for vert in all_verts)/len(all_verts)

            average_weight = average_weight * (1.0 - factor) + factor

            island_vertices = [loop[uv_layer].uv for face in island for loop in face.loops]
            island_center = sum(island_vertices, mathutils.Vector((0,0)))/len(island_vertices)

            for face in island:
                for loop in face.loops:
                    uv_loop = loop[uv_layer]
                    uv_loop.uv = (uv_loop.uv - island_center) * average_weight + island_center

        bmesh.update_edit_mesh(object.data, loop_triangles=False, destructive=False)


def aabb_pack(margin = 0.001, merge_overlap = False):
    """ Used for pre-packing. """

    if 'margin_method' in repr(bpy.ops.uv.pack_islands):
        bpy.ops.uv.pack_islands(
            margin_method = 'ADD',
            merge_overlap = merge_overlap,
            shape_method = 'AABB',
            rotate=False,
            margin = margin
            )
    else:
        bpy.ops.uv.pack_islands(margin = margin)


def uv_packer_pack(
        uvp_width: int,
        uvp_height: int,
        uvp_padding: int,
        uvp_prerotate: bool,
        uvp_rescale = False,
        use_high_quality_engine = True
    ):

    uv_packer_props: uv_packer.UVPackProperty = bpy.context.scene.UVPackerProps

    uv_packer_props.uvp_fullRotate = False
    uv_packer_props.uvp_rotate = '1'

    if use_high_quality_engine:
        uv_packer_props.uvp_engine = 'OP1'  # HQ
    else:
        uv_packer_props.uvp_engine = 'OP0'  # Efficient

    uv_packer_props.uvp_width = uvp_width
    uv_packer_props.uvp_height = uvp_height
    uv_packer_props.uvp_padding = uvp_padding

    uv_packer_props.uvp_selection_only = True
    uv_packer_props.uvp_combine = True

    uv_packer_props.uvp_prerotate = uvp_prerotate
    uv_packer_props.uvp_rescale = uvp_rescale

    bpy.ops.ed.flush_edits()
    # Exception: Input data validation for object InvisibleCollisions Cylinder failed, packing not possible: There are not enough vertices for provided geoIndex 427.


    # bpy.ops.uvpackeroperator.packbtn()

    class Dummy():
        pass

    class Dummy_Context():
        selected_objects = bpy.context.selected_objects
        scene = bpy.context.scene

    for _object in bpy.context.selected_objects:
        assert  _object.mode == 'EDIT', _object

    execute_uv_packer_addon(Dummy(), Dummy_Context())


def pack(objects: typing.List[bpy.types.Object], settings: typing.Optional[tool_settings.Pack_UVs] = None) -> str:
    """ Assumes the objects are selected and in the object mode. """

    settings =  tool_settings.Pack_UVs()._update(settings)

    print('pack_uvs...')

    objects = bpy_utils.get_unique_mesh_objects(objects)

    if not objects:
        print("No valid objects to pack: ", [o.name_full for o in objects])
        return

    with bpy_context.Focus_Objects(objects, mode='EDIT'), bpy_context.Bpy_State() as bpy_state:

        bpy_state.set(bpy.context.scene.tool_settings, 'use_uv_select_sync', False)

        for object in objects:
            bpy_state.set(object.data.uv_layers, 'active', object.data.uv_layers[settings.uv_layer_name])


        bpy.ops.mesh.reveal()
        bpy.ops.uv.reveal()

        if settings.material_key:

            any_material_selected = False

            bpy.ops.uv.select_all(action='DESELECT')
            bpy.ops.mesh.select_all(action='DESELECT')

            for object in objects:

                bpy_state.set(object, 'active_material_index', 0)

                for material_index in range(len(object.material_slots)):

                    object.active_material_index = material_index
                    if not object.active_material.get(settings.material_key):
                        continue

                    result = bpy_context.call_for_object(object, bpy.ops.object.material_slot_select, can_be_canceled = True)
                    any_material_selected = 'CANCELLED' not in result  # can be canceled if the material slot is not assigned to any polygon


            if not any_material_selected:
                utils.print_in_color(utils.get_color_code(255, 219, 187, 0,0,0), f"Objects do not use materials with key:\n\tobjects = {', '.join([o.name_full for o in objects])}\n\tmaterial_key = {settings.material_key}")
                return

            bpy.ops.uv.select_all(action='SELECT')
        else:
            bpy.ops.mesh.select_all(action='SELECT')
            bpy.ops.uv.select_all(action='SELECT')


        if settings.average_uv_scale:
            scale_uv_to_world_per_uv_island(objects)


        bpy.ops.uv.pin(clear=True)


        for object in objects:
            # prevent the material to act as a source of the uv aspect ratio
            # ED_uvedit_get_aspect
            # https://github.com/blender/blender/blob/6329ac2f7ddee0fc203f9dc90dca07d4cc048e7e/source/blender/editors/uvedit/uvedit_unwrap_ops.cc#L270C6-L270C40
            # can also crate an empty or procedural texture in the material and make active
            for material_slot in object.material_slots:
                bpy_state.set(material_slot, 'material', None)


        print('Pre-packing UV islands...')

        if blend_inspector.has_identifier(blend_inspector.COMMON.SKIP_UV_ALL, blend_inspector.COMMON.SKIP_UV_PACK):
            pass
        elif settings.use_uv_packer_addon and settings.use_uv_packer_for_pre_packing and enable_uv_packer_addon():
            uv_packer_pack(settings._actual_width, settings._actual_height, settings.padding, settings.uvp_prerotate, settings.uvp_rescale, use_high_quality_engine=False)
        else:
            aabb_pack(merge_overlap=settings.merge_overlap)


        print('Packing UV islands...')

        if blend_inspector.has_identifier(blend_inspector.COMMON.SKIP_UV_ALL, blend_inspector.COMMON.SKIP_UV_PACK):
            aabb_pack(merge_overlap=settings.merge_overlap)

        elif settings.use_uv_packer_addon and enable_uv_packer_addon():

            if settings.uv_packer_addon_pin_largest_island:
                pin_largest_island(bpy.context.object.data)

            uv_packer_pack(settings._actual_width, settings._actual_height, settings.padding, settings.uvp_prerotate, settings.uvp_rescale)

            if settings.uv_packer_addon_pin_largest_island:
                bpy.ops.uv.pin(clear=True)

        else:

            if 'margin_method' in repr(bpy.ops.uv.pack_islands):
                bpy.ops.uv.pack_islands(
                    margin = settings._uv_island_margin_fraction,
                    margin_method = 'FRACTION',
                    merge_overlap = settings.merge_overlap,

                    rotate=True,
                    rotate_method='CARDINAL',
                    )
            else:
                margin = get_island_margin(bpy_utils.get_unique_meshes(objects), settings)
                bpy.ops.uv.pack_islands(margin = margin)

        scale_uv_to_bounds(objects, settings._uv_island_margin_fraction)

        blend_inspector.inspect_if_has_identifier(blend_inspector.COMMON.INSPECT_UV_PACK)


def get_linked_uv_islands(mesh: bmesh.types.BMesh, uv_layer: bmesh.types.BMLayerItem):

    result: typing.List[typing.List[bmesh.types.BMFace]] = []
    processed = set()

    for init_face in mesh.faces:

        if init_face in processed:
            continue

        processed.add(init_face)
        island = [init_face]
        pool = [init_face]

        while pool:
            current_face = pool.pop()

            for loop in current_face.loops:

                vert = loop.vert
                uv = loop[uv_layer].uv

                for face in vert.link_faces:

                    if face is current_face or face in processed:
                        continue

                    if not any(loop.vert == vert and uv == loop[uv_layer].uv for loop in face.loops):
                        continue

                    processed.add(face)
                    island.append(face)
                    pool.append(face)

        result.append(island)

    return result


def get_spiral_shifts(n = 6):

    coord = [0,0]
    coords = [tuple(coord)]

    for k in range(1, n):

        shift = -1 if k % 2 else 1

        for _ in range(k):
            coord[0] -= shift
            coords.append(tuple(coord))

        for _ in range(k):
            coord[1] += shift
            coords.append(tuple(coord))

    return coords


def _ensure_pixel_per_island(objects: typing.List[bpy.types.Object], res_x: int, res_y: int, SPIRAL_SHIFTS = get_spiral_shifts()):
    """
    Baking pixel-perfect maps is extremely inaccurate #74823
    https://projects.blender.org/blender/blender/issues/74823

    Operates in the mesh edit mode.
    """

    ZERO_VECTOR = mathutils.Vector((0,0))

    taken_pixels = set()

    pixel_step_x = 1/res_x
    pixel_step_y = 1/res_y

    center_offset_x = pixel_step_x / 2
    center_offset_y = pixel_step_y / 2

    min_pixel_size = min(pixel_step_x, pixel_step_y)

    from math import floor
    from mathutils import Vector
    from mathutils.geometry import intersect_point_tri_2d
    from mathutils.geometry import area_tri


    def get_incenter(a: Vector, b: Vector, c: Vector):
        ab = (a - b).length
        bc = (b - c).length
        ca = (c - a).length
        abc = ab + bc + ca
        if abc == 0:
            return a
        else:
            return Vector(((ab * a.x + bc * b.x + ca * c.x) / abc, (ab * a.y + bc * b.y + ca * c.y) / abc))


    def get_closest_pixel_center(point):
        return Vector((
            ((floor(point[0] * res_x)/res_x) + center_offset_x) % 1,
            ((floor(point[1] * res_y)/res_y) + center_offset_y) % 1
        ))


    def has_pixels(island):
        for face in island:
            for uv_triangle in face_to_uv_triangles[face]:

                try:
                    pixel_center = get_closest_pixel_center(sum(uv_triangle, ZERO_VECTOR)/len(uv_triangle))
                except ValueError as e:  #ValueError: cannot convert float NaN to integer
                    print(e)
                    return False

                incenter = get_incenter(*uv_triangle)

                if intersect_point_tri_2d(pixel_center, *((uv - incenter) * 0.9 + incenter for uv in uv_triangle)):
                    return True

        return False


    for object in objects:

        if object.mode != 'EDIT':
            continue

        data = object.data
        if not isinstance(data, bpy.types.Mesh):
            continue

        b_mesh = bmesh.from_edit_mesh(data)

        uv_layer = b_mesh.loops.layers.uv.verify()

        face_to_uv_triangles = get_uv_triangles(b_mesh, uv_layer)

        linked_uv_islands = get_linked_uv_islands(b_mesh, uv_layer)

        islands_without_pixels = [island for island in linked_uv_islands if not has_pixels(island)]

        for island in islands_without_pixels:

            # select_island(island, uv_layer)

            ## by central uv triangle
            island_uvs: typing.List[Vector] = []
            uv_triangles_centers: typing.List[Vector] = []

            for face in island:
                for uv_triangle in face_to_uv_triangles[face]:
                    uv_triangles_centers.append(sum(uv_triangle, ZERO_VECTOR)/len(uv_triangle))
                    island_uvs.extend(uv_triangle)

            island_vertex_center = sum(island_uvs, ZERO_VECTOR)/len(island_uvs)
            island_center = min(uv_triangles_centers, key = lambda point: (island_vertex_center - point).length_squared)

            ## by biggest triangle
            # biggest_triangle = max((uv_triangle for face in island for uv_triangle in face_to_uv_triangles[face]), key=lambda x: area_tri(*x))
            # island_center = sum(biggest_triangle, ZERO_VECTOR)/len(biggest_triangle)


            try:
                init_pixel_center = get_closest_pixel_center(island_center)
            except ValueError as e:  #ValueError: cannot convert float NaN to integer
                print(e)
                continue

            for shift in SPIRAL_SHIFTS:

                x = init_pixel_center[0] + shift[0] * pixel_step_x
                y = init_pixel_center[1] + shift[1] * pixel_step_y

                pixel_center = Vector((x % 1, y % 1)).freeze()

                if not pixel_center in taken_pixels:
                    break

            taken_pixels.add(pixel_center)

            for face in island:
                for loop in face.loops:
                    loop[uv_layer].uv += pixel_center - island_center

        bmesh.update_edit_mesh(data, loop_triangles=False, destructive=False)


def ensure_pixel_per_island(objects: typing.List[bpy.types.Object], settings: tool_settings.Pack_UVs):
    print('ensure_pixel_per_island...')

    objects = bpy_utils.get_unique_mesh_objects(objects)

    with bpy_context.Focus_Objects(objects, mode='EDIT'), bpy_context.Bpy_State() as bpy_state:

        for object in objects:

            mesh: bpy.types.Mesh = object.data

            bpy_state.set(mesh.uv_layers, 'active', mesh.uv_layers[settings.uv_layer_name])

        _ensure_pixel_per_island(objects, settings._actual_width, settings._actual_height)




def clear_uv_layers(mesh: bpy.types.Mesh, uv_layer_name_to_remain: str, unified_name: typing.Optional[str] = None):

    uv_layers_to_delete = [uv_layer.name for uv_layer in mesh.uv_layers if not uv_layer.name == uv_layer_name_to_remain]

    for name in uv_layers_to_delete:
        mesh.uv_layers.remove(mesh.uv_layers[name])

    name = mesh.uv_layers[uv_layer_name_to_remain].name
    if unified_name:
        mesh.uv_layers[uv_layer_name_to_remain].name = unified_name
        name = unified_name

    return name


def clear_uv_layers_from_objects(objects: typing.List[bpy.types.Object], uv_layer_name_to_remain: str, unified_name: typing.Optional[str] = None):
    meshes: typing.List[bpy.types.Mesh] = [object.data for object in objects]
    meshes = utils.deduplicate(meshes)

    for mesh in meshes:
        clear_uv_layers(mesh, uv_layer_name_to_remain, unified_name)



def unwrap(objects: typing.List[bpy.types.Object], *,
           uv_layer = tool_settings.DEFAULT_UV_LAYER_NAME,
           uv_layer_reuse = '',
           settings: typing.Optional[tool_settings.Unwrap_UVs] = None,
           ministry_of_flat_settings: typing.Optional[tool_settings.Ministry_Of_Flat] = None
        ):

    incompatible_objects = set(objects) - set(object for object in objects if object.data and hasattr(object.data, 'uv_layers'))
    if incompatible_objects:
        raise ValueError(f"Specified objects cannot be unwrapped: {[o.name_full for o in objects]}\nIncompatible: {[o.name_full for o in incompatible_objects]}")


    objects = bpy_utils.get_unique_mesh_objects(objects)

    settings = tool_settings.Unwrap_UVs(uv_layer_name = uv_layer)._update(settings)


    ensure_uv_layer(objects, settings.uv_layer_name, init_from = uv_layer_reuse, init_from_does_not_exist_ok=True)


    with bpy_context.Bpy_State() as bpy_state, bpy_context.Global_Optimizations():

        for object in bpy_utils.get_view_layer_objects():
            if object.animation_data:
                for driver in object.animation_data.drivers:
                    bpy_state.set(driver, 'mute', True)

                for nla_track in object.animation_data.nla_tracks:
                    bpy_state.set(nla_track, 'mute', True)

        for object in bpy_utils.get_view_layer_objects():
            for modifier in object.modifiers:
                bpy_state.set(modifier, 'show_viewport', False)

        for object in objects:
            bpy_state.set(object.data.uv_layers, 'active', object.data.uv_layers[settings.uv_layer_name])

        with bpy_context.Empty_Scene():
            unwrap_with_fallback(objects, settings, ministry_of_flat_settings)

        scale_uv_to_world_per_uv_layout(objects)


def get_stdev_mean(values: typing.Union[typing.Sized, typing.Iterable]):

    mean = statistics.mean(values)

    if len(values) == 1:
        return mean
    else:
        stdev = statistics.stdev(values, mean)

        minimum = mean - 3 * stdev
        maximum = mean + 3 * stdev

        return statistics.mean(multiplier for multiplier in values if multiplier <= maximum and multiplier >= minimum)


@blend_inspector.skipable(blend_inspector.COMMON.SKIP_UV_ALL, blend_inspector.COMMON.SKIP_UV_UNWRAP)
def reunwrap_bad_uvs(objects: typing.List[bpy.types.Object], only_select = False, divide_by_mean = True):
    print(f"{reunwrap_bad_uvs.__name__}...")


    from mathutils.geometry import area_tri


    def get_bound_box_ratio(island: typing.List[bmesh.types.BMFace]):
        xs, ys = zip(*(bm_loop[uv_layer].uv for face in island for bm_loop in face.loops))
        return ( abs(max(xs) - min(xs)) ) / ( abs(max(ys) - min(ys)) )


    all_bound_box_ratios: typing.List[float] = []

    with bpy_context.Focus_Objects(objects, mode='EDIT'):

        for object in objects:

            bpy.ops.mesh.reveal()
            bpy.ops.uv.reveal()
            bpy.ops.uv.select_all(action='SELECT')
            bpy.ops.uv.align_rotation()

            bm = bmesh.from_edit_mesh(object.data)

            uv_layer = bm.loops.layers.uv.verify()

            for island in get_linked_uv_islands(bm, uv_layer):

                try:
                    bound_box_ratio = get_bound_box_ratio(island)
                    if bound_box_ratio < 1:
                        bound_box_ratio = 1 / bound_box_ratio
                except ZeroDivisionError:
                   continue

                all_bound_box_ratios.append(bound_box_ratio)

    maximum_bound_box_ratio = pow(statistics.harmonic_mean(all_bound_box_ratios), 3)


    for object in objects:

        with bpy_context.Focus_Objects(object, mode='EDIT'):

            bm = bmesh.from_edit_mesh(object.data)
            if not bm.faces:
                continue

            # collect islands data
            mesh_areas: typing.List[float] = []
            uv_areas: typing.List[float] = []
            world_to_uv_ratios: typing.List[float] = []
            bound_box_ratios: typing.List[float] = []

            bm_copy = bm.copy()
            bm_copy.transform(object.matrix_world)

            bm_copy.faces.ensure_lookup_table()

            uv_layer = bm.loops.layers.uv.verify()

            islands = get_linked_uv_islands(bm, uv_layer)
            if not islands:
                continue

            face_to_uv_triangles = get_uv_triangles(bm, uv_layer)

            for island in islands:

                island_mesh_area = sum(bm_copy.faces[face.index].calc_area() for face in island)

                island_uv_area = sum(area_tri(*loop) for face in island for loop in face_to_uv_triangles[face])

                # #79775 - Something in Blender can generate invalid (Nan) values in UVMaps
                # https://projects.blender.org/blender/blender/issues/79775
                if math.isnan(island_uv_area):
                    island_uv_area = sum(area_tri(*loop) for face in island for loop in face_to_uv_triangles[face] if all(not map(math.isnan, vert) for vert in loop))

                try:
                    world_to_uv_ratio = island_mesh_area / island_uv_area
                except ZeroDivisionError:
                    world_to_uv_ratio = 0

                try:
                    bound_box_ratio = get_bound_box_ratio(island)
                    if bound_box_ratio < 1:
                        bound_box_ratio = 1 / bound_box_ratio
                except ZeroDivisionError:
                    bound_box_ratio = 0

                mesh_areas.append(island_mesh_area)
                uv_areas.append(island_uv_area)
                world_to_uv_ratios.append(world_to_uv_ratio)
                bound_box_ratios.append(bound_box_ratio)


            is_bad_islands = [bound_box_ratio > maximum_bound_box_ratio or world_to_uv_ratio == 0 or bound_box_ratio == 0 for world_to_uv_ratio, bound_box_ratio in zip( world_to_uv_ratios, bound_box_ratios)]

            # mean_scale_multiplier = statistics.harmonic_mean([math.sqrt(world_to_uv_ratio) for is_bad, world_to_uv_ratio in zip(is_bad_islands, world_to_uv_ratios) if not is_bad])

            bpy.ops.mesh.select_all(action='SELECT')
            bpy.ops.uv.select_all(action='DESELECT')

            for index, (island, mesh_area, uv_area, world_to_uv_ratio, bound_box_ratio, is_bad) in enumerate(zip(islands, mesh_areas, uv_areas, world_to_uv_ratios, bound_box_ratios, is_bad_islands)):

                if is_bad:

                    utils.print_in_color(utils.get_color_code(255,255,255, 148,0,211), f"Outlier island: {index}/{len(islands)}")

                    if not only_select:
                        bpy.ops.mesh.select_all(action='SELECT')
                        bpy.ops.uv.select_all(action='DESELECT')

                    select_island(island, uv_layer)

                    if only_select:
                        continue

                    bpy_context.call_in_uv_editor(bpy.ops.uv.unwrap, method='MINIMUM_STRETCH', fill_holes=True, no_flip=True, can_be_canceled=True, iterations=30)

                    uv_area = sum(area_tri(*loop) for face in island for loop in face_to_uv_triangles[face])
                    if math.isnan(uv_area):
                        uv_area = sum(area_tri(*loop) for face in island for loop in face_to_uv_triangles[face] if all(not map(math.isnan, vert) for vert in loop))


                if only_select:
                    continue

                # if uv_area == 0:
                #     scale_multiplier = mean_scale_multiplier
                # else:
                #     scale_multiplier = math.sqrt(mesh_area/uv_area)

                island_vertices = [loop[uv_layer].uv for face in island for loop in face.loops]
                island_center = sum(island_vertices, mathutils.Vector((0,0)))/len(island_vertices)

                # if divide_by_mean:
                #     scale_multiplier /= mean_scale_multiplier

                # for face in island:
                #     for loop in face.loops:

                #         uv_loop = loop[uv_layer]
                #         uv_loop.uv -= island_center
                #         uv_loop.uv *= scale_multiplier
                #         uv_loop.uv += island_center


                # stretch the bad uv island to make it no large than the maximum
                # to make packing more efficient
                try:
                    bound_box_ratio_raw = get_bound_box_ratio(island)
                    if bound_box_ratio_raw < 1:
                        bound_box_ratio = 1 / bound_box_ratio_raw
                    else:
                        bound_box_ratio = bound_box_ratio_raw
                except ZeroDivisionError as e:
                    continue

                if bound_box_ratio > maximum_bound_box_ratio:

                    for face in island:
                        for loop in face.loops:
                            uv_loop = loop[uv_layer]
                            uv_loop.uv -= island_center
                            if bound_box_ratio_raw > 1:
                                uv_loop.uv[0] /= bound_box_ratio/maximum_bound_box_ratio
                            else:
                                uv_loop.uv[1] /= bound_box_ratio/maximum_bound_box_ratio
                            uv_loop.uv += island_center


            bpy.ops.ed.flush_edits()
            bmesh.update_edit_mesh(object.data, loop_triangles=False, destructive=False)

            bm_copy.free()


def copy_uv(from_object: bpy.types.Object, to_object: bpy.types.Object, uv_layer_name: str):


    if not(from_object.type == to_object.type == 'MESH'):
        raise ValueError("\n\t".join([
            "Objects must be of type MESH:",
            f"{from_object.name_full}: {from_object.type}",
            f"{to_object.name_full}: {to_object.type}",
        ]))


    if len(from_object.data.loops) != len(to_object.data.loops):
        raise ValueError("\n\t".join([
            "Mesh loops count mismatch:",
            f"{from_object.name_full}: {from_object.data.loops}",
            f"{to_object.name_full}: {to_object.data.loops}",
        ]))


    with bpy_context.Focus_Objects([from_object, to_object]):

        uvs = array.array('f', [0.0, 0.0]) * len(from_object.data.loops)

        from_object.data.uv_layers[uv_layer_name].data.foreach_get('uv', uvs)

        to_object.data.uv_layers[uv_layer_name].data.foreach_set('uv', uvs)


def get_active_render_uv_layer(object: bpy.types.Object):

    if not object.data:
        return

    if not hasattr(object.data, 'uv_layers'):
        return

    for layer in object.data.uv_layers:
        if layer.active_render:
            return layer


def unwrap_ministry_of_flat_with_fallback(
            objects: typing.List[bpy.types.Object],
            settings: typing.Optional[tool_settings.Unwrap_UVs] = None,
            ministry_of_flat_settings: typing.Optional[tool_settings.Ministry_Of_Flat] = None,
        ):

    settings = tool_settings.Unwrap_UVs()._update(settings)
    ministry_of_flat_settings = tool_settings.Ministry_Of_Flat(vertex_weld=False, rasterization_resolution=1, packing_iterations=1)._update(ministry_of_flat_settings)

    for object in objects:

        if not object.data.polygons:
            utils.print_in_color(utils.get_foreground_color_code(217, 103, 41), f"Object has no faces: {object.name_full}")
            continue

        object_copy = get_object_copy_for_uv_unwrap(object)
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

                    unwrap_ministry_of_flat(object_copy, temp_dir, settings = ministry_of_flat_settings, uv_layer_name = settings.uv_layer_name)
            except utils.Fallback as e:

                utils.print_in_color(utils.get_color_code(240,0,0, 0,0,0), f"Fallback to smart_project: {e}")

                object_copy.data.uv_layers.active = object_copy.data.uv_layers[settings.uv_layer_name]

                bpy.ops.mesh.select_all(action='SELECT')
                bpy.ops.uv.select_all(action='SELECT')
                bpy.ops.uv.pin(clear=True)
                bpy.ops.uv.smart_project(angle_limit = math.radians(settings.smart_project_angle_limit))

            do_reunwrap = settings.reunwrap_bad_uvs_with_minimal_stretch or settings.reunwrap_all_with_minimal_stretch

            if do_reunwrap and 'iterations' in repr(bpy.ops.uv.unwrap):

                mark_seams_from_islands(object_copy, settings.uv_layer_name)

                if settings.reunwrap_all_with_minimal_stretch:
                    bpy.ops.mesh.select_all(action='SELECT')
                    bpy.ops.uv.select_all(action='SELECT')
                    bpy_context.call_in_uv_editor(
                        bpy.ops.uv.unwrap,
                        method='MINIMUM_STRETCH',
                        fill_holes=True,
                        no_flip=True,
                        use_weights = bool(settings.uv_importance_weight_group),
                        weight_group = settings.uv_importance_weight_group,
                        weight_factor = settings.uv_importance_weight_factor,
                        can_be_canceled=True,
                    )

                reunwrap_bad_uvs([object_copy])


        copy_uv(object_copy, object, settings.uv_layer_name)

        blend_inspector.inspect_if_has_identifier(blend_inspector.COMMON.INSPECT_UV_UNWRAP)

        bpy.data.objects.remove(object_copy)

        if settings.mark_seams_from_islands:
            mark_seams_from_islands(object, settings.uv_layer_name)


def get_weighted_percentile(values, quantiles, weights):
    """ https://stackoverflow.com/a/29677616/11799308 """

    import numpy as np

    values = np.array(values)
    quantiles = np.array(quantiles)
    weights = np.array(weights)

    sort_indices = np.argsort(values)

    values = values[sort_indices]
    weights = weights[sort_indices]

    weighted_quantiles = (np.cumsum(weights) - 0.5 * weights) / np.sum(weights)

    return np.interp(quantiles, weighted_quantiles, values)


def get_weighted_interquartile_range(values, weights = None):

    import numpy as np

    if weights is None:
        percentile = np.percentile(values, (25, 75), axis=None, method='linear', keepdims=False)
    else:
        percentile = get_weighted_percentile(values, (0.25, 0.75), weights)

    return np.subtract(percentile[1], percentile[0])


def get_texel_density_for_uv_quality(object: bpy.types.Object, uv_layer_name: str, current_texture_size = 2048):

    from mathutils.geometry import area_tri

    init_active = object.data.uv_layers.active

    object.data.uv_layers.active = object.data.uv_layers[uv_layer_name]

    bm = bmesh.new()
    bm.from_mesh(object.data)
    bm.transform(object.matrix_world)

    face_to_uv_triangles = get_uv_triangles(bm, bm.loops.layers.uv.verify())

    face_areas = []
    face_uv_areas = []

    for face in bm.faces:

        face_areas.append(face.calc_area())
        face_uv_areas.append(sum(area_tri(*loop) for loop in face_to_uv_triangles[face]))


    total_uv_area = sum(face_uv_areas)
    if math.isnan(total_uv_area):
        total_uv_area = sum(itertools.filterfalse(math.isnan, face_uv_areas))

    total_face_area = sum(face_areas)
    if math.isnan(total_uv_area):
        total_face_area = sum(itertools.filterfalse(math.isnan, face_areas))

    texel_densities = []
    weights = []
    area_ratios = []

    for face_area, face_area_uv in zip(face_areas, face_uv_areas):

        try:
            area_ratio = face_area / face_area_uv
            texel_density = math.sqrt(pow(current_texture_size, 2) / face_area * face_area_uv)
            weight = face_area / total_face_area
        except ZeroDivisionError:
            continue

        texel_densities.append(texel_density)
        weights.append(weight)
        area_ratios.append(area_ratio)

    texel_density_weighted_median = get_weighted_percentile(texel_densities, 0.5, weights)

    texel_density_deviation = get_weighted_interquartile_range(texel_densities, weights)

    area_ratios_deviation = get_weighted_interquartile_range(area_ratios, weights)

    object.data.uv_layers.active = init_active

    # this is invalid
    if total_uv_area >= 1:
        total_uv_area = 0
        texel_density_weighted_median = 0

    return texel_density_weighted_median, total_uv_area, texel_density_deviation, area_ratios_deviation


def select_collapsed_islands(object: bpy.types.Object, uv_layer_name: str, tolerance = 1e-5):
    """ The unwrap with minimal stretch can produce these when fails. """


    def get_bound_box_size(island: typing.List[bmesh.types.BMFace]):
        xs, ys = zip(*(bm_loop[uv_layer].uv for face in island for bm_loop in face.loops))
        return abs(max(xs) - min(xs)), abs(max(ys) - min(ys))

    loop_count = 0

    with bpy_context.Focus_Objects([object], mode='EDIT'):

        bpy.ops.mesh.reveal()
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.uv.reveal()
        bpy.ops.uv.select_all(action='DESELECT')

        bm = bmesh.from_edit_mesh(object.data)
        uv_layer = bm.loops.layers.uv[uv_layer_name]

        islands = get_linked_uv_islands(bm, uv_layer)

        for island in islands:

            x, y = get_bound_box_size(island)
            is_collapsed = x <= tolerance or y <= tolerance or math.isnan(x) or math.isnan(y)

            if is_collapsed:
                select_island(island, uv_layer)

        bmesh.update_edit_mesh(object.data, loop_triangles=False, destructive=False)

    return loop_count


def get_unwrap_quality_measures(object: bpy.types.Object, uv_layer_name: str, clear_seams = True):

    # save the uvs
    with bpy_context.Focus_Objects(object):
        saved_uvs = array.array('f', [0.0, 0.0]) * len(object.data.loops)
        object.data.uv_layers[uv_layer_name].data.foreach_get('uv', saved_uvs)


    stretches = []

    with bpy_context.Focus_Objects([object]):

        # https://blender.stackexchange.com/questions/139996/how-to-get-uv-stretching-angle-or-area-colors-with-python-without-looking-at-v

        from mathutils import Vector

        me = object.data
        uv_layer = me.uv_layers[uv_layer_name]

        for f in me.polygons:
            verts = [me.vertices[me.loops[l].vertex_index].co for l in f.loop_indices]
            uvs = [uv_layer.data[l].uv for l in f.loop_indices]
            lvs = Vector((v1 - v0).length for v0, v1 in zip(verts, verts[1:])).normalized()
            luvs = Vector((v1 - v0).length for v0, v1 in zip(uvs, uvs[1:])).normalized()

            stretches.append((lvs - luvs).length)


    with bpy_context.Focus_Objects([object], mode='EDIT'):

        bpy.ops.mesh.reveal()
        bpy.ops.mesh.select_all(action='SELECT')

        bpy.ops.uv.select_all(action='DESELECT')
        collapsed_loops_count = select_collapsed_islands(object, uv_layer_name)
        if collapsed_loops_count:
            bpy.ops.uv.hide(unselected=False)  # hiding because invalid anyway

        bpy.ops.uv.select_all(action='DESELECT')
        print('bpy.ops.uv.select_overlap...', '[ can be long for badly overlapped uvs ]')
        bpy.ops.uv.select_overlap()

        bm = bmesh.from_edit_mesh(object.data)
        bm.faces.ensure_lookup_table()
        uv_layer = bm.loops.layers.uv.verify()
        linked_uv_islands = get_linked_uv_islands(bm, uv_layer)

        overlapping_loops = get_selected_uvs_count(linked_uv_islands, uv_layer) + collapsed_loops_count

        bpy.ops.uv.reveal()
        bpy.ops.uv.select_all(action='DESELECT')

        from mathutils.geometry import area_tri
        face_to_uv_triangles = get_uv_triangles(bm, uv_layer)


        number_of_faces_in_island = []
        weights = []

        for island in linked_uv_islands:

            face_areas = []
            face_uv_areas = []

            for face in island:
                face_areas.append(face.calc_area())
                face_uv_areas.append(sum(area_tri(*loop) for loop in face_to_uv_triangles[face]))

            island_mesh_area = sum(itertools.filterfalse(math.isnan, face_areas))
            island_uv_area = sum(itertools.filterfalse(math.isnan, face_uv_areas))

            try:
                weight = island_mesh_area/island_uv_area
                number_of_faces_in_island.append(len(island))
                weights.append(weight)
            except ZeroDivisionError:
                pass


        faces_per_island_weighted_mean = sum(map(operator.mul, number_of_faces_in_island, weights))/sum(weights)


        mark_seams_from_islands(object, uv_layer_name)


        bm = bmesh.from_edit_mesh(object.data)
        bm.faces.ensure_lookup_table()
        uv_layer = bm.loops.layers.uv.verify()

        seam_length = 0
        for edge in bm.edges:
            if edge.seam:
                seam_length += edge.calc_length()

        if clear_seams:
            bpy.ops.uv.select_all(action='SELECT')
            bpy.ops.uv.mark_seam(clear=True)


        if enable_uv_packer_addon():

            bpy.ops.uv.select_all(action='SELECT')
            bpy.ops.uv.pin(clear=True)

            uv_packer_pack(2048, 2048, 4, True, False, use_high_quality_engine = False)

        _, _,  texel_density_deviation, area_ratios_deviation = get_texel_density_for_uv_quality(object, uv_layer_name)

        scale_uv_to_bounds([object])

        texel_density, uv_area_taken,  _, _ = get_texel_density_for_uv_quality(object, uv_layer_name)


    metric = Unwrap_Quality_Score(
        islands_count = len(linked_uv_islands),
        faces_per_island_weighted_mean = faces_per_island_weighted_mean,
        texel_density = texel_density,
        uv_area_taken = uv_area_taken,
        mean_stretches = statistics.mean(stretches),
        overlapping_loops = overlapping_loops,
        texel_density_deviation = texel_density_deviation,
        area_ratios_deviation = area_ratios_deviation,
        seam_length = seam_length,
    )

    metric._uvs = saved_uvs

    return metric


def scale_uv_to_bounds(objects: typing.List[bpy.types.Object], margin: float = 0):

    objects = bpy_utils.get_unique_data_objects(objects)

    with bpy_context.Focus_Objects(objects, mode='EDIT'):

        bmeshes = [bmesh.from_edit_mesh(object.data) for object in objects]

        min_x = float('inf')
        min_y = float('inf')
        max_x = float('-inf')
        max_y = float('-inf')

        for bm in bmeshes:

            uv_layer = bm.loops.layers.uv.verify()

            for face in bm.faces:
                for loop in face.loops:
                    uv = loop[uv_layer].uv
                    min_x = min(min_x, uv.x)
                    min_y = min(min_y, uv.y)
                    max_x = max(max_x, uv.x)
                    max_y = max(max_y, uv.y)

        scale_x = (1.0 - margin) / (max_x - min_x)
        scale_y = (1.0 - margin) / (max_y - min_y)

        for bm, object in zip(bmeshes, objects):

            uv_layer = bm.loops.layers.uv.verify()

            for face in bm.faces:
                for loop in face.loops:
                    uv = loop[uv_layer].uv
                    uv.x = (uv.x - min_x) * scale_x + margin / 2
                    uv.y = (uv.y - min_y) * scale_y + margin / 2

            bmesh.update_edit_mesh(object.data, loop_triangles=False, destructive=False)


def get_interquartile_range(values):

    if len(values) <= 1:
        return 0

    values_sorted = sorted(values)

    middle_index = len(values_sorted) // 2

    if len(values_sorted) % 2 == 1:
        lower_half = values_sorted[:middle_index]
        upper_half = values_sorted[middle_index + 1:]
    else:
        lower_half = values_sorted[:middle_index]
        upper_half = values_sorted[middle_index:]

    return statistics.median(upper_half) - statistics.median(lower_half)


class Unwrap_Quality_Score:

    def __init__(self, *,
            islands_count,
            faces_per_island_weighted_mean,
            texel_density,
            uv_area_taken,
            mean_stretches,
            overlapping_loops,
            texel_density_deviation,
            area_ratios_deviation,
            seam_length,
        ):

        self.islands_count = islands_count
        self.faces_per_island_weighted_mean = faces_per_island_weighted_mean
        self.texel_density = texel_density
        self.uv_area_taken = uv_area_taken
        self.mean_stretches = mean_stretches
        self.overlapping_loops = overlapping_loops
        self.texel_density_deviation = texel_density_deviation
        self.area_ratios_deviation = area_ratios_deviation
        self.seam_length = seam_length

        self._keys = tuple(key for key in self.__dict__.keys() if not key.startswith('_'))

        self._uvs = []


    def __getitem__(self, index: int):
        return getattr(self, self._keys[index])


    def __setitem__(self, index: int, value):
        return setattr(self, self._keys[index], value)


    def _normalize(self, index: str, min: float, max: float):
        if min == max:
            self[index] = 0
        else:
            self[index] = (self[index] - min) / (max - min)


    def _get_score(self):
        """ The values should be normalized first. """
        return (
            (- self.islands_count) * 3
            +
            self.faces_per_island_weighted_mean * 4
            +
            self.texel_density * 7
            +
            self.uv_area_taken * 6
            +
            (- self.mean_stretches) * 5
            +
            (- self.overlapping_loops) * 20
            +
            (- self.texel_density_deviation) * 4
            +
            (- self.area_ratios_deviation) * 10
            +
            (- self.seam_length) * 10
        )


    def _copy(self):
        return Unwrap_Quality_Score(**{key : getattr(self, key) for key in self._keys})


    @staticmethod
    def _get_best(candidates: typing.Dict[str, Unwrap_Quality_Score]):

        for name, measure in list(candidates.items()):
            if not measure:
                print(f"Method failed: {name}")
                candidates.pop(name)

        if not candidates:
            return ('None', None)

        if len(candidates) == 1:
            return list(candidates.items())[0]

        number_of_metrics = len(list(candidates.values())[-1]._keys)

        for name, measure in list(candidates.items()):
            print(name)
            for i in range(number_of_metrics):
                print('\t', round(measure[i], 3), end='\t', sep = '')
            print()


        # normalize
        copies = {key : value._copy() for key, value in candidates.items()}

        for i in range(number_of_metrics):

            values = [copies[name][i] for name in copies]

            values_median = statistics.median(values)

            iqr = get_interquartile_range(values)

            if math.isclose(iqr, 0, rel_tol=1e-9, abs_tol=1e-9):
                min_value = min(values)
                max_value = max(values)
                for name in copies:
                    copies[name]._normalize(i, min_value, max_value)
            else:
                for name in copies:
                    copies[name][i] = (copies[name][i] - values_median) / iqr


        variants = sorted(copies.items(), key = lambda x: x[1]._get_score())

        for i, (name, score) in enumerate(variants, start = 1):
            green_color = int(255/len(variants) * i)
            utils.print_in_color(utils.get_color_code(51, green_color, 51, 0,0,0), name, score._get_score())

        the_best_name = variants[-1][0]

        return (the_best_name, candidates[the_best_name])


    def _print(self, prefix = ''):
        for i, key in enumerate(self._keys):
            print(prefix + key, '=', round(self[i], 2))


class Unwrap_Methods:

    ACTIVE_RENDER = 'active_render'
    ACTIVE_RENDER_MINIMAL_STRETCH = 'active_render_minimal_stretch'

    MOF_DEFAULT = 'mof_default'
    MOF_SEPARATE_HARD_EDGES = 'mof_separate_hard_edges'
    MOF_USE_NORMAL = 'mof_use_normal'

    JUST_MINIMAL_STRETCH = 'just_minimal_stretch'
    JUST_CONFORMAL = 'just_conformal'

    SMART_PROJECT_REUNWRAP = 'smart_project_reunwrap'
    SMART_PROJECT_CONFORMAL = 'smart_project_conformal'

    CUBE_PROJECT_REUNWRAP = 'cube_project_reunwrap'
    CUBE_PROJECT_CONFORMAL = 'cube_project_conformal'


DEFAULT_BRUTE_FORCE_METHODS = {
    Unwrap_Methods.MOF_DEFAULT,
    Unwrap_Methods.MOF_SEPARATE_HARD_EDGES,
    Unwrap_Methods.MOF_USE_NORMAL,
    Unwrap_Methods.JUST_MINIMAL_STRETCH,
    Unwrap_Methods.JUST_CONFORMAL,
    Unwrap_Methods.SMART_PROJECT_REUNWRAP,
    Unwrap_Methods.SMART_PROJECT_CONFORMAL,
    Unwrap_Methods.CUBE_PROJECT_REUNWRAP,
    Unwrap_Methods.CUBE_PROJECT_CONFORMAL,
}


def brute_force_unwrap(
            object: bpy.types.Object,
            settings: typing.Optional[tool_settings.Unwrap_UVs] = None,
            ministry_of_flat_settings: typing.Optional[tool_settings.Ministry_Of_Flat] = None,
            methods: typing.Set[str] = DEFAULT_BRUTE_FORCE_METHODS,
        ):

    settings = tool_settings.Unwrap_UVs()._update(settings)
    ministry_of_flat_settings = tool_settings.Ministry_Of_Flat(vertex_weld=False, rasterization_resolution=1, packing_iterations=1)._update(ministry_of_flat_settings)

    ministry_of_flat_settings.stretch = False
    ministry_of_flat_settings.scale_uv_space_to_worldspace = True
    ministry_of_flat_settings.vertex_weld = False
    ministry_of_flat_settings.rasterization_resolution = 1
    ministry_of_flat_settings.packing_iterations = 1

    if not object.data.polygons:
        utils.print_in_color(utils.get_foreground_color_code(217, 103, 41), f"Object has no faces: {object.name_full}")
        return

    object_copy = get_object_copy_for_uv_unwrap(object)
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

        object_copy.data.uv_layers.active = object_copy.data.uv_layers[settings.uv_layer_name]

        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.uv.select_all(action='SELECT')
        bpy.ops.uv.pin(clear=True)


        def rescale():
            scale_uv_to_world_per_uv_island([object_copy])
            bpy.ops.mesh.select_all(action='SELECT')
            bpy.ops.uv.select_all(action='SELECT')
            aabb_pack()


        def mof_default():
            try:
                with tempfile.TemporaryDirectory() as temp_dir:

                    mof_settings = ministry_of_flat_settings._get_copy()

                    unwrap_ministry_of_flat(object_copy, temp_dir, settings = mof_settings, uv_layer_name = settings.uv_layer_name)

                    rescale()

                    return get_unwrap_quality_measures(object_copy, settings.uv_layer_name)
            except utils.Fallback:
                    traceback.print_exc(file=sys.stderr)
                    return None


        def mof_separate_hard_edges():
            try:
                with tempfile.TemporaryDirectory() as temp_dir:

                    mof_settings = ministry_of_flat_settings._get_copy()
                    mof_settings.separate_hard_edges = True

                    unwrap_ministry_of_flat(object_copy, temp_dir, settings = mof_settings, uv_layer_name = settings.uv_layer_name)

                    rescale()

                    return get_unwrap_quality_measures(object_copy, settings.uv_layer_name)
            except utils.Fallback:
                    traceback.print_exc(file=sys.stderr)
                    return None

        def mof_use_normal():
            try:
                with tempfile.TemporaryDirectory() as temp_dir:

                    mof_settings = ministry_of_flat_settings._get_copy()
                    mof_settings.use_normal = True

                    unwrap_ministry_of_flat(object_copy, temp_dir, settings = mof_settings, uv_layer_name = settings.uv_layer_name)

                    rescale()

                    return get_unwrap_quality_measures(object_copy, settings.uv_layer_name)
            except utils.Fallback:
                    traceback.print_exc(file=sys.stderr)
                    return None


        def smart_project(angle_limit: float):

            bpy.ops.mesh.select_all(action='SELECT')
            bpy.ops.uv.select_all(action='SELECT')
            bpy.ops.uv.pin(clear=True)
            bpy.ops.uv.smart_project(
                angle_limit = angle_limit,
                scale_to_bounds=False,
                correct_aspect = False,
            )

            # can produce bad result that affect the normalization negatively

            reunwrap_bad_uvs([object_copy])
            rescale()


        def cube_project():

            bpy.ops.mesh.select_all(action='SELECT')
            bpy.ops.uv.select_all(action='SELECT')
            bpy.ops.uv.pin(clear=True)
            bpy.ops.uv.cube_project(
                cube_size=2,
                clip_to_bounds=False,
                scale_to_bounds=False,
                correct_aspect = False,
            )

            reunwrap_bad_uvs([object_copy])
            rescale()


        def reunwrap_with_minimal_stretch():

            if not 'iterations' in repr(bpy.ops.uv.unwrap):
                return

            bpy.ops.mesh.select_all(action='SELECT')
            bpy.ops.uv.select_all(action='SELECT')

            with utils.Capture_Stdout() as capture:
                bpy_context.call_in_uv_editor(
                    bpy.ops.uv.unwrap,
                    method='MINIMUM_STRETCH',
                    use_weights = bool(settings.uv_importance_weight_group),
                    weight_group = settings.uv_importance_weight_group,
                    weight_factor = settings.uv_importance_weight_factor,
                    correct_aspect = False,
                    )

            # Warning: Unwrap failed to solve 1 of 1 island(s), edge seams may need to be added
            # When this happens it just re-packs the existing uv layout leading to a wrong conclusion

            for line in capture.lines.queue:
                print(line)
                match = re.search(r'(\d+) of (\d+)', line)
                if match and int(match.group(1)) == int(match.group(2)):
                    raise Exception(line)


        def reunwrap_conformal():

            bpy.ops.mesh.select_all(action='SELECT')
            bpy.ops.uv.select_all(action='SELECT')

            with utils.Capture_Stdout() as capture:
                bpy_context.call_in_uv_editor(
                    bpy.ops.uv.unwrap,
                    method='CONFORMAL',
                    correct_aspect = False,
                )

            # Warning: Unwrap failed to solve 1 of 1 island(s), edge seams may need to be added
            # When this happens it just re-packs the existing uv layout leading to a wrong conclusion

            for line in capture.lines.queue:
                print(line)
                match = re.search(r'(\d+) of (\d+)', line)
                if match and int(match.group(1)) == int(match.group(2)):
                    raise Exception(line)


        def clear_seams():
            bpy.ops.mesh.select_all(action='SELECT')
            bpy.ops.uv.select_all(action='SELECT')
            bpy.ops.uv.mark_seam(clear=True)


        def copy_active_render_uv():

            with bpy_context.Focus_Objects(object_copy):
                uvs = array.array('f', [0.0, 0.0]) * len(object_copy.data.loops)
                get_active_render_uv_layer(object_copy).data.foreach_get('uv', uvs)
                object_copy.data.uv_layers[object_copy.data.uv_layers.active.name].data.foreach_set('uv', uvs)


        def print_name(name: str):
            utils.print_in_color(utils.get_color_code(0,0,0, 247, 102, 40), name)


        clear_seams()


        skip_inspect = not blend_inspector.get_value('inspect_brute_force_unwrap', False)
        measures: typing.Dict[str, Unwrap_Quality_Score] = {}


        name = Unwrap_Methods.ACTIVE_RENDER
        if name in methods:
            print_name(name)
            try:
                copy_active_render_uv()
                rescale()
                measure = get_unwrap_quality_measures(object_copy, settings.uv_layer_name)
            except Exception:
                measure = None
                traceback.print_exc(file=sys.stderr)

            measures[name] = measure
            skip_inspect or binspect(name)


        name = Unwrap_Methods.ACTIVE_RENDER_MINIMAL_STRETCH
        if name in methods:
            print_name(name)
            try:
                copy_active_render_uv()
                mark_seams_from_islands(object_copy, settings.uv_layer_name)
                reunwrap_with_minimal_stretch()
                rescale()
                measure = get_unwrap_quality_measures(object_copy, settings.uv_layer_name)
            except Exception:
                measure = None
                traceback.print_exc(file=sys.stderr)

            measures[name] = measure
            skip_inspect or binspect(name)



        name = Unwrap_Methods.MOF_DEFAULT
        if name in methods:
            print_name(name)
            measures[name] = mof_default()
            skip_inspect or binspect(name)


        name = Unwrap_Methods.MOF_SEPARATE_HARD_EDGES
        if name in methods:
            print_name(name)
            measures[name] = mof_separate_hard_edges()
            skip_inspect or binspect(name)


        name = Unwrap_Methods.MOF_USE_NORMAL
        if name in methods:
            print_name(name)
            measures[name] = mof_use_normal()
            skip_inspect or binspect(name)



        is_minimal_stretch_failed = False

        name = Unwrap_Methods.JUST_MINIMAL_STRETCH
        if name in methods:
            print_name(name)
            try:
                reunwrap_with_minimal_stretch()
                measure = get_unwrap_quality_measures(object_copy, settings.uv_layer_name)
            except Exception:
                traceback.print_exc(file=sys.stderr)
                is_minimal_stretch_failed = True
                measure = None

            measures[name] = measure
            skip_inspect or binspect(name)


        name = Unwrap_Methods.JUST_CONFORMAL
        if name in methods:
            print_name(name)
            try:
                if is_minimal_stretch_failed:
                    raise Exception('MINIMUM_STRETCH has failed')  # this to reduce the outlier effect and save time, it most likely won't give a good result
                reunwrap_conformal()
                measure = get_unwrap_quality_measures(object_copy, settings.uv_layer_name)
            except Exception:
                traceback.print_exc(file=sys.stderr)
                measure = None

            measures[name] = measure
            skip_inspect or binspect(name)


        clear_seams()


        if any(name in (Unwrap_Methods.SMART_PROJECT_REUNWRAP, Unwrap_Methods.SMART_PROJECT_CONFORMAL) for name in methods):

            smart_project(math.radians(settings.smart_project_angle_limit))
            mark_seams_from_islands(object_copy, settings.uv_layer_name)

            name = Unwrap_Methods.SMART_PROJECT_REUNWRAP
            if name in methods:
                print_name(name)
                try:
                    reunwrap_with_minimal_stretch()
                    rescale()
                    measure = get_unwrap_quality_measures(object_copy, settings.uv_layer_name, clear_seams = False)
                except Exception:
                    traceback.print_exc(file=sys.stderr)
                    measure = None

                measures[name] = measure
                skip_inspect or binspect(name)

            name = Unwrap_Methods.SMART_PROJECT_CONFORMAL
            if name in methods:
                print_name(name)
                try:
                    reunwrap_conformal()
                    rescale()
                    measure = get_unwrap_quality_measures(object_copy, settings.uv_layer_name)
                except Exception:
                    traceback.print_exc(file=sys.stderr)
                    measure = None

                measures[name] = measure
                skip_inspect or binspect(name)


            clear_seams()



        if any(name in (Unwrap_Methods.CUBE_PROJECT_REUNWRAP, Unwrap_Methods.CUBE_PROJECT_CONFORMAL) for name in methods):

            cube_project()
            mark_seams_from_islands(object_copy, settings.uv_layer_name)

            name = Unwrap_Methods.CUBE_PROJECT_REUNWRAP
            if name in methods:
                print_name(name)
                try:
                    reunwrap_with_minimal_stretch()
                    rescale()
                    measure = get_unwrap_quality_measures(object_copy, settings.uv_layer_name, clear_seams = False)
                except Exception:
                    traceback.print_exc(file=sys.stderr)
                    measure = None

                measures[name] = measure
                skip_inspect or binspect(name)


            name = Unwrap_Methods.CUBE_PROJECT_CONFORMAL
            if name in methods:
                print_name(name)
                try:
                    reunwrap_conformal()
                    rescale()
                    measure = get_unwrap_quality_measures(object_copy, settings.uv_layer_name)
                except Exception:
                    traceback.print_exc(file=sys.stderr)
                    measure = None

                measures[name] = measure
                skip_inspect or binspect(name)

            clear_seams()



        the_best = Unwrap_Quality_Score._get_best(measures)[1]


        with bpy_context.Focus_Objects(object):
            object.data.uv_layers[settings.uv_layer_name].data.foreach_set('uv', the_best._uvs)

        re_unwrap_overlaps(object, settings.uv_layer_name)


        if blend_inspector.has_identifier(blend_inspector.COMMON.INSPECT_UV_UNWRAP):

            with bpy_context.Focus_Objects(object_copy):
                object_copy.data.uv_layers[settings.uv_layer_name].data.foreach_set('uv', the_best._uvs)

            re_unwrap_overlaps(object_copy, settings.uv_layer_name)

            mark_seams_from_islands(object_copy, settings.uv_layer_name)

            blend_inspector.inspect_blend(blend_inspector.COMMON.INSPECT_UV_UNWRAP)


        bpy.data.objects.remove(object_copy)


    if settings.mark_seams_from_islands:
        mark_seams_from_islands(object, settings.uv_layer_name)



def unwrap_with_fallback(
            objects: typing.List[bpy.types.Object],
            settings: typing.Optional[tool_settings.Unwrap_UVs] = None,
            ministry_of_flat_settings: typing.Optional[tool_settings.Ministry_Of_Flat] = None,
        ):

    settings = tool_settings.Unwrap_UVs()._update(settings)

    if settings.use_brute_force_unwrap:

        if settings.brute_unwrap_methods:
            methods = set(settings.brute_unwrap_methods)
        else:
            methods = DEFAULT_BRUTE_FORCE_METHODS

        for object in objects:
            brute_force_unwrap(object, settings, ministry_of_flat_settings, methods = methods)

    else:
        unwrap_ministry_of_flat_with_fallback(objects, settings, ministry_of_flat_settings)


    if blend_inspector.get_value('unwrap_test', False):
        raise Exception('Unwrap Test')



if bpy.app.version >= (5, 0):

    def select_island(island: typing.List[bmesh.types.BMFace], uv_layer: bmesh.types.BMLayerItem):

        for face in island:
            face.select = True
            for loop in face.loops:
                loop.uv_select_vert = True

    def get_selected_uvs_count(islands: typing.List[typing.List[bmesh.types.BMFace]], uv_layer: bmesh.types.BMLayerItem):
        return sum(loop.uv_select_vert for island in islands for face in island for loop in face.loops)

else:

    def select_island(island: typing.List[bmesh.types.BMFace], uv_layer: bmesh.types.BMLayerItem):
        for face in island:
            face.select = True
            for loop in face.loops:
                loop[uv_layer].select = True


    def get_selected_uvs_count(islands: typing.List[typing.List[bmesh.types.BMFace]], uv_layer: bmesh.types.BMLayerItem):
        return sum(loop[uv_layer].select for island in islands for face in island for loop in face.loops)
