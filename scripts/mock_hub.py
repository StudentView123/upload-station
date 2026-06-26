#!/usr/bin/env python3
"""Mock Practice Hub for local testing.

Serves /dicom-worklist (GET) with a sample schedule and /dicom-studies (POST)
which prints whatever the station reports. Run with:

    python3 scripts/mock_hub.py  # listens on http://127.0.0.1:9999
"""

import hashlib
import json
import uuid
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

TOKEN = "test-token"
STORAGE_DIR = Path(__file__).resolve().parent.parent / "runtime" / "mock_storage"

PATIENTS = [
    {"first": "Maria", "last": "Lopez", "chart": "10241", "dob": "1957-03-14", "gender": "female"},
    {"first": "James", "last": "Carter", "chart": "10242", "dob": "1948-11-02", "gender": "male"},
    {"first": "Priya", "last": "Patel", "chart": "10243", "dob": "1971-07-29", "gender": "female"},
]


def accession(appt_id: str) -> str:
    return "A" + hashlib.sha256(appt_id.encode()).hexdigest()[:12].upper()


def build_worklist() -> dict:
    now = datetime.now().astimezone()
    entries = []
    for i, p in enumerate(PATIENTS):
        appt_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"mock-appt-{p['chart']}"))
        start = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=i)
        entries.append({
            "appointment_id": appt_id,
            "accession_number": accession(appt_id),
            "start_time": start.isoformat(),
            "end_time": (start + timedelta(minutes=30)).isoformat(),
            "provider_name": "Tung",
            "appointment_type": "Comprehensive Exam",
            "status": "scheduled",
            "patient": {
                "chart_number": p["chart"],
                "nextech_patient_id": "nx-" + p["chart"],
                "first_name": p["first"],
                "last_name": p["last"],
                "date_of_birth": p["dob"],
                "gender": p["gender"],
            },
        })
    return {
        "location": {"id": "mock-location", "name": "Test Office"},
        "date": now.strftime("%Y-%m-%d"),
        "entries": entries,
    }


class Handler(BaseHTTPRequestHandler):
    def _authed(self) -> bool:
        return self.headers.get("Authorization") == f"Bearer {TOKEN}"

    def _send(self, code: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self):
        if self.path != "/dicom-worklist":
            return self._send(404, {"error": "not found"})
        if not self._authed():
            return self._send(401, {"error": "bad token"})
        self._send(200, build_worklist())

    def do_POST(self):
        if self.path == "/dicom-enroll":
            body = self._read_body()
            if not body.get("enrollment_code"):
                return self._send(401, {"error": "bad code"})
            print(f"[mock-hub] enrolled device: {body.get('device_name')}")
            return self._send(200, {
                "station_token": TOKEN,
                "location_id": "mock-location",
                "location_name": "Test Office",
            })

        if self.path == "/dicom-upload-url":
            if not self._authed():
                return self._send(401, {"error": "bad token"})
            body = self._read_body()
            study = body.get("study_instance_uid", "study")
            date = body.get("study_date", "nodate")
            uploads = []
            for f in body.get("files", []):
                storage_path = f"mock-location/{date}/{study}/{f['name']}"
                uploads.append({
                    "name": f["name"],
                    "storage_path": storage_path,
                    "put_url": f"http://127.0.0.1:9999/storage/{storage_path}",
                })
            return self._send(200, {"uploads": uploads})

        if self.path == "/dicom-studies":
            if not self._authed():
                return self._send(401, {"error": "bad token"})
            body = self._read_body()
            print("\n=== Station reported studies ===")
            print(json.dumps(body, indent=2))
            log_path = STORAGE_DIR.parent / "hub_posts.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(log_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(body, indent=2) + "\n")
            results = [
                {"study_instance_uid": s.get("study_instance_uid"), "ok": True}
                for s in body.get("studies", [])
            ]
            return self._send(200, {"results": results})

        self._send(404, {"error": "not found"})

    def do_PUT(self):
        if not self.path.startswith("/storage/"):
            return self._send(404, {"error": "not found"})
        rel = self.path[len("/storage/"):]
        dest = STORAGE_DIR / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        length = int(self.headers.get("Content-Length", 0))
        dest.write_bytes(self.rfile.read(length))
        print(f"[mock-hub] stored {rel} ({length} bytes)")
        self._send(200, {"ok": True})

    def log_message(self, fmt, *args):
        print(f"[mock-hub] {fmt % args}")


if __name__ == "__main__":
    print("Mock Practice Hub on http://127.0.0.1:9999 (token: test-token)")
    HTTPServer(("127.0.0.1", 9999), Handler).serve_forever()
