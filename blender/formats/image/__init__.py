import typing
import os


if __spec__.name == __name__:
    from blend_converter.blender.formats.image.export_image import export_image
else:
    from .export_image import export_image


DIR = os.path.dirname(os.path.realpath(__file__))


if not os.path.exists(os.path.join(DIR, '_generated.py')):

    if __spec__.name == __name__:
        from blend_converter.blender.formats.image._generated import S_Image, S_Cycles, S_Eevee, S_Render, S_View
    else:
        from ._generated import S_Image, S_Cycles, S_Eevee, S_Render, S_View

elif not typing.TYPE_CHECKING:

    if __spec__.name == __name__:
        from blend_converter import tool_settings
    else:
        from .... import tool_settings

    class S_Fake(tool_settings.Settings):

        allow_missing_settings = True

    S_Image = S_Cycles = S_Eevee = S_Render = S_View = S_Fake



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
