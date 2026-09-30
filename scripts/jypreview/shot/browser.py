"""Persistent headless Chromium controlled over raw CDP.

Why not ``headless_shell --screenshot``: with one-shot CLI mode this build either
attaches to an existing browser instance or hangs while the page keeps fetching
(seekable video is a permanent fetch). One long-lived instance driven by
``Runtime.evaluate`` + ``Page.captureScreenshot`` is faster and deterministic.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

CANDIDATES = (
    # Order matters: Playwright's Chromium and the headless-shell build report
    # canPlayType('video/mp4; codecs="avc1..."') === "" so H.264 drafts decode no
    # frames (readyState 4, videoWidth 0). Edge/Chrome ship the proprietary codecs.
    Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"),
    Path("C:/Program Files/Microsoft/Edge/Application/msedge.exe"),
    Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
    Path.home() / "AppData/Local/ms-playwright/chromium-1169/chrome-win/chrome.exe",
    Path.home() / "AppData/Local/ms-playwright/chromium_headless_shell-1169/chrome-win/headless_shell.exe",
)


def find_browser() -> Path | None:
    for candidate in CANDIDATES:
        if candidate.is_file():
            return candidate
    for name in ("chrome-headless-shell", "chromium", "chrome", "msedge"):
        found = shutil.which(name)
        if found:
            return Path(found)
    root = Path.home() / "AppData/Local/ms-playwright"
    if root.is_dir():
        for shell in sorted(root.glob("*/chrome-win/headless_shell.exe")):
            return shell
    return None


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


class BrowserSession:
    def __init__(self, state_dir: Path, prefer: str | None = None):
        self.state_dir = Path(state_dir)
        self.port = _free_port()
        self.binary = Path(prefer) if prefer else find_browser()
        # A user-data-dir may only ever be used by one browser family, so key it by
        # binary name instead of sharing it across Edge/Chromium/headless-shell.
        self.profile = self.state_dir / "profiles" / (self.binary.stem if self.binary else "default")
        self.proc: subprocess.Popen | None = None
        self.started_at = 0.0
        self.last_error: str | None = None
        self.fallback_profile: Path | None = None

    @property
    def running(self) -> bool:
        return bool(self.proc) and self.proc.poll() is None

    def start(self) -> None:
        if self.running:
            return
        if not self.binary:
            self.last_error = "no Chromium/Edge binary found for screenshots"
            raise RuntimeError(self.last_error)
        try:
            self._launch(self.profile)
            return
        except RuntimeError as first:
            self.last_error = str(first)
        # A profile orphaned by a killed browser makes every later launch exit instantly, and
        # Windows often refuses to rename or delete the directory while something holds a
        # handle inside it, so the only reliable recovery is a sibling profile.
        stem = self.binary.stem if self.binary else "default"
        for attempt in range(3):
            sibling = self.state_dir / "profiles" / f"{stem}-{int(time.time())}-{attempt}"
            try:
                self._launch(sibling)
                self.fallback_profile = sibling
                self._prune_siblings(keep=sibling)
                return
            except RuntimeError as exc:
                self.last_error = f"{self.last_error} | retry with {sibling.name}: {exc}"
        raise RuntimeError(self.last_error)

    def _prune_siblings(self, keep: Path) -> None:
        """Recovery creates a profile per launch; drop the ones no browser is holding.

        Only `msedge-<ts>-<n>` style names are matched, so the canonical profile directory
        (which may be locked by a browser that is still shutting down) is never touched.
        """
        root = self.state_dir / "profiles"
        prefix = keep.name.split("-")[0]
        for entry in sorted(root.glob(f"{prefix}-*"), reverse=True):
            if entry == keep or not entry.is_dir():
                continue
            shutil.rmtree(entry, ignore_errors=True)

    def _launch(self, profile: Path) -> None:
        self.profile = Path(profile)
        self.profile.mkdir(parents=True, exist_ok=True)
        cmd = [str(self.binary), f"--remote-debugging-port={self.port}",
               f"--user-data-dir={profile}", "--headless=new" if "msedge" in self.binary.name
               else "--headless",
               "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
               "--force-device-scale-factor=1", "--mute-audio",
               "--disk-cache-size=1", "--remote-allow-origins=*", "about:blank"]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        log_path = self.state_dir / f"browser-{self.binary.stem}.log"
        log = open(log_path, "wb")
        self.proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=log,
                                     stderr=subprocess.STDOUT, creationflags=flags)
        self.started_at = time.time()
        deadline = time.time() + 20
        while time.time() < deadline:
            if not self.running:
                try:
                    log.flush()
                    tail = log_path.read_text(encoding="utf-8", errors="replace")[-300:]
                except OSError:
                    tail = ""
                self.proc = None
                self.last_error = f"browser exited during startup ({self.binary}) {tail}".strip()
                raise RuntimeError(self.last_error)
            try:
                self._http("/json/version")
                break
            except Exception:
                time.sleep(0.15)
        else:
            self.stop()
            self.last_error = f"devtools endpoint never came up on port {self.port}"
            raise RuntimeError(self.last_error)
        log.close()

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            try:
                self._http("/json/close")
            except Exception:
                pass
            self.proc.terminate()
            try:
                self.proc.wait(3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None

    def _http(self, suffix: str, method: str = "GET") -> Any:
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}{suffix}", method=method)
        with urllib.request.urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))

    def targets(self) -> list[dict[str, Any]]:
        return self._http("/json/list")

    def new_page(self, url: str = "about:blank") -> dict[str, Any]:
        """DevTools requires PUT for /json/new on modern Chromium builds."""
        try:
            page = self._http(f"/json/new?{urllib.parse.quote(url, safe='/:?=&')}", method="PUT")
            if isinstance(page, dict) and page.get("webSocketDebuggerUrl"):
                return page
        except Exception:
            pass
        pages = [item for item in self.targets() if item.get("type") == "page"]
        if pages:
            return pages[0]
        raise RuntimeError("no devtools page target available")

    def info(self) -> dict[str, Any]:
        try:
            version = self._http("/json/version")
        except Exception as exc:
            version = {"error": str(exc)}
        return {"running": self.running, "port": self.port, "binary": str(self.binary) if self.binary else None,
                "profile": str(self.profile), "uptime_s": round(time.time() - self.started_at, 1)
                                          if self.running else 0,
                "version": {key: version.get(key) for key in ("Browser", "protocolVersion") if isinstance(version, dict)},
                "last_error": self.last_error}
