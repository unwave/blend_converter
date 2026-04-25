import typing
import json
import inspect

import wx
import wx.propgrid as pg

from .. import settings_base
from .. import common


def to_json(value):
    return json.dumps(value, ensure_ascii = False)


def get_property(name: str, value: typing.Any, spec: settings_base.Attribute_Spec):

    if spec.type is int:
        return pg.IntProperty(spec.name, name, value)
    elif spec.type is bool:
        return pg.BoolProperty(spec.name, name, value)
    elif spec.type is float:
        return pg.FloatProperty(spec.name, name, value)
    elif spec.enum_items:
        labels = [x[0] for x in spec.enum_items]
        return pg.EnumProperty(spec.name, name,
            labels = labels,
            values = list(range(len(spec.enum_items))),
            value = labels.index(value),
        )
    elif spec.type is str:
        return pg.StringProperty(spec.name, name, value)
    else:
        return pg.StringProperty(spec.name + ' [JSON]', name, to_json(value))



def get_pg_prop(path: str, value: typing.Any, spec: settings_base.Attribute_Spec):

    is_read_only = False

    if type(value) is dict and value.get(common.K_INSTRUCTION_IDENTIFIER):
        value = f"[{value[common.K_INSTRUCTION_IDENTIFIER]}]"
        is_read_only = True

    property = get_property(path, value, spec)

    if is_read_only:
        property.Enable(False)

    if spec.description:
        property.SetHelpString(spec.description)

    property.SetClientData(spec)

    return property


class Program_Dialog(wx.Dialog):


    def __init__(self, parent: wx.Window, program: common.Program):

        self.program = program

        title = f"Settings - {program.blend_path}"

        super().__init__(parent, title = title, style = wx.RESIZE_BORDER | wx.CAPTION | wx.CLOSE_BOX | wx.SYSTEM_MENU)

        sizer = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(sizer)

        self.grid = pg.PropertyGrid(self, wx.ID_ANY, style = pg.PG_SPLITTER_AUTO_CENTER | pg.PG_BOLD_MODIFIED)
        self.grid.SetExtraStyle(pg.PG_EX_HELP_AS_TOOLTIPS)
        self.grid.Bind(pg.EVT_PG_CHANGED, self.on_property_change)


        for instruction in program.instructions:

            signature = inspect.signature(instruction.func)

            arguments = {name: value for name, value in zip(signature.parameters.keys(), instruction.args)}
            arguments.update(instruction.kwargs)

            instruction_path = instruction.identifier
            instruction_prop = self.grid.Append(pg.PropertyCategory(instruction_path, instruction_path))

            for argument_name, argument in arguments.items():

                argument_path = instruction_path + '.' + argument_name

                if isinstance(argument, settings_base.Settings):

                    argument_prop = self.grid.AppendIn(instruction_prop, pg.PropertyCategory(argument_name, argument_path))

                    for key in argument.__class__.__dict__:

                        if key.startswith('_'):
                            continue

                        spec = argument._get_attribute_spec(key)

                        path = argument_path + '.' + key
                        value = getattr(argument, key, spec.default)

                        self.grid.AppendIn(argument_prop, get_pg_prop(path, value, spec))

                elif isinstance(argument, (bool, int, float, str)):
                    spec = settings_base.Attribute_Spec(name = argument_name, type = type(argument), default = argument)
                    self.grid.AppendIn(instruction_prop, get_pg_prop(argument_path, argument, spec))

                else:

                    spec = settings_base.Attribute_Spec(name = argument_name, type = str, default = '')

                    if type(argument) is dict and argument.get(common.K_INSTRUCTION_IDENTIFIER):
                        value = f"[{argument[common.K_INSTRUCTION_IDENTIFIER]}]"
                    else:
                        value = repr(argument)

                    prop = get_pg_prop(argument_path, value, spec)
                    prop.Enable(False)

                    self.grid.AppendIn(instruction_prop, prop)



        sizer.Add(self.grid, 1, wx.EXPAND)

        self.Layout()


    def on_property_change(self, event):

        prop: pg.PGProperty = event.GetProperty()

        spec: settings_base.Attribute_Spec = prop.GetClientData()

        path: str = prop.GetName()
        value = event.GetPropertyValue()

        if spec.enum_items:
            value = spec.enum_items[value][0]

        print(path, '=', repr(value))

        if value == spec.default:
            prop.SetLabel(spec.name)
        else:
            prop.SetLabel(spec.name + ' [MODIFIED]')

        self.grid.RefreshProperty(prop)


        path_list = path.split('.')

        section = path_list[0]
        option = '.'.join(path_list[1:])

        if not self.program._instructions_config.has_section(section):
            self.program._instructions_config.add_section(section)

        self.program._instructions_config.set(section, option, str(value))

        with open(self.program.settings_path, 'w') as f:
            self.program._instructions_config.write(f)


    if typing.TYPE_CHECKING:

        def __enter__(self):
            return self
