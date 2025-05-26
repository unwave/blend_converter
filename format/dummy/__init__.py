from .. import common
from . import export_dummy


class Dummy(common.Generic_Exporter):
    """ Does not export a file. """

    _file_extension = 'dummy'


    @property
    def needs_update(self):

        settings = self.get_json()

        if settings.get('blend_stat') != common.get_file_stat(self.blend_path):
            return True

        if settings.get('blender_executable_stat') != common.get_file_stat(self.blender_executable):
            return True

        if settings.get('scripts') != self._get_scripts():
            return True

        return False


    def _get_scripts(self):
        return self.scripts
