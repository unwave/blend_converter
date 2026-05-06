import typing
import os


from .. import utils
from .. import tool_settings


if utils.is_in_blender():
    import bpy
elif not typing.TYPE_CHECKING:
    bpy = utils.Dummy()


class S_Dummy(tool_settings.Settings):
    allow_missing_settings = True



## glTF
try:
    from .generated.gltf_settings import S_GLTF
except Exception as e:
    print(e)
    if not typing.TYPE_CHECKING:
        S_GLTF = S_Dummy


def export_gltf(filepath: str, settings: S_GLTF = dict()):

    bpy.context.preferences.use_preferences_save = False
    bpy.ops.preferences.addon_enable(module='io_scene_gltf2')

    os.makedirs(os.path.dirname(filepath), exist_ok = True)

    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter('default')

        bpy.ops.export_scene.gltf(filepath=filepath, **settings)

    print(f"glTF is exported in path: {filepath}")



## fbx
try:
    from .generated.fbx_settings import S_Fbx
except Exception as e:
    print(e)
    if not typing.TYPE_CHECKING:
        S_Fbx = S_Dummy


def export_fbx(filepath: str, settings: S_Fbx = dict()):

    settings = {k: v for k, v in settings._to_dict().items() if not k.startswith('_')}

    if 'object_types' in settings:
        settings['object_types'] = set(settings['object_types'])

    bpy.context.preferences.use_preferences_save = False
    bpy.ops.preferences.addon_enable(module='io_scene_fbx')

    os.makedirs(os.path.dirname(filepath), exist_ok = True)

    bpy.ops.export_scene.fbx(filepath = filepath, **settings)



try:
    from .generated.obj_settings import S_Obj
except Exception as e:
    print(e)
    if not typing.TYPE_CHECKING:
        S_Obj = S_Dummy


def export_obj(filepath: str, settings: S_Obj = dict()):

    bpy.context.preferences.use_preferences_save = False
    bpy.ops.preferences.addon_enable(module='io_scene_obj')

    os.makedirs(os.path.dirname(filepath), exist_ok = True)

    bpy.ops.wm.obj_export(**settings)



## render image
try:
    from .generated.render_settings import S_Image, S_Cycles, S_Eevee, S_Render, S_View
except Exception as e:
    print(e)
    if not typing.TYPE_CHECKING:
        S_Image = S_Cycles = S_Eevee = S_Render = S_View = S_Dummy


FILE_EXTENSION = dict(
    BMP = 'bmp',
    IRIS = 'rgb',
    PNG = 'png',
    JPEG = 'jpg',
    JPEG2000 = 'jp2',
    TARGA = 'tga',
    TARGA_RAW = 'tga',
    CINEON = 'cin',
    DPX = 'dpx',
    OPEN_EXR_MULTILAYER = 'exr',
    OPEN_EXR = 'exr',
    HDR = 'hdr',
    TIFF = 'tif',
    WEBP = 'webp',

    AVI_JPEG = 'avi',
    AVI_RAW = 'avi',
    FFMPEG = 'mp4',
)


def render_image(
        filepath: str,
        *,
        render: S_Render = dict(),
        image: S_Image = dict(),
        view: S_View = dict(),
        cycles: S_Cycles = dict(),
        eevee: S_Eevee = dict(),
    ):

    from . import bpy_context

    with bpy_context.State() as state:

        def apply_settings(target, settings: dict):
            for key, value in settings.items():
                state.set(target, key, value)

        apply_settings(bpy.context.scene.render, render)
        apply_settings(bpy.context.scene.render.image_settings, image)
        apply_settings(bpy.context.scene.view_settings, view)
        apply_settings(bpy.context.scene.cycles, cycles)
        apply_settings(bpy.context.scene.eevee, eevee)

        bpy.ops.render.render()

        os.makedirs(os.path.dirname(filepath), exist_ok = True)

        bpy.data.images['Render Result'].save_render(filepath=filepath)
        print("Image saved:", filepath)
