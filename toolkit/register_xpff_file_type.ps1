[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$AppRoot,
    [switch]$Unregister,
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
$progId = "XRDPhaseFinder.Project"
$applicationName = "XRD Phase Finder"
$classesRoot = "HKCU:\Software\Classes"
$extensionKey = Join-Path $classesRoot ".xpff"
$progIdKey = Join-Path $classesRoot $progId
$registeredApplicationsKey = "HKCU:\Software\RegisteredApplications"
$capabilitiesKey = "HKCU:\Software\XRDPhaseFinder\Capabilities"

function Set-DefaultRegistryValue {
    param([string]$Path, [string]$Value)
    New-Item -Path $Path -Force | Out-Null
    Set-Item -Path $Path -Value $Value
}

function Set-RegistryString {
    param([string]$Path, [string]$Name, [string]$Value)
    New-Item -Path $Path -Force | Out-Null
    New-ItemProperty -Path $Path -Name $Name -Value $Value -PropertyType String -Force | Out-Null
}

function Notify-AssociationChanged {
    if (-not ("XrdAssociationNativeMethods" -as [type])) {
        Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class XrdAssociationNativeMethods {
    [DllImport("shell32.dll")]
    public static extern void SHChangeNotify(uint eventId, uint flags, IntPtr item1, IntPtr item2);
}
"@
    }
    [XrdAssociationNativeMethods]::SHChangeNotify(0x08000000, 0x0000, [IntPtr]::Zero, [IntPtr]::Zero)
}

if ($Unregister) {
    $currentProgId = if (Test-Path -LiteralPath $extensionKey) { (Get-Item -LiteralPath $extensionKey).GetValue("") } else { "" }
    if ([string]$currentProgId -eq $progId) {
        Remove-Item -LiteralPath $extensionKey -Recurse -Force -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath $progIdKey -Recurse -Force -ErrorAction SilentlyContinue
    Remove-ItemProperty -LiteralPath $registeredApplicationsKey -Name $applicationName -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $capabilitiesKey -Recurse -Force -ErrorAction SilentlyContinue
    Notify-AssociationChanged
    exit 0
}

$resolvedRoot = [System.IO.Path]::GetFullPath($AppRoot)
$launcherPath = Join-Path $resolvedRoot "XRD_Finder\launch_xrd_finder_silent.vbs"
$iconPath = Join-Path $resolvedRoot "XRD_Finder\icon.ico"
$wscriptPath = Join-Path $env:WINDIR "System32\wscript.exe"
if (-not (Test-Path -LiteralPath $launcherPath)) {
    throw "XRD Phase Finder launcher was not found: $launcherPath"
}

$openCommand = '"' + $wscriptPath + '" "' + $launcherPath + '" "%1"'
Set-DefaultRegistryValue -Path $extensionKey -Value $progId
Set-RegistryString -Path (Join-Path $extensionKey "OpenWithProgids") -Name $progId -Value ""
Set-DefaultRegistryValue -Path $progIdKey -Value "XRD Phase Finder File"
Set-RegistryString -Path $progIdKey -Name "FriendlyTypeName" -Value "XRD Phase Finder File"
Set-DefaultRegistryValue -Path (Join-Path $progIdKey "DefaultIcon") -Value ($iconPath + ",0")
Set-DefaultRegistryValue -Path (Join-Path $progIdKey "shell\open\command") -Value $openCommand
Set-RegistryString -Path (Join-Path $progIdKey "Application") -Name "ApplicationName" -Value $applicationName
Set-RegistryString -Path (Join-Path $progIdKey "Application") -Name "ApplicationDescription" -Value "Open portable XRD Phase Finder projects"
Set-RegistryString -Path (Join-Path $progIdKey "Application") -Name "ApplicationIcon" -Value $iconPath

Set-RegistryString -Path $registeredApplicationsKey -Name $applicationName -Value "Software\XRDPhaseFinder\Capabilities"
Set-RegistryString -Path $capabilitiesKey -Name "ApplicationName" -Value $applicationName
Set-RegistryString -Path $capabilitiesKey -Name "ApplicationDescription" -Value "Phase identification from X-ray diffraction data"
Set-RegistryString -Path $capabilitiesKey -Name "ApplicationIcon" -Value $iconPath
Set-RegistryString -Path (Join-Path $capabilitiesKey "FileAssociations") -Name ".xpff" -Value $progId

Notify-AssociationChanged
if (-not $Quiet) {
    Write-Output ".xpff is registered for XRD Phase Finder."
}
