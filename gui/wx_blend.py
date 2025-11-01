from __future__ import annotations


import operator
import webbrowser
import re
import os
import sys
import typing
import pathlib
import json
import threading
import time as sys_time
from datetime import datetime
from urllib.parse import unquote, urlparse

import pyperclip
import wx
import wx.adv
import wx.lib.scrolledpanel as scrolled


from .. import utils
from .. import common
from .. import updater


from . import wxp_utils



def get_root_path(*name: str):
    return os.path.join(common.ROOT_DIR, *name)


SENTINEL = object()


NUMBER_TYPE_ATTRS = {
    'mtime',
    'ctime',
}

STRING_TYPE_ATTRS = {
    'name',
    'path',
    'json_path'
 }

BASIC_TYPE_ATTRS = NUMBER_TYPE_ATTRS | STRING_TYPE_ATTRS

SUBSTITUTIONS = {
}

def validate_attr(attr: str):
    if attr in SUBSTITUTIONS:
        attr = SUBSTITUTIONS[attr]

    if not attr in BASIC_TYPE_ATTRS:
        return None

    return attr


BITMAPS = wxp_utils.Bitmaps()





class Item(typing.Dict[str, typing.Any], dict):

    name: str
    ctime: float
    mtime: float
    logs: typing.List[dict]
    json_path: str = None

    os_stat = None

    id: list
    search_string: str
    search_set = set()

    template: Item = None


    is_dir: bool
    entries: typing.List[updater.Program_Entry]
    source_path: str


    @property
    def name(self):
        if name := self.get('name'):
            return name

        if self.json_path:
            return os.path.basename(os.path.dirname(self.json_path))

        return 'NO NAME'


    def __repr__(self):
        return f"<Item {self.path}>"


    def __bool__(self):
        return True


    def get_strings(self, value: typing.Union[dict, list]):
        strings = []

        strings.append(self.name)

        if issubclass(type(value), list):
            for sub_value in value:

                if type(sub_value) in (dict, list):
                    strings.extend(self.get_strings(sub_value))
                    continue

                strings.append(str(sub_value))

        elif issubclass(type(value), dict):
            for key, sub_value in value.items():

                if key in NUMBER_TYPE_ATTRS:
                    continue

                if type(sub_value) in (dict, list):
                    strings.extend(self.get_strings(sub_value))
                    continue

                strings.append(str(key))
                strings.append(str(sub_value))

        else:
            raise NotImplementedError(f"The value  '{value}' of type '{type(value)}' is not supported")

        return strings


    def update_search_set(self):
        self.search_string = ' '.join(self.get_strings(self)).lower()


    def __init__(self, *args, **kwargs):
        super().__init__( *args, **kwargs)
        self.lock = threading.RLock()


    @classmethod
    def from_dict(cls, data: dict):
        item = cls(data)

        item.set_time()
        item.update_search_set()
        return item


    @classmethod
    def new_from_dict(cls):
        item = cls()

        item.set_time()
        item.update_search_set()
        return item


    @classmethod
    def from_json(cls, json_path: str):
        with open(json_path, 'r', encoding = 'utf-8') as f:
            data = json.load(f)

        item = cls(data)

        item.json_path = json_path
        item.set_time()
        item.update_search_set()

        return item


    @classmethod
    def new_from_json(cls, json_path: str):

        if os.path.exists(json_path):
            raise BaseException(f'A file exists at the specified path for a new item. {json_path}')

        item = cls()

        item.json_path = json_path

        item.set_time_from_now()

        with open(json_path, 'w', encoding = 'utf-8') as f:
            json.dump(item, f)

        item.set_time()
        item.update_search_set()

        return item


    def set_time_from_now(self):
        time = sys_time.time()
        self.update({
            'ctime': time,
            'mtime': time
        })


    def set_time(self):
        if self.json_path:
            self.os_stat = os.stat(self.json_path)
            if not self.get('ctime'):
                self['ctime'] = self.os_stat.st_ctime


    @property
    def data(self) -> list:
        data = self.get('data')
        if not data:
            self['data'] = data = []
        return data


    def get_entries(self):
        entries = {}

        if self.template:
            for entry in self.template.data:
                entries[(entry['name'], entry['type'])] = (entry, 'template')

        for entry in self.data:
            entries[(entry['name'], entry['type'])] = (entry, 'self')

        return entries


    def get_count(self):
        return len(self.get_entries())


    def get_entry(self, index: int) -> dict:
        entry, entry_type = list(self.get_entries().values())[index]

        if entry_type == 'template':
            return entry.copy()
        else:
            return entry


    def iter_entry(self):
        for index, (entry, entry_type) in enumerate(self.get_entries().values()):
            yield index, entry.copy() if entry_type == 'template' else entry


    def is_template_entry(self, index: int):
        if not self.template:
            return False

        entry, entry_type = list(self.get_entries().values())[index]

        for template_entry in self.template.data:
            if entry['name'] == template_entry['name'] and entry['type'] == template_entry['type']:
                return True

        return False


    def set_entry(self, index: int, new_entry: dict):
        entry, entry_type = list(self.get_entries().values())[index]

        if entry_type == 'template':
            self.data.append(new_entry)
        else:
            self.data[self.data.index(entry)] = new_entry


    def set_entry_data(self, index: int, data: typing.Any):
        entry, entry_type = list(self.get_entries().values())[index]

        if entry_type == 'template':
            entry = self.get_entry(index)
            entry['mtime'] = sys_time.time()
            entry['data'] = data
            self.set_entry(index, entry)
        else:
            entry = self.data[self.data.index(entry)]
            entry['mtime'] = sys_time.time()
            entry['data'] = data


    def set_entry_value(self, index: int, key: str, value: typing.Any):
        entry, entry_type = list(self.get_entries().values())[index]

        if entry_type == 'template':
            entry = self.get_entry(index)
            entry['mtime'] = sys_time.time()
            entry[key] = value
            self.set_entry(index, entry)
        else:
            entry = self.data[self.data.index(entry)]
            entry['mtime'] = sys_time.time()
            entry[key] = value


    def append_entry(self, data: dict):
        self.data.append(data)


    def __getattribute__(self, key):
        return self[key] if key in self else super().__getattribute__(key)


    def __hash__(self):
        return id(self)


    def log(self, name: str, value):
        log = self.get('logs') # type: list
        if not log:
            self['logs'] = log = []

        log.append({
            'name': name,
            'value': value,
            'time': sys_time.time()
        })


    def set_data(self, data: dict):
        self.update(data)
        self.log('set_data', data)
        self.update_search_set()
        self.save()


    def save(self, extra_print = ''):

        with self.lock:

            file_path = self.json_path
            temp_file_path = self.json_path + '@temp'

            if self.os_stat.st_mtime != os.path.getmtime(file_path):
                print(f'The file {file_path} was modified outside. A copy of the modified file created.')
                dir = os.path.dirname(file_path)
                stem, ext = os.path.splitext(os.path.basename(file_path))
                name = f"{stem}_{os.getpid()}_{sys_time.time()}{ext}"
                dst = os.path.join(dir, name)
                import shutil
                shutil.copy2(file_path, dst)

            self['mtime'] = sys_time.time()

            with open(temp_file_path, 'w+') as temp_file:
                json.dump(self, temp_file, indent = 4, ensure_ascii = False)

            os.replace(temp_file_path, file_path)

            self.os_stat = os.stat(file_path)

            print(f"{utils.get_time_str_from(sys_time.time())} JSON saved: {file_path}{' | ' + extra_print if extra_print else ''}")


    @property
    def path(self) -> str:
        if self.json_path:
            return os.path.dirname(self.json_path)
        else:
            return ''


    @property
    def icon_path(self):
        return os.path.join(self.path, '__icon__.png')


    @property
    def basename(self):
        return os.path.basename(self.path)


    @property
    def path(self):
        return self.source_path


    @property
    def icon_path(self):
        if self.is_dir:
            return os.path.join(self.source_path, '__icon__.png')
        else:
            return f"{os.path.splitext(self.source_path)[0]}.icon.png"


    @property
    def blend_path(self):
        return self.entries[0].blend_path


