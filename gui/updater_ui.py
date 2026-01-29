from __future__ import annotations

import os
import sys
import re
import typing
import json
import subprocess
import collections
import base64
import shutil

import pyperclip
import wx
import wx.lib.newevent
import wx.lib.agw.aui as aui


from .. import utils
from .. import common
from .. import updater

from ..blender import blender_server

from . import wx_blend
from . import wxp_utils

class Model_List(wxp_utils.Item_Viewer_Native):

    parent: Result_Panel


    def __init__(self, parent, columns: typing.Iterable[typing.Tuple[str, int, typing.Callable[[int], str]]]):
        """
        `columns`: list of tuples (name, width, function)
        """

        super().__init__(parent, style = wx.LC_REPORT | wx.LC_HRULES | wx.LC_VRULES | wx.LC_VIRTUAL)

        self.parent = parent

        self.main_frame: Main_Frame = self.GetTopLevelParent()

        self.columns = [
            ('live', 40, self.get_column_live_update),
            ('ℹ️', 40, self.get_column_icon_status),
            ('status', 175, self.get_column_status),
            ('path', 800, self.get_column_path),
            # ('path_parts', 600, self.get_column_path_parts),
            ('ext', 100, self.get_column_result_type),
            # ('poke_time', 200, self.get_column_poke_time),
        ]

        self.columns.extend(columns)

        self.set_columns(self.columns)
        self.set_item_attrs()

        self.Bind(wx.EVT_KEY_DOWN, self.on_key)

        self.double_click_function: typing.Optional[typing.Callable[[updater.Program_Entry]]] = self.on_empty_double_click_function

        self.Bind(wx.EVT_LEFT_DCLICK, self._on_left_double_click)
        self.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_item_selected)
        self.Bind(wx.EVT_LIST_ITEM_RIGHT_CLICK, self.on_right_click)


    def set_columns(self, columns):
        for i, column in enumerate(columns):
            self.InsertColumn(i, column[0])
            self.SetColumnWidth(i, column[1])


    def on_empty_double_click_function(self, entry):
        pass


    def set_item_attrs(self):

        self.status_to_bg_color = dict(
            ok = wx.Colour(91, 237, 120),
            needs_update = wx.Colour(240, 235, 98),
            updating = wx.Colour(242, 176, 83),
            error = wx.Colour(255, 105, 97),
            does_not_exist = wx.Colour(211, 211, 211),
            waiting_for_dependency = wx.Colour(201, 177, 113),
        )

        for key, value in self.status_to_bg_color.items():
            item_attr = wx.ItemAttr()
            item_attr.SetBackgroundColour(value)
            self.status_to_bg_color[key] = item_attr


    def set_data(self, data):

        self.Freeze()

        self.data: list[updater.Program_Entry] = data
        self.SetItemCount(len(data))
        self.Refresh()

        if not self.data:
            self.main_frame.Refresh()

        self.Thaw()


    def OnGetItemText(self, row: int, col: int) -> str:
        return self.columns[col][2](self.data[row])


    def get_column_icon_status(self, item: updater.Program_Entry):
        if item.status == 'ok':
            return '✔️'
        elif item.status == 'updating':
            return '🔨'
        elif item.status == 'needs_update':
            return '🔥'
        elif item.status == 'error':
            return '❌'
        elif item.status == 'waiting_for_dependency':
            return '🔒'
        elif item.status == 'does_not_exist':
            return '👻'
        elif item.status == 'unknown':
            return '❓'
        else:
            return ''


    def get_column_live_update(self, item: updater.Program_Entry):
        if item.is_manual_update:
            return '🚀'
        elif item.is_live_update:
            return '⚡'
        else:
            return ''


    # def get_column_path_parts(self, item: updater.Program_Entry):
    #     return " • ".join(item.program.path_list[-3:])


    def get_column_path(self, item: updater.Program_Entry):
        if item.program.blend_path.startswith(self.parent.common_blend_path):
            return '...' + item.program.blend_path[len(self.parent.common_blend_path):]
        else:
            return item.program.blend_path

    def get_column_result_type(self, item: updater.Program_Entry):
        return os.path.splitext(item.program.result_path)[1]

    def get_column_poke_time(self, item: updater.Program_Entry):
        return utils.get_time_str_from(item.poke_time)

    def get_column_status(self, item: updater.Program_Entry):
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
            if os.path.exists(entry.program.result_path):
                self.on_show_result_in_explorer(entry)
            elif os.path.exists(os.path.dirname(entry.program.result_path)):
                utils.os_open(os.path.dirname(entry.program.result_path))
            else:
                wx.MessageBox(f"The result path does not exist yet:\n{entry.program.result_path}", 'File does not exist', style= wx.OK | wx.ICON_ERROR)

        elif mask == (True, True, True):
            self.on_compare_model(entry)

        elif mask == (True, True, False):
            utils.os_show([entry.program.blend_path, entry.program.result_path if os.path.exists(entry.program.result_path) else entry.program.report_path])

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

        blend_path = entry.program.blend_path
        menu_item = menu.append_item(f"Show Blend", get_func(utils.os_show, blend_path))
        menu_item.Enable(os.path.exists(blend_path))

        menu_item = menu.append_item(f"Open Blend", get_func(self.on_open_source, entry))
        menu_item.Enable(os.path.exists(blend_path))

        menu.append_separator()

        menu_item = menu.append_item(f"Show Result", get_func(utils.os_show, entry.program.result_path))
        menu_item.Enable(os.path.exists(entry.program.result_path))

        menu_item = menu.append_item(f"Open Result", get_func(self.on_open_result, entry))
        menu_item.Enable(os.path.exists(entry.program.result_path))

        menu_item = menu.append_item(f"Show Result Dir", get_func(utils.os_open, os.path.dirname(entry.program.result_path)))
        menu_item.Enable(os.path.exists( os.path.dirname(entry.program.result_path)))

        menu.append_separator()

        output_file = entry.stdout_file
        menu_item = menu.append_item(f"Show Stdout file", get_func(utils.os_show, output_file))
        menu_item.Enable(os.path.exists(output_file))

        output_file = entry.stderr_file
        menu_item = menu.append_item(f"Show Stderr file", get_func(utils.os_show, output_file))
        menu_item.Enable(os.path.exists(output_file))

        menu_item = menu.append_item(f"Compare", get_func(self.on_compare_model, entry))
        menu_item.Enable(os.path.exists(blend_path) and os.path.exists(entry.program.result_path))

        menu.append_separator()

        menu_item = menu.append_item(f"Copy Command", get_func(self.on_copy_conversion_command, entry))
        menu_item = menu.append_item(f"Copy Folder Basename", get_func(self.on_copy_folder_basename, entry))
        menu_item = menu.append_item(f"Copy Blend Path", get_func(self.on_copy_blend_path, entry))

        menu.append_separator()

        menu_item = menu.append_item(f"Show Difference VSCode (Single Entry)", get_func(self.on_show_diff_vscode, entry))
        menu_item = menu.append_item(f"Show Difference", get_func(self.on_show_difference, entry))
        menu_item = menu.append_item(f"Show Difference Inline", get_func(self.on_show_inline_difference, entry))

        menu_item = menu.append_item(f"Set As Updated", get_func(self.on_set_as_updated, entry))

        menu.append_separator()

        menu_item = menu.append_item(f"Mark As Needs Update", get_func(self.on_mark_as_needs_update))
        menu_item = menu.append_item(f"Poke Selected", get_func(self.on_poke_entries, entry))

        menu.append_separator()

        # menu_item = menu.append_item(f"Force Update", get_func(self.on_entry_force_update, entry))

        menu_item = menu.append_item(f"Update Selected", get_func(self.on_update_selected))

        menu.append_separator()

        menu_item = menu.append_item(f"Force Execute Selected", get_func(self.on_force_execute_selected))

        menu.append_separator()

        menu_item = menu.append_item(f"Set Config", get_func(self.on_set_config, entry))
        menu_item.Enable(bool(entry.program.config))

        menu.append_separator()
        menu_item = menu.append_item(f"Enable Live Update", get_func(self.on_enable_live_update, True))
        menu_item = menu.append_item(f"Disable Live Update", get_func(self.on_enable_live_update, False))


        self.PopupMenu(menu)
        menu.Destroy()


    def on_enable_live_update(self, value):
        for entry in self.get_selected_items():
            entry.is_live_update = value
        self.Refresh()


    def on_item_selected(self, event: wx.ListEvent):
        entry = self.data[int(event.GetIndex())]

        self.main_frame.stdout_viewer.set_data(entry.stdout_lines)
        self.main_frame.stderr_viewer.set_data(entry.stderr_lines)
        # if os.path.exists(entry.stdout_file):
        #     self.parent.console_output.LoadFile(entry.stdout_file)
        #     self.parent.console_output.SetScrollPos(wx.VERTICAL, self.parent.console_output.GetScrollRange(wx.VERTICAL))
        #     self.parent.console_output.SetInsertionPoint(-1)
        # else:
        #     self.parent.console_output.Clear()

        self.main_frame.Refresh()


    def on_poke_entries(self, entry: updater.Program_Entry):
        for entry in self.get_selected_items():
            self.main_frame.updater.poke_entry(entry)


    def get_conversion_command(self, entries: typing.Iterable[updater.Program_Entry]):

        programs = []

        for entry in entries:
            programs.append([
                entry.from_module_file,
                entry.programs_getter_name,
                entry.keyword_arguments,
            ])

        command = utils.get_command_from_list([
            sys.executable,
            common.get_script_path('forced_update'),
            json.dumps(dict(programs=programs), ensure_ascii=False)
        ])

        return command


    def on_copy_conversion_command(self, entry: updater.Program_Entry):
        wxp_utils.set_clipboard_text(self.get_conversion_command(self.get_selected_items()))


    def on_show_source_in_explorer(self, entry: updater.Program_Entry):
        utils.os_show(entry.program.blend_path)

    def on_open_source(self, entry: updater.Program_Entry):
        self.GetTopLevelParent().blender_server.ensure()
        self.GetTopLevelParent().blender_server.open_mainfile(entry.program.blend_path)

    def on_show_result_in_explorer(self, entry: updater.Program_Entry):
        utils.os_show(entry.program.result_path)

    def on_open_result(self, entry: updater.Program_Entry):
        path = entry.program.result_path

        if not os.path.exists(path):
            with wx.MessageDialog(None, f"{path}", 'File does not exist.', wx.OK | wx.ICON_ERROR) as dialog:
                dialog.ShowModal()
            return

        if path.endswith('.bam'):
            panda_viewer_path = common.get_script_path('panda3d_viewer')
            subprocess.Popen([sys.executable, panda_viewer_path, path])
        elif path.endswith('.blend'):
            cmd = [entry.program.blender_executable, path]
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
            pyperclip.copy(self.get_conversion_command(self.get_selected_items()))
        elif key_code == ord('A'):
            prev_func = self.on_item_selected
            self.on_item_selected = lambda a, b: None
            for index in range(self.GetItemCount()):
                self.Select(index)
            self.on_item_selected = prev_func


    def on_compare_model(self, entry: updater.Program_Entry):

        args = {
            'blend_path': entry.program.blend_path,
            'result_path': entry.program.result_path
        }

        cmd = [entry.program.blender_executable, '--python', common.get_script_path('start_compare'), '--', '-json_args', json.dumps(args)]

        utils.open_blender_detached(*cmd)


    def on_open_source(self, entry: updater.Program_Entry):

        cmd = [entry.program.blender_executable, entry.program.blend_path]

        utils.open_blender_detached(*cmd)


    def on_copy_folder_basename(self, entry: updater.Program_Entry):
        wxp_utils.set_clipboard_text("\n".join((os.path.basename(os.path.dirname(entry.program.blend_path)) for entry in self.get_selected_items())))


    def on_copy_blend_path(self, entry: updater.Program_Entry):
        wxp_utils.set_clipboard_text("\n".join((entry.program.blend_path for entry in self.get_selected_items())))


    def on_mark_as_needs_update(self):
        for entry in self.get_selected_items():
            entry.status = 'needs_update'


    def on_entry_force_update(self, entry: updater.Program_Entry):

        main_frame: Main_Frame = self.GetTopLevelParent()

        if main_frame.updater.total_max_parallel_executions_exceeded():
            wx.MessageBox("Max amount of simultaneous updates exceeded.", "Error", style= wx.OK | wx.ICON_ERROR)
            return

        entry.status = 'needs_update'
        entry.update(main_frame.updater.poke_waiting_for_dependency)


    def on_set_config(self, entry: updater.Program_Entry):

        config = entry.program.config
        if not config:
            return

        def save_without_restart(event):
            dialog.Destroy()
            config.from_ui_data(dialog.get_data())
            config.save()

        with wxp_utils.Generic_Selector_Dialog(self, config.to_ui_data(), title = f"Config: {os.path.basename(entry.program.blend_path)}") as dialog:

            dialog.ok_button.SetLabel("Restart")

            button = wx.Button(dialog, wx.ID_APPLY)
            button.SetLabel('Save Without Restart')
            button.Bind(wx.EVT_BUTTON, save_without_restart)
            dialog.button_sizer.Insert(0, button)

            dialog.CenterOnScreen()

            result = dialog.ShowModal()

            if result != wx.ID_OK:
                return

            config.from_ui_data(dialog.get_data())

            config.save()

        self.main_frame.on_restart()


    def on_update_selected(self):
        for entry in self.get_selected_items():
            if entry.status in ('needs_update', 'error'):
                entry.is_manual_update = True
        self.Refresh()


    def on_force_execute_selected(self):
        for entry in self.get_selected_items():
            entry.is_manual_update = True
        self.Refresh()


    def on_show_diff_vscode(self, entry: updater.Program_Entry):
        from .. import diff_utils
        import threading
        threading.Thread(target=diff_utils.show_program_diff_vscode, args=[entry.program]).start()


    def on_show_difference(self, entry: updater.Program_Entry):

        import difflib

        def get_difference(entry: updater.Program_Entry):
            prev_report = entry.program.get_prev_report_diff()
            next_report = entry.program.get_next_report_diff()
            return '\n'.join(difflib.unified_diff(
                json.dumps(prev_report, indent=4, default = lambda x: x._to_dict()).splitlines(),
                json.dumps(next_report, indent=4, default = lambda x: x._to_dict()).splitlines(),
                fromfile='PREVIOUS', tofile='NEXT', lineterm=''))

        difference_to_entries = utils.list_by_key(self.get_selected_items(), key=get_difference)

        lines = []

        for diff, entries in difference_to_entries.items():

            if diff:
                lines.append(diff)
            else:
                lines.append('NO DIFFERENCE')

            lines.append('')
            lines.append('')
            lines.append('\n'.join(e.program.blend_path for e in entries))
            lines.append('#' * 80)

        dialog = wxp_utils.Text_Dialog(self, "Difference", '\n'.join(lines))
        dialog.Show()


    def on_show_inline_difference(self, entry: updater.Program_Entry):

        import difflib

        def get_difference(entry: updater.Program_Entry):
            prev_report = entry.program.get_prev_report_diff()
            next_report = entry.program.get_next_report_diff()

            a = json.dumps(prev_report, default = lambda x: x._to_dict())
            b = json.dumps(next_report, default = lambda x: x._to_dict())

            matcher = difflib.SequenceMatcher(None, a, b)
            result = []

            for tag, i1, i2, j1, j2 in matcher.get_opcodes():
                if tag == 'replace':
                    result.append(f"REPLACE:\n{a[i1:i2]} -> {b[j1:j2]}")
                elif tag == 'delete':
                    result.append(f"DELETE:\n{a[i1:i2]}")
                elif tag == 'insert':
                    result.append(f"INSERT:\n{b[j1:j2]}")

            return '\n\n'.join(result)

        difference_to_entries = utils.list_by_key(self.get_selected_items(), key=get_difference)

        lines = []

        for diff, entries in difference_to_entries.items():

            if diff:
                lines.append(diff)
            else:
                lines.append('NO DIFFERENCE')

            lines.append('')
            lines.append('')
            lines.append('\n'.join(e.program.blend_path for e in entries))
            lines.append('#' * 80)

        dialog = wxp_utils.Text_Dialog(self, "Inline Difference", '\n'.join(lines))
        dialog.Show()


    def on_set_as_updated(self, entry: updater.Program_Entry):

        selected_entries =  self.get_selected_items()

        text = (
            f"Are you sure you want to set the entries as up to date?"
            '\n\n'
            +
            '\n'.join([entry.program.blend_path for entry in selected_entries])
        )

        with wx.MessageDialog(None, text, f"Set As Updated ({len(selected_entries)})", wx.YES | wx.NO | wx.NO_DEFAULT | wx.ICON_WARNING) as dialog:
            result = dialog.ShowModal()

            if result != wx.ID_YES:
                return

        for entry in selected_entries:
            entry.program.write_report()

        self.main_frame.updater.poke_all()


