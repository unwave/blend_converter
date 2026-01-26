from __future__ import annotations

import os
import contextlib
import typing
import time
import uuid
import threading
import sys
import re
import math

import bpy


from .. import tool_settings
from .. import utils

from . import bpy_node
from . import bpy_context
from . import bpy_utils
from . import bpy_uv
from . import bake_settings
from . import blend_inspector
from . import communication



def print_error(*args):
    utils.print_in_color(utils.CONSOLE_COLOR.BG_RED, 'ERROR:', *args)

def print_warning(*args):
    utils.print_in_color(utils.CONSOLE_COLOR.RED, 'WARNING:',*args)

def print_ok(*args):
    utils.print_in_color(utils.CONSOLE_COLOR.BOLD + utils.CONSOLE_COLOR.GREEN, 'OK:',*args)

def print_notion(*args):
    utils.print_in_color(utils.CONSOLE_COLOR.BOLD + utils.CONSOLE_COLOR.MAGENTA, 'LOOK:', *args)

def print_bold(*args):
    utils.print_in_color(utils.CONSOLE_COLOR.BOLD, *args)

def print_accent(*args):
    utils.print_in_color(utils.CONSOLE_COLOR.BOLD + utils.CONSOLE_COLOR.YELLOW, *args)

def print_done(*args):
    utils.print_in_color(utils.CONSOLE_COLOR.BOLD + utils.CONSOLE_COLOR.BG_GREEN, *args)


def do_error(*args):
    print_error(*args)
    raise Exception("ERROR: " + ' '.join(str(arg) for arg in args))


def do_warning(*args, do_raise = False):
    print_warning(*args)
    if do_raise:
        raise Exception("WARNING: " + ' '.join(str(arg) for arg in args))


def is_property_missing(object: bpy.types.Object, attribute_type: str, attribute_name: str, SENTINEL = object()):
    if attribute_type == 'GEOMETRY':
        return False # do not check anything
    elif attribute_type == 'OBJECT':
        if object.data:
            return object.get(attribute_name, SENTINEL) == SENTINEL and object.data.get(attribute_name, SENTINEL) == SENTINEL
        else:
            return object.get(attribute_name, SENTINEL) == SENTINEL
    elif attribute_type == 'INSTANCER':
        return is_property_missing(object, 'OBJECT', attribute_name) # not correct if has the instancer


def report_missing_attributes(node_tree: bpy.types.NodeTree, object: bpy.types.Object, do_raise = False):
    """ does not check if the node is connect or not """

    tree = bpy_node.Shader_Tree_Wrapper(node_tree)

    root_node = tree.root
    if not root_node:
        return

    for node in root_node.descendants:

        if node.be('ShaderNodeAttribute'):

            if not node.attribute_name:
                continue

            if is_property_missing(object, node.attribute_type, node.attribute_name):
                do_warning(f"An attribute node refers to the property '{node.attribute_name}' that does not exist in object '{object.name}'.", do_raise=do_raise)

        elif node.be('ShaderNodeGroup'):
            if node.node_tree:
                report_missing_attributes(node.node_tree, object, do_raise=do_raise)


def get_images(bl_tree: bpy.types.NodeTree):

    images: typing.List[bpy.types.Image] = []

    tree = bpy_node.Shader_Tree_Wrapper(bl_tree)

    root_node = tree.root
    if not root_node:
        return images

    for node in root_node.descendants:

        if node.be('ShaderNodeTexImage') and node.image:
            images.append(node.image)

        elif node.be('ShaderNodeGroup'):
            if node.node_tree:
                images.extend(get_images(node.node_tree))

    return images


def report_missing_files(node_tree: bpy.types.NodeTree, do_raise = False):

    for image in utils.deduplicate(get_images(node_tree)):
        if not image.packed_file and not os.path.exists(bpy_utils.get_block_abspath(image)):
            do_warning(f"Image is missing in path: {image.filepath}.", do_raise=do_raise)


NORMAL_SOCKETS = {
    'Normal',
    'Tangent',

    'Clearcoat Normal',

    'Coat Normal',
}

SRGB_SOCKETS = {
    'Base Color',

    'Emission',
    'Subsurface Color',

    'Specular Tint',
    'Coat Tint',
    'Sheen Tint',
    'Emission Color',
}


class Compositor_Image_Channel:

    RGB = -1
    R = 0
    G = 1
    B = 2



