import os
import json
import argparse
import sys
import subprocess
import threading
import socket
import atexit

import bpy

from blend_converter.addon import view3d_operator
from blend_converter import utils, bpy_utils


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
    VIEWER_STARTER_COMMAND = view3d_operator.PANDA_VIEWER_COMMAND
else:
    VIEWER_STARTER_COMMAND = view3d_operator.BLENDER_VIEWER_COMMAND


COMMANDER = view3d_operator.Viewer_Commander.get_viewer_commander()

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
    view3d_operator.update_camera(scene, depsgraph, COMMANDER)


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

        bpy_utils.open_homefile(BLEND)

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
