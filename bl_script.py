def _ensure_site_packages(packages):
    """ `packages`: list of tuples (<import name>, <pip name>) """
    
    if not packages:
        return

    import sys
    import bpy
    import site
    import importlib
    import importlib.util

    user_site_packages = site.getusersitepackages()
    if not user_site_packages in sys.path:
        sys.path.append(user_site_packages)

    modules_to_install = [module[1] for module in packages if not importlib.util.find_spec(module[0])]
    if not modules_to_install:
        return

    if bpy.app.version < (2,91,0):
        python_binary = bpy.app.binary_path_python
    else:
        python_binary = sys.executable
        
    import subprocess
    subprocess.run([python_binary, '-m', 'ensurepip'], check=True)
    subprocess.run([python_binary, '-m', 'pip', 'install', *modules_to_install, "--user"], check=True)
    
    importlib.invalidate_caches()


def _set_builtins():
    
    import sys
    import builtins

    import bpy
    from bpy.app.handlers import persistent

    builtins.get_job = lambda: builtins.__job__

    builtins.get_args = lambda: sys.argv[sys.argv.index('--') + 1:]

    builtins._blend_index = -1
    builtins.get_blend_index = lambda: builtins._blend_index

    @persistent
    def increase_blend_index(dummy):
        builtins._blend_index += 1

    bpy.app.handlers.load_pre.append(increase_blend_index)


def _import_module_from_file(file_path: str, module_name: str):
    import sys
    import importlib.util

    spec = importlib.util.spec_from_file_location(module_name, file_path)
    module = importlib.util.module_from_spec(spec)

    sys.modules[module_name] = module
    spec.loader.exec_module(module)


def duplicates_make_real():
    import bpy

    if bpy.app.version > (2,80,0):
        select = lambda object: object.select_set(True)
    else:
        select = lambda object: setattr(object, 'select', True)

    for object in bpy.data.objects:

        if not any(modifier for modifier in object.modifiers if modifier.type == 'PARTICLE_SYSTEM' and modifier.show_viewport):
            continue
                
        bpy.ops.object.select_all(action='DESELECT')
        select(object)

        bpy.ops.object.duplicates_make_real()


def add_actions_to_nla():
    """ from blend2bam """
    # https://github.com/Moguri/blend2bam/blob/master/blend2bam/blend2gltf/blender28_script.py

    import bpy

    def can_object_use_action(obj, action):
        for fcurve in action.fcurves:
            path = fcurve.data_path
            if not path.startswith('pose'):
                return obj.animation_data is not None

            if obj.type == 'ARMATURE':
                path = path.split('["')[-1]
                path = path.split('"]')[0]
                if path in [bone.name for bone in obj.data.bones]:
                    return True

        return False

    armature_objects = [
        obj
        for obj in bpy.data.objects
        if obj.type == 'ARMATURE' and obj.animation_data and not obj.animation_data.nla_tracks
    ]

    for obj in armature_objects:
        try:
            obj.select_set(True)
            actions = [
                action
                for action in bpy.data.actions
                if can_object_use_action(obj, action)
            ]
            for action in actions:
                tracks = obj.animation_data.nla_tracks
                track = tracks.new()
                track.strips.new(action.name, 0, action)
        except RuntimeError as error:
            print('Failed to auto-add actions to NLA for {}: {}'.format(obj.name, error))


def apply_scale():
    """ apply object scale, non uniform scale cause bugs in bullet physics """

    import bpy
    from mathutils import Matrix

    for object in bpy.data.objects.values():

        translation, rotation, scale = object.matrix_basis.decompose()

        scale_matrix = Matrix.Diagonal(scale).to_4x4()
            
        if hasattr(object.data, "transform"):
            object.data.transform(scale_matrix)

        for child in object.children:
            child.matrix_local = scale_matrix @ child.matrix_local
            
        object.matrix_basis = Matrix.Translation(translation) @ rotation.to_matrix().to_4x4()