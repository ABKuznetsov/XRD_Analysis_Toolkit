function Get-ShowcaseSeenMarkerPath {
    param([string]$Version)
    $folder = Join-Path $env:LOCALAPPDATA "Sci\XRD_Finder"
    return (Join-Path $folder "showcase-$Version.seen")
}

function Test-ShowcaseSeen {
    param([string]$Version)
    return (Test-Path -LiteralPath (Get-ShowcaseSeenMarkerPath $Version))
}

function Save-ShowcaseSeenMarker {
    param([string]$Version)
    $path = Get-ShowcaseSeenMarkerPath $Version
    $folder = Split-Path -Parent $path
    if (-not (Test-Path -LiteralPath $folder)) {
        New-Item -ItemType Directory -Path $folder -Force | Out-Null
    }
    [DateTime]::UtcNow.ToString("o") | Set-Content -LiteralPath $path -Encoding UTF8
}

function Load-ShowcaseCards {
    param([string]$AssetRoot)
    $manifest = Join-Path $AssetRoot "showcase.json"
    if (-not (Test-Path -LiteralPath $manifest)) {
        throw "Showcase manifest is missing: $manifest"
    }
    return @((Get-Content -LiteralPath $manifest -Raw -Encoding UTF8 | ConvertFrom-Json))
}

function Set-ShowcaseCard {
    param([int]$Index)
    if (-not $script:Showcase -or $script:Showcase.Cards.Count -eq 0) { return }
    $count = $script:Showcase.Cards.Count
    $script:Showcase.Index = (($Index % $count) + $count) % $count
    $card = $script:Showcase.Cards[$script:Showcase.Index]
    $script:Showcase.Title.Text = [string]$card.title
    $script:Showcase.Description.Text = [string]$card.description
    $script:Showcase.Notice.Text = [string]$card.notice
    $script:Showcase.Notice.Visible = -not [string]::IsNullOrWhiteSpace([string]$card.notice)
    $script:Showcase.Counter.Text = "{0}  /  {1}" -f ($script:Showcase.Index + 1), $count

    $imagePath = Join-Path $script:Showcase.AssetRoot ([string]$card.image)
    if ($script:Showcase.Picture.Image) {
        $oldImage = $script:Showcase.Picture.Image
        $script:Showcase.Picture.Image = $null
        $oldImage.Dispose()
    }
    if (Test-Path -LiteralPath $imagePath) {
        $bytes = [System.IO.File]::ReadAllBytes($imagePath)
        $stream = New-Object System.IO.MemoryStream(,$bytes)
        try {
            $source = [System.Drawing.Image]::FromStream($stream)
            $script:Showcase.Picture.Image = New-Object System.Drawing.Bitmap($source)
            $source.Dispose()
        } finally {
            $stream.Dispose()
        }
    }
}

function Show-PreviousShowcaseCard {
    Set-ShowcaseCard ($script:Showcase.Index - 1)
}

function Show-NextShowcaseCard {
    Set-ShowcaseCard ($script:Showcase.Index + 1)
}

function Set-ShowcaseMode {
    param([ValidateSet("Installing", "Ready")][string]$Mode)
    if (-not $script:Showcase) { return }
    $script:Showcase.Mode = $Mode
    $script:Showcase.Skip.Visible = ($Mode -eq "Ready")
    if ($Mode -eq "Installing") {
        $script:Showcase.ProgressTitle.Visible = $true
        $script:Showcase.Progress.Visible = $true
        $script:Showcase.Primary.Text = "Установка выполняется..."
        $script:Showcase.Primary.Enabled = $false
    } else {
        $script:Showcase.ProgressTitle.Visible = $false
        $script:Showcase.Progress.Visible = $false
        $script:Showcase.Primary.Text = "Продолжить"
        $script:Showcase.Primary.Enabled = $true
    }
}

function Set-ShowcaseInstallationComplete {
    if (-not $script:Showcase) { return }
    $script:Showcase.InstallationComplete = $true
    $script:Showcase.Primary.Text = "Запустить XRD Phase Finder"
    $script:Showcase.Primary.Enabled = $true
}

