"""Local web UI.

Two faces, chosen by whether the station is connected to Practice Hub:
  - Setup page: connect via token, enrollment code, or login (first run / reconfigure).
  - Dashboard: today's worklist, received studies, mark-uploaded queue.
"""

import logging
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from .config import Config
from .db import StationDB
from .hub_client import HubError

log = logging.getLogger("web")

DASHBOARD = """<!doctype html>
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
  a.meta { text-decoration:none; }
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
  <a class="meta" href="/setup">Connection settings</a>
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
  if (study.status === 'uploaded') return '<span class="chip ok">Uploaded to EMR</span>';
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
    renderWorklist(state); renderOrphans(state);
  } catch (e) {}
}
async function markUploaded(uid){ await fetch(`/api/studies/${encodeURIComponent(uid)}/uploaded`,{method:'POST'}); refresh(); }
async function openFolder(uid){ await fetch(`/api/studies/${encodeURIComponent(uid)}/open-folder`,{method:'POST'}); }
async function syncNow(){ await fetch('/api/sync-now',{method:'POST'}); setTimeout(refresh,1500); }
refresh(); setInterval(refresh, 10000);
</script>
</body>
</html>"""

SETUP_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Connect Upload Station</title>
<style>
  :root { --bg:#f5f6f8; --card:#fff; --ink:#1c2430; --mut:#69788c; --line:#e3e8ef;
          --accent:#1f5eff; --ok:#0f7b46; --err:#c0392b; }
  * { box-sizing:border-box; }
  body { margin:0; font:15px/1.5 -apple-system,"Segoe UI",Roboto,sans-serif;
         background:var(--bg); color:var(--ink); }
  .wrap { max-width:560px; margin:48px auto; padding:0 20px; }
  h1 { font-size:22px; margin:0 0 4px; }
  p.lead { color:var(--mut); margin:0 0 24px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:22px; }
  .tabs { display:flex; gap:6px; margin-bottom:20px; }
  .tab { flex:1; text-align:center; padding:9px; border:1px solid var(--line); border-radius:8px;
         cursor:pointer; font-size:13px; font-weight:600; color:var(--mut); background:#fafbfc; }
  .tab.active { background:var(--accent); border-color:var(--accent); color:#fff; }
  label { display:block; font-size:13px; font-weight:600; margin:14px 0 5px; }
  input, select { width:100%; padding:10px 12px; border:1px solid var(--line); border-radius:8px; font:inherit; }
  .hint { color:var(--mut); font-size:12.5px; margin-top:6px; }
  button.go { margin-top:18px; width:100%; padding:11px; border:none; border-radius:8px;
              background:var(--accent); color:#fff; font:600 15px inherit; cursor:pointer; }
  button.go:disabled { opacity:.5; cursor:default; }
  .pane { display:none; } .pane.active { display:block; }
  .msg { margin-top:14px; padding:10px 12px; border-radius:8px; font-size:13.5px; display:none; }
  .msg.err { display:block; background:#fdecea; color:var(--err); }
  .msg.ok  { display:block; background:#e2f5ea; color:var(--ok); }
  .current { font-size:13px; color:var(--mut); margin-bottom:16px; }
</style>
</head>
<body>
<div class="wrap">
  <h1>Connect this Upload Station</h1>
  <p class="lead">Pick one method. You only do this once on this computer.</p>
  <div class="card">
    <div class="current" id="current"></div>
    <div class="tabs">
      <div class="tab active" data-pane="token" onclick="tab('token')">Token</div>
      <div class="tab" data-pane="enroll" onclick="tab('enroll')">Enrollment code</div>
      <div class="tab" data-pane="login" onclick="tab('login')">Log in</div>
    </div>

    <div class="pane active" id="pane-token">
      <label>Station name (optional)</label>
      <input id="t-name" placeholder="e.g. Great Neck OCT">
      <label>Office token</label>
      <input id="t-token" placeholder="Paste the token from Practice Hub → Imaging → Stations">
      <div class="hint">Reusable per office. The same token can be used on every computer in that office.</div>
      <button class="go" onclick="submitToken()">Connect with token</button>
    </div>

    <div class="pane" id="pane-enroll">
      <label>Station name (optional)</label>
      <input id="e-name" placeholder="e.g. Great Neck OCT">
      <label>Enrollment code</label>
      <input id="e-code" placeholder="Paste the office enrollment code">
      <div class="hint">Reusable per office. Each computer registers itself automatically and gets its own identity.</div>
      <button class="go" onclick="submitEnroll()">Connect with code</button>
    </div>

    <div class="pane" id="pane-login">
      <label>Practice Hub email</label>
      <input id="l-email" type="email" placeholder="you@practice.com">
      <label>Password</label>
      <input id="l-pass" type="password" placeholder="Your Practice Hub password">
      <button class="go" id="l-btn" onclick="submitLogin()">Log in</button>
      <div id="l-locwrap" style="display:none">
        <label>Which office is this computer in?</label>
        <select id="l-loc"></select>
        <label>Station name (optional)</label>
        <input id="l-name" placeholder="e.g. Great Neck OCT">
        <button class="go" onclick="submitLoginSelect()">Connect this office</button>
      </div>
    </div>

    <div class="msg" id="msg"></div>
  </div>
</div>
<script>
let cur = 'token';
function tab(name){ cur=name;
  document.querySelectorAll('.tab').forEach(t=>t.classList.toggle('active', t.dataset.pane===name));
  document.querySelectorAll('.pane').forEach(p=>p.classList.remove('active'));
  document.getElementById('pane-'+name).classList.add('active');
  hide();
}
function show(t, ok){ const m=document.getElementById('msg'); m.className='msg '+(ok?'ok':'err'); m.textContent=t; }
function hide(){ document.getElementById('msg').className='msg'; }
function connected(name){ show('Connected to '+name+'. Starting the station…', true); setTimeout(()=>location.href='/', 4500); }

async function post(url, body){
  const r = await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  let d={}; try{ d=await r.json(); }catch(e){}
  if(!r.ok) throw new Error(d.error || 'Something went wrong.');
  return d;
}
async function submitToken(){ hide();
  try{ const d=await post('/api/setup/token',{token:val('t-token'),station_name:val('t-name')});
    connected(d.location_name || val('t-name') || 'Practice Hub'); }
  catch(e){ show(e.message,false); } }
async function submitEnroll(){ hide();
  try{ const d=await post('/api/setup/enroll',{code:val('e-code'),station_name:val('e-name')});
    connected(d.location_name || 'this office'); }
  catch(e){ show(e.message,false); } }
async function submitLogin(){ hide();
  try{ const d=await post('/api/setup/login',{email:val('l-email'),password:val('l-pass')});
    const sel=document.getElementById('l-loc'); sel.innerHTML='';
    (d.locations||[]).forEach(l=>{ const o=document.createElement('option'); o.value=l.id; o.textContent=l.name; o.dataset.name=l.name; sel.appendChild(o); });
    document.getElementById('l-locwrap').style.display='block';
    document.getElementById('l-btn').style.display='none';
    show('Logged in. Choose this computer\\'s office.', true); }
  catch(e){ show(e.message,false); } }
async function submitLoginSelect(){ hide();
  const sel=document.getElementById('l-loc'); const opt=sel.options[sel.selectedIndex];
  try{ const d=await post('/api/setup/login-select',{location_id:sel.value,location_name:opt?opt.dataset.name:'',station_name:val('l-name')});
    connected(opt?opt.dataset.name:'this office'); }
  catch(e){ show(e.message,false); } }
function val(id){ return document.getElementById(id).value.trim(); }

(async()=>{ try{ const i=await (await fetch('/api/setup/info')).json();
  if(i.configured) document.getElementById('current').textContent =
    'Currently connected: '+(i.location_name||i.station_name||'')+' ('+i.auth_mode+'). Reconnect below to change.';
  if(!i.login_available){ const lt=document.querySelector('.tab[data-pane=login]'); if(lt) lt.style.display='none'; }
}catch(e){} })();
</script>
</body>
</html>"""


class TokenBody(BaseModel):
    token: str
    station_name: str = ""


class EnrollBody(BaseModel):
    code: str
    station_name: str = ""


class LoginBody(BaseModel):
    email: str
    password: str


class LoginSelectBody(BaseModel):
    location_id: str
    location_name: str = ""
    station_name: str = ""


def create_app(cfg: Config, db: StationDB, runtime) -> FastAPI:
    """`runtime` is the StationRuntime (setup actions + orthanc + hub)."""
    app = FastAPI(title="Upload Station", docs_url=None, redoc_url=None)

    @app.get("/", response_class=HTMLResponse)
    def index():
        return SETUP_PAGE if runtime.setup_mode else DASHBOARD

    @app.get("/setup", response_class=HTMLResponse)
    def setup():
        return SETUP_PAGE

    # ---- setup API ----------------------------------------------------------
    @app.get("/api/setup/info")
    def setup_info():
        return {
            "configured": not runtime.setup_mode,
            "auth_mode": cfg.auth_mode,
            "station_name": cfg.station_name,
            "location_name": cfg.selected_location_name,
            "login_available": bool(cfg.supabase_anon_key),
        }

    @app.post("/api/setup/token")
    def setup_token(body: TokenBody):
        if not body.token.strip():
            raise HTTPException(400, "Please paste a token.")
        runtime.apply_token(body.token, body.station_name)
        return {"ok": True, "location_name": body.station_name}

    @app.post("/api/setup/enroll")
    def setup_enroll(body: EnrollBody):
        if not body.code.strip():
            raise HTTPException(400, "Please paste an enrollment code.")
        try:
            result = runtime.apply_enroll(body.code, body.station_name)
        except HubError as exc:
            raise HTTPException(400, str(exc))
        except Exception as exc:
            raise HTTPException(400, f"Could not reach Practice Hub: {exc}")
        return {"ok": True, "location_name": result.get("location_name", "")}

    @app.post("/api/setup/login")
    def setup_login(body: LoginBody):
        try:
            locations = runtime.begin_login(body.email, body.password)
        except HubError as exc:
            raise HTTPException(400, str(exc))
        except Exception as exc:
            raise HTTPException(400, f"Could not reach Practice Hub: {exc}")
        return {"ok": True, "locations": locations}

    @app.post("/api/setup/login-select")
    def setup_login_select(body: LoginSelectBody):
        if not body.location_id:
            raise HTTPException(400, "Please choose an office.")
        try:
            runtime.complete_login(body.location_id, body.location_name, body.station_name)
        except HubError as exc:
            raise HTTPException(400, str(exc))
        return {"ok": True, "location_name": body.location_name}

    # ---- dashboard API ------------------------------------------------------
    @app.get("/api/state")
    def state():
        worklist = db.load_worklist() or {}
        return JSONResponse({
            "location_name": (worklist.get("location") or {}).get("name") or cfg.selected_location_name,
            "date": worklist.get("date"),
            "worklist": worklist,
            "studies": db.all_studies(),
            "last_worklist_sync": db.get_meta("last_worklist_sync"),
            "hub_ok": db.get_meta("hub_ok") == "1",
            "dicom_ok": runtime.orthanc.is_running() if runtime.orthanc else False,
        })

    @app.post("/api/studies/{study_uid}/uploaded")
    def mark_uploaded(study_uid: str):
        if not db.get_study(study_uid):
            raise HTTPException(404)
        db.mark_uploaded(study_uid, datetime.now(timezone.utc).isoformat())
        if runtime.exporter:
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
