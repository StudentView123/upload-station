"""Watch Orthanc for completed studies, render images, stream them to Practice
Hub (so they're viewable from any computer), and report capture/upload status."""

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

import requests

from .config import Config
from .db import StationDB
from .hub_client import HubClient

log = logging.getLogger("exporter")


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_\-]+", "_", name or "").strip("_") or "UNKNOWN"


def _local_date(iso_ts: str) -> str:
    return datetime.fromisoformat(iso_ts).astimezone().strftime("%Y-%m-%d")


class Exporter:
    def __init__(self, cfg: Config, db: StationDB, hub: HubClient):
        self.cfg = cfg
        self.db = db
        self.hub = hub

    # -- Orthanc REST helpers -------------------------------------------------
    def _get(self, path: str):
        r = requests.get(f"{self.cfg.orthanc_url}{path}", timeout=30)
        r.raise_for_status()
        return r.json()

    def _get_bytes(self, path: str, accept: str | None = None) -> bytes:
        headers = {"Accept": accept} if accept else {}
        r = requests.get(f"{self.cfg.orthanc_url}{path}", headers=headers, timeout=60)
        r.raise_for_status()
        return r.content

    # -- main poll loop body --------------------------------------------------
    def poll_once(self) -> None:
        since = int(self.db.get_meta("orthanc_change_seq", "0"))
        while True:
            changes = self._get(f"/changes?since={since}&limit=100")
            for change in changes["Changes"]:
                if change["ChangeType"] == "StableStudy":
                    try:
                        self.export_study(change["ID"])
                    except Exception:
                        log.exception("Failed to export study %s", change["ID"])
            since = changes["Last"]
            self.db.set_meta("orthanc_change_seq", str(since))
            if changes["Done"]:
                break
        if self.cfg.stream_images_to_hub:
            self.upload_pending_images()
        self.report_to_hub()

    def export_study(self, orthanc_study_id: str) -> None:
        study = self._get(f"/studies/{orthanc_study_id}")
        tags = study.get("MainDicomTags", {})
        ptags = study.get("PatientMainDicomTags", {})
        study_uid = tags.get("StudyInstanceUID")
        if not study_uid:
            return

        patient_name = ptags.get("PatientName", "").replace("^", "_")
        patient_id = ptags.get("PatientID", "")
        captured = datetime.now(timezone.utc)
        date_folder = captured.astimezone().strftime("%Y-%m-%d")
        folder = (
            self.cfg.images_path
            / date_folder
            / f"{_safe(patient_name)}_{_safe(patient_id)}"
        )
        folder.mkdir(parents=True, exist_ok=True)

        # The DICOM original is only written locally if we keep local copies or
        # we intend to upload it; otherwise the rendered PNG is all we need.
        write_dicom = self.cfg.keep_local_copy or self.cfg.upload_dicom_originals

        modalities: set[str] = set()
        files: list[dict] = []
        image_count = 0
        for series_id in study.get("Series", []):
            series = self._get(f"/series/{series_id}")
            modality = series.get("MainDicomTags", {}).get("Modality", "OT")
            modalities.add(modality)
            sdir = folder / _safe(modality)
            sdir.mkdir(exist_ok=True)
            for idx, instance_id in enumerate(series.get("Instances", []), 1):
                stem = f"{_safe(modality)}_{series_id[:8]}_{idx:03d}"

                if write_dicom:
                    dcm_path = sdir / f"{stem}.dcm"
                    if not dcm_path.exists():
                        dcm_path.write_bytes(self._get_bytes(f"/instances/{instance_id}/file"))
                    if self.cfg.upload_dicom_originals:
                        files.append({
                            "name": f"{stem}.dcm", "kind": "dicom", "modality": modality,
                            "content_type": "application/dicom", "local_path": str(dcm_path),
                            "uploaded": False, "storage_path": None,
                        })

                # Rendered PNG: what staff click and upload to the EMR.
                png_path = sdir / f"{stem}.png"
                if not png_path.exists():
                    try:
                        png = self._get_bytes(
                            f"/instances/{instance_id}/rendered", accept="image/png"
                        )
                        png_path.write_bytes(png)
                    except requests.RequestException:
                        png_path = None  # some SOP classes can't be rendered
                if png_path is not None:
                    files.append({
                        "name": f"{stem}.png", "kind": "png", "modality": modality,
                        "content_type": "image/png", "local_path": str(png_path),
                        "uploaded": False, "storage_path": None,
                    })
                image_count += 1

        self.db.upsert_study(
            study_uid=study_uid,
            orthanc_id=orthanc_study_id,
            patient_name=ptags.get("PatientName", ""),
            patient_id=patient_id,
            accession=tags.get("AccessionNumber", ""),
            modalities=",".join(sorted(modalities)),
            description=tags.get("StudyDescription", ""),
            image_count=image_count,
            folder=str(folder),
            captured_at=captured.isoformat(),
            status="captured",
            files_json=json.dumps(files),
        )
        log.info(
            "Exported study for %s (%s): %d images -> %s",
            patient_name, patient_id, image_count, folder,
        )

    # -- image streaming -------------------------------------------------------
    def upload_pending_images(self) -> None:
        for s in self.db.all_studies():
            raw = s.get("files_json")
            if not raw:
                continue
            files = json.loads(raw)
            pending = [f for f in files if not f.get("uploaded")]
            if not pending:
                continue
            study_date = _local_date(s["captured_at"])
            try:
                urls = self.hub.get_upload_urls(
                    s["study_uid"], study_date,
                    [{"name": f["name"], "content_type": f["content_type"]} for f in pending],
                )
            except requests.RequestException as exc:
                log.warning("Could not get upload URLs (will retry): %s", exc)
                continue

            changed = False
            for f in pending:
                target = urls.get(f["name"])
                local = Path(f["local_path"])
                if not target or not local.exists():
                    continue
                try:
                    self.hub.put_file(target["put_url"], local.read_bytes(), f["content_type"])
                except requests.RequestException as exc:
                    log.warning("Image upload failed for %s (will retry): %s", f["name"], exc)
                    continue
                f["uploaded"] = True
                f["storage_path"] = target["storage_path"]
                changed = True
                if not self.cfg.keep_local_copy:
                    local.unlink(missing_ok=True)

            if changed:
                self.db.upsert_study(study_uid=s["study_uid"], files_json=json.dumps(files))
                done = sum(1 for f in files if f.get("uploaded"))
                log.info("Uploaded %d/%d images for study %s", done, len(files), s["study_uid"][:16])

    # -- Practice Hub reporting ------------------------------------------------
    def report_to_hub(self) -> None:
        pending = self.db.unsynced_studies()
        if not pending:
            return
        payload = []
        reported_uids = []
        for s in pending:
            files = json.loads(s["files_json"]) if s.get("files_json") else []
            # When streaming, hold the report until every image is uploaded so
            # the hub never shows a study with missing pictures.
            if self.cfg.stream_images_to_hub and any(not f.get("uploaded") for f in files):
                continue
            entry = {
                "study_instance_uid": s["study_uid"],
                "accession_number": s["accession"] or None,
                "chart_number": s["patient_id"] or None,
                "patient_name": (s["patient_name"] or "").replace("^", ", "),
                "modality": s["modalities"],
                "study_description": s["description"] or None,
                "captured_at": s["captured_at"],
                "image_count": s["image_count"],
                "status": s["status"],
                "uploaded_at": s["uploaded_at"],
            }
            uploaded_files = [
                {"storage_path": f["storage_path"], "kind": f["kind"],
                 "modality": f["modality"], "name": f["name"]}
                for f in files if f.get("uploaded")
            ]
            if uploaded_files:
                entry["files"] = uploaded_files
            payload.append(entry)
            reported_uids.append(s["study_uid"])

        if payload and self.hub.post_studies(payload):
            self.db.mark_hub_synced(reported_uids)
            log.info("Reported %d studies to Practice Hub", len(payload))
