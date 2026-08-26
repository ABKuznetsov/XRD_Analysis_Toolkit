param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("xrd_finder", "xrd_craft")]
    [string]$TargetAppId
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$catalogUrl = "https://raw.githubusercontent.com/ABKuznetsov/XRD_Analysis_Toolkit/main/toolkit/catalog.json"

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Net.Http

function Show-TopMostMessageBox {
    param(
        [string]$Text,
        [System.Windows.Forms.MessageBoxButtons]$Buttons,
        [System.Windows.Forms.MessageBoxIcon]$Icon
    )

    $owner = [System.Windows.Forms.Form]::new()
    $owner.Text = "XRD Analysis Toolkit"
    $owner.StartPosition = "CenterScreen"
    $owner.ShowInTaskbar = $false
    $owner.FormBorderStyle = "FixedToolWindow"
    $owner.ClientSize = [System.Drawing.Size]::new(1, 1)
    $owner.Opacity = 0
    $owner.TopMost = $true
    try {
        [void]$owner.Show()
        $owner.BringToFront()
        [void]$owner.Activate()
        [System.Windows.Forms.Application]::DoEvents()
        return [System.Windows.Forms.MessageBox]::Show(
            $owner,
            $Text,
            "XRD Analysis Toolkit",
            $Buttons,
            $Icon
        )
    }
    finally {
        $owner.Close()
        $owner.Dispose()
    }
}

function Show-OptionalInstallerMessage {
    param(
        [string]$Text,
        [System.Windows.Forms.MessageBoxIcon]$Icon = [System.Windows.Forms.MessageBoxIcon]::Information
    )

    [void](Show-TopMostMessageBox -Text $Text -Buttons OK -Icon $Icon)
}

