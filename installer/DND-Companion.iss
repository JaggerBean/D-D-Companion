#define AppName "D&D Companion"
#define AppVersion GetEnv("DND_COMPANION_VERSION")
#define AppPublisher "Obsidian Kingdom"
#define AppExeName "DNDCompanion.exe"

[Setup]
AppId={{C2EB1DAE-7ED1-42A4-B9FD-06CE72A04B43}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\DND Companion Listener
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\release
OutputBaseFilename=DND-Companion-{#AppVersion}-Setup
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
WizardStyle=modern
SetupIconFile=..\app\assets\dnd-companion.ico
UninstallDisplayIcon={app}\{#AppExeName}
CloseApplications=yes
RestartApplications=no

[Files]
Source: "..\build\dist\DNDCompanion\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "config.yaml,config\*,sessions\*,logs\*"

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: checkedonce

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
