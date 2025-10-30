import typing

from .. import common

from . import export_image
from . import _generated


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


class Image(common.Generic_Exporter):


    @property
    def _file_extension(self):
        return FILE_EXTENSION[self.settings_image.file_format]


    def __init__(self, source_path: str, result_dir: str, **kwargs):
        super().__init__(source_path, result_dir, **kwargs)

        self.settings_image = _generated.Settings_Image()
        self.settings_render = _generated.Settings_Render()
        self.settings_cycles = _generated.Settings_Cycles()
        self.settings_eevee = _generated.Settings_Eevee()
        self.settings_view = _generated.Settings_View()


    def get_export_script(self):
        return self._get_function_script(
            export_image.export_image,
            **dict(
                filepath = self.result_path,
                settings_image = self.settings_image,
                settings_render = self.settings_render,
                settings_cycles = self.settings_cycles,
                settings_eevee = self.settings_eevee,
                settings_view = self.settings_view,
            )
        )
