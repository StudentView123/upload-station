; Inno Setup script for the all-in-one Upload Station installer.
; Produces UploadStation-Setup.exe which installs the PyInstaller app, the
; bundled Orthanc binaries, writes config.json from a token entered in the
; wizard, opens the DICOM firewall port, auto-starts at logon, and launches.
;
; Paths are relative to this .iss file (installer/), so the repo root is "..".
; Override the version with: iscc /DAppVersion=1.2.0 installer\UploadStation.iss

#ifndef AppVersion
  #define AppVersion "1.2.0"
#endif
#define AppName "Upload Station"
#define HubBaseUrl "https://iqbszdfexefwursnocgb.supabase.co/functions/v1"

[Setup]
AppId={{B7C4E2A1-9D3F-4E5A-8C1B-UPLOADSTATION}}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=LIOCNY
DefaultDirName=C:\UploadStation
DisableDirPage=no
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\dist_installer
OutputBaseFilename=UploadStation-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Files]
; The PyInstaller onedir output (app + embedded Python).
Source: "..\dist\UploadStation\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
; The portable Orthanc DICOM engine + worklist plugin.
Source: "..\vendor\orthanc-windows\*"; DestDir: "{app}\vendor\orthanc-windows"; Flags: recursesubdirs createallsubdirs ignoreversion
; Microsoft VC++ runtime needed by Orthanc on a bare Windows machine.
Source: "..\redist\vc_redist.x64.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall

[Icons]
Name: "{group}\Upload Station"; Filename: "{app}\UploadStation.exe"
Name: "{group}\Upload Station screen (browser)"; Filename: "http://localhost:8088"
Name: "{userstartup}\Upload Station"; Filename: "{app}\UploadStation.exe"

[Run]
; Install the VC++ runtime silently (no-op if already present).
Filename: "{tmp}\vc_redist.x64.exe"; Parameters: "/install /quiet /norestart"; StatusMsg: "Installing required runtime..."; Flags: waituntilterminated
; Open the DICOM port so imaging equipment on the LAN can connect.
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""Upload Station DICOM"" dir=in action=allow protocol=TCP localport=4242"; Flags: runhidden
; Launch the station at the end of setup.
Filename: "{app}\UploadStation.exe"; Description: "Start the Upload Station now"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""Upload Station DICOM"""; Flags: runhidden

[Code]
var
  TokenPage: TInputQueryWizardPage;

procedure InitializeWizard;
begin
  TokenPage := CreateInputQueryPage(wpSelectDir,
    'Practice Hub connection',
    'Enter this office''s station token',
    'Paste the station token from Practice Hub (Imaging - Stations). ' +
    'It is entered once and saved on this machine; you will not need it again.');
  TokenPage.Add('Station token:', False);
  TokenPage.Add('Station name (e.g. Great Neck OCT):', False);
  TokenPage.Values[1] := 'Upload Station';
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = TokenPage.ID then
  begin
    if Trim(TokenPage.Values[0]) = '' then
    begin
      MsgBox('Please paste the station token from Practice Hub before continuing.', mbError, MB_OK);
      Result := False;
    end;
  end;
end;

function JsonEscape(const S: string): string;
var
  R: string;
begin
  R := S;
  StringChangeEx(R, '\', '\\', True);
  StringChangeEx(R, '"', '\"', True);
  Result := R;
end;

procedure WriteConfigJson;
var
  Cfg: string;
  Token, Name: string;
begin
  Token := JsonEscape(Trim(TokenPage.Values[0]));
  Name := Trim(TokenPage.Values[1]);
  if Name = '' then
    Name := 'Upload Station';
  Name := JsonEscape(Name);
  Cfg :=
    '{' + #13#10 +
    '  "hub_base_url": "{#HubBaseUrl}",' + #13#10 +
    '  "station_token": "' + Token + '",' + #13#10 +
    '  "station_name": "' + Name + '",' + #13#10 +
    '  "local_ui_enabled": true,' + #13#10 +
    '  "stream_images_to_hub": true' + #13#10 +
    '}' + #13#10;
  SaveStringToFile(ExpandConstant('{app}\config.json'), Cfg, False);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    WriteConfigJson;
end;
