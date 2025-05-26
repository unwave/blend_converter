import typing
import time

import bpy

ADDON_NAME = 'blend_converter'
ADDON_CLASS_PREFIX = ADDON_NAME.replace('_', '').upper()
BL_CATEGORY = 'BC'


DEBUG = False
"""
Raise error on CANCELLED in all operators.
```
if DEBUG: raise Exception(message)
return {'CANCELLED'}
```
"""

from . import addon_register


class BC_Register(addon_register.Addon_Register):

    def get_addon_modules(self) -> typing.List[str]:

        modules = [
            'operator_factory',
            'view3d_ui',
            'view3d_operator',
            'misc_tools',
        ]

        return [__package__ + '.' + module for module in modules]
    
    def reload(self):

        self.unregister()
        self.reload_modules()
        self.register()



class _OT_reload_addon(bpy.types.Operator):
    bl_idname = f"wm.{ADDON_NAME}_reload_addon"
    bl_label = f"Reload {ADDON_NAME}"

    def execute(self, context):

        start = time.perf_counter()

        reg.reload()

        from .. import utils
        utils.reload_library()

        reload_time = time.perf_counter() - start
        self.report({'INFO'}, f"{ADDON_NAME} has been reloaded in {reload_time:.2f} sec.")

        return {'FINISHED'}



reg = BC_Register(ADDON_CLASS_PREFIX)


def register():

    import bpy
    
    bpy.utils.register_class(_OT_reload_addon)
    reg.register()


def unregister():

    import bpy

    reg.unregister()
    bpy.utils.unregister_class(_OT_reload_addon)
