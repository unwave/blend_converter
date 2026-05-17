import os
import json
import argparse
import sys
import subprocess
import threading
import socket
import atexit
import typing
import math
import time
import traceback

import bpy
import mathutils


import runpy

BC_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
runpy.run_path(os.path.join(BC_ROOT, 'serialization.py'))['bootstrap']()


from blend_converter.blender import bpy_utils
from blend_converter import utils
from blend_converter import root



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
        'far': space_view.clip_end,

        'view_location': list(space_view.region_3d.view_location),
        'view_rotation': list(space_view.region_3d.view_rotation),
        'view_distance': space_view.region_3d.view_distance,
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


PANDA_VIEWER_COMMAND = ['python', root.get_script_path('panda3d_viewer')]
BLENDER_VIEWER_COMMAND = [bpy.app.binary_path, '--python', root.get_blender_script_path('blender_viewer')]


def get_args() -> dict:

    parser = argparse.ArgumentParser()
    parser.add_argument('-json_args')

    args = sys.argv[sys.argv.index('--') + 1:]
    args, _ = parser.parse_known_args(args)

    return json.loads(args.json_args)


ARGS = get_args()


BLEND: str = ARGS['blend_path']
BLEND_DIR = os.path.dirname(BLEND)
BLEND_TITLE = os.path.splitext(BLEND)[1].lstrip('.').title()

RESULT: str = ARGS['result_path']
RESULT_TITLE = os.path.splitext(RESULT)[1].lstrip('.').title()


if RESULT.lower().endswith('.bam'):
    VIEWER_STARTER_COMMAND = PANDA_VIEWER_COMMAND
else:
    VIEWER_STARTER_COMMAND = BLENDER_VIEWER_COMMAND


COMMANDER = Viewer_Commander()

bpy.context.preferences.view.show_splash = False


def update_ui():
    for wm in bpy.data.window_managers:
        for window in wm.windows:
            for area in window.screen.areas:
                for region in area.regions:
                    if region.type == 'UI':
                        region.tag_redraw()


@bpy.app.handlers.persistent
def blend_conv_depsgraph_update_func(scene: bpy.types.Scene, depsgraph: bpy.types.Depsgraph):
    update_camera(scene, depsgraph, COMMANDER)


def start_viewer():

    with COMMANDER.lock:

        if not COMMANDER.is_terminated:
            print('The viewer is already running!')
            return

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            host = 'localhost'
            s.bind((host, 0))
            s.listen()
            port = s.getsockname()[1]

            extra_args = ['--',
                '-json_args',
                json.dumps(dict(host = host, port = port))
            ]

            def run():
                subprocess.run(VIEWER_STARTER_COMMAND + extra_args, check=True)
                s.close()

            threading.Thread(target = run, daemon = True).start()

            blende_socket, addr = s.accept()
            blende_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, True)

        COMMANDER.start(blende_socket, blend_conv_depsgraph_update_func)
        COMMANDER.load_model(RESULT)
        COMMANDER.terminate_callback = update_ui

        def send_terminate():
            print('Terminating the viewer.')
            COMMANDER.send(dict(terminate=True))

        atexit.register(send_terminate)

        update_ui()


class OP:

    @classmethod
    def get_op(cls: bpy.types.Operator):
        op_section, op_name = cls.bl_idname.split('.', 1)
        return getattr(getattr(bpy.ops, op_section), op_name)

    @classmethod
    def run(cls: 'OP', **kwargs):

        op = cls.get_op()

        result = op(**kwargs)
        if 'CANCELLED' in result:
            raise Exception(f"CANCELLED: op:{repr(op)}, kwargs: {kwargs}")

        return result


class BLENDCONVVIEWER_OT_start_viewer(bpy.types.Operator, OP):
    bl_idname = "wm.blendconvviewer_start_viewer"
    bl_label = "Start Viewer"

    def execute(self, context):

        if COMMANDER.is_terminated:
            threading.Thread(target=start_viewer, daemon=True).start()
            return {'FINISHED'}
        else:
            self.report({'WARNING'}, "The viewer is already running.")
            return {'CANCELLED'}


class BLENDCONVVIEWER_OT_reload_result_model(bpy.types.Operator, OP):
    bl_idname = "wm.blendconvviewer_reload_model"
    bl_label = "Reload Result Model"

    def execute(self, context):

        COMMANDER.load_model(RESULT)

        return {'FINISHED'}


class BLENDCONVVIEWER_OT_reload_blend_file(bpy.types.Operator, OP):
    bl_idname = "wm.blendconvviewer_reload_blend_file"
    bl_label = "Reload Source Blend"

    def execute(self, context):

        bpy_utils.read_homefile(BLEND)

        return {'FINISHED'}


class BLENDCONVVIEWER_OT_os_show(bpy.types.Operator):
    bl_idname = "wm.blendconvviewer_os_show"
    bl_label = "Show In File Explorer"

    path: bpy.props.StringProperty(options={'SKIP_SAVE'})

    def execute(self, context):

        utils.os_show(self.path)

        return {'FINISHED'}


class BLENDCONVVIEWER_PT_panel(bpy.types.Panel):
    bl_label = "Default"
    bl_category = "BC_VIEWER"
    bl_space_type = 'VIEW_3D'
    bl_region_type = "UI"

    def draw(self, context):
        layout = self.layout
        column = layout.column()

        box = column.box()
        box.label(text=BLEND_TITLE)

        box.operator(BLENDCONVVIEWER_OT_os_show.bl_idname, text=BLEND, emboss=False).path = BLEND
        box.operator(BLENDCONVVIEWER_OT_reload_blend_file.bl_idname)

        box = column.box()
        box.label(text=RESULT_TITLE)

        box.operator(BLENDCONVVIEWER_OT_os_show.bl_idname, text=RESULT, emboss=False).path = RESULT

        if COMMANDER.is_terminated:
            box.operator(BLENDCONVVIEWER_OT_start_viewer.bl_idname)
        else:
            box.operator(BLENDCONVVIEWER_OT_reload_result_model.bl_idname)
            box.label(text='The viewer is running.')


for key, value in list(globals().items()):
    if key.startswith('BLENDCONVVIEWER_'):
        bpy.utils.register_class(value)


BLENDCONVVIEWER_OT_start_viewer.run()
BLENDCONVVIEWER_OT_reload_blend_file.run()
