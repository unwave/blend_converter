""" A collection of wxPython utilities. """

import operator
import os
import re
import time as sys_time
import typing
from datetime import datetime
import ctypes
import functools
import itertools


import wx
import wx.adv
import wx.lib.masked
import wx.py.editwindow
from wx import stc
from wx.lib.agw import ultimatelistctrl as ULC
from wx.lib.intctrl import IntCtrl



def get_on_pop_up_menu(parent, items: typing.List[typing.Tuple[str, typing.Callable]]):
    """
    `Usage:`
    ```
    def func(event: wx.CommandEvent):
        pass

    popup_items = [
        ('Name', func)
        ]

    self.attr.Bind(wx.EVT_CONTEXT_MENU, wx_utils.get_on_pop_up_menu(self, popup_items))
    ```
    """

    def pop_up_menu(event):
        menu = wx.Menu()

        for name, func in items:
            menu_item = wx.MenuItem(menu, wx.Window.NewControlId(), name)
            menu.Append(menu_item)
            menu.Bind(wx.EVT_MENU, func, menu_item)

        parent.PopupMenu(menu)
        menu.Destroy()

    return pop_up_menu



def set_ToolTip_update(widget: wx.StaticText, update_func: typing.Callable):

    SetLabel = widget.SetLabel

    def func(label):
        SetLabel(label)
        widget.SetToolTip(update_func())

    widget.SetLabel = func


class Context_Menu(wx.Menu):
    parent: wx.Window
    event: wx.Event


    def __init__(self, parent, event, **kwargs):
        super().__init__(**kwargs)
        self.parent = parent
        self.event = event


    def append_item(self, name: str, func: typing.Callable, bitmap: typing.Union[wx.Bitmap, None] = None):
        item = wx.MenuItem(self, wx.Window.NewControlId(), name)
        self.Append(item)
        self.Bind(wx.EVT_MENU, func, item)
        if bitmap is not None:
            item.SetBitmap(bitmap)
        return item


    def append_separator(self):
        self.AppendSeparator()


def get_small_icon(bitmap: wx.Bitmap):
    return wx.Bitmap(bitmap.ConvertToImage().Scale(64, 64, wx.IMAGE_QUALITY_HIGH))


class Item_Viewer(ULC.UltimateListCtrl):


    def __init__(self, *args, **kwargs):
        kwargs['agwStyle'] = wx.LC_REPORT|wx.LC_HRULES|wx.LC_VRULES|ULC.ULC_SHOW_TOOLTIPS|ULC.ULC_HAS_VARIABLE_ROW_HEIGHT|ULC.ULC_SINGLE_SEL|ULC.ULC_NO_ITEM_DRAG|ULC.ULC_VIRTUAL
        super().__init__(*args, **kwargs)

        # self.locale = wx.Locale(wx.LANGUAGE_ENGLISH)

        self.EnableSelectionVista(True)

        self.Bind(ULC.EVT_LIST_ITEM_SELECTED, self.on_item_selected)
        self.Bind(wx.EVT_LEFT_DCLICK, self._on_left_double_click)
        self.Bind(ULC.EVT_LIST_ITEM_RIGHT_CLICK, self.on_right_click)
        self.Bind(ULC.EVT_LIST_ITEM_CHECKING, self.on_item_checking)


    def set_columns(self, columns):
        for i, (column, width) in enumerate(columns):
            self.InsertColumn(i, column, width=wx.LIST_AUTOSIZE)
            self.SetColumnWidth(i, width)


    def OnGetItemText(self, item: int, col: int):
        return 'OnGetItemText'


    def OnGetItemToolTip(self, item: int, col: int):
        return self.OnGetItemText(item, col)


    def OnGetItemTextColour(self, item: int, col: int):
        return None


    def _on_left_double_click(self, event: wx.MouseEvent):
        item, flags = self.HitTest(event.GetPosition())
        if flags and flags & ULC.ULC_HITTEST_ONITEM:
            self.on_left_double_click(item, event)


    def on_left_double_click(self, index: int, event: wx.MouseEvent):
        print('on_left_double_click', index)


    def on_right_click(self, event: ULC.UltimateListEvent):
        index = event.GetIndex()
        print('on_right_click', index)


    def on_item_selected(self, event: ULC.UltimateListEvent):
        index = event.GetIndex()
        print('on_item_selected', index)


    def on_item_checking(self, event: ULC.UltimateListEvent):
        index = event.GetIndex()
        print('on_item_checking', index)


