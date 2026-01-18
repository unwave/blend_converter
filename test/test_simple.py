import pytest


from simple_programs import BLEND_DIRS, get_bake_program


@pytest.mark.parametrize('blend_dir', BLEND_DIRS)
def test_copy_and_bake_gltf(blend_dir, blender_executable):
    """ this test is not meant for evaluating the quality of the results, just for code being executed without errors """

    get_bake_program(blend_dir, blender_executable).execute()
