import sys

if 'bpy' in sys.modules:
    import bpy


def apply_settings(settings_image: dict, settings_render: dict, settings_cycles: dict, settings_eevee: dict, settings_view: dict):

    for key, value in settings_image.items():
        setattr(bpy.context.scene.render.image_settings, key, value)

    for key, value in settings_render.items():
        setattr(bpy.context.scene.render, key, value)

    for key, value in settings_cycles.items():
        setattr(bpy.context.scene.cycles, key, value)

    for key, value in settings_eevee.items():
        setattr(bpy.context.scene.eevee, key, value)

    for key, value in settings_view.items():
        setattr(bpy.context.scene.view_settings, key, value)


def export_image(filepath, **kwargs):

    apply_settings(**kwargs)

    bpy.ops.render.render()

    bpy.data.images['Render Result'].save_render(filepath=filepath)
    print("Image saved:", filepath)
