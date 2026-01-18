if __name__ == '__main__':
    from blend_converter.gui import updater_ui
    app = updater_ui.Main_Frame.get_app([(__file__, 'get_programs')])
    app.MainLoop()


def get_programs():

    from blend_converter import utils

    from simple_programs import BLEND_DIRS, get_bake_program

    executable = utils.get_blender_executable()
    if not executable:
        raise Exception(f"Blender executable not found: {repr(executable)}")

    programs = utils.Appendable_Dict()

    for blend_dir in BLEND_DIRS:
        programs.append(get_bake_program(blend_dir, executable))


    return programs
