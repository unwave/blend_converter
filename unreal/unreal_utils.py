"""
This should be run in Unreal Engine.
The current functionality is too rigid, was created for testing purposes.
Copy the file and edit.
"""

import sys
import typing
import os
import time


import unreal


from blend_converter import tool_settings


if typing.TYPE_CHECKING:
    # need only __init__ hints
    import dataclasses

    import typing_extensions
else:
    class dataclasses:
        dataclass = lambda x: x


def import_texture(os_path: str, ue_dir: str, name: typing.Optional[str] = None) -> 'unreal.Texture':

    if name:
        dest_ue_name = name
    else:
        dest_ue_name = os.path.splitext(os.path.basename(os_path))[0]

    task = unreal.AssetImportTask()

    task.automated = True
    task.replace_existing = True
    task.save = True

    task.filename = os_path
    task.destination_path = ue_dir
    task.destination_name = dest_ue_name

    factory = unreal.TextureFactory()

    task.factory = factory
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])

    return unreal.load_asset(unreal.Paths.combine([ue_dir, dest_ue_name]))


def is_in_memory_asset(asset_path: str):
    """ For debugging. """
    asset_registry: unreal.AssetRegistry = unreal.AssetRegistryHelpers.get_asset_registry()
    asset_registry.scan_files_synchronous([asset_path], force_rescan=True)
    return asset_registry.get_asset_by_object_path(asset_path, include_only_on_disk_assets=True) == asset_registry.get_asset_by_object_path(asset_path, include_only_on_disk_assets=False)



@dataclasses.dataclass
class Settings_Unreal_Material_Instance(tool_settings.Settings):

    # https://forums.unrealengine.com/t/setting-static-switch-parameters-of-a-material-instance-in-python/136415
    PARENT_MATERIAL_INSTANCE_WITH_NORMALS = "/Game/Materials/MI_main_orm_with_normal"
    PARENT_MATERIAL_INSTANCE_WITHOUT_NORMALS = "/Game/Materials/MI_main_orm_without_normal"


    name: str = ''
    dir: str = ''

    base_color_filepath: str = ''
    _base_color_param_name: str = 'Base Color'

    orm_filepath: str = ''
    _orm_param_name: str = 'ORM'

    normal_filepath: str = ''
    _normal_param_name: str = 'Normal'

    # not implemented
    # emission_filepath: str = ''
    # _emission_param_name: str = 'Emission'


    @property
    def _asset_path(self):
        return unreal.Paths.combine([self.dir, self.name])


def create_material_instance(settings: Settings_Unreal_Material_Instance):

    unreal.EditorAssetLibrary.make_directory(settings.dir)

    if is_in_memory_asset(settings._asset_path):
        raise Exception(f"In memory asset, restart Unreal Engine: {settings._asset_path}")  # TODO: testing


    do_replace = unreal.EditorAssetLibrary.does_asset_exist(settings._asset_path)
    if do_replace:
        asset_name = settings.name + f"_TEMP_{time.strftime('%Y%m%d_%H%M%S')}"
    else:
        asset_name = settings.name


    factory = unreal.MaterialInstanceConstantFactoryNew()
    material_instance: unreal.MaterialInstanceConstant = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
        asset_name=asset_name,
        package_path=settings.dir,
        asset_class=unreal.MaterialInstanceConstant,
        factory=factory,
    )


    if not material_instance:
        raise Exception(f"Fail to create Material Instance: {settings._asset_path}")


    if settings.normal_filepath:
        material_instance.set_editor_property('parent', unreal.load_asset(settings.PARENT_MATERIAL_INSTANCE_WITH_NORMALS))

        normal_texture = import_texture(settings.normal_filepath, settings.dir)
        normal_texture.compression_settings = unreal.TextureCompressionSettings.TC_NORMALMAP
        normal_texture.flip_green_channel = True
        normal_texture.srgb = False
        unreal.MaterialEditingLibrary.set_material_instance_texture_parameter_value(material_instance, settings._normal_param_name, normal_texture)
    else:
        material_instance.set_editor_property('parent', unreal.load_asset(settings.PARENT_MATERIAL_INSTANCE_WITHOUT_NORMALS))


    base_color_texture = import_texture(settings.base_color_filepath, settings.dir)
    base_color_texture.compression_settings = unreal.TextureCompressionSettings.TC_DEFAULT
    unreal.MaterialEditingLibrary.set_material_instance_texture_parameter_value(material_instance, settings._base_color_param_name, base_color_texture)


    orm_texture = import_texture(settings.orm_filepath, settings.dir)
    orm_texture.compression_settings = unreal.TextureCompressionSettings.TC_DEFAULT
    orm_texture.srgb = False
    unreal.MaterialEditingLibrary.set_material_instance_texture_parameter_value(material_instance, settings._orm_param_name, orm_texture)


    # if settings.emission_filepath:
    #     texture = import_texture(settings.emission_filepath, settings.dir)
    #     texture.compression_settings = unreal.TextureCompressionSettings.TC_DEFAULT
    #     unreal.MaterialEditingLibrary.set_material_instance_texture_parameter_value(material_instance, settings.orm_param_name, texture)
    # else:
    #     unreal.MaterialEditingLibrary.set_material_instance_static_switch_parameter_value(material_instance, settings.use_emission_param_name, False)


    unreal.EditorAssetLibrary.save_asset(material_instance.get_full_name())

    def save(asset_path: str):
        if type(asset_path) is str and unreal.EditorAssetLibrary.does_asset_exist(asset_path):
            return unreal.EditorAssetLibrary.save_asset(asset_path)

    if do_replace:
        old_asset = unreal.load_asset(settings._asset_path)
        if old_asset:
            unreal.EditorAssetLibrary.consolidate_assets(material_instance, [old_asset])
            # https://forums.unrealengine.com/t/fix-redirectors-via-python/124785
            unreal.EditorAssetLibrary.delete_asset(settings._asset_path)  # deleting redirect
            unreal.EditorAssetLibrary.rename_asset(material_instance.get_full_name(), settings._asset_path)
        else:
            # not tested
            unreal.EditorAssetLibrary.delete_asset(settings._asset_path)
            unreal.EditorAssetLibrary.rename_asset(material_instance.get_full_name(), settings._asset_path)


    unreal.log(f"Materials Instance created: {settings}")

    return material_instance



@dataclasses.dataclass
class Settings_Unreal_Static_Mesh(tool_settings.Settings):

    os_path: str = ''
    dir: str = ''
    name: str = ''


def import_static_mesh(settings: Settings_Unreal_Static_Mesh):

    options = unreal.FbxImportUI()

    options.import_mesh = True
    options.import_textures = False
    options.import_materials = False
    options.import_as_skeletal = False
    options.import_animations = False

    static_mesh_import_data: unreal.FbxStaticMeshImportData = options.static_mesh_import_data
    static_mesh_import_data.combine_meshes = True


    task = unreal.AssetImportTask()

    task.automated = True
    task.replace_existing = True
    task.save = True

    task.options = options

    task.filename = settings.os_path
    task.destination_path = settings.dir
    task.destination_name = settings.name


    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])

    unreal.log(f"Static Mesh imported: {settings}")


    return unreal.load_asset(unreal.Paths.combine([settings.dir, settings.name]))
