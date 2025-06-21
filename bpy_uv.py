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

import bpy
import mathutils
import bmesh

from . import utils
from . import bpy_context
from . import bpy_utils
from . import tool_settings


def ensure_uv_layer(objects: typing.List[bpy.types.Object], name: str, *, init_from: str = ''):

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
            with bpy_context.Bpy_State() as bpy_state:
                bpy_state.set(mesh.uv_layers, 'active', mesh.uv_layers[init_from])
                uvs = mesh.uv_layers.new(name = name, do_init = True)
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


def get_island_margin(meshes: typing.Iterable[bpy.types.Mesh], settings: tool_settings.UVs):
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


def unwrap_ministry_of_flat(object: bpy.types.Object, temp_dir: os.PathLike, settings: typing.Optional[tool_settings.Ministry_Of_Flat], uv_layer_name: typing.Optional[str] = None, mark_seams_from_islands = False):
    """ Currently operates on per mesh basis, so it is not possible to unwrap only a part of `bpy.types.Mesh`. """

    print('ministry_of_flat:', object.name_full)


    def move_modifier_to_first(object, modifier):
        if bpy.app.version < (2,90,0):
            for _ in range(len(object.modifiers)):
                bpy.ops.object.modifier_move_up(modifier = modifier.name)
        else:
            bpy.ops.object.modifier_move_to_index(modifier = modifier.name, index=0)


    def create_uv_transfer_modifier(object: bpy.types.Object, target_object: bpy.types.Object):

        modifier: bpy.types.DataTransferModifier = object.modifiers.new(name='__uv_transfer__', type='DATA_TRANSFER')

        move_modifier_to_first(object, modifier)

        modifier.object = target_object

        modifier.use_loop_data = True
        modifier.data_types_loops = {'UV'}
        modifier.loop_mapping = 'TOPOLOGY'

        return modifier


    def print_output(capture_stdout, capture_stderr, stderr_color = utils.get_color_code(255, 94, 14, 0,0,0)):
        for line in capture_stdout.lines.queue:
            print(line, end='')
        print()
        for line in capture_stderr.lines.queue:
            utils.print_in_color(stderr_color, line, end='')


    magenta_color = utils.get_color_code(255,128,255, 0,0,0)
    yellow_color = utils.get_color_code(219, 185, 61, 0,0,0)


    with bpy_context.Focus_Objects(object), bpy_context.Bpy_State() as bpy_state:


        if object.type != 'MESH':
            raise Exception(f"Object is not of mesh type: {object.name_full}")

        if not object.data.polygons:
            raise utils.Fallback(f"Object has no faces: {object.name_full}")


        bpy_state.set(object, 'rotation_mode', 'XYZ')
        bpy_state.set(object, 'location', (0,0,0))
        bpy_state.set(object, 'scale', (1,1,1))
        bpy_state.set(object, 'rotation_euler', (0,0,0))
        bpy_state.set(object, 'delta_location', (0,0,0))
        bpy_state.set(object, 'delta_scale', (1,1,1))
        bpy_state.set(object, 'delta_rotation_euler', (0,0,0))


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
                raise utils.Fallback('Fail to export obj.') from e


        cmd = settings._get_cmd(filepath_input, filepath_output)

        print('subprocess ', end='')
        try:
            process = subprocess.run(cmd, timeout=settings.timeout, text = True, capture_output=True, encoding='utf-8')
        except subprocess.TimeoutExpired as e:
            raise utils.Fallback(f"Timeout: {object.name_full}") from e

        returncode = process.returncode

        # if returncode == 1:
        #     pass
        # elif returncode == 3221225477:
        #     utils.print_in_color(utils.get_color_code(255,255,255, 255//2,0,0), "0xc0000005 Access Violation Error")
        #     _settings = settings._get_copy()
        #     _settings.grids = False
        #     _cmd = _settings._get_cmd(filepath_input, filepath_output)
        #     try:
        #         process = subprocess.run(_cmd, timeout=10, text = True, capture_output=True, encoding='utf-8')
        #     except subprocess.TimeoutExpired as e:
        #         raise utils.Fallback(f"Timeout: {object.name_full}") from e
        #     returncode = process.returncode

        if returncode == 1:
            pass
        elif returncode == 3221225786:
            raise KeyboardInterrupt(f"STATUS_CONTROL_C_EXIT: {object.name_full}")
        elif returncode == 3221225477:
            raise utils.Fallback(f"0xc0000005 Access Violation Error: {object.name_full}")
        else:
            print()
            utils.print_in_color(utils.get_color_code(0,0,0, 256,256,256), 'CMD:', utils.get_command_from_list(cmd))
            utils.print_in_color(yellow_color, process.stdout)
            utils.print_in_color(magenta_color, process.stderr)
            raise utils.Fallback(f"Bad return code {process.returncode}: {object.name_full}")

        if not os.path.exists(filepath_output):
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
                raise utils.Fallback('Fail to import obj.') from e

        imported_object = bpy.context.selected_objects[0]

        print('validate')
        with utils.Capture_Stdout() as capture_stdout:
            is_invalid_geometry = imported_object.data.validate(verbose=True)

        validation_lines: typing.List[str] = list(capture_stdout.lines.queue)

        if is_invalid_geometry:
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


                with bpy_context.State() as state:

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
                    bpy_context.call_with_override(override, bpy.ops.uv.select_linked)
                    try:
                        bpy_context.call_with_override(override, bpy.ops.uv.unwrap)
                    except Exception as e:
                        if 'CANCELLED' in str(e):
                            pass

                bpy.ops.uv.reveal()
                bpy.ops.object.editmode_toggle()

                was_re_unwrapped = True
            elif line.strip():
                bpy.data.objects.remove(imported_object)
                raise utils.Fallback(line)

        bpy_utils.focus(object)

        if not object.data.uv_layers:
            object.data.uv_layers.new()

        if uv_layer_name is None:
            imported_object.data.uv_layers[0].name = object.data.uv_layers.active.name
        else:
            imported_object.data.uv_layers[0].name = uv_layer_name


        if bpy_utils.is_single_user(object.data):
            modifier = create_uv_transfer_modifier(object, imported_object)

            with utils.Capture_Stdout() as capture:
                bpy.ops.object.modifier_apply(modifier=modifier.name)

        else:
            orig_mesh = object.data
            object.data = object.data.copy()

            modifier = create_uv_transfer_modifier(object, imported_object)

            with utils.Capture_Stdout() as capture:
                bpy.ops.object.modifier_apply(modifier=modifier.name)

            orig_mesh.user_remap(object.data)

            bpy.data.meshes.remove(orig_mesh)


        bpy.data.objects.remove(imported_object)


        for line in capture.lines.queue:
            if 'cannot be' in line:
                raise utils.Fallback(line)


        if mark_seams_from_islands:
            object.data.uv_layers.active = object.data.uv_layers[uv_layer_name]
            bpy.ops.object.editmode_toggle()
            bpy.ops.mesh.reveal()
            bpy.ops.uv.reveal()
            bpy.ops.mesh.select_all(action='SELECT')
            bpy.ops.uv.select_all(action='SELECT')
            bpy.ops.uv.mark_seam(clear=True)
            bpy.ops.uv.seams_from_islands()
            bpy.ops.object.editmode_toggle()