class Baked_Image:


    def __init__(self, bake_types: typing.Union[bake_settings._Bake_Type, typing.List[bake_settings._Bake_Type]], name_prefix: str, settings: tool_settings.Bake):

        if isinstance(bake_types, bake_settings._Bake_Type):
            bake_types = [bake_types]

        self.bake_types = bake_types
        self.settings = settings
        self.name_prefix = name_prefix
        self.image_name = utils.ensure_valid_basename(name_prefix + '_' + '_'.join([type._identifier for type in bake_types]).replace(' ', '_').lower())

        self.sub_images: typing.List[bpy.types.Image] = []

        self.final_image: typing.Optional[bpy.types.Image] = None


    @property
    def bakeable_tasks(self) -> typing.List[typing.List[bake_settings._Bake_Type]]:

        if len(self.bake_types) == 1:
            return [
                [self.bake_types[0]],
            ]

        elif len(self.bake_types) == 2:
            if self.bake_types[0]._socket_type in (bake_settings._Socket_Type.COLOR, bake_settings._Socket_Type.VECTOR):
                return [
                    [self.bake_types[0]],
                    [self.bake_types[1]],
                ]
            elif any(type._socket_type == bake_settings._Socket_Type.SHADER for type in self.bake_types):
                return [
                    [self.bake_types[0]],
                    [self.bake_types[1]],
                ]
            else:
                return [
                    [self.bake_types[0], self.bake_types[1], bake_settings.Fill_Color()],
                ]

        elif len(self.bake_types) in (3, 4):

            alpha = [[self.bake_types[3]]] if len(self.bake_types) == 4 else []

            if all(type._socket_type != bake_settings._Socket_Type.SHADER for type in self.bake_types[:3]):
                return [
                    [self.bake_types[0], self.bake_types[1], self.bake_types[2]],
                    *alpha,
                ]
            elif self.bake_types[0]._socket_type == bake_settings._Socket_Type.SHADER and all(type._socket_type != bake_settings._Socket_Type.SHADER for type in self.bake_types[1:3]):
                return [
                    [self.bake_types[0]],
                    [bake_settings.Fill_Color(), self.bake_types[1], self.bake_types[2]],
                    *alpha,
                ]
            elif self.bake_types[1]._socket_type == bake_settings._Socket_Type.SHADER and all(type._socket_type != bake_settings._Socket_Type.SHADER for type in self.bake_types[:3:2]):
                return [
                    [self.bake_types[0], bake_settings.Fill_Color(), self.bake_types[2]],
                    [self.bake_types[1]],
                    *alpha,
                ]
            elif self.bake_types[2]._socket_type == bake_settings._Socket_Type.SHADER and all(type._socket_type != bake_settings._Socket_Type.SHADER for type in self.bake_types[:2]):
                return [
                    [self.bake_types[0], self.bake_types[1], bake_settings.Fill_Color()],
                    [self.bake_types[2]],
                    *alpha,
                ]
            else:
                return [
                    [self.bake_types[0]],
                    [self.bake_types[1]],
                    [self.bake_types[2]],
                    *alpha,
                ]
        else:
            raise ValueError(f"Unexpected identifier length: {self.bake_types}")


    def append_sub_image(self, bake_task: typing.List[bake_settings._Bake_Type]):

        name = self.name_prefix + '_' + '_'.join(bake_type._identifier for bake_type in bake_task).replace(' ', '_').lower() + '_' + uuid.uuid1().hex

        image = bpy.data.images.new(name, width = self.settings._bake_width, height = self.settings._bake_height, float_buffer = True, is_data = not self.is_srgb_image, alpha = True)
        image.alpha_mode = 'CHANNEL_PACKED'

        if len(bake_task) == 1:
            image.generated_color = [ *bake_task[0]._default_color, 0.0 ]
        else:
            image.generated_color = [ *(sub_task._default_value for sub_task in bake_task), 0.0 ]

        image[self.settings._K_MAP_IDENTIFIER] = {sub_task._identifier: bool(sub_task) for sub_task in bake_task}

        self.sub_images.append(image)

        return image


    @property
    def is_srgb_image(self):
        return any(bake_type._is_srgb for bake_type in self.bake_types)


    default_file_settings = tool_settings.Image_File_Settings(file_format = 'PNG', color_depth = '8', compression = 15, color_mode = 'RGB')
    """ Default: PNG 8-bit RGB """

    normal_file_settings = tool_settings.Image_File_Settings(file_format = 'PNG', color_depth = '16', compression = 15, color_mode = 'RGB')
    """ Default: PNG 16-bit RGB """

    displacement_file_settings = tool_settings.Image_File_Settings(file_format = 'PNG', color_depth = '16', compression = 15, color_mode = 'BW')
    """ Default: PNG 16-bit BW """

    buffer_file_settings = tool_settings.Image_File_Settings(file_format = 'OPEN_EXR', color_depth = '32', exr_codec = 'ZIP', color_mode = 'RGB')
    """ For intermediate data. """


    @property
    def image_file_settings(self):
        if self.bake_types[0]._identifier in NORMAL_SOCKETS:
            return self.normal_file_settings
        elif any(isinstance(type, bake_settings.Buffer_Factor) for type in self.bake_types):
            return self.buffer_file_settings
        elif any(isinstance(type, bake_settings.View_Space_Normal) for type in self.bake_types):
            return self.buffer_file_settings
        else:
            return self.default_file_settings


    def compose_and_save(self):
        print()
        print('Composing and saving...')

        with bpy_context.State() as state:

            ## set color space
            # this does not affect .exr files
            state.set(bpy.context.scene.display_settings, 'display_device', 'sRGB')
            if self.is_srgb_image:
                state.set(bpy.context.scene.view_settings, 'view_transform', 'Standard')
            else:
                state.set(bpy.context.scene.view_settings, 'view_transform', 'Raw')


            state.set(bpy.context.scene.view_settings, 'exposure', 0)
            state.set(bpy.context.scene.view_settings, 'look', 'None')
            state.set(bpy.context.scene.view_settings, 'gamma', 1)
            state.set(bpy.context.scene.view_settings, 'use_curve_mapping', False)


            ## set nodes
            if bpy.app.version < (5, 0):
                # Compositor: Remove scene.use_nodes from Python API #143578
                # https://projects.blender.org/blender/blender/pulls/143578
                state.set(bpy.context.scene, 'use_nodes', True)

            state.set(bpy.context.scene.render, 'use_file_extension', False)
            state.set(bpy.context.scene.render, 'dither_intensity', self.settings.dither_intensity)

            tree = bpy_node.Compositor_Tree_Wrapper.from_scene(bpy.context.scene)

            for node in tree.get_by_bl_idname({'CompositorNodeRLayers', 'CompositorNodeComposite', 'CompositorNodeOutputFile', 'CompositorNodeViewer'}):
                state.set(node.bl_node, 'mute', True)

            file_node = tree.new('CompositorNodeOutputFile')

            if bpy.app.version >= (5, 0):
                file_node.format.media_type = 'IMAGE'

            for key, value in self.image_file_settings._to_dict().items():
                setattr(file_node.format, key, value)

            if bpy.app.version >= (5, 0):
                file_node.directory = self.settings.image_dir
            else:
                file_node.base_path = self.settings.image_dir

            if bpy.app.version >= (5, 0):
                file_slot = file_node.file_output_items.new(socket_type='RGBA', name = '')
                file_node.update_sockets()
            else:
                file_slot: bpy.types.NodeOutputFileSlotFile = file_node.file_slots[0]

            try:
                file_slot.save_as_render = True
            except AttributeError:
                # Blender 2.83 does not have save_as_render but uses the render color transform
                pass

            file_name = self.image_name + '.' + self.image_file_settings._file_extension.lower()
            # https://docs.blender.org/manual/en/latest/compositing/types/output/file_output.html#properties
            file_name = file_name.replace('#', '_')

            if bpy.app.version >= (5, 0):
                file_node.file_name = file_name
            else:
                file_slot.path = file_name

            file_node_input = file_node.inputs[0]
            file_node.format.color_mode = 'RGB'


            ## downscale
            if self.settings.do_downscale and not math.isclose(self.settings.resolution_multiplier, 1, rel_tol=1e-5):

                scale_node = file_node_input.insert_new('CompositorNodeScale')
                scale_node.space = 'RENDER_SIZE'

                blur_node = scale_node.inputs[0].insert_new('CompositorNodeBlur')

                blur_node.size_x = 1
                blur_node.size_y = 1

                aspect_ratio = self.settings._aspect_ratio
                if aspect_ratio > 1:
                    blur_node.size_x = aspect_ratio
                elif aspect_ratio < 1:
                    blur_node.size_y = 1/aspect_ratio

                blur_node.filter_type = 'CUBIC'
                blur_node.inputs[1].set_default_value(self.settings.resolution_multiplier)

                if self.settings.use_anti_aliasing and bpy.app.version >= (2, 93):
                    anti_aliasing = blur_node.inputs[0].insert_new('CompositorNodeAntiAliasing')
                    anti_aliasing.inputs[1].default_value = 0.5
                    target_input = anti_aliasing.inputs[0]
                else:
                    target_input = blur_node.inputs[0]

                if isinstance(self.bake_types[0], (bake_settings.Normal, bake_settings.Normal_Native)):
                    bpy_context.insert_normalize(scale_node)
                elif isinstance(self.bake_types[0], bake_settings.View_Space_Normal):
                    bpy_context.insert_normalize(scale_node, use_map_range = False)
            else:
                if self.settings.use_anti_aliasing and bpy.app.version >= (2, 93):
                    anti_aliasing = file_node_input.insert_new('CompositorNodeAntiAliasing')
                    anti_aliasing.inputs[1].default_value = 0.5
                    target_input = anti_aliasing.inputs[0]
                else:
                    target_input = file_node_input


            ## set images
            combine_rgba: bpy_node._Compositor_Node_Wrapper

            def get_combined_input(channel: str):
                return combine_rgba.inputs[channel].new(bpy_node.Compositor_Node_Type.SEPARATE_RGBA, channel).inputs[0]

            R = 0
            G = 1
            B = 2
            A = 3

            with contextlib.ExitStack() as context_stack:

                if len(self.bake_types) == 1:
                    print('[RGB]')

                    context_stack.enter_context(self.bake_types[0]._get_compositor_context(target_input, self.sub_images[0], Compositor_Image_Channel.RGB))

                elif len(self.bake_types) == 2:
                    if self.bake_types[0]._socket_type in (bake_settings._Socket_Type.COLOR, bake_settings._Socket_Type.VECTOR):
                        print('[RGB] + [A]')

                        file_node.format.color_mode = 'RGBA'

                        combine_rgba = target_input.new(bpy_node.Compositor_Node_Type.COMBINE_RGBA)

                        split_rgba = combine_rgba.inputs[R].new(bpy_node.Compositor_Node_Type.SEPARATE_RGBA, R)
                        split_rgba.outputs[G].join(combine_rgba.inputs[G], move=False)
                        split_rgba.outputs[B].join(combine_rgba.inputs[B], move=False)

                        context_stack.enter_context(self.bake_types[0]._get_compositor_context(split_rgba.inputs[0], self.sub_images[0], Compositor_Image_Channel.RGB))
                        context_stack.enter_context(self.bake_types[1]._get_compositor_context(combine_rgba.inputs[A], self.sub_images[1], Compositor_Image_Channel.RGB))


                    elif any(type._socket_type == bake_settings._Socket_Type.SHADER for type in self.bake_types):
                        print('[R] + [G]')

                        combine_rgba = target_input.new(bpy_node.Compositor_Node_Type.COMBINE_RGBA)

                        context_stack.enter_context(self.bake_types[0]._get_compositor_context(combine_rgba.inputs[R], self.sub_images[0], Compositor_Image_Channel.RGB))
                        context_stack.enter_context(self.bake_types[1]._get_compositor_context(combine_rgba.inputs[G], self.sub_images[1], Compositor_Image_Channel.RGB))

                    else:
                        print('[R + G + None]')

                        combine_rgba = target_input.new(bpy_node.Compositor_Node_Type.COMBINE_RGBA)

                        context_stack.enter_context(self.bake_types[0]._get_compositor_context(get_combined_input(R), self.sub_images[0], Compositor_Image_Channel.R))
                        context_stack.enter_context(self.bake_types[1]._get_compositor_context(get_combined_input(G), self.sub_images[0], Compositor_Image_Channel.G))


                elif len(self.bake_types) in (3, 4):
                    if all(type._socket_type != bake_settings._Socket_Type.SHADER for type in self.bake_types[:3]):
                        print('[R + G + B]')

                        combine_rgba = target_input.new(bpy_node.Compositor_Node_Type.COMBINE_RGBA)

                        # TODO: this is inefficient
                        context_stack.enter_context(self.bake_types[0]._get_compositor_context(get_combined_input(R), self.sub_images[0], Compositor_Image_Channel.R))
                        context_stack.enter_context(self.bake_types[1]._get_compositor_context(get_combined_input(G), self.sub_images[0], Compositor_Image_Channel.G))
                        context_stack.enter_context(self.bake_types[2]._get_compositor_context(get_combined_input(B), self.sub_images[0], Compositor_Image_Channel.B))


                    elif self.bake_types[0]._socket_type == bake_settings._Socket_Type.SHADER and all(type._socket_type != bake_settings._Socket_Type.SHADER for type in self.bake_types[1:3]):
                        print('[R] + [None + G + B]')

                        combine_rgba = target_input.new(bpy_node.Compositor_Node_Type.COMBINE_RGBA)

                        context_stack.enter_context(self.bake_types[0]._get_compositor_context(combine_rgba.inputs[R], self.sub_images[0], Compositor_Image_Channel.RGB))
                        context_stack.enter_context(self.bake_types[1]._get_compositor_context(get_combined_input(G), self.sub_images[1], Compositor_Image_Channel.G))
                        context_stack.enter_context(self.bake_types[2]._get_compositor_context(get_combined_input(B), self.sub_images[1], Compositor_Image_Channel.B))


                    elif self.bake_types[1]._socket_type == bake_settings._Socket_Type.SHADER and all(type._socket_type != bake_settings._Socket_Type.SHADER for type in self.bake_types[:3:2]):
                        print('[R + None + B] + [G]')

                        combine_rgba = target_input.new(bpy_node.Compositor_Node_Type.COMBINE_RGBA)

                        context_stack.enter_context(self.bake_types[0]._get_compositor_context(get_combined_input(R), self.sub_images[0], Compositor_Image_Channel.R))
                        context_stack.enter_context(self.bake_types[1]._get_compositor_context(combine_rgba.inputs[G], self.sub_images[1], Compositor_Image_Channel.RGB))
                        context_stack.enter_context(self.bake_types[2]._get_compositor_context(get_combined_input(B), self.sub_images[0], Compositor_Image_Channel.B))


                    elif self.bake_types[2]._socket_type == bake_settings._Socket_Type.SHADER and all(type._socket_type != bake_settings._Socket_Type.SHADER for type in self.bake_types[:2]):
                        print('[R + G + None] + [B]')

                        combine_rgba = target_input.new(bpy_node.Compositor_Node_Type.COMBINE_RGBA)

                        context_stack.enter_context(self.bake_types[0]._get_compositor_context(get_combined_input(R), self.sub_images[0], Compositor_Image_Channel.R))
                        context_stack.enter_context(self.bake_types[1]._get_compositor_context(get_combined_input(G), self.sub_images[0], Compositor_Image_Channel.G))
                        context_stack.enter_context(self.bake_types[2]._get_compositor_context(combine_rgba.inputs[B], self.sub_images[1], Compositor_Image_Channel.RGB))

                    else:
                        print('[R] + [G] + [B]')

                        combine_rgba = target_input.new(bpy_node.Compositor_Node_Type.COMBINE_RGBA)

                        context_stack.enter_context(self.bake_types[0]._get_compositor_context(combine_rgba.inputs[R], self.sub_images[0], Compositor_Image_Channel.RGB))
                        context_stack.enter_context(self.bake_types[1]._get_compositor_context(combine_rgba.inputs[G], self.sub_images[1], Compositor_Image_Channel.RGB))
                        context_stack.enter_context(self.bake_types[2]._get_compositor_context(combine_rgba.inputs[B], self.sub_images[2], Compositor_Image_Channel.RGB))

                    if len(self.bake_types) == 4:
                        print('_ + [A]')

                        file_node.format.color_mode = 'RGBA'

                        context_stack.enter_context(self.bake_types[3]._get_compositor_context(combine_rgba.inputs[A], self.sub_images[3], Compositor_Image_Channel.RGB))

                else:
                    raise ValueError(f"Unexpected identifier length: {self.bake_types}")


                state.set(bpy.context.scene.render, 'resolution_y', self.settings._actual_height)
                state.set(bpy.context.scene.render, 'resolution_x', self.settings._actual_width)
                state.set(bpy.context.scene.render, 'resolution_percentage', 100)


                use_view_space_normals = (
                    # the settings have view space normals assigned for denoising
                    self.settings.view_space_normals_id
                    and
                    # the image, which is being saved, is not itself the view space normals
                    not any(self.settings.view_space_normals_id == bake_type._uuid for bake_type in self.bake_types)
                )

                if use_view_space_normals:

                    tree = bpy_node.Compositor_Tree_Wrapper.from_scene(bpy.context.scene)

                    for image in bpy.data.images:
                        if self.settings.view_space_normals_id in image.get(self.settings._K_BAKE_TYPES, ()):
                            view_space_normals_image = image
                            break
                    else:
                        raise Exception(f"View space normals are expected but not found: {self.settings.view_space_normals_id}")

                    view_space_normals_node = tree.new('CompositorNodeImage', image = view_space_normals_image)

                    for node in tree:

                        if node.be('CompositorNodeDenoise'):
                            view_space_normals_node.outputs[0].join(node.inputs['Normal'])
                        elif node.be('CompositorNodeGroup') and node.node_tree and node.node_tree.name.startswith('BC_C_Denoise'):
                            view_space_normals_node.outputs[0].join(node.get_input_by_name('Normal'))



                blend_inspector.inspect_if_has_identifier(blend_inspector.COMMON.INSPECT_BAKE_COMPOSITOR)

                if not self.settings.fake_bake:
                    with utils.Capture_Stdout() as capture:
                        bpy.ops.render.render()

                final_path = os.path.join(self.settings.image_dir, file_name)

                if not self.settings.fake_bake:

                    if bpy.app.version >= (5, 0):
                        pass
                    else:
                        os.replace(final_path + str(bpy.context.scene.frame_current).zfill(4), final_path)

                if self.settings.fake_bake:
                    image = bpy.data.images.new(name=self.image_name, width=4, height=4)
                    image.filepath_raw = final_path
                else:
                    image = bpy.data.images.load(final_path, check_existing=True)

                image[self.settings._K_MAP_IDENTIFIER] = {bake_type._identifier: bool(bake_type) for bake_type in self.bake_types}
                image[self.settings._K_BAKE_TYPES] = [bake_type._uuid for bake_type in self.bake_types]
                image.name = self.image_name

                image.colorspace_settings.name = 'sRGB' if self.is_srgb_image else 'Non-Color'

                tree.delete_new_nodes()

                self.final_image = image

                return image