class Items(typing.Dict[str, typing.Any], dict):
    dir_path: str = None
    template: Item = None

    @property
    def name(self):
        if self.dir_path:
            return os.path.basename(self.dir_path)[:-9]
        else:
            return None

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.re_compile()

    def __hash__(self):
        return id(self)

    def load_items(self, dir_path: str, template: Item = None):
        self.dir_path = dir_path
        self.template = template

        for file in os.scandir(dir_path):
            if not file.is_dir():
                continue

            json_path = os.path.join(file.path, '__item__.json')
            if not os.path.exists(json_path):
                with open(json_path, 'w', encoding='utf-8') as item_json:
                    json.dump({}, item_json)

            try:
                item = Item.from_json(json_path)

                if template != None:
                    item.template = template

                self[file.path] = item
            except:
                print('-' * 50)
                utils.print_error(f'Cannot read item: {json_path}')
                import traceback
                traceback.print_exc()
                print('-' * 50)
                continue

    def load_template(self, dir_path: str):
        json_path = os.path.join(dir_path, '__template__.json')
        if not os.path.exists(json_path):
            return None

        try:
            item = Item.from_json(json_path)
            self[dir_path] = item
            return item
        except:
            print('-' * 50)
            utils.print_error(f'Cannot read template: {json_path}')
            import traceback
            traceback.print_exc()
            print('-' * 50)
            return None

    def re_compile(self):
        self.re_sort = re.compile(r"(?:sort|s):([a-z_]+)(:rev)?", flags=re.IGNORECASE)
        self.re_compare = re.compile(r"([a-z_]+):([><=!]*)(\d+)", flags=re.IGNORECASE)
        self.re_query_fragment = re.compile(r'\S+".+?"|\S+', flags=re.IGNORECASE)

        self.re_item_search = re.compile(r'(?P<is_whole>w)?(?P<type>key|k|value|v):(?:"(?P<quoted>.+?)"|(?P<not_quoted>\S+))', flags=re.IGNORECASE)

    def get_result(self, query: str = None, sort: bool = True, is_partial = True):

        items = list(self.values()) # type: typing.List[Item]
        if not items:
            return []

        if not query:
            return items

        query = self.re_query_fragment.findall(query.strip()) # type: typing.List[str]
        exclude = []
        include = []
        is_intersection = False

        for fragment in query:

            if fragment == '-':
                continue

            match = self.re_compare.match(fragment)
            if match:
                attr = validate_attr(match.group(1))
                if not attr:
                    continue

                sign = match.group(2)
                if sign == '>':
                    f = operator.gt
                elif sign == '>=':
                    f = operator.ge
                elif sign == '<':
                    f = operator.lt
                elif sign == '<=':
                    f = operator.le
                elif sign in ('=', '==', ''):
                    f = operator.eq
                elif sign == '!=':
                    f = operator.ne
                else:
                    continue

                value = int(match.group(3))

                items = [item for item in items if f(getattr(item, attr), value)]
                continue

            match = self.re_sort.match(fragment)
            if match:
                if not sort:
                    continue

                sort_by = match.group(1)
                do_reverse = not bool(match.group(2))

                sort_by = validate_attr(sort_by)
                if not sort_by:
                    continue

                if sort_by in STRING_TYPE_ATTRS:
                    items.sort(key = lambda x: getattr(x, sort_by).lower(), reverse = do_reverse)
                else:
                    items.sort(key=operator.attrgetter(sort_by), reverse = do_reverse)

                continue

            match = self.re_item_search.match(fragment)
            if match:
                do_match_whole = bool(match.group('is_whole'))
                mode = 'eq' if do_match_whole else 'contains'

                key = match.group('quoted') or match.group('not_quoted')

                is_dict_key = match.group('type') in ('key', 'k')

                def has_key(item: Item):
                    return any(utils.locate_item(item, key, is_dict_key = is_dict_key, mode = mode))

                items = [item for item in items if has_key(item)]
                continue

            if fragment.lower() == ':w':
                is_partial = False
                continue

            if fragment.lower() == ':i':
                is_intersection = True
                continue

            if fragment.startswith('-'):
                exclude.append(fragment[1:].lower())
                continue

            include.append(fragment.lower())

        exclude = set(exclude)
        include = set(include)

        if is_partial:
            if is_intersection:
                result = [item for item in items if any(fragment in item.search_string for fragment in include) and not any(fragment in item.search_string for fragment in exclude)]
                if sort:
                    result.sort(key=lambda item: len(fragment in item.search_string for fragment in include), reverse = True)
            else:
                result = [item for item in items if all(fragment in item.search_string for fragment in include) and not any(fragment in item.search_string for fragment in exclude)]
        else:
            if is_intersection:
                result = [item for item in items if not include.isdisjoint(item.search_set) and exclude.isdisjoint(item.search_set)]
                if sort:
                    result.sort(key=lambda item: len(item.search_set.intersection(include)), reverse = True)
            else:
                result = [item for item in items if include.issubset(item.search_set) and exclude.isdisjoint(item.search_set)]

        return result


    def load(self, data: typing.Dict[str, typing.List[updater.Program_Entry]]):

        for source_file, entires in data.items():

            is_dir = os.path.isdir(source_file)

            if is_dir:
                json_path = os.path.join(source_file, '__info__.json')
            else:
                json_path = f"{os.path.splitext(source_file)[0]}.info.json"

            if not os.path.exists(json_path):
                with open(json_path, 'w', encoding='utf-8') as item_json:
                    json.dump({}, item_json)

            try:
                item = Item.from_json(json_path)
                item.is_dir = is_dir
                item.entries = entires.copy()
                item.source_path = source_file
                self[source_file] = item

            except:
                print(f'Cannot read item: {json_path}')
                import traceback
                traceback.print_exc()
                continue


