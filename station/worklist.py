"""Translate the Practice Hub schedule into DICOM Modality Worklist (.wl) files
that Orthanc's worklist plugin serves to imaging equipment via C-FIND."""

import logging
import re
from datetime import datetime
from pathlib import Path

from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

from .config import Config

log = logging.getLogger("worklist")

MODALITY_WORKLIST_SOP = "1.2.840.10008.5.1.4.31"


def _ascii(value: str | None) -> str:
    """DICOM PN/LO-safe ASCII: strip diacritics/control chars equipment may reject."""
    if not value:
        return ""
    cleaned = value.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[\\\x00-\x1f]", " ", cleaned).strip()


def _person_name(last: str | None, first: str | None) -> str:
    return f"{_ascii(last)}^{_ascii(first)}"


def _sex_code(gender: str | None) -> str:
    return {"male": "M", "female": "F", "other": "O"}.get((gender or "").lower(), "")


def study_uid_for_appointment(appointment_id: str) -> str:
    """Deterministic StudyInstanceUID so every modality groups into one visit study."""
    return generate_uid(entropy_srcs=[f"upload-station-study:{appointment_id}"])


def build_worklist_dataset(entry: dict, modality: str, cfg: Config) -> Dataset:
    patient = entry.get("patient") or {}
    start = datetime.fromisoformat(entry["start_time"]).astimezone()

    ds = Dataset()
    ds.SpecificCharacterSet = "ISO_IR 100"
    ds.AccessionNumber = _ascii(entry.get("accession_number"))[:16]
    ds.PatientName = _person_name(patient.get("last_name"), patient.get("first_name"))
    ds.PatientID = _ascii(patient.get("chart_number") or patient.get("nextech_patient_id"))[:64]
    dob = patient.get("date_of_birth") or ""
    ds.PatientBirthDate = dob.replace("-", "")
    ds.PatientSex = _sex_code(patient.get("gender"))
    ds.StudyInstanceUID = study_uid_for_appointment(entry["appointment_id"])
    ds.ReferringPhysicianName = _person_name(entry.get("provider_name"), None).rstrip("^")
    ds.RequestedProcedureID = ds.AccessionNumber
    ds.RequestedProcedureDescription = _ascii(entry.get("appointment_type"))[:64]

    sps = Dataset()
    sps.Modality = modality
    # Empty = wildcard so any device AE title matches this entry.
    sps.ScheduledStationAETitle = ""
    sps.ScheduledProcedureStepStartDate = start.strftime("%Y%m%d")
    sps.ScheduledProcedureStepStartTime = start.strftime("%H%M%S")
    sps.ScheduledPerformingPhysicianName = ds.ReferringPhysicianName
    sps.ScheduledProcedureStepDescription = ds.RequestedProcedureDescription
    sps.ScheduledProcedureStepID = f"{ds.AccessionNumber}{modality}"[:16]
    ds.ScheduledProcedureStepSequence = [sps]

    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = MODALITY_WORKLIST_SOP
    meta.MediaStorageSOPInstanceUID = generate_uid(
        entropy_srcs=[f"upload-station-wl:{entry['appointment_id']}:{modality}"]
    )
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.file_meta = meta
    return ds


def write_worklist_files(payload: dict, cfg: Config) -> int:
    """Rewrite the worklist folder from a fresh hub payload. Returns entry count."""
    wl_dir: Path = cfg.worklists_path
    wl_dir.mkdir(parents=True, exist_ok=True)

    written: set[str] = set()
    count = 0
    for entry in payload.get("entries", []):
        if not (entry.get("patient") or {}).get("chart_number") and not (
            entry.get("patient") or {}
        ).get("nextech_patient_id"):
            log.warning("Skipping worklist entry with no patient ID: %s", entry.get("appointment_id"))
            continue
        for modality in cfg.worklist_modalities:
            ds = build_worklist_dataset(entry, modality, cfg)
            name = f"{ds.AccessionNumber}_{modality}.wl"
            tmp = wl_dir / (name + ".tmp")
            ds.save_as(str(tmp), enforce_file_format=True)
            tmp.replace(wl_dir / name)
            written.add(name)
        count += 1

    # Remove stale entries (cancelled appointments, yesterday's schedule).
    for old in wl_dir.glob("*.wl"):
        if old.name not in written:
            old.unlink(missing_ok=True)

    log.info("Worklist updated: %d appointments x %d modalities", count, len(cfg.worklist_modalities))
    return count
