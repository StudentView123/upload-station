"""Local web UI: today's worklist, received studies, mark-uploaded queue.

Served on http://localhost:<ui_port> — staff open this page on the upload
station desktop. No external assets, works offline.
"""

import logging
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

from .config import Config
from .db import StationDB

log = logging.getLogger("web")

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Upload Station</title>
<style>
  :root { --bg:#f5f6f8; --card:#fff; --ink:#1c2430; --mut:#69788c; --line:#e3e8ef;
          --ok:#0f7b46; --okbg:#e2f5ea; --warn:#9a6700; --warnbg:#fff3d6;
          --idle:#5b6877; --idlebg:#edf0f4; --accent:#1f5eff; }
  * { box-sizing:border-box; }
  body { margin:0; font:15px/1.45 -apple-system, "Segoe UI", Roboto, sans-serif;
         background:var(--bg); color:var(--ink); }
  header { background:var(--card); border-bottom:1px solid var(--line);
           padding:14px 24px; display:flex; align-items:center; gap:16px; }
  header h1 { font-size:17px; margin:0; }
  .grow { flex:1; }
  .dot { width:9px; height:9px; border-radius:50%; display:inline-block; margin-right:6px; }
  .meta { color:var(--mut); font-size:13px; }
  main { max-width:1100px; margin:24px auto; padding:0 24px; }
  h2 { font-size:14px; text-transform:uppercase; letter-spacing:.04em; color:var(--mut); }
  table { width:100%; border-collapse:collapse; background:var(--card);
          border:1px solid var(--line); border-radius:10px; overflow:hidden; }
  th { text-align:left; font-size:12px; color:var(--mut); padding:10px 14px;
       border-bottom:1px solid var(--line); background:#fafbfc; }
  td { padding:10px 14px; border-bottom:1px solid var(--line); vertical-align:middle; }
  tr:last-child td { border-bottom:none; }
  .chip { display:inline-block; padding:3px 10px; border-radius:999px; font-size:12px; font-weight:600; }
  .chip.ok   { background:var(--okbg);   color:var(--ok); }
  .chip.warn { background:var(--warnbg); color:var(--warn); }
  .chip.idle { background:var(--idlebg); color:var(--idle); }
  button { font:13px inherit; padding:6px 12px; border-radius:7px; cursor:pointer;
           border:1px solid var(--line); background:var(--card); }
  button.primary { background:var(--accent); border-color:var(--accent); color:#fff; }
  button:disabled { opacity:.5; cursor:default; }
  .name { font-weight:600; }
  .sub { color:var(--mut); font-size:12.5px; }
  .empty { padding:28px; text-align:center; color:var(--mut); background:var(--card);
           border:1px dashed var(--line); border-radius:10px; }
</style>
</head>
<body>
<header>
  <h1>Upload Station</h1>
  <span class="meta" id="loc"></span>
  <div class="grow"></div>
  <span class="meta"><span class="dot" id="hubdot"></span>Practice Hub</span>
  <span class="meta"><span class="dot" id="dcmdot"></span>DICOM server</span>
  <span class="meta" id="sync"></span>
  <button onclick="syncNow()">Refresh schedule</button>
</header>
<main>
  <h2>Today's patients</h2>
  <div id="worklist"></div>
  <h2 style="margin-top:32px">Other received studies</h2>
  <div id="orphans"></div>
</main>
<script>
const fmtTime = iso => iso ? new Date(iso).toLocaleTimeString([], {hour:'numeric', minute:'2-digit'}) : '';

function chip(study) {
  if (!study) return '<span class="chip idle">No images yet</span>';
  if (study.status === 'uploaded')
    return '<span class="chip ok">Uploaded to EMR</span>';
  return `<span class="chip warn">Captured · ${study.image_count} image${study.image_count===1?'':'s'}</span>`;
}

function actions(study) {
  if (!study) return '';
  const open = `<button onclick="openFolder('${study.study_uid}')">Open folder</button>`;
  const mark = study.status === 'uploaded' ? ''
    : ` <button class="primary" onclick="markUploaded('${study.study_uid}')">Mark uploaded</button>`;
  return open + mark;
}

function renderWorklist(state) {
  const entries = (state.worklist && state.worklist.entries) || [];
  if (!entries.length) {
    document.getElementById('worklist').innerHTML =
      '<div class="empty">No appointments on today\\'s schedule yet.</div>';
    return;
  }
  const byAccession = {};
  (state.studies || []).forEach(s => { if (s.accession) byAccession[s.accession] = s; });
  let rows = entries.map(e => {
    const s = byAccession[e.accession_number];
    return `<tr>
      <td>${fmtTime(e.start_time)}</td>
      <td><span class="name">${e.patient.last_name}, ${e.patient.first_name}</span>
          <div class="sub">Chart ${e.patient.chart_number || '—'} · DOB ${e.patient.date_of_birth || '—'}</div></td>
      <td>${e.provider_name || ''}<div class="sub">${e.appointment_type || ''}</div></td>
      <td>${chip(s)}</td>
      <td style="text-align:right">${actions(s)}</td>
    </tr>`;
  }).join('');
  document.getElementById('worklist').innerHTML =
    `<table><tr><th>Time</th><th>Patient</th><th>Provider</th><th>Imaging</th><th></th></tr>${rows}</table>`;
}

function renderOrphans(state) {
  const entries = (state.worklist && state.worklist.entries) || [];
  const accessions = new Set(entries.map(e => e.accession_number));
  const orphans = (state.studies || []).filter(s => !accessions.has(s.accession));
  const el = document.getElementById('orphans');
  if (!orphans.length) { el.innerHTML = '<div class="empty">None — every study matches today\\'s schedule.</div>'; return; }
  let rows = orphans.map(s => `<tr>
      <td>${fmtTime(s.captured_at)}</td>
      <td><span class="name">${(s.patient_name||'').replace('^', ', ')}</span>
          <div class="sub">ID ${s.patient_id || '—'} · ${s.modalities || ''}</div></td>
      <td>${chip(s)}</td>
      <td style="text-align:right">${actions(s)}</td>
    </tr>`).join('');
  el.innerHTML = `<table><tr><th>Received</th><th>Patient</th><th>Status</th><th></th></tr>${rows}</table>`;
}

async function refresh() {
  try {
    const state = await (await fetch('/api/state')).json();
    document.getElementById('loc').textContent =
      state.location_name ? `${state.location_name} — ${state.date || ''}` : '';
    document.getElementById('sync').textContent =
      state.last_worklist_sync ? `Schedule synced ${fmtTime(state.last_worklist_sync)}` : 'Schedule not synced yet';
    document.getElementById('hubdot').style.background = state.hub_ok ? '#19a35c' : '#d64545';
    document.getElementById('dcmdot').style.background = state.dicom_ok ? '#19a35c' : '#d64545';
    renderWorklist(state);
    renderOrphans(state);
  } catch (e) { /* station restarting; retry on next tick */ }
}

async function markUploaded(uid) {
  await fetch(`/api/studies/${encodeURIComponent(uid)}/uploaded`, {method:'POST'});
  refresh();
}
async function openFolder(uid) {
  await fetch(`/api/studies/${encodeURIComponent(uid)}/open-folder`, {method:'POST'});
}
async function syncNow() {
  await fetch('/api/sync-now', {method:'POST'});
  setTimeout(refresh, 1500);
}

refresh();
setInterval(refresh, 10000);
</script>
</body>
</html>"""


def create_app(cfg: Config, db: StationDB, runtime) -> FastAPI:
    """`runtime` is the StationRuntime from main.py (worklist sync + orthanc + hub)."""
    app = FastAPI(title="Upload Station", docs_url=None, redoc_url=None)

    @app.get("/", response_class=HTMLResponse)
    def index():
        return PAGE

    @app.get("/api/state")
    def state():
        worklist = db.load_worklist() or {}
        return JSONResponse({
            "location_name": (worklist.get("location") or {}).get("name"),
            "date": worklist.get("date"),
            "worklist": worklist,
            "studies": db.all_studies(),
            "last_worklist_sync": db.get_meta("last_worklist_sync"),
            "hub_ok": db.get_meta("hub_ok") == "1",
            "dicom_ok": runtime.orthanc.is_running(),
        })

    @app.post("/api/studies/{study_uid}/uploaded")
    def mark_uploaded(study_uid: str):
        if not db.get_study(study_uid):
            raise HTTPException(404)
        db.mark_uploaded(study_uid, datetime.now(timezone.utc).isoformat())
        runtime.exporter.report_to_hub()
        return {"ok": True}

    @app.post("/api/studies/{study_uid}/open-folder")
    def open_folder(study_uid: str):
        study = db.get_study(study_uid)
        if not study or not study.get("folder"):
            raise HTTPException(404)
        folder = Path(study["folder"])
        if not folder.exists():
            raise HTTPException(404, "Folder no longer exists")
        system = platform.system()
        if system == "Windows":
            subprocess.Popen(["explorer", str(folder)])
        elif system == "Darwin":
            subprocess.Popen(["open", str(folder)])
        else:
            subprocess.Popen(["xdg-open", str(folder)])
        return {"ok": True}

    @app.post("/api/sync-now")
    def sync_now():
        runtime.request_worklist_sync()
        return {"ok": True}

    return app