class Entry_Panel(scrolled.ScrolledPanel):

    parent: Item_Panel


    @property
    def item(self):
        return self.parent.item


    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)

        self.parent = parent
        self.SetFont(self.GetTopLevelParent().GetFont())

        self.main_sizer = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(self.main_sizer)

        self.SetupScrolling(scroll_x = False)


    def clear(self):
        self.Freeze()

        for sizer_item in self.main_sizer.GetChildren():
            window = sizer_item.GetWindow() # type: wx.Window
            window.Show(False)

        self.main_sizer.Clear(delete_windows = False)

        self.Thaw()


    def update(self, hard_update = False):
        item = self.item

        return

        self.Freeze()

        for sizer_item in self.main_sizer.GetChildren():
            window = sizer_item.GetWindow() # type: wx.Window
            # window.save()
            window.Show(False)

        if hard_update:
            get_editor.cache_clear()
        self.main_sizer.Clear(delete_windows = hard_update)

        for index, entry in item.iter_entry():
            entry_editor = get_editor(entry['type'], self, index, item)
            entry_editor.Show(True)
            self.main_sizer.Add(entry_editor, 0, wx.EXPAND|wx.ALL, border = 3)

        self.update_sizer()
        wx.CallAfter(self.Thaw)


    def update_sizer(self):
        self.main_sizer.Fit(self)
        wx.PostEvent( self.GetParent(), wx.SizeEvent(wx.Size()) )


    def save(self):
        self.item.save()


