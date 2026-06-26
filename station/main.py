"""Upload Station orchestrator.

Supervisor loop:
  - If the station is not yet connected to Practice Hub, serve only the local
    setup page (localhost:8088) so the user can connect it via token, enrollment
    code, or login.
  - Once connected, run the full runtime (Orthanc + worklist sync + exporter +
    dashboard). Reconfiguring from the web page restarts the runtime in place.
"""

import logging
import socket
import threading

import uvicorn

from .config import load_config, Config
from .db import StationDB
from .exporter import Exporter
from .hub_client import HubClient, HubError
from .orthanc_runtime import OrthancProcess
from .web import create_app
from .worklist import write_worklist_files

log = logging.getLogger("station")


class StationRuntime:
    def __init__(self):
        self.cfg: Config = load_config()
        self.db = StationDB(self.cfg.data_path / "station.sqlite3")
        self.hub = HubClient(self.cfg, on_config_change=self._persist_cfg)

        self.orthanc: OrthancProcess | None = None
        self.exporter: Exporter | None = None

        self.setup_mode = True
        self._restart = threading.Event()
        self._shutdown = threading.Event()
        self._stop = threading.Event()       # stops worker threads each cycle
        self._sync_kick = threading.Event()

        # Holds a Supabase session between the login and office-pick steps.
        self._pending_login: dict | None = None

    def _persist_cfg(self) -> None:
        try:
            self.cfg.save()
        except Exception:
            log.exception("Could not save config.json")

    # ===== setup actions (called from the web setup page) ====================
    def apply_token(self, token: str, station_name: str) -> None:
        self.cfg.auth_mode = "token"
        self.cfg.station_token = token.strip()
        if station_name:
            self.cfg.station_name = station_name.strip()
        self._persist_cfg()
        self.request_restart()

    def apply_enroll(self, code: str, station_name: str) -> dict:
        device_name = (station_name or socket.gethostname() or "Upload Station").strip()
        result = self.hub.enroll(code, device_name)  # raises HubError on bad code
        self.cfg.auth_mode = "enroll"
        self.cfg.enrollment_code = code.strip()
        self.cfg.station_token = result["station_token"]
        self.cfg.station_name = device_name
        self.cfg.selected_location_id = result.get("location_id", "")
        self.cfg.selected_location_name = result.get("location_name", "")
        self._persist_cfg()
        self.request_restart()
        return result

    def begin_login(self, email: str, password: str) -> list[dict]:
        data = self.hub.login(email, password)  # raises HubError on bad creds
        self._pending_login = data
        return self.hub.list_locations(data["access_token"])

    def complete_login(self, location_id: str, location_name: str, station_name: str) -> None:
        if not self._pending_login:
            raise HubError("Please log in again.")
        self.cfg.auth_mode = "login"
        self.cfg.hub_refresh_token = self._pending_login["refresh_token"]
        self.cfg.selected_location_id = location_id
        self.cfg.selected_location_name = location_name
        if station_name:
            self.cfg.station_name = station_name.strip()
        self._pending_login = None
        self._persist_cfg()
        self.request_restart()

    def request_restart(self) -> None:
        self._restart.set()

    # ===== worklist + export loops ===========================================
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

    def _export_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.exporter.poll_once()
            except Exception as exc:
                log.warning("Export poll failed (is Orthanc running?): %s", exc)
            self._stop.wait(timeout=self.cfg.export_poll_seconds)

    # ===== credential preparation ============================================
    def _prepare_credentials(self) -> bool:
        """Make sure we have a working credential; returns True if ready to run
        the full runtime, False if we should fall back to setup mode."""
        mode = self.cfg.auth_mode
        if mode == "token":
            return bool(self.cfg.station_token)
        if mode == "enroll":
            if self.cfg.station_token:
                return True
            if not self.cfg.enrollment_code:
                return False
            try:
                result = self.hub.enroll(self.cfg.enrollment_code)
                self.cfg.station_token = result["station_token"]
                self.cfg.selected_location_id = result.get("location_id", "")
                self.cfg.selected_location_name = result.get("location_name", "")
                self._persist_cfg()
                return True
            except (HubError, Exception) as exc:
                log.warning("Enrollment failed: %s", exc)
                return False
        if mode == "login":
            if not (self.cfg.hub_refresh_token and self.cfg.selected_location_id):
                return False
            try:
                self.hub._refresh_login(force=True)
                return True
            except Exception as exc:
                log.warning("Login refresh failed (need to log in again): %s", exc)
                return False
        return False

    # ===== one supervisor cycle ==============================================
    def _serve(self, app, host: str = "127.0.0.1") -> uvicorn.Server:
        config = uvicorn.Config(app, host=host, port=self.cfg.ui_port, log_level="warning")
        server = uvicorn.Server(config)
        threading.Thread(target=server.run, name="web", daemon=True).start()
        return server

    def _run_cycle(self) -> None:
        self._restart.clear()
        self._stop.clear()
        self.cfg = load_config()
        self.hub = HubClient(self.cfg, on_config_change=self._persist_cfg)

        ready = self._prepare_credentials()
        self.setup_mode = not ready

        server = None
        if self.setup_mode:
            log.info("Not connected to Practice Hub yet — open http://localhost:%d to set up.",
                     self.cfg.ui_port)
            server = self._serve(create_app(self.cfg, self.db, self))
            self._restart.wait()  # block until setup completes (or shutdown)
        else:
            log.info("Connected as '%s' (mode: %s)", self.cfg.station_name, self.cfg.auth_mode)
            self.orthanc = OrthancProcess(self.cfg)
            if not self.orthanc.start():
                log.error("DICOM server failed to start; falling back to setup page.")
                # Surface the problem in the UI rather than crash-looping.
                server = self._serve(create_app(self.cfg, self.db, self))
                self._restart.wait()
            else:
                self.exporter = Exporter(self.cfg, self.db, self.hub)
                threading.Thread(target=self._worklist_loop, name="worklist", daemon=True).start()
                threading.Thread(target=self._export_loop, name="exporter", daemon=True).start()
                if self.cfg.stream_images_to_hub:
                    log.info("Streaming captured images to Practice Hub.")
                if self.cfg.local_ui_enabled:
                    log.info("Local web UI: http://localhost:%d", self.cfg.ui_port)
                    server = self._serve(create_app(self.cfg, self.db, self))
                else:
                    log.info("Headless mode — images go to Practice Hub (no local UI).")
                self._restart.wait()

        # Teardown this cycle.
        self._stop.set()
        if server is not None:
            server.should_exit = True
        if self.orthanc is not None:
            self.orthanc.stop()
            self.orthanc = None
        self.exporter = None

    # ===== entry point =======================================================
    def _setup_logging(self) -> None:
        fmt = logging.Formatter("%(asctime)s %(name)-9s %(levelname)-7s %(message)s")
        root = logging.getLogger()
        root.setLevel(logging.INFO)
        stream = logging.StreamHandler()
        stream.setFormatter(fmt)
        root.addHandler(stream)
        try:
            from logging.handlers import RotatingFileHandler
            fileh = RotatingFileHandler(
                self.cfg.data_path / "station-app.log",
                maxBytes=2_000_000, backupCount=3, encoding="utf-8",
            )
            fileh.setFormatter(fmt)
            root.addHandler(fileh)
        except Exception:
            pass

    def run(self) -> None:
        self._setup_logging()
        log.info("Upload Station starting — %s", self.cfg.station_name)
        try:
            while not self._shutdown.is_set():
                self._run_cycle()
        except KeyboardInterrupt:
            pass
        finally:
            self._stop.set()
            if self.orthanc is not None:
                self.orthanc.stop()
            log.info("Upload Station stopped.")


def main() -> None:
    StationRuntime().run()


if __name__ == "__main__":
    main()
