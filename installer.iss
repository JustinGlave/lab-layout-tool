#define MyAppName "Lab Layout Tool"
#define MyAppPublisher "ATS Inc."
#define MyAppExeName "LabLayoutTool.exe"
#ifndef MyAppVersion
  #error MyAppVersion must be supplied by build.bat using /DMyAppVersion=...
#endif

[Setup]
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL=https://github.com/JustinGlave/lab-layout-tool
AppSupportURL=https://github.com/JustinGlave/lab-layout-tool/issues
AppUpdatesURL=https://github.com/JustinGlave/lab-layout-tool/releases

; Install to LocalAppData so no admin rights are needed and the auto-updater
; can replace files in the install folder.
DefaultDirName={localappdata}\ATS Inc\Lab Layout Tool
DefaultGroupName=ATS Inc\Lab Layout Tool
DisableProgramGroupPage=yes

; Output
OutputDir=dist
OutputBaseFilename=LabLayoutToolSetup
SetupIconFile=LLT_Normal.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}

; No admin required (LocalAppData is user-writable)
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=commandline

; Compression
Compression=lzma2/ultra64
SolidCompression=yes

; Wizard appearance
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
; Include the entire PyInstaller output folder
Source: "dist\LabLayoutTool\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; Desktop shortcut — {userdesktop} avoids access denied on no-admin installs
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"
; Start Menu
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"

[Run]
; Offer to launch after install
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Clean up files the app creates in its install folder (logs, generated drawings)
Type: filesandordirs; Name: "{app}"

[Code]
// Ask user if they want to keep their data on uninstall.
// User data lives in %APPDATA%\ATS Inc\Lab Layout Tool\ (saved jobs, generated drawings).
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
  MsgResult: Integer;
begin
  if CurUninstallStep = usUninstall then
  begin
    DataDir := ExpandConstant('{userappdata}\ATS Inc\Lab Layout Tool');
    if DirExists(DataDir) then
    begin
      MsgResult := MsgBox(
        'Do you want to delete your saved jobs and generated drawings?' + #13#10#13#10 +
        'Click Yes to delete all data, or No to keep it.',
        mbConfirmation, MB_YESNO
      );
      if MsgResult = IDYES then
        DelTree(DataDir, True, True, True);
    end;
  end;
end;
