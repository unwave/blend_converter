if __name__ == '__main__':
    from blend_converter.gui import updater_ui
    app = updater_ui.Main_Frame.get_app([(__file__, 'get_bake_program', 'get_keyword_arguments')])
    app.MainLoop()


from simple_programs import get_bake_program


def get_keyword_arguments():

    from blend_converter import utils

    from simple_programs import BLEND_DIRS

    executable = utils.get_blender_executable()
    if not executable:
        raise Exception(f"Blender executable not found: {repr(executable)}")

    return [dict(blend_dir = blend_dir, blender_executable = executable) for blend_dir in BLEND_DIRS]
