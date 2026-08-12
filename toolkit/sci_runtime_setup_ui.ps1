function Show-RuntimeConsent {
    param(
        [string]$Detail,
        [string]$EnvironmentPath,
        [string]$LogPath
    )
    $dialog = New-Object System.Windows.Forms.Form
    $dialog.Text = "XRD Phase Finder: научное окружение"
    $dialog.StartPosition = [System.Windows.Forms.FormStartPosition]::CenterScreen
    $dialog.FormBorderStyle = [System.Windows.Forms.FormBorderStyle]::FixedDialog
    $dialog.MaximizeBox = $false
    $dialog.MinimizeBox = $false
    $dialog.ClientSize = New-Object System.Drawing.Size(700, 470)
    $dialog.BackColor = [System.Drawing.Color]::White
    $dialog.TopMost = $true

    $header = New-Object System.Windows.Forms.Panel
    $header.Location = New-Object System.Drawing.Point(0, 0)
    $header.Size = New-Object System.Drawing.Size(700, 92)
    $header.BackColor = [System.Drawing.Color]::FromArgb(239, 246, 255)
    $dialog.Controls.Add($header)

    $title = New-Object System.Windows.Forms.Label
    $title.Location = New-Object System.Drawing.Point(28, 18)
    $title.Size = New-Object System.Drawing.Size(640, 34)
    $title.Text = "Нужно подготовить научное окружение"
    $title.Font = New-Object System.Drawing.Font("Segoe UI", 17, [System.Drawing.FontStyle]::Bold)
    $title.ForeColor = [System.Drawing.Color]::FromArgb(17, 24, 39)
    $header.Controls.Add($title)

    $subtitle = New-Object System.Windows.Forms.Label
    $subtitle.Location = New-Object System.Drawing.Point(30, 56)
    $subtitle.Size = New-Object System.Drawing.Size(630, 24)
    $subtitle.Text = "XRD Phase Finder проверил Python и пакеты реальным запуском."
    $subtitle.Font = New-Object System.Drawing.Font("Segoe UI", 9.5)
    $subtitle.ForeColor = [System.Drawing.Color]::FromArgb(55, 65, 81)
    $header.Controls.Add($subtitle)

    $label = New-Object System.Windows.Forms.Label
    $label.Location = New-Object System.Drawing.Point(30, 112)
    $label.Size = New-Object System.Drawing.Size(640, 24)
    $label.Text = "Не найдено или не работает:"
    $label.Font = New-Object System.Drawing.Font("Segoe UI", 10, [System.Drawing.FontStyle]::Bold)
    $dialog.Controls.Add($label)

    $details = New-Object System.Windows.Forms.TextBox
    $details.Location = New-Object System.Drawing.Point(30, 142)
    $details.Size = New-Object System.Drawing.Size(640, 205)
    $details.Multiline = $true
    $details.ReadOnly = $true
    $details.ScrollBars = [System.Windows.Forms.ScrollBars]::Vertical
    $details.Font = New-Object System.Drawing.Font("Consolas", 9)
    $details.BackColor = [System.Drawing.Color]::FromArgb(248, 250, 252)
    $details.Text = $Detail
    $dialog.Controls.Add($details)

    $destination = New-Object System.Windows.Forms.Label
    $destination.Location = New-Object System.Drawing.Point(30, 360)
    $destination.Size = New-Object System.Drawing.Size(640, 42)
    $destination.Text = "Python и пакеты будут обновлены или доустановлены в:`r`n$EnvironmentPath"
    $destination.Font = New-Object System.Drawing.Font("Segoe UI", 9)
    $dialog.Controls.Add($destination)

    $install = New-Object System.Windows.Forms.Button
    $install.Location = New-Object System.Drawing.Point(335, 416)
    $install.Size = New-Object System.Drawing.Size(215, 36)
    $install.Text = "Обновить или доустановить"
    $install.BackColor = [System.Drawing.Color]::FromArgb(37, 99, 235)
    $install.ForeColor = [System.Drawing.Color]::White
    $install.FlatStyle = [System.Windows.Forms.FlatStyle]::Flat
    $install.Font = New-Object System.Drawing.Font("Segoe UI", 9.5, [System.Drawing.FontStyle]::Bold)
    $install.DialogResult = [System.Windows.Forms.DialogResult]::OK
    $dialog.AcceptButton = $install
    $dialog.Controls.Add($install)

    $close = New-Object System.Windows.Forms.Button
    $close.Location = New-Object System.Drawing.Point(560, 416)
    $close.Size = New-Object System.Drawing.Size(110, 36)
    $close.Text = "Закрыть"
    $close.DialogResult = [System.Windows.Forms.DialogResult]::Cancel
    $dialog.CancelButton = $close
    $dialog.Controls.Add($close)

    $result = $dialog.ShowDialog()
    $dialog.Dispose()
    return ($result -eq [System.Windows.Forms.DialogResult]::OK)
}

