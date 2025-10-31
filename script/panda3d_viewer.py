import argparse
import json
import os
import queue
import socket
import sys
import threading
import traceback
import typing
import functools

os.environ['__GL_SYNC_TO_VBLANK'] = '1'

import simplepbr
from direct.gui.OnscreenText import OnscreenText
from direct.showbase.ShowBase import ShowBase
from panda3d import bullet, core


base: 'Viewer'
render: 'core.NodePath'

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


SENTINEL = object()

core.load_prc_file_data('',"""
win-size 1600 800
show-frame-rate-meter true
sync-video true
preload-textures 0
""")


def get_color_from_int8(*args):
    if len(args) == 3:
        return core.Vec4F(*(arg/255 for arg in args), 1)
    else:
        return core.Vec4F(*(arg/255 for arg in args))


def add_text(pos, msg):
    return OnscreenText(text=msg, style=1, fg=(0, 0, 0, 1), scale=0.05, shadow=(0, 0, 0, 1), parent=base.a2dTopLeft, pos=(0.08, -pos - 0.04), align=core.TextNode.ALeft )


class Viewer(ShowBase):


    def __init__(self, *args):

        super().__init__()

        self.jobs_queue = queue.Queue()

        self.pipeline = simplepbr.init(use_330=True)

        cube_map = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'cubemap')

        if os.path.exists(os.path.join(cube_map, 'map0.png')):
            self.pipeline.env_map = os.path.join(cube_map, 'map#.png')
        else:
            self.ambient_light = self.render.attach_new_node(core.AmbientLight('ambient_light'))
            self.ambient_light.node().set_color((.2, .2, .2, 1))
            self.render.set_light(self.ambient_light)

        # zup_axis = self.loader.load_model('zup-axis')
        # zup_axis.reparent_to(self.render)


        self.accept('escape', sys.exit)

        self.accept('shift-r', self.reload_last_model)
        self.accept('shift-l', self.render.ls)
        self.accept('shift-a', self.render.analyze)
        self.accept('shift-b', self.debug)

        self.accept('a', self.next_animation)
        self.accept('alt-a', self.stop_animations)
        self.current_anim_index = -1


        # setup socket connection
        self.scene_state = {}

        try:
            self.blender_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.blender_socket.connect((ARGS['host'], ARGS['port']))
        except (ConnectionRefusedError, KeyError):
            traceback.print_exc()
            # self.oobe()
            self.camera_lens = self.cam.node().get_lens()
        else:
            self.disable_mouse()

            scene_camera: core.NodePath[core.Camera] = self.camera.find('**/+Camera/**')
            self.camera_lens = scene_camera.node().get_lens()

            threading.Thread(target=self.message_receiving, daemon=True).start()
            threading.Thread(target=self.message_processing, daemon=True).start()

            self.taskMgr.add(self.camera_control_task, "camera_control_task")


        # set bullet world
        self.bullet_world = bullet.BulletWorld()

        self.taskMgr.add(self.update_bullet, 'update_bullet', extraArgs = [self.bullet_world.do_physics, self.clock])

        node = bullet.BulletDebugNode('Debug')
        self.bullet_world.setDebugNode(node)
        node.showWireframe(True)
        node.showConstraints(True)
        node.showBoundingBoxes(False)
        node.showNormals(False)
        node_path = self.render.attachNewNode(node)


        # UI
        PTOOLS_PATH = r'C:\Users\user\Documents\panda3d\common'
        if os.path.exists(PTOOLS_PATH):
            sys.path.insert(1, PTOOLS_PATH)

        import ptools

        ptools.debug.add_toggler(self, self.toggle_wireframe, self.toggle_wireframe, 'show_wireframe').set_init(False)
        # ptools.debug.add_toggler(self, self.toggle_backface, self.toggle_backface, 'show_backface').set_init(False)
        ptools.debug.add_toggler(self, self.toggle_texture, self.toggle_texture, 'show_texture').set_init(True)


        def add_simplepbr_toggler(attr: str):
            return ptools.debug.add_toggler(self, functools.partial(setattr, self.pipeline, attr, True), functools.partial(setattr, self.pipeline, attr, False), attr)

        add_simplepbr_toggler('use_normal_maps').on()
        add_simplepbr_toggler('use_occlusion_maps').on()
        add_simplepbr_toggler('use_emission_maps').on()


        ptools.debug.add_toggler(self, node_path.show, node_path.hide, 'Show Bullet World Debug').on()

        self.alpha_switcher = ptools.debug.add_switcher(
            self,
            'Alpha Mode',
            functions=[
                lambda: self.render.set_transparency(core.TransparencyAttrib.M_alpha, 1),
                lambda: self.render.set_transparency(core.TransparencyAttrib.M_premultiplied_alpha, 1),
                lambda: self.render.set_transparency(core.TransparencyAttrib.M_multisample, 1),
                lambda: self.render.set_transparency(core.TransparencyAttrib.M_multisample_mask, 1),
                lambda: self.render.set_transparency(core.TransparencyAttrib.M_binary, 1),
                lambda: self.render.set_transparency(core.TransparencyAttrib.M_dual, 1),
            ],
            texts=[
                 'M_alpha',
                 'M_premultiplied_alpha',
                 'M_multisample',
                 'M_multisample_mask',
                 'M_binary',
                 'M_dual'
            ],
        )

        self.alpha_switcher.set_index(2)


        # init camera position
        def print_coords():
            a = self.trackball.node().get_hpr()
            print(a)
            a = self.trackball.node().get_pos()
            print(a)


        self.trackball.node().set_hpr(core.LVecBase3f(41.0451, 14.5675, -12.6301))
        self.trackball.node().set_pos(core.LPoint3f(-0.228, 9.68801, -1.116))

        self.trackball.node().setForwardScale(self.trackball.node().getForwardScale()/50)

        self.accept('n', print_coords)


        # load model
        if args and args[0] != '--' and os.path.exists(args[0]):
            self.update_model(args[0])


    def __del__(self):
        self.blender_socket.close()


    def update_bullet(self, do_physics: typing.Callable, clock: typing.Callable):
        do_physics(clock.get_dt())
        return 1


    def stop_animations(self):
        self.anims.clearAnims()

        if hasattr(self, 'current_anim_text'):
            self.current_anim_text.destroy()

        self.current_anim_text = add_text(0.15, f"Current animation: [STOPPED]")


    def next_animation(self):

        if not self.model_np.find('**/+Character'):
            return

        if not self.anims.getAnims():
            core.autoBind(self.model_np.node(), self.anims, -1)

        anim_names = self.anims.get_anim_names()
        if not anim_names:
            return

        self.current_anim_index += 1
        if self.current_anim_index == len(anim_names):
            self.current_anim_index = 0

        self.anims.get_anim(self.current_anim_index).loop(True)

        if hasattr(self, 'current_anim_text'):
            self.current_anim_text.destroy()

        self.current_anim_text = add_text(0.15, f"Current animation: {anim_names[self.current_anim_index]}")


    def update_model(self, model_path: str):

        self.last_model_path = model_path

        if hasattr(self, 'model_np'):
            self.model_np.remove_node()

        assert os.path.exists(model_path), model_path

        panda_path = core.Filename.from_os_specific(os.path.abspath(model_path))

        flags = core.LoaderOptions(core.LoaderOptions.LF_no_cache)

        self.model_np: core.NodePath = self.loader.load_model(panda_path, loaderOptions = flags, noCache=True)
        self.model_np.reparent_to(self.render)


        # turning on character animation
        if self.model_np.find('**/+Character'):
            self.anims = core.AnimControlCollection()
            self.current_anim_text = add_text(0.15, f"Current animation: [PRESS A]")


        for rigid_body in self.bullet_world.get_rigid_bodies():
            self.bullet_world.remove(rigid_body)


        for node in self.bullet_world.get_rigid_bodies():
            self.bullet_world.remove(node)

        for node in self.bullet_world.get_ghosts():
            self.bullet_world.remove(node)

        if self.attach_to_bullet_world(self.model_np):
            self.add_ground_plane()
            self.bullet_world.set_gravity(core.Vec3(0, 0, -10))


    def attach_to_bullet_world(self, object: typing.Union[core.NodePath, bullet.BulletRigidBodyNode, bullet.BulletGhostNode]):

        count = 0

        if isinstance(object, core.NodePath):
            for bullet_node in object.find_all_matches('**/+BulletRigidBodyNode'):
                self.bullet_world.attach(bullet_node.node())
                count += 1
            for bullet_node in object.find_all_matches('**/+BulletGhostNode'):
                self.bullet_world.attach(bullet_node.node())
                count += 1
            if isinstance(object.node(), (bullet.BulletRigidBodyNode, bullet.BulletGhostNode)):
                self.bullet_world.attach(object.node())
                count += 1
        elif isinstance(object, (bullet.BulletRigidBodyNode, bullet.BulletGhostNode)):
            self.bullet_world.attach(object)
            count += 1

        return count


    def add_ground_plane(self):
        """
        Always triggers Ghost collisions.
        https://discourse.panda3d.org/t/solved-bulletplaneshape-bulletghostnode-collision-issue/10864
        """

        shape = bullet.BulletPlaneShape(core.Vec3(0, 0, 1), 0)
        node = bullet.BulletRigidBodyNode('Ground')
        node.addShape(shape)
        np = render.attach_new_node(node)
        np.setPos(0, 0, -10)
        self.attach_to_bullet_world(node)


    def reload_last_model(self):
        self.update_model(self.last_model_path)


    def debug(self):
        breakpoint()


    @staticmethod
    def load_matrix(mat):
        lmat = core.LMatrix4()

        for i in range(4):
            lmat.set_row(i, core.LVecBase4(*mat[i * 4: i * 4 + 4]))
        return lmat


    def camera_control_task(self, task):

        data = self.scene_state
        if data:
            if 'view_mat' in data:
                user_mat = core.LMatrix4f(*data['user_mat'])
                # user_mat = self.load_matrix(data['user_mat'])
                self.camera_lens.set_user_mat(user_mat)

                view_mat = core.LMatrix4f(*data['view_mat'])
                # view_mat = self.load_matrix(data['view_mat'])

                view_mat.invert_in_place()
                self.camera_lens.set_view_mat(view_mat)

                # core.WindowProperties().setSize(data['width'], data['height'])

                props = core.WindowProperties()
                props.setSize(data['width'], data['height'])

                self.win.requestProperties(props)

                self.camera.set_mat(self.camera.get_mat())

            else:
                self.camera.set_mat(render, core.LMatrix4f(*data['matrix']))
                self.camera_lens.fov = data['fov']
                self.camera_lens.near = data['near']
                self.camera_lens.far = data['far']

                props = core.WindowProperties()
                props.setSize(data['width'], data['height'])
                self.win.requestProperties(props)

        return 1


    def message_receiving(self):

        truncated_message = None
        message = None

        while self.blender_socket:

            message = self.blender_socket.recv(1024 * 8)
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
                self.jobs_queue.put(message)


    def message_processing(self):

        for job in iter(self.jobs_queue.get, SENTINEL):

            try:
                data: dict = json.loads(job)
            except json.decoder.JSONDecodeError:
                traceback.print_exc()
                print(job)
                continue

            if not data:
                continue

            if data.get('terminate') == True:
                self.do_method_later(0, sys.exit, None)
                return

            model_path = data.get('model')
            if model_path:
                print('Updating model:', repr(model_path))
                self.update_model(model_path)
            else:
                self.scene_state = data


def main():
    Viewer(*sys.argv[1:]).run()

if __name__ == '__main__':
    main()