class Output_Lines(wxp_utils.Item_Viewer_Native):


    def __init__(self, parent, name: str):

        super().__init__(parent, style = wx.LC_REPORT | wx.LC_HRULES | wx.LC_VIRTUAL)

        self.parent = self.GetParent()

        self.data: typing.List[str] = []

        self.set_columns([('№', 50), (name, 1400)])

        self.Bind(wx.EVT_KEY_DOWN, self.on_key_down)


    def on_key_down(self, event: wx.Event):

        event.Skip()

        if not event.ControlDown():
            return

        key_code = event.GetKeyCode()

        if key_code == ord('C'):
            wxp_utils.set_clipboard_text('\n'.join(row[1].rstrip() for row in self.get_selected_items_text()))

        elif key_code == ord('A'):

            for index in range(self.GetItemCount()):
                self.Select(index)


    def set_data(self, data: typing.List[dict]):

        self.Freeze()

        self.data = data

        self.SetItemCount(len(data))
        self.Focus(len(data) - 1)

        self.Thaw()


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

        self.stdout_need_update = False
        self.stderr_need_update = False

        self.search_column_tuple = tuple(f"{column[0]}:" for column in self.model_list.columns)
        self.search_column_dict = {column[0]: column[2] for column in self.model_list.columns}

        if not '__restart__' in sys.argv:
            self.execute_search('')


        self.output_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.on_output_timer)
        self.output_timer.Start(1000)

        blend_paths = list(dict.fromkeys(entry.program.blend_path for entry in self.main_frame.updater.entries))
        if len(blend_paths) > 1:
            self.common_blend_path = os.path.commonpath(blend_paths)
        else:
            self.common_blend_path = os.sep


    def on_output_timer(self, event):

        if self.stdout_need_update:
            self.main_frame.stdout_viewer.update()
            self.stdout_need_update = False

        if self.stderr_need_update:
            self.main_frame.stderr_viewer.update()
            self.stderr_need_update = False


    def on_stdout_need_update(self, event):
        if event.entry.stdout_lines == self.main_frame.stdout_viewer.data:
            self.stdout_need_update = True


    def on_stderr_need_update(self, event):
        if event.entry.stderr_lines == self.main_frame.stderr_viewer.data:
            self.stderr_need_update = True


    def _get_search_result(self, query: str):

        result = list(self.main_frame.updater.entries)

        query_list: typing.List[str] = self.re_query_fragment.findall(query.lower().strip())

        for fragment in query_list:

            # status
            if fragment.startswith('status:'):
                fragment = fragment[len('status:'):]

                do_negate = False
                if fragment.startswith('not:'):
                    _ , fragment = fragment.split(':', maxsplit=1)
                    do_negate = True

                if do_negate:
                    result = [entry for entry in result if fragment not in entry.status]
                else:
                    result = [entry for entry in result if fragment in entry.status]

            # column
            elif fragment.startswith(self.search_column_tuple):
                column, fragment = fragment.split(':', maxsplit=1)

                do_negate = False
                if fragment.startswith('not:'):
                    _ , fragment = fragment.split(':', maxsplit=1)
                    do_negate = True

                column_function = self.search_column_dict[column]

                if do_negate:
                    result = [entry for entry in result if fragment not in column_function(entry).lower()]
                else:
                    result = [entry for entry in result if fragment in column_function(entry).lower()]

            # is_live_update
            elif fragment == ':live':
                result = [entry for entry in result if entry.is_live_update]

            elif fragment == ':-live':
                result = [entry for entry in result if not entry.is_live_update]

            # simple search
            elif fragment.startswith('-'):
                fragment = fragment[1:]
                result = [entry for entry in result if not fragment.lower() in entry.program.blend_path.lower()]

            else:
                result = [entry for entry in result if fragment.lower() in entry.program.blend_path.lower()]

        return result


    def get_search_result(self, query: str):

        result = []

        for sub_query in query.split(' OR '):
            result.extend(self._get_search_result(sub_query))

        return list(dict.fromkeys(result))


    def execute_search(self, query: str):
        entries = self.get_search_result(query)
        self.model_list.set_data(entries)


    def refresh(self):
        self.execute_search(self.search.search.GetValue().strip())


    def set_query(self, query: str):
        self.search.search.SetValue(query)


