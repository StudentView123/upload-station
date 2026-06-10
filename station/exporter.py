"""Watch Orthanc for completed studies, export them to the local images folder,
and report capture/upload status back to Practice Hub."""

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

        modalities: set[str] = set()
        image_count = 0
        for series_id in study.get("Series", []):
            series = self._get(f"/series/{series_id}")
            modality = series.get("MainDicomTags", {}).get("Modality", "OT")
            modalities.add(modality)
            sdir = folder / _safe(modality)
            sdir.mkdir(exist_ok=True)
            for idx, instance_id in enumerate(series.get("Instances", []), 1):
                stem = f"{_safe(modality)}_{series_id[:8]}_{idx:03d}"
                dcm_path = sdir / f"{stem}.dcm"
                if not dcm_path.exists():
                    dcm_path.write_bytes(self._get_bytes(f"/instances/{instance_id}/file"))
                # Friendly PNG for quick manual upload to the EMR; some SOP
                # classes (raw volumes) can't be rendered — DICOM is kept anyway.
                png_path = sdir / f"{stem}.png"
                if not png_path.exists():
                    try:
                        png = self._get_bytes(
                            f"/instances/{instance_id}/rendered", accept="image/png"
                        )
                        png_path.write_bytes(png)
                    except requests.RequestException:
                        pass
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
        )
        log.info(
            "Exported study for %s (%s): %d images -> %s",
            patient_name, patient_id, image_count, folder,
        )

    # -- Practice Hub reporting ------------------------------------------------
    def report_to_hub(self) -> None:
        pending = self.db.unsynced_studies()
        if not pending:
            return
        payload = [
            {
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
            for s in pending
        ]
        if self.hub.post_studies(payload):
            self.db.mark_hub_synced([s["study_uid"] for s in pending])
            log.info("Reported %d studies to Practice Hub", len(pending))
