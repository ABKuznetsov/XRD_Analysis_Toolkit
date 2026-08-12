#define MyAppName "XRD Phase Finder"
#define MyAppVersion "1.4.0"
#define MyAppPublisher "ABKuznetsov"
#define MyAppURL "https://github.com/ABKuznetsov/XRD_Analysis_Toolkit"
#define MyAppExeName "launch_xrd_finder_silent.vbs"

[Setup]
AppId={{7F3F4D7E-1E5B-4B54-B8B1-8C5D4F4A0101}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}/releases
DefaultDirName={autopf}\XRD Phase Finder
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DefaultGroupName=XRD Phase Finder
MinVersion=10.0
DisableDirPage=no
DisableProgramGroupPage=yes
PrivilegesRequired=admin
OutputDir=output
OutputBaseFilename=XRD_Phase_Finder_Setup_{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\XRD_Finder\icon.ico
UninstallDisplayIcon={app}\XRD_Finder\icon.ico
UninstallDisplayName={#MyAppName}
VersionInfoVersion={#MyAppVersion}
CreateUninstallRegKey=yes
Uninstallable=yes
ChangesAssociations=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a Desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: checkedonce

[Files]
Source: "..\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "installer\*,.git\*,.venv\*,.agents\*,.codex\*,.worktrees\*,__pycache__\*,*.pyc,*.pyo,*.log,*.flag,*.signal,.DS_Store,.ruff_cache\*,.pytest_cache\*,build\*,dist\*,xrd_manager_data\*,diagnostics_runtime\*,benchmark_data\*,document_sync\*,document_work\*,tmp\*,docx_render_check\*,render_check_50case\*,docs\superpowers\*,XRD_Finder\data\*,XRD_Finder\tests\*,XRD_Finder\xrd_analysis_toolkit.egg-info\*,repair_xrd_finder_windows_runtime.bat,scripts\add_cod_targets_to_cache.py,scripts\evaluate_realistic_xrd_gain.py,scripts\evaluate_realistic_xrd_match.py,scripts\generate_realistic_xrd_gain_csv.py,scripts\inspect_download_zips.py,scripts\rruff_benchmark_probe.py,scripts\run_xrd_benchmark_20.py,scripts\summarize_realistic_xrd_gain.py,scripts\update_phase_finder_article.py"

[Icons]
Name: "{group}\XRD Phase Finder"; Filename: "{win}\System32\wscript.exe"; Parameters: """{app}\XRD_Finder\launch_xrd_finder_silent.vbs"""; WorkingDir: "{app}"; IconFilename: "{app}\XRD_Finder\icon.ico"
Name: "{group}\Uninstall XRD Phase Finder"; Filename: "{uninstallexe}"; IconFilename: "{uninstallexe}"
Name: "{autodesktop}\XRD Phase Finder"; Filename: "{win}\System32\wscript.exe"; Parameters: """{app}\XRD_Finder\launch_xrd_finder_silent.vbs"""; WorkingDir: "{app}"; IconFilename: "{app}\XRD_Finder\icon.ico"; Tasks: desktopicon

[Registry]
Root: HKLM; Subkey: "Software\Classes\.xpff"; ValueType: string; ValueName: ""; ValueData: "XRDPhaseFinder.Project"; Flags: uninsdeletevalue
Root: HKLM; Subkey: "Software\Classes\.xpff\OpenWithProgids"; ValueType: string; ValueName: "XRDPhaseFinder.Project"; ValueData: ""; Flags: uninsdeletevalue
Root: HKLM; Subkey: "Software\Classes\XRDPhaseFinder.Project"; ValueType: string; ValueName: ""; ValueData: "XRD Phase Finder File"; Flags: uninsdeletekey
Root: HKLM; Subkey: "Software\Classes\XRDPhaseFinder.Project"; ValueType: string; ValueName: "FriendlyTypeName"; ValueData: "XRD Phase Finder File"
Root: HKLM; Subkey: "Software\Classes\XRDPhaseFinder.Project\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\XRD_Finder\icon.ico,0"
Root: HKLM; Subkey: "Software\Classes\XRDPhaseFinder.Project\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{win}\System32\wscript.exe"" ""{app}\XRD_Finder\launch_xrd_finder_silent.vbs"" ""%1"""
Root: HKLM; Subkey: "Software\RegisteredApplications"; ValueType: string; ValueName: "XRD Phase Finder"; ValueData: "Software\XRDPhaseFinder\Capabilities"; Flags: uninsdeletevalue
Root: HKLM; Subkey: "Software\XRDPhaseFinder\Capabilities"; ValueType: string; ValueName: "ApplicationName"; ValueData: "XRD Phase Finder"; Flags: uninsdeletekey
Root: HKLM; Subkey: "Software\XRDPhaseFinder\Capabilities"; ValueType: string; ValueName: "ApplicationDescription"; ValueData: "Phase identification from X-ray diffraction data"
Root: HKLM; Subkey: "Software\XRDPhaseFinder\Capabilities"; ValueType: string; ValueName: "ApplicationIcon"; ValueData: "{app}\XRD_Finder\icon.ico"
Root: HKLM; Subkey: "Software\XRDPhaseFinder\Capabilities\FileAssociations"; ValueType: string; ValueName: ".xpff"; ValueData: "XRDPhaseFinder.Project"

[Run]
Filename: "{win}\System32\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\toolkit\register_xpff_file_type.ps1"" -AppRoot ""{app}"" -Quiet"; Flags: runhidden waituntilterminated runascurrentuser
Filename: "{win}\System32\wscript.exe"; Parameters: """{app}\XRD_Finder\launch_xrd_finder_silent.vbs"""; Description: "Launch XRD Phase Finder"; Flags: postinstall nowait skipifsilent

[UninstallRun]
Filename: "{win}\System32\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\toolkit\register_xpff_file_type.ps1"" -AppRoot ""{app}"" -Unregister -Quiet"; Flags: runhidden waituntilterminated runascurrentuser

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
