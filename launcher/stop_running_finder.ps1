param()

$patterns = @(
    @{ Name = 'python.exe'; Command = 'xrd_finder.apps.finder_gui' },
    @{ Name = 'pythonw.exe'; Command = 'xrd_finder.apps.finder_gui' },
    @{ Name = 'powershell.exe'; Command = 'launch_xrd_finder_preview.ps1' },
    @{ Name = 'pwsh.exe'; Command = 'launch_xrd_finder_preview.ps1' }
)

try {
    $currentPid = $PID
    Get-CimInstance Win32_Process | ForEach-Object {
        $processName = [string]$_.Name
        $commandLine = [string]$_.CommandLine
        foreach ($pattern in $patterns) {
            if ($_.ProcessId -ne $currentPid -and $processName -ieq $pattern.Name -and $commandLine -like ('*' + $pattern.Command + '*')) {
                Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
                break
            }
        }
    }
} catch {
}