# class Item_Viewer_Native(wx.ListCtrl, listctrl.ListCtrlAutoWidthMixin):
class Item_Viewer_Native(wx.ListCtrl):


    def __init__(self, *args, **kwargs):

        if not 'style' in kwargs:
            kwargs['style'] = wx.LC_REPORT | wx.LC_HRULES | wx.LC_VRULES | wx.LC_VIRTUAL

        super().__init__(*args, **kwargs)
        # listctrl.ListCtrlAutoWidthMixin.__init__(self)

        # self.EnableCheckBoxes(False)

        self.Bind(wx.EVT_LEFT_DCLICK, self._on_left_double_click)

        self.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_item_selected)
        self.Bind(wx.EVT_LIST_ITEM_RIGHT_CLICK, self.on_right_click)
        # self.Bind(ULC.EVT_LIST_ITEM_CHECKING, self.on_item_checking)


    # def setResizeColumn(self, value):
    #     pass


    def set_columns(self, columns):
        for i, (column, width) in enumerate(columns):
            self.InsertColumn(i, column)
            self.SetColumnWidth(i, width)


    def OnGetItemText(self, item: int, col: int):
        return 'OnGetItemText'


    def OnGetItemToolTip(self, item: int, col: int):
        return 'OnGetItemToolTip'


    def OnGetItemTextColour(self, item: int, col: int):
        return None


    def _on_left_double_click(self, event: wx.MouseEvent):
        item, flags = self.HitTest(event.GetPosition())
        if flags & wx.LIST_HITTEST_ONITEM:
            self.on_left_double_click(item, event)


    def on_left_double_click(self, index: int, event: wx.MouseEvent):
        print('on_left_double_click', index)


    def on_right_click(self, event: wx.ListEvent):
        index = event.GetIndex()
        print('on_right_click', index)


    def on_item_selected(self, event: wx.ListEvent):
        index = event.GetIndex()
        print('on_item_selected', index)


    def on_item_checking(self, event: wx.ListEvent):
        index = event.GetIndex()
        print('on_item_checking', index)


    def deselect_all(self):
        index = self.GetFirstSelected()
        while index >= 0:
            self.Select(index, 0)
            index = self.GetNextSelected(index)


    def get_selected_indexes(self) -> typing.List[int]:
        index = self.GetFirstSelected()
        indexes = []
        while index >= 0:
            indexes.append(index)
            index = self.GetNextSelected(index)

        return indexes


    def get_visible_indexes(self):
        start_index = self.GetTopItem()
        end_index = start_index + self.GetCountPerPage() + 1
        end_index = min(end_index, len(self.GetItemCount()))
        return range(start_index, end_index)


    def setResizeColumn(self, col):
        pass


    def resizeLastColumn(self, minWidth):
        pass


    def resizeColumn(self, minWidth):
        pass


    def get_item_text(self, index: int):
        return [self.OnGetItemText(index, col) for col in range(self.ColumnCount)]


    def get_selected_items_text(self):
        lines: typing.List[typing.List[str]] = []
        for row in self.get_selected_indexes():
            lines.append([self.OnGetItemText(row, column) for column in range(self.ColumnCount)])
        return lines


    def get_active_index(self):
        if self.GetSelectedItemCount():
            return self.GetFocusedItem()
        else:
            return -1


def get_click_position(parent: wx.Window, size_x = 400, size_y = 300):
    a, b = wx.Display(wx.Display.GetFromWindow(parent)).GetGeometry().GetSize()
    x, y = wx.GetMouseState().GetPosition()
    return (min(a - size_x, x), min(b - size_y, y))


class Search_Preset(dict[str, typing.Any]):
    name: str
    query: str
    is_default: bool
    ctime: float
    mtime: float


    @classmethod
    def from_data(cls, data: dict):
        preset = cls()
        preset.update(data)
        return preset


    @classmethod
    def new(cls, query: str, name: typing.Optional[str] = None):
        preset = cls()

        time = sys_time.time()
        preset.update({
            'name': name if name else query,
            'query': query,
            'is_default': False,
            'ctime': time,
            'mtime': time,
        })

        return preset


    def __getattribute__(self, key):
        return self[key] if key in self else super().__getattribute__(key)


    def __setattr__(self, key: str, value):
        if key in self:
            self[key] = value
        else:
            super().__setattr__(key, value)
        self['mtime'] = sys_time.time()