function Get-RuntimeSetupProgress {
    param([string]$LogPath)
    if (-not (Test-Path -LiteralPath $LogPath)) {
        return [pscustomobject]@{ Text = "Подготовка установки"; Current = 0; Total = 0 }
    }
    try { $lines = @(Get-Content -LiteralPath $LogPath -Tail 80 -ErrorAction Stop) } catch {
        return [pscustomobject]@{ Text = "Подготовка установки"; Current = 0; Total = 0 }
    }
    $joined = $lines -join "`n"
    $text = "Подготовка научного окружения"
    if ($joined -match "Downloading Python") { $text = "Скачивается Python 3.11" }
    elseif ($joined -match "Installing Python") { $text = "Устанавливается Python 3.11" }
    elseif ($joined -match "Creating venv") { $text = "Создаётся окружение Sci" }
    elseif ($joined -match "Upgrading pip") { $text = "Обновляется установщик пакетов pip" }
    elseif ($joined -match "Installing package:\s*([^`r`n]+)") { $text = "Устанавливается пакет: " + $Matches[1].Trim() }
    elseif ($joined -match "Collecting\s+([^\s`r`n]+)") { $text = "Скачивается пакет: " + $Matches[1].Trim() }
    elseif ($joined -match "Runtime self-test") { $text = "Проверяются Python и научные пакеты" }
    $current = 0
    $total = 0
    if ($joined -match "\[(\d+)\s*/\s*(\d+)\]") {
        $current = [int]$Matches[1]
        $total = [int]$Matches[2]
        $text = "$text ($current из $total)"
    }
    return [pscustomobject]@{ Text = $text; Current = $current; Total = $total }
}

function Invoke-VisibleSciRuntimeRepair {
    param(
        [string]$SetupScript,
        [string]$LogPath,
        [scriptblock]$ProgressCallback
    )
    if (-not (Test-Path -LiteralPath $SetupScript)) {
        throw "Не найден сценарий установки: $SetupScript"
    }
    $process = Start-Process -FilePath "cmd.exe" -ArgumentList @("/c", "`"$SetupScript`"") -PassThru -WindowStyle Hidden
    while (-not $process.HasExited) {
        $progress = Get-RuntimeSetupProgress $LogPath
        if ($ProgressCallback) { & $ProgressCallback $progress }
        [System.Windows.Forms.Application]::DoEvents()
        Start-Sleep -Milliseconds 350
    }
    $process.Refresh()
    $progress = Get-RuntimeSetupProgress $LogPath
    if ($ProgressCallback) { & $ProgressCallback $progress }
    if ($process.ExitCode -ne 0) {
        $tail = ""
        try { $tail = (Get-Content -LiteralPath $LogPath -Tail 35 -ErrorAction Stop) -join "`r`n" } catch {}
        throw "Установка завершилась с кодом $($process.ExitCode).`r`n`r`n$tail"
    }
}

function Show-RuntimeSetupFailure {
    param([string]$Detail, [string]$LogPath)
    $dialog = New-Object System.Windows.Forms.Form
    $dialog.Text = "XRD Phase Finder: установка не завершена"
    $dialog.StartPosition = [System.Windows.Forms.FormStartPosition]::CenterScreen
    $dialog.FormBorderStyle = [System.Windows.Forms.FormBorderStyle]::FixedDialog
    $dialog.MaximizeBox = $false
    $dialog.MinimizeBox = $false
    $dialog.ClientSize = New-Object System.Drawing.Size(690, 420)
    $dialog.BackColor = [System.Drawing.Color]::White
    $dialog.TopMost = $true

    $title = New-Object System.Windows.Forms.Label
    $title.Location = New-Object System.Drawing.Point(26, 20)
    $title.Size = New-Object System.Drawing.Size(630, 36)
    $title.Text = "Не удалось подготовить научное окружение"
    $title.Font = New-Object System.Drawing.Font("Segoe UI", 15, [System.Drawing.FontStyle]::Bold)
    $title.ForeColor = [System.Drawing.Color]::FromArgb(185, 28, 28)
    $dialog.Controls.Add($title)

    $details = New-Object System.Windows.Forms.TextBox
    $details.Location = New-Object System.Drawing.Point(28, 68)
    $details.Size = New-Object System.Drawing.Size(634, 270)
    $details.Multiline = $true
    $details.ReadOnly = $true
    $details.ScrollBars = [System.Windows.Forms.ScrollBars]::Vertical
    $details.Font = New-Object System.Drawing.Font("Consolas", 9)
    $details.Text = $Detail
    $dialog.Controls.Add($details)

    $retry = New-Object System.Windows.Forms.Button
    $retry.Location = New-Object System.Drawing.Point(312, 360)
    $retry.Size = New-Object System.Drawing.Size(110, 36)
    $retry.Text = "Повторить"
    $retry.DialogResult = [System.Windows.Forms.DialogResult]::Retry
    $dialog.Controls.Add($retry)

    $openLog = New-Object System.Windows.Forms.Button
    $openLog.Location = New-Object System.Drawing.Point(432, 360)
    $openLog.Size = New-Object System.Drawing.Size(130, 36)
    $openLog.Text = "Открыть журнал"
    $openLog.Add_Click({ if (Test-Path -LiteralPath $LogPath) { Start-Process -FilePath "notepad.exe" -ArgumentList @("`"$LogPath`"") | Out-Null } })
    $dialog.Controls.Add($openLog)

    $close = New-Object System.Windows.Forms.Button
    $close.Location = New-Object System.Drawing.Point(572, 360)
    $close.Size = New-Object System.Drawing.Size(90, 36)
    $close.Text = "Закрыть"
    $close.DialogResult = [System.Windows.Forms.DialogResult]::Cancel
    $dialog.Controls.Add($close)

    $result = $dialog.ShowDialog()
    $dialog.Dispose()
    return $result
}
