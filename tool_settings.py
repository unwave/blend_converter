import os
import re
import inspect
import functools
import textwrap
import tempfile
import json
import typing
import traceback

ROOT_DIR = os.path.dirname(os.path.realpath(__file__))


SENTINEL = object()


DEFAULT_UV_LAYER_NAME = '__bc_uv'


if typing.TYPE_CHECKING:
    # need only __init__ hints
    import dataclasses

    import typing_extensions
else:
    class dataclasses:
        dataclass = lambda x: x


if typing.TYPE_CHECKING:
    import idprop
    import bpy


RE_ATTR = re.compile(r'([a-zA-Z0-9_]+):\s*(.+?)\s*=\s*(.+)\s*\n\s*"""([\w\W]+?)"""')
RE_ATTR_ENTRY = re.compile(r'^`(.+?)`\s*:\s*`(.+?)`$')
RE_ATTR_DEFAULT_ENTRY = re.compile(r'^#### Default: `(.+?)`$')
RE_ATTR_ENUM_ENTRY = re.compile(r'^\* `(.+?)`\s*:\s*(.+?)\s*—\s*(.+)*$')


def is_json_serializable(object):
    try:
        json.dumps(object)
    except json.JSONDecodeError:
        return False
    else:
        return True


def get_qualified_value(value: str):

    if value.startswith(('\'', '\"')):
        return value[1:-1]
    if ',' in value:
        return tuple(get_qualified_value(v.strip()) for v in value.split(','))
    elif value == 'False':
        return False
    elif value == 'True':
        return True
    elif '.' in value:
        return float(value)
    else:
        return int(value)


def get_qualified_attr_property(key: str, value: str):

    if key == 'cmd':  # how the parameter is specified for the underlying tool
        if value.lower() == 'none':
            return key, None
        else:
            assert value.startswith('-')
            return key, value
    elif key in ('max', 'min', 'soft_min', 'soft_max'):  # Blender UI parameters
        return key, get_qualified_value(value)
    elif key == 'subtype':  # Blender string property subtype
        return key, get_qualified_value(value)
    else:
        raise ValueError(f"Unexpected key and value pare: {key} = {value}")


def get_blender_prop_specs(default_value, attribute_properties: dict):

    try:
        parameters = dict(default=default_value, description=attribute_properties['description'], subtype=attribute_properties.get('subtype', 'NONE'))
    except KeyError as e:
        raise Exception(f"Requeued specifications missing in: {attribute_properties}") from e
    default_type = type(default_value)

    if default_type is bool:
        return dict(type='BoolProperty', kwargs=parameters)

    elif default_type is int:
        for _key, _value in attribute_properties.items():
            if _key in ('min', 'max', 'soft_min', 'soft_max'):
                parameters[_key] = _value
        return dict(type='IntProperty', kwargs=parameters)

    elif default_type is float:
        for _key, _value in attribute_properties.items():
            if _key in ('min', 'max', 'soft_min', 'soft_max'):
                parameters[_key] = _value
        return dict(type='FloatProperty', kwargs=parameters)

    elif default_type is tuple:
        parameters['size'] = len(default_value)
        return dict(type='FloatVectorProperty', kwargs=parameters)

    elif default_type is str:
        if 'enum_items' in attribute_properties:
            parameters['items'] = [(item[0], item[1], item[2], index) for index, item in enumerate(attribute_properties['enum_items'])]
            parameters.pop('subtype')  #TypeError: 'subtype' is an invalid keyword argument for EnumProperty()
            return dict(type='EnumProperty', kwargs=parameters)
        else:
            return dict(type='StringProperty', kwargs=parameters)

    elif is_json_serializable(default_value):
        parameters['default'] = json.dumps(default_value)
        return dict(type='StringProperty', is_json=True, kwargs=parameters)

    else:
        raise Exception(f"Unexpected property specification:\n\tdefault_value = {repr(default_value)}\n\tattribute_properties = {attribute_properties}")



@functools.lru_cache(None)
def _get_specs(cls):

    source = textwrap.dedent(inspect.getsource(cls))

    specs = dict()

    for attr in RE_ATTR.finditer(source):
        name = attr.group(1)
        attr_type = attr.group(2)
        default = getattr(cls, name)
        default_repr = attr.group(3)
        docs = textwrap.dedent(attr.group(4))

        attribute_properties = dict(
            default=default,
            description=docs
        )

        for line in docs.splitlines():
            line = line.strip()

            if re.search(r'`.+`\s*:\s`.+`', line):

                match = RE_ATTR_ENTRY.match(line)
                if match is None:
                    raise Exception(f"Failed to parse an item from string: {line}")

                key, value = get_qualified_attr_property(match.group(1),  match.group(2))
                attribute_properties[key] = value

            elif line.startswith('#### Default:'):
                match = RE_ATTR_DEFAULT_ENTRY.match(line)
                if match is None:
                    raise Exception(f"Failed to parse an default item from string: {line}")

                attribute_properties['default_repr'] = match.group(1)

            elif line.startswith('* `'):
                match = RE_ATTR_ENUM_ENTRY.match(line)
                if match is None:
                    raise Exception(f"Failed to parse an enumeration item from string: {line}")


                attribute_properties.setdefault('enum_items', []).append((match.group(1), match.group(2), match.group(3)))

        if not 'default_repr' in attribute_properties:
            raise Exception(f"The attribute does not include a default: {name}")

        if attribute_properties['default_repr'] != default_repr:
            raise Exception(f"The default representation of `{name}` does not mach:\n\t{attribute_properties['default_repr']}\n\t{default_repr}")

        if attr_type != type(default).__name__:
            raise Exception(f"Default value and type of `{name}` do not mach:\n\tdefault={default}\n\tattr_type={attr_type}")

        try:
            ui_spec = get_blender_prop_specs(default, attribute_properties)
        except Exception as e:
            raise Exception(f"Failed to collect a Blender UI specification:\n\tname = {name}\ndefault = {repr(default)}\n\tattribute_properties = {attribute_properties}") from e

        specs[name] = dict(
            default = default,
            docs = docs,
            ui_spec = ui_spec,
            properties = attribute_properties,
        )

    return specs


