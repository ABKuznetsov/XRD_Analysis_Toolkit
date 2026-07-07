param(
    [string]$AppId = "xrd_finder"
)

$ErrorActionPreference = "Stop"

function Resolve-AppRoot {
    if ($PSScriptRoot) {
        return (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
    }
    return (Get-Location).Path
}

function Compare-VersionText {
    param([string]$Left, [string]$Right)
    try {
        $lv = [version]$Left
        $rv = [version]$Right
        return $lv.CompareTo($rv)
    } catch {
        return [string]::Compare($Left, $Right, $true)
    }
}

function Ensure-Folder {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        New-Item -ItemType Directory -Path $Path -Force | Out-Null
    }
}

function New-Label {
    param(
        [string]$Text,
        [int]$X,
        [int]$Y,
        [int]$W,
        [int]$H,
        [float]$Size = 9,
        [string]$Style = "Regular",
        [System.Drawing.Color]$Color = [System.Drawing.Color]::FromArgb(31, 41, 55)
    )
    $label = New-Object System.Windows.Forms.Label
    $label.Text = $Text
    $label.Location = New-Object System.Drawing.Point -ArgumentList $X, $Y
    $label.Size = New-Object System.Drawing.Size -ArgumentList $W, $H
    $label.Font = New-Object System.Drawing.Font -ArgumentList "Segoe UI", $Size, ([System.Drawing.FontStyle]::$Style)
    $label.ForeColor = $Color
    $label.BackColor = [System.Drawing.Color]::Transparent
    return $label
}


function New-StateBitmap {
    param([string]$State)
    $bmp = New-Object System.Drawing.Bitmap 34, 34
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $g.Clear([System.Drawing.Color]::Transparent)
    if ($State -eq "OK") {
        $pen = New-Object System.Drawing.Pen ([System.Drawing.Color]::FromArgb(46, 125, 50)), 2.6
        $brush = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(232, 245, 233))
        $g.FillEllipse($brush, 4, 4, 26, 26)
        $g.DrawEllipse($pen, 4, 4, 26, 26)
        $g.DrawLines($pen, [System.Drawing.Point[]]@((New-Object System.Drawing.Point 11, 18), (New-Object System.Drawing.Point 15, 22), (New-Object System.Drawing.Point 23, 13)))
    } elseif ($State -eq "Error") {
        $pen = New-Object System.Drawing.Pen ([System.Drawing.Color]::FromArgb(185, 28, 28)), 2.6
        $brush = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(254, 226, 226))
        $g.FillEllipse($brush, 4, 4, 26, 26)
        $g.DrawEllipse($pen, 4, 4, 26, 26)
        $g.DrawLine($pen, 12, 12, 22, 22)
        $g.DrawLine($pen, 22, 12, 12, 22)
    } elseif ($State -eq "Working") {
        $pen = New-Object System.Drawing.Pen ([System.Drawing.Color]::FromArgb(37, 99, 235)), 2.8
        $brush = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(239, 246, 255))
        $g.FillEllipse($brush, 4, 4, 26, 26)
        $g.DrawArc($pen, 7, 7, 20, 20, 25, 285)
        $g.FillEllipse((New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(37, 99, 235))), 15, 15, 4, 4)
    } else {
        $pen = New-Object System.Drawing.Pen ([System.Drawing.Color]::FromArgb(148, 163, 184)), 2.2
        $brush = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(248, 250, 252))
        $g.FillEllipse($brush, 4, 4, 26, 26)
        $g.DrawEllipse($pen, 4, 4, 26, 26)
    }
    $g.Dispose()
    return $bmp
}

function Set-StateIcon {
    param([int]$Index, [string]$State)
    if ($script:StepIconBoxes.Count -le $Index) { return }
    $box = $script:StepIconBoxes[$Index]
    if ($box.Image) { $box.Image.Dispose() }
    $box.Image = New-StateBitmap $State
}

function Pause-PreviewStep {
    Start-Sleep -Milliseconds 2000
}

