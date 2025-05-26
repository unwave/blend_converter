import typing

if typing.TYPE_CHECKING:
    import pytest


def pytest_addoption(parser: 'pytest.Parser'):
    parser.addoption("--bpath", help='Blender path.', default = 'blender')


def pytest_generate_tests(metafunc: 'pytest.Metafunc'):
    bpath = metafunc.config.getoption('bpath')
    import shutil
    metafunc.parametrize('blender_executable', [shutil.which(bpath)])