class Base_Editor(wx.Panel):

    later_caller: wx.CallLater = None
    entry_data_index: int
    data: typing.Any # data ctrl
    item: data.Item
    id_name: str = None

    @property
    def parent(self) -> Entry_Panel:
        return self.GetParent()

    @property
    def entry(self):
        return self.item.get_entry(self.entry_data_index)

    @property
    def entry_data(self):
        return self.entry.get('data', SENTINEL)

    def __init__(self, parent: wx.Window, entry_data_index: int, item: data.Item, **kwargs) -> None:
        super().__init__(parent, style = wx.TAB_TRAVERSAL|wx.BORDER_THEME, **kwargs)
        self.entry_data_index = entry_data_index
        self.item = item

        self.main_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.SetSizer(self.main_sizer)

        self.label = wx.StaticText(self, label = self.entry.get('name', 'NO NAME'), size = wx.Size(150, -1))
        self.main_sizer.Add(self.label, 0, wx.ALIGN_CENTRE_VERTICAL, border = 2)

        label = '📝' if self.item.is_template_entry(entry_data_index) else '✨'
        self.entry_icon = wx.StaticText(self, label = label)
        self.main_sizer.Add(self.entry_icon, 0, wx.ALIGN_CENTRE_VERTICAL)

        self.label.Bind(wx.EVT_LEFT_UP, self.on_label_left_click)
        self.label.Bind(wx.EVT_RIGHT_UP, self.on_icon_right_click)

    def on_label_left_click(self, event):
        wxp_utils.set_clipboard_text(self.label.GetLabel())

    def on_icon_right_click(self, event):

        menu = wx.Menu()

        is_template_item = self.item.is_template_entry(self.entry_data_index)

        menu_item = wx.MenuItem(menu, wx.Window.NewControlId(), 'Rename')
        menu.Append(menu_item)
        menu.Bind(wx.EVT_MENU, self.on_rename_item, menu_item)
        if is_template_item:
            menu_item.Enable(False)
            menu_item.SetItemLabel(f"{menu_item.GetItemLabel()} — Template entry")

        menu_item = wx.MenuItem(menu, wx.Window.NewControlId(), 'Move Up')
        menu.Append(menu_item)
        menu.Bind(wx.EVT_MENU, self.on_move_up, menu_item)
        if is_template_item:
            menu_item.Enable(False)
            menu_item.SetItemLabel(f"{menu_item.GetItemLabel()} — Template entry")

        menu_item = wx.MenuItem(menu, wx.Window.NewControlId(), 'Move Down')
        menu.Append(menu_item)
        menu.Bind(wx.EVT_MENU, self.on_move_down, menu_item)
        if is_template_item:
            menu_item.Enable(False)
            menu_item.SetItemLabel(f"{menu_item.GetItemLabel()} — Template entry")

        menu.AppendSeparator()

        menu_item = wx.MenuItem(menu, wx.Window.NewControlId(), 'Delete')
        menu.Append(menu_item)
        menu.Bind(wx.EVT_MENU, self.on_delete, menu_item)
        if is_template_item:
            menu_item.Enable(False)
            menu_item.SetItemLabel(f"{menu_item.GetItemLabel()} — Template entry")

        self.PopupMenu(menu)
        menu.Destroy()

    def on_delete(self, event):
        if self.item.is_template_entry(self.entry_data_index):
            return

        content = "\n".join(f"{key}: {str(value)[:1000]}" for key, value in self.entry.items())
        text = f"Do you want to permanently delete this entry?\n\n{content}"
        with wx.MessageDialog(None, text, f"Deleting Entry — {self.entry_data_index}: {self.entry.get('name', 'NO NAME')}", wx.OK | wx.CANCEL | wx.CANCEL_DEFAULT | wx.ICON_WARNING) as dialog:
            result = dialog.ShowModal()

            if result != wx.ID_OK:
                return

        self.item.data.remove(self.entry)

        self.item.save()
        self.parent.update(True)

    def on_move_up(self, event):
        if self.item.is_template_entry(self.entry_data_index):
            return

        index = self.item.data.index(self.entry)
        if index == 0:
            return

        index_above = index - 1

        self.item.data[index_above], self.item.data[index] = self.item.data[index], self.item.data[index_above]

        self.item.save()
        self.parent.update(True)


    def on_move_down(self, event):
        if self.item.is_template_entry(self.entry_data_index):
            return

        index = self.item.data.index(self.entry)
        if index == len(self.item.data) - 1:
            return

        index_below = index + 1

        self.item.data[index_below], self.item.data[index] = self.item.data[index], self.item.data[index_below]

        self.item.save()
        self.parent.update(True)

    def on_rename_item(self, event):
        if self.item.is_template_entry(self.entry_data_index):
            return

        data = wxp_utils.get_input(self, {'name': self.label.GetLabel()}, title='Rename Entry')
        if not data:
            return

        name = data['name']
        self.label.SetLabel(name)

        self.item.set_entry_value(self.entry_data_index, 'name', name)
        self.item.save()

    def init_data(self):
        init_data = self.entry_data
        if init_data != SENTINEL:
            self.data = init_data

    def auto_save(self, event: wx.Event):
        event.Skip()
        if self.later_caller:
            self.later_caller.Start(2000, data = self.data)
        else:
            self.later_caller = wx.CallLater(2000, self.save, data = self.data)

    def save(self, event: wx.Event = None, data: typing.Any = SENTINEL):
        if event and event.EventType != wx.EVT_TEXT_ENTER.typeId:
            event.Skip()

        if data == SENTINEL:
            data = self.data

        if self.entry_data == data:
            return

        self.item.set_entry_data(self.entry_data_index, data)
        self.item.save()

    def __del__(self):
        if self.later_caller:
            self.later_caller.Stop()


class URL_Editor(Base_Editor):
    parent: Entry_Panel
    id_name = 'url'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.ctrl = wx.adv.HyperlinkCtrl(self)
        self.main_sizer.Add(self.ctrl, 1, wx.EXPAND|wx.ALL, border = 4)

        self.ctrl.Bind(wx.adv.EVT_HYPERLINK, self.on_url_click)

        self.ctrl.Bind(wx.EVT_RIGHT_UP, self.on_right_click)
        self.Bind(wx.EVT_RIGHT_UP, self.on_right_click)

        self.init_data()

    @property
    def data(self) -> str:
        return {
            'name': self.ctrl.GetLabel(),
            'url': self.ctrl.GetURL(),
        }

    @data.setter
    def data(self, data: dict):
        self.ctrl.SetLabel(data.get('name', ''))
        self.ctrl.SetURL(data.get('url', ''))

    def on_url_click(self, event: wx.adv.HyperlinkEvent):
        event.Skip()

    def on_right_click(self, event):
        menu = wx.Menu()

        menu_item = wx.MenuItem(menu, wx.Window.NewControlId(), 'Edit')
        menu.Append(menu_item)
        menu.Bind(wx.EVT_MENU, self.on_edit, menu_item)

        menu_item = wx.MenuItem(menu, wx.Window.NewControlId(), 'From Clipboard')
        menu.Append(menu_item)
        menu.Bind(wx.EVT_MENU, self.on_paste_from_clipboard, menu_item)

        menu.AppendSeparator()

        menu_item = wx.MenuItem(menu, wx.Window.NewControlId(), 'Copy Title And URL')
        menu.Append(menu_item)
        menu.Bind(wx.EVT_MENU, self.on_copy_name_url, menu_item)

        menu_item = wx.MenuItem(menu, wx.Window.NewControlId(), 'Copy URL')
        menu.Append(menu_item)
        menu.Bind(wx.EVT_MENU, self.on_copy_url, menu_item)

        self.PopupMenu(menu)
        menu.Destroy()

    def on_copy_name_url(self, event):
        wxp_utils.set_clipboard_text(self.ctrl.GetLabel() + '\n' +  self.ctrl.GetURL())

    def on_copy_url(self, event):
        wxp_utils.set_clipboard_text(self.ctrl.GetURL())

    def on_edit(self, event):
        self.show_edit(self.data)

    def on_paste_from_clipboard(self, event):
        text = wxp_utils.get_clipboard_text()
        if not text:
            return

        urls = utils.urls_from_flat_list(text)
        if not urls:
            return

        url = urls[0]

        self.show_edit({
            'name': url['name'],
            'url': url['path'],
        })

    def show_edit(self, data):

        data = wxp_utils.get_input(self, data, title = f"Edit URL: {self.label.GetLabel()}")
        if not data:
            return

        self.data = data
        self.save()
        self.parent.update_sizer()


