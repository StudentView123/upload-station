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
Name: "{group}\Connect / Settings (browser)"; Filename: "http://localhost:8088/setup"
Name: "{userstartup}\Upload Station"; Filename: "{app}\UploadStation.exe"

[Run]
; Install the VC++ runtime silently (no-op if already present).
Filename: "{tmp}\vc_redist.x64.exe"; Parameters: "/install /quiet /norestart"; StatusMsg: "Installing required runtime..."; Flags: waituntilterminated
; Open the DICOM port so imaging equipment on the LAN can connect.
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""Upload Station DICOM"" dir=in action=allow protocol=TCP localport=4242"; Flags: runhidden
; Launch the station at the end of setup.
Filename: "{app}\UploadStation.exe"; Description: "Start the Upload Station now"; Flags: nowait postinstall skipifsilent
; Open the browser setup page so the user can connect (token / code / login).
Filename: "http://localhost:8088/setup"; Description: "Open the connection setup page"; Flags: shellexec nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""Upload Station DICOM"""; Flags: runhidden

[Code]
var
  TokenPage: TInputQueryWizardPage;

procedure InitializeWizard;
begin
  { Token entry is OPTIONAL. By default the user finishes setup in the browser
    page (token / enrollment code / login). Advanced users may paste a token here. }
  TokenPage := CreateInputQueryPage(wpSelectDir,
    'Connect to Practice Hub (optional)',
    'You can connect now or right after install',
    'Recommended: leave these blank and click Next. After install, a browser ' +
    'page opens where you choose how to connect (office token, enrollment code, ' +
    'or login). Advanced: paste an office token here to connect immediately.');
  TokenPage.Add('Station name (optional, e.g. Great Neck OCT):', False);
  TokenPage.Add('Office token (optional):', False);
  TokenPage.Values[0] := 'Upload Station';
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
  Name := Trim(TokenPage.Values[0]);
  if Name = '' then
    Name := 'Upload Station';
  Name := JsonEscape(Name);
  Token := JsonEscape(Trim(TokenPage.Values[1]));

  Cfg :=
    '{' + #13#10 +
    '  "hub_base_url": "{#HubBaseUrl}",' + #13#10 +
    '  "station_name": "' + Name + '",' + #13#10;
  if Token <> '' then
    Cfg := Cfg +
    '  "auth_mode": "token",' + #13#10 +
    '  "station_token": "' + Token + '",' + #13#10;
  Cfg := Cfg +
    '  "local_ui_enabled": true,' + #13#10 +
    '  "stream_images_to_hub": true' + #13#10 +
    '}' + #13#10;
  { Do not overwrite an existing config on reinstall/upgrade. }
  if not FileExists(ExpandConstant('{app}\config.json')) then
    SaveStringToFile(ExpandConstant('{app}\config.json'), Cfg, False);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    WriteConfigJson;
end;
