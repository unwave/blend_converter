import typing


if __spec__.name == __name__:
    from blend_converter.blender.formats.image.export_image import export_image
    from blend_converter.blender.formats.image._generated import Settings_Image, Settings_Cycles, Settings_Eevee, Settings_Render, Settings_View
else:
    from .export_image import export_image
    from ._generated import Settings_Image, Settings_Cycles, Settings_Eevee, Settings_Render, Settings_View



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
