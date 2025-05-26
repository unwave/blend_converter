import json
import os
import math
import socket
import sys
import threading
import traceback
import functools
import argparse

import mathutils
import bpy



CAMERA_ROTATION = mathutils.Matrix.Rotation(math.radians(90), 4, 'X')

DIR = os.path.dirname(__file__)


def get_args() -> dict:

    parser = argparse.ArgumentParser()
    parser.add_argument('-json_args')

    try:
        index = sys.argv.index('--')
    except ValueError:
        return {}

    args = sys.argv[index + 1:]
    args, _ = parser.parse_known_args(args)

    return json.loads(args.json_args)

ARGS = get_args()


def open_homefile(blend_file):

        import os

        blend_dir = os.path.dirname(blend_file)

        try:
            result = bpy.ops.wm.read_homefile(filepath=blend_file, load_ui=False)
        except RuntimeError:
            import traceback
            traceback.print_exc()

        assert 'CANCELLED' not in result

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


def update_model(model_path: str):

    bpy.data.batch_remove(list(filter(None, bpy.context.view_layer.objects)))
    bpy.ops.outliner.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)


    if model_path.lower().endswith('blend'):
        open_homefile(model_path)
    else:
        result = bpy.ops.import_scene.gltf(filepath=model_path, loglevel=50)
        assert 'CANCELLED' not in result


def set_useful_preferences():
    import bpy

    bpy.context.preferences.use_preferences_save = False

    bpy.context.preferences.view.show_splash = False
    bpy.context.preferences.inputs.use_mouse_emulate_3_button = True
    bpy.context.preferences.view.ui_scale = 1.2
    bpy.context.preferences.view.show_developer_ui = True
    bpy.context.preferences.view.show_tooltips_python = True

    bpy.context.scene.render.engine = 'CYCLES'

    active_keyconfig = bpy.context.preferences.keymap.active_keyconfig
    preferences = bpy.context.window_manager.keyconfigs[active_keyconfig].preferences
    if preferences:
        preferences.spacebar_action = 'SEARCH'


def get_space() -> bpy.types.SpaceView3D:
    for wm in bpy.data.window_managers:
        for window in wm.windows:
            for area in window.screen.areas:
                if area.type == 'VIEW_3D':
                    return area.spaces[0]

DELAY = 1/30

pre_view_matrix = None

def update_scene():

    global pre_view_matrix
    global scene_data
    data: dict = scene_data

    if not data:
        return DELAY

    space_view = get_space()

    if not space_view:
        return DELAY

    if not space_view.region_3d:
        return DELAY

    if space_view.region_3d.view_perspective != 'PERSP':
        return DELAY

    # view_matrix = list(zip(*[iter()]*4))

    # m = m @ CAMERA_ROTATION

    if pre_view_matrix != data['view_matrix']:
        space_view.region_3d.view_matrix = data['view_matrix']

    pre_view_matrix = data['view_matrix']

    # space_view.region_3d.perspective_matrix = data['perspective_matrix']
    # space_view.region_3d.window_matrix = data['window_matrix']

    # space_view.clip_start = data['near']
    # space_view.clip_end = data['far']
    # space_view.lens = data['fov']

    # data['width']
    # data['height']

    return DELAY

import queue

jobs_queue = queue.Queue()
SENTINEL = object()


def socket_listening(blender_socket: socket.socket):

    truncated_message = None
    message = None

    while blender_socket:

        message = blender_socket.recv(1024 * 8)
        if not message:
            continue

        messages = message.split(b'\0')

        if truncated_message is not None:
            messages[0] = truncated_message + messages[0]


        if messages[-1] == b'':
            truncated_message = None
        else:
            truncated_message = messages[-1]


        for message in messages[:-1]:
            jobs_queue.put(message)


def run(model_path: str):
    print('Updating model:', repr(model_path))
    update_model(model_path)


def working():

    global scene_data

    for job in iter(jobs_queue.get, SENTINEL):

        try:
            data: dict = json.loads(job)
        except json.decoder.JSONDecodeError:
            traceback.print_exc()
            print(job)
            continue

        if not data:
            continue

        if data.get('terminate') == True:

            def exit():
                bpy.ops.wm.quit_blender()

            bpy.app.timers.register(function = exit, persistent=True)
            return

        model_path = data.get('model')
        if model_path:
            bpy.app.timers.register(functools.partial(run, model_path), persistent=True)
        else:
            scene_data = data


def main():

    set_useful_preferences()

    global scene_data
    scene_data = {}

    try:
        blender_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        blender_socket.connect((ARGS['host'], ARGS['port']))
    except ConnectionRefusedError:
        traceback.print_exc()
    else:
        threading.Thread(target=working, daemon=True).start()
        threading.Thread(target=socket_listening, args=[blender_socket], daemon=True).start()

    bpy.app.timers.register(update_scene, persistent=True)


if __name__ == '__main__':
    main()
