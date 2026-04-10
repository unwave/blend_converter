import os


PATH = os.path.dirname(os.path.realpath(__file__))


def get_script_path(name: str):
    return os.path.join(PATH, 'script', f'{name}.py')


def get_blender_script_path(name: str):
    return os.path.join(PATH, 'blender', 'scripts', f'{name}.py')