Event_Stdout_Line_Printed, EVT_STDOUT_LINE_PRINTED = wx.lib.newevent.NewEvent()
Event_Stderr_Line_Printed, EVT_STDERR_LINE_PRINTED = wx.lib.newevent.NewEvent()


class BC_App(wx.App):

    main_frame: Main_Frame


class Main_Frame(wxp_utils.Generic_Frame):


    def __init__(self, program_definitions: typing.List[typing.Tuple[str, str, str]], columns: typing.Optional[typing.Iterable[typing.Tuple[str, int, typing.Callable[[int], str]]]] = None):

        self.updater = updater.Updater.from_files(program_definitions)

        if not self.updater.entries:
            raise Exception(f"No programs provided in files: {program_definitions}")

        blender_executable = collections.Counter([entry.program.blender_executable for entry in self.updater.entries]).most_common(1)[0][0]

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

        updater.update_ui = lambda: wx.CallAfter(refresh)

        updater.stdout_line_printed = lambda entry: wx.PostEvent(self, Event_Stdout_Line_Printed(entry=entry))
        updater.stderr_line_printed = lambda entry: wx.PostEvent(self, Event_Stderr_Line_Printed(entry=entry))

        self.SetDoubleBuffered(True)

        self.sizer = wx.BoxSizer(wx.VERTICAL)

        self.init_ui()

        self.SetSizer(self.sizer)

        self.SetBackgroundColour("white")
        self.SetSize((1600, 900))
        self.Centre()

        self.pause(self.updater.is_paused)

        # self.set_blends()


    # def set_blends(self):
    #     blend_paths = utils.list_by_key(self.updater.entries, lambda entry: os.path.realpath(entry.program.blend_path))
    #     self.blend_panel.load_data(blend_paths)


    @classmethod
    def get_app(cls, program_definitions: typing.List[typing.Tuple[str, str, str]], columns = None):

        print(sys.argv)

        app = BC_App()
        frame = cls(program_definitions, columns = columns)
        app.main_frame = frame

        is_console_shown = False

        if '__restart__' in sys.argv:

            restart_info = json.loads(sys.argv[sys.argv.index('__restart__') + 1])

            frame.SetPosition(wx.Point(restart_info['x'], restart_info['y']))
            frame.SetSize(wx.Size(restart_info['width'], restart_info['height']))
            wx.CallAfter(frame.result_panel.set_query, restart_info['search_query'])

            is_console_shown = restart_info['is_console_shown']

            frame.Raise()

        frame.Show()

        if not (utils.Console_Shown.get_is_using_terminal() or is_console_shown):
            frame.show_console(False)

        return app


    def init_ui(self):

        style = (
            aui.AUI_NB_TOP |
            aui.AUI_NB_TAB_SPLIT |
            aui.AUI_NB_TAB_MOVE |
            aui.AUI_NB_SCROLL_BUTTONS |
            # aui.AUI_NB_CLOSE_ON_ACTIVE_TAB |
            # aui.AUI_NB_MIDDLE_CLICK_CLOSE |
            # aui.AUI_NB_CLOSE_ON_ALL_TABS |
            aui.AUI_NB_DRAW_DND_TAB
        )

        self.notebook = aui.AuiNotebook(self, agwStyle=style)
        self.sizer.Add(self.notebook, 1, wx.EXPAND)

        self.result_panel = Result_Panel(self.notebook)
        self.notebook.AddPage(self.result_panel, "Result")

        self.stdout_viewer = Output_Lines(self, 'stdout')

        self.notebook.AddPage(self.stdout_viewer, 'stdout')

        self.Bind(EVT_STDOUT_LINE_PRINTED, self.result_panel.on_stdout_need_update)

        self.stderr_viewer = Output_Lines(self, 'stderr')

        self.notebook.AddPage(self.stderr_viewer, 'stderr')

        self.Bind(EVT_STDERR_LINE_PRINTED, self.result_panel.on_stderr_need_update)

        self.on_restore_default_layout(None)

        self.notebook.Update()

        self.notebook.Bind(aui.EVT_AUINOTEBOOK_PAGE_CHANGED, self.on_page_changed)

        # self.blend_panel = wx_blend.Blend_Panel(self.notebook)
        # self.notebook.AddPage(self.blend_panel, "Blend")


    def set_menu_bar(self):

        menu = wx.Menu()
        self.menubar.Append(menu, "&Updater")

        self.Bind(wx.EVT_MENU, self.on_show_app_scripts, menu.Append(wx.ID_ANY, "Show Scripts In Explorer"))

        self.Bind(wx.EVT_MENU, self.on_open_VSCode_workspace, menu.Append(wx.ID_ANY, "Open .code-workspace"))

        menu.AppendSeparator()

        self.pause_menu_item: wx.MenuItem = menu.Append(wx.ID_ANY, "Pause\tCtrl+P")
        self.Bind(wx.EVT_MENU, self.on_updater_pause_toggle, self.pause_menu_item)

        menu.AppendSeparator()

        self.Bind(wx.EVT_MENU, self.on_restart, menu.Append(wx.ID_ANY, "Restart\tCtrl+R"))

        menu.AppendSeparator()

        self.Bind(wx.EVT_MENU, self.on_mark_update_all, menu.Append(wx.ID_ANY, "Mark All As Needing Update"))

        self.Bind(wx.EVT_MENU, self.on_terminate_and_pause, menu.Append(wx.ID_ANY, "Terminate All and Pause"))

        menu = wx.Menu()
        self.menubar.Append(menu, "&Tool")

        self.Bind(wx.EVT_MENU, self.on_settings, menu.Append(wx.ID_ANY, "Settings"))

        menu.AppendSeparator()

        self.Bind(wx.EVT_MENU, self.on_print_layout, menu.Append(wx.ID_ANY, "Print Layout"))

        self.Bind(wx.EVT_MENU, self.on_restore_default_layout, menu.Append(wx.ID_ANY, "Restore Layout"))


        if os.name == 'nt':
            menu = wx.Menu()
            self.menubar.Append(menu, '&Window')
            self.Bind(wx.EVT_MENU, self.on_show_console_on_top, menu.Append(wx.ID_ANY, "Show Console On Top"))

            if utils.Console_Shown.get_is_using_terminal():
                self.set_toggle_console_menu_item = lambda:None


    def on_show_app_scripts(self, event = None):
        utils.os_show(utils.deduplicate(utils.deduplicate(e.from_module_file for e in self.updater.entries)))


    def on_open_VSCode_workspace(self, event = None):

        folders = utils.deduplicate(os.path.dirname(e.from_module_file) for e in self.updater.entries)

        for folder in folders:
            for path in os.scandir(folder):
                if path.is_file() and path.name.endswith('.code-workspace'):
                    utils.os_open(path)


    def on_updater_pause_toggle(self, event = None):
        self.pause(not self.updater.is_paused)


    def pause(self, value: bool):
        self.updater.is_paused = value
        if self.updater.is_paused:
            self.SetTitle(self.init_title + ' [Paused]')
            self.pause_menu_item.SetItemLabel("Unpause\tCtrl+P")
        else:
            self.SetTitle(self.init_title)
            self.pause_menu_item.SetItemLabel("Pause\tCtrl+P")


    def on_mark_update_all(self, event):

        for entry in self.updater.entries:
            entry.status = 'needs_update'

        updater.update_ui()


    def on_terminate_and_pause(self, event):

        if not self.updater.is_paused:
            self.on_updater_pause_toggle()

        for entry in self.updater.entries:
            entry.is_manual_update = False
            entry.terminate()

        self.updater.poke_all()


    def on_restart(self, event = None):

        if not self.updater.is_paused:
            self.on_updater_pause_toggle()

        for entry in self.updater.entries:
            entry.is_manual_update = False
            entry.terminate()

        # TODO: does not work for argv with spaces

        position = self.GetPosition()
        size = self.GetSize()

        argv = sys.argv

        if '__restart__' in argv:
            argv = argv[:argv.index('__restart__')]

        restart_info = dict(
            x = position.x,
            y = position.y,
            width = size.width,
            height = size.height,
            search_query = self.result_panel.search.search.GetValue().strip(),
            is_console_shown = self.is_console_shown,
        )

        command = [
            sys.executable,
            *argv,
            utils.get_command_from_list(['__restart__', json.dumps(restart_info)]),
        ]

        self.show_console(True)

        os.execv(sys.executable, command)


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


    def on_print_layout(self, event):
        print(self.notebook.SavePerspective())


    def on_restore_default_layout(self, event):

        self.Freeze()

        default_aui_layout_path = os.path.join(os.path.dirname(__file__), 'default_aui_layout')
        with open(default_aui_layout_path) as f:
            self.notebook.LoadPerspective(f.read())

        self.Thaw()


    def on_page_changed(self, event):
        self.Refresh()
