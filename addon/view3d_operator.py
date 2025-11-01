import json
import math
import os
import socket
import subprocess
import threading
import time
import typing
import uuid
import traceback

import bpy
import mathutils

from . import reg


from .. import utils
from ..blender import bpy_utils
from .. import tool_settings


class Viewer_Commander:

    def __init__(self, ):
        self.state = {}
        self.is_dirty = True
        self.is_terminated = True
        self.lock = threading.RLock()
        self.terminate_callback: typing.Optional[typing.Callable] = None


    def start(self, blende_socket: socket.socket, depsgraph_update_func: typing.Callable):

        with self.lock:

            self.blende_socket = blende_socket
            self.depsgraph_update_func = depsgraph_update_func

            self.remove_depsgraph_update()

            self.is_terminated = False

            bpy.app.handlers.depsgraph_update_post.append(depsgraph_update_func)  # pyright: ignore[reportAttributeAccessIssue]

            bpy.app.timers.register(self.tick_send, persistent=True)

            print('START', time.strftime('%H:%M:%S %Y-%m-%d'))


    def remove_depsgraph_update(self):
        for func in list(bpy.app.handlers.depsgraph_update_post):  # pyright: ignore[reportArgumentType]
            if func is self.depsgraph_update_func:
                bpy.app.handlers.depsgraph_update_post.remove(func)  # pyright: ignore[reportAttributeAccessIssue]


    def terminate(self):

        with self.lock:
            self.remove_depsgraph_update()

            self.is_terminated = True

            print('EXIT', time.strftime('%H:%M:%S %Y-%m-%d'))

            if self.terminate_callback is not None:

                def do_once():
                    self.terminate_callback()

                bpy.app.timers.register(do_once, persistent=True)


    def set(self, key: str, value):
        self.state[key] = value
        self.is_dirty = True


    def update(self, date: dict):
        self.state.update(date)
        self.is_dirty = True


    def send(self, data: dict):
        try:
            self.blende_socket.sendall(json.dumps(data).encode() + b'\0')
        except Exception:
            traceback.print_exc()

            self.terminate()

    def tick_send(self):
        if self.is_terminated:
            return None

        viewport_camera_data = get_viewport_camera_data()
        if viewport_camera_data:
            self.state.update(viewport_camera_data)

        if self.is_dirty or viewport_camera_data:
            self.send(self.state)
            self.is_dirty = False

        return 1/60


    def load_model(self, model_path):
        self.send({'model': model_path})


    @staticmethod
    def get_viewer_commander() -> 'Viewer_Commander':
        return getattr(bpy.data.window_managers[0], 'blend_converter_viewer_commander')


reg.property(
    'blend_converter_viewer_commander',
    Viewer_Commander()
)

BLENDER_CAMERA_ROTATION = mathutils.Matrix.Rotation(math.radians(-90), 4, 'X')


def get_perspective_view_3d_area():
    for wm in bpy.data.window_managers:
        for window in wm.windows:
            for area in window.screen.areas:

                if area.type != 'VIEW_3D':
                    continue

                if not area.spaces:
                    continue

                if not area.spaces[0].region_3d:
                    continue

                if area.spaces[0].region_3d.view_perspective != 'PERSP':
                    continue

                return area

def get_viewport_camera_data():

    area = get_perspective_view_3d_area()
    if not area:
        return

    space_view: bpy.types.SpaceView3D = area.spaces[0]

    for region in area.regions:
        if region.type == 'WINDOW':
            break

    x = region.width
    y = region.height

    # hardcoded
    sensor_width = 36
    zoom = 2

    if x < y:
        sensor_width = sensor_width * x/y

    return {
        'width': x,
        'height': y,

        'matrix': [value for row in (space_view.region_3d.view_matrix.inverted() @ BLENDER_CAMERA_ROTATION).transposed() for value in row],

        'view_matrix': [list(row) for row in space_view.region_3d.view_matrix.transposed()],
        # 'perspective_matrix': [list(row) for row in space_view.region_3d.perspective_matrix],
        # 'window_matrix': [list(row) for row in space_view.region_3d.window_matrix],

        'fov': math.degrees(2.0 * math.atan((sensor_width / 2.0) / space_view.lens * zoom)),
        'near': space_view.clip_start,
        'far': space_view.clip_end
    }


def update_camera(scene: bpy.types.Scene, depsgraph: bpy.types.Depsgraph, commander: Viewer_Commander):

    for update in depsgraph.updates:
        if update.id.original != scene.camera:
            continue

        id_data: bpy.types.Object = update.id
        camera_data: bpy.types.Camera = id_data.data

        commander.update({
            'matrix': [value for row in (id_data.matrix_world @ BLENDER_CAMERA_ROTATION).transposed() for value in row],
            'fov': math.degrees(camera_data.angle),
            'near': camera_data.clip_start,
            'far': camera_data.clip_end
        })



class BLENDCONVERTER_PROP_bake_settings(bpy.types.PropertyGroup):
    __annotations__ = tool_settings.Bake._get_ui_properties()


