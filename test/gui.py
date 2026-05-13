from simple_programs import get_bake_program


def main():

    from blend_converter.gui import updater_ui
    from blend_converter import common

    app = updater_ui.Main_Frame.get_app([common.Program_Definition.from_callable(get_bake_program, get_keyword_arguments)])

    import psutil
    cpu_count = psutil.cpu_count(logical=False)

    app.main_frame.updater.total_max_parallel_executions = cpu_count
    app.main_frame.updater.default_max_parallel_executions = cpu_count

    app.MainLoop()


def get_keyword_arguments():

    from blend_converter import utils

    from simple_programs import BLEND_DIRS

    executable = utils.get_blender_executable()
    if not executable:
        raise Exception(f"Blender executable not found: {repr(executable)}")

    return [dict(blend_dir = blend_dir, blender_executable = executable) for blend_dir in BLEND_DIRS]


if __name__ == '__main__':
    main()
