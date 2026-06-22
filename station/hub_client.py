"""HTTPS client for the Practice Hub edge functions (dicom-worklist / dicom-studies)."""

import logging

import requests

from .config import Config

log = logging.getLogger("hub")


class HubClient:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {cfg.station_token}",
            "Content-Type": "application/json",
        })

    def get_worklist(self) -> dict:
        """Fetch today's schedule for this station's office.

        Returns {"location": {...}, "date": "...", "entries": [...]}.
        Raises on network/auth errors so callers can keep the previous worklist.
        """
        resp = self.session.get(f"{self.cfg.hub_base_url}/dicom-worklist", timeout=30)
        resp.raise_for_status()
        return resp.json()

    def post_studies(self, studies: list[dict]) -> bool:
        """Report captured/uploaded studies back to Practice Hub. Returns True on success."""
        if not studies:
            return True
        try:
            resp = self.session.post(
                f"{self.cfg.hub_base_url}/dicom-studies",
                json={"studies": studies},
                timeout=30,
            )
            resp.raise_for_status()
            return True
        except requests.RequestException as exc:
            log.warning("Could not report studies to Practice Hub (will retry): %s", exc)
            return False

    def get_upload_urls(self, study_uid: str, study_date: str, files: list[dict]) -> list[dict]:
        """Ask Practice Hub for signed upload URLs for image files.

        `files` is [{"name", "content_type"}]. Returns the `uploads` list in the
        same order as requested — each item is {"name", "storage_path", "put_url"}.
        The hub may sanitize names, so callers should match positionally and use
        the returned storage_path/name verbatim. Raises on failure to retry later.
        """
        resp = self.session.post(
            f"{self.cfg.hub_base_url}/dicom-upload-url",
            json={"study_instance_uid": study_uid, "study_date": study_date, "files": files},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json().get("uploads", [])

    def put_file(self, put_url: str, data: bytes, content_type: str) -> None:
        """Upload raw bytes to a signed storage URL.

        Uses a bare request (not the authenticated session) so the station
        token is never sent to the storage endpoint.
        """
        resp = requests.put(
            put_url,
            data=data,
            headers={"Content-Type": content_type, "x-upsert": "true"},
            timeout=120,
        )
        resp.raise_for_status()