@dataclasses.dataclass
class Settings():


    ignore_default_settings = False
    """
    If `True` replacing a default value with a default value will be ignored.

    Can be useful when trying to avoid unnecessary updates while setting the settings programmatically.

    #### Beware of the `_update` usage and cases where settings are required to be explicitly set to defaults.

    It is more relable to conditionally replace the whole Settings object rather than set its members.

    #### Default: `False`
    """


    allow_non_default_settings = False
    """
    If `True` non-existent settings or settings with no default value will be allowed.

    #### Default: `False`
    """


    def __init__(self, **kwargs):

        self.__dict__['_has_been_set'] = set()
        self._has_been_set: set

        for key, value in kwargs.items():
            self.__setattr__(key, value)


    def __setattr__(self, name, value):

        default = getattr(type(self), name, SENTINEL)
        current = getattr(self, name, SENTINEL)

        if self.ignore_default_settings and current == default == value:
            return

        if not self.allow_non_default_settings and default is SENTINEL:
            raise Exception(f"Unexpected setting for {type(self).__name__}: {name} = {repr(value)}\nUse allow_non_default_settings=True.")

        self._has_been_set.add(name)
        super().__setattr__(name, value)


    @classmethod
    def _get_attribute_spec(cls, name) -> dict:
        return _get_specs(cls)[name]


    @classmethod
    def _get_ui_properties(cls) -> dict:

        import bpy
        properties = dict()

        for name, spec in _get_specs(cls).items():
            properties[name] = getattr(bpy.props, spec['ui_spec']['type'])(**spec['ui_spec']['kwargs'])

        return properties


    def _get_copy(self):

        settings = type(self)()

        for key, value in self._to_dict().items():

            if isinstance(value, Settings):
                setattr(settings, key, value._get_copy())
            else:
                setattr(settings, key, value)

        return settings


    @classmethod
    def _from_bpy_struct(cls, bpy_struct: typing.Union['idprop.types.IDPropertyGroup', 'bpy.types.PropertyGroup', 'bpy.types.Operator'], ignore_other = False):

        settings = cls()

        import bpy

        if isinstance(bpy_struct, bpy.types.Operator):
            bpy_struct = bpy_struct.properties

        for key, value in bpy_struct.items():

            try:
                spec = cls._get_attribute_spec(key)
            except KeyError as e:
                if ignore_other:
                    continue
                else:
                    raise e

            if spec['ui_spec']['type'] == 'EnumProperty':
                value = spec['ui_spec']['kwargs']['items'][value][0]
            if spec['ui_spec']['type'] == 'BoolProperty':
                value = bool(value)
            elif spec['ui_spec'].get('is_json', False):
                value = json.loads(value)
            elif isinstance(value, bpy.types.bpy_prop_array):
                value = tuple(value)
                if value and type(value[0]) is float:
                    value = tuple(round(sub_value, 7) for sub_value in value)
            elif type(value) is float:
                value = round(value, 7)

            setattr(settings, key, value)

        return settings



    @classmethod
    def _from_dict(cls, data: dict, only_matching = False):

        settings = cls()

        for key, value in data.items():

            if only_matching and not key in cls.__annotations__:
                continue

            if cls.__annotations__.get(key) is set:
                setattr(settings, key, set(value))
            else:
                setattr(settings, key, value)

        return settings


    def _to_dict(self):

        data = {}

        for key in self.__dict__:

            if key.startswith('_'):
                continue

            if not key in self._has_been_set:
                continue

            value = getattr(self, key)

            if isinstance(value, Settings):
                data[key] = value._to_dict()
            elif isinstance(value, set):
                data[key] = list(value)
            else:
                data[key] = value


        return data


    @classmethod
    def _from_json(cls, data: str):
        return cls._from_dict(json.loads(data))


    def _to_json(self):
        return json.dumps(self._to_dict(), ensure_ascii = False)


    def _get_cmd(self):

        command = []

        for key, value in self._to_dict().items():

            spec = self._get_attribute_spec(key)

            try:
                cmd = spec['properties']['cmd']
            except KeyError as e:
                raise Exception(f"Fail to get command for: {key}") from e

            if cmd is None:
                continue

            command.extend((cmd, value))

        return command


    def __eq__(self, other: typing.Union[dict, 'typing_extensions.Self']):

        if isinstance(other, dict):
            return self._to_dict() == other
        else:
            try:
                return self._to_dict() == other._to_dict()
            except AttributeError:
                traceback.print_exc()
                return False


    def __ne__(self, other: typing.Union[dict, 'typing_extensions.Self']):
        return not self.__eq__(other)


    def __repr__(self):
        return f"< {type(self).__name__}  {self._to_dict()} >"


    def _update(self, other: 'typing_extensions.Self'):

        if not other:
            return self

        for key in other.__dict__:

            if key.startswith('_'):
                continue

            if not key in other._has_been_set:
                continue

            if key not in type(self).__dict__:
                continue

            setattr(self, key, getattr(other, key))

        return self


    def __iter__(self):

        for key in self.__dict__:

            if key.startswith('_'):
                continue

            if not key in self._has_been_set:
                continue

            yield key


    def __getitem__(self, key: str):

        if key.startswith('_') or not key in self._has_been_set:
            raise KeyError(f"Unexpected key: {key}")

        value = getattr(self, key)

        if isinstance(value, Settings):
            return value._to_dict()
        elif isinstance(value, set):
            return list(value)
        else:
            return value


