import typing
import json

import wx
import wx.propgrid as pg

from .. import settings_base
from .. import common


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
        prop = pg.StringProperty(spec.name + ' [UNSUPPORTED]', name, repr(value))
        prop.Enable(False)
        return prop


def get_read_only_property(name: str, value: typing.Any, spec: settings_base.Attribute_Spec):

    if common._is_instruction_return(value):
        value = f'[{value[common.K_INSTRUCTION_IDENTIFIER]}]'

    prop = pg.StringProperty(spec.name, name, str(value))
    prop.Enable(False)
    return prop



def get_pg_prop(item: common.Argument_Walk_Item):

    is_type_mismatch = type(item.value) != item.spec.type

    if item.override is common.SENTINEL:
        value = item.value
    else:
        value = item.override

    is_unsupported_type = value is settings_base.SENTINEL

    if item.is_instruction_return or is_type_mismatch or is_unsupported_type:
        property = get_read_only_property('.'.join(item.path), value, item.spec)
    else:
        property = get_property('.'.join(item.path), value, item.spec)

    if item.spec.description:
        property.SetHelpString(item.spec.description)

    property.SetClientData(item.spec)

    if item.override is not common.SENTINEL:
        property.SetModifiedStatus(True)

    return property


class Property_Grid_Dialog(wx.Dialog):


    def __init__(self, parent: wx.Window, arguments: typing.Iterable[common.Argument_Walk_Item]):

        self.changes: typing.Dict[typing.Tuple[str], typing.Any] = {}
        self.do_save = False


        super().__init__(parent, style = wx.RESIZE_BORDER | wx.CAPTION | wx.CLOSE_BOX | wx.SYSTEM_MENU)

        sizer = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(sizer)

        self.grid = pg.PropertyGrid(self, wx.ID_ANY, style = pg.PG_SPLITTER_AUTO_CENTER | pg.PG_BOLD_MODIFIED)
        sizer.Add(self.grid, 1, wx.EXPAND)
        self.grid.Bind(pg.EVT_PG_CHANGED, self.on_property_change)


        for item in arguments:
            category = self.get_category(item.path)
            self.grid.AppendIn(category, get_pg_prop(item))


        self.description_ctrl = wx.TextCtrl(self, style = wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_BESTWRAP, size = (-1, 150))
        sizer.Add(self.description_ctrl, 0, wx.EXPAND)

        self.grid.Bind(pg.EVT_PG_SELECTED, self.on_property_selected)


        self.save_ctrl = wx.Button(self, label = "Save And Close")
        sizer.Add(self.save_ctrl, 0, wx.ALL, border = 5)
        self.save_ctrl.Bind(wx.EVT_BUTTON, self.on_save_and_close)


        self.Layout()


    def get_category(self, path: typing.List[str]):

        prop = self.grid.GetPropertyByName('.'.join(path[:-1]))
        if prop:
            return prop

        if len(path) > 1:
            return self.grid.AppendIn(self.get_category(path[:-1]), pg.PropertyCategory(path[-2], '.'.join(path[:-1])))
        else:
            return self.grid.Append(pg.PropertyCategory(path[0], path[0]))


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

        self.changes[tuple(path.split('.'))] = value


    if typing.TYPE_CHECKING:

        def __enter__(self):
            return self


    def on_save_and_close(self, event):

        self.do_save = True
        self.Destroy()


    def on_property_selected(self, event):

        prop: pg.PGProperty = event.GetProperty()
        path: str = prop.GetName()
        path_list = path.split('.')

        spec: settings_base.Attribute_Spec = prop.GetClientData()

        if spec and spec.description:
            description = spec.description
        else:
            if len(path_list) > 1:
                description = "This option does not have a description."
            else:
                description = "This is a name of a function."

        description = ' ● '.join(path_list) + "\n\n" + description

        self.description_ctrl.SetValue(description)
