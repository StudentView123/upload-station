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

## 2. Install Python + the station (one click)

1. Install Python 3.12+ from <https://www.python.org/downloads/> ("Add to PATH" checked).
2. Download the Upload Station zip (link on the Practice Hub **Imaging → Setup**
   page) and extract it to `C:\UploadStation`.
3. In Practice Hub → **Imaging → Stations** (admin), create a station for this
   office and copy its **token**.
4. Right-click `setup.bat` → **Run as administrator**. It installs everything,
   asks for the token, opens firewall port 4242, adds the station to Startup,
   launches it, and prints the IP/port/AE-title card for the equipment technician.

Open <http://localhost:8088> — you should see today's patients within a few
seconds, and the station should turn green on the Practice Hub Imaging page.

Manual tweaks (rarely needed) live in `config.json` — e.g. `station_name`, or
`orthanc_executable` if Orthanc was installed somewhere unusual. Keep the
desktop set to never sleep.

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
