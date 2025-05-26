import bpy
import sys
import os
import argparse
import json

parser = argparse.ArgumentParser()
parser.add_argument('-caller_script_dir')

args = sys.argv[sys.argv.index('--') + 1:]
args = parser.parse_args(args)


job: dict = get_job() # type: ignore


def export_physics(gltf_data, settings):
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
            meshref = [
                idx
                for idx, mesh in enumerate(gltf_data['meshes'])
                if mesh['name'] == obj.data.name
            ][0]
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
        collection = settings['invisible_collisions_collection']
        if any(x.name == collection for x in obj.users_collection) and "mesh" in gltf_node:
            del gltf_node["mesh"]


def unquote_image_uri(gltf_data):

    from urllib.parse import unquote

    for img in gltf_data.get('images', []):

        uri = img.get('uri')
        if not uri:
            # print(f'No URI in: {img}')
            continue

        img['uri'] = unquote(uri)

def get_image_path(name):
    image = bpy.data.images.get(name)

    if not image:
        return None

    if image.source != 'FILE':
        return None

    return bpy.path.abspath(image.filepath, library = image.library)

def unquote_and_repath(gltf_data: dict, blend_path: str, gltf_path: str, bam_path: str):
    """
    fixing image URIs when converting with 'ref' so they will point to the place the .blend file uses them
    """

    from urllib.parse import unquote

    blend_dir = os.path.dirname(blend_path)
    bam_dir = os.path.dirname(bam_path)
    gltf_dir = os.path.dirname(gltf_path)

    for img in gltf_data.get('images', ()):

        path = get_image_path(img['name'])
        if not path:
            print(f"No Blender image from file by name: {img}")
            continue
        
        uri = img.get('uri')
        if uri:
            path_from_uri = os.path.abspath(os.path.join(gltf_dir, unquote(uri).replace('/', os.sep)))
            try:
                os.path.samefile(path, path_from_uri)
            except:
                import traceback
                traceback.print_exc()
                raise BaseException(f"{path} and {path_from_uri} are different files or do not exist.")

        try:
            path = os.path.relpath(path, bam_dir)
        except ValueError:
            path = os.path.abspath(path)
        
        img['uri'] = path


def export_gltf(settings: dict, blend_path: str, gltf_path: str, bam_path: str, blender_gltf_settings: dict = None):

    target_dir = os.path.dirname(gltf_path)
    os.makedirs(target_dir, exist_ok=True)

    gltf_settings = dict(
        filepath = gltf_path,

        export_format = 'GLTF_EMBEDDED' if settings['textures'] == 'embed' else 'GLTF_SEPARATE',
        export_animations = settings['animations'] != 'skip',

        export_cameras = True,
        export_extras = True,
        export_yup = False,
        export_lights = True,
        export_force_sampling = True,
        export_apply = True,
        export_tangents = True,

        export_keep_originals = settings['textures'] == 'ref'
    )

    if blender_gltf_settings:
        gltf_settings.update(blender_gltf_settings)

    bpy.ops.export_scene.gltf(**gltf_settings)

    with open(gltf_path) as gltf_file:
        gltf_data = json.load(gltf_file)

    export_physics(gltf_data, settings)

    if settings['textures'] == 'ref':
        unquote_and_repath(gltf_data, blend_path, gltf_path, bam_path)
    elif settings['textures'] == 'copy':
        unquote_image_uri(gltf_data)

    with open(gltf_path, 'w') as gltf_file:
        json.dump(gltf_data, gltf_file)


export_gltf(job['settings_gltf'], bpy.data.filepath, job['dst'], job['bam_dst'], job['settings_blender_gltf'])