def get_uv_triangles(b_mesh: bmesh.types.BMesh, uv_layer):

    face_to_uv_triangles: typing.Dict[bmesh.types.BMFace, typing.List[typing.Tuple[mathutils.Vector, mathutils.Vector, mathutils.Vector]]]
    face_to_uv_triangles = collections.defaultdict(list)

    for triangle_loops in b_mesh.calc_loop_triangles():
        # assert triangle_loops[0].face is triangle_loops[1].face and triangle_loops[0].face is triangle_loops[2].face
        face_to_uv_triangles[triangle_loops[0].face].append(tuple(loop[uv_layer].uv for loop in triangle_loops))

    return face_to_uv_triangles


def scale_uv_to_world_per_uv_island(objects: typing.List[bpy.types.Object], use_selected = True, divide_by_mean = False):
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

            uv_layer = bm.loops.layers.uv.verify()

            islands = get_linked_uv_islands(bm, uv_layer)
            if use_selected:
                islands = list(filter(None, [[face for face in island if face.select] for island in islands]))

            if not islands:
                continue

            face_to_uv_triangles = get_uv_triangles(bm, uv_layer)

            islands_data = []
            multipliers = []


            for island in islands:

                island_mesh_area = sum(bm_copy.faces[face.index].calc_area() for face in island)

                island_uv_area = sum(area_tri(*loop) for face in island for loop in face_to_uv_triangles[face])

                # #79775 - Something in Blender can generate invalid (Nan) values in UVMaps
                # https://projects.blender.org/blender/blender/issues/79775
                if math.isnan(island_uv_area):
                    island_uv_area = sum(area_tri(*loop) for face in island for loop in face_to_uv_triangles[face] if all(not map(math.isnan, vert) for vert in loop))

                if island_uv_area == 0 or island_mesh_area == 0:
                    continue

                scale_multiplier = math.sqrt(island_mesh_area/island_uv_area)

                multipliers.append(scale_multiplier)

                islands_data.append(dict(
                    island_mesh_area = island_mesh_area,
                    island_uv_area = island_uv_area,
                    scale_multiplier = scale_multiplier,
                ))

            if not multipliers:
                continue

            mean = statistics.mean(multipliers)

            if len(multipliers) == 1:
                minimum = float('-inf')
                maximum = float('inf')
                new_mean = 1
            else:
                stdev = statistics.stdev(multipliers, mean)

                minimum = mean - 3 * stdev
                maximum = mean + 3 * stdev

                new_mean = statistics.mean(multiplier for multiplier in multipliers if multiplier <= maximum and multiplier >= minimum)


            def select(state, faces: typing.Iterable[bmesh.types.BMFace], value):
                for face in faces:
                    for vert in face.verts:
                        state.set(vert, 'hide', not value)
                        state.set(vert, 'select', value)
                    state.set(face, 'hide', not value)
                    state.set(face, 'select', value)
                    for loop in face.loops:
                        state.set(loop[uv_layer], 'select', value)


            for index, (island_data, island) in enumerate(zip(islands_data, islands)):

                scale_multiplier = island_data['scale_multiplier']

                if scale_multiplier > maximum or scale_multiplier < minimum:

                    utils.print_in_color(utils.get_color_code(255,255,255, 148,0,211), f"Outlier island: {index}/{len(islands)}")
                    # scale_multiplier = new_mean

                    # with bpy_context.State(print=False) as state:

                    #     select(state, bm.faces, False)
                    #     select(state, island, True)

                    #     utils.print_in_color(utils.get_color_code(255,255,255, 148,0,211), f"Unwrapping outlier island: {index}/{len(islands)}")
                    #     bpy.ops.uv.unwrap()

                    # island_uv_area = sum(area_tri(*loop) for face in island for loop in face_to_uv_triangles[face])
                    # island_mesh_area = island_data['island_mesh_area']

                    # if island_uv_area == 0 or island_mesh_area == 0:
                    #     continue

                    # scale_multiplier = math.sqrt(island_mesh_area/island_uv_area)

                island_vertices = [loop[uv_layer].uv for face in island for loop in face.loops]
                island_center = sum(island_vertices, mathutils.Vector((0,0)))/len(island_vertices)

                if not divide_by_mean:
                    new_mean = 1

                for face in island:
                    for loop in face.loops:

                        uv_loop = loop[uv_layer]
                        uv_loop.uv -= island_center
                        uv_loop.uv *= scale_multiplier / new_mean
                        uv_loop.uv += island_center

            bpy.ops.ed.flush_edits()
            bmesh.update_edit_mesh(object.data, loop_triangles=False, destructive=False)

            bm_copy.free()


