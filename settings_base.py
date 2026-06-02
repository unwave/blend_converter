import re
import inspect
import functools
import textwrap
import json
import typing
import traceback
import uuid
import sys


class Sentinel:

    def __repr__(self):
        return '[SENTINEL]'

SENTINEL = Sentinel()


K_CLASS_NAME = '_bc_settings_name'


if typing.TYPE_CHECKING:
    import typing_extensions
    import idprop
    import bpy


RE_ATTR = re.compile(r'([a-zA-Z0-9_]+):\s*(.+?)\s*(?:=\s*(.+)\s*)?\n\s*"""([\w\W]+?)"""')
RE_ATTR_ENTRY = re.compile(r'^`(.+?)`\s*:\s*`(.+?)`$')
RE_ATTR_DEFAULT_ENTRY = re.compile(r'^#### Default: `(.+?)`$')
RE_ATTR_ENUM_ENTRY = re.compile(r'^\* `(.+?)`\s*:\s*(.+?)\s*—\s*(.+)*$')


class Attribute_Spec(typing.NamedTuple):


    name: str

    type: typing.Type

    default: typing.Any


    description: str = None
    """ The full docstring of the attribute. """

    default_repr: str = None
    """ A Python representation of the default value. """

    enum_items: typing.List[typing.Tuple[str, str, str]] = None
    """ The Blender style enumeration items. """

    ui_spec: dict = None
    """ A Blender's UI property arguments. """

    cmd: str = None
    """ The parameter specifies an underlying command line interface tool name if any. E.g.: --attr-name. """

    subtype: str = None
    """ Blender's string property subtype. """

    min: typing.Union[int, float] = None
    """ A hard minimum numeric value. """

    max: typing.Union[int, float] = None
    """ A hard maximum numeric value. """

    soft_min: typing.Union[int, float] = None
    """ A soft maximum numeric value. """

    soft_max: typing.Union[int, float] = None
    """ A soft minimum numeric value. """



def is_json_serializable(object):
    try:
        json.dumps(object)
    except json.JSONDecodeError:
        return False
    except TypeError:
        return False
    else:
        return True


def _get_qualified_value(value: str):

    if value.startswith(('\'', '\"')):
        return value[1:-1]
    if ',' in value:
        return tuple(_get_qualified_value(v.strip()) for v in value.split(','))
    elif value == 'False':
        return False
    elif value == 'True':
        return True
    elif '.' in value:
        return float(value)
    else:
        return int(value)


def get_qualified_value(key: str, value: str):

    if key == 'cmd':  # how the parameter is specified for the underlying tool
        if value.lower() == 'none':
            return None
        elif value.startswith('-'):
            return value
    elif key in ('max', 'min', 'soft_min', 'soft_max'):  # Blender UI parameters
        return _get_qualified_value(value)
    elif key == 'subtype':  # Blender string property subtype
        return _get_qualified_value(value)

    print(f"Unexpected key and value pare: {key} = {value}", file = sys.stderr)

    return SENTINEL


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
        raise Exception(
            "Unexpected property specification:"
            "\n\t" f"default_value = {repr(default_value)}"
            "\n\t" f"attribute_properties = {attribute_properties}"
        )


def get_default_from_repr(cls: typing.Type, representation: str):

    if cls is str:
        return cls(representation[1:-1])
    elif cls is bool:
        if representation == 'True':
            return True
        else:
            return False
    elif cls is int:
        return int(representation)
    elif cls is float:
        return float(representation)
    else:
        return SENTINEL


