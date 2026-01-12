if __name__ == '__main__':
    from blend_converter.gui import updater_ui
    app = updater_ui.Main_Frame.get_app([(__file__, 'get_programs')])
    app.MainLoop()


def get_programs():

    from blend_converter import utils

    from test_simple import BLEND_DIRS, get_program_1, get_program_2

    executable = utils.get_blender_executable()
    if not executable:
        raise Exception(f"Blender executable not found: {repr(executable)}")

    programs = utils.Appendable_Dict()

    for blend_dir in BLEND_DIRS:
        programs.append(get_program_1(blend_dir, executable))


    for blend_dir in BLEND_DIRS:
        programs.append(get_program_2(blend_dir, executable))


    return programs