def get_conformed_pass_filter():

    bake = bpy.context.scene.render.bake
    bake_type = bpy.context.scene.cycles.bake_type

    if bake_type == 'COMBINED':
        pass_filter = set()

        if bake.use_pass_direct:
            pass_filter.add('DIRECT')

        if bake.use_pass_indirect:
            pass_filter.add('INDIRECT')

        if bake.use_pass_diffuse:
            pass_filter.add('DIFFUSE')

        if bake.use_pass_glossy:
            pass_filter.add('GLOSSY')

        if bake.use_pass_transmission:
            pass_filter.add('TRANSMISSION')

        if bake.use_pass_emit:
            pass_filter.add('EMIT')

        return pass_filter

    elif bake_type in ('DIFFUSE', 'GLOSSY', 'TRANSMISSION'):
        pass_filter = set()

        if bake.use_pass_direct:
            pass_filter.add('DIRECT')

        if bake.use_pass_indirect:
            pass_filter.add('INDIRECT')

        if bake.use_pass_color:
            pass_filter.add('COLOR')

        return pass_filter

    else:
        return {'NONE'}


def set_all_image_nodes_interpolation_to_smart(bl_tree: bpy.types.ShaderNodeTree, state: bpy_context.State):

    pool = [bl_tree]
    processed = set()

    while pool:

        tree = pool.pop()

        if tree in processed:
            continue

        processed.add(tree)

        for node in tree.nodes:
            if node.bl_idname == 'ShaderNodeTexImage' and node.image:
                state.set(node, 'interpolation', 'Smart')
            elif node.bl_idname == 'ShaderNodeGroup' and node.node_tree:
                pool.append(node.node_tree)


