#define MyAppName "CRAFT"
#define MyAppVersion "1.0.1"
#define MyAppPublisher "ABKuznetsov"
#define MyAppURL "https://github.com/ABKuznetsov/XRD_Analysis_Toolkit"

[Setup]
AppId={{D40D3438-89A7-4FE2-B659-17B7D857F9AF}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}/releases
DefaultDirName={autopf}\XRD CRAFT
DefaultGroupName=CRAFT
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
PrivilegesRequired=admin
UsePreviousAppDir=yes
DirExistsWarning=no
OutputDir=..\..\dist\releases
OutputBaseFilename=CRAFT_Setup_{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
VersionInfoVersion={#MyAppVersion}
SetupIconFile=..\..\XRD_Craft\assets\craft.ico
UninstallDisplayIcon={app}\assets\craft.ico

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Messages]
SelectTasksDesc=Choose optional components. XRD Phase Finder identifies and interprets phases in powder X-ray diffraction patterns. It is installed and updated independently.

[Tasks]
Name: "desktopicon"; Description: "Create a Desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: checkedonce
Name: "installfinder"; Description: "Download and install XRD Phase Finder 1.5.0"; GroupDescription: "Additional XRD software:"; Check: not FinderIsInstalled

[Files]
Source: "..\..\XRD_Craft\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "tests\*,__pycache__\*,*.pyc,*.pyo,*.log,.pytest_cache\*,.ruff_cache\*,docs\superpowers\*,crystal_viewer.egg-info\*"
Source: "..\..\toolkit\install_companion_app.ps1"; DestDir: "{app}\toolkit"; Flags: ignoreversion

[Icons]
Name: "{group}\CRAFT"; Filename: "{win}\System32\wscript.exe"; Parameters: """{app}\run_viewer_silent.vbs"""; WorkingDir: "{app}"; IconFilename: "{app}\assets\craft.ico"
Name: "{group}\Uninstall CRAFT"; Filename: "{uninstallexe}"
Name: "{autodesktop}\CRAFT"; Filename: "{win}\System32\wscript.exe"; Parameters: """{app}\run_viewer_silent.vbs"""; WorkingDir: "{app}"; IconFilename: "{app}\assets\craft.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\toolkit\setup_sci_env.bat"; Description: "Prepare the shared scientific environment"; Flags: waituntilterminated runasoriginaluser
Filename: "{win}\System32\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\toolkit\register_craft_install.ps1"" -InstallDir ""{app}"" -Version ""{#MyAppVersion}"""; Flags: runhidden waituntilterminated runasoriginaluser
Filename: "{win}\System32\WindowsPowerShell\v1.0\powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""{app}\toolkit\install_companion_app.ps1"" -TargetAppId ""xrd_finder"""; Description: "Download and install XRD Phase Finder 1.5.0"; Flags: runhidden waituntilterminated skipifsilent runasoriginaluser; Tasks: installfinder; Check: not FinderIsInstalled
Filename: "{win}\System32\wscript.exe"; Parameters: """{app}\run_viewer_silent.vbs"""; Description: "Launch CRAFT"; Flags: postinstall nowait skipifsilent runasoriginaluser

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
function FinderIsInstalled: Boolean;
begin
  Result := FileExists(
    ExpandConstant('{commonpf64}\XRD Phase Finder\XRD_Finder\launch_xrd_finder_silent.vbs'));
end;