FILE_EXTENSION = dict(
    BMP = 'bmp',
    IRIS = 'rgb',
    PNG = 'png',
    JPEG = 'jpg',
    JPEG2000 = 'jp2',
    TARGA = 'tga',
    TARGA_RAW = 'tga',
    CINEON = 'cin',
    DPX = 'dpx',
    OPEN_EXR_MULTILAYER = 'exr',
    OPEN_EXR = 'exr',
    HDR = 'hdr',
    TIFF = 'tif',
    WEBP = 'webp',

    AVI_JPEG = 'avi',
    AVI_RAW = 'avi',
    FFMPEG = 'mp4',
)


@dataclasses.dataclass
class Image_File_Settings(Settings):


    @property
    def _file_extension(self):
        return FILE_EXTENSION[self.file_format]


    file_format: str = 'PNG'
    """
    File Format

    File format to save the rendered images as

    Options:
    * `BMP`: BMP — Output image in bitmap format
    * `IRIS`: Iris — Output image in SGI IRIS format
    * `PNG`: PNG — Output image in PNG format
    * `JPEG`: JPEG — Output image in JPEG format
    * `JPEG2000`: JPEG 2000 — Output image in JPEG 2000 format
    * `TARGA`: Targa — Output image in Targa format
    * `TARGA_RAW`: Targa Raw — Output image in uncompressed Targa format
    * `CINEON`: Cineon — Output image in Cineon format
    * `DPX`: DPX — Output image in DPX format
    * `OPEN_EXR_MULTILAYER`: OpenEXR MultiLayer — Output image in multilayer OpenEXR format
    * `OPEN_EXR`: OpenEXR — Output image in OpenEXR format
    * `HDR`: Radiance HDR — Output image in Radiance HDR format
    * `TIFF`: TIFF — Output image in TIFF format
    * `AVI_JPEG`: AVI JPEG — Output video in AVI JPEG format
    * `AVI_RAW`: AVI Raw — Output video in AVI Raw format
    * `FFMPEG`: FFmpeg Video — The most versatile way to output video files

    #### Default: `'PNG'`
    """

    color_mode: str = 'BW'
    """
    Color Mode

    Choose BW for saving grayscale images, RGB for saving red, green and blue channels, and RGBA for saving red, green, blue and alpha channels

    Options:
    * `BW`: BW — Images get saved in 8-bit grayscale (only PNG, JPEG, TGA, TIF)
    * `RGB`: RGB — Images are saved with RGB (color) data
    * `RGBA`: RGBA — Images are saved with RGB and Alpha data (if supported)

    #### Default: `'BW'`
    """

    color_depth: str = '8'
    """
    Color Depth

    Bit depth per channel

    Options:
    * `8`: 8 — 8-bit color channels
    * `10`: 10 — 10-bit color channels
    * `12`: 12 — 12-bit color channels
    * `16`: 16 — 16-bit color channels
    * `32`: 32 — 32-bit color channels

    #### Default: `'8'`
    """

    quality: int = 90
    """
    Quality

    Quality for image formats that support lossy compression

    `min`: `0`
    `max`: `100`
    `soft_min`: `0`
    `soft_max`: `100`
    `subtype`: `'PERCENTAGE'`

    #### Default: `90`
    """

    compression: int = 15
    """
    Compression

    Amount of time to determine best compression: 0 = no compression with fast file output, 100 = maximum lossless compression with slow file output

    `min`: `0`
    `max`: `100`
    `soft_min`: `0`
    `soft_max`: `100`
    `subtype`: `'PERCENTAGE'`

    #### Default: `15`
    """

    use_zbuffer: bool = False
    """
    Z Buffer

    Save the z-depth per pixel (32-bit unsigned integer z-buffer)


    #### Default: `False`
    """

    use_preview: bool = False
    """
    Preview

    When rendering animations, save JPG preview images in same directory

    #### Default: `False`
    """

    exr_codec: str = 'NONE'
    """
    Codec

    Codec settings for OpenEXR

    https://openexr.com/en/latest/TechnicalIntroduction.html#data-compression

    Options:
    * `NONE`: None — No compression.
    * `PXR24`: Pxr24 (lossy) — todo
    * `ZIP`: ZIP (lossless) — todo
    * `PIZ`: PIZ (lossless) — todo
    * `RLE`: RLE (lossless) — todo
    * `ZIPS`: ZIPS (lossless) — todo
    * `B44`: B44 (lossy) — todo
    * `B44A`: B44A (lossy) — todo
    * `DWAA`: DWAA (lossy) — todo
    * `DWAB`: DWAB (lossy) — todo

    #### Default: `'NONE'`
    """

    use_jpeg2k_ycc: bool = False
    """
    YCC

    Save luminance-chrominance-chrominance channels instead of RGB colors

    #### Default: `False`
    """

    use_jpeg2k_cinema_preset: bool = False
    """
    Cinema

    Use Openjpeg Cinema Preset

    #### Default: `False`
    """

    use_jpeg2k_cinema_48: bool = False
    """
    Cinema (48)

    Use Openjpeg Cinema Preset (48fps)

    #### Default: `False`
    """

    jpeg2k_codec: str = 'JP2'
    """
    Codec

    Codec settings for Jpeg2000

    Options:
    * `JP2`: JP2 — todo
    * `J2K`: J2K — todo

    #### Default: `'JP2'`
    """

    tiff_codec: str = 'DEFLATE'
    """
    Compression

    Compression mode for TIFF

    Options:
    * `NONE`: None — todo
    * `DEFLATE`: Deflate — todo
    * `LZW`: LZW — todo
    * `PACKBITS`: Pack Bits — todo

    #### Default: `'DEFLATE'`
    """

    use_cineon_log: bool = False
    """
    Log

    Convert to logarithmic color space

    #### Default: `False`
    """

    cineon_black: int = 0
    """
    B

    Log conversion reference blackpoint

    `min`: `0`
    `max`: `1024`
    `soft_min`: `0`
    `soft_max`: `1024`

    #### Default: `0`
    """

    cineon_white: int = 0
    """
    W

    Log conversion reference whitepoint

    `min`: `0`
    `max`: `1024`
    `soft_min`: `0`
    `soft_max`: `1024`

    #### Default: `0`
    """

    cineon_gamma: float = 0.0
    """
    G

    Log conversion gamma

    `min`: `0.0`
    `max`: `10.0`
    `soft_min`: `0.0`
    `soft_max`: `10.0`

    #### Default: `0.0`
    """

    views_format: str = 'INDIVIDUAL'
    """
    Views Format

    Format of multiview media

    Options:
    * `INDIVIDUAL`: Individual — Individual files for each view with the prefix as defined by the scene views
    * `STEREO_3D`: Stereo 3D — Single file with an encoded stereo pair

    #### Default: `'INDIVIDUAL'`
    """


