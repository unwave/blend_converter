[Console]::Error.WriteLine("Hello from PowerShell")


$script:script_shell = New-Object -ComObject WScript.Shell
$script:shell_application = New-Object -ComObject Shell.Application


function Get-LnkTarget([PSCustomObject]$arguments) {

    try {
        $path = $script:script_shell.CreateShortcut($arguments.path).TargetPath
    } catch {
        $path = ""
    }

    return @{ path = $path }
}


function Create-ShortCut([PSCustomObject]$arguments) {

    $desktop = [Environment]::GetFolderPath('Desktop')
    $name = $arguments.Name + ".lnk"
    $shortcut_path = Join-Path -Path $desktop -ChildPath $name

    $script_shell.CreateShortcut($shortcut_path).Save()

    $name_space = $script:shell_application.NameSpace($desktop)
    $shortcut = $name_space.ParseName($name).GetLink

    $shortcut.Path = $arguments.TargetPath
    $shortcut.Arguments = $arguments.Arguments
    $shortcut.WorkingDirectory = $arguments.WorkingDirectory

    $shortcut.Save()

    return @{ path = $shortcut_path }
}


:mainLoop while ($true) {

    $raw_request = [Console]::ReadLine()

    if ([string]::IsNullOrWhiteSpace($raw_request)) {
        continue
    }

    $request =  $raw_request | ConvertFrom-Json

    $response = @{ status = "error"; result = @{ message = $null } }

    switch ($request.command)
    {
        'Exit' {
            break :mainLoop
        }

        'Get-LnkTarget' {
            $response = @{ status = "ok"; result = Get-LnkTarget $request.arguments }
        }

        'Create-ShortCut' {
            $response = @{ status = "ok"; result = Create-ShortCut $request.arguments }
        }

        Default {
            $response = @{ status = "error"; result = @{ message = "Unknown command" } }
        }
    }

    $raw_response = $response | ConvertTo-Json -Compress

    [Console]::Out.WriteLine($raw_response)
}
