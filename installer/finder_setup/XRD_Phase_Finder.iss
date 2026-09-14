#define MyAppName "XRD Phase Finder"
#define MyAppVersion "1.6.1"
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
OutputBaseFilename=XRD_Phase_Finder_Setup_v1_6_1
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
Source: "..\..\app.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\icon.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\icon.png"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\launch_xrd_finder.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\launch_xrd_finder_silent.vbs"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\launcher\check_sci_runtime.py"; DestDir: "{app}\launcher"; Flags: ignoreversion
Source: "..\..\launcher\first_run_showcase.ps1"; DestDir: "{app}\launcher"; Flags: ignoreversion
Source: "..\..\launcher\launch_xrd_finder_preview.ps1"; DestDir: "{app}\launcher"; Flags: ignoreversion
Source: "..\..\launcher\manifest.json"; DestDir: "{app}\launcher"; Flags: ignoreversion
Source: "..\..\launcher\register_xpff_file_type.ps1"; DestDir: "{app}\launcher"; Flags: ignoreversion
Source: "..\..\launcher\sci_runtime_setup_ui.ps1"; DestDir: "{app}\launcher"; Flags: ignoreversion
Source: "..\..\launcher\stop_running_finder.ps1"; DestDir: "{app}\launcher"; Flags: ignoreversion
Source: "..\..\launcher\setup_sci_env.bat"; DestDir: "{app}\launcher"; Flags: ignoreversion
Source: "..\..\launcher\showcase\*"; DestDir: "{app}\launcher\showcase"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "__pycache__\*,*.pyc,*.pyo,*.log,*.pkg,*.zip,*.7z"
Source: "..\..\launcher\updates\xrd_finder.json"; DestDir: "{app}\launcher\updates"; Flags: ignoreversion
Source: "..\..\xrd_finder\*"; DestDir: "{app}\xrd_finder"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "__pycache__\*,*.pyc,*.pyo,*.log,*.pkg,*.zip,*.7z"

[InstallDelete]
Type: filesandordirs; Name: "{app}\.agents"
Type: filesandordirs; Name: "{app}\.codex"
Type: filesandordirs; Name: "{app}\.git"
Type: filesandordirs; Name: "{app}\.pytest_cache"
Type: filesandordirs; Name: "{app}\.ruff_cache"
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{app}\.worktrees"
Type: filesandordirs; Name: "{app}\benchmark_data"
Type: filesandordirs; Name: "{app}\build"
Type: filesandordirs; Name: "{app}\diagnostics_runtime"
Type: filesandordirs; Name: "{app}\dist"
Type: filesandordirs; Name: "{app}\docs"
Type: filesandordirs; Name: "{app}\document_sync"
Type: filesandordirs; Name: "{app}\document_work"
Type: filesandordirs; Name: "{app}\docx_render_check"
Type: filesandordirs; Name: "{app}\installer"
Type: filesandordirs; Name: "{app}\render_check_50case"
Type: filesandordirs; Name: "{app}\scripts"
Type: filesandordirs; Name: "{app}\toolkit"
Type: filesandordirs; Name: "{app}\tmp"
Type: filesandordirs; Name: "{app}\XRD_Finder"
Type: files; Name: "{app}\.gitattributes"
Type: files; Name: "{app}\.gitignore"
Type: files; Name: "{app}\CHANGELOG.md"
Type: files; Name: "{app}\install_macos.command"
Type: files; Name: "{app}\install_windows_runtime_direct.bat"
Type: files; Name: "{app}\install_xrd_finder_windows_runtime.bat"
Type: files; Name: "{app}\LICENSE"
Type: files; Name: "{app}\MANIFEST.in"
Type: files; Name: "{app}\PROJECT_HEALTH.md"
Type: files; Name: "{app}\pyproject.toml"
Type: files; Name: "{app}\README.md"
Type: files; Name: "{app}\RELEASE_NOTES_1.6.1.md"
Type: files; Name: "{app}\repair_xrd_finder_windows_runtime.bat"
Type: files; Name: "{app}\requirements-dev.txt"
Type: files; Name: "{app}\run_finder.bat"
Type: files; Name: "{app}\run_finder.command"
Type: files; Name: "{app}\run_finder.sh"
Type: files; Name: "{app}\run_finder_cli.bat"
Type: files; Name: "{app}\run_finder_cli.command"
Type: files; Name: "{app}\run_finder_cli.sh"
Type: files; Name: "{app}\run_finder_silent.vbs"
Type: files; Name: "{app}\setup_env.bat"
Type: files; Name: "{app}\setup_env.command"
Type: files; Name: "{app}\setup_env.sh"
Type: files; Name: "{app}\THIRD_PARTY_DATA_SOURCES.md"
Type: files; Name: "{app}\update_from_github.bat"
Type: files; Name: "{app}\update_macos.command"
Type: files; Name: "{app}\launcher\catalog.json"
Type: files; Name: "{app}\launcher\launch_xrd_finder_preview.command"
Type: files; Name: "{app}\launcher\launch_xrd_finder_preview_macos.py"
Type: files; Name: "{app}\launcher\setup_sci_env.command"
Type: files; Name: "{app}\launcher\updates\xrd_finder_macos.json"

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
Filename: "{win}\System32\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\launcher\stop_running_finder.ps1"""; Flags: runhidden waituntilterminated runascurrentuser
Filename: "{win}\System32\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\launcher\register_xpff_file_type.ps1"" -AppRoot ""{app}"" -Quiet"; Flags: runhidden waituntilterminated runascurrentuser
Filename: "{win}\System32\wscript.exe"; Parameters: """{app}\launch_xrd_finder_silent.vbs"""; Description: "Launch XRD Phase Finder"; Flags: postinstall nowait skipifsilent

[UninstallRun]
Filename: "{win}\System32\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\launcher\register_xpff_file_type.ps1"" -AppRoot ""{app}"" -Unregister -Quiet"; Flags: runhidden waituntilterminated runascurrentuser

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
