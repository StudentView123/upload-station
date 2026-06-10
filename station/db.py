"""Tiny sqlite store: received studies, worklist cache, Orthanc change cursor."""

import json
import sqlite3
import threading
from pathlib import Path


class StationDB:
    def __init__(self, path: Path):
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock, self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS studies (
                    study_uid     TEXT PRIMARY KEY,
                    orthanc_id    TEXT,
                    patient_name  TEXT,
                    patient_id    TEXT,
                    accession     TEXT,
                    modalities    TEXT,
                    description   TEXT,
                    image_count   INTEGER DEFAULT 0,
                    folder        TEXT,
                    captured_at   TEXT,
                    status        TEXT DEFAULT 'captured',
                    uploaded_at   TEXT,
                    hub_synced    INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS meta (
                    key   TEXT PRIMARY KEY,
                    value TEXT
                );
                """
            )

    # -- meta ---------------------------------------------------------------
    def get_meta(self, key: str, default: str | None = None) -> str | None:
        with self._lock:
            row = self._conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_meta(self, key: str, value: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO meta(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    # -- worklist cache (for the local UI) ----------------------------------
    def save_worklist(self, payload: dict) -> None:
        self.set_meta("worklist", json.dumps(payload))

    def load_worklist(self) -> dict | None:
        raw = self.get_meta("worklist")
        return json.loads(raw) if raw else None

    # -- studies -------------------------------------------------------------
    def upsert_study(self, **fields) -> None:
        study_uid = fields.pop("study_uid")
        with self._lock, self._conn:
            existing = self._conn.execute(
                "SELECT status FROM studies WHERE study_uid=?", (study_uid,)
            ).fetchone()
            if existing is None:
                cols = ["study_uid"] + list(fields.keys())
                sql = (
                    f"INSERT INTO studies ({','.join(cols)}) "
                    f"VALUES ({','.join('?' for _ in cols)})"
                )
                self._conn.execute(sql, [study_uid] + list(fields.values()))
            else:
                # Never downgrade an 'uploaded' study back to 'captured'.
                if existing["status"] == "uploaded":
                    fields.pop("status", None)
                if fields:
                    sets = ",".join(f"{k}=?" for k in fields)
                    self._conn.execute(
                        f"UPDATE studies SET {sets}, hub_synced=0 WHERE study_uid=?",
                        list(fields.values()) + [study_uid],
                    )

    def mark_uploaded(self, study_uid: str, uploaded_at: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE studies SET status='uploaded', uploaded_at=?, hub_synced=0 "
                "WHERE study_uid=?",
                (uploaded_at, study_uid),
            )

    def mark_hub_synced(self, study_uids: list[str]) -> None:
        with self._lock, self._conn:
            self._conn.executemany(
                "UPDATE studies SET hub_synced=1 WHERE study_uid=?",
                [(u,) for u in study_uids],
            )

    def unsynced_studies(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM studies WHERE hub_synced=0"
            ).fetchall()
        return [dict(r) for r in rows]

    def all_studies(self, limit: int = 200) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM studies ORDER BY captured_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def get_study(self, study_uid: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM studies WHERE study_uid=?", (study_uid,)
            ).fetchone()
        return dict(row) if row else None
