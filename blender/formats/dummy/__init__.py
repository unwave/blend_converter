from .. import common
from . import export_dummy


class Dummy(common.Generic_Exporter):
    """ Does not export a file. """

    _file_extension = 'dummy'


    def get_current_stats(self):

        stats = {}

        stats['blend_stat'] = common.get_file_stat(self.blend_path)

        stats['blender_executable_stat'] = common.get_file_stat(self.blender_executable)

        stats['scripts'] = self._get_scripts()

        return stats


    def get_json_stats(self):

        info = self.get_json()

        stats = {}

        stats['blend_stat'] = info.get('blend_stat')

        stats['blender_executable_stat'] = info.get('blender_executable_stat')

        stats['scripts'] = info.get('scripts')

        return stats


    def _get_scripts(self):
        return self.scripts
