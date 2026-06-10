"""Generate the Orthanc configuration and manage the Orthanc subprocess."""

import json
import logging
import platform
import shutil
import subprocess
import time
from pathlib import Path

import requests

from .config import Config, REPO_ROOT

log = logging.getLogger("orthanc")

WINDOWS_DEFAULT_PATHS = [
    r"C:\Program Files\Orthanc Server\Orthanc.exe",
    r"C:\Program Files (x86)\Orthanc Server\Orthanc.exe",
]


def find_orthanc_executable(cfg: Config) -> Path | None:
    if cfg.orthanc_executable:
        p = Path(cfg.orthanc_executable).expanduser()
        return p if p.exists() else None

    candidates: list[Path] = []
    vendor = REPO_ROOT / "vendor"
    if vendor.exists():
        candidates += sorted(vendor.rglob("Orthanc"))
        candidates += sorted(vendor.rglob("Orthanc.exe"))
    on_path = shutil.which("Orthanc")
    if on_path:
        candidates.append(Path(on_path))
    if platform.system() == "Windows":
        candidates += [Path(p) for p in WINDOWS_DEFAULT_PATHS]

    for c in candidates:
        if c.exists() and c.is_file():
            return c
    return None


def find_worklist_plugin(orthanc_exe: Path) -> Path | None:
    """Locate the worklists plugin near the Orthanc executable."""
    patterns = [
        "*OrthancWorklists*", "*ModalityWorklists*",
        "*libModalityWorklists*", "*libOrthancWorklists*",
    ]
    roots = [orthanc_exe.parent, orthanc_exe.parent.parent]
    for root in roots:
        for pattern in patterns:
            for ext in (".dylib", ".so", ".dll"):
                hits = sorted(root.rglob(pattern + ext))
                if hits:
                    return hits[0]
    return None


def generate_orthanc_config(cfg: Config, plugin: Path | None) -> Path:
    storage = cfg.data_path / "orthanc-storage"
    storage.mkdir(parents=True, exist_ok=True)
    conf = {
        "Name": cfg.station_name,
        "DicomAet": cfg.aet,
        "DicomPort": cfg.dicom_port,
        "HttpPort": cfg.orthanc_http_port,
        "RemoteAccessAllowed": False,
        "AuthenticationEnabled": False,
        "StorageDirectory": str(storage),
        "IndexDirectory": str(storage),
        "DicomServerEnabled": True,
        # Accept images from any device on the LAN without per-device registration.
        "DicomCheckCalledAet": False,
        "DicomAlwaysAllowEcho": True,
        "DicomAlwaysAllowStore": True,
        "DicomAlwaysAllowFind": True,
        "DicomAlwaysAllowFindWorklist": True,
        "DicomCheckModalityHost": False,
        # Ophthalmic devices use uncommon SOP classes; never reject them.
        "UnknownSopClassAccepted": True,
        "OverwriteInstances": True,
        # A study is "stable" (complete) after 30s without new images.
        "StableAge": 30,
        "Worklists": {
            "Enable": True,
            "Database": str(cfg.worklists_path),
        },
        "Plugins": [str(plugin)] if plugin else [],
    }
    path = cfg.data_path / "orthanc.json"
    path.write_text(json.dumps(conf, indent=2), encoding="utf-8")
    return path


class OrthancProcess:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.proc: subprocess.Popen | None = None
        self.exe = find_orthanc_executable(cfg)

    def start(self) -> bool:
        if self.exe is None:
            log.error(
                "Orthanc executable not found. Install Orthanc (Windows installer or "
                "macOS package in ./vendor) or set orthanc_executable in config.json."
            )
            return False
        plugin = find_worklist_plugin(self.exe)
        if plugin is None:
            log.error("Orthanc worklists plugin not found next to %s", self.exe)
            return False
        conf = generate_orthanc_config(self.cfg, plugin)
        logfile = open(self.cfg.data_path / "orthanc.log", "ab")
        self.proc = subprocess.Popen(
            [str(self.exe), str(conf)],
            stdout=logfile, stderr=subprocess.STDOUT,
        )
        log.info("Orthanc starting (pid %s) with plugin %s", self.proc.pid, plugin.name)
        return self.wait_ready()

    def wait_ready(self, timeout: int = 30) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.proc and self.proc.poll() is not None:
                log.error("Orthanc exited early — see orthanc.log in the data folder.")
                return False
            try:
                r = requests.get(f"{self.cfg.orthanc_url}/system", timeout=2)
                if r.ok:
                    log.info("Orthanc ready: version %s", r.json().get("Version"))
                    return True
            except requests.RequestException:
                pass
            time.sleep(0.5)
        log.error("Orthanc did not become ready in %ss", timeout)
        return False

    def is_running(self) -> bool:
        try:
            return requests.get(f"{self.cfg.orthanc_url}/system", timeout=2).ok
        except requests.RequestException:
            return False

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
