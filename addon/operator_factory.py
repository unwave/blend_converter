import functools
import typing
import inspect

import bpy

from . import ADDON_CLASS_PREFIX
from . import BL_CATEGORY
from . import DEBUG

DEFAULT_PANEL_CLASS_NAME = ADDON_CLASS_PREFIX + '_PT_default_panel'

OPERATORS_TO_DRAW = []
TAKEN_FUNCTION_NAMES = set()

def ensure_unique_func_name(name: str):

    number = 2
    init_name = name

    while name in TAKEN_FUNCTION_NAMES:
        name = f"{init_name}_{number}"
        number += 1

    TAKEN_FUNCTION_NAMES.add(name)

    return name


class Default_Panel_Base_Class(object if not typing.TYPE_CHECKING else bpy.types.Panel):
    bl_label = 'Default Panel'
    bl_category = BL_CATEGORY
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):

        column = self.layout.column()

        for op_path in OPERATORS_TO_DRAW:
            column.operator(op_path)


globals()[DEFAULT_PANEL_CLASS_NAME] = type(DEFAULT_PANEL_CLASS_NAME, (Default_Panel_Base_Class, bpy.types.Panel), dict(bl_idname = DEFAULT_PANEL_CLASS_NAME))


@functools.lru_cache(None)
def get_arg_spec(func):
    return inspect.getfullargspec(func)

def get_kwargs(func):

    spec = get_arg_spec(func)

class Operator_Class_Base(bpy.types.Operator):

    _execute: typing.Callable

    def execute(self, context):

        try:
            result = self._execute(self, context)
        except Exception as e:
            raise e

        if result:
            if DEBUG: raise Exception(result)
            self.report({'WARNING'}, result)
            return {'CANCELLED'}
        else:
            return {'FINISHED'}


def operator(*, bl_idname_prefix: str = 'wm', default_draw = True, class_bases: typing.Iterable = tuple(), **kwargs):

    def decor(func) -> typing.Union[typing.Type, Operator_Class_Base]:

        func_name: str = str(func.__name__).lower()

        func_name = ensure_unique_func_name(func_name)

        class_name = f"{ADDON_CLASS_PREFIX.upper()}_OT_f_{func_name}"

        bl_label = kwargs.pop('bl_label', None)
        if not bl_label:
            bl_label = func_name.title().replace('_', ' ')

        bl_idname = kwargs.pop('bl_idname', None)
        if not bl_idname:
            bl_idname = f"{bl_idname_prefix}.{ADDON_CLASS_PREFIX.lower()}_f_{func_name}"

        if default_draw:
            OPERATORS_TO_DRAW.append(bl_idname)

        kwds = dict(
            bl_idname = bl_idname,
            bl_label = bl_label,
            _execute = staticmethod(func),
            **kwargs
        )

        globals()[class_name] = type(class_name, (Operator_Class_Base, *class_bases), kwds)

        return func

    return decor