def get_short_url(url: str):
    if not url.startswith(("https://", "http://")):
        url = "https://" + url

    path = urlparse(url)._replace(scheme="").geturl()[2:]

    if path.startswith('www.'):
        path = path[4:]

    return path


class URL_List_Clipboard_Import(wxp_utils.Item_Viewer_Native):
    parent: URL_Import_From_Text_Dialog

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.parent = self.GetParent()

        columns = (
            ('name', 700),
            ('path', 700),
        )

        self.set_columns(columns)
        self.setResizeColumn(2)

    def set_data(self, data: typing.List[dict]):
        self.data = data
        self.SetItemCount(len(data))

    def OnGetItemText(self, item: int, col: int):
        if col == 0:
            return self.data[item].get('name', '')
        elif col == 1:
            return get_short_url(self.data[item].get('path', ''))

    def OnGetItemToolTip(self, item: int, col: int):
        return self.OnGetItemText(item, col)


def urls_from_flat_list(text: str):
    lines = [line for line in text.splitlines() if line]

    data: typing.List[dict] = []
    time = sys_time.time()
    for name, path in zip(*(iter(lines),) * 2):

        unquote_path = unquote(path, encoding='utf-8', errors='replace')
        url = {
            'name': name,
            'path': unquote_path,
            'ctime': time,
            'mtime': time
        }
        if unquote_path != path:
            url['original_path'] = path

        data.append(url)

    return data


class URL_Import_From_Text_Dialog(wxp_utils.Generic_Selector_Dialog):
    parent: URL_List

    def __init__(self, parent, text: str, **kwargs):
        data = {
            'comment': '',
            'ignore_duplicates': True
        }
        super().__init__(parent, data, **kwargs)

        self.urls = urls_from_flat_list(text)
        self.list.set_data(self.urls)

        existing_urls = self.parent.get_results()
        self.existing_url_path = {url.get('path', '') for url in existing_urls}
        number_of_duplicates = sum(url.get('path', '') in self.existing_url_path for url in self.urls)
        self.info_label.SetLabel(f"All: {len(self.urls)}, Duplicates: {number_of_duplicates}, Not Duplicates: {len(self.urls) - number_of_duplicates}")

        sizer_item: wx.SizerItem = self.main_sizer.GetItem(self.entry_sizer)
        sizer_item.SetProportion(0)

        self.SetMaxSize((-1, -1))
        self.SetSize(1400, 600)
        self.CenterOnScreen()

    def pre_entries_init(self):
        self.info_label = wx.StaticText(self)
        self.main_sizer.Add(self.info_label, 0, wx.EXPAND | wx.ALL, border = 5)

        self.list = URL_List_Clipboard_Import(self)
        self.main_sizer.Add(self.list, 1, wx.EXPAND | wx.ALL, border = 5)

    def import_urls(self, original_file: str = None):
        data = self.get_data()
        comment = data['comment']

        if original_file:
            stat = os.stat(original_file)
            ctime = stat.st_ctime
            mtime = stat.st_mtime

        current_time = sys_time.time()

        final_urls = []
        for url in self.urls:

            if url.get('path', '') in self.existing_url_path:
                continue

            if original_file:
                url['ctime'] = ctime
                url['mtime'] = mtime

            if comment:
                url['comment'] = comment
                url['mtime'] = current_time

            final_urls.append(url)

        if final_urls:
            self.parent.parent._data.extend(final_urls)
            self.parent.parent.save()


