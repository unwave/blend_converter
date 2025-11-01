import sys

from .gui import updater_ui
app = updater_ui.Main_Frame.get_app(files = sys.argv[1:])
app.MainLoop()
