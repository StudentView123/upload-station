# Upload Station — Staff Guide

The Upload Station is the desktop in your office that connects the schedule to
the imaging equipment and collects all images in one place.

## The big picture

1. Every morning the station automatically loads **today's patients for your
   office** from the schedule. Nothing to do.
2. On any imaging device (OCT, fundus camera, etc.), open the **worklist /
   patient list** — today's patients are already there. **Pick the patient,
   don't type their info.** This is what keeps images filed under the right chart.
3. After capture, the device sends images to the station automatically. Within
   about a minute the patient's row shows **"Captured"** on the station screen.
4. **Upload to the EMR** (the one manual step for now):
   - Open the Upload Station page: `http://localhost:8088` on the station desktop
     (bookmarked on that machine).
   - Find the patient, click **Open folder** — the images are right there
     (PNG files for easy uploading, DICOM originals alongside).
   - Upload them to the patient's chart in the EMR as usual.
   - Click **Mark uploaded**. The row turns green and the Imaging page in
     Practice Hub updates for everyone.

## Reading the screen

| Chip | Meaning |
|---|---|
| `No images yet` | Patient is on today's schedule, nothing captured yet |
| `Captured · n images` | Images received — needs EMR upload |
| `Uploaded to EMR` | Done |

- **"Other received studies"** at the bottom = images that don't match today's
  schedule (usually someone skipped the worklist and typed the patient by hand,
  or a walk-in). They still save fine — open the folder and upload as normal,
  but remind techs to pick from the worklist.
- Header dots: **Practice Hub** (green = schedule syncing) and **DICOM server**
  (green = equipment can connect). If one is red for more than a few minutes,
  restart the station app; if it stays red, submit a ticket.

## Rules of thumb

- Always **select the patient from the device worklist** before imaging.
- A patient added to the schedule mid-day appears on devices within ~5 minutes
  (or instantly after clicking **Refresh schedule** on the station page).
- Don't shut down the station desktop during office hours.
- End of day: every row should be green. Anything yellow still needs an EMR upload.
