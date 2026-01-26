import bpy

from . import _OT_reload_addon
from . import view3d_operator


class BLENDCONVERTER_PT_tools(bpy.types.Panel):
    bl_idname = "BLENDCONVERTER_PT_tools"
    bl_label = "TEST"
    bl_category = "BC"
    bl_space_type = 'VIEW_3D'
    bl_region_type = "UI"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):

        column = self.layout.column()

        column.label(text='Join and Bake')

        column.operator(view3d_operator.BLENDCONVERTER_OT_export_and_inspect.bl_idname, text="Blender").viewer_type = 'BLENDER'
        column.operator(view3d_operator.BLENDCONVERTER_OT_export_and_inspect.bl_idname, text="Panda3D").viewer_type = 'PANDA'

        op = column.operator(view3d_operator.BLENDCONVERTER_OT_export_and_inspect.bl_idname, text="Bullet", icon='PLAY')
        op.viewer_type = 'PANDA'
        op.bullet_physics = True

        column.separator()
        column.operator(_OT_reload_addon.bl_idname)


class BLENDCONVERTER_PT_bake_settings(bpy.types.Panel):
    bl_idname = "BLENDCONVERTER_PT_bake_settings"
    bl_label = "Bake Settings"
    bl_category = "BC"
    bl_space_type = 'VIEW_3D'
    bl_region_type = "UI"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):

        column = self.layout.column()

        blend_converter_bake_settings = context.window_manager.blend_converter_bake_settings

        for name in blend_converter_bake_settings.__annotations__:
            column.prop(blend_converter_bake_settings, name)