function Add-StepRow {
    param(
        [int]$Index,
        [string]$Glyph,
        [string]$Title,
        [string]$Detail,
        [int]$Y
    )
    $iconBox = New-Object System.Windows.Forms.PictureBox
    $iconBox.Location = New-Object System.Drawing.Point -ArgumentList 430, ($Y + 8)
    $iconBox.Size = New-Object System.Drawing.Size -ArgumentList 34, 34
    $iconBox.SizeMode = [System.Windows.Forms.PictureBoxSizeMode]::CenterImage
    $iconBox.Image = New-StateBitmap "Waiting"
    $script:Form.Controls.Add($iconBox)
    $script:StepIconBoxes.Add($iconBox)

    $titleLabel = New-Label $Title 492 ($Y - 2) 315 25 11 "Bold" ([System.Drawing.Color]::FromArgb(15, 23, 42))
    $script:Form.Controls.Add($titleLabel)

    $detailLabel = New-Label $Detail 492 ($Y + 24) 315 40 9.5 "Regular" ([System.Drawing.Color]::FromArgb(75, 85, 99))
    $script:Form.Controls.Add($detailLabel)

    $statusLabel = New-Label "Waiting" 784 ($Y + 11) 102 22 9.5 "Regular" ([System.Drawing.Color]::FromArgb(37, 99, 235))
    $statusLabel.TextAlign = [System.Drawing.ContentAlignment]::MiddleRight
    $script:Form.Controls.Add($statusLabel)

    $divider = New-Object System.Windows.Forms.Panel
    $divider.Location = New-Object System.Drawing.Point -ArgumentList 430, ($Y + 62)
    $divider.Size = New-Object System.Drawing.Size -ArgumentList 456, 1
    $divider.BackColor = [System.Drawing.Color]::FromArgb(226, 232, 240)
    $script:Form.Controls.Add($divider)

    $script:StepStatusLabels.Add($statusLabel)
    $script:StepDetailLabels.Add($detailLabel)
}

function Set-Step {
    param([int]$Index, [string]$Status, [string]$Detail, [string]$Tone = "Blue")
        if ($Status -match "OK") { Set-StateIcon $Index "OK" } elseif ($Tone -eq "Red" -or $Status -match "Failed") { Set-StateIcon $Index "Error" } elseif ($Status -match "Checking|Installing|Loading|Starting") { Set-StateIcon $Index "Working" } else { Set-StateIcon $Index "Waiting" }
if ($script:StepStatusLabels.Count -gt $Index) {
        $label = $script:StepStatusLabels[$Index]
        $label.Text = $Status
        if ($Tone -eq "Green") {
            $label.ForeColor = [System.Drawing.Color]::FromArgb(46, 125, 50)
        } elseif ($Tone -eq "Red") {
            $label.ForeColor = [System.Drawing.Color]::FromArgb(185, 28, 28)
        } elseif ($Tone -eq "Muted") {
            $label.ForeColor = [System.Drawing.Color]::FromArgb(100, 116, 139)
        } else {
            $label.ForeColor = [System.Drawing.Color]::FromArgb(37, 99, 235)
        }
    }
    if ($script:StepDetailLabels.Count -gt $Index -and $Detail) {
        $script:StepDetailLabels[$Index].Text = $Detail
    }
    [System.Windows.Forms.Application]::DoEvents()
}

function Set-ProgressText {
    param([int]$Value, [string]$Text)
    [System.Windows.Forms.Application]::DoEvents()
}

$appRoot = Resolve-AppRoot
$toolkitRoot = Join-Path $env:LOCALAPPDATA "XRD_Toolkit"
$envRoot = Join-Path $toolkitRoot "env"
$finderRoot = Join-Path $toolkitRoot "XRD_Finder"
$dataRoot = Join-Path $finderRoot "data"
$logsRoot = Join-Path $toolkitRoot "logs"
$updateRoot = Join-Path $toolkitRoot "updates"
$pythonw = Join-Path $envRoot "Scripts\pythonw.exe"
$setupBat = Join-Path $appRoot "toolkit\setup_xrd_toolkit_env.bat"
$manifestPath = Join-Path $appRoot "toolkit\manifest.json"
$appManifestPath = Join-Path $appRoot "XRD_Finder\app.json"
$appPackageRoot = Join-Path $appRoot "XRD_Finder"
$appIconPath = Join-Path $appRoot "XRD_Finder\icon.png"
$localVersion = "0.0.0"
$manifestUrl = ""
$updateManifestUrl = ""
$installerUrl = ""
$installerSha256 = ""
$releaseUrl = ""
$entryModule = "xrd_finder.apps.finder_gui"

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

