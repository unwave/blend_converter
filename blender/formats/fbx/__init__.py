import typing


if __spec__.name == __name__:
    from blend_converter.blender.formats.fbx.export_fbx import export_fbx
    from blend_converter import tool_settings
else:
    from .export_fbx import export_fbx
    from .... import tool_settings


if typing.TYPE_CHECKING:
    import dataclasses
else:
    class dataclasses:
        dataclass = lambda x: x


@dataclasses.dataclass
class Settings_Fbx(tool_settings.Settings):
    """ Official Blender FBX Exporter `4.29.1` """


    allow_missing_settings = True


    check_existing: bool
    """
    Check Existing

    Check and warn on overwriting existing files

    Blender Property Options: `{'HIDDEN'}`

    #### Default: `True`
    """


    filter_glob: str
    """
    Blender Property Options: `{'HIDDEN'}`

    #### Default: `'*.fbx'`
    """

    use_selection: bool
    """
    Selected Objects

    Export selected and visible objects only

    #### Default: `False`
    """

    use_active_collection: bool
    """
    Active Collection

    Export only objects from the active collection (and its children)

    #### Default: `False`
    """

    global_scale: float
    """
    Scale

    Scale all data (Some importers do not support scaled armatures!)

    Soft Min: `0.01`
    Soft Max: `1000.0`
    Min: `0.001`
    Max: `1000.0`

    #### Default: `1.0`
    """

    apply_unit_scale: bool
    """
    Apply Unit

    Take into account current Blender units settings (if unset, raw Blender Units values are used as-is)

    #### Default: `True`
    """

    apply_scale_options: str
    """
    Apply Scalings

    How to apply custom and units scalings in generated FBX file (Blender uses FBX scale to detect units on import, but many other applications do not handle the same way)

    Options:
    * `FBX_SCALE_NONE`: All Local, Apply custom scaling and units scaling to each object transformation, FBX scale remains at 1.0
    * `FBX_SCALE_UNITS`: FBX Units Scale, Apply custom scaling to each object transformation, and units scaling to FBX scale
    * `FBX_SCALE_CUSTOM`: FBX Custom Scale, Apply custom scaling to FBX scale, and units scaling to each object transformation
    * `FBX_SCALE_ALL`: FBX All, Apply custom scaling and units scaling to FBX scale

    #### Default: `None`
    """

    use_space_transform: bool
    """
    Use Space Transform

    Apply global space transform to the object rotations. When disabled only the axis space is written to the file and all object transforms are left as-is

    #### Default: `True`
    """

    bake_space_transform: bool
    """
    Apply Transform

    Bake space transform into object data, avoids getting unwanted rotations to objects when target space is not aligned with Blender's space (WARNING! experimental option, use at own risks, known broken with armatures/animations)

    #### Default: `False`
    """

    object_types: typing.Set[str]
    """
    Object Types

    Which kind of object to export

    Options:
    * `EMPTY`: Empty
    * `CAMERA`: Camera
    * `LIGHT`: Lamp
    * `ARMATURE`: Armature, WARNING: not supported in dupli/group instances
    * `MESH`: Mesh
    * `OTHER`: Other, Other geometry types, like curve, metaball, etc. (converted to meshes)

    Blender Property Options: `{'ENUM_FLAG'}`

    #### Default: `{'EMPTY', 'ARMATURE', 'MESH', 'OTHER', 'LIGHT', 'CAMERA'}`
    """

    use_mesh_modifiers: bool
    """
    Apply Modifiers

    Apply modifiers to mesh objects (except Armature ones) - WARNING: prevents exporting shape keys

    #### Default: `True`
    """

    use_mesh_modifiers_render: bool
    """
    Use Modifiers Render Setting

    Use render settings when applying modifiers to mesh objects (DISABLED in Blender 2.8)

    #### Default: `True`
    """

    mesh_smooth_type: str
    """
    Smoothing

    Export smoothing information (prefer 'Normals Only' option if your target importer understand split normals)

    Options:
    * `OFF`: Normals Only, Export only normals instead of writing edge or face smoothing data
    * `FACE`: Face, Write face smoothing
    * `EDGE`: Edge, Write edge smoothing

    #### Default: `'OFF'`
    """

    use_subsurf: bool
    """
    Export Subdivision Surface

    Export the last Catmull-Rom subdivision modifier as FBX subdivision (does not apply the modifier even if 'Apply Modifiers' is enabled)

    #### Default: `False`
    """

    use_mesh_edges: bool
    """
    Loose Edges

    Export loose edges (as two-vertices polygons)

    #### Default: `False`
    """

    use_tspace: bool
    """
    Tangent Space

    Add binormal and tangent vectors, together with normal they form the tangent space (will only work correctly with tris/quads only meshes!)

    #### Default: `False`
    """

    use_custom_props: bool
    """
    Custom Properties

    Export custom properties

    #### Default: `False`
    """

    add_leaf_bones: bool
    """
    Add Leaf Bones

    Append a final bone to the end of each chain to specify last bone length (use this when you intend to edit the armature from exported data)

    #### Default: `True`
    """

    primary_bone_axis: str
    """
    Primary Bone Axis

    Options:
    * `X`: X Axis
    * `Y`: Y Axis
    * `Z`: Z Axis
    * `-X`: -X Axis
    * `-Y`: -Y Axis
    * `-Z`: -Z Axis

    #### Default: `'Y'`
    """

    secondary_bone_axis: str
    """
    Secondary Bone Axis

    Options:
    * `X`: X Axis
    * `Y`: Y Axis
    * `Z`: Z Axis
    * `-X`: -X Axis
    * `-Y`: -Y Axis
    * `-Z`: -Z Axis

    #### Default: `'X'`
    """

    use_armature_deform_only: bool
    """
    Only Deform Bones

    Only write deforming bones (and non-deforming ones when they have deforming children)

    #### Default: `False`
    """

    armature_nodetype: str
    """
    Armature FBXNode Type

    FBX type of node (object) used to represent Blender's armatures (use Null one unless you experience issues with other app, other choices may no import back perfectly in Blender...)

    Options:
    * `NULL`: Null, 'Null' FBX node, similar to Blender's Empty (default)
    * `ROOT`: Root, 'Root' FBX node, supposed to be the root of chains of bones...
    * `LIMBNODE`: LimbNode, 'LimbNode' FBX node, a regular joint between two bones...

    #### Default: `'NULL'`
    """

    bake_anim: bool
    """
    Baked Animation

    Export baked keyframe animation

    #### Default: `True`
    """

    bake_anim_use_all_bones: bool
    """
    Key All Bones

    Force exporting at least one key of animation for all bones (needed with some target applications, like UE4)

    #### Default: `True`
    """

    bake_anim_use_nla_strips: bool
    """
    NLA Strips

    Export each non-muted NLA strip as a separated FBX's AnimStack, if any, instead of global scene animation

    #### Default: `True`
    """

    bake_anim_use_all_actions: bool
    """
    All Actions

    Export each action as a separated FBX's AnimStack, instead of global scene animation (note that animated objects will get all actions compatible with them, others will get no animation at all)

    #### Default: `True`
    """

    bake_anim_force_startend_keying: bool
    """
    Force Start/End Keying

    Always add a keyframe at start and end of actions for animated channels

    #### Default: `True`
    """

    bake_anim_step: float
    """
    Sampling Rate

    How often to evaluate animated values (in frames)

    Soft Min: `0.1`
    Soft Max: `10.0`
    Min: `0.01`
    Max: `100.0`

    #### Default: `1.0`
    """

    bake_anim_simplify_factor: float
    """
    Simplify

    How much to simplify baked values (0.0 to disable, the higher the more simplified)

    Soft Min: `0.0`
    Soft Max: `10.0`
    Min: `0.0`
    Max: `100.0`

    #### Default: `1.0`
    """

    path_mode: str
    """
    Path Mode

    Method used to reference paths

    Options:
    * `AUTO`: Auto, Use Relative paths with subdirectories only
    * `ABSOLUTE`: Absolute, Always write absolute paths
    * `RELATIVE`: Relative, Always write relative paths (where possible)
    * `MATCH`: Match, Match Absolute/Relative setting with input path
    * `STRIP`: Strip Path, Filename only
    * `COPY`: Copy, Copy the file to the destination path (or subdirectory)

    #### Default: `'AUTO'`
    """

    embed_textures: bool
    """
    Embed Textures

    Embed textures in FBX binary file (only for "Copy" path mode!)

    #### Default: `False`
    """

    batch_mode: str
    """
    Batch Mode

    Options:
    * `OFF`: Off, Active scene to file
    * `SCENE`: Scene, Each scene as a file
    * `COLLECTION`: Collection, Each collection (data-block ones) as a file, does not include content of children collections
    * `SCENE_COLLECTION`: Scene Collections, Each collection (including master, non-data-block ones) of each scene as a file, including content from children collections
    * `ACTIVE_SCENE_COLLECTION`: Active Scene Collections, Each collection (including master, non-data-block one) of the active scene as a file, including content from children collections

    #### Default: `None`
    """

    use_batch_own_dir: bool
    """
    Batch Own Dir

    Create a dir for each exported file

    #### Default: `True`
    """

    use_metadata: bool
    """
    Use Metadata

    Blender Property Options: `{'HIDDEN'}`

    #### Default: `True`
    """

    axis_forward: str
    """
    Forward

    Options:
    * `X`: X Forward
    * `Y`: Y Forward
    * `Z`: Z Forward
    * `-X`: -X Forward
    * `-Y`: -Y Forward
    * `-Z`: -Z Forward

    #### Default: `'-Z'`
    """

    axis_up: str
    """
    Up

    Options:
    * `X`: X Up
    * `Y`: Y Up
    * `Z`: Z Up
    * `-X`: -X Up
    * `-Y`: -Y Up
    * `-Z`: -Z Up

    #### Default: `'Y'`
    """