def scale_uv_to_world_per_uv_layout(objects: typing.List[bpy.types.Object]):
    """ Works on the active uv layer. """
    print(f"{scale_uv_to_world_per_uv_layout.__name__}...")

    from mathutils.geometry import area_tri

    with bpy_context.Focus_Objects(objects, mode='EDIT'):

        for object in objects:

            bm = bmesh.from_edit_mesh(object.data)

            bm_copy = bm.copy()
            bm_copy.transform(object.matrix_world)

            bm_copy.faces.ensure_lookup_table()
            face_to_uv_triangles = get_uv_triangles(bm_copy, bm_copy.loops.layers.uv.verify())

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


def unwrap_and_pack(objects: typing.List[bpy.types.Object], settings: tool_settings.UVs) -> str:
    """ Assumes the objects are selected and in the object mode. """

    print('unwrap_and_pack_uvs...')

    objects = bpy_utils.get_unique_mesh_objects(objects)

    if not objects:
        print("No valid objects to unwrap and pack: ", [o.name_full for o in objects])
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

                    try:
                        bpy_context.call_with_object_override(object, [object], bpy.ops.object.material_slot_select)
                        any_material_selected = True
                    except Exception as e:
                        if 'CANCELLED' in str(e):
                            pass  # can be canceled if the material slot is not assigned to any polygon
                        else:
                            raise e

            if not any_material_selected:
                utils.print_in_color(utils.get_color_code(255, 219, 187, 0,0,0), f"Objects do not use materials with key:\n\tobjects = {', '.join([o.name_full for o in objects])}\n\tmaterial_key = {settings.material_key}")
                return

            bpy.ops.uv.select_all(action='SELECT')
        else:
            bpy.ops.mesh.select_all(action='SELECT')
            bpy.ops.uv.select_all(action='SELECT')


        if settings.average_uv_scale:
            scale_uv_to_world_per_uv_island(objects)

        aabb_pack(merge_overlap=settings.merge_overlap)

        bpy.ops.uv.pin(clear=True)

        for object in objects:
            # prevent the material to act as a source of the uv aspect ratio
            # ED_uvedit_get_aspect
            # https://github.com/blender/blender/blob/6329ac2f7ddee0fc203f9dc90dca07d4cc048e7e/source/blender/editors/uvedit/uvedit_unwrap_ops.cc#L270C6-L270C40
            # can also crate an empty or procedural texture in the material and make active
            for material_slot in object.material_slots:
                bpy_state.set(material_slot, 'material', None)

        if settings.do_unwrap:
            print('bpy.ops.uv.smart_project...')
            bpy.ops.uv.smart_project(
                island_margin = settings._uv_island_margin_fraction / 0.8,
                angle_limit = math.radians(settings.smart_project_angle_limit),
            )

        print('Packing UV islands...')


        if settings.use_uv_packer_addon and enable_uv_packer_addon():

            if settings.uv_packer_addon_pin_any_uv_vertex:
                pin_any_vertex(bpy.context.object.data)

            uv_packer_props: uv_packer.UVPackProperty = bpy.context.scene.UVPackerProps

            uv_packer_props.uvp_fullRotate = False
            uv_packer_props.uvp_rotate = '1'

            uv_packer_props.uvp_engine = 'OP1' # HQ

            uv_packer_props.uvp_width = settings._actual_width
            uv_packer_props.uvp_height = settings._actual_height
            uv_packer_props.uvp_padding = settings.padding

            uv_packer_props.uvp_selection_only = True
            uv_packer_props.uvp_combine = True

            uv_packer_props.uvp_prerotate = True
            uv_packer_props.uvp_rescale = settings.uvp_rescale


            # bpy.ops.object.editmode_toggle()
            # bpy.ops.object.editmode_toggle()
            bpy.ops.ed.flush_edits()
            # Exception: Input data validation for object InvisibleCollisions Cylinder failed, packing not possible: There are not enough vertices for provided geoIndex 427.

            class Dummy():
                pass

            class Dummy_Context():
                selected_objects = objects
                scene = bpy.context.scene

            # bpy.ops.uvpackeroperator.packbtn()
            for _object in objects:
               assert  _object.mode == 'EDIT', _object
            execute_uv_packer_addon(Dummy(), Dummy_Context())


            if settings.uv_packer_addon_pin_any_uv_vertex:
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


        if settings.inspect_post_unwrap:
            bpy_utils.inspect_blend()



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

            # for face in island:
            #     for loop in face.loops:
            #         loop[uv_layer].select = True

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


def ensure_pixel_per_island(objects: typing.List[bpy.types.Object], settings: tool_settings.UVs):
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
