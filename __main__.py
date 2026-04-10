
def print_orange(*args):

    from . import utils

    utils.print_in_color(utils.get_color_code(242, 125, 12, 18, 18, 18), *args)


def show_external():

    import os
    from . import utils
    from . import root

    utils.os_open(os.path.join(root.PATH, 'external'))


def show_blender():

    from . import utils

    path = utils.get_blender_executable()

    if path is None:
        print("Blender executable is not found.")
    else:
        utils.os_show(path)


def show_logs():

    from . import utils
    from . import updater

    utils.os_open(updater.LOG_DIR)


def show_blend_converter():

    from . import utils
    from . import root

    utils.os_open(root.PATH)


def show_test_blends():

    import os
    from . import utils
    from . import root

    utils.os_open(os.path.join(root.PATH, 'test', 'blend'))


def test_gui():

    import sys
    import os
    import subprocess

    from . import root

    subprocess.Popen([sys.executable, os.path.join(root.PATH, 'test', 'gui.py')])


def generate_settings(blender_executable):

    from .blender.generate_settings import main

    main(blender_executable)


def main():

    import sys

    if len(sys.argv) <= 1:
        print_orange(f"No commands entered.")
        return


    command = sys.argv[1]
    arguments = sys.argv[2:]


    if command == 'show':

        for argument in arguments:

            if argument == 'self':
                show_blend_converter()

            elif argument == 'external':
                show_external()

            elif argument == 'blender':
                show_blender()

            elif argument == 'logs':
                show_logs()

            elif argument == 'blends':
                show_test_blends()

            else:
                print_orange(f"Argument not recognized: {argument}")


    elif command == 'test':

        for argument in arguments:

            if argument == 'gui':
                test_gui()
            else:
                print_orange(f"Argument not recognized: {argument}")

    elif command == 'generate_settings':

        generate_settings(arguments[0])


    else:
        print_orange(f"Command not recognized: {command}")



if __name__ == '__main__':
    main()
