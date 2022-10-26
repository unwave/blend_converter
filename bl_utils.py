import json
import inspect

COMMON_KEYWORDS = {
    'soft_min', 
    'items', 
    'update', 
    'default', 
    'soft_max', 
    'max', 
    'attr', 
    'options', 
    'min', 
    'name', 
    'description',
    'hard_max',
    'hard_min'
    }

PROPERTY_INTERNAL = {
    '__doc__', 
    '__module__', 
    '__slots__', 
    'bl_rna', 
    'fixed_type', 
    'icon', 
    'identifier', 
    'is_animatable', 
    'is_argument_optional', 
    'is_hidden', 
    'is_library_editable', 
    'is_output', 
    'is_overridable', 
    'is_registered', 
    'is_registered_optional', 
    'is_required', 
    'is_runtime', 
    'is_skip_save', 
    'rna_type', 
    'srna', 
    'tags', 
    'translation_context', 
    'type', 
    'unit', 
    'length_max', 
    'array_dimensions', 
    'array_length', 
    'default_array', 
    'is_array', 
    'precision', 
    'step',
    'enum_items',
    'is_readonly'
    }

SENTINEL = object()

def prop_name_to_python_type(name, keywords):
    if name == 'BoolProperty':
        return 'bool'
    elif name == 'StringProperty':
        return 'str'
    elif name == 'FloatProperty':
        return 'float'
    elif name == 'EnumProperty':
        options = keywords.get('options', SENTINEL)
        if options is not SENTINEL and 'ENUM_FLAG' in options:
            return 'typing.Set[str]'
        else:
            return 'str'
    elif name == 'CollectionProperty':
        return 'list'
    elif name == 'PointerProperty':
        return 'str'
    elif name == 'IntProperty':
        return 'int'
    else:
        raise NotImplementedError(f'Type: {name} is not supported.')

def get_docs_string(keywords: dict, is_property = False):
    docs_string = []
    docs_string.append('"""')
    docs_string.append('\n')
    
    text = keywords.get('name')
    if text:
        docs_string.append(text)
        docs_string.append('\n\n')
        
    text = keywords.get('description')
    if text:
        docs_string.append(text)
        docs_string.append('\n\n')
        
    items = keywords.get('items', SENTINEL)
    if items is not SENTINEL:
        docs_string.append(f"Options:")
        docs_string.append('\n')
        for item in items:
            docs_string.append(f"* `{item[0]}`: {item[1]}{', ' + item[2] if item[2] else ''}\n")
        docs_string.append('\n')

    
    value = keywords.get('hard_min', SENTINEL)
    if value is not SENTINEL:
        docs_string.append(f"Hard Min: `{round(value, 8)}`")
        docs_string.append('\n')
        
    value = keywords.get('hard_max', SENTINEL)
    if value is not SENTINEL:
        docs_string.append(f"Hard Max: `{round(value, 8)}`")
        docs_string.append('\n')
        
    value = keywords.get('soft_min', SENTINEL)
    if value is not SENTINEL:
        docs_string.append(f"Soft Min: `{round(value, 8)}`")
        docs_string.append('\n')
        
    value = keywords.get('soft_max', SENTINEL)
    if value is not SENTINEL:
        docs_string.append(f"Soft Max: `{round(value, 8)}`")
        docs_string.append('\n')
        
    value = keywords.get('min', SENTINEL)
    if value is not SENTINEL:
        docs_string.append(f"Min: `{round(value, 8)}`")
        docs_string.append('\n')
        
    value = keywords.get('max', SENTINEL)
    if value is not SENTINEL:
        docs_string.append(f"Max: `{round(value, 8)}`")
        docs_string.append('\n')

    if any(keywords.get(key, SENTINEL) is not SENTINEL for key in ('max', 'max', 'soft_max', 'soft_min', 'hard_max', 'hard_min')):
        docs_string.append('\n')

        
    options = keywords.get('options', SENTINEL)
    if options is not SENTINEL:
        docs_string.append(f"Blender Property Options: `{options}`")
        docs_string.append('\n\n')

    if is_property:

        value = keywords.pop('default_flag', None)
        if value:
            keywords['default'] = value

        value = keywords.pop('enum_items_static', None)
        if value:
            docs_string.append(f"Options:")
            docs_string.append('\n')
            for item in value:
                docs_string.append(f"* `{item.identifier}`: {item.name}{', ' + item.description if item.description else ''}\n")
            docs_string.append('\n')

        value = keywords.pop('is_enum_flag', None)
        if value:
            docs_string.append(f"Is a multiple choice enumerator.")
            docs_string.append('\n')

        value = keywords.pop('is_never_none', None)
        if value:
            docs_string.append(f"#### Required.")
            docs_string.append('\n')

        value = keywords.pop('subtype', None)
        if value and value != 'NONE':
            docs_string.append(f"Subtype: `{value}`")
            docs_string.append('\n')
        
        for key, value in keywords.items():
            if key not in COMMON_KEYWORDS and key not in PROPERTY_INTERNAL:
                docs_string.append(f"`{key}`: `{value}`")
                docs_string.append('\n')
    else:
        for key, value in keywords.items():
            if key not in COMMON_KEYWORDS:
                docs_string.append(f"`{key}`: `{value}`")
                docs_string.append('\n')

    docs_string.append('\n')
    docs_string.append(f"#### Default: `{keywords.get('default').__repr__()}`")
    docs_string.append('\n')
    docs_string.append('"""')

    return docs_string