@dataclasses.dataclass
class Bake(Settings):


    @property
    def _actual_width(self):
        return self.width if self.width else self.resolution


    @property
    def _actual_height(self):
        return self.height if self.height else self.resolution


    @property
    def _aspect_ratio(self):
        return self._actual_width/self._actual_height


    @property
    def _bake_width(self):
        """ An actual bake image width resolution. """
        return int(self.width if self.width else self.resolution * self.resolution_multiplier)


    @property
    def _bake_height(self):
        """ An actual bake image height resolution. """
        return int(self.height if self.height else self.resolution * self.resolution_multiplier)


    image_dir: str = os.path.join(tempfile.gettempdir(), 'blend_converter', 'default_image_dir')
    """
    The baked textures folder path.

    `subtype`: `'FILE_PATH'`

    #### Default: `os.path.join(tempfile.gettempdir(), 'blend_converter', 'default_image_dir')`
    """

    resolution: int = 1024
    """
    Resolution of both X and Y sides of the image.

    #### Default: `1024`
    """

    width: int = 0
    """
    X Resolution

    Width of the image, if not `0` then this is used instead of `resolution`.

    #### Default: `0`
    """

    height: int = 0
    """
    Y Resolution

    Height of the image, if not `0` then this is used instead of `resolution`.

    #### Default: `0`
    """

    merge_materials: bool = True
    """
    Merge the object's materials into one.

    #### Default: `True`
    """

    material_key: str = ''
    """
    If not an empty string then only materials for which `bool(bpy.types.Material.get(material_key))` is `True` are processed.

    #### Default: `''`
    """


    bake_types: list = []
    """
    List of the bake types to bake.

    See `bake_settings`.

    #### Default: `[]`
    """

    do_disable_armature: bool = True
    """
    Bake with armature disabled and upparent.

    #### Default: `True`
    """

    use_modifiers_as_in_viewport: bool = True
    """
    Modifiers As In Viewport
    Bake with modifiers that are visible in the viewport.

    #### Default: `True`
    """

    turn_off_vertex_changing_modifiers: bool = False
    """
    Turn Off Vertex Changing Modifiers
    Turn off the vertex changing modifiers for render.

    #### Default: `False`
    """

    samples: int = 1
    """
    The cycles render samples. Higher values result in a smoother and less aliased image at an increased render time.
    Usually more than 8 samples would not improve the result. In such a case use `resolution_multiplier`.

    `min`: `1`
    `soft_max`: `8`

    #### Default: `1`
    """

    resolution_multiplier: float = 1.0
    """
    Bake the image with `resolution_multiplier` times higher resolution and downscale it to the target one.
    The Blender's bake renderer does not have pixel or texture filtering.
    This is the way to increase details, smooth UV seams transitions, reduce aliasing and avoid moire patterns.

    `min`: `1.0`
    `soft_max`: `4.0`

    #### Default: `1.0`
    """

    use_smart_texture_interpolation: bool = True
    """
    Use `Smart` texture interpolation for all image nodes.

    #### Default: `True`
    """

    margin_type: str = 'ADJACENT_FACES'
    """
    Algorithm to extend the baked result.
    * `ADJACENT_FACES`: Adjacent Faces — Use pixels from adjacent faces across UV seams.
    * `EXTEND`: Extend — Extend border pixels outwards.
    #### When baking normal maps this is set to `EXTEND` due to incorrect values being generated. See: https://developer.blender.org/T96942

    #### Default: `'ADJACENT_FACES'`
    """

    margin: int = 16
    """
    Extends the baked result as a post process filter.
    #### Expensive! The texture padding extending to the image borders is created during the compositing stage, and not by increasing this value.
    #### When baking multiple objects into one texture margin is set to `1` due to overlaps between the objects. See: https://developer.blender.org/T83971

    #### Default: `16`
    """


    uv_layer_name: str = DEFAULT_UV_LAYER_NAME
    """
    The UV layer to use for baking.

    #### Default: `DEFAULT_UV_LAYER_NAME`
    """

    use_inpaint: bool = True
    """
    Extend image to the image borders.

    #### Default: `True`
    """


    merge_materials_between_objects: bool = True
    """
    Bake all materials into one.

    #### Default: `True`
    """


    create_materials: bool = True
    """
    After the baking replace the materials with the new ones made from baked textures.

    #### Default: `True`
    """


    isolate_objects: bool = True
    """
    Isolate baking objects from other objects in the scene.

    #### Default: `True`
    """


    raise_warnings: bool = False
    """
    #### DEBUGGING

    If a warning is encountered it will be raised.

    #### Default: `False`
    """

    fake_bake: bool = False
    """
    #### DEBUGGING

    All the usual processing accept for actually baking and saving the baked image.

    #### Default: `False`
    """

    compose_and_save: bool = True
    """
    #### DEBUGGING

    Compose and save the images to disk.

    If `False` - disables the compositor: denoising, inpaint and channel merging. Use `_raw_images` to access the images.

    #### Default: `True`
    """

    use_global_bake_settings: bool = True
    """
    Use all `bpy_context.Baking_Settings`. Otherwise the bake settings are the current scene's ones.

    #### Default: `True`
    """

    _MAP_IDENTIFIER_KEY = '__bc_map_identifier'
    """
    The key for an `bpy.types.Image` ID property that contains the type of the image.
    """

    _images = []
    """
    The baked images.
    """

    _raw_images = []
    """
    The not composed baked images.
    """

    dither_intensity: float = 1.0
    """
    Dither to apply when saving textures to avoid banding artifacts but introduce noise.

    `min`: `0.0`
    `max`: `1.0`

    #### Default: `1.0`
    """

    texture_name_prefix: str = ''
    """
    A name prefix to use for created textures and materials.

    If an empty string, then a common part of the materials names or the objects names will be used.

    #### Default: `''`
    """

    use_selected_to_active: bool = False
    """
    Bake from selected to active.

    #### Default: `False`
    """

    cage_object_name: str = ''
    """
    If not an empty string then the object will be used as a bake cage.

    #### Default: `''`
    """

    max_ray_distance = 0
    """
    Used for the selected to active bake.

    #### Default: `0`
    """