class Search_Bar(wx.Panel):


    def __init__(self, parent, presets: typing.Optional[typing.List[dict]] = None, **kwargs):
        super().__init__(parent, **kwargs)

        if presets is None:
            presets = []

        self.presets = presets

        sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.SetSizer(sizer)

        self.search = wx.SearchCtrl(self, style = wx.TE_PROCESS_ENTER)
        self.search.ShowCancelButton(True)
        sizer.Add(self.search, 3, wx.EXPAND)
        for event in (wx.EVT_TEXT, wx.EVT_SEARCH):
            self.search.Bind(event, self.on_search)

        self.search_history = []
        self.search_history_index = 0
        self.last_edit = sys_time.time()

        self.prev_button = wx.Button(self, label = "<", style = wx.NO_BORDER)
        sizer.Add(self.prev_button, 0, wx.EXPAND)
        self.prev_button.Bind(wx.EVT_BUTTON, self.on_prev)
        self.prev_button.Disable()

        self.next_button = wx.Button(self, label = ">", style = wx.NO_BORDER)
        sizer.Add(self.next_button, 0, wx.EXPAND)
        self.next_button.Bind(wx.EVT_BUTTON, self.on_next)
        self.next_button.Disable()

        self.presets_ComboBox = wx.ComboBox(self, style = wx.CB_READONLY)
        sizer.Add(self.presets_ComboBox, 1, wx.EXPAND)
        self.presets_ComboBox.Bind(wx.EVT_COMBOBOX, self.on_preset_selected)
        self.presets_ComboBox.Bind(wx.EVT_CONTEXT_MENU, self.on_presets_menu)

        self.set_presets()


    def on_prev(self, event):
        index = max(0, self.search_history_index - 1)

        self.next_button.Enable()
        if index == 0:
            self.prev_button.Disable()

        self.search_history_index = index
        self.set_search(self.search_history[self.search_history_index])


    def on_next(self, event):
        index = min(self.search_history_index + 1, len(self.search_history) - 1)

        self.prev_button.Enable()
        if index == len(self.search_history) - 1:
            self.next_button.Disable()

        self.search_history_index = index
        self.set_search(self.search_history[self.search_history_index])


    def set_presets(self, presets: typing.Optional[typing.List[dict]] = None):
        if presets:
            self.presets = presets

        self.presets_ComboBox.Clear()

        for preset in sorted(self.presets, key = operator.itemgetter('name')):
            self.presets_ComboBox.Append(preset['name'], preset)


    def on_preset_selected(self, event: wx.CommandEvent):
        index = self.presets_ComboBox.GetSelection()
        if index == wx.NOT_FOUND:
            return

        self.set_search(self.presets_ComboBox.GetClientData(index)['query'])


    def search_default(self):
        for index, preset in enumerate(self.presets):
            if preset.get('is_default'):
                self.presets_ComboBox.SetSelection(index)
                self.search.SetValue(preset['query'])
                break


    def on_presets_menu(self, event):
        menu = wx.Menu()

        def add_action(name: str, func: typing.Callable):
            menu_item = wx.MenuItem(menu, wx.Window.NewControlId(), name)
            menu.Append(menu_item)
            menu.Bind(wx.EVT_MENU, func, menu_item)

        add_action('Add', self.add_preset)

        if not self.presets_ComboBox.IsListEmpty():

            menu.AppendSeparator()
            add_action('Set As Default', self.set_default_preset)
            add_action('Rename', self.rename_preset)
            add_action('Update', self.update_query)

            menu.AppendSeparator()
            add_action('Delete', self.del_preset)

        self.PopupMenu(menu)
        menu.Destroy()


    def add_preset(self, event: wx.CommandEvent):
        query = self.search.GetValue()

        preset = Search_Preset.new(query)
        index = self.presets_ComboBox.Append(query, preset)
        self.presets_ComboBox.SetSelection(index)
        self.presets.append(preset)
        self.save_presets()


    def rename_preset(self, event: wx.CommandEvent):
        index = self.presets_ComboBox.GetSelection()
        if index == wx.NOT_FOUND:
            return

        with wx.TextEntryDialog(self, "Preset Name:", caption="Input New Name", value = self.presets_ComboBox.GetString(index), style=wx.OK | wx.CANCEL) as dialog:
            result = dialog.ShowModal()
            if result not in (wx.OK, wx.ID_OK):
                return

            new_name = dialog.GetValue()

        self.presets_ComboBox.SetString(index, new_name)
        preset = self.presets_ComboBox.GetClientData(index)
        preset.name = new_name
        self.save_presets()


    def update_query(self, event: wx.CommandEvent):
        index = self.presets_ComboBox.GetSelection()
        if index == wx.NOT_FOUND:
            return

        preset = self.presets_ComboBox.GetClientData(index)
        preset.query = self.search.GetValue()
        self.save_presets()


    def del_preset(self, event: wx.CommandEvent):
        index = self.presets_ComboBox.GetSelection()
        if index == wx.NOT_FOUND:
            return

        preset = self.presets_ComboBox.GetClientData(index)
        self.presets_ComboBox.Delete(index)
        self.presets.remove(preset)
        self.save_presets()
        self.presets_ComboBox.Refresh()


    def set_default_preset(self, event: wx.CommandEvent):
        index_def = self.presets_ComboBox.GetSelection()
        if index_def == wx.NOT_FOUND:
            return

        for index, name in enumerate(self.presets_ComboBox.GetStrings()):
            preset = self.presets_ComboBox.GetClientData(index)
            preset.is_default = False

        preset = self.presets_ComboBox.GetClientData(index_def)
        preset.is_default  = True

        self.save_presets()


    def save_presets(self):
        raise NotImplementedError('You must override this function.')


    def update_search_history(self, query: str, is_redo_undo = False, create_undo = False, HISTORY_DEBUG = 0):

        if not self.search_history:
            self.search_history.append(query)
            return

        if is_redo_undo:
            if HISTORY_DEBUG: print('-redo/undo-')
            return

        def is_last():
            return self.search_history_index == len(self.search_history) - 1

        prev_query = self.search_history[self.search_history_index]
        if prev_query == query and is_last():
            return

        current_time = sys_time.time()

        def is_entering_continuation():
            return current_time - self.last_edit < 4

            # trying to be smart
            # prev_query = self.search_history[self.search_history_index]

            # fragments = query.split()
            # prev_fragments = prev_query.split()

            # if not (fragments and prev_fragments):
            #     return False

            # if len(fragments) != len(prev_fragments):
            #     return False

            # for fragment, prev_fragment in zip(fragments, prev_fragments):
            #     if not (fragment.startswith(prev_fragment) or prev_fragment.startswith(fragment)):
            #         return False

        if not create_undo and is_last() and is_entering_continuation():
            self.last_edit = current_time
            self.search_history[self.search_history_index] = query
            return

        self.last_edit = current_time

        self.search_history = self.search_history[:self.search_history_index + 1]
        self.search_history.append(query)
        self.search_history_index += 1
        self.prev_button.Enable()
        self.next_button.Disable()


    def on_search(self, event = None, is_redo_undo = False, create_undo = False):

        query = self.search.GetValue().strip()

        HISTORY_DEBUG = 0
        if HISTORY_DEBUG:
            os.system('cls')

        self.update_search_history(query, is_redo_undo, create_undo, HISTORY_DEBUG)

        if HISTORY_DEBUG:
            print('index: ', self.search_history_index)
            print(*self.search_history, sep = '\n')
            print()

        return self.execute_search(query)


    def execute_search(self, query: str):
        raise NotImplementedError('You must override this function.')


    def set_search(self, query: str, create_undo = True):
        self.search.ChangeValue(query)
        self.on_search(create_undo = create_undo)


