#define MyAppName "Tekzite Browser"
#define MyAppVersion "10.5.0"
#define MyAppPublisher "Tekzite"
#define MyAppExeName "Tekzite Browser.exe"

[Setup]
AppId={{53D205D4-7AA9-4F48-A3C4-A9A5D6C1C983}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\Tekzite Browser
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\installer-dist
OutputBaseFilename=Tekzite-Browser-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
#if FileExists("..\assets\tekzite.ico")
SetupIconFile=..\assets\tekzite.ico
#endif

[Files]
Source: "..\dist\Tekzite Browser\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"; Flags: unchecked

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
