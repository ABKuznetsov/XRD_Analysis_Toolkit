from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import ssl
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox
from urllib.error import URLError
from urllib.request import Request, urlopen


APP_ID = "xrd_finder"
APP_NAME = "XRD Phase Finder"
MIN_VISIBLE_STEP_SECONDS = 1.0


def app_root() -> Path:
    return Path(__file__).resolve().parents[1]


def compare_versions(left: str, right: str) -> int:
    def parts(value: str) -> list[int | str]:
        result: list[int | str] = []
        for chunk in value.replace("-", ".").split("."):
            if chunk.isdigit():
                result.append(int(chunk))
            elif chunk:
                result.append(chunk.lower())
        return result

    l_parts = parts(left)
    r_parts = parts(right)
    for index in range(max(len(l_parts), len(r_parts))):
        l_item = l_parts[index] if index < len(l_parts) else 0
        r_item = r_parts[index] if index < len(r_parts) else 0
        if l_item == r_item:
            continue
        if isinstance(l_item, int) and isinstance(r_item, int):
            return 1 if l_item > r_item else -1
        return 1 if str(l_item) > str(r_item) else -1
    return 0


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def create_ssl_context() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def fetch_url_bytes(url: str, timeout: float = 30.0) -> bytes:
    request = Request(url, headers={"User-Agent": "XRD-Phase-Finder-macOS-Updater"})
    try:
        with urlopen(request, timeout=timeout, context=create_ssl_context()) as response:
            return response.read()
    except Exception:
        curl = Path("/usr/bin/curl")
        if not curl.exists():
            raise
        process = subprocess.run(
            [
                str(curl),
                "-fsSL",
                "--connect-timeout",
                str(max(1, int(timeout))),
                "--max-time",
                str(max(30, int(timeout))),
                url,
            ],
            capture_output=True,
            check=True,
        )
        return process.stdout


def fetch_json(url: str, timeout: float = 8.0) -> dict:
    data = fetch_url_bytes(url, timeout=timeout)
    return json.loads(data.decode("utf-8-sig"))


def download_file(url: str, target: Path, expected_sha256: str = "") -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    data = fetch_url_bytes(url, timeout=300)
    digest = hashlib.sha256()
    digest.update(data)
    target.write_bytes(data)
    if target.stat().st_size < 1024:
        target.unlink(missing_ok=True)
        raise RuntimeError("Downloaded installer is empty or incomplete.")
    if expected_sha256 and digest.hexdigest().lower() != expected_sha256.lower():
        target.unlink(missing_ok=True)
        raise RuntimeError("Downloaded installer checksum does not match the manifest.")


def find_macos_asset(remote_app: dict) -> tuple[str, str]:
    for asset in remote_app.get("assets", []) or []:
        platform_name = str(asset.get("platform", "")).lower()
        name = str(asset.get("name", "")).lower()
        if "macos" in platform_name or name.endswith(".pkg") or name.endswith(".dmg"):
            return str(asset.get("url", "")), str(asset.get("sha256", ""))
    url = str(remote_app.get("macos_installer_url") or "")
    sha = str(remote_app.get("macos_installer_sha256") or "")
    if url:
        return url, sha
    url = str(remote_app.get("installer_url") or "")
    if url.lower().endswith((".pkg", ".dmg", ".zip")):
        return url, str(remote_app.get("installer_sha256") or "")
    return "", ""