class URL_List(wx.ListCtrl):
    # parent: URLs_Editor

    def __init__(self, *args, **kwargs):
        super().__init__(*args, style = wx.LC_REPORT|wx.LC_HRULES|wx.LC_VRULES|wx.LC_VIRTUAL, **kwargs)

        self.parent = self.GetParent()

        columns = (
            ('name', 300),
            ('url', 200),
            ('comment', 200),
            ('is_read', 62),
            ('ctime', 200),
            ('mtime', 200),
        )

        self.set_columns(columns)

        self.data = []
        self.selected_url: dict = None

        self.re_query_fragment = re.compile(r'\S+".+?"|".+?"|\S+', flags=re.IGNORECASE)

        self.Bind(wx.EVT_KEY_DOWN, self.on_key)

        self.SetMinSize(wx.Size(1,-1))

        self.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_item_selected)
        self.Bind(wx.EVT_LEFT_DCLICK, self._on_left_double_click)
        self.Bind(wx.EVT_LIST_ITEM_RIGHT_CLICK, self.on_right_click)

    def set_columns(self, columns):
        for i, (column, width) in enumerate(columns):
            self.InsertColumn(i, column)
            self.SetColumnWidth(i, width)

    def _on_left_double_click(self, event: wx.MouseEvent):
        item, flags = self.HitTest(event.GetPosition())
        if flags & wx.LIST_HITTEST_ONITEM:
            self.on_left_double_click(item, event)

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

    def on_key(self, event: wx.KeyEvent):
        event.Skip()

        if not event.ControlDown():
            return

        key_code = event.GetKeyCode()

        if key_code == ord('C'):
            self.on_copy_to_clipboard()
        elif key_code == ord('V'):
            self.on_add_from_clipboard()

    def set_data(self, data: typing.List[dict]):

        self.data = data
        self.SetItemCount(len(data))
        self.deselect_all()

        try:
            index = data.index(self.selected_url)
            self.Select(index)
            self.Focus(index)
        except:
            pass

    def OnGetItemText(self, item: int, col: int):
        if col == 0:
            return self.data[item].get('name', '')
        elif col == 1:
            return get_short_url(self.data[item].get('path', ''))
        elif col == 2:
            return self.data[item].get('comment', '')
        elif col == 3:
            return str(self.data[item].get('is_read', False))
        elif col == 4:
            return utils.get_time_str_from(self.data[item].get('ctime', 0))[2:]
        elif col == 5:
            return utils.get_time_str_from(self.data[item].get('mtime', 0))[2:]

    def OnGetItemToolTip(self, item: int, col: int):
        return self.OnGetItemText(item, col)

    def OnGetItemCheck(self, item: int):
        return self.data[item].get('is_read', False)

    def on_item_selected(self, event: wx.ListEvent):
        index = event.GetIndex()
        url = self.data[index]
        self.selected_url = url
        event.Skip()

    def on_left_double_click(self, index: int, event: wx.MouseEvent):
        url = self.data[index]
        webbrowser.open(url['path'], new = 2, autoraise=True)

    def on_right_click(self, event: wx.ListEvent):
        index = event.GetIndex()
        url = self.data[index]
        self.Select(index)

        menu = wx.Menu()

        def add_action(name: str, func: typing.Callable):
            menu_item = wx.MenuItem(menu, wx.Window.NewControlId(), name)
            menu.Append(menu_item)
            menu.Bind(wx.EVT_MENU, func, menu_item)
            return menu_item

        def get_func(func: typing.Callable, *args, **kwargs):
            def wrapper(event: wx.CommandEvent):
                func(*args, **kwargs)
            return wrapper

        add_action('Open', get_func(webbrowser.open, url['path'], new = 2, autoraise=True))
        add_action('Comment', get_func(self.on_url_comment, url, index))
        add_action('Uncheck' if url.get('is_read', False) else 'Check', get_func(self.on_item_check, url, index))
        add_action('Edit', get_func(self.on_url_edit, url, index))
        add_action('Delete', get_func(self.on_delete, url, index))

        menu.AppendSeparator()

        add_action('Copy To Clipboard', get_func(self.on_copy_to_clipboard))
        add_action('Add From Clipboard', get_func(self.on_add_from_clipboard))
        add_action('Add From File', get_func(self.on_add_from_file))

        self.PopupMenu(menu)
        menu.Destroy()

    def on_copy_to_clipboard(self):

        text = []
        for index in self.get_selected_indexes():
            url = self.data[index]

            text.append(url.get('name', ''))
            text.append(url.get('path', ''))
            text.append('')

        if text:
            wxp_utils.set_clipboard_text('\n'.join(text))

    def on_add_from_clipboard(self):

        text = wxp_utils.get_clipboard_text()

        with URL_Import_From_Text_Dialog(self, text = text, pos = wxp_utils.get_click_position(self, 640, 440), font = self.GetTopLevelParent().GetFont()) as dialog:
            result = dialog.ShowModal()

            if result != wx.ID_OK:
                return

            dialog.import_urls()

        self.parent.search.on_search()

    def on_add_from_file(self):

        dlg = wx.FileDialog(self, defaultDir = os.getcwd(), wildcard = "All Files|*", style = wx.FD_OPEN | wx.FD_CHANGE_DIR)
        result = dlg.ShowModal()
        if result != wx.ID_OK:
            return

        path = dlg.GetPath()
        dlg.Destroy()

        with open(path, 'r', encoding = 'utf-8') as file:
            text = file.read()

        with URL_Import_From_Text_Dialog(self, text = text, pos = wxp_utils.get_click_position(self), font = self.GetTopLevelParent().GetFont()) as dialog:
            result = dialog.ShowModal()

            if result != wx.ID_OK:
                return

            dialog.import_urls(path)

        self.parent.search.on_search()

    def on_item_check(self, url: dict, index: int):
        url['is_read'] = not url.get('is_read', False)
        url['mtime'] = sys_time.time()

        self.RefreshItem(index)

        self.parent.save()

        self.parent.search.on_search()

    def on_url_comment(self, url: dict, index: int):

        data = {
            'comment': url.get('comment', ''),
        }

        data = wxp_utils.get_input(self.parent, data, "URL Comment")
        if not data:
            return

        url.update(data)
        url['mtime'] = sys_time.time()

        self.RefreshItem(index)

        self.parent.save()

        self.parent.search.on_search()

    def on_url_edit(self, url: dict, index: int):

        data = {
            'name': url.get('name', ''),
            'path': url.get('path', ''),
            'comment': url.get('comment', ''),
            'is_read': url.get('is_read', False),
        }

        data = wxp_utils.get_input(self.parent, data, "URL Edit")
        if not data:
            return

        url.update(data)
        url['mtime'] = sys_time.time()

        self.RefreshItem(index)

        self.parent.save()

        self.parent.search.on_search()

    def on_delete(self, url: dict, index: int):
        name = url.get('name', '')

        text = f"Do you want to permanently delete this url?\n\
            Name: {name}\n\
            Url: {url.get('path', '')}"

        with wx.MessageDialog(None, text, f'Deleting URL — {name}', wx.OK | wx.CANCEL | wx.CANCEL_DEFAULT | wx.ICON_WARNING) as dialog:
            result = dialog.ShowModal()

            if result != wx.ID_OK:
                return

        self.parent._data.remove(url)

        self.parent.save()

        self.parent.search.on_search()

    def get_results(self, query: str = None):
        urls = self.parent._data

        if not query:
            return urls

        query = self.re_query_fragment.findall(query.lower().strip()) # type: typing.List[str]
        exclude = []
        include = []

        def get_search_string(url: dict):
            return ' '.join(filter(None, map(url.get, ('name', 'path', 'comment')))).lower()

        for fragment in query:

            if fragment == '-':
                continue

            if fragment == ':no_comment':
                urls = [url for url in urls if not url.get('comment')]
                continue

            if fragment == ':comment':
                urls = [url for url in urls if url.get('comment')]
                continue

            if fragment in ('s:ctime', 'sort:ctime'):
                urls.sort(key = lambda url: url.get('ctime', 0))
                continue

            if fragment == ('s:mtime', 'sort:mtime'):
                urls.sort(key = lambda url: url.get('mtime', 0))
                continue

            if fragment == ('s:is_read', 'sort:is_read'):
                urls.sort(key = lambda url: url.get('is_read', 0))
                continue

            if len(fragment) >= 3 and fragment[0] == '"' and fragment[-1] == '"':
                string = fragment[1:-1]
                urls = [url for url in urls if string in get_search_string(url)]
                continue

            if fragment.startswith('-'):
                exclude.append(fragment[1:])
                continue

            include.append(fragment)

        if exclude or include:
            def func(url):
                search_string = get_search_string(url)

                if any(fragment in search_string for fragment in exclude):
                    return False

                if not include or all(fragment in search_string for fragment in include):
                    return True

                return False

            urls = list(filter(func, urls))

        return urls


