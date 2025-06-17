import typing
import os
import tempfile
import subprocess

import bmesh
import bpy
import bpy_extras

from . import operator_factory
from .. import bpy_utils
from .. import utils
from .. import tool_settings
from .. import bpy_node
from .. import bpy_context
from .. import bpy_uv


operator_factory.Operator_Class_Base.bl_options = {'REGISTER', 'UNDO'}

view_3d_poll = classmethod(lambda cls, context: context.space_data.type == 'VIEW_3D')
edit_mode_poll = classmethod(lambda cls, context: context.space_data.type == 'VIEW_3D' and context.mode == 'EDIT_MESH')
object_mode_poll = classmethod(lambda cls, context: context.space_data.type == 'VIEW_3D' and context.mode == 'OBJECT')



@operator_factory.operator()
def convert_to_pbr(self, context):

    material = bpy.context.object.active_material

    if not (material and material.node_tree):
        return "No active material."

    tree = bpy_node.Shader_Tree_Wrapper(material.node_tree)

    tree.convert_to_pbr()


@operator_factory.operator(
    poll = edit_mode_poll,
    __annotations__ = dict(
        resolution = bpy.props.IntVectorProperty(default=(1024,1024), size=2, min=1)
    ),
    invoke = lambda operator, context, event: bpy.data.window_managers[0].invoke_props_dialog(operator, width=400)
)
def ensure_pixel_per_island(operator: bpy.types.Operator, context: bpy.types.Context):
    from .. import bpy_uv
    bpy_uv._ensure_pixel_per_island(context.selected_objects, operator.resolution[0], operator.resolution[1])


@operator_factory.operator(
    poll = edit_mode_poll
)
def top_project_uv(operator: bpy.types.Operator, context: bpy.types.Context):

    object = context.active_object
    mesh = object.data
    b_mesh = bmesh.from_edit_mesh(mesh)

    uv_layer = b_mesh.loops.layers.uv.verify()

    for face in b_mesh.faces:
        for loop in face.loops:
            loop_uv = loop[uv_layer]
            loop_uv.uv = loop.vert.co.xy

    bmesh.update_edit_mesh(mesh)


@operator_factory.operator(
    poll = object_mode_poll
)
def mesh_linked_triangles(operator: bpy.types.Operator, context: bpy.types.Context):

    islands = bpy_extras.mesh_utils.mesh_linked_uv_islands(context.object.data)

    print(islands)

    print(bpy_extras.__file__)


@operator_factory.operator(
    poll = edit_mode_poll
)
def print_selected_uv_verts(operator: bpy.types.Operator, context: bpy.types.Context):

    obj = bpy.context.active_object
    bm = bmesh.from_edit_mesh(obj.data)
    uv_layer = bm.loops.layers.uv.verify()
    sel_faces = (f for f in bm.faces if f.select)

    def find_loops():
        """Generator, yields loops of selected mesh faces"""

        for f in sel_faces:
            for l in f.loops:
                yield l

    def find_selected_loops():
        """Generator, yields loops that are selected in UV editor"""

        for l in find_loops():
            if l[uv_layer].select and l.link_loop_next[uv_layer].select:
                yield l

    # Show the coordinates of selected loops. Note that loops are printed
    # twice, once for the (A -> B) edge, and once for the (B -> A) edge.
    print()
    for l in find_selected_loops():
        print(l.vert.co, ' -> ', l.link_loop_next.vert.co)


@operator_factory.operator()
def copy_selected_objects_names(operator: bpy.types.Operator, context: bpy.types.Context):

    names = []

    for object in bpy.context.selected_objects:
        names.append((object.name, object.library.filepath if object.library else None))

    import pyperclip
    pyperclip.copy(repr(names))


@operator_factory.operator()
def copy_blend_path(operator: bpy.types.Operator, context: bpy.types.Context):

    import pyperclip
    pyperclip.copy(f"r'{bpy.data.filepath}'")