def ensure_unique_name(name, taken_names = set()):

    init_name = name
    index = 2

    while name in taken_names:
        name = f"{init_name}_{index}"
        index += 1

    taken_names.add(name)

    return name


def the_bake(active_object: bpy.types.Object, selected_objects: typing.List[bpy.types.Object], kwargs):
    """ Wrapped into a function to be shown separately when profiling and for monkey patching. """
    bpy_context.call_for_objects(
        active_object,
        selected_objects,
        bpy.ops.object.bake,
        **kwargs,
    )


def bake_images(objects: typing.List[bpy.types.Object], uv_layer: str, settings: tool_settings.Bake):

    materials_to_bake: typing.List[bpy.types.Material] = []
    objects_by_material = bpy_utils.group_objects_by_material(objects)

    if settings.texture_name_prefix:
        texture_name_prefix = settings.texture_name_prefix
    else:
        texture_name_prefix = ensure_unique_name(bpy_utils.get_common_name(filter(None, objects_by_material.keys()), objects[0].name))

    baking_images = [Baked_Image(map, texture_name_prefix, settings) for map in settings.bake_types]


    print()

    for material, _ in objects_by_material.items():

        if not material:
            continue

        if settings.material_key and not material.get(settings.material_key):
            continue

        materials_to_bake.append(material)


    for baking_image in baking_images:


        for bake_task in baking_image.bakeable_tasks:

            print()
            print_bold('Bake task:', str(bake_task), f"{settings._bake_width}x{settings._bake_height}")

            # creating shared image
            image = baking_image.append_sub_image(bake_task)
            settings._raw_images.append(image)

            # set up the bake image for all the materials
            for material in materials_to_bake:

                for node in material.node_tree.nodes:
                    node.select = False

                image_node: bpy.types.ShaderNodeTexImage = material.node_tree.nodes.new('ShaderNodeTexImage')
                image_node.name = image.name
                image_node.image = image
                image_node.select = True
                material.node_tree.nodes.active = image_node

            with contextlib.ExitStack() as context_stack:

                for sub_task in bake_task:
                    context_stack.enter_context(sub_task._get_setup_context())

                def enter_output_context(material: bpy.types.Material, bake_task: typing.List[bake_settings._Bake_Type]):
                    if len(bake_task) == 1:
                        output_socket = context_stack.enter_context(bake_task[0]._get_material_context(material))
                        context_stack.enter_context(bpy_context.Output_Override(material, output_socket))
                    else:
                        r_g_b = [context_stack.enter_context(bake_task[i]._get_material_context(material)) for i in range(3)]
                        context_stack.enter_context(bpy_context.Output_Override_Combine_RGB(material, *r_g_b))


                is_global_bake_type = any(isinstance(task, bake_settings.AO_Diffuse) for task in bake_task)
                if is_global_bake_type:
                    for material in materials_to_bake:
                        enter_output_context(material, bake_task)

                    for material in bpy_utils.get_view_layer_materials():
                        if material not in materials_to_bake:
                            if material.node_tree:
                                context_stack.enter_context(bpy_context.No_Active_Image(material))
                else:
                    for material in materials_to_bake:
                        enter_output_context(material, bake_task)

                    disable_material_state = context_stack.enter_context(bpy_context.State())
                    for object in objects:
                        for slot in object.material_slots:
                            if not slot.material in materials_to_bake:
                                disable_material_state.set(slot, 'material', None)


                def get_bake_type_match(regex: str):
                    for match in blend_inspector.search_identifier(regex):
                        for bake_type in bake_task:
                            if re.search(match.group(1), bake_type._identifier, flags=re.IGNORECASE):
                                return match.group(0)
                    return None


                if blend_inspector.inspect_if_has_identifier(blend_inspector.COMMON.INSPECT_BAKE_PRE):
                    pass
                elif get_bake_type_match(r'inspect:bake:map=(.+)'):
                    blend_inspector.inspect_blend(get_bake_type_match(r'inspect:bake:map=(.+)'))
                elif get_bake_type_match(r'skip:bake:map=(.+)'):
                    print(f"Skipped: {get_bake_type_match(r'skip:bake:map=(.+)')}")
                    continue
                elif blend_inspector.has_identifier(blend_inspector.COMMON.SKIP_BAKE_ALL):
                    print(f"Skipped: {blend_inspector.COMMON.SKIP_BAKE_ALL}")
                    continue


                if bpy.context.scene.cycles.bake_type in ('COMBINED', 'DIFFUSE', 'GLOSSY', 'TRANSMISSION'):
                    kwargs = dict(
                        type = bpy.context.scene.cycles.bake_type,
                        pass_filter = get_conformed_pass_filter(),
                    )
                else:
                    kwargs = dict(type=bpy.context.scene.cycles.bake_type)


                if not settings.fake_bake:

                    print(f"Bake started: {time.strftime('%H:%M:%S %Y-%m-%d')}")

                    with utils.Capture_Stdout():

                        if bpy.context.view_layer.objects.active in objects:
                            active_object = bpy.context.view_layer.objects.active
                        else:
                            active_object = objects[0]

                        the_bake(active_object, objects, kwargs)


                blend_inspector.inspect_if_has_identifier(blend_inspector.COMMON.INSPECT_BAKE_AFTER)


        do_compose_and_save = (
            settings.compose_and_save
            and
            not blend_inspector.has_identifier(blend_inspector.COMMON.SKIP_BAKE_ALL)
            and
            not blend_inspector.has_identifier(blend_inspector.COMMON.SKIP_BAKE_SAVE)
        )

        if do_compose_and_save:
            baking_image.compose_and_save()

    # TODO: checking for None only applicable when skipping stages, otherwise may be ambiguous
    return [image.final_image for image in baking_images if image.final_image]


