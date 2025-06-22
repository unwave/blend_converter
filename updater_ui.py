from __future__ import annotations

import os
import sys
import re
import typing
import json
import subprocess
import collections

import pyperclip
import wx
import wx.lib.newevent

from . import utils
from . import updater
from . import wx_blend
from . import wxp_utils
from . import blender_server


class Model_List(wxp_utils.Item_Viewer_Native):

    parent: Result_Panel


    def __init__(self, parent, columns: typing.Iterable[typing.Tuple[str, int, typing.Callable[[int], str]]]):
        """
        `columns`: list of tuples (name, width, function)
        """

        super().__init__(parent)

        self.parent = parent

        self.main_frame: Main_Frame = self.GetTopLevelParent()

        self.columns = [
            ('path', 800, self.get_column_path),
            ('ext', 100, self.get_column_result_type),
            ('poke_time', 200, self.get_column_poke_time),
            ('status', 200, self.get_column_status),
        ]

        self.columns.extend(columns)

        self.set_columns(self.columns)
        self.set_item_attrs()

        self.Bind(wx.EVT_KEY_DOWN, self.on_key)

        self.double_click_function: typing.Optional[typing.Callable[[updater.Model_Entry]]] = self.on_empty_double_click_function


    def set_columns(self, columns):
        for i, column in enumerate(columns):
            self.InsertColumn(i, column[0])
            self.SetColumnWidth(i, column[1])


    def on_empty_double_click_function(self, entry):
        pass


    def set_item_attrs(self):

        self.status_to_bg_color = dict(
            ok = wx.Colour(95, 212, 119),
            needs_update = wx.Colour(244, 241, 134),
            updating = wx.Colour(255, 179, 71),
            error = wx.Colour(255, 105, 97),
            does_not_exist = wx.Colour(211, 211, 211),
            waiting_for_dependency = wx.Colour(150, 217, 202),
        )

        for key, value in self.status_to_bg_color.items():
            item_attr = wx.ItemAttr()
            item_attr.SetBackgroundColour(value)
            self.status_to_bg_color[key] = item_attr


    def set_data(self, data):

        self.data: list[updater.Model_Entry] = data
        self.SetItemCount(len(data))
        self.Refresh()

        if not self.data:
            self.GetParent().Update()
            self.GetParent().Refresh()
            self.Update()
            self.Refresh()


    def OnGetItemText(self, row: int, col: int) -> str:
        return self.columns[col][2](self.data[row])


    def get_column_path(self, item: updater.Model_Entry):
        return item.blend_path

    def get_column_result_type(self, item: updater.Model_Entry):
        return item.model._file_extension

    def get_column_poke_time(self, item: updater.Model_Entry):
        return utils.get_time_str_from(item.poke_time)

    def get_column_status(self, item: updater.Model_Entry):
        return item.status




    def get_selected_items(self):
        return [self.data[index] for index in self.get_selected_indexes()]

    def OnGetItemToolTip(self, item: int, col: int):
        return 'OnGetItemToolTip'

    def OnGetItemAttr(self, row: int):
        entry = self.data[row]
        return self.status_to_bg_color.get(entry.status)

    def OnGetItemTextColour(self, item: int, col: int):
        return None


    def on_left_double_click(self, index: int, event: wx.MouseEvent):

        entry = self.data[index]

        mask = (event.ControlDown(), event.AltDown(), event.ShiftDown())

        # (ctrl, alt, shift)
        # alt - result
        # ctrl - source
        # shift - open

        if mask == (True, False, True):
            self.on_open_source(entry)
        elif mask == (True, False, False):
            self.on_show_source_in_explorer(entry)

        elif mask == (False, True, True):
            self.on_open_result(entry)
        elif mask == (False, True, False):
            if os.path.exists(entry.model.result_path):
                self.on_show_result_in_explorer(entry)
            elif os.path.exists(entry.model.result_dir):
                utils.os_open(entry.model.result_dir)
            else:
                wx.MessageBox(f"The result path does not exist yet:\n{entry.model.result_path}", 'File does not exist', style= wx.OK | wx.ICON_ERROR)

        elif mask == (True, True, True):
            self.on_compare_model(entry)

        elif mask == (True, True, False):
            utils.os_show([entry.model.blend_path, entry.model.result_path if os.path.exists(entry.model.result_path) else entry.model.result_dir])

        else:
            if self.double_click_function:
                self.double_click_function(entry)


    def on_right_click(self, event: wx.ListEvent):
        index: int = event.GetIndex()
        self.Select(index)

        menu = wxp_utils.Context_Menu(self, event)

        def get_func(func: typing.Callable, *args, **kwargs):
            def wrapper(event: wx.CommandEvent):
                func(*args, **kwargs)
            return wrapper

        entry = self.data[index]

        blend_path = entry.model.blend_path
        menu_item = menu.append_item(f"Show Blend", get_func(utils.os_show, blend_path))
        menu_item.Enable(os.path.exists(blend_path))

        menu_item = menu.append_item(f"Open Blend", get_func(self.on_open_source, entry))
        menu_item.Enable(os.path.exists(blend_path))

        menu.append_separator()

        menu_item = menu.append_item(f"Show Result", get_func(utils.os_show, entry.model.result_path))
        menu_item.Enable(os.path.exists(entry.model.result_path))

        menu_item = menu.append_item(f"Open Result", get_func(self.on_open_result, entry))
        menu_item.Enable(os.path.exists(entry.model.result_path))

        menu_item = menu.append_item(f"Show Result Dir", get_func(utils.os_open, entry.model.result_dir))
        menu_item.Enable(os.path.exists(entry.model.result_dir))

        menu.append_separator()

        output_file = entry.stdout_file
        menu_item = menu.append_item(f"Show Stdout file", get_func(utils.os_show, output_file))
        menu_item.Enable(os.path.exists(output_file))

        output_file = entry.stderr_file
        menu_item = menu.append_item(f"Show Stderr file", get_func(utils.os_show, output_file))
        menu_item.Enable(os.path.exists(output_file))

        menu_item = menu.append_item(f"Compare", get_func(self.on_compare_model, entry))
        menu_item.Enable(os.path.exists(blend_path) and os.path.exists(entry.model.result_path))

        menu.append_separator()

        menu_item = menu.append_item(f"Copy Command", get_func(self.on_copy_conversion_command, entry))
        menu_item = menu.append_item(f"Copy Folder Basename", get_func(self.on_copy_folder_basename, entry))
        menu_item = menu.append_item(f"Copy Blend Path", get_func(self.on_copy_blend_path, entry))

        menu.append_separator()

        menu_item = menu.append_item(f"Mark As Needing Update", get_func(self.on_make_update, entry))
        menu_item = menu.append_item(f"Poke", get_func(self.on_entry_poke, entry))

        menu.append_separator()

        menu_item = menu.append_item(f"Force Update", get_func(self.on_entry_force_update, entry))

        self.PopupMenu(menu)
        menu.Destroy()


    def on_item_selected(self, event: wx.ListEvent):
        entry = self.data[int(event.GetIndex())]

        self.parent.stdout_viewer.set_data(entry.stdout_lines)
        self.parent.stderr_viewer.set_data(entry.stderr_lines)
        # if os.path.exists(entry.stdout_file):
        #     self.parent.console_output.LoadFile(entry.stdout_file)
        #     self.parent.console_output.SetScrollPos(wx.VERTICAL, self.parent.console_output.GetScrollRange(wx.VERTICAL))
        #     self.parent.console_output.SetInsertionPoint(-1)
        # else:
        #     self.parent.console_output.Clear()

        self.parent.main_frame.Refresh()


    def on_entry_poke(self, entry: updater.Model_Entry):
        self.main_frame.updater.poke_entry(entry)


    def on_copy_conversion_command(self, entry: updater.Model_Entry):

        def get_module_and_name():
            for module in self.main_frame.updater.modules:
                for key, value in getattr(module, '__blends__').items():
                    if value is entry.model:
                        return module.__file__, key

        command = utils.get_command_from_list([
            sys.executable,
            utils.get_script_path('forced_update'),
            *get_module_and_name(),
        ])

        wxp_utils.set_clipboard_text(command)


    def on_show_source_in_explorer(self, entry: updater.Model_Entry):
        utils.os_show(entry.model.blend_path)

    def on_open_source(self, entry: updater.Model_Entry):
        self.GetTopLevelParent().blender_server.ensure()
        self.GetTopLevelParent().blender_server.open_mainfile(entry.model.blend_path)

    def on_show_result_in_explorer(self, entry: updater.Model_Entry):
        utils.os_show(entry.model.result_path)

    def on_open_result(self, entry: updater.Model_Entry):
        path = entry.model.result_path

        if not os.path.exists(path):
            with wx.MessageDialog(None, f"{path}", 'File does not exist.', wx.OK | wx.ICON_ERROR) as dialog:
                dialog.ShowModal()
            return

        if path.endswith('.bam'):
            panda_viewer_path = utils.get_script_path('panda3d_viewer')
            subprocess.Popen([sys.executable, panda_viewer_path, path])
        elif path.endswith('.blend'):
            cmd = [entry.model.blender_executable, path]
            utils.open_blender_detached(*cmd)
        else:
            utils.os_open(path)


    def on_show_item(self, item):
        self.deselect_all()
        index = self.data.index(item)
        self.Select(index)
        self.Focus(index)


    def on_key(self, event: wx.KeyEvent):
        event.Skip()

        if not event.ControlDown():
            return

        key_code = event.GetKeyCode()

        if key_code == ord('C'):
            pyperclip.copy('\n'.join((entry.blend_path for entry in self.get_selected_items())))
        elif key_code == ord('A'):
            prev_func = self.on_item_selected
            self.on_item_selected = lambda a, b: None
            for index in range(self.GetItemCount()):
                self.Select(index)
            self.on_item_selected = prev_func


    def on_compare_model(self, entry: updater.Model_Entry):

        args = {
            'blend_path': entry.model.blend_path,
            'result_path': entry.model.result_path
        }

        cmd = [entry.model.blender_executable, '--python', utils.get_script_path('start_compare'), '--', '-json_args', json.dumps(args)]

        utils.open_blender_detached(*cmd)


    def on_open_source(self, entry: updater.Model_Entry):

        cmd = [entry.model.blender_executable, entry.model.blend_path]

        utils.open_blender_detached(*cmd)


    def on_copy_folder_basename(self, entry: updater.Model_Entry):
        wxp_utils.set_clipboard_text("\n".join((os.path.basename(os.path.dirname(entry.blend_path)) for entry in self.get_selected_items())))


    def on_copy_blend_path(self, entry: updater.Model_Entry):
        wxp_utils.set_clipboard_text("\n".join((entry.blend_path for entry in self.get_selected_items())))


    def on_make_update(self, entry: updater.Model_Entry):
        entry.status = 'needs_update'


    def on_entry_force_update(self, entry: updater.Model_Entry):

        main_frame: Main_Frame = self.GetTopLevelParent()

        if not main_frame.updater.max_updating_entries_exceeded():
            entry.status = 'needs_update'
            entry.update(main_frame.updater.poke_waiting_for_dependency)


