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
import functools

import pyperclip
import wx
import wx.lib.newevent
import wx.lib.agw.aui as aui
import wx.ribbon as RB


from .. import utils
from .. import common
from .. import updater


from . import wxp_utils


def get_valid_paths(items: typing.List[str]):
    return [p for p in utils.deduplicate(items) if p and os.path.exists(p)]


def ask_conformation(message: str, caption = "Confirmation required"):

    with wx.MessageDialog(None, message, caption, wx.YES | wx.NO | wx.NO_DEFAULT | wx.ICON_WARNING) as dialog:
        result = dialog.ShowModal()

        return result == wx.ID_YES


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
        ]

        self.columns.extend(columns)

        self.set_columns(self.columns)
        self.set_item_attrs()

        self.Bind(wx.EVT_KEY_DOWN, self.on_key)

        self.double_click_function: typing.Optional[typing.Callable[[updater.Program_Entry]]] = self.empty_double_click_function

        self.Bind(wx.EVT_LEFT_DCLICK, self._on_left_double_click)
        self.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_item_selected)
        self.Bind(wx.EVT_LIST_ITEM_DESELECTED, self.on_item_selected)
        self.Bind(wx.EVT_LIST_ITEM_RIGHT_CLICK, self.on_right_click)

        self.ignore_select_events = False


    def set_columns(self, columns):
        for i, column in enumerate(columns):
            self.InsertColumn(i, column[0])
            self.SetColumnWidth(i, column[1])


    def empty_double_click_function(self, entry):
        pass


    def set_item_attrs(self):

        colors = {
            updater.Status.OK: wx.Colour(91, 237, 120),
            updater.Status.STALE : wx.Colour(240, 235, 98),
            updater.Status.UPDATING: wx.Colour(242, 176, 83),
            updater.Status.ERROR: wx.Colour(255, 105, 97),
            updater.Status.DOES_NOT_EXIST: wx.Colour(211, 211, 211),
            updater.Status.WAITING_FOR_DEPENDENCY: wx.Colour(201, 177, 113),
            updater.Status.YIELDING: wx.Colour(99, 179, 232),
        }

        self.status_to_bg_color = {}

        for key, value in colors.items():
            item_attr = wx.ItemAttr()
            item_attr.SetBackgroundColour(value)
            self.status_to_bg_color[key] = item_attr


    def set_data(self, data):
        self.data: list[updater.Program_Entry] = data
        self.SetItemCount(len(data))
        self.refresh_visible()



    def OnGetItemText(self, row: int, col: int) -> str:
        return self.columns[col][2](self.data[row])


    def get_column_icon_status(self, item: updater.Program_Entry):
        return updater.STATUS_ICON.get(item.status, '')


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


    def left_double_click(self, index: int, event: wx.MouseEvent):

        entry = self.data[index]

        mask = (event.ControlDown(), event.AltDown(), event.ShiftDown())

        # (ctrl, alt, shift)
        # alt - result
        # ctrl - source
        # shift - open

        if mask == (True, False, True):
            self.open_source(entry)
        elif mask == (True, False, False):
            self.show_source_in_explorer(entry)

        elif mask == (False, True, True):
            self.open_result(entry)
        elif mask == (False, True, False):
            if os.path.exists(entry.program.result_path):
                self.show_result_in_explorer(entry)
            elif os.path.exists(os.path.dirname(entry.program.result_path)):
                utils.os_open(os.path.dirname(entry.program.result_path))
            else:
                wx.MessageBox(f"The result path does not exist yet:\n{entry.program.result_path}", 'File does not exist', style= wx.OK | wx.ICON_ERROR)

        elif mask == (True, True, True):
            self.compare_model(entry)

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

        menu_item = menu.append_item(f"Open Blend", get_func(self.open_source, entry))
        menu_item.Enable(os.path.exists(blend_path))

        menu.append_separator()

        menu_item = menu.append_item(f"Show Result", get_func(utils.os_show, entry.program.result_path))
        menu_item.Enable(os.path.exists(entry.program.result_path))

        menu_item = menu.append_item(f"Open Result", get_func(self.open_result, entry))
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

        menu_item = menu.append_item(f"Compare", get_func(self.compare_model, entry))
        menu_item.Enable(os.path.exists(blend_path) and os.path.exists(entry.program.result_path))

        menu.append_separator()

        menu_item = menu.append_item(f"Copy Command", self.on_copy_conversion_command)
        menu_item = menu.append_item(f"Copy Folder Basename", self.on_copy_folder_basename)
        menu_item = menu.append_item(f"Copy Blend Path", self.on_copy_blend_path,)

        menu.append_separator()

        menu_item = menu.append_item(f"Show Difference VSCode (Single Entry)", get_func(self.show_diff_vscode, entry))
        menu_item = menu.append_item(f"Show Difference", self.on_show_difference)
        menu_item = menu.append_item(f"Show Difference Inline", self.on_show_inline_difference)

        menu.append_separator()

        menu_item = menu.append_item(f"Set As Updated", self.on_set_as_updated)
        menu_item = menu.append_item(f"Mark As Needs Update", self.on_mark_as_needs_update)
        menu_item = menu.append_item(f"Poke Selected", self.on_poke_entries)

        menu.append_separator()

        # menu_item = menu.append_item(f"Force Update", get_func(self.on_entry_force_update, entry))

        menu_item = menu.append_item(f"Update Selected", self.on_update_selected)

        menu.append_separator()

        menu_item = menu.append_item(f"Force Execute Selected", self.on_force_execute_selected)

        menu.append_separator()

        menu_item = menu.append_item(f"Set Config", get_func(self.set_config, entry))
        menu_item.Enable(bool(entry.program.config))

        menu.append_separator()
        menu_item = menu.append_item(f"Enable Live Update", get_func(self.enable_live_update, True))
        menu_item = menu.append_item(f"Disable Live Update", get_func(self.enable_live_update, False))


        self.PopupMenu(menu)
        menu.Destroy()


    def enable_live_update(self, value):
        for entry in self.get_selected_items():
            entry.is_live_update = value
        self.main_frame.update_ribbon_state()
        self.refresh_visible()


    def on_enable_live_update(self, event):
        self.enable_live_update(True)
        self.main_frame.updater.despatch()


    def on_disable_live_update(self, event):
        self.enable_live_update(False)


    def on_item_selected(self, event: wx.ListEvent):

        if not self.ignore_select_events:

            index = int(event.GetIndex())

            if index >= 0:
                entry = self.data[index]
                stdout_lines = entry.stdout_lines
                stderr_lines = entry.stderr_lines
            else:
                stdout_lines = []
                stderr_lines = []

            self.main_frame.stdout_viewer.data = stdout_lines
            self.main_frame.stdout_viewer.update()
            self.main_frame.stdout_viewer.refresh_visible()

            self.main_frame.stderr_viewer.data = stderr_lines
            self.main_frame.stderr_viewer.update()
            self.main_frame.stderr_viewer.refresh_visible()

        wx.CallAfter(self.main_frame.update_ribbon_state)

        event.Skip()


    def on_poke_entries(self, event):
        for entry in self.get_selected_items():
            self.main_frame.updater.poke_entry(entry)
        self.main_frame.updater.despatch()


    def get_conversion_command(self, entries: typing.Iterable[updater.Program_Entry]):

        programs = []

        for entry in entries:
            programs.append([
                entry.module_file_path,
                entry.programs_getter_name,
                entry.keyword_arguments,
            ])

        command = utils.get_command_from_list([
            sys.executable,
            common.get_script_path('forced_update'),
            json.dumps(dict(programs=programs), ensure_ascii=False)
        ])

        return command


    def on_copy_conversion_command(self, event):
        wxp_utils.set_clipboard_text(self.get_conversion_command(self.get_selected_items()))


    def show_source_in_explorer(self, entry: updater.Program_Entry):
        utils.os_show(entry.program.blend_path)


    def show_result_in_explorer(self, entry: updater.Program_Entry):
        utils.os_show(entry.program.result_path)


    def open_result(self, entry: updater.Program_Entry):
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


    def show_item(self, item):
        self.deselect_all()
        index = self.data.index(item)
        self.Select(index)
        self.Focus(index)


    def on_key(self, event: wx.KeyEvent):
        event.Skip()

        ctrl = event.ControlDown()
        alt = event.AltDown()

        key_code = event.GetKeyCode()

        if ctrl and key_code == ord('C'):
            pyperclip.copy(self.get_conversion_command(self.get_selected_items()))
        elif ctrl and not alt and key_code == ord('A'):
            self.on_select_all(None)
        elif not ctrl and alt and key_code == ord('A'):
            self.on_deselect_all(None)


    def compare_model(self, entry: updater.Program_Entry):

        args = {
            'blend_path': entry.program.blend_path,
            'result_path': entry.program.result_path
        }

        cmd = [entry.program.blender_executable, '--python', common.get_script_path('start_compare'), '--', '-json_args', json.dumps(args)]

        utils.open_blender_detached(*cmd)


    def open_source(self, entry: updater.Program_Entry):

        cmd = [entry.program.blender_executable, entry.program.blend_path]

        utils.open_blender_detached(*cmd)


    def on_copy_folder_basename(self, event):
        wxp_utils.set_clipboard_text("\n".join((os.path.basename(os.path.dirname(entry.program.blend_path)) for entry in self.get_selected_items())))


    def on_copy_blend_path(self, event):
        wxp_utils.set_clipboard_text("\n".join((entry.program.blend_path for entry in self.get_selected_items())))


    def on_mark_as_needs_update(self, event):
        for entry in self.get_selected_items():
            entry.status = updater.Status.STALE
        self.main_frame.updater.despatch()
        self.refresh_visible()


    def set_config(self, entry: updater.Program_Entry):

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


    def on_update_selected(self, event):
        for entry in self.get_selected_items():
            if entry.status in (updater.Status.STALE, updater.Status.ERROR):
                entry.is_manual_update = True
        self.main_frame.updater.despatch()
        self.refresh_visible()


    def on_terminate_selected(self, event):

        for entry in self.get_selected_items():
            entry.is_manual_update = False

        for entry in self.get_selected_items():
            entry.terminate()

        self.main_frame.updater.despatch()

        self.main_frame.update_terminate_button()
        self.refresh_visible()


    def on_force_execute_selected(self, event):

        for entry in self.get_selected_items():
            entry.is_manual_update = True

        self.main_frame.updater.despatch()

        self.main_frame.update_terminate_button()
        self.refresh_visible()


    def show_diff_vscode(self, entry: updater.Program_Entry):
        from .. import diff_utils
        import threading
        threading.Thread(target=diff_utils.show_program_diff_vscode, args=[entry.program]).start()


    def on_show_difference(self, event):

        selected_items = self.get_selected_items()

        if len(selected_items) > 10 and not ask_conformation(f"Show the difference for {len(selected_items)} entires?"):
            return

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


    def on_show_inline_difference(self, event):

        selected_items = self.get_selected_items()

        if len(selected_items) > 5 and not ask_conformation(f"Show the inline difference for {len(selected_items)} entires?"):
            return

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


    def on_set_as_updated(self, event):

        selected_entries =  self.get_selected_items()

        text = (
            f"Set the entries as up to date?"
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


    def on_show_source_files(self, event):

        selected_items = self.get_selected_items()

        if len(selected_items) > 5 and not ask_conformation(f"Show {len(selected_items)} source files in the file explorer?"):
            return

        utils.os_show(get_valid_paths(entry.program.blend_path for entry in selected_items))


    def on_show_result_files(self, event):

        selected_items = self.get_selected_items()

        if len(selected_items) > 5 and not ask_conformation(f"Show {len(selected_items)} result files in the file explorer?"):
            return

        utils.os_show(get_valid_paths(entry.program.result_path for entry in selected_items))


    def on_open_source_files(self, event):

        selected_items = self.get_selected_items()

        if len(selected_items) > 3 and not ask_conformation(f"Open {len(selected_items)} source files?"):
            return

        for entry in selected_items:
            cmd = [entry.program.blender_executable, entry.program.blend_path]
            utils.open_blender_detached(*cmd)


    def on_open_result_files(self, event):

        selected_items = self.get_selected_items()

        if len(selected_items) > 3 and not ask_conformation(f"Open {len(selected_items)} result files?"):
            return

        for entry in selected_items:
            self.open_result(entry)


    def get_active_item(self):
        index = self.get_active_index()
        if index >= 0:
            return self.data[index]


    def on_set_config(self, event):
        self.set_config(self.get_active_item())


    def on_show_stdout_file_files(self, event):

        selected_items = self.get_selected_items()

        if len(selected_items) > 5 and not ask_conformation(f"Show {len(selected_items)} stdout files in the file explorer?"):
            return

        utils.os_show(get_valid_paths(entry.stdout_file for entry in selected_items))


    def on_show_stderr_file_files(self, event):

        selected_items = self.get_selected_items()

        if len(selected_items) > 5 and not ask_conformation(f"Show {len(selected_items)} stderr files in the file explorer?"):
            return

        utils.os_show(get_valid_paths(entry.stderr_file for entry in selected_items))


    def on_compare_model(self, event):
        self.compare_model(self.get_active_item())


    def on_show_diff_vscode(self, event):

        selected_items = self.get_selected_items()

        if len(selected_items) > 5 and not ask_conformation(f"Show the difference in VSCode for {len(selected_items)} entires?"):
            return

        for entry in selected_items:
            self.show_diff_vscode(entry)


    def on_select_all(self, event):
        self.ignore_select_events = True
        self.select_all()
        self.ignore_select_events = False


    def on_deselect_all(self, event):
        self.ignore_select_events = True
        self.deselect_all()
        self.ignore_select_events = False


class Output_Lines(wxp_utils.Item_Viewer_Native):


    def __init__(self, parent, name: str):

        super().__init__(parent, style = wx.LC_REPORT | wx.LC_HRULES | wx.LC_VIRTUAL)

        self.parent = self.GetParent()

        self.data: typing.List[str] = []

        self.set_columns([('№', 50), (name, 1400)])

        self.Bind(wx.EVT_KEY_DOWN, self.on_key_down)


    def on_key_down(self, event: wx.KeyEvent):

        event.Skip()

        if not event.ControlDown():
            return

        key_code = event.GetKeyCode()

        if key_code == ord('C'):
            wxp_utils.set_clipboard_text(''.join(self.data[row] for row in self.get_selected_indexes()))

        elif key_code == ord('A'):
            self.SetItemState(-1, wx.LIST_STATE_SELECTED, wx.LIST_STATE_SELECTED)



    def update(self):

        if self.GetItemCount():
            do_scroll = self.IsVisible(self.GetItemCount() - 1)
        else:
            do_scroll = True

        self.SetItemCount(len(self.data))

        if do_scroll:
            self.EnsureVisible(self.GetItemCount() - 1)


    def OnGetItemText(self, row: int, col: int):
        if col == 0:
            return str(row + 1)
        elif col == 1:
            return self.data[row].replace('\t', '    ')
        else:
            return ''


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
        if event.entry.stdout_lines is self.main_frame.stdout_viewer.data:
            self.stdout_need_update = True


    def on_stderr_need_update(self, event):
        if event.entry.stderr_lines is self.main_frame.stderr_viewer.data:
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


@functools.lru_cache(None)
def get_bitmap(id, size=(48, 48)):
    bitmap: wx.Bitmap = wx.ArtProvider.GetBitmap(id, wx.ART_TOOLBAR, size)

    image: wx.Image = bitmap.ConvertToImage()
    if image.HasAlpha():
        return bitmap

    image.InitAlpha()

    for y in range(image.GetHeight()):
        for x in range(image.GetWidth()):
            if image.GetRed(x, y) == 0 and image.GetGreen(x, y) == 0 and image.GetBlue(x, y) == 1:
                image.SetAlpha(x, y, 0)

    return image.ConvertToBitmap()


def get_bitmap_from_text(text: str, color = (0, 0, 0)):

    draw_size = 64

    bitmap: wx.Bitmap = wx.Bitmap(draw_size, draw_size)

    dc = wx.MemoryDC()

    font = wx.Font()
    font.SetPointSize(42)
    dc.SetFont(font)

    dc.SelectObject(bitmap)
    dc.Clear()

    x, y = dc.GetTextExtent(text)
    dc.DrawText(text, (draw_size - x) // 2 ,  (draw_size - y) // 2)


    image: wx.Image = bitmap.ConvertToImage()
    image.InitAlpha()

    alpha = bytes(255 - min(r, g, b) for r, g, b in zip(*(iter(image.GetData()),) * 3))

    image.SetRGB(wx.Rect(0, 0, draw_size, draw_size), *color)
    image.SetAlpha(bytes(alpha))

    bitmap = image.ConvertToBitmap()

    return bitmap


class BC_App(wx.App):

    main_frame: Main_Frame


class Button_Data:


    def __init__(self, label: str, icon = '', icon_color = (0, 0, 0), wx_icon = '', description = ""):
        self.id = wx.NewIdRef()
        self.label = label
        self.icon = icon
        self.icon_color = icon_color
        self.wx_icon = wx_icon
        self.description = description


    def get_bitmap(self):
        if self.wx_icon:
            return get_bitmap(self.wx_icon)
        elif self.icon:
            return get_bitmap_from_text(self.icon, color = self.icon_color)
        else:
            return get_bitmap_from_text('🛎️', color = self.icon_color)


    def get_data(self):
        return self.id, self.label, self.get_bitmap(), self.description


class Button:

    SELECT_ALL = Button_Data("Select All", icon = '☑️')
    DESELECT_ALL = Button_Data("Deselect All", icon = '↩️')

    TERMINATE = Button_Data("Terminate", wx_icon = wx.ART_DELETE, description = "Terminate selected entries.")
    EXECUTE = Button_Data("Execute", wx_icon = wx.ART_REDO, description = "Execute selected entries.")
    CONFIGURE = Button_Data("Configure", wx_icon = wx.ART_REPORT_VIEW, description = "Open the entry's configuration.")

    SHOW_SOURCE_FILES = Button_Data("Show Source", wx_icon = wx.ART_FIND, description = "Show source files in the file explorer.")
    SHOW_RESULT_FILES = Button_Data("Show Result", wx_icon = wx.ART_FIND, description = "Show result files in the file explorer.")

    EDIT_SOURCE_FILES = Button_Data("Edit Source", icon = '🌱', description = "Open source files.")
    EDIT_RESULT_FILES = Button_Data("Edit Result", icon = '🏆', description = "Open result files.")

    PAUSE = Button_Data("Pause", icon = '⏸️', description = "Pause the live execution.")
    RESUME = Button_Data("Resume", icon = '▶️', description = "Resume the live execution.")

    ENABLE_LIVE = Button_Data("Enable", icon = '⚡', icon_color=(191, 137, 0))
    DISABLE_LIVE = Button_Data("Disable", icon = '🚫', icon_color = (14, 56, 125))

    TERMINATE_ALL_AND_PAUSE = Button_Data("Terminate All And Pause", wx_icon = wx.ART_ERROR, description = "Terminate all entries and pause.")
    RESTART = Button_Data("Restart", wx_icon = wx.ART_UNDO, description = "Restart the GUI.")
    SETTINGS = Button_Data("Settings", icon = '⚙️', description = "Open the GUI settings.")


    SHOW_STDOUT_FILE = Button_Data("Stdout", wx_icon = wx.ART_FIND)
    SHOW_STDERR_FILE = Button_Data("Stderr", wx_icon = wx.ART_FIND)

    SHOW_PYTHON_SCRIPTS = Button_Data("Show", wx_icon = wx.ART_FIND)

    COMPARE = Button_Data("Compare", icon = '🧐', icon_color = (227, 114, 0))

    DIFF_VSCODE = Button_Data("Diff VSCode", wx_icon = wx.ART_MISSING_IMAGE)
    DIFF = Button_Data("Diff", wx_icon = wx.ART_MISSING_IMAGE)
    DIFF_INLINE = Button_Data("Diff Inline", wx_icon = wx.ART_MISSING_IMAGE)

    SET_AS_UPDATED = Button_Data("Set As Ok", icon = '👍', icon_color = (25, 117, 10))
    SET_AS_NEEDS_UPDATE = Button_Data("Set As Stale", icon = '🦕', icon_color = (166, 171, 0))
    POKE = Button_Data("Poke", icon = '👇')

    COPY_COMMAND = Button_Data("Command", wx_icon = wx.ART_COPY)
    COPY_FOLDER_BASENAME = Button_Data("Folder Basename", wx_icon = wx.ART_COPY)
    COPY_SOURCE_PATH = Button_Data("Source Path", wx_icon = wx.ART_COPY)

    LAYOUT_PRINT = Button_Data("Print", wx_icon = wx.ART_PRINT)
    LAYOUT_RESTORE = Button_Data("Restore", wx_icon = wx.ART_GO_HOME)

    CONSOLE_SHOW_ON_TOP = Button_Data("Show On Top", icon = '🔝')
    CONSOLE_TOGGLE = Button_Data("Toggle", icon = '🖥️')


BUTTONS_WITH_COUNT =[
    Button.EXECUTE,
    Button.SHOW_SOURCE_FILES,
    Button.SHOW_RESULT_FILES,
    Button.EDIT_SOURCE_FILES,
    Button.EDIT_RESULT_FILES,

    Button.SHOW_STDOUT_FILE,
    Button.SHOW_STDERR_FILE,

    Button.DIFF_VSCODE,
    Button.DIFF,
    Button.DIFF_INLINE,

    Button.SET_AS_UPDATED,
    Button.SET_AS_NEEDS_UPDATE,
    Button.POKE,

    Button.COPY_COMMAND,
    Button.COPY_FOLDER_BASENAME,
    Button.COPY_SOURCE_PATH,
]


class Main_Frame(wxp_utils.Generic_Frame):


    def __init__(self, definitions: typing.List[common.Program_Definition], columns: typing.Optional[typing.Iterable[typing.Tuple[str, int, typing.Callable[[int], str]]]] = None):

        self.updater = updater.Updater.from_entries(updater.get_program_entries(definitions))

        if not self.updater.entries:
            raise Exception(f"No programs provided in files: {definitions}")

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
                self.update_terminate_button()

        updater.update_ui = lambda: wx.CallAfter(refresh)

        def refresh_item(entry):
            if entry in self.result_panel.model_list.data:
                index = self.result_panel.model_list.data.index(entry)
                self.result_panel.model_list.RefreshItem(index)

        updater.update_item = lambda entry: wx.CallAfter(refresh_item, entry)

        updater.stdout_line_printed = lambda entry: wx.PostEvent(self, Event_Stdout_Line_Printed(entry=entry))
        updater.stderr_line_printed = lambda entry: wx.PostEvent(self, Event_Stderr_Line_Printed(entry=entry))


        self.sizer = wx.BoxSizer(wx.VERTICAL)

        self.init_ribbon_ui()
        self.init_ui()
        self.init_ribbon_events()
        self.map_button_to_id()
        self.update_ribbon_state(True)
        self.ribbon.Realize()
        self.update_ribbon_state()

        self.SetSizer(self.sizer)

        self.SetBackgroundColour("white")
        self.SetSize((1600, 900))
        self.Centre()

        self.pause(self.updater.is_paused)

        self.updater.update_entries()


    @classmethod
    def get_app(cls, definitions: typing.List[common.Program_Definition], columns = None):

        app = BC_App()
        frame = cls(definitions, columns = columns)
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


    def init_ribbon_ui(self):

        self.ribbon = RB.RibbonBar(self, style = RB.RIBBON_BAR_DEFAULT_STYLE)
        self.sizer.Add(self.ribbon, 0, wx.EXPAND)



        main_page = RB.RibbonPage(self.ribbon, wx.ID_ANY, "Main")


        select = RB.RibbonPanel(main_page, wx.ID_ANY, "Select", style = RB.RIBBON_PANEL_NO_AUTO_MINIMISE)
        bar = RB.RibbonButtonBar(select)
        bar.AddButton(*Button.SELECT_ALL.get_data())
        bar.AddButton(*Button.DESELECT_ALL.get_data())


        execution = RB.RibbonPanel(main_page, wx.ID_ANY, "Execution", style = RB.RIBBON_PANEL_NO_AUTO_MINIMISE)
        bar = RB.RibbonButtonBar(execution)
        bar.AddButton(*Button.TERMINATE.get_data())
        bar.AddButton(*Button.EXECUTE.get_data())
        bar.AddButton(*Button.CONFIGURE.get_data())


        live = RB.RibbonPanel(main_page, wx.ID_ANY, "Live", style = RB.RIBBON_PANEL_NO_AUTO_MINIMISE)
        bar = RB.RibbonButtonBar(live)
        bar.AddButton(*Button.PAUSE.get_data())
        bar.AddButton(*Button.RESUME.get_data())
        bar.AddButton(*Button.ENABLE_LIVE.get_data())
        bar.AddButton(*Button.DISABLE_LIVE.get_data())


        files = RB.RibbonPanel(main_page, wx.ID_ANY, "Files", style = RB.RIBBON_PANEL_NO_AUTO_MINIMISE)
        bar = RB.RibbonButtonBar(files)
        bar.AddButton(*Button.SHOW_SOURCE_FILES.get_data())
        bar.AddButton(*Button.EDIT_SOURCE_FILES.get_data())
        bar.AddButton(*Button.SHOW_RESULT_FILES.get_data())
        bar.AddButton(*Button.EDIT_RESULT_FILES.get_data())


        app_misc = RB.RibbonPanel(main_page, wx.ID_ANY, "App", style = RB.RIBBON_PANEL_NO_AUTO_MINIMISE)
        bar = RB.RibbonButtonBar(app_misc)
        bar.AddButton(*Button.TERMINATE_ALL_AND_PAUSE.get_data())
        bar.AddButton(*Button.RESTART.get_data())
        bar.AddButton(*Button.SETTINGS.get_data())



        inspect_page = RB.RibbonPage(self.ribbon, wx.ID_ANY, "Inspect")

        stdout = RB.RibbonPanel(inspect_page, wx.ID_ANY, "Output", style = RB.RIBBON_PANEL_NO_AUTO_MINIMISE)
        bar = RB.RibbonButtonBar(stdout)
        bar.AddButton(*Button.SHOW_STDOUT_FILE.get_data())
        bar.AddButton(*Button.SHOW_STDERR_FILE.get_data())

        script = RB.RibbonPanel(inspect_page, wx.ID_ANY, "Script", style = RB.RIBBON_PANEL_NO_AUTO_MINIMISE)
        bar = RB.RibbonButtonBar(script)
        bar.AddButton(*Button.SHOW_PYTHON_SCRIPTS.get_data())

        compare = RB.RibbonPanel(inspect_page, wx.ID_ANY, "Compare", style = RB.RIBBON_PANEL_NO_AUTO_MINIMISE)
        bar = RB.RibbonButtonBar(compare)
        bar.AddButton(*Button.COMPARE.get_data())

        difference = RB.RibbonPanel(inspect_page, wx.ID_ANY, "Difference", style = RB.RIBBON_PANEL_NO_AUTO_MINIMISE)
        bar = RB.RibbonButtonBar(difference)
        bar.AddButton(*Button.DIFF_VSCODE.get_data())
        bar.AddButton(*Button.DIFF.get_data())
        bar.AddButton(*Button.DIFF_INLINE.get_data())

        status = RB.RibbonPanel(inspect_page, wx.ID_ANY, "Status", style = RB.RIBBON_PANEL_NO_AUTO_MINIMISE)
        bar = RB.RibbonButtonBar(status)
        bar.AddButton(*Button.SET_AS_UPDATED.get_data())
        bar.AddButton(*Button.SET_AS_NEEDS_UPDATE.get_data())
        bar.AddButton(*Button.POKE.get_data())



        copy = RB.RibbonPanel(inspect_page, wx.ID_ANY, "Copy", style = RB.RIBBON_PANEL_NO_AUTO_MINIMISE)
        bar = RB.RibbonButtonBar(copy)
        bar.AddButton(*Button.COPY_COMMAND.get_data())
        bar.AddButton(*Button.COPY_FOLDER_BASENAME.get_data())
        bar.AddButton(*Button.COPY_SOURCE_PATH.get_data())


        layout = RB.RibbonPanel(inspect_page, wx.ID_ANY, "Layout", style = RB.RIBBON_PANEL_NO_AUTO_MINIMISE)
        bar = RB.RibbonButtonBar(layout)
        bar.AddButton(*Button.LAYOUT_PRINT.get_data())
        bar.AddButton(*Button.LAYOUT_RESTORE.get_data())

        console = RB.RibbonPanel(inspect_page, wx.ID_ANY, "Console", style = RB.RIBBON_PANEL_NO_AUTO_MINIMISE)
        bar = RB.RibbonButtonBar(console)
        bar.AddButton(*Button.CONSOLE_SHOW_ON_TOP.get_data())
        if not utils.Console_Shown.get_is_using_terminal():
            bar.AddButton(*Button.CONSOLE_TOGGLE.get_data())


    def map_button_to_id(self):

        self.button_id_to_bar: typing.Dict[wx.WindowIDRef, RB.RibbonButtonBar] = {}

        for page in self.ribbon.GetChildren():
            if isinstance(page, RB.RibbonPage):
                for panel in page.GetChildren():
                    if isinstance(panel, RB.RibbonPanel):
                        for bar in panel.GetChildren():
                            if isinstance(bar, RB.RibbonButtonBar):
                                for i in range(bar.GetButtonCount()):
                                    self.button_id_to_bar[bar.GetItemId(bar.GetItem(i))] = bar


    def enable_button(self, id: wx.WindowIDRef, enable: bool):
        bar = self.button_id_to_bar[id]
        bar.EnableButton(id, enable)


    def set_button_text(self, id: wx.WindowIDRef, text: str):
        bar = self.button_id_to_bar[id]
        bar.SetButtonText(id, text)


    def update_ribbon_state(self, initial = False):

        active = self.result_panel.model_list.get_active_item()
        selected = self.result_panel.model_list.get_selected_items()

        if initial:
            count = 999
            has_active = True
            is_configurable = True
            enabled_live_count = 999
            disabled_live_count = 999
        else:
            count = len(selected)
            has_active = bool(active)
            is_configurable = bool(active and active.program.config)
            enabled_live_count = sum(entry.is_live_update for entry in selected)
            disabled_live_count = count - enabled_live_count


        for button in BUTTONS_WITH_COUNT:
            self.set_button_text(button.id, button.label + f" ({count})")
            self.enable_button(button.id, bool(count))


        self.enable_button(Button.CONFIGURE.id, is_configurable)
        self.set_button_text(Button.CONFIGURE.id, Button.CONFIGURE.label + f"{' 🚫' if not is_configurable else ' (Active)'}")

        self.enable_button(Button.COMPARE.id, has_active)
        self.set_button_text(Button.COMPARE.id, Button.COMPARE.label + f"{' 🚫' if not has_active else ' (Active)'}")


        self.enable_button(Button.ENABLE_LIVE.id, bool(disabled_live_count))
        self.enable_button(Button.DISABLE_LIVE.id, bool(enabled_live_count))
        self.set_button_text(Button.ENABLE_LIVE.id, Button.ENABLE_LIVE.label + f" ({disabled_live_count}/{count})")
        self.set_button_text(Button.DISABLE_LIVE.id, Button.DISABLE_LIVE.label + f" ({enabled_live_count}/{count})")

        self.update_terminate_button(initial = initial)


    def update_terminate_button(self, initial = False):

        selected = self.result_panel.model_list.get_selected_items()

        if initial:
            count = 999
            running_entries_count = 999
        else:
            count = len(selected)
            running_entries_count = sum(entry.status in (updater.Status.UPDATING, updater.Status.YIELDING) for entry in selected)


        self.enable_button(Button.TERMINATE.id, bool(running_entries_count))
        self.set_button_text(Button.TERMINATE.id, Button.TERMINATE.label + f" ({running_entries_count}/{count})")


    def init_ribbon_events(self):

        self.Bind(RB.EVT_RIBBONBUTTONBAR_CLICKED, self.result_panel.model_list.on_select_all, Button.SELECT_ALL.id)
        self.Bind(RB.EVT_RIBBONBUTTONBAR_CLICKED, self.result_panel.model_list.on_deselect_all, Button.DESELECT_ALL.id)


        self.Bind(RB.EVT_RIBBONBUTTONBAR_CLICKED, self.result_panel.model_list.on_terminate_selected, Button.TERMINATE.id)
        self.Bind(RB.EVT_RIBBONBUTTONBAR_CLICKED, self.result_panel.model_list.on_force_execute_selected, Button.EXECUTE.id)
        self.Bind(RB.EVT_RIBBONBUTTONBAR_CLICKED, self.result_panel.model_list.on_set_config, Button.CONFIGURE.id)

        self.Bind(RB.EVT_RIBBONBUTTONBAR_CLICKED, self.result_panel.model_list.on_show_source_files, Button.SHOW_SOURCE_FILES.id)
        self.Bind(RB.EVT_RIBBONBUTTONBAR_CLICKED, self.result_panel.model_list.on_open_source_files, Button.EDIT_SOURCE_FILES.id)
        self.Bind(RB.EVT_RIBBONBUTTONBAR_CLICKED, self.result_panel.model_list.on_show_result_files,  Button.SHOW_RESULT_FILES.id)
        self.Bind(RB.EVT_RIBBONBUTTONBAR_CLICKED, self.result_panel.model_list.on_open_result_files,  Button.EDIT_RESULT_FILES.id)


        self.Bind(RB.EVT_RIBBONBUTTONBAR_CLICKED, self.on_pause, Button.PAUSE.id)
        self.Bind(RB.EVT_RIBBONBUTTONBAR_CLICKED, self.on_resume, Button.RESUME.id)

        self.Bind(RB.EVT_RIBBONBUTTONBAR_CLICKED, self.result_panel.model_list.on_enable_live_update, Button.ENABLE_LIVE.id)
        self.Bind(RB.EVT_RIBBONBUTTONBAR_CLICKED, self.result_panel.model_list.on_disable_live_update, Button.DISABLE_LIVE.id)


        self.Bind(RB.EVT_RIBBONBUTTONBAR_CLICKED, self.on_terminate_and_pause, Button.TERMINATE_ALL_AND_PAUSE.id)
        self.Bind(RB.EVT_RIBBONBUTTONBAR_CLICKED, self.on_restart, Button.RESTART.id)
        self.Bind(RB.EVT_RIBBONBUTTONBAR_CLICKED, self.on_settings, Button.SETTINGS.id)


        self.Bind(RB.EVT_RIBBONBUTTONBAR_CLICKED, self.result_panel.model_list.on_show_stdout_file_files, Button.SHOW_STDOUT_FILE.id)
        self.Bind(RB.EVT_RIBBONBUTTONBAR_CLICKED, self.result_panel.model_list.on_show_stderr_file_files, Button.SHOW_STDERR_FILE.id)

        self.Bind(RB.EVT_RIBBONBUTTONBAR_CLICKED, self.on_show_app_scripts, Button.SHOW_PYTHON_SCRIPTS.id)


        self.Bind(RB.EVT_RIBBONBUTTONBAR_CLICKED, self.result_panel.model_list.on_compare_model, Button.COMPARE.id)

        self.Bind(RB.EVT_RIBBONBUTTONBAR_CLICKED, self.result_panel.model_list.on_show_diff_vscode, Button.DIFF_VSCODE.id)
        self.Bind(RB.EVT_RIBBONBUTTONBAR_CLICKED, self.result_panel.model_list.on_show_difference, Button.DIFF.id)
        self.Bind(RB.EVT_RIBBONBUTTONBAR_CLICKED, self.result_panel.model_list.on_show_inline_difference, Button.DIFF_INLINE.id)

        self.Bind(RB.EVT_RIBBONBUTTONBAR_CLICKED, self.result_panel.model_list.on_set_as_updated, Button.SET_AS_UPDATED.id)
        self.Bind(RB.EVT_RIBBONBUTTONBAR_CLICKED, self.result_panel.model_list.on_mark_as_needs_update, Button.SET_AS_NEEDS_UPDATE.id)
        self.Bind(RB.EVT_RIBBONBUTTONBAR_CLICKED, self.result_panel.model_list.on_poke_entries, Button.POKE.id)

        self.Bind(RB.EVT_RIBBONBUTTONBAR_CLICKED, self.result_panel.model_list.on_copy_conversion_command, Button.COPY_COMMAND.id)
        self.Bind(RB.EVT_RIBBONBUTTONBAR_CLICKED, self.result_panel.model_list.on_copy_folder_basename, Button.COPY_FOLDER_BASENAME.id)
        self.Bind(RB.EVT_RIBBONBUTTONBAR_CLICKED, self.result_panel.model_list.on_copy_blend_path, Button.COPY_SOURCE_PATH.id)

        self.Bind(RB.EVT_RIBBONBUTTONBAR_CLICKED, self.on_print_layout, Button.LAYOUT_PRINT.id)
        self.Bind(RB.EVT_RIBBONBUTTONBAR_CLICKED, self.on_restore_default_layout, Button.LAYOUT_RESTORE.id)

        self.Bind(RB.EVT_RIBBONBUTTONBAR_CLICKED, self.on_show_console_on_top, Button.CONSOLE_SHOW_ON_TOP.id)
        if not utils.Console_Shown.get_is_using_terminal():
            self.Bind(RB.EVT_RIBBONBUTTONBAR_CLICKED, self.on_toggle_console, Button.CONSOLE_TOGGLE.id)


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
        utils.os_show(utils.deduplicate(utils.deduplicate(e.module_file_path for e in self.updater.entries)))


    def on_open_VSCode_workspace(self, event = None):

        folders = utils.deduplicate(os.path.dirname(e.module_file_path) for e in self.updater.entries)

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
        self.updater.despatch()


    def on_pause(self, event):
        self.pause(True)


    def on_resume(self, event):
        self.pause(False)


    def on_mark_update_all(self, event):

        for entry in self.updater.entries:
            entry.status = updater.Status.STALE

        self.updater.despatch()
        updater.update_ui()


    def on_terminate_and_pause(self, event):

        self.pause(True)

        for entry in self.updater.entries:
            entry.is_manual_update = False
            entry.terminate()


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
            utils.get_command_from_list(argv),  # https://github.com/python/cpython/issues/64650
            utils.get_command_from_list(['__restart__', json.dumps(restart_info)]),
        ]

        self.show_console(True)

        os.execv(sys.executable, command)


    def on_settings(self, event):

        settings = {
            'double_click_action': (
                {
                    'show_source_in_explorer': self.result_panel.model_list.show_source_in_explorer,
                    'open_source': self.result_panel.model_list.open_source,
                    'show_result_in_explorer': self.result_panel.model_list.show_result_in_explorer,
                    'open_result': self.result_panel.model_list.open_result,
                    'nothing': self.result_panel.model_list.empty_double_click_function,
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