function Get-VerifiedFileHash {
    param([string]$Path)

    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Test-VerifiedInstaller {
    param(
        [string]$Path,
        [long]$ExpectedSize,
        [string]$ExpectedSha256
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return $false
    }

    $item = Get-Item -LiteralPath $Path
    if ($item.Length -ne $ExpectedSize) {
        return $false
    }

    return (Get-VerifiedFileHash -Path $Path) -eq $ExpectedSha256
}

function New-DownloadWindow {
    param([string]$ApplicationName)

    $form = [System.Windows.Forms.Form]::new()
    $form.Text = "XRD Analysis Toolkit"
    $form.StartPosition = "CenterScreen"
    $form.FormBorderStyle = "FixedDialog"
    $form.MaximizeBox = $false
    $form.MinimizeBox = $false
    $form.ClientSize = [System.Drawing.Size]::new(520, 126)
    $form.TopMost = $true

    $label = [System.Windows.Forms.Label]::new()
    $label.AutoSize = $false
    $label.Location = [System.Drawing.Point]::new(20, 18)
    $label.Size = [System.Drawing.Size]::new(480, 44)
    $label.Text = "Downloading the verified $ApplicationName installer...`r`nThe current installation will continue if the download fails."

    $progress = [System.Windows.Forms.ProgressBar]::new()
    $progress.Location = [System.Drawing.Point]::new(20, 78)
    $progress.Size = [System.Drawing.Size]::new(480, 22)
    $progress.Minimum = 0
    $progress.Maximum = 100
    $progress.Style = "Continuous"

    [void]$form.Controls.Add($label)
    [void]$form.Controls.Add($progress)

    return [pscustomobject]@{
        Form = $form
        Progress = $progress
    }
}

function Save-HttpFile {
    param(
        [System.Net.Http.HttpClient]$Client,
        [System.Uri]$Uri,
        [string]$Destination,
        [long]$ExpectedSize,
        [System.Windows.Forms.ProgressBar]$ProgressBar
    )

    $response = $Client.GetAsync(
        $Uri,
        [System.Net.Http.HttpCompletionOption]::ResponseHeadersRead
    ).GetAwaiter().GetResult()
    try {
        $response.EnsureSuccessStatusCode()
        $inputStream = $response.Content.ReadAsStreamAsync().GetAwaiter().GetResult()
        try {
            $outputStream = [System.IO.File]::Open(
                $Destination,
                [System.IO.FileMode]::Create,
                [System.IO.FileAccess]::Write,
                [System.IO.FileShare]::None
            )
            try {
                $buffer = New-Object byte[] 1048576
                [long]$written = 0
                while (($read = $inputStream.Read($buffer, 0, $buffer.Length)) -gt 0) {
                    $outputStream.Write($buffer, 0, $read)
                    $written += $read
                    if ($ExpectedSize -gt 0) {
                        $percent = [Math]::Min(100, [int](100 * $written / $ExpectedSize))
                        $ProgressBar.Value = $percent
                    }
                    [System.Windows.Forms.Application]::DoEvents()
                }
            }
            finally {
                $outputStream.Dispose()
            }
        }
        finally {
            $inputStream.Dispose()
        }
    }
    finally {
        $response.Dispose()
    }
}

$httpClient = $null
$downloadWindow = $null
$partialPath = $null

try {
    [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12
    $handler = [System.Net.Http.HttpClientHandler]::new()
    $handler.AllowAutoRedirect = $true
    $httpClient = [System.Net.Http.HttpClient]::new($handler)
    $httpClient.Timeout = [TimeSpan]::FromMinutes(20)

    $catalogJson = $httpClient.GetStringAsync($catalogUrl).GetAwaiter().GetResult()
    $catalog = $catalogJson | ConvertFrom-Json
    if ([int]$catalog.schema_version -ne 1) {
        throw "Unsupported application catalogue version."
    }

    $application = @($catalog.applications | Where-Object { $_.app_id -eq $TargetAppId })
    if ($application.Count -ne 1) {
        throw "The requested application is missing from the official catalogue."
    }
    $application = $application[0]

    $filename = [string]$application.installer.filename
    $expectedSha256 = ([string]$application.installer.sha256).ToLowerInvariant()
    [long]$expectedSize = $application.installer.size_bytes
    $installerUri = [System.Uri]([string]$application.installer.url)

    if ([System.IO.Path]::GetFileName($filename) -ne $filename -or
        -not $filename.EndsWith(".exe", [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "The catalogue contains an invalid installer filename."
    }
    if ($installerUri.Scheme -ne "https" -or $installerUri.Host -ne "github.com") {
        throw "The catalogue contains an untrusted installer address."
    }
    if ($expectedSize -le 0 -or $expectedSha256 -notmatch '^[0-9a-f]{64}$') {
        throw "The catalogue contains invalid verification metadata."
    }

    $downloadRoot = Join-Path $env:LOCALAPPDATA "Sci\downloads\toolkit\$TargetAppId\$($application.version)"
    [void][System.IO.Directory]::CreateDirectory($downloadRoot)
    $installerPath = Join-Path $downloadRoot $filename
    $partialPath = "$installerPath.part"

    if (-not (Test-VerifiedInstaller -Path $installerPath -ExpectedSize $expectedSize -ExpectedSha256 $expectedSha256)) {
        if (Test-Path -LiteralPath $installerPath) {
            Remove-Item -LiteralPath $installerPath -Force
        }
        if (Test-Path -LiteralPath $partialPath) {
            Remove-Item -LiteralPath $partialPath -Force
        }

        $downloadWindow = New-DownloadWindow -ApplicationName ([string]$application.name)
        [void]$downloadWindow.Form.Show()
        [System.Windows.Forms.Application]::DoEvents()
        Save-HttpFile -Client $httpClient -Uri $installerUri -Destination $partialPath -ExpectedSize $expectedSize -ProgressBar $downloadWindow.Progress

        if (-not (Test-VerifiedInstaller -Path $partialPath -ExpectedSize $expectedSize -ExpectedSha256 $expectedSha256)) {
            throw "The downloaded installer failed size or SHA-256 verification."
        }
        Move-Item -LiteralPath $partialPath -Destination $installerPath -Force
    }

    if ($null -ne $downloadWindow) {
        $downloadWindow.Form.Close()
        $downloadWindow.Form.Dispose()
        $downloadWindow = $null
    }

    $answer = Show-TopMostMessageBox `
        -Text "The verified $($application.name) $($application.version) installer is ready.`r`nInstall it now?" `
        -Buttons YesNo `
        -Icon Question
    if ($answer -eq [System.Windows.Forms.DialogResult]::Yes) {
        $process = Start-Process -FilePath $installerPath -Wait -PassThru
        if ($process.ExitCode -ne 0) {
            Show-OptionalInstallerMessage -Text "$($application.name) setup ended with exit code $($process.ExitCode). The current installation is not affected." -Icon Warning
        }
    }
}
catch {
    if ($null -ne $downloadWindow) {
        $downloadWindow.Form.Close()
        $downloadWindow.Form.Dispose()
        $downloadWindow = $null
    }
    if ($partialPath -and (Test-Path -LiteralPath $partialPath)) {
        Remove-Item -LiteralPath $partialPath -Force -ErrorAction SilentlyContinue
    }
    Show-OptionalInstallerMessage -Text "The optional application could not be downloaded or started.`r`n$($_.Exception.Message)`r`n`r`nThe current installation will continue." -Icon Error
}
finally {
    if ($null -ne $httpClient) {
        $httpClient.Dispose()
    }
}

exit 0
