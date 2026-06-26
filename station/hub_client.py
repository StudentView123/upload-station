"""HTTPS client for the Practice Hub edge functions.

Supports three authentication modes (see config.Config.auth_mode):
  - token / enroll : Authorization: Bearer <station_token>
  - login          : Authorization: Bearer <supabase access jwt> + X-Location-Id

For enroll mode the station first exchanges its enrollment code for a per-device
token via dicom-enroll. For login mode it keeps a Supabase session alive using
the persisted refresh token and auto-refreshes on 401.
"""

import logging
import socket
from typing import Callable

import requests

from .config import Config

log = logging.getLogger("hub")


class HubError(Exception):
    pass


class HubClient:
    def __init__(self, cfg: Config, on_config_change: Callable[[], None] | None = None):
        self.cfg = cfg
        self._on_config_change = on_config_change
        self._access_token: str | None = None  # login mode, in-memory

    # -- auth plumbing --------------------------------------------------------
    def _auth_headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.cfg.auth_mode == "login":
            if not self._access_token:
                self._refresh_login()
            headers["Authorization"] = f"Bearer {self._access_token}"
            headers["X-Location-Id"] = self.cfg.selected_location_id
        else:
            headers["Authorization"] = f"Bearer {self.cfg.station_token}"
        return headers

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        url = f"{self.cfg.hub_base_url}/{path.lstrip('/')}"
        headers = self._auth_headers()
        headers.update(kwargs.pop("headers", {}))
        resp = requests.request(method, url, headers=headers, timeout=kwargs.pop("timeout", 30), **kwargs)
        # In login mode an expired access token returns 401 — refresh once, retry.
        if resp.status_code == 401 and self.cfg.auth_mode == "login":
            self._refresh_login(force=True)
            headers["Authorization"] = f"Bearer {self._access_token}"
            resp = requests.request(method, url, headers=headers, timeout=30, **kwargs)
        return resp

    # -- enrollment (mode B, first run) ---------------------------------------
    def enroll(self, enrollment_code: str, device_name: str | None = None) -> dict:
        """Exchange a reusable enrollment code for this device's own station token.

        Returns {"station_token", "location_id", "location_name"} and is the
        caller's responsibility to persist into config (station_token).
        """
        device_name = device_name or socket.gethostname() or "Upload Station"
        resp = requests.post(
            f"{self.cfg.hub_base_url}/dicom-enroll",
            json={"enrollment_code": enrollment_code.strip(), "device_name": device_name},
            timeout=30,
        )
        if resp.status_code == 401:
            raise HubError("That enrollment code was not accepted (check it is active).")
        resp.raise_for_status()
        return resp.json()

    # -- login (mode C) -------------------------------------------------------
    def _auth_endpoint(self, path: str) -> str:
        return f"{self.cfg.supabase_url}/auth/v1/{path.lstrip('/')}"

    def login(self, email: str, password: str) -> dict:
        """Sign in to Practice Hub (Supabase). Returns the gotrue token payload
        including access_token, refresh_token and user. Does not persist."""
        if not self.cfg.supabase_anon_key:
            raise HubError("Login is not available (missing Supabase key in this build).")
        resp = requests.post(
            self._auth_endpoint("token?grant_type=password"),
            headers={"apikey": self.cfg.supabase_anon_key, "Content-Type": "application/json"},
            json={"email": email, "password": password},
            timeout=30,
        )
        if resp.status_code in (400, 401):
            raise HubError("Incorrect email or password.")
        resp.raise_for_status()
        data = resp.json()
        self._access_token = data.get("access_token")
        return data

    def _refresh_login(self, force: bool = False) -> None:
        if not self.cfg.hub_refresh_token:
            raise HubError("Not logged in.")
        resp = requests.post(
            self._auth_endpoint("token?grant_type=refresh_token"),
            headers={"apikey": self.cfg.supabase_anon_key, "Content-Type": "application/json"},
            json={"refresh_token": self.cfg.hub_refresh_token},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        self._access_token = data.get("access_token")
        # gotrue rotates refresh tokens; persist the new one.
        new_refresh = data.get("refresh_token")
        if new_refresh and new_refresh != self.cfg.hub_refresh_token:
            self.cfg.hub_refresh_token = new_refresh
            if self._on_config_change:
                self._on_config_change()

    def list_locations(self, access_token: str) -> list[dict]:
        """Active locations the logged-in user can choose from (for the office picker)."""
        resp = requests.get(
            f"{self.cfg.supabase_url}/rest/v1/locations",
            headers={
                "apikey": self.cfg.supabase_anon_key,
                "Authorization": f"Bearer {access_token}",
            },
            params={"select": "id,name,is_active", "is_active": "eq.true", "order": "name"},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    # -- imaging endpoints ----------------------------------------------------
    def get_worklist(self) -> dict:
        resp = self._request("GET", "dicom-worklist")
        resp.raise_for_status()
        return resp.json()

    def post_studies(self, studies: list[dict]) -> bool:
        if not studies:
            return True
        try:
            resp = self._request("POST", "dicom-studies", json={"studies": studies})
            resp.raise_for_status()
            return True
        except requests.RequestException as exc:
            log.warning("Could not report studies to Practice Hub (will retry): %s", exc)
            return False

    def get_upload_urls(self, study_uid: str, study_date: str, files: list[dict]) -> list[dict]:
        resp = self._request(
            "POST", "dicom-upload-url",
            json={"study_instance_uid": study_uid, "study_date": study_date, "files": files},
        )
        resp.raise_for_status()
        return resp.json().get("uploads", [])

    def put_file(self, put_url: str, data: bytes, content_type: str) -> None:
        """Upload raw bytes to a signed storage URL (no auth header — the URL is signed)."""
        resp = requests.put(
            put_url, data=data,
            headers={"Content-Type": content_type, "x-upsert": "true"},
            timeout=120,
        )
        resp.raise_for_status()
