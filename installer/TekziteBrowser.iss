#define MyAppName "Tekzite Browser"
#define MyAppVersion "10.5.47"
#define MyAppPublisher "Tekzite"
#define MyAppExeName "TekziteBrowser.exe"

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
ChangesAssociations=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
#if FileExists("..\assets\tekzite.ico")
SetupIconFile=..\assets\tekzite.ico
#endif

[Files]
Source: "..\dist\TekziteBrowser.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"; Flags: unchecked


[Registry]
; Per-user Default Apps registration. Windows still requires the user to confirm
; their default choices; this only makes Tekzite available as a browser handler.
Root: HKCU; Subkey: "Software\Clients\StartMenuInternet\TekziteBrowser"; ValueType: string; ValueName: ""; ValueData: "{#MyAppName}"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Clients\StartMenuInternet\TekziteBrowser\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"",0"
Root: HKCU; Subkey: "Software\Clients\StartMenuInternet\TekziteBrowser\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"""
Root: HKCU; Subkey: "Software\Clients\StartMenuInternet\TekziteBrowser\Capabilities"; ValueType: string; ValueName: "ApplicationName"; ValueData: "{#MyAppName}"
Root: HKCU; Subkey: "Software\Clients\StartMenuInternet\TekziteBrowser\Capabilities"; ValueType: string; ValueName: "ApplicationDescription"; ValueData: "Tekzite Browser - Chromium rendered, privacy-focused Windows browser."
Root: HKCU; Subkey: "Software\Clients\StartMenuInternet\TekziteBrowser\Capabilities"; ValueType: string; ValueName: "ApplicationIcon"; ValueData: """{app}\{#MyAppExeName}"",0"
Root: HKCU; Subkey: "Software\Clients\StartMenuInternet\TekziteBrowser\Capabilities\FileAssociations"; ValueType: string; ValueName: ".htm"; ValueData: "TekziteBrowserHTML"
Root: HKCU; Subkey: "Software\Clients\StartMenuInternet\TekziteBrowser\Capabilities\FileAssociations"; ValueType: string; ValueName: ".html"; ValueData: "TekziteBrowserHTML"
Root: HKCU; Subkey: "Software\Clients\StartMenuInternet\TekziteBrowser\Capabilities\URLAssociations"; ValueType: string; ValueName: "http"; ValueData: "TekziteBrowserURL"
Root: HKCU; Subkey: "Software\Clients\StartMenuInternet\TekziteBrowser\Capabilities\URLAssociations"; ValueType: string; ValueName: "https"; ValueData: "TekziteBrowserURL"
Root: HKCU; Subkey: "Software\Clients\StartMenuInternet\TekziteBrowser\Capabilities\StartMenu"; ValueType: string; ValueName: "StartMenuInternet"; ValueData: "TekziteBrowser"
Root: HKCU; Subkey: "Software\RegisteredApplications"; ValueType: string; ValueName: "{#MyAppName}"; ValueData: "Software\Clients\StartMenuInternet\TekziteBrowser\Capabilities"; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\TekziteBrowserURL"; ValueType: string; ValueName: ""; ValueData: "Tekzite Browser URL"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\TekziteBrowserURL"; ValueType: string; ValueName: "URL Protocol"; ValueData: ""
Root: HKCU; Subkey: "Software\Classes\TekziteBrowserURL\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"",0"
Root: HKCU; Subkey: "Software\Classes\TekziteBrowserURL\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""
Root: HKCU; Subkey: "Software\Classes\TekziteBrowserHTML"; ValueType: string; ValueName: ""; ValueData: "Tekzite Browser HTML Document"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\TekziteBrowserHTML\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"",0"
Root: HKCU; Subkey: "Software\Classes\TekziteBrowserHTML\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""
Root: HKCU; Subkey: "Software\Classes\Applications\{#MyAppExeName}"; ValueType: string; ValueName: "FriendlyAppName"; ValueData: "{#MyAppName}"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\Applications\{#MyAppExeName}\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""
Root: HKCU; Subkey: "Software\Classes\Applications\{#MyAppExeName}\SupportedTypes"; ValueType: string; ValueName: ".htm"; ValueData: ""
Root: HKCU; Subkey: "Software\Classes\Applications\{#MyAppExeName}\SupportedTypes"; ValueType: string; ValueName: ".html"; ValueData: ""

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

