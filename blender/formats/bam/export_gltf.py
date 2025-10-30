import json
import os
import typing

import bpy

if typing.TYPE_CHECKING:
    __KWARGS__: dict
    __GLTF_PATH__: str


def export_physics(gltf_data, invisible_collisions_collection: str):
    """ https://github.com/Moguri/blend2bam/blob/master/blend2bam/blend2gltf/blender28_script.py """

    physics_extensions = ['BLENDER_physics', 'PANDA3D_physics_collision_shapes']
    gltf_data.setdefault('extensionsUsed', []).extend(physics_extensions)


    objs = [
        (bpy.data.objects[gltf_node['name']], gltf_node)
        for gltf_node in gltf_data['nodes']
        if gltf_node['name'] in bpy.data.objects
    ]

    objs = [
        i for i in objs
        if getattr(i[0], 'rigid_body')
    ]

    for obj, gltf_node in objs:
        if 'extensions' not in gltf_node:
            gltf_node['extensions'] = {}

        rbody = obj.rigid_body
        bounds = [obj.dimensions[i] / gltf_node.get('scale', (1, 1, 1))[i] for i in range(3)]
        collision_layers = sum(layer << i for i, layer in enumerate(rbody.collision_collections))
        shape_type = rbody.collision_shape.upper()
        if shape_type in ('CONVEX_HULL', 'MESH'):
            meshrefs = [idx for idx, mesh in enumerate(gltf_data.get('meshes', ())) if mesh['name'] == obj.data.name]
            if not meshrefs:
                continue
            meshref = meshrefs[0]
        else:
            meshref = None

        # BLENDER_physics
        physics = {
            'collisionShapes': [{
                'shapeType': shape_type,
                'boundingBox': bounds,
                'primaryAxis': "Z",
            }],
            'mass': rbody.mass,
            'static': rbody.type == 'PASSIVE',
            'collisionGroups': collision_layers,
            'collisionMasks': collision_layers,
        }
        if meshref is not None:
            physics['collisionShapes'][0]['mesh'] = meshref
        gltf_node['extensions']['BLENDER_physics'] = physics

        # PANDA3D_physics_collision_shapes
        collision_shapes = {
            'shapes': [{
                'type': shape_type,
                'boundingBox': bounds,
                'primaryAxis': "Z",
            }],
            'groups': collision_layers,
            'masks': collision_layers,
            'intangible': rbody.type == 'PASSIVE',
        }
        if meshref is not None:
            collision_shapes['shapes'][0]['mesh'] = meshref
        gltf_node['extensions']['PANDA3D_physics_collision_shapes'] = collision_shapes

        # Remove the visible mesh from the gltf_node if the object
        # is in a specific collection
        if any(x.name == invisible_collisions_collection for x in obj.users_collection) and "mesh" in gltf_node:
            del gltf_node["mesh"]



def get_block_realpath(block: typing.Union[bpy.types.Image, bpy.types.Library]):
    return os.path.realpath(bpy.path.abspath(block.filepath, library = block.library))


def get_image_path(name):

    # TODO: what if image is from a library
    image = bpy.data.images.get(name)

    if not image:
        return None

    if image.source != 'FILE':
        return None

    return os.path.realpath(bpy.path.abspath(image.filepath, library = image.library))


def validate_image_paths(gltf_data: dict, gltf_path: str):

    from urllib.parse import unquote, quote

    gltf_dir = os.path.dirname(gltf_path)

    for img in gltf_data.get('images', ()):

        path = get_image_path(img['name'])
        if not path:
            print(f"No Blender image for the image by name: {img}")
            continue

        uri = img.get('uri')
        if uri:
            path_from_uri = os.path.abspath(os.path.join(gltf_dir, unquote(uri).replace('/', os.sep)))
            try:
                os.path.samefile(path, path_from_uri)
            except Exception as e:
                raise Exception(f"{path} and {path_from_uri} are different files or do not exist.") from e

        try:
            # https://github.com/Moguri/panda3d-gltf/blob/95e2621d21792d522b5c939251f07a01259ffd69/gltf/cli.py#L121
            # converter = Converter(src, settings=settings)
            # https://github.com/Moguri/panda3d-gltf/blob/95e2621d21792d522b5c939251f07a01259ffd69/gltf/_converter.py#L133
            # self.filedir = Filename(filepath.get_dirname())
            # https://github.com/Moguri/panda3d-gltf/blob/95e2621d21792d522b5c939251f07a01259ffd69/gltf/_converter.py#L611
            # fulluri = Filename(self.filedir, uri)
            # path = os.path.relpath(path, gltf_dir)
            path = os.path.abspath(path)
        except ValueError as e:
            raise Exception(f"The image path must be relative to the glTF file: {path} {gltf_dir}") from e

        img['uri'] = quote(path)