reg.property(
    'blend_converter_bake_settings',
    bpy.props.PointerProperty(type=BLENDCONVERTER_PROP_bake_settings)
)


PANDA_VIEWER_COMMAND = ['python', utils.get_script_path('panda3d_viewer')]
BLENDER_VIEWER_COMMAND = [bpy.app.binary_path, '--python', utils.get_blender_script_path('blender_viewer')]
UPDATE_VIEWER_MODEL_PY = utils.get_script_path('update_viewer_model')


def update_model(model_type, viewer_starter_command, blend_path, object_names, temp_dir, bake_settings, bullet_physics):


    update_model_json_info = os.path.join(temp_dir, uuid.uuid1().hex + '.json')
    def get_model_path():
        with open(update_model_json_info, 'r', encoding='utf-8') as file:
            return json.load(file)['path']


    update_model_command = [
        'python',
        UPDATE_VIEWER_MODEL_PY,
        json.dumps(dict(
            blend_path = blend_path,
            object_names = object_names,
            temp_dir = temp_dir,
            bake_settings = bake_settings,
            update_model_json_info = update_model_json_info,
            model_type = model_type,
            blender_executable = bpy.app.binary_path,
            bullet_physics = bullet_physics,
        ))
    ]


    commander = Viewer_Commander.get_viewer_commander()

    if commander.is_terminated:
        def run():

            subprocess.run(update_model_command, check=True)

            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                host = 'localhost'
                s.bind((host, 0))
                s.listen()
                port = s.getsockname()[1]

                extra_args = ['--',
                    '-json_args',
                    json.dumps(dict(
                        host = host,
                        port = port,
                    ))
                ]

                def run():
                    subprocess.run(viewer_starter_command + extra_args, check=True)
                    s.close()

                threading.Thread(target = run, daemon = True).start()

                blende_socket, addr = s.accept()
                blende_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, True)

            @bpy.app.handlers.persistent
            def blend_conv_depsgraph_update_func(scene: bpy.types.Scene, depsgraph: bpy.types.Depsgraph):
                update_camera(scene, depsgraph, commander)

            commander.start(blende_socket, blend_conv_depsgraph_update_func)
            commander.load_model(get_model_path())
    else:
        def run():
            subprocess.run(update_model_command, check=True)
            commander.load_model(get_model_path())

    threading.Thread(target = run, daemon = True).start()


class BLENDCONVERTER_OT_export_and_inspect(bpy.types.Operator):
    bl_idname = 'object.blend_converter_export_and_inspect'
    bl_label = 'Export And Inspect'
    bl_options = {'REGISTER'}


    viewer_type: bpy.props.EnumProperty(
            name = 'Viewer Type',
            items = [
                ('PANDA', 'Panda3d', ''),
                ('BLENDER', 'Blender', ''),
            ],
            default = 'BLENDER') # type: ignore


    bullet_physics: bpy.props.BoolProperty()
    COLLISION_OBJECT_KEY = 'atool_collision_object_type'


    def execute(self, context):

        if self.bullet_physics:
            objects = [object for object in context.view_layer.objects if object.get(self.COLLISION_OBJECT_KEY)]
            if not objects:
                self.report({'ERROR'}, "No valid collision objects found to export.")
                return {'CANCELLED'}
        else:
            objects = [object for object in context.selected_objects]
            if not objects:
                message = 'Select at least one object.'
                self.report({'INFO'}, message)
                return {'CANCELLED'}

        utils.reload_library()

        return self.update(context, objects)


    def update(self, context: bpy.types.Context, objects: typing.List[bpy.types.Object]):


        temp_dir = os.path.join(bpy.app.tempdir, f'bc_{utils.get_time_stamp()}')
        os.makedirs(temp_dir)

        if bpy.data.filepath:
            basename = os.path.basename(bpy.data.filepath)
        else:
            basename = 'untitled.blend'

        blend_path = os.path.join(temp_dir, basename)

        for image in bpy.data.images:
            if image.source == 'GENERATED' and image.is_dirty:
                image.pack()

            if image.source == 'FILE':
                image.filepath = bpy_utils.get_block_abspath(image)

        bpy.data.libraries.write(filepath = blend_path, datablocks = set([context.scene]), fake_user=True, path_remap = 'ABSOLUTE', compress = False)

        utils.os_show(blend_path)

        bake_settings = tool_settings.Bake._from_bpy_struct(context.window_manager.blend_converter_bake_settings)

        kwargs = dict(
            blend_path = blend_path,
            object_names = [o.name for o in objects],
            temp_dir = temp_dir,
            bake_settings = bake_settings._to_dict(),
            bullet_physics = self.bullet_physics,
        )

        if self.viewer_type == 'PANDA':
            kwargs=dict(model_type = 'Bam', viewer_starter_command = PANDA_VIEWER_COMMAND, **kwargs)
        else:
            kwargs=dict(model_type = 'Gltf', viewer_starter_command = BLENDER_VIEWER_COMMAND, **kwargs)

        threading.Thread(target = update_model, kwargs=kwargs, daemon = True).start()

        return {'FINISHED'}
