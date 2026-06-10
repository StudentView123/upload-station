#!/usr/bin/env python3
"""Pretend to be an imaging device: query the station's worklist (C-FIND),
then capture and send a test image (C-STORE) — the same two operations real
equipment performs.

    python3 scripts/simulate_modality.py --host 127.0.0.1 --port 4242
"""

import argparse
import sys
from datetime import datetime

import numpy as np
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, SecondaryCaptureImageStorage, generate_uid
from pynetdicom import AE
from pynetdicom.sop_class import ModalityWorklistInformationFind


def query_worklist(host: str, port: int, called_aet: str) -> list[Dataset]:
    ae = AE(ae_title="TESTSCOPE")
    ae.add_requested_context(ModalityWorklistInformationFind)
    assoc = ae.associate(host, port, ae_title=called_aet)
    if not assoc.is_established:
        sys.exit("Could not associate with the station for C-FIND (worklist).")

    query = Dataset()
    query.PatientName = ""
    query.PatientID = ""
    query.PatientBirthDate = ""
    query.PatientSex = ""
    query.AccessionNumber = ""
    query.StudyInstanceUID = ""
    sps = Dataset()
    sps.Modality = "OT"
    sps.ScheduledProcedureStepStartDate = datetime.now().strftime("%Y%m%d")
    sps.ScheduledProcedureStepStartTime = ""
    sps.ScheduledPerformingPhysicianName = ""
    query.ScheduledProcedureStepSequence = [sps]

    results = []
    for status, ds in assoc.send_c_find(query, ModalityWorklistInformationFind):
        if status and status.Status in (0xFF00, 0xFF01) and ds is not None:
            results.append(ds)
    assoc.release()
    return results


def make_test_image(wl: Dataset) -> Dataset:
    """A small Secondary Capture image carrying the worklist's patient/study IDs."""
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = SecondaryCaptureImageStorage
    meta.MediaStorageSOPInstanceUID = generate_uid()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian

    ds = Dataset()
    ds.file_meta = meta
    ds.SOPClassUID = SecondaryCaptureImageStorage
    ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
    ds.PatientName = wl.PatientName
    ds.PatientID = wl.PatientID
    ds.PatientBirthDate = getattr(wl, "PatientBirthDate", "")
    ds.PatientSex = getattr(wl, "PatientSex", "")
    ds.AccessionNumber = getattr(wl, "AccessionNumber", "")
    ds.StudyInstanceUID = wl.StudyInstanceUID
    ds.SeriesInstanceUID = generate_uid()
    ds.StudyID = "1"
    ds.SeriesNumber = 1
    ds.InstanceNumber = 1
    ds.Modality = "OT"
    ds.StudyDescription = "Upload Station test capture"
    now = datetime.now()
    ds.StudyDate = now.strftime("%Y%m%d")
    ds.StudyTime = now.strftime("%H%M%S")
    ds.ConversionType = "SYN"

    pixels = np.tile(np.linspace(0, 255, 128, dtype=np.uint8), (128, 1))
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.Rows, ds.Columns = pixels.shape
    ds.BitsAllocated = 8
    ds.BitsStored = 8
    ds.HighBit = 7
    ds.PixelRepresentation = 0
    ds.PixelData = pixels.tobytes()
    return ds


def send_image(host: str, port: int, called_aet: str, ds: Dataset) -> None:
    ae = AE(ae_title="TESTSCOPE")
    ae.add_requested_context(SecondaryCaptureImageStorage, ExplicitVRLittleEndian)
    assoc = ae.associate(host, port, ae_title=called_aet)
    if not assoc.is_established:
        sys.exit("Could not associate with the station for C-STORE (image send).")
    status = assoc.send_c_store(ds)
    assoc.release()
    if not status or status.Status != 0x0000:
        sys.exit(f"C-STORE failed: {status}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4242)
    parser.add_argument("--aet", default="UPLOADSTATION", help="Called AE title of the station")
    parser.add_argument("--pick", type=int, default=0, help="Worklist entry index to image")
    args = parser.parse_args()

    print(f"Querying worklist at {args.host}:{args.port} ({args.aet})...")
    entries = query_worklist(args.host, args.port, args.aet)
    if not entries:
        sys.exit("Worklist is empty — has the station synced a schedule?")
    print(f"Found {len(entries)} worklist entries:")
    for i, e in enumerate(entries):
        sps = e.ScheduledProcedureStepSequence[0]
        print(f"  [{i}] {e.PatientName}  ID={e.PatientID}  ACC={e.AccessionNumber}  "
              f"{sps.ScheduledProcedureStepStartTime} {sps.Modality}")

    wl = entries[args.pick]
    print(f"\nCapturing test image for {wl.PatientName} and sending via C-STORE...")
    send_image(args.host, args.port, args.aet, make_test_image(wl))
    print("Image sent. Check the Upload Station UI and images folder.")
