import sys

from .gui import updater_ui
app = updater_ui.Main_Frame.get_app([*sys.argv[1:3]])
app.MainLoop()