function Initialize-FirstRunShowcase {
    param(
        [System.Windows.Forms.Form]$Owner,
        [string]$AssetRoot,
        [string]$Version,
        [ValidateSet("Installing", "Ready")][string]$Mode = "Ready"
    )
    Dispose-FirstRunShowcase
    $cards = Load-ShowcaseCards $AssetRoot
    $dialog = New-Object System.Windows.Forms.Form
    $dialog.Text = "Добро пожаловать в XRD Phase Finder $Version"
    $dialog.StartPosition = [System.Windows.Forms.FormStartPosition]::CenterScreen
    $dialog.FormBorderStyle = [System.Windows.Forms.FormBorderStyle]::FixedDialog
    $dialog.MaximizeBox = $false
    $dialog.MinimizeBox = $false
    $dialog.ClientSize = New-Object System.Drawing.Size(1040, 650)
    $dialog.BackColor = [System.Drawing.Color]::FromArgb(245, 247, 250)
    $dialog.ShowInTaskbar = $true
    $dialog.TopMost = $true

    $picture = New-Object System.Windows.Forms.PictureBox
    $picture.Location = New-Object System.Drawing.Point(28, 28)
    $picture.Size = New-Object System.Drawing.Size(640, 475)
    $picture.SizeMode = [System.Windows.Forms.PictureBoxSizeMode]::Zoom
    $picture.BackColor = [System.Drawing.Color]::White
    $picture.BorderStyle = [System.Windows.Forms.BorderStyle]::FixedSingle
    $dialog.Controls.Add($picture)

    $eyebrow = New-Object System.Windows.Forms.Label
    $eyebrow.Location = New-Object System.Drawing.Point(704, 36)
    $eyebrow.Size = New-Object System.Drawing.Size(300, 24)
    $eyebrow.Text = "ВОЗМОЖНОСТИ XRD PHASE FINDER"
    $eyebrow.Font = New-Object System.Drawing.Font("Segoe UI", 9, [System.Drawing.FontStyle]::Bold)
    $eyebrow.ForeColor = [System.Drawing.Color]::FromArgb(37, 99, 235)
    $dialog.Controls.Add($eyebrow)

    $title = New-Object System.Windows.Forms.Label
    $title.Location = New-Object System.Drawing.Point(700, 72)
    $title.Size = New-Object System.Drawing.Size(305, 55)
    $title.Font = New-Object System.Drawing.Font("Segoe UI", 24, [System.Drawing.FontStyle]::Bold)
    $title.ForeColor = [System.Drawing.Color]::FromArgb(17, 24, 39)
    $dialog.Controls.Add($title)

    $description = New-Object System.Windows.Forms.Label
    $description.Location = New-Object System.Drawing.Point(704, 137)
    $description.Size = New-Object System.Drawing.Size(300, 100)
    $description.Font = New-Object System.Drawing.Font("Segoe UI", 11)
    $description.ForeColor = [System.Drawing.Color]::FromArgb(55, 65, 81)
    $dialog.Controls.Add($description)

    $notice = New-Object System.Windows.Forms.Label
    $notice.Location = New-Object System.Drawing.Point(704, 253)
    $notice.Size = New-Object System.Drawing.Size(300, 133)
    $notice.Padding = New-Object System.Windows.Forms.Padding(12)
    $notice.Font = New-Object System.Drawing.Font("Segoe UI", 9)
    $notice.BackColor = [System.Drawing.Color]::FromArgb(255, 247, 220)
    $notice.ForeColor = [System.Drawing.Color]::FromArgb(120, 75, 0)
    $dialog.Controls.Add($notice)

    $previous = New-Object System.Windows.Forms.Button
    $previous.Text = "<"
    $previous.Location = New-Object System.Drawing.Point(28, 526)
    $previous.Size = New-Object System.Drawing.Size(48, 38)
    $previous.Add_Click({ Show-PreviousShowcaseCard })
    $dialog.Controls.Add($previous)

    $next = New-Object System.Windows.Forms.Button
    $next.Text = ">"
    $next.Location = New-Object System.Drawing.Point(620, 526)
    $next.Size = New-Object System.Drawing.Size(48, 38)
    $next.Add_Click({ Show-NextShowcaseCard })
    $dialog.Controls.Add($next)

    $counter = New-Object System.Windows.Forms.Label
    $counter.Location = New-Object System.Drawing.Point(270, 531)
    $counter.Size = New-Object System.Drawing.Size(160, 28)
    $counter.TextAlign = [System.Drawing.ContentAlignment]::MiddleCenter
    $counter.Font = New-Object System.Drawing.Font("Segoe UI", 10, [System.Drawing.FontStyle]::Bold)
    $dialog.Controls.Add($counter)

    $progressTitle = New-Object System.Windows.Forms.Label
    $progressTitle.Location = New-Object System.Drawing.Point(28, 585)
    $progressTitle.Size = New-Object System.Drawing.Size(640, 23)
    $progressTitle.Text = "Подготовка научного окружения"
    $progressTitle.Font = New-Object System.Drawing.Font("Segoe UI", 9, [System.Drawing.FontStyle]::Bold)
    $dialog.Controls.Add($progressTitle)

    $progress = New-Object System.Windows.Forms.ProgressBar
    $progress.Location = New-Object System.Drawing.Point(28, 612)
    $progress.Size = New-Object System.Drawing.Size(640, 16)
    $progress.Style = [System.Windows.Forms.ProgressBarStyle]::Marquee
    $dialog.Controls.Add($progress)

    $primary = New-Object System.Windows.Forms.Button
    $primary.Location = New-Object System.Drawing.Point(704, 536)
    $primary.Size = New-Object System.Drawing.Size(300, 42)
    $primary.BackColor = [System.Drawing.Color]::FromArgb(37, 99, 235)
    $primary.ForeColor = [System.Drawing.Color]::White
    $primary.FlatStyle = [System.Windows.Forms.FlatStyle]::Flat
    $primary.Font = New-Object System.Drawing.Font("Segoe UI", 10, [System.Drawing.FontStyle]::Bold)
    $primary.Add_Click({
        if ($script:Showcase.Mode -eq "Ready" -or $script:Showcase.InstallationComplete) {
            Save-ShowcaseSeenMarker $script:Showcase.Version
        }
        $script:Showcase.ContinueRequested = $true
        $script:Showcase.Dialog.Close()
    })
    $dialog.Controls.Add($primary)

    $skip = New-Object System.Windows.Forms.Button
    $skip.Text = "Пропустить знакомство"
    $skip.Location = New-Object System.Drawing.Point(704, 588)
    $skip.Size = New-Object System.Drawing.Size(300, 34)
    $skip.Add_Click({ Save-ShowcaseSeenMarker $script:Showcase.Version; $script:Showcase.ContinueRequested = $true; $script:Showcase.Dialog.Close() })
    $dialog.Controls.Add($skip)

    $timer = New-Object System.Windows.Forms.Timer
    $timer.Interval = 4500
    $timer.Add_Tick({ Show-NextShowcaseCard })

    $script:Showcase = [pscustomobject]@{
        Dialog = $dialog; Cards = $cards; Index = 0; AssetRoot = $AssetRoot; Version = $Version
        Picture = $picture; Title = $title; Description = $description; Notice = $notice; Counter = $counter
        Previous = $previous; Next = $next; Skip = $skip; Primary = $primary; Timer = $timer; Progress = $progress
        ProgressTitle = $progressTitle; Mode = $Mode; InstallationComplete = $false; ContinueRequested = $false
    }
    $dialog.Add_FormClosing({
        param($sender, $eventArgs)
        if ($script:Showcase.Mode -eq "Installing" -and -not $script:Showcase.InstallationComplete) {
            $eventArgs.Cancel = $true
        } elseif ($script:Showcase.Mode -eq "Ready" -and -not $script:Showcase.ContinueRequested) {
            Save-ShowcaseSeenMarker $script:Showcase.Version
        }
    })
    Set-ShowcaseMode $Mode
    Set-ShowcaseCard 0
    $timer.Start()
    return $script:Showcase
}

