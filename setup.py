import setuptools

setuptools.setup(
    name="blend_converter",
    version='0.0.1',
    description="Lazy evaluated blend file converter handlers.",
    install_requires = [
        'panda3d-gltf',
        'dill'
    ],
    packages = ['blend_converter', 'blend_converter.scripts'],
    package_dir = {'blend_converter': '.',},
    python_requires='>=3.7',
)