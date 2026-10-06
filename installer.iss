; Inno Setup Script for Universal Media Downloader v3.1
#define MyAppName "Universal Media Downloader"
#define MyAppVersion "3.1"
#define MyAppPublisher "Magerko & MrPablo"
#define MyAppURL "https://github.com/dimalinau-lab/universal-media-downloader-2"
#define MyAppExeName "Windows3.1.UMD.exe"
#define ProjectDir "D:\pton\PythonProject9"

[Setup]
; Basic Application Information
AppId={{9B7C726A-01D5-4E83-A816-64F7E666C2F1}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}

; Destination Directories
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
LicenseFile={#ProjectDir}\LICENSE

; Output
OutputDir={#ProjectDir}\output
OutputBaseFilename=Universal_Media_Downloader_v3.1_Setup
SetupIconFile={#ProjectDir}\assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}

; High-ratio LZMA2 solid compression
Compression=lzma2/ultra64
SolidCompression=yes

; Modern visual style
WizardStyle=modern
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

; 64-bit Windows compatibility
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "ukrainian"; MessagesFile: "compiler:Languages\Ukrainian.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#ProjectDir}\output\Windows3.1.UMD\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\assets\icon.ico"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\assets\icon.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
