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
