bl_info = {
    "name" : "blend_converter",
    "author" : "unwave",
    "description" : "",
    "blender" : (2, 83, 0),
    "version" : (0, 0, 1),
    "location" : "",
    "warning" : "",
    "category" : "Generic"
}


def register():
    from . import addon
    addon.register()

def unregister():
    from . import addon
    addon.unregister()