# python 3.9.12 bug

# # does not work
# def get_wx_datetime(timestamp):
#     return wx.DateTime.FromTimeT(timestamp)

# # works only for the first time
# def get_wx_datetime(timestamp):
#     return wx.DateTime().SetTimeT(int(timestamp))

# https://discuss.wxpython.org/t/wxdatepickerctrl-not-returning-month-correctly/21388/9
# Beware: the months in this class are in an array starting with zero (Jan) and ending with eleven(Dec)
def get_wx_datetime(timestamp: float):
    date = datetime.fromtimestamp(timestamp)
    return wx.DateTime.FromDMY(date.day, date.month - 1, date.year, date.hour, date.minute, date.second, int(date.microsecond/1000))


class Date_Time_Picker(wx.Panel):

    def __init__(self, parent, default: float, min: float, max: float, **kwargs):
        super().__init__(parent, **kwargs)

        self.min = min
        self.max = max

        sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.SetSizer(sizer)

        date_time = get_wx_datetime(default)

        self.date = wx.adv.DatePickerCtrl(self)
        sizer.Add(self.date, 1, wx.EXPAND)
        self.date.Bind(wx.adv.EVT_DATE_CHANGED, self.on_change)
        self.date.SetValue(date_time)

        self.time = wx.adv.TimePickerCtrl(self)
        # self.time = wx.lib.masked.timectrl.TimeCtrl(self, fmt24hr = True)
        sizer.Add(self.time, 1, wx.EXPAND)
        self.time.Bind(wx.adv.EVT_TIME_CHANGED, self.on_change)
        self.time.SetValue(date_time)

        # spin_button = wx.SpinButton(self)
        # sizer.Add(spin_button, 0, wx.EXPAND)
        # self.time.BindSpinButton(spin_button)

        if get_wx_datetime(min).GetDateOnly() == get_wx_datetime(max).GetDateOnly():
            self.date.Disable()


    @property
    def value(self):
        date_time = self.date.GetValue().GetDateOnly() # type: wx.DateTime
        days_time = date_time.GetValue() / 1000

        # date_time = self.time.GetValue(as_wxDateTime = True) # type: wx.DateTime
        secs_time = (self.time.GetValue().GetValue() - self.time.GetValue().GetDateOnly().GetValue()) / 1000

        return days_time + secs_time


    def on_change(self, event: wx.Event):
        event.Skip()

        time = self.value

        time = max(time, self.min)
        time = min(time, self.max)

        date_time = get_wx_datetime(time)

        self.date.SetValue(date_time)
        self.time.SetValue(date_time)


    def GetValue(self):
        return self.value


