# Upload Station — Staff Guide

There's a small always-on computer in your office (the "station") that connects
the schedule to the imaging equipment. You don't have to touch it — **you do all
your work in Practice Hub from any computer.**

## The big picture

1. Every morning the station automatically loads **today's patients for your
   office** from the schedule. Nothing to do.
2. On any imaging device (OCT, fundus camera, etc.), open the **worklist /
   patient list** — today's patients are already there. **Pick the patient,
   don't type their info.** This is what keeps images filed under the right chart.
3. After capture, the device sends the images up automatically. Within about a
   minute they appear in **Practice Hub → DICOM / Imaging**, under that patient,
   marked **"Captured"** — visible from any computer, nothing to download.
4. **Upload to the EMR** (the one manual step for now):
   - In Practice Hub, open the patient's study and view the images.
   - Click **Download** on an image (one at a time) and upload it to the
     patient's chart in the EMR as usual.
   - Click **Mark uploaded**. The row turns green for everyone.

> The station also keeps a local copy and a fallback page at
> `http://localhost:8088` on the station PC itself, but day to day you only need
> Practice Hub.

## Reading the screen (Practice Hub → Imaging)

| Chip | Meaning |
|---|---|
| `No images yet` | Patient is on today's schedule, nothing captured yet |
| `Captured · n images` | Images received — needs EMR upload |
| `Uploaded to EMR` | Done |

- Studies that don't match today's schedule (someone skipped the worklist and
  typed the patient by hand, or a walk-in) still show up — view and upload as
  normal, but remind techs to **pick from the worklist** so images file cleanly.
- The Imaging page shows a **station health** indicator per office (green = the
  station is online and equipment can connect). If it's red for more than a few
  minutes, submit a ticket.

## Rules of thumb

- Always **select the patient from the device worklist** before imaging.
- A patient added to the schedule mid-day appears on devices within ~5 minutes
  (or instantly after clicking **Refresh schedule** on the station page).
- Don't shut down the station desktop during office hours.
- End of day: every row should be green. Anything yellow still needs an EMR upload.
