# Konan CellChek (Specular Microscope) — DICOM answer sheet

Answers for Konan's **FRM-082 "Checklist for DICOM CellChek Installation"**.
Fill in the IP from the Upload Station PC in your office (shown at the end of
`setup.bat`, or run `ipconfig` on that PC).

## MWL (Modality Worklist)

| # | Question | Answer |
|---|---|---|
| 1 | MWL Provider AE Title | `UPLOADSTATION` |
| 2 | MWL User AE Title for Specular Microscope | Yes — use `CELLCHEK` (any name works; pick one per device) |
| 3 | IP Address of MWL Server | IP of this office's Upload Station PC: `__________` |
| 4 | Port Number of MWL Server | `4242` |
| 5 | Use "OP" as the modality for Specular Microscope? | **Yes** — the worklist publishes `OP` entries. (Konan's note is correct: the OP list also shows other photography orders for the same patients — that's expected and harmless.) |

## Secondary Capture Storage

| # | Question | Answer |
|---|---|---|
| 6 | Storage Provider AE Title | `UPLOADSTATION` |
| 7 | Storage User AE Title for Specular Microscope | Yes — `CELLCHEK` (same as #2) |
| 8 | IP Address of Storage Server | Same IP as #3: `__________` |
| 9 | Port Number of Storage Server | `4242` |

Worklist and storage are the **same server** — one IP, one port, one AE title.

## After configuration — 3-minute acceptance test

1. From the CellChek, run a DICOM **C-ECHO / connection test** → must succeed.
2. Open the **worklist** on the CellChek → today's patients for this office appear.
3. Select a test patient, capture, and send → within ~1 minute the patient's row
   on the Upload Station screen (`http://localhost:8088` on the station PC)
   shows **Captured**, and the images are in the patient's folder.

If any step fails, see the Troubleshooting table in `docs/EQUIPMENT_SETUP.md`
(firewall port 4242 inbound on the station PC is the most common culprit).
