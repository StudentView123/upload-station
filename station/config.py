"""Station configuration loaded from config.json."""

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Config:
    hub_base_url: str = ""
    station_token: str = ""
    station_name: str = "Upload Station"

    aet: str = "UPLOADSTATION"
    dicom_port: int = 4242
    ui_port: int = 8088
    orthanc_http_port: int = 8042

    images_dir: str = "~/UploadStation/Images"
    data_dir: str = "~/UploadStation/Data"

    worklist_modalities: list = field(default_factory=lambda: ["OPT", "OP", "OPV", "OT"])
    worklist_refresh_seconds: int = 300
    export_poll_seconds: int = 10

    # Stream captured images to Practice Hub so they're viewable from any
    # computer. When True the relay uploads the rendered PNGs (and optionally the
    # DICOM originals) to the hub's private storage and registers them.
    stream_images_to_hub: bool = True
    upload_dicom_originals: bool = False
    keep_local_copy: bool = True
    # The local web UI is optional once images live in Practice Hub. Left on by
    # default as an on-site health/fallback view; set False for a headless relay.
    local_ui_enabled: bool = True

    orthanc_executable: str | None = None

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

    def ensure_dirs(self) -> None:
        for p in (self.images_path, self.data_path, self.worklists_path):
            p.mkdir(parents=True, exist_ok=True)


def config_file_path() -> Path:
    env = os.environ.get("UPLOAD_STATION_CONFIG")
    if env:
        return Path(env).expanduser()
    return REPO_ROOT / "config.json"


def load_config() -> Config:
    path = config_file_path()
    if not path.exists():
        print(f"Config file not found: {path}", file=sys.stderr)
        print("Copy config.example.json to config.json and fill in your station token.", file=sys.stderr)
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    known = {k: v for k, v in raw.items() if k in Config.__dataclass_fields__}
    cfg = Config(**known)
    if not cfg.hub_base_url or not cfg.station_token:
        print("config.json must set hub_base_url and station_token.", file=sys.stderr)
        sys.exit(1)
    cfg.hub_base_url = cfg.hub_base_url.rstrip("/")
    cfg.ensure_dirs()
    return cfg