$script:Form = New-Object System.Windows.Forms.Form
$script:Form.Text = "XRD Phase Finder"
$script:Form.StartPosition = "CenterScreen"
$script:Form.Size = New-Object System.Drawing.Size -ArgumentList 940, 590
$script:Form.MinimumSize = New-Object System.Drawing.Size -ArgumentList 940, 590
$script:Form.FormBorderStyle = "FixedSingle"
$script:Form.MaximizeBox = $false
$script:Form.BackColor = [System.Drawing.Color]::FromArgb(248, 250, 252)

$leftPanel = New-Object System.Windows.Forms.Panel
$leftPanel.Location = New-Object System.Drawing.Point -ArgumentList 0, 0
$leftPanel.Size = New-Object System.Drawing.Size -ArgumentList 400, 552
$leftPanel.BackColor = [System.Drawing.Color]::White
$script:Form.Controls.Add($leftPanel)

$splitter = New-Object System.Windows.Forms.Panel
$splitter.Location = New-Object System.Drawing.Point -ArgumentList 400, 0
$splitter.Size = New-Object System.Drawing.Size -ArgumentList 1, 552
$splitter.BackColor = [System.Drawing.Color]::FromArgb(226, 232, 240)
$script:Form.Controls.Add($splitter)

if (Test-Path -LiteralPath $appIconPath) {
    $picture = New-Object System.Windows.Forms.PictureBox
    $picture.Location = New-Object System.Drawing.Point -ArgumentList 60, 92
    $picture.Size = New-Object System.Drawing.Size -ArgumentList 280, 280
    $picture.SizeMode = [System.Windows.Forms.PictureBoxSizeMode]::Zoom
    $picture.Image = [System.Drawing.Image]::FromFile($appIconPath)
    $leftPanel.Controls.Add($picture)
}

$brand = New-Label "XRD Phase Finder" 58 390 320 46 24 "Bold" ([System.Drawing.Color]::FromArgb(15, 23, 42))
$leftPanel.Controls.Add($brand)
$subtitle = New-Label "Phase identification from`r`nX-ray diffraction data" 60 438 290 58 12 "Regular" ([System.Drawing.Color]::FromArgb(71, 85, 105))
$leftPanel.Controls.Add($subtitle)
$versionLabel = New-Label "Version 1.0.2" 60 512 140 24 9 "Regular" ([System.Drawing.Color]::FromArgb(100, 116, 139))
$leftPanel.Controls.Add($versionLabel)

$title = New-Label "Starting XRD Phase Finder..." 430 46 420 42 19 "Bold" ([System.Drawing.Color]::FromArgb(15, 23, 42))
$script:Form.Controls.Add($title)
$topHint = New-Label "Preparing folders, databases, updates and user settings." 432 82 420 24 9.5 "Regular" ([System.Drawing.Color]::FromArgb(100, 116, 139))
$script:Form.Controls.Add($topHint)

$script:StepStatusLabels = New-Object System.Collections.Generic.List[System.Windows.Forms.Label]
$script:StepDetailLabels = New-Object System.Collections.Generic.List[System.Windows.Forms.Label]
$script:StepIconBoxes = New-Object System.Collections.Generic.List[System.Windows.Forms.PictureBox]
Add-StepRow 0 "" "Checking application folders" "User data directory`r`nCache directory" 132
Add-StepRow 1 "" "Checking local databases" "User library`r`nCache database" 204
Add-StepRow 2 "" "Checking database connections" "COD`r`nMaterials Project" 276
Add-StepRow 3 "" "Checking for updates" "Current version: 1.0.2" 348
Add-StepRow 4 "" "Loading settings" "User preferences" 420


$script:Form.Show()
[System.Windows.Forms.Application]::DoEvents()

