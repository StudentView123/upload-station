"""Upload Station orchestrator: Orthanc + worklist sync + exporter + web UI."""

import logging
import threading

import uvicorn

from .config import load_config
from .db import StationDB
from .exporter import Exporter
from .hub_client import HubClient
from .orthanc_runtime import OrthancProcess
from .web import create_app
from .worklist import write_worklist_files

log = logging.getLogger("station")


class StationRuntime:
    def __init__(self):
        self.cfg = load_config()
        self.db = StationDB(self.cfg.data_path / "station.sqlite3")
        self.hub = HubClient(self.cfg)
        self.orthanc = OrthancProcess(self.cfg)
        self.exporter = Exporter(self.cfg, self.db, self.hub)
        self._stop = threading.Event()
        self._sync_kick = threading.Event()

    # -- worklist sync loop ---------------------------------------------------
    def request_worklist_sync(self) -> None:
        self._sync_kick.set()

    def _sync_worklist_once(self) -> None:
        from datetime import datetime, timezone
        try:
            payload = self.hub.get_worklist()
            write_worklist_files(payload, self.cfg)
            self.db.save_worklist(payload)
            self.db.set_meta("last_worklist_sync", datetime.now(timezone.utc).isoformat())
            self.db.set_meta("hub_ok", "1")
        except Exception as exc:
            self.db.set_meta("hub_ok", "0")
            log.warning("Worklist sync failed (keeping previous worklist): %s", exc)

    def _worklist_loop(self) -> None:
        while not self._stop.is_set():
            self._sync_worklist_once()
            self._sync_kick.wait(timeout=self.cfg.worklist_refresh_seconds)
            self._sync_kick.clear()

    # -- exporter loop ----------------------------------------------------------
    def _export_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.exporter.poll_once()
            except Exception as exc:
                log.warning("Export poll failed (is Orthanc running?): %s", exc)
            self._stop.wait(timeout=self.cfg.export_poll_seconds)

    # -- entry point --------------------------------------------------------------
    def _setup_logging(self) -> None:
        fmt = logging.Formatter("%(asctime)s %(name)-9s %(levelname)-7s %(message)s")
        root = logging.getLogger()
        root.setLevel(logging.INFO)
        # Console (no-op in a windowed/frozen build, useful in a terminal).
        stream = logging.StreamHandler()
        stream.setFormatter(fmt)
        root.addHandler(stream)
        # Rotating file log so a background/windowed install is still debuggable.
        try:
            from logging.handlers import RotatingFileHandler
            log_path = self.cfg.data_path / "station-app.log"
            fileh = RotatingFileHandler(
                log_path, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
            )
            fileh.setFormatter(fmt)
            root.addHandler(fileh)
        except Exception:
            pass

    def run(self) -> None:
        self._setup_logging()
        log.info("Upload Station starting — %s", self.cfg.station_name)

        if not self.orthanc.start():
            log.error("Cannot continue without the DICOM server.")
            raise SystemExit(1)

        threading.Thread(target=self._worklist_loop, name="worklist", daemon=True).start()
        threading.Thread(target=self._export_loop, name="exporter", daemon=True).start()

        if self.cfg.stream_images_to_hub:
            log.info("Streaming captured images to Practice Hub — view them at the /dicom page.")

        try:
            if self.cfg.local_ui_enabled:
                app = create_app(self.cfg, self.db, self)
                log.info("Local web UI: http://localhost:%d", self.cfg.ui_port)
                uvicorn.run(app, host="127.0.0.1", port=self.cfg.ui_port, log_level="warning")
            else:
                log.info("Headless relay mode — no local UI. Images go to Practice Hub.")
                self._stop.wait()
        except KeyboardInterrupt:
            pass
        finally:
            self._stop.set()
            self.orthanc.stop()
            log.info("Upload Station stopped.")


def main() -> None:
    StationRuntime().run()


if __name__ == "__main__":
    main()
