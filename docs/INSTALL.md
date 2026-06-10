# Installing an Upload Station (one per office)

Target: one always-on Windows desktop per office, on the same network as the
imaging equipment, with a static IP or DHCP reservation.

## 1. Install Orthanc (the DICOM engine)

1. Download the official Windows installer (64-bit) from
   <https://www.orthanc-server.com/download-windows.php>.
2. Run the installer. Default options are fine — it includes the worklists
   plugin the station needs. **Untick "Start Orthanc as a service"** if asked;
   the Upload Station app launches and manages Orthanc itself with its own
   configuration.
3. Nothing to configure — the station generates Orthanc's config automatically.

## 2. Install Python + the station

1. Install Python 3.12+ from <https://www.python.org/downloads/> ("Add to PATH" checked).
2. Copy this `upload-station` folder to `C:\UploadStation` (or `git clone` it).
3. In a terminal:

```bat
cd C:\UploadStation
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy config.example.json config.json
```

## 3. Configure the station

In Practice Hub → **Imaging → Stations** (admin), create a station for this
office and copy its token. Then edit `config.json`:

- `hub_base_url` — the Practice Hub functions URL (shown on the same admin page)
- `station_token` — the token you just copied (this is what scopes the station
  to this office's schedule)
- `station_name` — e.g. `"Main St Office — Front Desk PC"`

Everything else can stay at defaults. If Windows didn't auto-detect Orthanc,
set `orthanc_executable` to `C:\\Program Files\\Orthanc Server\\Orthanc.exe`.

## 4. Open the firewall and start

```bat
netsh advfirewall firewall add rule name="Upload Station DICOM" dir=in action=allow protocol=TCP localport=4242
.venv\Scripts\python run.py
```

Open <http://localhost:8088> — you should see today's patients within a few
seconds, and the station should turn green on the Practice Hub Imaging page.

### Start automatically with Windows

Create a shortcut to `.venv\Scripts\pythonw.exe run.py` (working directory
`C:\UploadStation`) inside `shell:startup`, or register a Scheduled Task that
runs at logon. Keep the desktop set to never sleep.

## 5. Connect the equipment

Hand `docs/EQUIPMENT_SETUP.md` to the equipment vendor/technician along with
this PC's IP address. Each device gets the worklist + storage destination
pointed at this PC, port 4242, AE title `UPLOADSTATION`.

## Notes

- **Local only**: the station UI and Orthanc's HTTP interface bind to
  localhost; only DICOM (4242) is exposed to the office LAN.
- **PHI**: enable BitLocker on the station PC drive; images live under
  `~/UploadStation/Images` organized by date and patient.
- **macOS** (for testing): unzip the official macOS Orthanc package into
  `vendor/` inside this folder — the station finds it automatically.