class Item_Panel(wx.Panel):


    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)

        sizer = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(sizer)

        head_sizer = wx.BoxSizer(wx.HORIZONTAL)
        sizer.Add(head_sizer, 0, wx.EXPAND)

        self.icon = wx.StaticBitmap(self)
        head_sizer.Add(self.icon, 0, wx.EXPAND)
        self.icon.Bind(wx.EVT_LEFT_UP, self.on_icon_click)
        self.icon.Bind(wx.EVT_RIGHT_UP, self.on_icon_menu)
        self.icon.SetMinSize((128, 128))

        head_item_sizer = wx.BoxSizer(wx.VERTICAL)
        head_sizer.Add(head_item_sizer, 1, wx.EXPAND)

        self.name = wx.StaticText(self)
        head_item_sizer.Add(self.name, 0, wx.EXPAND)

        self.template = wx.StaticText(self)
        head_item_sizer.Add(self.template, 0, wx.EXPAND)

        self.date = wx.StaticText(self)
        head_item_sizer.Add(self.date, 0, wx.EXPAND)

        self.saving_later_caller: wx.CallLater = None

        self.comment = wx.TextCtrl(self, style = wx.TE_PROCESS_ENTER)
        head_item_sizer.Add(self.comment, 0, wx.EXPAND)
        self.comment.Bind(wx.EVT_KILL_FOCUS, self.save_comment)
        self.comment.Bind(wx.EVT_TEXT_ENTER, self.save_comment)
        self.comment.Bind(wx.EVT_TEXT, self.save_comment_delayed)


        self.entry_panel = Entry_Panel(self)
        sizer.Add(self.entry_panel, 4, wx.EXPAND)


        self.search = wxp_utils.Search_Bar(self)
        sizer.Add(self.search, 0, wx.EXPAND)
        self.search.execute_search = self.execute_search
        self.search.presets_ComboBox.Hide()

        # urls
        self._data = []

        self.urls = URL_List(self)
        sizer.Add(self.urls, 3, wx.EXPAND)

        self.item_history = []
        self.use_history = True
        self.item: Item = None


    def execute_search(self, query: str):
        data = self.urls.get_results(query)
        self.urls.set_data(data)
        self.Refresh()


    def save(self):
        if self.item:
            self.item.save()


    def save_comment(self, event: wx.Event = None, data: str = SENTINEL):
        if event:
            event.Skip()

        item = self.item
        if not item:
            return

        if data == SENTINEL:
            new_comment = self.comment.GetValue().strip()
        else:
            new_comment = data

        old_comment = self.item.get('comment', '')

        if new_comment == old_comment:
            return

        self.item['comment'] = new_comment
        self.item.save()


    def save_comment_delayed(self, event: wx.Event):
        event.Skip()
        if self.saving_later_caller:
            self.saving_later_caller.Start(2000, data = self.comment.GetValue().strip())
        else:
            self.saving_later_caller = wx.CallLater(2000, self.save_comment, data = self.comment.GetValue().strip())


    def clear(self):
        self.item = None
        self.name.SetLabel('')
        self.template.SetLabel('')
        self.icon.SetBitmap(wx.NullBitmap)
        # self.entry_panel.clear()


    def set_data(self, item: Item):
        self.item = item

        self.date.SetLabel(f"{datetime.fromtimestamp(self.item.get('ctime', 0))}")

        self.comment.SetValue(self.item.get('comment', ''))

        urls = self.item.get('urls')
        if not urls:
            self.item['urls'] = urls = []
        self._data = urls
        self.search.on_search()

        self.name.SetLabel(item.name)

        if os.path.exists(item.icon_path):
            self.icon.SetBitmap(BITMAPS.get_bitmap(item.icon_path, 128))
        else:
            self.icon.SetBitmap(wx.NullBitmap)

        # self.entry_panel.update()

        if self.use_history:
            self.item_history.append(item)
            self.item_history = list(reversed(utils.deduplicate(reversed(self.item_history))))


    def on_icon_menu(self, event: wx.ContextMenuEvent):

        menu = wx.Menu()

        def get_starter(target_func):
            def starter(event):
                threading.Thread(target = target_func, args=()).start()
            return starter

        menu_item = wx.MenuItem(menu, wx.Window.NewControlId(), 'Set Icon From Clipboard')
        menu.Append(menu_item)
        menu.Bind(wx.EVT_MENU, self.make_icon_from_clipboard, menu_item)
        if not wxp_utils.is_image_in_clipboard():
            menu_item.Enable(False)
            menu_item.SetItemLabel('Set Icon From Clipboard — No clipboard image')

        self.PopupMenu(menu)
        menu.Destroy()


    def on_icon_click(self, event):
        icon_path = self.entry_panel.item.icon_path
        if not os.path.exists(icon_path):
            return

        threading.Thread(target = utils.os_open, args = (icon_path, )).start()


    def make_icon_from_clipboard(self, event: wx.CommandEvent = None):

        item = self.entry_panel.item
        if not item:
            wxp_utils.show_info(self.icon, 'Bitmap From Clipboard', 'Select an item.')
            return

        bitmap = wxp_utils.get_bitmap_from_clipboard()
        if not bitmap:
            wxp_utils.show_warning(self.icon, 'Bitmap From Clipboard', 'No image in the clipboard.')
            return


        if os.path.exists(item.icon_path):
            path, ext = os.path.splitext(item.icon_path)
            os.rename(item.icon_path, path + str(sys_time.time()) + ext)

        bitmap.SaveFile(item.icon_path, wx.BITMAP_TYPE_PNG)
        self.icon.SetBitmap(BITMAPS.get_bitmap(item.icon_path, 128, reload=True))


