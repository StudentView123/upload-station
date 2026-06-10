@echo off
REM ============================================================
REM  Upload Station - one-time setup for Windows
REM  Right-click this file and choose "Run as administrator".
REM ============================================================
cd /d "%~dp0"
echo.
echo  === Upload Station setup ===
echo.

REM -- 1. Check Python ------------------------------------------------
python --version >nul 2>&1
if errorlevel 1 (
    echo  Python was not found. Install Python 3.12+ from
    echo  https://www.python.org/downloads/  (check "Add to PATH"),
    echo  then run this script again.
    pause
    exit /b 1
)

REM -- 2. Create venv and install dependencies ------------------------
if not exist .venv (
    echo  Creating Python environment...
    python -m venv .venv
)
echo  Installing dependencies...
.venv\Scripts\pip install --quiet -r requirements.txt
if errorlevel 1 (
    echo  Dependency install failed - check your internet connection.
    pause
    exit /b 1
)

REM -- 3. Create config.json with the station token --------------------
if not exist config.json (
    copy /y config.example.json config.json >nul
    echo.
    echo  Paste this office's STATION TOKEN.
    echo  (Practice Hub - Imaging - Stations - create/copy token)
    set /p TOKEN="  Token: "
    powershell -NoProfile -Command ^
      "(Get-Content config.json) -replace 'PASTE-TOKEN-FROM-PRACTICE-HUB-IMAGING-SETTINGS', $env:TOKEN | Set-Content config.json"
    echo  Saved to config.json
) else (
    echo  config.json already exists - keeping it.
)

REM -- 4. Open the DICOM port in Windows Firewall -----------------------
netsh advfirewall firewall show rule name="Upload Station DICOM" >nul 2>&1
if errorlevel 1 (
    echo  Opening firewall port 4242 for the imaging equipment...
    netsh advfirewall firewall add rule name="Upload Station DICOM" dir=in action=allow protocol=TCP localport=4242 >nul
)

REM -- 5. Start the station automatically at logon ----------------------
powershell -NoProfile -Command ^
  "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Startup')+'\Upload Station.lnk');" ^
  "$s.TargetPath='%~dp0start.bat'; $s.WorkingDirectory='%~dp0'; $s.WindowStyle=7; $s.Save()"
echo  Added to Startup so it launches at logon.

REM -- 6. Show this PC's IP for the equipment installers ----------------
echo.
echo  ============================================================
echo   Setup complete. Give the equipment technician this info:
echo     AE Title : UPLOADSTATION
echo     Port     : 4242
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do echo     IP       :%%a
echo  ============================================================
echo.
echo  Starting the Upload Station now...
start "" "%~dp0start.bat"
echo  Open http://localhost:8088 to see today's patients.
pause