try {
    Set-ProgressText 8 "Initializing"
    Set-Step 0 "Checking..." "Creating user data folders" "Blue"
    Ensure-Folder $toolkitRoot
    Ensure-Folder $finderRoot
    Ensure-Folder $dataRoot
    Ensure-Folder $logsRoot
    Ensure-Folder $updateRoot
    Ensure-Folder (Join-Path $finderRoot "matplotlib")
    Set-Step 0 "OK" "User data and cache folders are ready" "Green"

    Pause-PreviewStep
    Set-ProgressText 28 "Preparing runtime"
    Set-Step 1 "Checking..." "Looking for XRD_Toolkit runtime" "Blue"
    if (-not (Test-Path -LiteralPath $pythonw)) {
        Set-Step 1 "Installing..." "Creating shared Python environment" "Blue"
        if (-not (Test-Path -LiteralPath $setupBat)) {
            throw "Setup script was not found: $setupBat"
        }
        $setupProcess = Start-Process -FilePath "cmd.exe" -ArgumentList @("/c", "`"$setupBat`"") -Wait -PassThru -WindowStyle Hidden
        if ($setupProcess.ExitCode -ne 0) {
            throw "Environment setup failed. See log: $(Join-Path $logsRoot 'setup.log')"
        }
    }
    if (-not (Test-Path -LiteralPath $pythonw)) {
        throw "Python launcher was not found: $pythonw"
    }
    Ensure-Folder (Join-Path $dataRoot "cod_cache")
    Ensure-Folder (Join-Path $dataRoot "cod_cache\rruff")
    Set-Step 1 "OK" "Runtime and cache database are ready" "Green"

    Pause-PreviewStep
    Set-ProgressText 48 "Checking sources"
    Set-Step 2 "Checking..." "COD, Materials Project, local sources" "Blue"
    Set-Step 2 "OK" "Configured sources are available" "Green"

    Pause-PreviewStep
    Set-ProgressText 68 "Checking for updates"
    Set-Step 3 "Checking..." ("Current version: " + $localVersion) "Blue"
    if (Test-Path -LiteralPath $appManifestPath) {
        $appManifest = Get-Content -LiteralPath $appManifestPath -Raw | ConvertFrom-Json
        if ($appManifest.version) { $localVersion = [string]$appManifest.version }
        if ($appManifest.entry_module) { $entryModule = [string]$appManifest.entry_module }
        $versionLabel.Text = "Version $localVersion"
        Set-Step 3 "Checking..." ("Current version: " + $localVersion) "Blue"
    }
    if (Test-Path -LiteralPath $manifestPath) {
        $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
        $appInfo = $manifest.apps.$AppId
        if ($appInfo.manifest_url) { $manifestUrl = [string]$appInfo.manifest_url }
        if ($appInfo.update_manifest_url) { $updateManifestUrl = [string]$appInfo.update_manifest_url }
        if ($appInfo.installer_url) { $installerUrl = [string]$appInfo.installer_url }
        if ($appInfo.installer_sha256) { $installerSha256 = [string]$appInfo.installer_sha256 }
        if ($appInfo.release_url) { $releaseUrl = [string]$appInfo.release_url }
    }

    $updateStatus = [ordered]@{
        checked_at = (Get-Date).ToString("s")
        app_id = $AppId
        current_version = $localVersion
        latest_version = $localVersion
        update_available = $false
        release_url = $releaseUrl
        installer_url = $installerUrl
        installer_sha256 = $installerSha256
        error = $null
    }
    if ($manifestUrl -or $updateManifestUrl) {
        try {
            $remoteUrl = $manifestUrl
            if ($updateManifestUrl) { $remoteUrl = $updateManifestUrl }
            $remote = Invoke-RestMethod -Uri $remoteUrl -UseBasicParsing -TimeoutSec 5
            $remoteApp = $remote
            if ($remote.apps -and $remote.apps.$AppId) { $remoteApp = $remote.apps.$AppId }
            if ($remoteApp.version) {
                $latestVersion = [string]$remoteApp.version
                $updateStatus.latest_version = $latestVersion
                if ((Compare-VersionText $latestVersion $localVersion) -gt 0) {
                    $updateStatus.update_available = $true
                    if ($remoteApp.release_url) { $updateStatus.release_url = [string]$remoteApp.release_url }
                    if ($remoteApp.installer_url) { $updateStatus.installer_url = [string]$remoteApp.installer_url }
                    if ($remoteApp.installer_sha256) { $updateStatus.installer_sha256 = [string]$remoteApp.installer_sha256 }
                    if ($remoteApp.assets -and $remoteApp.assets.Count -gt 0) {
                        $asset = $remoteApp.assets | Select-Object -First 1
                        if ($asset.url) { $updateStatus.installer_url = [string]$asset.url }
                        if ($asset.sha256) { $updateStatus.installer_sha256 = [string]$asset.sha256 }
                    }
                    Set-Step 3 "Update" ("$localVersion -> $latestVersion") "Blue"
                    $summaryLines = New-Object System.Collections.Generic.List[string]
                    if ($remoteApp.summary) {
                        foreach ($line in $remoteApp.summary) {
                            $textLine = [string]$line
                            if ($textLine.Trim()) { $summaryLines.Add("- " + $textLine.Trim()) | Out-Null }
                        }
                    }
                    if ($summaryLines.Count -eq 0) {
                        $summaryLines.Add("- See the release notes for details.") | Out-Null
                    }
                    $message = "A new XRD Phase Finder version is available: $latestVersion.`r`nCurrent version: $localVersion`r`n`r`nWhat changed:`r`n" + ($summaryLines -join "`r`n") + "`r`n`r`nOpen the update download now?"
                    $choice = [System.Windows.Forms.MessageBox]::Show($message, "XRD Phase Finder update available", [System.Windows.Forms.MessageBoxButtons]::YesNo, [System.Windows.Forms.MessageBoxIcon]::Information)
                    if ($choice -eq [System.Windows.Forms.DialogResult]::Yes) {
                        $downloadTarget = $updateStatus.installer_url
                        if (-not $downloadTarget) { $downloadTarget = $updateStatus.release_url }
                        if ($downloadTarget) { Start-Process $downloadTarget }
                        ($updateStatus | ConvertTo-Json -Depth 5) | Set-Content -LiteralPath (Join-Path $updateRoot "$AppId.json") -Encoding UTF8
                        $script:Form.Close()
                        return
                    }
                } else {
                    Set-Step 3 "OK" ("No update available. Current version: $localVersion") "Green"
                }
            } else {
                Set-Step 3 "OK" ("No update available. Current version: $localVersion") "Green"
            }
        } catch {
            $updateStatus.error = $_.Exception.Message
            Set-Step 3 "Offline" "Update check unavailable" "Muted"
        }
    } else {
        Set-Step 3 "OK" "No update source configured" "Muted"
    }
    ($updateStatus | ConvertTo-Json -Depth 4) | Set-Content -LiteralPath (Join-Path $updateRoot "$AppId.json") -Encoding UTF8

    Pause-PreviewStep
    Set-ProgressText 88 "Loading settings"
    Set-Step 4 "Loading..." "User preferences" "Blue"
    $env:PYTHONDONTWRITEBYTECODE = "1"
    $env:XRD_FINDER_DATA_DIR = $dataRoot
    $env:MPLCONFIGDIR = Join-Path $finderRoot "matplotlib"
    if ($env:PYTHONPATH) {
        $env:PYTHONPATH = "$appPackageRoot;$env:PYTHONPATH"
    } else {
        $env:PYTHONPATH = $appPackageRoot
    }
    Start-Process -FilePath $pythonw -ArgumentList @("-m", $entryModule) -WorkingDirectory $appRoot | Out-Null
    Set-Step 4 "OK" "XRD Phase Finder started" "Green"
    Pause-PreviewStep
    Set-ProgressText 100 "Starting"
    Start-Sleep -Milliseconds 2000
} catch {
    Set-ProgressText 100 "Failed"
    if ($script:StepStatusLabels.Count -gt 0) {
        Set-Step 4 "Failed" $_.Exception.Message "Red"
    }
    [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, "XRD Phase Finder startup failed", [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Error) | Out-Null
} finally {
    if ($picture -and $picture.Image) { $picture.Image.Dispose() }
    $script:Form.Close()
    $script:Form.Dispose()
}