function Set-ShowcaseProgressText {
    param([string]$Text)
    if ($script:Showcase) { $script:Showcase.ProgressTitle.Text = $Text }
}

function Set-ShowcaseProgress {
    param(
        [string]$Text,
        [int]$Current = 0,
        [int]$Total = 0
    )
    if (-not $script:Showcase) { return }
    $script:Showcase.ProgressTitle.Text = $Text
    if ($Total -gt 0) {
        $script:Showcase.Progress.Style = [System.Windows.Forms.ProgressBarStyle]::Continuous
        $script:Showcase.Progress.Minimum = 0
        $script:Showcase.Progress.Maximum = $Total
        $script:Showcase.Progress.Value = [Math]::Max(0, [Math]::Min($Current, $Total))
    } else {
        $script:Showcase.Progress.Style = [System.Windows.Forms.ProgressBarStyle]::Marquee
    }
}

function Show-FirstRunShowcaseDialog {
    if (-not $script:Showcase) { return $false }
    $script:Showcase.Dialog.ShowDialog() | Out-Null
    return [bool]$script:Showcase.ContinueRequested
}

function Dispose-FirstRunShowcase {
    if (-not $script:Showcase) { return }
    if ($script:Showcase.Timer) { $script:Showcase.Timer.Stop(); $script:Showcase.Timer.Dispose() }
    if ($script:Showcase.Picture -and $script:Showcase.Picture.Image) {
        $script:Showcase.Picture.Image.Dispose()
        $script:Showcase.Picture.Image = $null
    }
    if ($script:Showcase.Dialog) { $script:Showcase.Dialog.Dispose() }
    $script:Showcase = $null
}
