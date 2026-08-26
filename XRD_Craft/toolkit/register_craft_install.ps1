param(
    [string]$InstallDir = "",
    [string]$Version = "",
    [switch]$Unregister
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
    throw "LOCALAPPDATA is not available for the current user."
}

$metadataDir = Join-Path $env:LOCALAPPDATA "Sci\apps\craft"
$metadataPath = Join-Path $metadataDir "installed.ini"

if ($Unregister) {
    if (Test-Path -LiteralPath $metadataPath -PathType Leaf) {
        Remove-Item -LiteralPath $metadataPath -Force
    }
    if ((Test-Path -LiteralPath $metadataDir -PathType Container) -and
        -not (Get-ChildItem -LiteralPath $metadataDir -Force | Select-Object -First 1)) {
        Remove-Item -LiteralPath $metadataDir -Force
    }
    exit 0
}

if ([string]::IsNullOrWhiteSpace($InstallDir) -or
    [string]::IsNullOrWhiteSpace($Version)) {
    throw "InstallDir and Version are required when registering CRAFT."
}

$resolvedInstallDir = [System.IO.Path]::GetFullPath($InstallDir)
if (-not (Test-Path -LiteralPath $resolvedInstallDir -PathType Container)) {
    throw "The CRAFT installation directory does not exist: $resolvedInstallDir"
}

# Releases before 1.0.1 placed the complete application in this metadata folder.
# Remove that known legacy payload only; Sci\env and Sci\craft user data are separate.
$legacyLauncher = Join-Path $metadataDir "run_viewer_silent.vbs"
if (Test-Path -LiteralPath $legacyLauncher -PathType Leaf) {
    Remove-Item -LiteralPath $metadataDir -Recurse -Force
}

[void][System.IO.Directory]::CreateDirectory($metadataDir)
$contents = @(
    "[CRAFT]",
    "InstallDir=$resolvedInstallDir",
    "Version=$Version"
)
$utf8WithoutBom = [System.Text.UTF8Encoding]::new($false)
[System.IO.File]::WriteAllLines($metadataPath, $contents, $utf8WithoutBom)