class Output_Lines(wxp_utils.Item_Viewer_Native):


    def __init__(self, parent, name: str, *args, **kwargs):

        self.data = []

        if not 'style' in kwargs:
            # kwargs['style'] = wx.LC_REPORT | wx.LC_HRULES | wx.LC_VRULES | wx.LC_VIRTUAL
            kwargs['style'] = wx.LC_REPORT | wx.LC_HRULES | wx.LC_VIRTUAL

        super().__init__(parent, *args, **kwargs)

        self.parent = self.GetParent()

        columns = (
            ('№', 50),
            (name, 1400),
        )

        self.set_columns(columns)

        self.Bind(wx.EVT_KEY_DOWN, self.on_key_down)


    def on_key_down(self, event: wx.Event):

        event.Skip()

        if not event.ControlDown():
            return

        key_code = event.GetKeyCode()

        if key_code == ord('C'):
            wxp_utils.set_clipboard_text('\n'.join(row[1].rstrip() for row in self.get_selected_items_text()))

        elif key_code == ord('A'):

            # this ensures that no side effects triggered
            prev_func = self.on_item_selected
            self.on_item_selected = lambda a, b: None

            for index in range(self.GetItemCount()):
                self.Select(index)

            self.on_item_selected = prev_func


    def set_data(self, data: typing.List[dict]):

        self.data = data

        self.SetItemCount(len(data))
        self.Focus(len(data) - 1)


    def update(self):

        if self.data:
            do_scroll = self.IsVisible(self.GetItemCount() - 1)
            self.SetItemCount(len(self.data))
            if do_scroll:
                self.Focus(self.GetItemCount() - 1)


    def OnGetItemText(self, row: int, col: int):
        if col == 0:
            return str(row + 1)
        elif col == 1:
            return self.data[row]
        else:
            return 'UNKNOWN'