def get_gltf_settings_node_tree():
    node_tree = bpy.data.node_groups.get('glTF Settings')
    if node_tree:
        return node_tree

    node_tree: bpy.types.ShaderNodeTree = bpy.data.node_groups.new('glTF Settings', 'ShaderNodeTree')

    if hasattr(node_tree, 'interface'):
        node_tree.interface.new_socket(name='Occlusion', in_out='INPUT', socket_type='NodeSocketFloat')
        node_tree.interface.items_tree['Occlusion'].default_value = 0.5
    else:
        node_tree.inputs.new('NodeSocketFloatFactor', 'Occlusion')
        node_tree.inputs['Occlusion'].default_value = 0.5

    return node_tree


def create_material(
            name: str,
            uv_layer: str,
            images: typing.Iterable[bpy.types.Image],
            material: typing.Optional[bpy.types.Material] = None,
            k_map_identifier = tool_settings.Bake._K_MAP_IDENTIFIER
        ):

    do_reset = False

    if not material:
        material = bpy.data.materials.new(name)
        if bpy.app.version < (5, 0):
            material.use_nodes = True
    else:
        do_reset = True

    tree = bpy_node.Shader_Tree_Wrapper(material.node_tree)
    if do_reset:
        tree.reset_nodes()

    principled = tree.output['Surface']

    uv_node = tree.new('ShaderNodeUVMap')
    uv_node.uv_map = uv_layer
    x, y = uv_node.location
    uv_node.location = (x - 500, y)


    def get_gltf_settings_node():
        node = tree.bl_tree.nodes.get('glTF Settings')
        if node:
            return tree[node]

        node = tree.new('ShaderNodeGroup', node_tree = get_gltf_settings_node_tree())
        node.name = 'glTF Settings'
        return node


    def get_input(identifier):
        if identifier == bake_settings._AO._identifier:
            return get_gltf_settings_node().inputs[0]
        else:
            socket = principled.inputs.get(identifier)
            if socket is None:
                print("Unexpected image type:", map_identifier)
                return tree.new('NodeReroute').inputs[0]
            else:
                return socket


    for image in images:

        map_identifier = list(image[k_map_identifier].keys())

        if len(map_identifier) in (1,2):
            input = get_input(map_identifier[0])

            image_node = input.new('ShaderNodeTexImage', image = image)

            uv_node.outputs[0].join(image_node.inputs['Vector'], False)

            if map_identifier[0] in NORMAL_SOCKETS:
                normal_map_node = image_node.outputs[0].new('ShaderNodeNormalMap', 'Color')
                normal_map_node.uv_map = uv_layer
                normal_map_node.outputs[0].join(input)

        elif len(map_identifier) in (3, 4):

            for index, _identifier in enumerate(map_identifier[:3]):
                if _identifier:
                    non_none_index = index
                    break
            else:
                continue

            input = get_input(map_identifier[non_none_index])

            separate_rgb = input.new(bpy_node.Shader_Node_Type.SEPARATE_RGB)

            image_node = separate_rgb.inputs[non_none_index].new('ShaderNodeTexImage', image = image)
            uv_node.outputs[0].join(image_node.inputs['Vector'], False)

            for index, _identifier in enumerate(map_identifier):

                if not _identifier:
                    continue

                separate_rgb.outputs[index].join(get_input(_identifier), move = False)

        if len(map_identifier) in (2, 4):
            image_node.outputs[1].join(get_input(map_identifier[-1]))

    if principled['Alpha']:
        material.blend_method = 'HASHED'

    if principled[bpy_node.Socket_Identifier.EMISSION]:
        if 'Emission Strength' in principled.inputs.identifiers and not principled['Emission Strength']:
            principled['Emission Strength'] = 1

    if principled['Base Color']:
        tree.bl_tree.nodes.active = principled['Base Color'].bl_node

    return material


