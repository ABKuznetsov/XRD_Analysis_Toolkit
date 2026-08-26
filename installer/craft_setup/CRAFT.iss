#define MyAppName "CRAFT"
#define MyAppVersion "0.1.0"
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
DefaultDirName={localappdata}\Sci\apps\craft
DefaultGroupName=CRAFT
ArchitecturesAllowed=x64compatible
MinVersion=10.0
PrivilegesRequired=lowest
OutputDir=..\..\dist\releases
OutputBaseFilename=CRAFT_Setup_{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
VersionInfoVersion={#MyAppVersion}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a Desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: checkedonce

[Files]
Source: "..\..\XRD_Craft\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "tests\*,__pycache__\*,*.pyc,*.pyo,*.log,.pytest_cache\*,.ruff_cache\*,docs\superpowers\*,crystal_viewer.egg-info\*"

[Icons]
Name: "{group}\CRAFT"; Filename: "{win}\System32\wscript.exe"; Parameters: """{app}\run_viewer_silent.vbs"""; WorkingDir: "{app}"
Name: "{group}\Uninstall CRAFT"; Filename: "{uninstallexe}"
Name: "{autodesktop}\CRAFT"; Filename: "{win}\System32\wscript.exe"; Parameters: """{app}\run_viewer_silent.vbs"""; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\toolkit\setup_sci_env.bat"; Description: "Prepare the shared scientific environment"; Flags: waituntilterminated
Filename: "{win}\System32\wscript.exe"; Parameters: """{app}\run_viewer_silent.vbs"""; Description: "Launch CRAFT"; Flags: postinstall nowait skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