class Result_Panel(wx.Panel):

    re_query_fragment = re.compile(r'\S+?".+?"|".+?"|\S+', flags=re.IGNORECASE)


    def __init__(self, parent):
        super().__init__(parent)

        self.main_frame: Main_Frame = self.GetTopLevelParent()

        self.sizer = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(self.sizer)

        self.search = wxp_utils.Search_Bar(self)

        self.search.execute_search = self.execute_search
        self.sizer.Add(self.search, 0, wx.EXPAND)

        self.model_list = Model_List(self, self.main_frame.user_columns)
        self.sizer.Add(self.model_list, 1, wx.EXPAND)

        # self.console_output = wx.TextCtrl(self, style = wx.TE_READONLY | wx.TE_MULTILINE)
        self.stdout_viewer = Output_Lines(self, 'stdout')
        self.main_frame.Bind(EVT_STDOUT_LINE_PRINTED, self.on_stdout_need_update)
        self.stdout_need_update = False
        self.sizer.Add(self.stdout_viewer, 1, wx.EXPAND)

        self.stderr_viewer = Output_Lines(self, 'stderr')
        self.main_frame.Bind(EVT_STDERR_LINE_PRINTED, self.on_stderr_need_update)
        self.stderr_need_update = False
        self.sizer.Add(self.stderr_viewer, 1, wx.EXPAND)

        self.search_column_tuple = tuple(f"{column[0]}:" for column in self.model_list.columns)
        self.search_column_dict = {column[0]: column[2] for column in self.model_list.columns}

        self.execute_search('')


        self.output_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.on_output_timer)
        self.output_timer.Start(1000)


    def on_output_timer(self, event):

        if self.stdout_need_update:
            self.stdout_viewer.update()
            self.stdout_need_update = False

        if self.stderr_need_update:
            self.stderr_viewer.update()
            self.stderr_need_update = False


    def on_stdout_need_update(self, event):
        if event.entry.stdout_lines == self.stdout_viewer.data:
            self.stdout_need_update = True


    def on_stderr_need_update(self, event):
        if event.entry.stderr_lines == self.stderr_viewer.data:
            self.stderr_need_update = True


    def get_search_result(self, query: str):

        result = list(self.main_frame.updater.entries.values())

        if not query:
            return result

        query_list: typing.List[str] = self.re_query_fragment.findall(query.lower().strip())

        for fragment in query_list:

            # status
            if fragment.startswith('status:'):
                fragment = fragment[len('status:'):]
                result = [entry for entry in result if fragment in entry.status]
                continue

            # column
            if fragment.startswith(self.search_column_tuple):
                column, fragment = fragment.split(':', maxsplit=1)
                function = self.search_column_dict[column]
                result = [entry for entry in result if fragment in function(entry).lower()]
                continue

            # simple search
            if fragment.startswith('-'):
                fragment = fragment[1:]
                result = [entry for entry in result if not fragment.lower() in entry.blend_path.lower()]
            else:
                result = [entry for entry in result if fragment.lower() in entry.blend_path.lower()]

        return result


    def execute_search(self, query: str):
        entries = self.get_search_result(query)
        self.model_list.set_data(entries)


    def refresh(self):
        self.execute_search(self.search.search.GetValue().strip())