def bake_materials(objects: typing.List[bpy.types.Object], settings: tool_settings.Bake):

    uv_layer_name = settings.uv_layer_name

    if settings.merge_materials and not settings.material_key:

        with communication.All_Cores():
            images = bake_images(objects, uv_layer_name, settings)
        settings._images.extend(images)

        if settings.create_materials:

            if settings.use_selected_to_active:
                objects = [o for o in objects if bpy.context.view_layer.objects.active == o]

            bpy_uv.clear_uv_layers_from_objects(objects, uv_layer_name, 'UVMap')

            material_name = settings.texture_name_prefix
            if not material_name:
                material_name = bpy_utils.get_common_name(objects)

            material = create_material(material_name, 'UVMap', images, k_map_identifier = settings._K_MAP_IDENTIFIER)
            material[settings._K_MATERIAL_KEY] = settings.material_key

            for object in objects:
                mesh: bpy.types.Mesh = object.data

                mesh.materials.clear()
                mesh.materials.append(material)

    elif settings.merge_materials and settings.material_key:

        materials_to_bake = [m for m in bpy.data.materials if m.get(settings.material_key)]

        # collect objects with at least one material from the group
        objects_in_group: typing.List[bpy.types.Object] = []
        for _object in objects:
            for slot in _object.material_slots:
                if slot.material in materials_to_bake:
                    objects_in_group.append(_object)
                    break

        if not objects_in_group:
            do_warning(
                f"No objects found for specified materials to be baked:"
                "\n\t"
                f"material_key={settings.material_key}"
                "\n\t"
                f"materials_to_bake={materials_to_bake}"
                "\n\t"
                f"objects={objects}",
                do_raise=settings.raise_warnings)
            return

        print_bold(
            "\n"
            f"Material Baking: {[m.name_full for m in bpy_utils.get_unique_materials(objects_in_group) if m in materials_to_bake]}"
            "\n"
            f"For objects: {[o.name_full for o in objects_in_group]}"
        )

        with communication.All_Cores():
            images = bake_images(objects_in_group, uv_layer_name, settings)
        settings._images.extend(images)

        if settings.create_materials:

            if settings.use_selected_to_active:
                objects_in_group = [o for o in objects_in_group if bpy.context.view_layer.objects.active == o]

            material_name = settings.texture_name_prefix
            if not material_name:
                material_name = bpy_utils.get_common_name(materials_to_bake)

            material = create_material(material_name, uv_layer_name, images, k_map_identifier = settings._K_MAP_IDENTIFIER)
            material[settings._K_MATERIAL_KEY] = settings.material_key

            for object in objects_in_group:

                object.data.uv_layers.active = object.data.uv_layers[uv_layer_name]

                for slot in object.material_slots:
                    if slot.material in materials_to_bake:
                        slot.material = material

    else:
        objects_by_material = bpy_utils.group_objects_by_material(objects)

        for material, _objects in objects_by_material.items():

            print_bold('\nMaterial Baking: ', material.name_full, '\nfor objects:', [o.name_full for o in _objects])

            with communication.All_Cores():
                images = bake_images(_objects, uv_layer_name, settings)
            settings._images.extend(images)

            if settings.create_materials:
                material = create_material(material.name, uv_layer_name, images, material, k_map_identifier = settings._K_MAP_IDENTIFIER)
                material[settings._K_MATERIAL_KEY] = settings.material_key

        if settings.create_materials:

            if settings.use_selected_to_active:
                objects = [o for o in objects if bpy.context.view_layer.objects.active == o]

            bpy_uv.clear_uv_layers_from_objects(objects, uv_layer_name, 'UVMap')