def get_docs_from_annotations(annotations, argument_names = None) -> str:
    """ 
    From `__annotations__` 
    
    ```
    import io_scene_fbx
    __annotations__ = io_scene_fbx.ExportFBX.__annotations__
    docs = bl_utils.get_docs_from_annotations(__annotations__)
    ```
    
    """
    if argument_names:
        argument_names = set(argument_names)

    docs = []

    for key, value in annotations.items():

        if argument_names is not None and key not in argument_names:
            continue

        keywords = value.keywords

        docs.append(f"{key}: {prop_name_to_python_type(value.function.__name__, keywords)}")
        docs.append('\n')

        assert keywords['attr'] == key

        docs_string = get_docs_string(keywords)
        
        docs.append(''.join(docs_string))
        docs.append('\n\n')

    return ''.join(docs)


def get_docs_from_properties(properties, argument_names = None) -> str:
    """ 
    From `properties` 

    ```
    properties = bpy.ops.wm.obj_export.get_rna_type().properties
    docs = bl_utils.get_docs_from_properties(properties)
    ```
    """
    if argument_names:
        argument_names = set(argument_names)

    docs = []

    for key, value in properties.items():

        if argument_names is not None and key not in argument_names:
            continue

        keywords = dict(inspect.getmembers(value))

        if keywords['is_hidden']:
            continue
        if keywords['is_readonly']:
            continue

        is_enum_flag = keywords.get('is_enum_flag', None)
        if is_enum_flag:
            docs.append(f"{key}: set")
            docs.append('\n')
        else:
            docs.append(f"{key}: {prop_name_to_python_type(type(value).__name__, keywords)}")
            docs.append('\n')

        docs_string = get_docs_string(keywords, is_property = True)
        
        docs.append(''.join(docs_string))
        docs.append('\n\n')

    return ''.join(docs)


def to_json(object):
    type_name = type(object).__name__
    if type_name == '_PropertyDeferred':
        return dict(object.keywords)
    elif type_name == 'set':
        return list(object)
    else:
        return repr(object)

def annotations_to_json(annotations, json_default = to_json):
    return json.dumps(dict(annotations), ensure_ascii = False, indent = 4, default = json_default)

def get_arguments_names(func):
    return [argument.name for argument in inspect.signature(func).parameters.values()]

def print_members(object):
    for key, value in inspect.getmembers(object):
        print(key, '—', value)