@dataclasses.dataclass
class Unwrap_UVs(Settings):


    uv_layer_name: str = DEFAULT_UV_LAYER_NAME
    """
    The UV layer to use for baking.
    #### Default: `DEFAULT_UV_LAYER_NAME`
    """

    smart_project_angle_limit: int = 54
    """
    `angle_limit` parameter of the `bpy.ops.uv.smart_project` operator.

    #### Default: `54`
    """

    mark_seams_from_islands: bool = False
    """
    After unwrapping mark uv seams according the islands.

    #### Default: `False`
    """

    reunwrap_bad_uvs_with_minimal_stretch: bool = True
    """
    Reunwrap bad uvs using the Blender's MINIMUM_STRETCH method.

    #### Default: `True`
    """

    reunwrap_all_with_minimal_stretch: bool = False
    """
    Reunwrap all uvs using the Blender's MINIMUM_STRETCH method.

    #### Default: `False`
    """

    uv_importance_weight_group: str = ''
    """
    Used for the MINIMUM_STRETCH method.

    #### Default: `''`
    """

    uv_importance_weight_factor: float = 1.0
    """
    Used for the MINIMUM_STRETCH method.

    #### Default: `1.0`
    """



@dataclasses.dataclass
class Pack_UVs(Settings):


    @property
    def _actual_width(self):
        return self.width if self.width else self.resolution


    @property
    def _actual_height(self):
        return self.height if self.height else self.resolution


    @property
    def _aspect_ratio(self):
        return self._actual_width/self._actual_height


    @property
    def _uv_island_margin_fraction(self):
        """ The pixel padding for a UV island in the UV space coordinates. """
        return self.padding / min(self._actual_height, self._actual_width)


    resolution: int = 1024
    """
    Resolution of both X and Y sides of the image.

    #### Default: `1024`
    """

    width: int = 0
    """
    X Resolution

    Width of the image, if not `0` then this is used instead of `resolution`.

    #### Default: `0`
    """

    height: int = 0
    """
    Y Resolution

    Height of the image, if not `0` then this is used instead of `resolution`.

    #### Default: `0`
    """

    uv_layer_name: str = DEFAULT_UV_LAYER_NAME
    """
    The UV layer to use for baking.
    #### Default: `DEFAULT_UV_LAYER_NAME`
    """

    merge: bool = True
    """
    Merge the object's UVs into one UV set.
    #### Default: `True`
    """

    material_key: str = ''
    """
    If not an empty string then only materials for which `bool(bpy.types.Material.get(material_key))` is `True` are targeted.

    The materials in the group are baked together, other materials are not baked directly.

    If `False` then all the objects' materials are baked together

    #### Default: `''`
    """

    padding: int = 4
    """
    An amount of pixels reserved around a UV island. So if padding is 4 there will be 8 pixels between the two UV islands.

    #### Default: `4`
    """

    merge_overlap: bool = False
    """
    Blender 3.6+
    Overlapping islands stick together.

    #### Default: `False`
    """

    use_uv_packer_addon: bool = True
    """
    Use the UV-Packer addon to pack UV islands.
    https://www.uv-packer.com/blender/
    #### The results of the packer are non-deterministic. Every packing you will get a different UV layout.

    #### Default: `True`
    """

    uv_packer_addon_pin_largest_island: bool = False
    """
    A hack to trigger a packing to others algorithm.

    Allows for a better UV coverage in presence of stretched and long uv islands.
    https://blenderartists.org/t/uv-packer-for-blender-free-windows-macos/1287541/71

    Significantly increases the packing time. Can still produce a suboptimal pack.

    #### Default: `False`
    """

    average_uv_scale: bool = True
    """
    Scale uv islands according to their mesh surface area.

    #### Default: `True`
    """

    uvp_rescale: bool = False
    """
    Rescale UVs before packing.

    #### Default: `False`
    """

    uvp_prerotate: bool = True
    """
    Pre-rotate UVs before packing. This can make them be no longer axis aligned.

    #### Default: `True`
    """

    use_uv_packer_for_pre_packing: bool = False
    """
    Use the UV-Packer addon for pre-packing to make uv_packer_addon_pin_largest_island option to work better.

    #### Default: `False`
    """


    def _set_suggested_padding(self, resolution: typing.Optional[int] = None):

        if resolution is None:
            resolution = self.resolution

        padding = resolution/128/2
        if padding <= 4:
            padding += 1

        self.padding = padding

        return padding