def run_in_area(context: bpy.types.Context, func, *args, **kwargs):
    override = dict(
        window=context.window,
        workspace=context.window.workspace,
        screen=context.window.screen,
        area=context.area,
        region=context.region
    )
    return bpy_context.call_with_override(override, func, *args, **kwargs)


@operator_factory.operator(
    __annotations__ = dict(
        reset_render_settings = bpy.props.BoolProperty()
    ),
)
def reveal_all(operator: bpy.types.Operator, context: bpy.types.Context):

    if context.area.type == 'VIEW_3D' and context.area.spaces.active.local_view:
        run_in_area(context, bpy.ops.view3d.localview)

    main_collection = bpy.context.view_layer.layer_collection.collection

    linked_objects = set()
    linked_collections = set()

    def unhide_layer_collection(layer_collection: bpy.types.LayerCollection):

        layer_collection.exclude = False
        layer_collection.hide_viewport = False

        layer_collection.collection.hide_select = False
        layer_collection.collection.hide_viewport = False

        if operator.reset_render_settings:
            layer_collection.collection.hide_render = False
            layer_collection.holdout = False
            layer_collection.indirect_only = False

        linked_collections.add(layer_collection.collection)
        linked_objects.update(layer_collection.collection.all_objects)

        for child in layer_collection.children:
            unhide_layer_collection(child)

    unhide_layer_collection(bpy.context.view_layer.layer_collection)


    default_collection_name = '__unlinked__'

    default_collection = bpy.data.collections.get(default_collection_name)
    if default_collection is None:
        default_collection = bpy.data.collections.new(default_collection_name)

    if not default_collection in set(main_collection.children):
        main_collection.children.link(default_collection)

    linked_collections.add(default_collection)

    for object in bpy.data.objects:

        object.hide_set(False)

        object.hide_viewport = False
        object.hide_select = False

        if operator.reset_render_settings:
            object.hide_render = False
            object.is_shadow_catcher = False
            object.is_holdout = False

            object.visible_camera = True
            object.visible_diffuse = True
            object.visible_glossy = True
            object.visible_transmission = True
            object.visible_volume_scatter = True
            object.visible_shadow = True

        if not object in linked_objects:
            default_collection.objects.link(object)

    for collection in bpy.data.collections:
        collection.hide_select = False
        collection.hide_viewport = False

        if operator.reset_render_settings:
            collection.hide_render = False

        if not collection in linked_collections:
            default_collection.children.link(collection)

    for window_manager in bpy.data.window_managers:
        for window in window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'VIEW_3D':
                    area.spaces.active.overlay.show_outline_selected = True

    bpy.ops.object.mode_set(mode='OBJECT')


def get_visible_objects(context: bpy.types.Context) -> typing.List[bpy.types.Object]:
    return [object for object in context.view_layer.layer_collection.collection.all_objects if object.visible_get()]


@operator_factory.operator(
    poll = object_mode_poll,
    __annotations__ = dict(
        decrement = bpy.props.BoolProperty(),
        focus = bpy.props.BoolProperty(default=True),
    ),
)
def iter_object(operator: bpy.types.Operator, context: bpy.types.Context):

    all_objects = get_visible_objects(context)

    object = context.object
    if object is None:
        object_to_focus = all_objects[0]
        index = 0
    else:
        index = all_objects.index(object) + (-1 if operator.decrement else 1)
        if index >= len(all_objects):
            index = 0
        elif index < 0:
            index = len(all_objects) - 1

        object_to_focus = all_objects[index]


    bpy_utils.focus(object_to_focus)
    if operator.focus:
        run_in_area(context, bpy.ops.view3d.view_selected)

    operator.report({'INFO'}, f"Object: {object_to_focus.name} [{index + 1}/{len(all_objects)}]")


