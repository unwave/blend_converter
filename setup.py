import os
import typing
import subprocess

DIR = os.path.dirname(os.path.realpath(__file__))


def get_git_ignored_files():


    result = subprocess.run(
        [
            'git',
            'ls-files',
            '--ignored',
            '--exclude-standard',
            '--others',
            '--full-name',
            '--directory',
            '-z',
        ],
        stdout = subprocess.PIPE,
        check = True,
        text = True,
        encoding = 'utf-8',
        cwd = DIR
    )

    ignored_files = result.stdout.split('\0') if result.stdout else []
    ignored_files = [os.path.realpath(os.path.join(DIR, file)) for file in ignored_files]
    ignored_files.append(os.path.realpath(os.path.join(DIR, '.git')))

    return list(dict.fromkeys(ignored_files))


def get_files(path, filter_func: typing.Callable[[os.DirEntry], bool], recursively = True) -> typing.List[os.DirEntry]:

    files = []

    for file in os.scandir(path):

        if not filter_func(file):
            continue

        files.append(file)

        if recursively and file.is_dir():
            files.extend(get_files(file.path, filter_func, recursively))

    return files


def get_git_files():

    ignored_files = get_git_ignored_files()


    def filter_func(entry: os.DirEntry):
        return not os.path.realpath(entry.path) in ignored_files


    included_files = [file.path for file in get_files(DIR, filter_func) if file.is_file()]
    excluded_files = [file for file in ignored_files if os.path.isfile(file)]

    package_data = {'': [os.path.relpath(os.path.realpath(path), DIR) for path in included_files]}
    exclude_package_data = {'': [os.path.relpath(os.path.realpath(path), DIR) for path in excluded_files]}

    return package_data, exclude_package_data


package_data, exclude_package_data = get_git_files()


import sys

if '__test__' in sys.argv:

    print('#' * 80)
    print("Include:")
    print()

    for key, value in package_data.items():
        print(key)
        for x in value:
            print('\t', x)

    print()

    print('#' * 80)
    print("Exclude:")
    print()

    for key, value in exclude_package_data.items():
        print(key)
        for x in value:
            print('\t', x)

    raise SystemExit(0)



## super-flat-layout

# sdist and wheel files are identical
# all files are specified by git

## to get sdist use
# py -m build --sdist
# FIXME: there duplicates in SOURCES.txt
# TODO: currently it not possible to build from sdist without the .git and a git client

## to get wheel use
# py -m build --wheel --no-isolation
# TODO: --no-isolation is because .git is needed


import setuptools

setuptools.setup(

    python_requires = '>=3.7',

    name = "blend_converter",
    url = "https://github.com/unwave/blend_converter",
    version = '0.0.1',
    description = "Blender's data conversion",
    author = "unwave",

    install_requires = [
        'wxpython',
        'psutil',
        'watchdog',
        'pyperclip',
    ],

    package_dir = {'blend_converter': '.'},
    packages = ['blend_converter'],

    include_package_data = False,

    package_data = package_data,
    exclude_package_data = exclude_package_data,

)
