
if __spec__.name == __name__:
    from blend_converter.blender.formats.dummy.export_dummy import export_dummy
else:
    from .export_dummy import export_dummy