class Generic_Selector_Dialog(wx.Dialog):


    def __init__(self, parent: wx.Window, data_dict: dict[str, typing.Any], ok_default = True, **kwargs):

        if not 'style' in kwargs:
            kwargs['style'] = wx.RESIZE_BORDER | wx.CAPTION | wx.CLOSE_BOX | wx.SYSTEM_MENU

        if not 'font' in kwargs:
            kwargs['font'] = parent.GetFont()

        if not 'pos' in kwargs:
            kwargs['pos'] = get_click_position(parent)

        font = kwargs.pop('font', None)

        super().__init__(parent, **kwargs)

        self.parent = parent
        self.data_dict = data_dict

        if font:
            self.SetFont(font)

        self.main_sizer = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(self.main_sizer)

        self.pre_entries_init()

        self.entry_sizer = wx.FlexGridSizer(cols=2, vgap=5, hgap=5)
        self.main_sizer.Add(self.entry_sizer, 1, wx.EXPAND | wx.ALL, border = 5)

        self.entries: typing.Dict[str, typing.Union[wx.TextCtrl, wx.ComboBox, wx.CheckBox, IntCtrl, Date_Time_Picker, TextEditor]] = {}
        self.set_entries()

        self.entry_sizer.AddGrowableCol(1)

        self.button_sizer = wx.StdDialogButtonSizer()
        self.main_sizer.Add(self.button_sizer, 0, wx.EXPAND | wx.ALL, border = 5)

        button = wx.Button(self, wx.ID_OK)
        self.button_sizer.AddButton(button)
        self.ok_button = button

        button = wx.Button(self, wx.ID_CANCEL)
        self.button_sizer.AddButton(button)
        self.button_sizer.Realize()

        if ok_default:
            self.ok_button.SetDefault()
        else:
            button.SetDefault()

        self.SetMinSize((600, -1))
        self.Fit()
        x, y = self.GetSize()
        self.SetMinSize((600, y))
        self.SetMaxSize((-1, y))


    def set_entries(self):
        for key, value in self.data_dict.items():

            value_type = type(value)

            if value_type == str:
                self.add_string_entry(key, value)
            elif value_type == list:
                self.add_enum_entry(key, value)
            elif value_type == bool:
                self.add_bool_entry(key, value)
            elif value_type == int:
                self.add_int_entry(key, value)
            elif value_type == float:
                self.add_float_entry(key, value)
            elif value_type == dict:
                self.add_named_enum_entry(key, value)
            elif value_type == tuple:
                if type(value[0]) == dict:
                    self.add_named_enum_entry(key, *value)
                elif type(value[0]) == list:
                    self.add_enum_entry(key, *value)
                elif value[0] == 'text':
                    self.add_text_entry(key, *value[1:])
                elif value[0] == 'time':
                    self.add_date_time_entry(key, *value[1:])


    def get_data(self):
        data = {}

        for key, entry in self.entries.items():
            if isinstance(entry, (wx.TextCtrl, wx.CheckBox, IntCtrl, Date_Time_Picker, TextEditor, wx.SpinCtrlDouble)):
                data[key] = entry.GetValue()
            elif isinstance(entry, wx.ComboBox):
                data[key] = entry.GetClientData(entry.GetSelection())

        return data


    def pre_entries_init(self):
        """ You need to override it """


    def add_title(self, string: str):
        self.entry_sizer.Add(wx.StaticText(self, label = string), 0, wx.ALIGN_LEFT)


    def add_int_entry(self, key: str, value: int):
        self.add_title(key)
        entry = IntCtrl(self, value = value)
        self.entries[key] = entry
        self.entry_sizer.Add(entry, 0, wx.EXPAND)


    def add_string_entry(self, key: str, value: str):
        self.add_title(key)
        entry = wx.TextCtrl(self, value = value)
        self.entries[key] = entry
        self.entry_sizer.Add(entry, 0, wx.EXPAND)


    def add_bool_entry(self, key: str, value: bool):
        self.add_title(key)
        entry = wx.CheckBox(self)
        self.entries[key] = entry
        self.entry_sizer.Add(entry, 0, wx.EXPAND)
        entry.SetValue(value)


    def add_enum_entry(self, key: str, value: list, default_value: typing.Optional[str] = None, titleize = False):
        self.add_title(key)
        entry = wx.ComboBox(self, style = wx.CB_READONLY)
        self.entries[key] = entry
        self.entry_sizer.Add(entry, 0, wx.EXPAND)

        for sub_value in value:

            if titleize:
                name = str(sub_value).title()
            else:
                name = str(sub_value)

            entry.Append(name, sub_value)

        if entry.GetCount() >= 1:
            if default_value is not None:
                for index in range(entry.GetCount()):
                    if default_value == entry.GetClientData(index):
                        entry.SetSelection(index)
            else:
                entry.SetSelection(0)


    def add_named_enum_entry(self, key: str, value: typing.Dict[str, typing.Any], default_value: typing.Any = None, titleize = False):
        self.add_title(key)
        entry = wx.ComboBox(self, style = wx.CB_READONLY)
        self.entries[key] = entry
        self.entry_sizer.Add(entry, 0, wx.EXPAND)

        for name, data in value.items():

            if titleize:
                name = str(name).title()
            else:
                name = str(name)

            entry.Append(name, data)

        if entry.GetCount() >= 1:
            if default_value:
                for index in range(entry.GetCount()):
                    if default_value == entry.GetClientData(index):
                        entry.SetSelection(index)
            else:
                entry.SetSelection(0)


    def add_date_time_entry(self, key: str, default_time: float, min_time: float, max_time: float):

        self.add_title(key)

        entry = Date_Time_Picker(self, default_time, min_time, max_time)
        self.entries[key] = entry
        self.entry_sizer.Add(entry, 0, wx.EXPAND)


    def __enter__(self):
        super().__enter__()
        return self


    def add_text_entry(self, key: str, value: str):
        self.add_title(key)
        entry = TextEditor(self)
        # entry.SetFont(self.GetFont())
        entry.SetZoom(5)
        entry.SetValue(value)
        entry.update_spell_checking()
        self.entries[key] = entry
        self.entry_sizer.Add(entry, 1, wx.EXPAND)
        self.entry_sizer.AddGrowableRow(self.entry_sizer.GetEffectiveRowsCount() - 1)


    def add_float_entry(self, key: str, value: float):
        self.add_title(key)
        entry = wx.SpinCtrlDouble(self, value = str(value))
        entry.SetDigits(3)
        self.entries[key] = entry
        self.entry_sizer.Add(entry, 0, wx.EXPAND)