def export_gltf():

    result_dir = os.path.dirname(__GLTF_PATH__)
    os.makedirs(result_dir, exist_ok=True)

    rna_type = bpy.ops.export_scene.gltf.get_rna_type()
    export_options_keys = rna_type.properties.keys()
    export_format_options = [item.identifier for item in rna_type.properties['export_format'].enum_items_static]

    from blend_converter.format import bam

    gltf_settings = bam.Settings_Blender_Gltf._from_dict(__KWARGS__['gltf_settings'])
    gltf2bam_settings = bam.Settings_Gltf_2_Bam._from_dict(__KWARGS__['gltf2bam_settings'])


    gltf_settings.export_animations = gltf2bam_settings.animations != 'skip'


    if gltf2bam_settings.textures == 'embed':
        if 'GLTF_EMBEDDED' in export_format_options:
            gltf_settings.export_format = 'GLTF_EMBEDDED'
        else:
            print("GLTF_EMBEDDED option is not supported.")


    if 'export_keep_originals' in export_options_keys:
        gltf_settings.export_keep_originals = gltf2bam_settings.textures == 'ref'
    if 'use_mesh_edges' in export_options_keys:
        gltf_settings.use_mesh_edges = True
    if 'use_mesh_vertices' in export_options_keys:
        gltf_settings.use_mesh_vertices = True
    if 'export_optimize_animation_size' in export_options_keys:
        gltf_settings.export_optimize_animation_size = False
    if 'convert_lighting_mode' in export_options_keys:
        gltf_settings.convert_lighting_mode = 'RAW'
    if 'export_import_convert_lighting_mode' in export_options_keys:
        gltf_settings.export_import_convert_lighting_mode = 'RAW'
    if 'export_try_sparse_sk' in export_options_keys:
        gltf_settings.export_try_sparse_sk = False


    if 'export_keep_originals' in export_options_keys:

        # case if the setting are getting updated
        if gltf2bam_settings.textures == 'ref' and gltf_settings.export_keep_originals == False:
            message = "Cannot reference textures that will being deleted with the temporal glTF file when `export_keep_originals == False`. When `export_keep_originals == False` use `textures == 'copy'`."
            print('Warning:', message)
            gltf_settings.export_keep_originals = True
            # raise Exception(message)


        if gltf_settings.export_keep_originals or gltf2bam_settings.textures == 'ref':
            for image in bpy.data.images:
                if image.filepath:
                    try:
                        os.path.relpath(os.path.realpath(__GLTF_PATH__), get_block_realpath(image))
                    except ValueError as e:
                        gltf_settings.export_keep_originals = False
                        gltf2bam_settings.textures = 'copy'
                        message = f"Cannot export a gltf keeping an original image with no possible relative path to the gltf file being written: {image} {image.filepath}"
                        print('Warning:', message)
                        # raise Exception(message) from e


    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter('default')

        gltf_settings_dict = gltf_settings._to_dict()

        print("GLTF:", gltf_settings_dict)

        bpy.ops.export_scene.gltf(filepath = __GLTF_PATH__, **gltf_settings_dict)


    with open(__GLTF_PATH__) as gltf_file:
        gltf_data = json.load(gltf_file)

    export_physics(gltf_data, gltf2bam_settings.invisible_collisions_collection)

    if gltf2bam_settings.textures in ('ref', 'copy'):
        validate_image_paths(gltf_data, __GLTF_PATH__)

    with open(__GLTF_PATH__, 'w') as gltf_file:
        json.dump(gltf_data, gltf_file)


export_gltf()