@dataclasses.dataclass
class Vhacd(Settings):
    """ https://github.com/kmammou/v-hacd """


    hulls_number: int = 32
    """
    Maximum number of output convex hulls.

    #### Default: `32`
    `cmd`: `-h`
    """


    voxel_resolution: int = 100000
    """
    Total number of voxels to use.

    #### Default: `100000`
    `cmd`: `-r`
    """


    volume_error_percent: float = 1.0
    """
    Volume error allowed as a percentage.

    #### Default: `1.0`
    `min`: `0.001`
    `max`: `10`
    `cmd`: `-e`
    """


    max_recursion_depth: int = 10
    """
    Maximum recursion depth.

    #### Default: `10`
    `cmd`: `-d`
    """


    shrinkwrap_output: bool = True
    """
    Whether or not to shrinkwrap output to source mesh.

    #### Default: `True`
    `cmd`: `-s`
    """


    fill_mode: str = 'flood'
    """
    Fill mode.

    * `flood`: flood — flood
    * `surface`: surface — surface
    * `raycast`: raycast — raycast

    #### Default: `'flood'`
    `cmd`: `-f`
    """


    max_hull_vert_count: int = 64
    """
    Maximum number of vertices in the output convex hull.

    `min`: `8`
    `max`: `20484`

    #### Default: `64`
    `cmd`: `-v`
    """


    run_asynchronously: bool = True
    """
    Whether or not to run asynchronously.

    #### Default: `True`
    `cmd`: `-a`
    """


    min_edge_length: int = 2
    """
    Minimum size of a voxel edge.

    #### Default: `2`
    `cmd`: `-l`
    """


    splits_hulls: bool = False
    """
    If false, splits hulls in the middle. If true, tries to find optimal split plane location.

    #### Default: `False`
    `cmd`: `-p`
    """


    # -o <obj/stl/usda>       : Export the convex hulls as a series of wavefront OBJ files, STL files, or a single USDA.


    logging: bool = True
    """
    If set to false, no logging will be displayed.

    #### Default: `True`
    `cmd`: `-g`
    """


    vhacd_executable: str = os.path.join(ROOT_DIR, 'external', 'vhacd', 'TestVHACD.exe')
    """
    Path to the vhacd executable.

    #### Default: `os.path.join(ROOT_DIR, 'external', 'vhacd', 'TestVHACD.exe')`
    `subtype`: `'FILE_PATH'`
    `cmd`: `None`
    """


    def _get_cmd(self, filepath_input):
        return [self.vhacd_executable, filepath_input, *[str(arg).lower() for arg in super()._get_cmd()]]