Event_Stdout_Line_Printed, EVT_STDOUT_LINE_PRINTED = wx.lib.newevent.NewEvent()
Event_Stderr_Line_Printed, EVT_STDERR_LINE_PRINTED = wx.lib.newevent.NewEvent()


class Main_Frame(wxp_utils.Generic_Frame):


    def __init__(self, files: list[str], columns: typing.Optional[typing.Iterable[typing.Tuple[str, int, typing.Callable[[int], str]]]] = None):

        self.updater = updater.Updater.from_files(files)

        if not self.updater.entries:
            raise Exception("Nothing to do. No models provided in __blends__.")

        blender_executable = collections.Counter([entry.model.blender_executable for entry in self.updater.entries.values()]).most_common(1)[0][0]

        self.blender_server = blender_server.Blender_Server(blender_executable)

        self.init_title = "Blend Converter"

        font = wx.Font(14, wx.SWISS, wx.NORMAL, wx.NORMAL, False, 'Helvetica')  # type: ignore

        if columns is None:
            self.user_columns = []
        else:
            self.user_columns = columns

        super().__init__(None, self.init_title, font = font)

        def refresh():
            if self.__nonzero__():
                self.result_panel.refresh()

        updater.update_ui = refresh

        updater.stdout_line_printed = lambda entry: wx.PostEvent(self, Event_Stdout_Line_Printed(entry=entry))
        updater.stderr_line_printed = lambda entry: wx.PostEvent(self, Event_Stderr_Line_Printed(entry=entry))


        self.sizer = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(self.sizer)

        self.init_ui()

        self.SetBackgroundColour("white")
        self.SetSize((1600, 900))
        self.Centre()

        self.pause(self.updater.is_paused)

        self.set_blends()


    def set_blends(self):
        blend_paths = utils.list_by_key(self.updater.entries.values(), lambda entry: os.path.realpath(entry.model._source_path))
        self.blend_panel.load_data(blend_paths)


    @classmethod
    def get_app(cls, files, columns = None):
        app = wxp_utils.App()
        frame = cls(files=files, columns = columns)
        frame.Show()
        frame.show_console(False)
        return app


    def init_ui(self):

        self.notebook = wx.Notebook(self)
        self.sizer.Add(self.notebook, 1, wx.EXPAND)

        self.result_panel = Result_Panel(self.notebook)
        self.notebook.AddPage(self.result_panel, "Result")

        self.blend_panel = wx_blend.Blend_Panel(self.notebook)
        self.notebook.AddPage(self.blend_panel, "Blend")


    def set_menu_bar(self):

        menu = wx.Menu()
        self.menubar.Append(menu, "&Updater")

        self.Bind(wx.EVT_MENU, self.on_show_app_scripts, menu.Append(wx.ID_ANY, "Show Scripts"))

        self.Bind(wx.EVT_MENU, self.on_open_scripts_VSCode, menu.Append(wx.ID_ANY, "Open Scripts VSCode"))

        self.pause_menu_item: wx.MenuItem = menu.Append(wx.ID_ANY, "Pause")
        self.Bind(wx.EVT_MENU, self.on_updater_pause_toggle, self.pause_menu_item)

        menu.AppendSeparator()

        self.Bind(wx.EVT_MENU, self.on_reload_updater, menu.Append(wx.ID_ANY, "Reload Scripts\tCtrl+R"))

        self.Bind(wx.EVT_MENU, self.on_restart, menu.Append(wx.ID_ANY, "Restart"))

        self.Bind(wx.EVT_MENU, self.on_mark_update_all, menu.Append(wx.ID_ANY, "Mark All As Needing Update"))

        self.Bind(wx.EVT_MENU, self.on_terminate_and_pause, menu.Append(wx.ID_ANY, "Terminate All and Pause"))

        menu = wx.Menu()
        self.menubar.Append(menu, "&Tool")

        self.Bind(wx.EVT_MENU, self.on_settings, menu.Append(wx.ID_ANY, "Settings"))

        if os.name == 'nt':
            menu = wx.Menu()
            self.menubar.Append(menu, '&Window')
            self.Bind(wx.EVT_MENU, self.on_show_console_on_top, menu.Append(wx.ID_ANY, "Show Console On Top"))


    def on_show_app_scripts(self, event = None):
        utils.os_show(utils.deduplicate(self.updater.init_files))


    def on_open_scripts_VSCode(self, event = None):
        subprocess.Popen(['code', '-n', *self.updater.init_files], shell = True)


    def on_updater_pause_toggle(self, event = None):
        self.pause(not self.updater.is_paused)


    def pause(self, value: bool):
        self.updater.is_paused = value
        if self.updater.is_paused:
            self.SetTitle(self.init_title + ' [Paused]')
            self.pause_menu_item.SetItemLabel("Unpause")
        else:
            self.SetTitle(self.init_title)
            self.pause_menu_item.SetItemLabel("Pause")


    def on_reload_updater(self, event):
        self.updater.reload_targets()
        self.result_panel.execute_search('')
        self.set_blends()


    def on_mark_update_all(self, event):

        for entry in self.updater.entries.values():
            entry.status = 'needs_update'

        updater.update_ui()


    def on_terminate_and_pause(self, event):

        if not self.updater.is_paused:
            self.on_updater_pause_toggle()

        for entry in self.updater.entries.values():
            entry.terminate()

        self.updater.poke_all()


    def on_restart(self, event):

        for entry in self.updater.entries.values():
            entry.terminate()

        # TODO: does not work for argv with spaces
        os.execv(sys.executable, [sys.executable] + sys.argv)


    def on_settings(self, event):

        settings = {
            'double_click_action': (
                {
                    'show_source_in_explorer': self.result_panel.model_list.on_show_source_in_explorer,
                    'open_source': self.result_panel.model_list.on_open_source,
                    'show_result_in_explorer': self.result_panel.model_list.on_show_result_in_explorer,
                    'open_result': self.result_panel.model_list.on_open_result,
                    'nothing': self.result_panel.model_list.on_empty_double_click_function,
                },
                self.result_panel.model_list.double_click_function
            ),
        }

        with wxp_utils.Generic_Selector_Dialog(self, settings, title = f"Settings") as dialog:

            dialog.SetMaxSize((-1, -1))
            dialog.SetSize(1000, 600)
            dialog.CenterOnScreen()

            result = dialog.ShowModal()

            if result != wx.ID_OK:
                return

            dialog_data = dialog.get_data()

        self.result_panel.model_list.double_click_function = dialog_data['double_click_action']


    def on_show_console_on_top(self, event):
        console_manager = utils.Console_Shown()
        console_manager.show(True)
        console_manager.always_on_top(True)
        self.is_console_shown = True