class Generic_Frame(wx.Frame):


    def __init__(self, parent, app_id_name = 'my_test', font: typing.Optional[wx.Font] = None, icon: typing.Optional[wx.Icon] = None, **kwargs):
        super().__init__(parent, **kwargs)

        self.SetDoubleBuffered(True)

        if font:
            self.SetFont(font)

        if icon:
            self.SetIcon(icon)

        self.SetTitle(app_id_name.title())
        if os.name == 'nt':
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id_name)

            if not 'PROMPT' in os.environ:
                console = ctypes.windll.kernel32.GetConsoleWindow()
                menu = ctypes.windll.user32.GetSystemMenu(console, 0)
                ctypes.windll.user32.DeleteMenu(menu, 0xF060, 0)

        self.statusbar: wx.StatusBar = self.CreateStatusBar()
        self.statusbar.SetStatusText('')

        self.menubar = wx.MenuBar()
        self.SetMenuBar(self.menubar)
        self.menubar.Bind(wx.EVT_MENU_HIGHLIGHT, self.on_menu_item_highlight)
        self.menubar.Bind(wx.EVT_MENU_CLOSE, self.on_menu_closed)
        if font:
            self.menubar.SetFont(font)

        self.set_menu_bar()
        self.set_toggle_console_menu_item()


    def set_menu_bar(self):

        test = wx.Menu()
        self.menubar.Append(test, "&Override Me")

        item = test.Append(wx.ID_ANY, "Override Me") # type: wx.MenuItem
        self.Bind(wx.EVT_MENU, lambda event: print("Override Me"), item)
        item.SetHelp("You need to override this.")

        test.AppendSeparator()


    def set_toggle_console_menu_item(self):

        index = self.menubar.FindMenu('Window')
        if index == wx.NOT_FOUND:
            menu = wx.Menu()
            self.menubar.Append(menu, '&Window')
        else:
            menu = self.menubar.GetMenu(index)

        if os.name == 'nt':
            self.is_console_shown = True
            item = menu.Append(wx.ID_ANY, 'Toggle Console') # type: wx.MenuItem
            self.Bind(wx.EVT_MENU, self.on_toggle_console, item)
            item.SetHelp("Toggle the system console.")


    def on_menu_item_highlight(self, event: wx.MenuEvent):
        item = event.GetMenu().FindItemById(event.GetMenuId())
        if not item:
            return

        help = item.GetHelp() # type: wx.MenuItem
        self.statusbar.SetStatusText(help)


    def on_menu_closed(self, event: wx.MenuEvent):
        self.statusbar.SetStatusText('')


    def on_toggle_console(self, event):
        if self.is_console_shown:
            self.show_console(False)
        else:
            self.show_console()


    def show_console(self, value: bool = True):
        # https://discuss.wxpython.org/t/mask-or-redirect-console-window-of-external-program/34195/6
        # https://stackoverflow.com/questions/20232685/how-can-i-prevent-my-program-from-closing-when-a-open-console-window-is-closed/20236791#20236791
        # https://stackoverflow.com/a/25322305/11799308
        if value:
            nCmdShow = 5 # SW_SHOW
            self.is_console_shown = True
        else:
            nCmdShow = 0 # SW_HIDE
            self.is_console_shown = False

        console = ctypes.windll.kernel32.GetConsoleWindow()
        ctypes.windll.user32.ShowWindow(console, nCmdShow)


