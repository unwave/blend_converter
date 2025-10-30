import typing

from .. import common
from . import export_blend
from ... import tool_settings


if typing.TYPE_CHECKING:
    import dataclasses
else:
    class dataclasses:
        dataclass = lambda x: x


@dataclasses.dataclass
class Settings_Blend(tool_settings.Settings):


    compress: bool
    """
    Compress, Write compressed .blend file.

    #### Default: `False`
    """

    relative_remap: bool
    """
    Remap Relative, Remap relative paths when saving to a different directory.

    #### Default: `True`
    """

    copy: bool
    """
    Save Copy, Save a copy of the actual working state but does not make saved file active.

    #### Default: `False`
    """


class Blend(common.Generic_Exporter):

    _file_extension = 'blend'
    settings: Settings_Blend


    def __init__(self, source_path: str, result_dir: str, **kwargs):
        super().__init__(source_path, result_dir, **kwargs)

        self.settings = Settings_Blend()


    def get_export_script(self):
        return self._get_function_script(export_blend.export_blend, dict(filepath = self.result_path, **self.settings._to_dict()))
