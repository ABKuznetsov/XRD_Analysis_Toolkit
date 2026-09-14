#define MyAppName "XRD Phase Finder"
#define MyAppVersion "1.6.0"
#define MyAppPublisher "ABKuznetsov"
#define MyAppURL "https://github.com/ABKuznetsov/XRD_Analysis_Toolkit"

[Setup]
AppId={{7F3F4D7E-1E5B-4B54-B8B1-8C5D4F4A0101}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}/releases
DefaultDirName={autopf}\XRD Phase Finder
DefaultGroupName=XRD Phase Finder
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
PrivilegesRequired=admin
OutputDir=..\..\dist\releases
OutputBaseFilename=XRD_Phase_Finder_Setup_{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\..\icon.ico
UninstallDisplayIcon={app}\icon.ico
VersionInfoVersion={#MyAppVersion}
ChangesAssociations=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a Desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: checkedonce

[Files]
Source: "..\..\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: ".git\*,.venv\*,build\*,dist\*,docs\*,tests\*,installer\*,scripts\*,data\*,__pycache__\*,*.pyc,*.pyo,*.log,.pytest_cache\*,.ruff_cache\*,*.pkg,*.zip,*.7z,requirements-dev.txt"

[Icons]
Name: "{group}\XRD Phase Finder"; Filename: "{win}\System32\wscript.exe"; Parameters: """{app}\launch_xrd_finder_silent.vbs"""; WorkingDir: "{app}"; IconFilename: "{app}\icon.ico"
Name: "{group}\Uninstall XRD Phase Finder"; Filename: "{uninstallexe}"
Name: "{autodesktop}\XRD Phase Finder"; Filename: "{win}\System32\wscript.exe"; Parameters: """{app}\launch_xrd_finder_silent.vbs"""; WorkingDir: "{app}"; IconFilename: "{app}\icon.ico"; Tasks: desktopicon

[Registry]
Root: HKLM; Subkey: "Software\Classes\.xpff"; ValueType: string; ValueName: ""; ValueData: "XRDPhaseFinder.Project"; Flags: uninsdeletevalue
Root: HKLM; Subkey: "Software\Classes\.xpff\OpenWithProgids"; ValueType: string; ValueName: "XRDPhaseFinder.Project"; ValueData: ""; Flags: uninsdeletevalue
Root: HKLM; Subkey: "Software\Classes\XRDPhaseFinder.Project"; ValueType: string; ValueName: ""; ValueData: "XRD Phase Finder File"; Flags: uninsdeletekey
Root: HKLM; Subkey: "Software\Classes\XRDPhaseFinder.Project\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\icon.ico,0"
Root: HKLM; Subkey: "Software\Classes\XRDPhaseFinder.Project\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{win}\System32\wscript.exe"" ""{app}\launch_xrd_finder_silent.vbs"" ""%1"""
Root: HKLM; Subkey: "Software\RegisteredApplications"; ValueType: string; ValueName: "XRD Phase Finder"; ValueData: "Software\XRDPhaseFinder\Capabilities"; Flags: uninsdeletevalue
Root: HKLM; Subkey: "Software\XRDPhaseFinder\Capabilities"; ValueType: string; ValueName: "ApplicationName"; ValueData: "XRD Phase Finder"; Flags: uninsdeletekey
Root: HKLM; Subkey: "Software\XRDPhaseFinder\Capabilities"; ValueType: string; ValueName: "ApplicationDescription"; ValueData: "Phase identification from X-ray diffraction data"
Root: HKLM; Subkey: "Software\XRDPhaseFinder\Capabilities"; ValueType: string; ValueName: "ApplicationIcon"; ValueData: "{app}\icon.ico"
Root: HKLM; Subkey: "Software\XRDPhaseFinder\Capabilities\FileAssociations"; ValueType: string; ValueName: ".xpff"; ValueData: "XRDPhaseFinder.Project"

[Run]
Filename: "{win}\System32\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\launcher\register_xpff_file_type.ps1"" -AppRoot ""{app}"" -Quiet"; Flags: runhidden waituntilterminated runascurrentuser
Filename: "{win}\System32\wscript.exe"; Parameters: """{app}\launch_xrd_finder_silent.vbs"""; Description: "Launch XRD Phase Finder"; Flags: postinstall nowait skipifsilent

[UninstallRun]
Filename: "{win}\System32\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\launcher\register_xpff_file_type.ps1"" -AppRoot ""{app}"" -Unregister -Quiet"; Flags: runhidden waituntilterminated runascurrentuser

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
