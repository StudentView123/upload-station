# Upload Station

Local DICOM bridge between **Practice Hub** (the Lovable app that syncs the
Nextech schedule) and the imaging equipment in each office.

What it does, per office:

1. Pulls **today's patients for this office** from Practice Hub over HTTPS
   (authenticated by a per-office station token).
2. Serves them to imaging equipment as a **DICOM Modality Worklist** — every
   device shows the day's patients, no manual typing.
3. Receives finished images via **DICOM C-STORE**, renders PNGs, and **streams
   them up to Practice Hub** (private Supabase storage) so staff can view and
   download them from any computer — no local software needed for viewing.
   A local copy is also kept by default.
4. Reports each study (with its image references) to Practice Hub, where the
   `/dicom` page shows the gallery, per-image download, and **Mark uploaded**.
5. Can run **headless** (`local_ui_enabled: false`) as a pure relay; a local
   fallback queue UI (<http://localhost:8088>) is available when enabled.

The DICOM engine is [Orthanc](https://www.orthanc-server.com) (free, open
source) with its worklists plugin; the station generates Orthanc's
configuration and manages the process automatically.

## Layout

| Path | Purpose |
|---|---|
| `station/` | The app: config, hub client, worklist writer, exporter, web UI, orchestrator |
| `scripts/simulate_modality.py` | Acts like a real device: C-FIND worklist, then C-STORE a test image |
| `scripts/mock_hub.py` | Fake Practice Hub for offline development |
| `docs/INSTALL.md` | Office install guide (Windows) |
| `docs/EQUIPMENT_SETUP.md` | Hand to equipment vendors/technicians |
| `docs/STAFF_GUIDE.md` | Hand to office staff |

## Quick start (development, macOS/Linux)

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
# put the official Orthanc macOS package in ./vendor (or install Orthanc system-wide)
.venv/bin/python scripts/mock_hub.py &                       # fake Practice Hub
UPLOAD_STATION_CONFIG=config.test.json .venv/bin/python run.py &
.venv/bin/python scripts/simulate_modality.py                # pretend to be a camera
open http://localhost:8088
```

Production setup: see `docs/INSTALL.md`.
