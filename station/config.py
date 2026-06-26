"""Station configuration loaded from / saved to config.json.

Supports three interchangeable ways to authenticate to Practice Hub:
  - "token"  : a reusable per-office station token (pasted by the user)
  - "enroll" : a reusable per-office enrollment code that the station exchanges
               (once, via dicom-enroll) for its own per-device station token
  - "login"  : a Practice Hub login (Supabase session) + a chosen location
"""

import json
import os
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Production Practice Hub. The anon/publishable key is safe to embed (it is the
# public client key); it is only used for the optional login auth mode.
DEFAULT_HUB_BASE_URL = "https://iqbszdfexefwursnocgb.supabase.co/functions/v1"
DEFAULT_SUPABASE_ANON_KEY = ""


def is_frozen() -> bool:
    """True when running from a PyInstaller-built executable."""
    return bool(getattr(sys, "frozen", False))


def app_dir() -> Path:
    """Folder that holds config.json and the bundled vendor/ binaries.

    When frozen (PyInstaller), this is the directory of the executable — i.e.
    the install directory (C:\\UploadStation) where the installer also placed
    config.json and vendor/. In development it's the repo root.
    """
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return REPO_ROOT


@dataclass
class Config:
    hub_base_url: str = DEFAULT_HUB_BASE_URL
    supabase_anon_key: str = DEFAULT_SUPABASE_ANON_KEY
    station_name: str = "Upload Station"

    # Authentication. auth_mode is one of: "token", "enroll", "login".
    auth_mode: str = "token"
    station_token: str = ""          # token mode, and enroll mode after enrollment
    enrollment_code: str = ""        # enroll mode (exchanged for a token on first run)
    hub_refresh_token: str = ""      # login mode (persisted Supabase session)
    selected_location_id: str = ""   # login mode (which office this machine serves)
    selected_location_name: str = ""

    aet: str = "UPLOADSTATION"
    dicom_port: int = 4242
    ui_port: int = 8088
    orthanc_http_port: int = 8042

    images_dir: str = "~/UploadStation/Images"
    data_dir: str = "~/UploadStation/Data"

    worklist_modalities: list = field(default_factory=lambda: ["OPT", "OP", "OPV", "OT"])
    worklist_refresh_seconds: int = 300
    export_poll_seconds: int = 10

    stream_images_to_hub: bool = True
    upload_dicom_originals: bool = False
    keep_local_copy: bool = True
    local_ui_enabled: bool = True

    orthanc_executable: str | None = None

    # -- derived paths --------------------------------------------------------
    @property
    def images_path(self) -> Path:
        return Path(self.images_dir).expanduser().resolve()

    @property
    def data_path(self) -> Path:
        return Path(self.data_dir).expanduser().resolve()

    @property
    def worklists_path(self) -> Path:
        return self.data_path / "worklists"

    @property
    def orthanc_url(self) -> str:
        return f"http://127.0.0.1:{self.orthanc_http_port}"

    @property
    def supabase_url(self) -> str:
        """Base Supabase URL (for auth/rest), derived from the functions URL."""
        base = self.hub_base_url.rstrip("/")
        for suffix in ("/functions/v1", "/functions"):
            if base.endswith(suffix):
                return base[: -len(suffix)]
        return base

    # -- state ----------------------------------------------------------------
    def is_configured(self) -> bool:
        """True when the station has a usable credential for its auth mode."""
        if self.auth_mode == "token":
            return bool(self.station_token)
        if self.auth_mode == "enroll":
            # Either already enrolled (have a token) or have a code to enroll with.
            return bool(self.station_token or self.enrollment_code)
        if self.auth_mode == "login":
            return bool(self.hub_refresh_token and self.selected_location_id)
        return False

    def ensure_dirs(self) -> None:
        for p in (self.images_path, self.data_path, self.worklists_path):
            p.mkdir(parents=True, exist_ok=True)

    def to_dict(self) -> dict:
        return asdict(self)

    def save(self) -> None:
        path = config_file_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")


def config_file_path() -> Path:
    env = os.environ.get("UPLOAD_STATION_CONFIG")
    if env:
        return Path(env).expanduser()
    return app_dir() / "config.json"


def load_config() -> Config:
    """Load config.json, falling back to defaults. Never exits — an unconfigured
    station boots into setup mode so the user can connect it from the web page."""
    path = config_file_path()
    raw = {}
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except (json.JSONDecodeError, OSError):
            raw = {}
    known = {k: v for k, v in raw.items() if k in Config.__dataclass_fields__}
    cfg = Config(**known)
    cfg.hub_base_url = (cfg.hub_base_url or DEFAULT_HUB_BASE_URL).rstrip("/")
    if not cfg.supabase_anon_key:
        cfg.supabase_anon_key = DEFAULT_SUPABASE_ANON_KEY
    cfg.ensure_dirs()
    return cfg
