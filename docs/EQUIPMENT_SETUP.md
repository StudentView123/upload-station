# DICOM Setup Instructions — for Equipment Vendors / Field Technicians

Give this page to the technician configuring any imaging device (OCT, fundus
camera, topographer, visual field, etc.). The office runs a DICOM server called
the **Upload Station** on a desktop PC in the office. Each device needs two
things configured: a **Modality Worklist (MWL) source** and a **DICOM storage
destination**. Both point at the same server.

## Connection details

| Setting | Value |
|---|---|
| Server IP address | IP of the Upload Station PC (see below) |
| Port | `4242` (same port for worklist and storage) |
| Called AE Title (the server) | `UPLOADSTATION` |
| Calling AE Title (the device) | Anything — e.g. `OCT1`, `FUNDUS1` (the server accepts any AE title) |
| TLS / encryption | Off (local network only) |
| Character set | ISO_IR 100 (Latin-1) |

The Upload Station PC must have a **static IP or DHCP reservation** on the
office network. The office manager can read the current IP from the Upload
Station screen or via `ipconfig` on that PC.

## 1. Modality Worklist (MWL)

- Enable "Worklist", "MWL", "Work List Server", or "Patient Schedule" on the device.
- Point it at the server above (IP / port `4242` / AE `UPLOADSTATION`).
- Query mode: "Today" / broad query is fine. The server returns the office's
  schedule for the current day.
- The worklist provides per patient: name, patient ID (chart number), date of
  birth, sex, accession number, scheduled date/time, and performing physician.
- **Do not filter by Scheduled Station AE Title** (or leave that field blank on
  the device) — worklist entries are not tied to a specific device.
- Modality filtering: the server publishes each appointment under these
  modality codes: `OPT`, `OP`, `OPV`, `OT` (configurable). If the device
  queries with a modality code not in that list and sees an empty list, tell
  the office manager which modality code the device uses so it can be added.

## 2. Storage destination (image export)

- Configure the DICOM "Storage", "Export", "Send", or "Archive/PACS"
  destination to the same server (IP / port `4242` / AE `UPLOADSTATION`).
- Enable **auto-send / auto-export after capture** if the device supports it,
  so images transfer without a manual step.
- The server accepts all standard and vendor-specific SOP classes and all
  standard transfer syntaxes. Uncompressed or JPEG/JPEG-2000 compressed are both fine.

## 3. Acceptance test (please verify before leaving)

1. **C-ECHO** (DICOM ping) from the device to the server succeeds.
2. Open the worklist on the device: today's patients appear.
3. Select a worklist patient, capture (or use the device's test capture), and send.
4. Confirm with the office staff that the study appeared on the Upload Station
   screen (`http://localhost:8088` on the station PC) within ~1 minute.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| C-ECHO fails | Wrong IP/port; Windows Firewall on the station PC must allow inbound TCP 4242; device and PC must be on the same network/VLAN |
| Worklist empty | Device queries with a date other than today, or a modality code the server doesn't publish, or it filters by Scheduled Station AE Title |
| Worklist works, send fails | Storage destination misconfigured (check it's the same IP/port/AET) |
| Patient shows on device but images never appear on station | Auto-export not enabled on the device; check the device's send queue/log |