def get_default_material() -> bpy.types.Material:

    material = bpy.data.materials.get('__bc_default_material')
    if not material:
        material = bpy.data.materials.new('__bc_default_material')
        if bpy.app.version < (5, 0):
            material.use_nodes = True

    return material



def bake_objects(objects: typing.List[bpy.types.Object], settings: tool_settings.Bake):

    start_time = time.perf_counter()

    print_accent('Start baking:\n', '\n'.join((o.name_full for o in objects)))


    with contextlib.ExitStack() as exit_stack:

        state = exit_stack.enter_context(bpy_context.State())

        # hide other object in render
        if settings.isolate_objects:
            for object in bpy_utils.get_view_layer_objects():
                state.set(object, 'hide_render', object not in objects)

        for object in objects:

            # disable the object's particle systems
            for modifier in object.modifiers:
                if modifier.type == 'PARTICLE_SYSTEM':
                    state.set(modifier, 'show_render', False)

            # use modifiers that are only visible in viewport
            if settings.use_modifiers_as_in_viewport:
                for modifier in object.modifiers:
                    state.set(modifier, 'show_render', modifier.show_viewport)

            # disable geometry order changing modifiers
            if settings.turn_off_vertex_changing_modifiers:
                for modifier in object.modifiers:
                    if modifier.show_render and modifier.type in bpy_context.TOPOLOGY_CHANGING_MODIFIER_TYPES:
                        state.set(modifier, 'show_render', False)

            # disable armature
            if settings.do_disable_armature:
                exit_stack.enter_context(bpy_context.Armature_Disabled(object))

        bake_materials(objects, settings)


    print()
    print_ok(f'Done baking in {round(time.perf_counter() - start_time, 2)} secs.')
    utils.print_separator(char='▓')