@functools.lru_cache(None)
def _get_specs(cls) -> typing.Dict[str, Attribute_Spec]:

    source = textwrap.dedent(inspect.getsource(cls))

    specs = dict()

    type_hints = typing.get_type_hints(cls)

    for attr in RE_ATTR.finditer(source):
        name = attr.group(1)
        attr_type = attr.group(2)
        default = getattr(cls, name, SENTINEL)
        default_repr = attr.group(3)
        docs = textwrap.dedent(attr.group(4))

        has_default_value = default is not SENTINEL


        attribute_properties = dict()

        for line in docs.splitlines():
            line = line.strip()

            if re.search(r'`.+`\s*:\s`.+`', line):

                match = RE_ATTR_ENTRY.match(line)
                if match is None:
                    raise Exception(f"Failed to parse an item from string: {line}")

                key = match.group(1)
                value = get_qualified_value(key, match.group(2))

                if value is SENTINEL:
                    continue

                attribute_properties[key] = value

            elif line.startswith('#### Default:'):
                match = RE_ATTR_DEFAULT_ENTRY.match(line)
                if match is None:
                    raise Exception(f"Failed to parse a default item from string: {line}")

                attribute_properties['default_repr'] = match.group(1)

            elif line.startswith('* `'):
                match = RE_ATTR_ENUM_ENTRY.match(line)
                if match is None:
                    raise Exception(f"Failed to parse an enumeration item from string: {line}")


                attribute_properties.setdefault('enum_items', []).append((match.group(1), match.group(2), match.group(3)))


        if not has_default_value:
            default_repr = attribute_properties['default_repr']
            default = get_default_from_repr(type_hints[name], default_repr)

        attribute_properties['default'] = default
        attribute_properties['description'] = docs.strip()

        is_supported_type = default is not SENTINEL


        if not 'default_repr' in attribute_properties:
            raise Exception(f"The attribute does not include a default: {name}")

        if attribute_properties['default_repr'] != default_repr:
            raise Exception(
                f"The default representation of `{name}` does not mach:"
                "\n\t" f"{attribute_properties['default_repr']}"
                "\n\t" f"{default_repr}"
            )

        if is_supported_type and attr_type != type(default).__name__:
            raise Exception(
                f"Default value and type of `{name}` do not mach:"
                "\n\t" f"default = {default}"
                "\n\t" f"attr_type = {attr_type}"
            )

        try:
            if is_supported_type:
                ui_spec = get_blender_prop_specs(default, attribute_properties)
            else:
                ui_spec = None
        except Exception as e:
            raise Exception(
                "Failed to collect a Blender UI specification:"
                "\n\t" f"name = {name}"
                "\n\t" f"default = {repr(default)}"
                "\n\t" f"attribute_properties = {attribute_properties}"
            ) from e


        specs[name] = Attribute_Spec(
            name = name,
            type = type(default),
            ui_spec = ui_spec,
            **attribute_properties,
        )

    return specs



class Settings():


    ignore_default_settings = False
    """
    If `True` replacing a default value with a default value will be ignored.

    Can be useful when trying to avoid unnecessary updates while setting the settings programmatically.

    #### Beware of the `_update` usage and cases where settings are required to be explicitly set to defaults.

    It is more reliable to conditionally replace the whole Settings object rather than set its members.

    #### Default: `False`
    """


    allow_missing_settings = False
    """
    If `True` non-existent settings or settings with no default value will be allowed.

    #### Default: `False`
    """


    _uuid = ''
    """
    A unique ID per Settings instance created.
    """


    def __init__(self, **kwargs):

        self.__dict__['_has_been_set'] = set()
        self.__dict__['_uuid'] = uuid.uuid1().hex
        self._has_been_set: set

        for key, value in kwargs.items():
            self.__setattr__(key, value)


    def __setattr__(self, name, value):

        default = getattr(type(self), name, SENTINEL)
        current = getattr(self, name, SENTINEL)

        if self.ignore_default_settings and current == default == value:
            return

        if not self.allow_missing_settings and default is SENTINEL:
            raise Exception(
                f"Unexpected setting for {type(self).__name__}: {name} = {repr(value)}"
                "\n\t" "If it should be valid — use allow_missing_settings=True."
                "\n\t" "To allow non-existent settings or settings with no default value."
            )

        self._has_been_set.add(name)
        super().__setattr__(name, value)


    @classmethod
    def _get_attribute_spec(cls, name):

        try:
            return _get_specs(cls)[name]
        except KeyError:
            pass
        except Exception as e:
            traceback.print_exc(file = sys.stderr)

        annotations = getattr(cls, '__annotations__', {})
        default = getattr(cls, name, None)

        return Attribute_Spec(
            name = name,
            type = annotations.get(name, type(default)),
            default = default,
        )


    @classmethod
    def _get_ui_properties(cls) -> dict:

        import bpy
        properties = dict()

        for name, spec in _get_specs(cls).items():
            properties[name] = getattr(bpy.props, spec.ui_spec['type'])(**spec.ui_spec['kwargs'])

        return properties


    def _get_copy(self):

        settings = type(self)()

        for key, value in self.items():

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

            if spec.ui_spec['type'] == 'EnumProperty':
                value = spec.ui_spec['kwargs']['items'][value][0]
            if spec.ui_spec['type'] == 'BoolProperty':
                value = bool(value)
            elif spec.ui_spec.get('is_json', False):
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

        annotations = getattr(cls, '__annotations__', {})

        for key, value in data.items():

            if key == K_CLASS_NAME:
                continue

            if only_matching and not key in annotations:
                continue

            if annotations.get(key) is set:
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

        data[K_CLASS_NAME] = self.__class__.__name__

        return data


    @classmethod
    def _from_json(cls, data: str):
        return cls._from_dict(json.loads(data))


    def _to_json(self):
        return json.dumps(self._to_dict(), ensure_ascii = False)


    def _get_cmd(self):

        command = []

        for key, value in self.items():

            spec = self._get_attribute_spec(key)

            cmd = spec.cmd
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


    def keys(self):
        return list(self)


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


    def items(self):
        for key in self:
            yield key, self[key]
