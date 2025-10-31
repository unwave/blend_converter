import typing


if __spec__.name == __name__:
    from blend_converter.blender.formats.egg.export_egg import export_egg
    from blend_converter import tool_settings
else:
    from .export_egg import export_egg
    from .... import tool_settings



if typing.TYPE_CHECKING:
    import dataclasses
else:
    class dataclasses:
        dataclass = lambda x: x


@dataclasses.dataclass
class Settings_YABEE(tool_settings.Settings):
    """
    `yabee_libs.egg_writer.write_out`'s settings
    """

    anims = {}
    """
    A dictionary that specify how the Timeline's animation data will be split in to separate animations.

    ```python
    {"name": {"from_frame": 1, "to_frame": 2, "from_frame": 24}}
    ```

    If `from_frame` and `to_frame` has the same value YABEE will automatically add one frame to `to_frame`.

    #### Default: `{}`
    """

    from_actions = False
    """
    Export an animation for every Action

    #### Default: `False`
    """

    uv_img_as_tex = False
    """
    export uv image as texture

    #### Default: `False`
    """

    sep_anim = True
    """
    Write an animation data into the separate files

    #### Default: `True`
    """

    a_only = False
    """
    Write only animation data

    #### Default: `False`
    """

    copy_tex= True
    """
    Copy texture files together with EGG

    #### Default: `True`
    """

    t_path = './tex'
    """
    Path for the copied textures. Relative to the main EGG file dir

    #### Default: `./tex`
    """

    tbs = 'BLENDER'
    """
    Export all textures as MODULATE or bake texture layers

    * `PANDA`: Use egg-trans to calculate TBS (Need installed Panda3D)
    * `BLENDER`: Use Blender to calculate TBS
    * `NO`: Do not generate TBS

    #### Default: `BLENDER`
    """

    autoselect = True
    """
    Automatically select all objects in the scene

    #### Default: `True`
    """

    apply_obj_transform = False
    """
    Apply object transform as default

    #### Default: `False`
    """

    m_actor = False
    """
    Merge meshes, armatured by single Armature

    #### Default: `False`
    """

    apply_m = True
    """
    Apply modifiers on exported objects (except Armature)

    #### Default: `True`
    """

    apply_coll_tag = False
    """
    Add Collide tag on exported objects

    #### Default: `False`
    """

    apply_pin_tag = False
    """
    Add Pin tag on exported objects. Required for soft bodies

    #### Default: `False`
    """

    rp_compat = False
    """
    Enable compatibility with RenderPipeline

    #### Default: `False`
    """

    pview = False
    """
    Run pview after exporting

    #### Default: `False`
    """

    loop_normals = False
    """
    Use loop normals created by applying 'Normal Edit' Modifier as vertex normals.

    #### Default: `False`
    """

    force_export_vertex_colors = False
    """
    when False, writes only vertex color if polygon material is using it

    #### Default: `False`
    """
