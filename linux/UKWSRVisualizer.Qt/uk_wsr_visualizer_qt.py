#!/usr/bin/env python3
"""Qt desktop launcher for the Linux UK WSR Visualizer beta."""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


APP_NAME = "UK WSR Visualizer"
BUILD_VERSION = os.environ.get("UK_WSR_VISUALIZER_APP_VERSION", "linux-beta")
REMOTE_BASE = "https://ncas-radar-o.s3-ext.jc.rl.ac.uk/uk-wsr-visualizer-public"
REMOTE_CATALOG = f"{REMOTE_BASE}/ukmo-nimrod/catalog/pvol/catalog.json"
DEFAULT_PORT = 8765
FIRST_FALLBACK_PORT = 8766
LAST_FALLBACK_PORT = 8785
CACHE_MAX_BYTES = str(25 * 1024 * 1024 * 1024)


def _xdg_dir(env_name: str, fallback: Path) -> Path:
    value = os.environ.get(env_name)
    return Path(value).expanduser() if value else fallback


def _app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def _port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _log_tail(path: Path, lines: int = 20) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return "\n".join(text.splitlines()[-lines:])


def _append_log(path: Path, message: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8") if not path.exists() else None
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {message}\n")
    except OSError:
        pass


@dataclass(frozen=True)
class LauncherConfig:
    app_root: Path
    state_dir: Path
    data_dir: Path
    log_file: Path
    pid_file: Path
    server_exe: Path
    logo_file: Path
    port: int
    base_url: str
    window_url: str

    @classmethod
    def create(cls) -> "LauncherConfig":
        app_root = _app_root()
        cache_root = _xdg_dir("XDG_CACHE_HOME", Path.home() / ".cache")
        state_root = _xdg_dir("XDG_STATE_HOME", Path.home() / ".local" / "state")
        state_dir = state_root / "uk-wsr-visualizer"
        data_dir = cache_root / "uk-wsr-visualizer" / "data"
        state_dir.mkdir(parents=True, exist_ok=True)
        data_dir.mkdir(parents=True, exist_ok=True)

        requested = int(os.environ.get("UK_WSR_VISUALIZER_LINUX_PORT", DEFAULT_PORT))
        port = cls._resolve_port(state_dir, requested)
        base_url = f"http://127.0.0.1:{port}"
        return cls(
            app_root=app_root,
            state_dir=state_dir,
            data_dir=data_dir,
            log_file=state_dir / "uk-wsr-visualizer.log",
            pid_file=state_dir / "server.pid",
            server_exe=app_root / "server" / "uk-wsr-visualizer-server",
            logo_file=app_root / "resources" / "UKWSRVisualizer.png",
            port=port,
            base_url=base_url,
            window_url=f"{base_url}/?v={BUILD_VERSION}",
        )

    def with_port(self, port: int) -> "LauncherConfig":
        base_url = f"http://127.0.0.1:{port}"
        return LauncherConfig(
            app_root=self.app_root,
            state_dir=self.state_dir,
            data_dir=self.data_dir,
            log_file=self.log_file,
            pid_file=self.pid_file,
            server_exe=self.server_exe,
            logo_file=self.logo_file,
            port=port,
            base_url=base_url,
            window_url=f"{base_url}/?v={BUILD_VERSION}",
        )

    @staticmethod
    def _resolve_port(state_dir: Path, requested: int) -> int:
        if _port_available(requested):
            return requested
        LauncherConfig._try_stop_saved_server(state_dir / "server.pid")
        if _port_available(requested):
            return requested
        return LauncherConfig.resolve_fallback_port(requested)

    @staticmethod
    def resolve_fallback_port(current_port: int) -> int:
        for port in range(FIRST_FALLBACK_PORT, LAST_FALLBACK_PORT + 1):
            if port != current_port and _port_available(port):
                return port
        raise RuntimeError("No free retry port found in 8766-8785.")

    @staticmethod
    def _try_stop_saved_server(pid_file: Path) -> None:
        try:
            pid = int(pid_file.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return
        try:
            cmdline = Path(f"/proc/{pid}/cmdline").read_text(encoding="utf-8", errors="ignore")
            if "uk-wsr-visualizer" not in cmdline and "python" not in cmdline:
                return
            os.kill(pid, signal.SIGTERM)
            for _ in range(20):
                time.sleep(0.25)
                try:
                    os.kill(pid, 0)
                except OSError:
                    break
            pid_file.unlink(missing_ok=True)
        except OSError:
            pid_file.unlink(missing_ok=True)


class ServerProcess:
    def __init__(self, config: LauncherConfig) -> None:
        self.config = config
        self.process: subprocess.Popen[bytes] | None = None
        self.log_handle = None

    @property
    def has_exited(self) -> bool:
        return self.process is not None and self.process.poll() is not None

    @property
    def exit_code(self) -> int | None:
        return None if self.process is None else self.process.poll()

    def start(self) -> None:
        self.config.data_dir.mkdir(parents=True, exist_ok=True)
        self.config.state_dir.mkdir(parents=True, exist_ok=True)
        _append_log(self.config.log_file, "starting Linux server")
        _append_log(self.config.log_file, f"app_version={BUILD_VERSION}")
        _append_log(self.config.log_file, f"server_exe={self.config.server_exe}")
        _append_log(self.config.log_file, f"working_dir={self.config.app_root}")
        _append_log(self.config.log_file, f"selected_port={self.config.port}")
        _append_log(self.config.log_file, f"base_url={self.config.base_url}")
        _append_log(self.config.log_file, f"remote_catalog={REMOTE_CATALOG}")
        _append_log(self.config.log_file, f"data_dir={self.config.data_dir}")
        _append_log(self.config.log_file, f"cache_max_bytes={CACHE_MAX_BYTES}")

        env = os.environ.copy()
        env["UK_WSR_VISUALIZER_DATA_DIR"] = str(self.config.data_dir)
        env["UK_WSR_VISUALIZER_CATALOG"] = str(self.config.data_dir / "catalog.json")
        env["UK_WSR_VISUALIZER_REMOTE_CATALOG_URL"] = REMOTE_CATALOG
        env["UK_WSR_VISUALIZER_OBJECT_STORE_EXTERNAL_BASE"] = REMOTE_BASE
        env["UK_WSR_VISUALIZER_REMOTE_CACHE_TTL_SECONDS"] = "0"
        env["UK_WSR_VISUALIZER_REMOTE_CACHE_MAX_BYTES"] = CACHE_MAX_BYTES

        if self.config.server_exe.exists():
            command = [str(self.config.server_exe), "api", "--host", "127.0.0.1", "--port", str(self.config.port)]
        else:
            env["PYTHONPATH"] = str(self.config.app_root / "src")
            command = [sys.executable, "-m", "uk_wsr_visualizer.cli", "api", "--host", "127.0.0.1", "--port", str(self.config.port)]

        self.log_handle = self.config.log_file.open("ab")
        self.process = subprocess.Popen(
            command,
            cwd=str(self.config.app_root),
            env=env,
            stdout=self.log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        self.config.pid_file.write_text(str(self.process.pid), encoding="utf-8")
        _append_log(self.config.log_file, f"started Linux server pid {self.process.pid}")

    def kill_and_clear_pid_file(self, reason: str) -> None:
        _append_log(self.config.log_file, reason)
        if self.process is not None and self.process.poll() is None:
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
                self.process.wait(timeout=5)
            except Exception:
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except Exception:
                    pass
        self.config.pid_file.unlink(missing_ok=True)
        if self.log_handle is not None:
            self.log_handle.close()

    def close(self) -> None:
        self.kill_and_clear_pid_file("disposing Linux launcher")


def _ready(base_url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{base_url}/api/ready", timeout=2) as response:
            return 200 <= response.status < 300
    except (OSError, urllib.error.URLError):
        return False


def _status(base_url: str) -> str:
    with urllib.request.urlopen(f"{base_url}/api/status", timeout=10) as response:
        return response.read().decode("utf-8")


def wait_for_ready(config: LauncherConfig, server: ServerProcess, timeout_seconds: float) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error = ""
    while time.monotonic() < deadline:
        if server.has_exited:
            tail = _log_tail(config.log_file)
            suffix = f" Recent server output: {tail}" if tail else ""
            raise RuntimeError(f"The local server exited before it became ready (exit code {server.exit_code}).{suffix}")
        try:
            if _ready(config.base_url):
                return
        except Exception as exc:
            last_error = str(exc)
        time.sleep(0.75)
    raise TimeoutError(f"The local UK WSR Visualizer server did not become ready. Last readiness error: {last_error}")


def start_server_with_retry(
    initial_config: LauncherConfig,
    timeout_seconds: float,
    on_config_changed: Callable[[LauncherConfig], None] | None = None,
    on_status: Callable[[str], None] | None = None,
) -> ServerProcess:
    active_config = initial_config
    first_failure: Exception | None = None
    for attempt in range(1, 3):
        server = ServerProcess(active_config)
        try:
            if on_status:
                on_status("Starting local radar server..." if attempt == 1 else "Retrying local radar server on another port...")
            server.start()
            wait_for_ready(active_config, server, timeout_seconds)
            if on_status:
                on_status("Loading radar interface...")
            return server
        except Exception as exc:
            server.kill_and_clear_pid_file(f"startup attempt {attempt} failed: {exc}")
            if attempt == 1:
                first_failure = exc
                active_config = active_config.with_port(LauncherConfig.resolve_fallback_port(active_config.port))
                if on_config_changed:
                    on_config_changed(active_config)
                continue
            raise RuntimeError(
                "The local UK WSR Visualizer server did not become ready after a retry. "
                f"First failure: {first_failure}. Last failure: {exc}"
            ) from exc
    raise RuntimeError("The local UK WSR Visualizer server did not become ready.")


def run_self_test(config: LauncherConfig) -> int:
    server: ServerProcess | None = None
    try:
        server = start_server_with_retry(config, 90)
        print(json.dumps(json.loads(_status(server.config.base_url)), indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        print(f"Log: {config.log_file}", file=sys.stderr)
        return 1
    finally:
        if server is not None:
            server.close()


def run_gui(config: LauncherConfig) -> int:
    from PySide6.QtCore import QUrl, Qt, Signal
    from PySide6.QtGui import QPixmap
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QMainWindow, QStackedWidget, QVBoxLayout, QWidget

    class MainWindow(QMainWindow):
        status_signal = Signal(str)
        ready_signal = Signal(object)
        error_signal = Signal(str)

        def __init__(self, launcher_config: LauncherConfig) -> None:
            super().__init__()
            self.config = launcher_config
            self.server: ServerProcess | None = None
            self.setWindowTitle(APP_NAME)
            self.resize(1440, 940)
            self.setMinimumSize(1100, 720)
            self.stack = QStackedWidget()
            self.splash_status = QLabel("Starting local radar viewer...")
            self.web_view = QWebEngineView()
            self.stack.addWidget(self._build_splash())
            self.stack.addWidget(self.web_view)
            self.setCentralWidget(self.stack)
            self.status_signal.connect(self.splash_status.setText)
            self.ready_signal.connect(self._server_ready)
            self.error_signal.connect(self._server_failed)
            self.web_view.loadFinished.connect(lambda _ok: self.stack.setCurrentWidget(self.web_view))
            threading.Thread(target=self._start_background, daemon=True).start()

        def _build_splash(self) -> QWidget:
            widget = QWidget()
            layout = QVBoxLayout(widget)
            layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            logo = QLabel()
            logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
            if self.config.logo_file.exists():
                logo.setPixmap(QPixmap(str(self.config.logo_file)).scaled(340, 340, Qt.AspectRatioMode.KeepAspectRatio))
            title = QLabel(APP_NAME)
            title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            title.setStyleSheet("font-size: 28px; font-weight: 700; color: #192833;")
            self.splash_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.splash_status.setStyleSheet("font-size: 14px; color: #5b6774;")
            layout.addWidget(logo)
            layout.addWidget(title)
            layout.addWidget(self.splash_status)
            return widget

        def _start_background(self) -> None:
            try:
                server = start_server_with_retry(
                    self.config,
                    120,
                    on_config_changed=lambda updated: setattr(self, "config", updated),
                    on_status=self.status_signal.emit,
                )
                self.ready_signal.emit(server)
            except Exception as exc:
                _append_log(self.config.log_file, repr(exc))
                self.error_signal.emit(str(exc))

        def _server_ready(self, server: ServerProcess) -> None:
            self.server = server
            self.web_view.load(QUrl(server.config.window_url))

        def _server_failed(self, message: str) -> None:
            self.splash_status.setText("UK WSR Visualizer did not start. Open the log for details.")
            QMessageBox.critical(self, APP_NAME, f"UK WSR Visualizer did not start.\n\nLog:\n{self.config.log_file}\n\n{message}")

        def closeEvent(self, event) -> None:  # noqa: N802 - Qt API name
            if self.server is not None:
                self.server.close()
            super().closeEvent(event)

    app = QApplication(sys.argv)
    window = MainWindow(config)
    window.show()
    return app.exec()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="UK WSR Visualizer Linux Qt launcher")
    parser.add_argument("--self-test", action="store_true", help="Start the bundled server, print /api/status, and exit.")
    args = parser.parse_args(argv)
    config = LauncherConfig.create()
    if args.self_test:
        return run_self_test(config)
    return run_gui(config)


if __name__ == "__main__":
    raise SystemExit(main())
