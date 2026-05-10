[Console]::Error.WriteLine("Hello from PowerShell")


$script:script_shell = New-Object -ComObject WScript.Shell


function Get-LnkTarget([PSCustomObject]$arguments) {

    try {
        $path = $script:script_shell.CreateShortcut($arguments.path).TargetPath
    } catch {
        $path = ""
    }

    return @{ path = $path }
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

        Default {
            $response = @{ status = "error"; result = @{ message = "Unknown command" } }
        }
    }

    $raw_response = $response | ConvertTo-Json -Compress

    [Console]::Out.WriteLine($raw_response)
}
