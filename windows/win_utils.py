from . import powershell


_powershell = None

def get_powershell():

    global _powershell

    if _powershell is None:
        _powershell = powershell.PowerShell()

    return _powershell


def get_shortcut_target(path: str):
    return get_powershell().request('Get-LnkTarget', path = path)['result']['path']
