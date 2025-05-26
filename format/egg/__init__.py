import typing
import os

from . import common
from . import utils

DIR = os.path.dirname(__file__)
BLENDER_EXPORT_YABEE = os.path.join(DIR, 'scripts', 'blender_export_yabee.py')

# BLENDER_EXPORT_YABEE = os.path.join(DIR, 'blend2egg', 'blender_export_yabee.py')


class Settings_YABEE(common.Settings):
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


class Egg(common.Blend):
    """ Lazy evaluated `.blend` to `.egg` handler """

    _file_extension = 'egg'

    def __init__(self, blend_path: str, target_dir: str):
        """
        Parameters
        ----------
        blend_path: `.blend` file path

        target_dir: directory where `.egg` files will be placed
        """

        super().__init__(blend_path, target_dir)

        self.settings_yabee = Settings_YABEE()
        """ `yabee_libs.egg_writer.write_out`'s settings """

        self._args_pre = []
        self._args_post = []

    @property
    def args_pre(self):
        """ Blender's command line arguments before the export script """
        return self._unwrap_args(self._args_pre)

    @property
    def args_post(self):
        """ Blender's command line arguments after the export script """
        return self._unwrap_args(self._args_post)


    def attach_pre_script(self, func: typing.Callable, *args, **kwargs):
        """
        The scrip will be executed before the `.egg` export.

        By default:
        `func` must not use the scope where it was declared, as it will be evaluated in isolation.
        `args` and `kwargs` must be JSON serializable.
        Set `script.use_dill = True` to use `uqfoundation/dill` to bypass that.
        """

        script = common.Script(func, args, kwargs)
        self._args_pre.append(script)

        return script

    def attach_post_script(self, func: typing.Callable, *args, **kwargs):
        """
        The scrip will be executed after the `.egg` export.

        By default:
        `func` must not use the scope where it was declared, as it will be evaluated in isolation.
        `args` and `kwargs` must be JSON serializable.
        Set `script.use_dill = True` to use `uqfoundation/dill` to bypass that.
        """

        script = common.Script(func, args, kwargs)
        self._args_post.append(script)

        return script

    @property
    def needs_update(self):

        if not os.path.exists(self.os_path_target):
            return True

        settings = self.file_settings

        if settings.get('blend_stat') != self._get_blend_stat():
            return True

        if settings.get('settings_yabee') != self.settings_yabee._dict:
            return True

        if settings.get('args_pre') != self.args_pre:
            return True
        
        if settings.get('args_post') != self.args_post:
            return True

        return False

    def _get_job_yabee(self):
        job = self.settings_yabee._dict
        job['fname'] = self.os_path_target
        return job

    def _get_yabee_commands(self):
        return [
            self.blend_path,

            '--python-expr',
            self._get_job_expr(self._get_job_yabee()),

            *self.args_pre,

            '--python',
            BLENDER_EXPORT_YABEE,

            *self.args_post,
        ]

    def _write_json(self):
        super()._write_json({
            'settings_yabee': self.settings_yabee._dict,
            'args_pre': self.args_pre,
            'args_post': self.args_post,
        })

    def update(self, forced = False):

        if not (self.needs_update or forced):
            return

        os.makedirs(os.path.dirname(self.os_path_target), exist_ok = True)

        utils.run_blender(self._get_yabee_commands(), stdout = self.blender_stdout, blender_binary = self.blender_binary)

        self._write_json()