@dataclasses.dataclass
class Ministry_Of_Flat(Settings):


    silent: bool = False
    """
    Do not output any text to console. [ -SILENT TRUE/FALSE ]

    #### Default: `False`
    `cmd`: `-SILENT`
    """

    texture_resolution: int = 1024
    """
    Resolution of texture, to give right amount of island gaps to prevent bleeds. [ -resolution <VALUE> ]

    #### Default: `1024`
    `cmd`: `-resolution`
    """

    separate_hard_edges: bool = False
    """
    Guarantees that all hard edges are separated. Useful for lightmapping and Normalmapping [ -separate TRUE/FALSE ]

    #### Default: `False`
    `cmd`: `-separate`
    """

    aspect: float = 1.0
    """
    Aspect ratio of pixels. For non square textures. [ -aspect <VALUE> ]

    #### Default: `1.0`
    `cmd`: `-aspect`
    """

    use_normal: bool = False
    """
    Use the models normals to help classify polygons. [ -normals TRUE/FALSE ]

    #### Default: `False`
    `cmd`: `-normals`
    """

    udims: int = 1
    """
    Split the model in to multople UDIMs [ -udims <VALUE> ]

    #### Default: `1`
    `cmd`: `-udims`
    """

    overlap_identical_parts: bool = False
    """
    Overlap identtical parts to take up the same texture space. [ -overlap TRUE/FALSE ]

    #### Default: `False`
    `cmd`: `-overlap`
    """

    overlap_mirrored_parts: bool = False
    """
    Overlap mirrored parts to take up the same texture space. [ -mirror TRUE/FALSE ]

    #### Default: `False`
    `cmd`: `-mirror`
    """

    scale_uv_space_to_worldspace: bool = False
    """
    Scales the UVs to match their real world scale going beyound the zero to one range. [ -worldscale TRUE/FALSE ]

    #### Default: `False`
    `cmd`: `-worldscale`
    """

    texture_density: int = 1024
    """
    If worldspace is enabled, this value sets the number of pixels per unit. [ -density <VALUE> ]

    #### Default: `1024`
    `cmd`: `-density`
    """

    seam_direction: tuple = (0.0, 0.0, 0.0)
    """
    Sets a pointy in space that seams are directed towards. By default the center of the model. [ -center <X VALUE> <Y VALUE> <Z VALUE> ]

    #### Default: `(0.0, 0.0, 0.0)`
    `cmd`: `-center`
    """

    supress_validation_errors: bool = False
    """
    Faulty geometry errors will not be printed to standard out. [ -supress TRUE/FALSE ]

    #### Default: `False`
    `cmd`: `-supress`
    """

    quads: bool = True
    """
    Searches the model for triangle pairs that make good quads. Improves the use of patches. [ -quad TRUE/FALSE ]

    #### Default: `True`
    `cmd`: `-quad`
    """

    vertex_weld: bool = True
    """
    Merges duplicate vertices, Does not efect the out put polygon or vertext data. [ -weld TRUE/FALSE ]

    #### Default: `True`
    `cmd`: `-weld`
    """

    flat_soft_surface: bool = True
    """
    Detects flat areas of soft surfaces in order to minimize their distortion. [ -flat TRUE/FALSE ]

    #### Default: `True`
    `cmd`: `-flat`
    """

    cones: bool = True
    """
    Searches the model for sharp Cones. [ -cone TRUE/FALSE ]

    #### Default: `True`
    `cmd`: `-cone`
    """

    cone_ratio: float = 0.5
    """
    The minimum ratio of a triangle used in a cone. [ -coneratio <VALUE> ]

    #### Default: `0.5`
    `cmd`: `-coneratio`
    """

    grids: bool = True
    """
    Searches the model for grids of quads. [ -grids TRUE/FALSE ]

    #### Default: `True`
    `cmd`: `-grids`
    """

    strips: bool = True
    """
    Searches the model for strips of quads. [ -strip TRUE/FALSE ]

    #### Default: `True`
    `cmd`: `-strip`
    """

    patches: bool = True
    """
    Searches the model for grids of quads. [ -patch TRUE/FALSE ]

    #### Default: `True`
    `cmd`: `-patch`
    """

    planes: bool = True
    """
    Detect planes. [ -planes TRUE/FALSE ]

    #### Default: `True`
    `cmd`: `-planes`
    """

    flatness: float = 0.9
    """
    Minimum normal dot product between two flat polygons. [ -flatt <VALUE> ]

    #### Default: `0.9`
    `cmd`: `-flatt`
    """

    merge: bool = True
    """
    Merges polygons using unfolding [ -merge TRUE/FALSE ]

    #### Default: `True`
    `cmd`: `-merge`
    """

    merge_limit: float = 0.0
    """
    Limit the angle of polygons beeing merged. [ -mergelimit <VALUE> ]

    #### Default: `0.0`
    `cmd`: `-mergelimit`
    """

    pre_smooth: bool = True
    """
    Soften the mesh before atempting to cut and project. [ -presmooth TRUE/FALSE ]

    #### Default: `True`
    `cmd`: `-presmooth`
    """

    soft_unfold: bool = True
    """
    Atempt to unfold soft surfaces. [ -softunfold TRUE/FALSE ]

    #### Default: `True`
    `cmd`: `-softunfold`
    """

    tubes: bool = True
    """
    Find tube shaped geometry and unwrap it using cylindrical projection. [ -tubes TRUE/FALSE ]

    #### Default: `True`
    `cmd`: `-tubes`
    """

    junctions: bool = True
    """
    Find and handle Junctions between tubes. [ -junctionsdebug TRUE/FALSE ]

    #### Default: `True`
    `cmd`: `-junctionsdebug`
    """

    extra_ordenary_point: bool = False
    """
    Using vertices not sharded by 4 quads as starting points for cutting. [ -extradebug TRUE/FALSE ]

    #### Default: `False`
    `cmd`: `-extradebug`
    """

    angle_based_flatening: bool = True
    """
    Using angle based flattening to handle smooth surfaces. [ -abf TRUE/FALSE ]

    #### Default: `True`
    `cmd`: `-abf`
    """

    smooth: bool = True
    """
    Cut and project smooth surfaces. [ -smooth TRUE/FALSE ]

    #### Default: `True`
    `cmd`: `-smooth`
    """

    repair_smooth: bool = True
    """
    Attaches small islands to larger islands on smooth surfaces. [ -repairsmooth TRUE/FALSE ]

    #### Default: `True`
    `cmd`: `-repairsmooth`
    """

    repair: bool = True
    """
    Repair edges to make then straight. [ -repair TRUE/FALSE ]

    #### Default: `True`
    `cmd`: `-repair`
    """

    squares: bool = True
    """
    Finds various individual polygons that hare right angles. [ -square TRUE/FALSE ]

    #### Default: `True`
    `cmd`: `-square`
    """

    relax: bool = True
    """
    Relax all smooth polygons to minimize distortion. [ -relax TRUE/FALSE ]

    #### Default: `True`
    `cmd`: `-relax`
    """

    relaxation_iterations: int = 50
    """
    The number of iteration loops when relaxing. [ -relax_iteration <VALUE> ] (wrong command help)

    #### Default: `50`
    `cmd`: `-relax_iterations`
    """

    expand: float = 0.25
    """
    Expand soft surfaces to make more use of texture space. Experimental, off by default [ -expand <VALUE> ]

    #### Default: `0.25`
    `cmd`: `-expand`
    """

    cut: bool = True
    """
    Cut down awkward shapes in order to optimize layout coverage. [ -cutdebug TRUE/FALSE ]

    #### Default: `True`
    `cmd`: `-cutdebug`
    """

    stretch: bool = True
    """
    Stretch any island that is too wide to fit in the image. [ -stretch TRUE/FALSE ]

    #### Default: `True`
    `cmd`: `-stretch`
    """

    match: bool = True
    """
    Match individual tirangles for better packing. [ -match TRUE/FALSE ]

    #### Default: `True`
    `cmd`: `-match`
    """

    packing: bool = True
    """
    Pack islands in to a rectangle [ -packing TRUE/FALSE ]

    #### Default: `True`
    `cmd`: `-packing`
    """

    rasterization_resolution: int = 64
    """
    Resolution of packing rasterization. [ -rasterization <VALUE> ]

    #### Default: `64`
    `cmd`: `-rasterization`
    """

    packing_iterations: int = 4
    """
    How many times the packer will pack the islands in order to find the optimal island spaceing. [ -packing_iterati <VALUE> ] (wrong command help)

    #### Default: `4`
    `cmd`: `-packing_iterations`
    """

    scale_to_fit: float = 0.5
    """
    Scales islands to fit cavites. [ -scaletofit <VALUE> ]

    #### Default: `0.5`
    `cmd`: `-scaletofit`
    """

    validate: bool = False
    """
    Validate geometry after each stage and print out any issues found (For debugging only). [ -validate TRUE/FALSE ]

    #### Default: `False`
    `cmd`: `-validate`
    """

    ministry_of_flat_executable: str = os.path.join(ROOT_DIR, 'external', 'ministry_of_flat', 'UnWrapConsole3.exe')
    """
    Path to the vhacd executable.

    #### Default: `os.path.join(ROOT_DIR, 'external', 'ministry_of_flat', 'UnWrapConsole3.exe')`
    `subtype`: `'FILE_PATH'`
    `cmd`: `None`
    """

    timeout: float = 5 * 60.0
    """
    `subprocess.run` timeout.

    In case of bad geometry it can get into an infinite or a very long inappropriate loop.

    #### Default: `5 * 60.0`
    `cmd`: `None`
    """


    @property
    def _executable_exists(self):
        return os.path.exists(self.ministry_of_flat_executable)


    def _get_cmd(self, filepath_input, filepath_output):

        parameters = super()._get_cmd()

        for index, item in enumerate(parameters):
            if isinstance(item, str):
                continue
            elif isinstance(item, bool):
                parameters[index] = str(item).upper()
            elif isinstance(item, (float, int)):
                parameters[index] = str(item)
            elif isinstance(item, tuple) or 'IDPropertyArray' in str(type(item)):
                parameters.pop(index)
                parameters.insert(index, str(item[2]))
                parameters.insert(index, str(item[1]))
                parameters.insert(index, str(item[0]))
            else:
                raise Exception(f"Unexpected item: {item} or type: {type(item)}")

        return [self.ministry_of_flat_executable, filepath_input, filepath_output, *parameters]


