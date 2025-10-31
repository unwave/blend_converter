import argparse
import json
import os
import queue
import socket
import sys
import threading
import time
import functools
import traceback

import bpy


SENTINEL = object()


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


def set_windows_console():

    try:
        import ctypes

        SW_HIDE = 0
        console = ctypes.windll.kernel32.GetConsoleWindow()
        ctypes.windll.user32.ShowWindow(console, SW_HIDE)

        menu = ctypes.windll.user32.GetSystemMenu(console, 0)
        ctypes.windll.user32.DeleteMenu(menu, 0xF060, 0)

    except Exception:
        traceback.print_exc()


def open_homefile(blend_file):

        blend_dir = os.path.dirname(blend_file)

        try:
            result = bpy.ops.wm.read_homefile(filepath=blend_file, load_ui=False)
        except RuntimeError:
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


def set_useful_preferences():

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


def message_processing(message_queue: queue.Queue, sentinel = SENTINEL):

    for job in iter(message_queue.get, sentinel):

        try:
            data: dict = json.loads(job)
        except json.decoder.JSONDecodeError:
            traceback.print_exc()
            print(job)
            continue

        print('SERVER RECEIVING:', data)

        code = data.pop('__code')

        if code == 'open_mainfile':
            do_func(bpy.ops.wm.open_mainfile, **data)

        elif code == 'kill':
            message_queue.put(sentinel)
            bpy.app.timers.register(exit)


def send(data: dict):
    print('SERVER SENDING:', data)
    SERVER_SOCKET.sendall(json.dumps(data).encode() + b'\0')


def message_receiving(socket_for_recv: socket.socket, message_queue: queue.Queue):

    truncated_message = None
    message = None

    while socket_for_recv:

        try:
            message = socket_for_recv.recv(1024 * 8)
        except Exception:
            return

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
            message_queue.put_nowait(message)


if bpy.app.background:
    def do_func(func, *args, **kwargs):
        func(*args, **kwargs)
else:
    def do_func(func, *args, **kwargs):

        def timer_func():
            func(*args, **kwargs)

        bpy.app.timers.register(timer_func, persistent=True)


if __name__ == '__main__':

    if os.name == 'nt':
        set_windows_console()

    set_useful_preferences()

    ARGS = get_args()

    try:
        SERVER_SOCKET = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        SERVER_SOCKET.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, True)
        SERVER_SOCKET.connect((ARGS['host'], ARGS['port']))
    except ConnectionRefusedError:
        traceback.print_exc()
    else:
        MESSAGE_QUEUE = queue.Queue()
        threading.Thread(target=message_receiving, args=[SERVER_SOCKET, MESSAGE_QUEUE], daemon=True).start()

        if bpy.app.background:
            message_processing(MESSAGE_QUEUE)
        else:
            threading.Thread(target=message_processing, args=[MESSAGE_QUEUE], daemon=True).start()
