#define MyAppName "NP Create Studio"
#define MyAppVersion "2.4.0"
#define MyAppPublisher "NP Create"
#define MyAppExeName "NPCreateStudio.exe"

[Setup]
AppId={{9E8309B9-83E3-4D3F-9AB1-NPCREATE24}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\NP Create Studio
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=NPCreateStudioSetup-{#MyAppVersion}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest

[Files]
Source: "..\dist\NPCreateStudio\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\NP Create Studio"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\NP Create Studio"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch NP Create Studio"; Flags: nowait postinstall skipifsilent