@dataclasses.dataclass
class Bake_Materials(Settings):


    image_dir: str = os.path.join(tempfile.gettempdir(), 'blend_converter', 'default_image_dir')
    """
    The baked textures folder path.

    `subtype`: `'FILE_PATH'`

    #### Default: `os.path.join(tempfile.gettempdir(), 'blend_converter', 'default_image_dir')`
    """

    resolution: int = 0
    """
    Resolution of both X and Y sides of the image.

    If not `0` — used instead of `texel_density`.

    #### Default: `0`
    """

    texel_density: int = 1024
    """
    Texel density in pixels per meter.

    https://www.beyondextent.com/deep-dives/deepdive-texeldensity

    #### Default: `1024`
    """

    min_resolution: int = 64
    """
    Minimum resolution per image.

    #### Default: `64`
    """

    max_resolution: int = 4096
    """
    Maximum resolution per image.

    #### Default: `4096`
    """

    uv_layer_bake: str = DEFAULT_UV_LAYER_NAME
    """
    The name of a uv layer that will be used for baking.

    #### Default: `DEFAULT_UV_LAYER_NAME`
    """

    uv_layer_reuse: str = ''
    """
    The name of a uv layer that will not be re-unwrapped, only packed.

    #### Default: `''`
    """

    faster_ao_bake: bool = True
    """
    Optimizations to make the AO baking faster sacrificing quality.

    #### Default: `True`
    """

    ao_bake_use_normals: bool = True
    """
    When baking the AO use the material normals. Will be slower.

    #### Default: `True`
    """

    denoise_all: bool = False
    """
    Use denoise for all types of maps.

    #### Default: `False`
    """

    isolate_object_hierarchies: bool = False
    """
    Space out object hierarchies, grouped by a top common parent, before baking to prevent them affecting each other, aka exploded bake.

    #### Default: `False`
    """

    bake_original_topology: bool = True
    """
    The UV data is transferred using the data transfer modifier.

    If `True` the topology changing modifiers will be excluded and the uvs transferred to the model.

    If `False` the topology changing modifiers will be applied and the transfer modifier will be left on the original model as a top most modifier.

    #### Default: `True`
    """

    unwrap_original_topology: bool = False
    """
    If `True` then pre-converter meshes will be UV unwrapped.

    #### Default: `False`
    """

    non_uniform_average_uv_scale: bool = False
    """
    Use non-uniform UVs rescale in `bpy.ops.uv.average_islands_scale`.

    May fix stretched UVs issues or make it worse.

    #### Default: `False`
    """

    convert_materials: bool = True
    """
    Convert materials to use a single Principled BSDF shader and make them independent from objects.

    #### Disable only if it was done prior.

    `bpy_utils.convert_materials_to_principled(objects)`

    `bpy_utils.make_material_independent_from_object(objects)`

    #### Default: `True`
    """

    pre_bake_labels: list = []
    """
    Bakes and replaces the nodes with the labels specified. See `label_mix_shader_nodes` and `bake_by_label`.

    #### Default: `[]`
    """


@dataclasses.dataclass
class Future_Bake_Materials(Settings):

    is_same_resolution: bool = True
    """
    All UDIM images have the same resolution.

    #### Default: `True`
    """

    max_udim_amount: int = 4
    """
    Maximum amount of images per UDIM set.

    #### Default: `4`
    """





if __name__ == '__main__':


    for cls in [object for object in globals().values() if type(object) is type and issubclass(object, Settings)]:

        print(cls)

        for key in [key for key in cls.__dict__.keys() if not key.startswith('_')]:
            print(key)

            for key_, value_ in cls._get_attribute_spec(key).items():
                if not key_ == 'docs':
                    print('\t', key_, ':', value_)

            print()

        print('#' * 80)
        print()

    print('All ok.')
