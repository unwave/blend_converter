import os

from . import common
from . import utils

class Settings_Obj(common.Settings):
    """ The built-in C based Wavefront OBJ exporter. """

    filepath: str
    """
    File Path

    Path to file

    #### Required.
    Subtype: `FILEPATH`

    #### Default: `''`
    """

    export_animation: bool
    """
    Export Animation

    Export multiple frames instead of the current frame only


    #### Default: `False`
    """

    start_frame: int
    """
    Start Frame

    The first frame to be exported

    #### Default: `-2147483648`
    """

    end_frame: int
    """
    End Frame

    The last frame to be exported

    #### Default: `2147483647`
    """

    forward_axis: str
    """
    Forward Axis

    Options:
    * `X_FORWARD`: X, Positive X axis
    * `Y_FORWARD`: Y, Positive Y axis
    * `Z_FORWARD`: Z, Positive Z axis
    * `NEGATIVE_X_FORWARD`: -X, Negative X axis
    * `NEGATIVE_Y_FORWARD`: -Y, Negative Y axis
    * `NEGATIVE_Z_FORWARD`: -Z (Default), Negative Z axis


    #### Default: `'NEGATIVE_Z_FORWARD'`
    """

    up_axis: str
    """
    Up Axis

    Options:
    * `X_UP`: X, Positive X axis
    * `Y_UP`: Y (Default), Positive Y axis
    * `Z_UP`: Z, Positive Z axis
    * `NEGATIVE_X_UP`: -X, Negative X axis
    * `NEGATIVE_Y_UP`: -Y, Negative Y axis
    * `NEGATIVE_Z_UP`: -Z, Negative Z axis


    #### Default: `'Y_UP'`
    """

    scaling_factor: float
    """
    Scale

    Upscale the object by this factor

    Hard Min: `0.001`
    Hard Max: `10000.0`
    Soft Min: `0.01`
    Soft Max: `1000.0`


    #### Default: `1.0`
    """

    apply_modifiers: bool
    """
    Apply Modifiers

    Apply modifiers to exported meshes


    #### Default: `True`
    """

    export_eval_mode: str
    """
    Object Properties

    Determines properties like object visibility, modifiers etc., where they differ for Render and Viewport

    Options:
    * `DAG_EVAL_RENDER`: Render, Export objects as they appear in render
    * `DAG_EVAL_VIEWPORT`: Viewport (Default), Export objects as they appear in the viewport


    #### Default: `'DAG_EVAL_VIEWPORT'`
    """

    export_selected_objects: bool
    """
    Export Selected Objects

    Export only selected objects instead of all supported objects


    #### Default: `False`
    """

    export_uv: bool
    """
    Export UVs


    #### Default: `True`
    """

    export_normals: bool
    """
    Export Normals

    Export per-face normals if the face is flat-shaded, per-face-per-loop normals if smooth-shaded


    #### Default: `True`
    """

    export_materials: bool
    """
    Export Materials

    Export MTL library. There must be a Principled-BSDF node for image textures to be exported to the MTL file


    #### Default: `True`
    """

    export_triangulated_mesh: bool
    """
    Export Triangulated Mesh

    All ngons with four or more vertices will be triangulated. Meshes in the scene will not be affected. Behaves like Triangulate Modifier with ngon-method: "Beauty", quad-method: "Shortest Diagonal", min vertices: 4


    #### Default: `False`
    """

    export_curves_as_nurbs: bool
    """
    Export Curves as NURBS

    Export curves in parametric form instead of exporting as mesh


    #### Default: `False`
    """

    export_object_groups: bool
    """
    Export Object Groups

    Append mesh name to object name, separated by a '_'


    #### Default: `False`
    """

    export_material_groups: bool
    """
    Export Material Groups

    Generate an OBJ group for each part of a geometry using a different material


    #### Default: `False`
    """

    export_vertex_groups: bool
    """
    Export Vertex Groups

    Export the name of the vertex group of a face. It is approximated by choosing the vertex group with the most members among the vertices of a face


    #### Default: `False`
    """

    export_smooth_groups: bool
    """
    Export Smooth Groups

    Every smooth-shaded face is assigned group "1" and every flat-shaded face "off"


    #### Default: `False`
    """

    smooth_group_bitflags: bool
    """
    Generate Bitflags for Smooth Groups


    #### Default: `False`
    """


def export():
    import bpy

    settings = get_job() # type: ignore

    bpy.ops.wm.obj_export(**settings) 

class Obj(common.Blend, common.Pre_Post_Args_Mixin):

    _file_extension = 'obj'

    def __init__(self, blend_path: str, target_dir: str):
        """
        Parameters
        ----------
        blend_path: `.blend` file path

        target_dir: directory where `.obj` files will be placed
        """

        common.Blend.__init__(self, blend_path, target_dir)
        common.Pre_Post_Args_Mixin.__init__(self)

        self.settings = Settings_Obj()
        """ Official Blender Built-In OBJ Exporter"""


    def _write_json(self):
        super()._write_json({
            'settings': self._set_to_list(self.settings._dict),
            'args_pre': self.args_pre,
            'args_post': self.args_post,
        })

    def _set_to_list(self, settings: dict):
        for key, value in settings.items():
            if type(value) is set:
                settings[key] = list(value)
        return settings

    @property
    def needs_update(self):

        if not os.path.exists(self.os_path_target):
            return True

        settings = self.file_settings

        if settings.get('blend_stat') != self._get_blend_stat():
            return True

        if settings.get('settings') != self._set_to_list(self.settings._dict):
            return True

        if settings.get('args_pre') != self.args_pre:
            return True
        
        if settings.get('args_post') != self.args_post:
            return True

        return False

    def _get_job(self):
        job = self.settings._dict
        job['filepath'] = self.os_path_target
        return job

    def _get_commands(self):
        
        return [
            self.blend_path,

            '--python-expr',
            self._get_job_expr(self._get_job()),

            *self.args_pre,

            '--python-expr',
            utils.get_expr(export),

            *self.args_post,
        ]

    def update(self, forced = False):
        if self.needs_update or forced:
            utils.run_blender(self._get_commands(), stdout = self.blender_stdout, blender_binary = self.blender_binary)
            self._write_json()