def bake(objects: typing.List[bpy.types.Object], settings: tool_settings.Bake) -> typing.List[bpy.types.Image]:


    if not objects:
        raise Exception(f"No objects provided for baking: {settings}")


    bake_start_time = time.perf_counter()

    utils.print_separator(char='░')
    utils.print_in_color(utils.get_color_code(0,0,0,128,128,0), f"Preparing bake...")


    if any(o.type != 'MESH' for o in objects):
        raise Exception("\n\t".join([
            "Bake target objects must be of type MESH:",
            f"objects = {[o.name_full for o in objects]}",
            f"incompatible = {[o.name_full for o in objects if o.type != 'MESH']}",
        ]))


    # validate

    view_layer_objects = bpy_utils.get_view_layer_objects()


    requires_single_principled_bsdf = False
    for bake_type in settings.bake_types:
        if isinstance(bake_type, bake_settings._Bake_Type):
            requires_single_principled_bsdf |= bake_type._requires_principled_bsdf
        else:
            for sub_type in bake_type:
                requires_single_principled_bsdf |= sub_type._requires_principled_bsdf


    for object in objects:

        if len(object.data.polygons) == 0:
            do_warning(f"Object has no polygons: {object.name_full}", do_raise=settings.raise_warnings)

        if object not in view_layer_objects:
            do_warning(f"Object is not in the scene: {object.name_full}", do_raise=settings.raise_warnings)

        if object.display_type in ('BOUNDS', 'WIRE'):
            do_warning(f"Object is displayed as bounds or wire: {object.name_full}")

        if not object.material_slots:
            do_warning(f"Object does not have materials: {object.name_full}", do_raise=settings.raise_warnings)

        for slot in object.material_slots:

            material = slot.material

            if material:

                if bpy.app.version < (5, 0) and not material.use_nodes:
                    do_warning(f"Object's material does not use nodes: {object.name_full}, {material.name_full}")

                if not material.node_tree:
                    do_warning(f"Material does not have a node tree: {object.name_full}, {material.name_full}")
                    continue

                report_missing_attributes(material.node_tree, object, do_raise=settings.raise_warnings)
                report_missing_files(material.node_tree, do_raise=settings.raise_warnings)

                if requires_single_principled_bsdf:

                    tree = bpy_node.Shader_Tree_Wrapper(material.node_tree)

                    shader_node = tree.output['Surface']

                    if shader_node is None or not shader_node.be('ShaderNodeBsdfPrincipled'):
                        do_error(f"A single Principled BSDF is required: {material.name_full}")

            else:
                do_warning(f"The material socket {repr(slot)} of the object {object.name_full} does not have a material assigned.", do_raise=settings.raise_warnings)

                if requires_single_principled_bsdf:
                    do_error(f"A single Principled BSDF is required: {repr(slot)}")


    settings._images = []
    settings._raw_images = []

    active_object = bpy.context.view_layer.objects.active

    if settings.isolate_objects:
        Focus = bpy_context.Isolate_Focus
    else:
        Focus = bpy_context.Focus

    with bpy_context.Bake_Settings(settings), bpy_context.Global_Optimizations(), Focus(objects), bpy_context.State() as state:


        if settings.use_selected_to_active:

            bpy.context.view_layer.objects.active = active_object

            if settings.cage_object_name:
                # Cage object "CAGE" not found in evaluated scene, it may be hidden
                # TODO: check if it can fail in other ways
                cage_object = bpy.data.objects[settings.cage_object_name]
                if not bpy.context.scene.collection in cage_object.users_collection:
                    bpy.context.scene.collection.objects.link(cage_object)


        # ensure object render visibility
        for object in objects:

            if object.animation_data:
                # drivers can modify render visibility
                for driver in object.animation_data.drivers:
                    state.set(driver, 'mute', True)

            state.set(object, 'hide_render', False)


        # set smart interpolation
        if settings.use_smart_texture_interpolation:
            for material in bpy_utils.get_unique_materials(objects):
                set_all_image_nodes_interpolation_to_smart(material.node_tree, state)


        # set active uv layer
        for object in objects:

            if settings.use_selected_to_active and bpy.context.view_layer.objects.active != object:
                continue

            try:
                uv_map = object.data.uv_layers[settings.uv_layer_name]
            except KeyError as e:
                raise Exception(f"UV map '{settings.uv_layer_name}' for baking is missing in object: {object.name_full}") from e

            state.set(object.data.uv_layers, 'active', uv_map)


        # bake objects
        if settings.merge_materials_between_objects:

            if len(objects) > 1:
                # ⚓ T83971 Blender baking's margin overlap if multiple meshes are selected
                # https://developer.blender.org/T83971
                state.set(bpy.context.scene.render.bake, 'margin', min(1, settings.margin))

            bake_objects(objects, settings)

        else:
            for object in objects:
                with Focus(object):
                    bake_objects([object], settings)


    # overall report
    print_done(f'Baking of {len(objects)} objects is done in {round(time.perf_counter() - bake_start_time, 2)} secs.')


    return settings._images