@operator_factory.operator(
    poll = object_mode_poll,
    __annotations__ = dict(
        decrement = bpy.props.BoolProperty(),
        focus = bpy.props.BoolProperty(default=True),
    ),
)
def iter_material(operator: bpy.types.Operator, context: bpy.types.Context):

    all_objects = get_visible_objects(context)

    material_to_object = {}

    for object in all_objects:

        if not hasattr(object, 'material_slots'):
            continue

        for material_slot in object.material_slots:

            if material_slot.material is None:
                continue

            material_to_object.setdefault(material_slot.material, []).append(object)

    index_to_material = list(material_to_object.keys())

    active_object = bpy.context.object
    if not hasattr(active_object, 'active_material') or not any(active_object in objects for objects in material_to_object.values()):
        material_to_select = index_to_material[0]
        index = 0
    else:
        index = index_to_material.index(active_object.active_material) + (-1 if operator.decrement else 1)
        if index >= len(index_to_material):
            index = 0
        elif index < 0:
            index = len(index_to_material) - 1

        material_to_select = index_to_material[index]

    object: bpy.types.Object
    for object in material_to_object[material_to_select]:
        object.active_material_index = object.material_slots.find(material_to_select.name)


    bpy_utils.focus(material_to_object[material_to_select])
    if operator.focus:
        run_in_area(context, bpy.ops.view3d.view_selected)

    operator.report({'INFO'}, f"Material: {material_to_select.name} [{index + 1}/{len(index_to_material)}]")





@operator_factory.operator(
    poll = object_mode_poll,
    __annotations__ = tool_settings.Vhacd._get_ui_properties(),
    invoke = lambda operator, context, event: bpy.data.window_managers[0].invoke_props_dialog(operator, width=400),
    bl_options = {'REGISTER', 'UNDO', 'PRESET'},
)
def run_vhacd(operator: bpy.types.Operator, context: bpy.types.Context):

    selected_objects = context.selected_objects


    with tempfile.TemporaryDirectory() as tempdir:

        for object in selected_objects:

            bpy_utils.focus(object)

            filepath_input = os.path.join(tempdir, object.name_full + '.obj')
            filepath_output = os.path.join(tempdir, 'decomp.obj')

            try:
                bpy.ops.wm.obj_export(filepath=filepath_input, export_selected_objects=True, export_materials=False, export_uv=False, apply_modifiers=True)
            except AttributeError:
                bpy.ops.export_scene.obj(filepath=filepath_input, use_selection=True, use_materials=False, use_uvs=False, use_mesh_modifiers=True)


            cmd = tool_settings.Vhacd._from_bpy_struct(operator)._get_cmd(filepath_input)
            print('CMD:', utils.get_command_from_list(cmd))
            subprocess.run(cmd, check=True, cwd=tempdir)

            try:
                bpy.ops.wm.obj_import(filepath=filepath_output)
            except AttributeError:
                bpy.ops.import_scene.obj(filepath=filepath_output)



@operator_factory.operator(
    poll = view_3d_poll,
    __annotations__ = tool_settings.Ministry_Of_Flat._get_ui_properties(),
    invoke = lambda operator, context, event: bpy.data.window_managers[0].invoke_props_dialog(operator, width=400),
    bl_options = {'REGISTER', 'UNDO', 'PRESET'},
)
def run_ministry_of_flat(operator: bpy.types.Operator, context: bpy.types.Context):

    objects = [objects[0] for data, objects in utils.list_by_key(context.selected_objects, lambda x: x.data).items() if hasattr(data, 'uv_layers')]

    with tempfile.TemporaryDirectory() as temp_dir:
        for object in objects:
            bpy_uv.unwrap_ministry_of_flat(object, temp_dir, tool_settings.Ministry_Of_Flat._from_bpy_struct(operator))