class App(wx.App):

    def InitLocale(self):
        """ https://github.com/wxWidgets/Phoenix/issues/1637#issuecomment-763933443 """

        if os.name == 'nt':
            import locale
            locale.setlocale(locale.LC_ALL, "C")


helps = {}
status_bar: typing.Optional[wx.StatusBar] = None
current_window: typing.Optional[wx.Window] = None


def set_help(window: wx.Window, string: str):
    global status_bar

    if not status_bar:
        status_bar = window.GetTopLevelParent().GetStatusBar()

    if not status_bar:
        raise Exception('No status bar found!')

    helps[window] = string
    window.Bind(wx.EVT_ENTER_WINDOW, show_help)
    window.Bind(wx.EVT_LEAVE_WINDOW, remove_help)


# https://discuss.wxpython.org/t/wx-evt-enter-window-and-wx-evt-leave-window-delayed-under-ms-windows-vista/22931/4
# There is no guarantee on the consistency of the delivery order of events

def show_help(event: wx.MouseEvent):
    if status_bar:
        window = event.GetEventObject() # type: wx.Window
        status_bar.SetStatusText(helps[window])
        global current_window
        current_window = window


def remove_help(event: wx.MouseEvent):
    if status_bar:
        window = event.GetEventObject() # type: wx.Window
        if current_window == window:
            status_bar.SetStatusText('')


LANGUAGES = {
    'en': "'abcdefghijklmnopqrstuvwxyz",
    'ru': 'абвгдежзийклмнопрстуфхцчшщъыьэюяё',

    # 'de': 'abcdefghijklmnopqrstuvwxyzßäöü',
    # 'es': 'abcdefghijklmnopqrstuvwxyzáéíñóúü',
    # 'fr': 'abcdefghijklmnopqrstuvwxyzàâæçèéêëîïôùûüœ',
    # 'pt': 'abcdefghijklmnopqrstuvwxyzàáâãçéêíóôõú',
}


@functools.lru_cache(None)
def get_spell_checker():
    from spellchecker import SpellChecker
    return SpellChecker(LANGUAGES.keys())


class TextEditor(wx.py.editwindow.EditWindow):


    @functools.cached_property
    def re_word(self):

        letter_bytes = set()
        for letter in itertools.chain(*LANGUAGES.values()):
            letter_bytes.add(letter.encode())

        return re.compile(b"((?:" + b'|'.join(letter_bytes) + b")+)")


    @functools.cached_property
    def dictionary(self):
        return get_spell_checker().word_frequency.dictionary


    @functools.cached_property
    def longest_word_length(self):
        return get_spell_checker().word_frequency.longest_word_length


    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.ClearDocumentStyle()
        # self.StyleClearAll()
        self.SetLexer(stc.STC_LEX_NULL)

        self.setDisplayLineNumbers(True)

        self.IndicatorSetStyle(0, stc.STC_INDIC_SQUIGGLE)
        self.IndicatorSetForeground(0, 'red')
        self.IndicatorSetUnder(0, True)
        self.SetWrapMode(stc.STC_WRAP_WORD)

        self.Bind(stc.EVT_STC_UPDATEUI, self.on_change)
        self.Bind(stc.EVT_STC_ZOOM, self.on_change)
        self.Bind(stc.EVT_STC_NEEDSHOWN, self.on_change)


    def check_word_iter(self, text: bytes):

        longest_word_length = self.longest_word_length
        dictionary = self.dictionary

        for match in self.re_word.finditer(text):
            word = match.group(0).decode()

            if len(word) < 2:
                continue

            if len(word) > longest_word_length:
                yield match

            if not word in dictionary:
                yield match


    def on_change(self, event: stc.StyledTextEvent):

        if not event.GetUpdated() in (stc.STC_UPDATE_CONTENT, stc.STC_UPDATE_V_SCROLL, stc.STC_UPDATE_H_SCROLL):
            return

        self.update_spell_checking()


    def update_spell_checking(self):

        start_pos = self.CharPositionFromPoint(0, 0)
        end_pos = self.CharPositionFromPoint(*self.GetSize())

        self.SetIndicatorCurrent(0)
        self.IndicatorClearRange(start_pos, end_pos - start_pos)

        for match in self.check_word_iter(self.GetTextRangeRaw(start_pos, end_pos).lower()):
            start, end = match.span()
            self.IndicatorFillRange(start_pos + start, end - start)