class Item_List_Context_Menu(wxp_utils.Context_Menu):

    parent: Item_List
    event: wx.ContextMenuEvent


    def __init__(self, parent, event, item: Item):

        super().__init__(parent, event)

        self.item = item

        self.append_item("Copy Name", self.on_copy_name)
        self.append_item("Show Blend", self.on_show_blend)
        self.append_item("Open Blend Compatible", self.on_open_blend)


    def on_copy_name(self, event: wx.CommandEvent):
        pyperclip.copy(self.item.basename)


    def on_show_blend(self, event: wx.CommandEvent):
        utils.os_show(self.item.blend_path)


    def on_open_blend(self, event: wx.CommandEvent):

        from blender_asset_tracer import blendfile

        if not 'atool' in sys.modules:
            utils.import_module_from_file(r'D:\source\software\blender\scripts\addons\atool\__init__.py')

        from atool.test import conftest

        blend_path = self.item.blend_path

        bf = blendfile.open_cached(pathlib.Path(blend_path))

        blend_file_version = str(bf.header.version)

        assert len(blend_file_version) == 3

        blend_major = int(blend_file_version[:1])
        blend_minor = int(blend_file_version[1:])

        for blender_path, version_string in conftest.get_blender_paths().items():

            major, minor, micro = map(int, version_string.split(maxsplit=1)[0].split('.'))

            if major < blend_major:
                continue
            elif major == blend_major:
                if minor < blend_minor:
                    continue

            command = ["--python-expr", f"import bpy; bpy.ops.wm.read_homefile(filepath = r'{blend_path}')"]

            return utils.open_blender_detached(blender_path, *command)

        raise Exception(f"Could not find a suitable Blender version for a blend with version: {blend_major}.{blend_minor}")



class Item_List(wxp_utils.Item_Viewer_Native):

    data: typing.List[data.Item]

    parent: 'Item_List_Panel'

    def __init__(self, parent, **kwargs):
        super().__init__(parent, style = wx.LC_SINGLE_SEL|wx.LC_REPORT|wx.LC_HRULES|wx.LC_VRULES|wx.LC_VIRTUAL, **kwargs)

        self.parent = parent

        self.column = [
            ('name', 200),
            ('path', 200),
        ]

        self.set_columns(self.column)
        self.setResizeColumn(2)


    def set_data(self, data):

        self.data = data
        self.SetItemCount(len(data))
        self.Refresh()


    def OnGetItemText(self, row: int, col: int):
        item = self.data[row]

        if col == 0:
            return item.name
        elif col == 1:
            return item.path
        else:
            return str(col)


    def on_item_selected(self, event: wx.ListEvent):
        index = event.GetIndex()
        if index >= 0:
            self.parent.parent.item_panel.set_data(self.data[index])
        event.Skip()


    def on_left_double_click(self, index: int, event: wx.MouseEvent):
        item: Item = self.data[index]

        self.GetTopLevelParent().blender_server.ensure()
        self.GetTopLevelParent().blender_server.open_mainfile(item.blend_path)


    def on_right_click(self, event: wx.ListEvent):
        self.PopupMenu(Item_List_Context_Menu(self, event, self.data[event.GetIndex()]))



class Item_Search_Bar(wxp_utils.Search_Bar):

    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self.parent: Item_List_Panel = self.GetParent()

    def execute_search(self, query: str):
        self.parent.list.set_data(self.parent.parent.items.get_result(query))


class Item_List_Panel(wx.Panel):

    parent: Blend_Panel

    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)

        self.parent = self.GetTopLevelParent()

        self.SetFont(self.GetTopLevelParent().GetFont())

        sizer = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(sizer)

        self.collection_ComboBox = wx.ComboBox(self, style = wx.CB_READONLY)
        sizer.Add(self.collection_ComboBox, 0, wx.EXPAND)
        self.collection_ComboBox.Bind(wx.EVT_COMBOBOX, self.on_collection_selected)
        self.collection_ComboBox.Hide()
        # self.collection_ComboBox.Bind(wx.EVT_CONTEXT_MENU, self.on_collection_menu)

        self.search_bar = Item_Search_Bar(self)
        sizer.Add(self.search_bar, 0, wx.EXPAND)

        self.list = Item_List(self)
        sizer.Add(self.list, 1, wx.EXPAND)
        self.list.SetColumnWidth(0, 400)

    def update_collection_ComboBox(self):

        self.collection_ComboBox.Clear()
        for key, value in self.parent.collections.items():
            self.collection_ComboBox.Append(key, value)


    def on_collection_selected(self, event):
        index = self.collection_ComboBox.GetSelection()
        if index == wx.NOT_FOUND:
            return

        items: Items = self.collection_ComboBox.GetClientData(index)
        self.parent.items = items
        self.set_items(items)


    def set_items(self, items: Items):

        self.parent.items = items

        name = items.name
        if not name:
            name = '__TEMPLATES__'

        index = self.collection_ComboBox.FindString(name)
        self.collection_ComboBox.SetSelection(index)

        self.list.set_data(items.get_result())

        self.list.deselect_all()
        if self.list.data:
            self.list.Select(0)
        else:
            self.parent.item_panel.clear()



class Blend_Panel(wx.Panel):


    def __init__(self, parent: wx.Window):
        super().__init__(parent)

        sizer = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(sizer)

        splitter = wx.SplitterWindow(self, style=wx.CLIP_CHILDREN | wx.SP_LIVE_UPDATE | wx.SP_3D)
        sizer.Add(splitter, 1, wx.EXPAND)

        self.item_panel = Item_Panel(splitter)
        self.list_ctrl = Item_List_Panel(splitter)

        self.list_ctrl.parent = self

        self.collections: typing.Dict[str, Items] = {}

        splitter.SplitVertically(self.list_ctrl, self.item_panel, 660)
        splitter.SetMinimumPaneSize(5)


    def load_data(self, data: typing.Dict[str, typing.List[updater.Program_Entry]]):

        items = Items()
        items.load(data)

        self.collections['blends'] = items

        # self.list_ctrl.update_collection_ComboBox()
        self.list_ctrl.set_items(self.collections[list(self.collections)[0]])
