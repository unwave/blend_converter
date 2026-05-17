from . import powershell


_powershell = None

def get_powershell():

    global _powershell

    if _powershell is None:
        _powershell = powershell.PowerShell()

    return _powershell


def get_shortcut_target(path: str):
    return get_powershell().request('Get-LnkTarget', path = path)['result']['path']


def create_shortcut(name: str, target_path: str, arguments: str, working_directory: str):
    return get_powershell().request(
        'Create-ShortCut',
        Name = name,
        TargetPath = target_path,
        Arguments = arguments,
        WorkingDirectory = working_directory,
    )['result']['path']
