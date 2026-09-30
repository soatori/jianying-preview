"""Restart the preview server in a detached process so it outlives this shell.

`preview.py serve` must keep running after the agent's turn ends, and Bash-spawned
children are killed with the session; a DETACHED_PROCESS child is not.

    python -m jypreview.tools.restart_server

Exits non-zero if the port stays busy after the old process is killed, or if the new
server never answers `/api/state`.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

PYTHON = sys.executable
SCRIPTS = Path(__file__).resolve().parents[2]
LOG = Path.home() / ".jypreview" / "server.log"
PORT = int(os.environ.get("JY_PREVIEW_PORT", "8765"))
HOST = "127.0.0.1"


def port_owner() -> int | None:
    out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True,
                         errors="replace").stdout
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[1].endswith(f":{PORT}") and parts[3] == "LISTENING":
            return int(parts[4])
    return None


def stop(pid: int) -> None:
    # Only the recorded port owner, never `/IM python.exe`: that would also kill the
    # resident server and its headless browser.
    subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
    for _ in range(40):
        if port_owner() is None:
            return
        time.sleep(0.25)


def main() -> int:
    pid = port_owner()
    if pid:
        print(f"stopping server pid={pid}")
        stop(pid)
    if port_owner() is not None:
        print("port still busy")
        return 1

    LOG.parent.mkdir(parents=True, exist_ok=True)
    log = open(LOG, "a", encoding="utf-8", buffering=1)      # noqa: SIM115
    log.write(f"\n=== restart {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
    flags = 0x00000008 | 0x00000200                          # DETACHED_PROCESS | NEW_PROCESS_GROUP
    # The sandbox exports an outbound proxy; left in place it also swallows every request
    # the server makes to its own headless browser on 127.0.0.1 (HTTP 502).
    env = {key: value for key, value in os.environ.items()
           if key.lower() not in ("http_proxy", "https_proxy", "all_proxy")}
    process = subprocess.Popen(
        [PYTHON, "preview.py", "serve", "--no-browser", "--port", str(PORT)],
        cwd=str(SCRIPTS), stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
        creationflags=flags, close_fds=True, env=env)
    print(f"spawned pid={process.pid}")

    last: Exception | None = None
    for _ in range(120):
        time.sleep(0.5)
        try:
            with urllib.request.urlopen(f"http://{HOST}:{PORT}/api/state", timeout=5) as response:
                payload = json.load(response)
            if payload.get("ok"):
                data = payload["data"]
                print("serving:", data["config"]["drafts_root"], "frames_built",
                      data["server"]["frames_built"])
                return 0
        except Exception as exc:                              # noqa: BLE001
            last = exc
    print("server did not answer:", last)
    return 1


if __name__ == "__main__":
    sys.exit(main())