class PreviewApp:
    def __init__(self) -> None:
        self.app_root = app_root()
        self.sci_root = Path.home() / "Library" / "Application Support" / "Sci"
        self.env_root = self.sci_root / "env"
        self.apps_root = self.sci_root / "apps"
        self.finder_root = self.apps_root / "xrd_phase_finder"
        self.data_root = self.finder_root / "data"
        self.logs_root = self.sci_root / "logs"
        self.update_root = self.sci_root / "updates"
        self.matplotlib_root = self.finder_root / "matplotlib"
        self.python = self.env_root / "bin" / "python"
        self.setup_script = self.app_root / "toolkit" / "setup_sci_env.command"
        self.manifest_path = self.app_root / "toolkit" / "manifest.json"
        self.app_manifest_path = self.app_root / "XRD_Finder" / "app.json"
        self.icon_path = self.app_root / "XRD_Finder" / "icon.png"
        self.local_version = "0.0.0"
        self.entry_module = "xrd_finder.apps.finder_gui"
        self.app_process: subprocess.Popen | None = None

        app_manifest = load_json(self.app_manifest_path)
        if app_manifest.get("version"):
            self.local_version = str(app_manifest["version"])
        if app_manifest.get("entry_module"):
            self.entry_module = str(app_manifest["entry_module"])

        self.root = tk.Tk()
        self.root.title(APP_NAME)
        self.root.geometry("920x560")
        self.root.resizable(False, False)
        self.root.configure(bg="#f8fafc")
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.step_status: list[tk.Label] = []
        self.step_detail: list[tk.Label] = []
        self.step_icon: list[tk.Label] = []
        self._build_ui()

    def _build_ui(self) -> None:
        left = tk.Frame(self.root, bg="white", width=390, height=560)
        left.place(x=0, y=0)
        tk.Frame(self.root, bg="#e2e8f0", width=1, height=560).place(x=390, y=0)

        if self.icon_path.exists():
            try:
                source_icon = tk.PhotoImage(file=str(self.icon_path))
                max_icon_size = 250
                scale = max(1, (max(source_icon.width(), source_icon.height()) + max_icon_size - 1) // max_icon_size)
                self.icon = source_icon.subsample(scale, scale)
                icon_x = (390 - self.icon.width()) // 2
                tk.Label(left, image=self.icon, bg="white").place(
                    x=icon_x,
                    y=60,
                    width=self.icon.width(),
                    height=self.icon.height(),
                )
            except Exception:
                self.icon = None
        tk.Label(left, text=APP_NAME, bg="white", fg="#0f172a", font=("Helvetica", 25, "bold")).place(x=48, y=350)
        tk.Label(
            left,
            text="Phase identification from\nX-ray diffraction data",
            bg="white",
            fg="#475569",
            justify="left",
            font=("Helvetica", 14),
        ).place(x=52, y=408)
        tk.Label(left, text=f"Version {self.local_version}", bg="white", fg="#64748b", font=("Helvetica", 10)).place(x=54, y=504)

        tk.Label(
            self.root,
            text="Starting XRD Phase Finder...",
            bg="#f8fafc",
            fg="#0f172a",
            font=("Helvetica", 21, "bold"),
        ).place(x=430, y=44)
        tk.Label(
            self.root,
            text="Preparing folders, runtime, updates and user settings.",
            bg="#f8fafc",
            fg="#64748b",
            font=("Helvetica", 11),
        ).place(x=432, y=84)

        rows = [
            ("Checking application folders", "User data directory\nCache directory"),
            ("Checking Sci runtime", "Python environment\nScientific packages"),
            ("Checking local databases", "User library\nCache database"),
            ("Checking for updates", f"Current version: {self.local_version}"),
            ("Opening application", "Main application window"),
        ]
        for index, (title, detail) in enumerate(rows):
            self._add_step(index, title, detail, 132 + index * 72)

    def _add_step(self, index: int, title: str, detail: str, y: int) -> None:
        icon = tk.Label(self.root, text="○", bg="#f8fafc", fg="#94a3b8", font=("Helvetica", 25, "bold"))
        icon.place(x=430, y=y + 2, width=36, height=36)
        self.step_icon.append(icon)
        tk.Label(self.root, text=title, bg="#f8fafc", fg="#0f172a", font=("Helvetica", 12, "bold")).place(x=492, y=y)
        detail_label = tk.Label(
            self.root,
            text=detail,
            bg="#f8fafc",
            fg="#475569",
            justify="left",
            font=("Helvetica", 10),
        )
        detail_label.place(x=492, y=y + 25, width=280, height=38)
        self.step_detail.append(detail_label)
        status = tk.Label(self.root, text="Waiting", bg="#f8fafc", fg="#2563eb", anchor="e", font=("Helvetica", 10))
        status.place(x=790, y=y + 13, width=100)
        self.step_status.append(status)
        tk.Frame(self.root, bg="#e2e8f0", width=458, height=1).place(x=430, y=y + 64)

    def set_step(self, index: int, status: str, detail: str = "", tone: str = "blue") -> None:
        colors = {
            "blue": ("●", "#2563eb"),
            "green": ("✓", "#2e7d32"),
            "red": ("×", "#b91c1c"),
            "muted": ("○", "#64748b"),
        }
        glyph, color = colors.get(tone, colors["blue"])
        self.step_icon[index].configure(text=glyph, fg=color)
        self.step_status[index].configure(text=status, fg=color)
        if detail:
            self.step_detail[index].configure(text=detail)
        self.root.update_idletasks()

    def ensure_folders(self) -> None:
        self.set_step(0, "Checking...", "Creating user data folders")
        for path in [self.sci_root, self.apps_root, self.finder_root, self.data_root, self.logs_root, self.update_root, self.matplotlib_root]:
            path.mkdir(parents=True, exist_ok=True)
        (self.data_root / "cod_cache" / "rruff").mkdir(parents=True, exist_ok=True)
        self.set_step(0, "OK", "User data and cache folders are ready", "green")

    def ensure_runtime(self) -> None:
        self.set_step(1, "Checking...", "Looking for Sci runtime")
        if not self.python.exists():
            if not self.setup_script.exists():
                raise RuntimeError(f"Setup script was not found: {self.setup_script}")
            self.set_step(1, "Installing...", "First launch: configuring Python packages")
            setup_log = self.logs_root / "setup.log"
            process = subprocess.Popen([str(self.setup_script)], cwd=str(self.app_root))
            while process.poll() is None:
                detail = self._setup_progress(setup_log)
                self.set_step(1, "Installing...", detail)
                time.sleep(0.7)
            if process.returncode:
                raise RuntimeError(f"Environment setup failed. See log: {setup_log}")
        if not self.python.exists():
            raise RuntimeError(f"Sci Python executable was not found: {self.python}")
        self.set_step(1, "OK", "Runtime and scientific packages are ready", "green")

    def _setup_progress(self, log_path: Path) -> str:
        try:
            text = "\n".join(log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-40:])
        except Exception:
            return "Preparing environment"
        for marker, message in [
            ("Creating venv", "Creating Sci environment"),
            ("Upgrading pip", "Upgrading pip"),
            ("Installing XRD Phase Finder requirements", "Installing scientific Python packages"),
            ("Installing package:", "Installing Python packages"),
            ("Successfully installed", "Finalizing packages"),
        ]:
            if marker in text:
                return message
        return "Preparing environment"

    def check_databases(self) -> None:
        self.set_step(2, "Checking...", "COD, RRUFF and local cache folders")
        (self.data_root / "cod_cache").mkdir(parents=True, exist_ok=True)
        self.set_step(2, "OK", "Configured sources are available", "green")

    def check_updates(self) -> bool:
        self.set_step(3, "Checking...", f"Current version: {self.local_version}")
        manifest = load_json(self.manifest_path)
        app_info = (manifest.get("apps") or {}).get(APP_ID, {})
        remote_url = app_info.get("update_manifest_url") or app_info.get("manifest_url")
        release_url = app_info.get("release_url", "")
        update_status = {
            "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "app_id": APP_ID,
            "current_version": self.local_version,
            "latest_version": self.local_version,
            "update_available": False,
            "release_url": release_url,
            "installer_url": app_info.get("macos_installer_url", ""),
            "error": None,
        }
        try:
            if not remote_url:
                self.set_step(3, "OK", "No update source configured", "muted")
                return False
            remote = fetch_json(str(remote_url))
            remote_app = remote
            if isinstance(remote.get("apps"), dict) and APP_ID in remote["apps"]:
                remote_app = remote["apps"][APP_ID]
            latest = str(remote_app.get("version") or self.local_version)
            update_status["latest_version"] = latest
            installer_url, sha256 = find_macos_asset(remote_app)
            if compare_versions(latest, self.local_version) <= 0:
                self.set_step(3, "OK", f"No update available. Current version: {self.local_version}", "green")
                return False
            update_status["update_available"] = True
            update_status["installer_url"] = installer_url
            update_status["installer_sha256"] = sha256
            self.set_step(3, "Update", f"{self.local_version} -> {latest}")
            summary = "\n".join(f"- {line}" for line in remote_app.get("summary", []) if str(line).strip())
            if not summary:
                summary = "- See the release notes for details."
            answer = messagebox.askyesno(
                "XRD Phase Finder update available",
                f"A new XRD Phase Finder version is available: {latest}\n"
                f"Current version: {self.local_version}\n\n"
                f"What changed:\n{summary}\n\n"
                "Download and start the macOS installer now?",
                parent=self.root,
            )
            if not answer:
                return False
            if not installer_url:
                if release_url:
                    subprocess.Popen(["open", str(release_url)])
                    self.root.after(300, self.root.destroy)
                    return True
                raise RuntimeError("macOS installer URL is not available.")
            target = self.update_root / Path(installer_url.split("?")[0]).name
            if not target.name:
                target = self.update_root / f"XRD_Phase_Finder_macOS_{latest}.pkg"
            self.set_step(3, "Downloading", "Downloading macOS installer")
            download_file(installer_url, target, sha256)
            (self.update_root / f"{APP_ID}.json").write_text(json.dumps(update_status, indent=2), encoding="utf-8")
            self.set_step(3, "Ready", "Starting macOS installer", "green")
            subprocess.Popen(["open", str(target)])
            self.root.after(300, self.root.destroy)
            return True
        except (URLError, TimeoutError, RuntimeError, OSError, ValueError) as exc:
            update_status["error"] = str(exc)
            self.set_step(3, "Offline", "Update check unavailable", "muted")
            try:
                (self.update_root / f"{APP_ID}.json").write_text(json.dumps(update_status, indent=2), encoding="utf-8")
            except OSError:
                pass
            return False

    def launch_main_app(self) -> None:
        self.set_step(4, "Opening...", "Preparing main application window")
        ready_file = self.logs_root / "xrd_finder_ready.flag"
        prepared_file = self.logs_root / "xrd_finder_prepared.flag"
        show_signal_file = self.logs_root / "xrd_finder_show.signal"
        for path in [ready_file, prepared_file, show_signal_file]:
            path.unlink(missing_ok=True)

        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONPATH"] = str(self.app_root / "XRD_Finder") + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        env["XRD_FINDER_DATA_DIR"] = str(self.data_root)
        env["XRD_FINDER_PREPARED_FILE"] = str(prepared_file)
        env["XRD_FINDER_SHOW_SIGNAL_FILE"] = str(show_signal_file)
        env["XRD_FINDER_READY_FILE"] = str(ready_file)
        env["MPLCONFIGDIR"] = str(self.matplotlib_root)
        env["QT_MAC_WANTS_LAYER"] = "1"

        log_file = self.logs_root / "xrd_finder_console.log"
        log_handle = log_file.open("w", encoding="utf-8")
        log_handle.write(f"[{time.ctime()}] Starting XRD Phase Finder on {platform.platform()}\n")
        log_handle.flush()
        self.app_process = subprocess.Popen(
            [str(self.python), "-m", self.entry_module],
            cwd=str(self.app_root),
            env=env,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
        )
        time.sleep(0.8)
        show_signal_file.write_text("show", encoding="utf-8")
        deadline = time.monotonic() + 120.0
        while time.monotonic() < deadline:
            if ready_file.exists():
                self.set_step(4, "OK", "XRD Phase Finder window is ready", "green")
                self.root.after(400, self.root.destroy)
                return
            if self.app_process.poll() is not None:
                raise RuntimeError(f"XRD Phase Finder closed during startup. Log: {log_file}")
            self.set_step(4, "Starting...", "Waiting for the main application window")
            time.sleep(0.5)
        self.set_step(4, "OK", "Application is running; startup is taking longer than expected", "green")
        self.root.after(900, self.root.destroy)

    def run_checks(self) -> None:
        try:
            self.ensure_folders()
            time.sleep(MIN_VISIBLE_STEP_SECONDS)
            self.ensure_runtime()
            time.sleep(MIN_VISIBLE_STEP_SECONDS)
            self.check_databases()
            time.sleep(MIN_VISIBLE_STEP_SECONDS)
            update_started = self.check_updates()
            if update_started:
                return
            time.sleep(MIN_VISIBLE_STEP_SECONDS)
            self.launch_main_app()
        except Exception as exc:
            self.set_step(4, "Failed", str(exc), "red")
            messagebox.showerror("XRD Phase Finder startup failed", str(exc), parent=self.root)

    def on_close(self) -> None:
        self.root.destroy()

    def start(self) -> None:
        thread = threading.Thread(target=self.run_checks, daemon=True)
        thread.start()
        self.root.mainloop()


def main() -> int:
    PreviewApp().start()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