def is_image_in_clipboard():
    if not wx.TheClipboard.Open():
        return False
    success = wx.TheClipboard.GetData(wx.BitmapDataObject())
    wx.TheClipboard.Close()
    return success

def get_bitmap_from_clipboard() -> wx.Bitmap:
    if not wx.TheClipboard.Open():
        return None

    bitmap = wx.BitmapDataObject()
    success = wx.TheClipboard.GetData(bitmap)
    wx.TheClipboard.Close()

    return bitmap.GetBitmap() if success else None


def get_clipboard_text() -> str:
    if not wx.TheClipboard.Open():
        return None

    text_data = wx.TextDataObject()
    success = wx.TheClipboard.GetData(text_data)
    wx.TheClipboard.Close()

    return text_data.GetText() if success else None


def set_clipboard_text(text: str):

    try:
        import pyperclip

    except ImportError:

        if wx.TheClipboard.IsOpened():
            wx.TheClipboard.Close()

        if wx.TheClipboard.Open():
            wx.TheClipboard.SetData(wx.TextDataObject(text))
            wx.TheClipboard.GetData(wx.TextDataObject())
            wx.TheClipboard.Flush()
            wx.TheClipboard.Close()
        else:
            wx.MessageBox('Unable to open the clipboard.', 'Error', style= wx.OK | wx.ICON_ERROR)

    else:
        pyperclip.copy(text)




class Bitmaps(typing.Dict[str,  wx.Bitmap], dict):


    def __init__(self, *args, **kwargs):
        super().__init__( *args, **kwargs)
        self.images: typing.Dict[str,  wx.Image] = {}


    def get_bitmap(self, path: str, resolution: int, reload = False):

        key = str(path) + str(resolution)

        bitmap = self.get(key)
        if bitmap and not reload:
            return bitmap

        image = self.get_image(path, reload)
        if not image:
            return wx.NullBitmap

        bitmap = wx.Bitmap(image.Scale(resolution, resolution, wx.IMAGE_QUALITY_HIGH))

        self[key] = bitmap
        return bitmap


    def get_image(self, path: str, reload = False):

        image = self.images.get(path)
        if not image or reload:

            image = wx.Image()
            # eXif: duplicate
            image.SetLoadFlags(image.GetLoadFlags() & ~1)
            image.LoadFile(path)

            self.images[path] = image


        return image


    def get_hash(path: str):
        stat = os.stat(path)
        return hash(map(str, (stat.st_size, stat.st_mtime, stat.st_ino, os.path.splitext(path)[1])))


def get_input(parent: wx.Window, data_dict: dict, title = ''):
    """ Generic_Selector_Dialog wrapper. """

    with Generic_Selector_Dialog(parent, data_dict, title = title, pos = get_click_position(parent), font = parent.GetTopLevelParent().GetFont()) as dialog:
        result = dialog.ShowModal()

        if result != wx.ID_OK:
            return None

        return dialog.get_data()


def show_tip(parent: wx.Window, title: str, message: str, icon = wx.ICON_WARNING):
    tip = wx.adv.RichToolTip(title, message)
    tip.SetIcon(icon)
    tip.ShowFor(parent)

def show_warning(parent: wx.Window, title: str, message: str):
    show_tip(parent, title, message, wx.ICON_WARNING)

def show_info(parent: wx.Window, title: str, message: str):
    show_tip(parent, title, message, wx.ICON_INFORMATION)


class Text_Dialog(wx.Dialog):

    def __init__(self, parent, title: str, text: str):

        super().__init__(parent, title=title, size=(800, 500), style= wx.RESIZE_BORDER | wx.CAPTION | wx.CLOSE_BOX | wx.SYSTEM_MENU)

        self.main_sizer = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(self.main_sizer)

        self.text_ctrl = wx.TextCtrl(self, wx.ID_ANY, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.VSCROLL)

        self.text_ctrl.SetValue(text)

        self.main_sizer.Add(self.text_ctrl, 1, wx.EXPAND | wx.ALL, border =5 )

        self.Layout()
        self.Centre()
