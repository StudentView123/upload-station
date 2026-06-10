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

TOKEN = "test-token"

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

    def do_GET(self):
        if self.path != "/dicom-worklist":
            return self._send(404, {"error": "not found"})
        if not self._authed():
            return self._send(401, {"error": "bad token"})
        self._send(200, build_worklist())

    def do_POST(self):
        if self.path != "/dicom-studies":
            return self._send(404, {"error": "not found"})
        if not self._authed():
            return self._send(401, {"error": "bad token"})
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        print("\n=== Station reported studies ===")
        print(json.dumps(body, indent=2))
        results = [
            {"study_instance_uid": s.get("study_instance_uid"), "ok": True}
            for s in body.get("studies", [])
        ]
        self._send(200, {"results": results})

    def log_message(self, fmt, *args):
        print(f"[mock-hub] {fmt % args}")


if __name__ == "__main__":
    print("Mock Practice Hub on http://127.0.0.1:9999 (token: test-token)")
    HTTPServer(("127.0.0.1", 9999), Handler).serve_forever()
