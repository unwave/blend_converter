import typing
import os
import sys
import subprocess

import setuptools
from pathspec import GitIgnoreSpec


DIR = os.path.dirname(__file__)


def get_files_pathspec(root: str):

    included_files: typing.List[str] = []
    excluded_files: typing.List[str] = []


    def read_file(path: str):
        with open(path) as f:
            return f.read().splitlines()


    def traverse(path: str, specs: list = None):

        if specs is None:
            specs: typing.List[GitIgnoreSpec] = []
        else:
            specs = specs.copy()

        for file in os.scandir(path):

            if file.name == '.gitignore':
                specs.append(GitIgnoreSpec.from_lines(read_file(file.path)))

        for file in os.scandir(path):

            if file.name == '.git':
                continue

            if file.is_dir():
                traverse(file.path, specs)
                continue

            if any(spec.match_file(file.path) for spec in specs):
                excluded_files.append(file.path)
            else:
                included_files.append(file.path)


    traverse(root)

    return included_files, excluded_files


def get_git_ignored_files(root: str):

    result = subprocess.run(
        [
            'git',
            'ls-files',
            '--ignored',
            '--exclude-standard',
            '--others',
            '--full-name',
            '-z',
        ],
        stdout = subprocess.PIPE,
        check = True,
        text = True,
        encoding = 'utf-8',
        cwd = root
    )

    ignored_files = result.stdout.split('\0') if result.stdout else []
    ignored_files = [os.path.realpath(os.path.join(root, file)) for file in ignored_files]
    ignored_files.append(os.path.realpath(os.path.join(root, '.git')))

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


def get_files_git(root: str):

    ignored_files = get_git_ignored_files(root)


    def filter_func(entry: os.DirEntry):
        return not os.path.realpath(entry.path) in ignored_files


    included_files = [file.path for file in get_files(root, filter_func) if file.is_file()]
    excluded_files = [file for file in ignored_files if os.path.isfile(file)]

    return included_files, excluded_files



included_files, excluded_files = get_files_pathspec(DIR)

try:
    included_files_git, excluded_files_git = get_files_git(DIR)
except (subprocess.SubprocessError, FileNotFoundError) as e:
    print(e)
else:
    if set(included_files) != set(included_files_git):
        raise Exception(f"Included files mismatch: {set(included_files).symmetric_difference(included_files_git)}")

    if  set(excluded_files) != set(excluded_files_git):
        raise Exception(f"Excluded files mismatch: {set(excluded_files).symmetric_difference(excluded_files_git)}")



package_data = {'': [os.path.relpath(os.path.realpath(path), DIR) for path in included_files]}
exclude_package_data = {'': [os.path.relpath(os.path.realpath(path), DIR) for path in excluded_files]}


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
# all files are specified by .gitignore

# if git is present, happens during the sdist build, it will check pathspec against git ls-files
# can use --no-isolation to also do it when building the wheel

# FIXME: there are duplicates in SOURCES.txt


## sdist
# py -m build --sdist

## wheel
# py -m build --wheel

## wheel + git check
# py -m build --wheel --no-isolation

## both
# py -m build


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