@operator_factory.operator(
    poll = view_3d_poll,
    __annotations__ = tool_settings.Ministry_Of_Flat._get_ui_properties(),
    invoke = lambda operator, context, event: bpy.data.window_managers[0].invoke_props_dialog(operator, width=400),
    bl_options = {'REGISTER', 'UNDO', 'PRESET'},
)
def run_ministry_of_flat_obj_import(operator: bpy.types.Operator, context: bpy.types.Context):

    selected_objects = context.selected_objects


    with tempfile.TemporaryDirectory() as tempdir:

        for object in selected_objects:

            bpy_utils.focus(object)

            filepath_input = os.path.join(tempdir, object.name_full + '.obj')
            filepath_output = os.path.join(tempdir, 'unwrapped.obj')

            try:
                bpy.ops.wm.obj_export(filepath=filepath_input, export_selected_objects=True, export_materials=False, export_uv=False, apply_modifiers=False)
            except AttributeError:
                bpy.ops.export_scene.obj(filepath=filepath_input, use_selection=True, use_materials=False, use_uvs=False, use_mesh_modifiers=False)


            cmd = tool_settings.Ministry_Of_Flat._from_bpy_struct(operator)._get_cmd(filepath_input, filepath_output)
            print('CMD:', utils.get_command_from_list(cmd))

            try:
                subprocess.run(cmd, check=True)
            except subprocess.CalledProcessError as e:
                if not os.path.exists(filepath_output):
                    raise e from None

            bpy.ops.object.select_all(action='DESELECT')

            try:
                bpy.ops.wm.obj_import(filepath=filepath_output)
            except AttributeError:
                bpy.ops.import_scene.obj(filepath=filepath_output)


@operator_factory.operator(
    poll = edit_mode_poll,
    __annotations__ = dict(
        use_selected = bpy.props.BoolProperty(default=True),
        divide_by_mean = bpy.props.BoolProperty(default=False),
    ),
    bl_options = {'REGISTER', 'UNDO'},
)
def uv_to_world_scale(operator: bpy.types.Operator, context: bpy.types.Context):
    objects = [object for object in context.selected_objects if object.data and hasattr(object.data, 'uv_layers') and object.data.is_editmode]
    bpy_uv.scale_uv_to_world_per_uv_island(objects, use_selected=operator.use_selected, divide_by_mean=operator.divide_by_mean)


@operator_factory.operator(
    poll = object_mode_poll,
    bl_options = {'REGISTER', 'UNDO'},
)
def merge_objects_respect_materials(operator: bpy.types.Operator, context: bpy.types.Context):
    objects = context.selected_objects
    bpy_utils.make_material_independent_from_object(objects)
    bpy_utils.merge_objects(objects)


@operator_factory.operator(
    poll = edit_mode_poll,
    bl_options = {'REGISTER', 'UNDO'},
)
def scale_uv_to_world_per_uv_layout_median(operator: bpy.types.Operator, context: bpy.types.Context):
    objects = [object for object in context.selected_objects if object.data and hasattr(object.data, 'uv_layers') and object.data.is_editmode]
    bpy_uv.scale_uv_to_world_per_uv_layout(objects)




@operator_factory.operator(
    poll = edit_mode_poll,
    bl_options = {'REGISTER', 'UNDO'},
)
def align_longest_1(operator: bpy.types.Operator, context: bpy.types.Context):

    from .. import bpy_uv
    import mathutils
    import math

    object = context.active_object
    mesh = object.data
    b_mesh = bmesh.from_edit_mesh(mesh)

    uv_layer = b_mesh.loops.layers.uv.verify()

    linked_uv_islands = bpy_uv.get_linked_uv_islands(b_mesh, uv_layer)

    cos_angle = math.cos(math.radians(90))
    sin_angle = math.sin(math.radians(90))

    for island in linked_uv_islands:
        xs, ys = zip(*(bm_loop[uv_layer].uv for face in island for bm_loop in face.loops))

        if max(xs) - min(xs) < max(ys) - min(ys):
            island_vertices = [loop[uv_layer].uv for face in island for loop in face.loops]
            island_center = sum(island_vertices, mathutils.Vector((0,0)))/len(island_vertices)

            for face in island:
                for loop in face.loops:

                    uv_loop = loop[uv_layer]

                    x_new = uv_loop.uv[0] * cos_angle - uv_loop.uv[1] * sin_angle
                    y_new = uv_loop.uv[0] * sin_angle + uv_loop.uv[1] * cos_angle

                    uv_loop.uv -= island_center
                    uv_loop.uv = (x_new, y_new)
                    uv_loop.uv += island_center

    bmesh.update_edit_mesh(mesh)
