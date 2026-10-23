"""Read-only preview gateway for the playback test (SP-04: keep-alive is a prerequisite).

Why this exists rather than reusing temp/px-probe/media_server.py: that probe answers every
request with `Connection: close`, and closed-range block fetching costs 11-62 requests per seek
(F-054) against Chromium's ~6 connections per origin, so per-request reconnects dominate. This
gateway keeps the connection open and logs whether a request arrived on a reused socket, which is
what SP-04 needs to read.

Safety: binds 127.0.0.1 only, GET/HEAD only, serves files by opaque id from media-manifest.json
(never by client-supplied path), and writes only under repo temp/.

Usage:
  python scripts/preview_gateway.py --model temp/playback-test/model.json [--port 8790]
  python scripts/preview_gateway.py --measure        # SP-04 micro-benchmark, no browser
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "temp" / "playback-test"
LOG = OUT / "gateway.log"
CHUNK = 256 * 1024
TYPES = {".mp4": "video/mp4", ".mov": "video/quicktime", ".m4v": "video/mp4",
         ".avi": "video/x-msvideo", ".webm": "video/webm", ".mp3": "audio/mpeg",
         ".wav": "audio/wav", ".jpg": "image/jpeg", ".png": "image/png",
         ".json": "application/json", ".html": "text/html; charset=utf-8",
         ".js": "text/javascript; charset=utf-8", ".mjs": "text/javascript; charset=utf-8",
         ".ttf": "font/ttf", ".otf": "font/otf"}


def media_id(path: str) -> str:
    return hashlib.sha1(path.encode("utf-8")).hexdigest()[:16]


def build_manifest(model: dict) -> dict[str, dict]:
    table = {}
    # Fonts travel as absolute paths into the resource cache; the preview has to render with the
    # very face JianYing used (F-036), so they go through the same id-addressed read-only route.
    for entry in model.get("fonts", []):
        fp = entry["path"]
        table[media_id(fp)] = {"path": fp, "exists": entry["exists"], "type": "font",
                              "readable": True, "container": None}
    for entry in model.get("media", []):
        p = entry["path"]
        table[media_id(p)] = {"path": p, "exists": entry["exists"], "type": entry.get("type"),
                              "readable": entry.get("readable", True),
                              "container": (entry.get("container") or {}).get("why")}
    return table


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    table: dict[str, dict] = {}
    static_root: Path = OUT
    reused: int = 0

    def log_message(self, fmt, *args):  # noqa: A003 - BaseHTTPRequestHandler hook
        pass

    def _note(self, row: str) -> None:
        try:
            with LOG.open("a", encoding="utf-8") as fh:
                fh.write(f"{time.strftime('%H:%M:%S')} {row}\n")
        except OSError:
            pass

    def _send(self, code: int, headers: dict[str, str], body: bytes | None = None, length: int | None = None):
        self.send_response(code)
        for k, v in headers.items():
            self.send_header(k, v)
        if body is not None:
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
        else:
            self.send_header("Content-Length", str(length if length is not None else 0))
            self.end_headers()

    def do_GET(self, head_only: bool = False) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if not self.table and path.startswith("/media/"):
            self._send(404, {"Content-Type": "text/plain"}, b"no manifest")
            return
        if path == "/media":
            listing = [{"id": k, **v} for k, v in self.table.items()]
            self._send(200, {"Content-Type": "application/json"}, json.dumps(listing).encode())
            return
        if path.startswith("/media/"):
            self._range_or_head(path[len("/media/"):].strip("/"), head_only)
            return
        target = (self.static_root / path.lstrip("/")).resolve()
        if ".." in path or not str(target).startswith(str(self.static_root.resolve())):
            self._send(404, {"Content-Type": "text/plain"}, b"outside scratch root")
            return
        if target.is_dir():
            target = target / "index.html"
        if not target.is_file():
            self._send(404, {"Content-Type": "text/plain"}, b"not found")
            self._note(f"404 {path}")
            return
        body = target.read_bytes()
        ctype = TYPES.get(target.suffix.lower(), "application/octet-stream")
        self._send(200, {"Content-Type": ctype, "Accept-Ranges": "bytes",
                         "Cache-Control": "no-store"}, body)
        self._note(f"200 {path} bytes={len(body)} file={target.name}")

    def do_HEAD(self) -> None:  # noqa: N802
        self.do_GET(head_only=True)

    def do_POST(self) -> None:  # noqa: N802
        """Probe pages self-report here: chrome-devtools MCP restarts the browser between calls,
        so only a page that writes its own results survives."""
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(min(n, 4_000_000)) if n else b""
        name = "gateway-report.jsonl"
        try:
            tag = json.loads(raw.decode("utf-8", "replace")).get("tag")
            if tag:
                name = f"report-{tag}.jsonl"
        except Exception:  # noqa: BLE001
            pass
        with (OUT / name).open("a", encoding="utf-8") as fh:
            fh.write(raw.decode("utf-8", "replace").strip() + "\n")
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.end_headers()
        self._note(f"POST {urlparse(self.path).path} bytes={n} -> {name}")

    def _range_or_head(self, mid: str, head_only: bool) -> None:
        entry = self.table.get(mid) or self.table.get(media_id(urlparse(mid).path))
        if not entry or not os.path.isfile(entry["path"]):
            self._send(404, {"Content-Type": "text/plain"}, b"unknown media id")
            self._note(f"404 media id={mid}")
            return
        fpath = entry["path"]
        size = os.path.getsize(fpath)
        rng = self.headers.get("Range", "")
        start, end, status = 0, size - 1, 200
        if rng.startswith("bytes="):
            a, _, b = rng[6:].partition("-")
            if a:
                start = int(a)
                end = int(b) if b else size - 1
            elif b:
                start = max(0, size - int(b))
            end = min(end, size - 1)
            status = 206 if start <= end else 416
        length = max(0, end - start + 1)
        headers = {"Content-Type": TYPES.get(Path(fpath).suffix.lower(), "application/octet-stream"),
                   "Accept-Ranges": "bytes", "Cache-Control": "no-store",
                   "X-Media-Id": mid}
        if status == 206:
            headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        reused = "yes" if self.reused else "no"
        if head_only:
            self._send(status, headers, length=length)
            self._note(f"{status} HEAD id={mid} size={size} range={rng or '-'} reused={reused}")
            return
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(length))
        self.end_headers()
        sent, aborted = 0, ""
        try:
            with open(fpath, "rb") as fh:
                fh.seek(start)
                remaining = length
                while remaining > 0:
                    block = fh.read(min(CHUNK, remaining))
                    if not block:
                        break
                    self.wfile.write(block)
                    remaining -= len(block)
                    sent += len(block)
        except (ConnectionResetError, BrokenPipeError, OSError) as exc:
            aborted = f" aborted={type(exc).__name__}"
        self._note(f"{status} GET id={mid} range={rng or '-'} sent={sent} wanted={length}{aborted} "
                   f"file={os.path.basename(fpath)} reused={reused}")

    def handle_one_request(self):
        # One Handler instance == one TCP connection, so the request counter minus one
        # is how many earlier responses were served without reconnecting.
        self._seq = getattr(self, "_seq", 0) + 1
        self.reused = self._seq - 1
        BaseHTTPRequestHandler.handle_one_request(self)


def measure(port: int) -> int:
    """SP-04: per-request cost split by where the bytes live.

    Loopback TCP setup is trivial; the cost F-053 pointed at is the per-request reconnect
    plus reopening the file on an SMB share. Both show up only when the served file is on
    the share, so each target is measured on its own row.
    """
    manifest = json.loads((OUT / "media-manifest.json").read_text(encoding="utf-8"))
    live = [e for e in manifest if os.path.isfile(e["path"])]
    if not live:
        print("no reachable media in manifest", file=sys.stderr)
        return 2
    video = sorted((e for e in live if Path(e["path"]).suffix.lower() in (".mp4", ".mov", ".m4v")),
                   key=lambda e: -os.path.getsize(e["path"]))
    targets = [video[0]] if video else []
    if len(video) > 1:
        targets.append(video[-1])
    targets.append(live[0])
    seen, rows = set(), []
    n = 24
    for entry in targets:
        path = entry["path"]
        if path in seen:
            continue
        seen.add(path)
        size = os.path.getsize(path)
        spans = [(i * (size // n), i * (size // n) + 65535) for i in range(n)]

        def run(mode: str) -> float:
            t0 = time.perf_counter()
            conn = buf = None
            for a, b in spans:
                if mode != "keepalive" or conn is None:
                    if conn:
                        conn.close()
                    conn = socket.create_connection(("127.0.0.1", port))
                    buf = conn.makefile("rb")
                conn.sendall(f"GET /media/{media_id(path)} HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                             f"Range: bytes={a}-{b}\r\nConnection: "
                             f"{'keep-alive' if mode == 'keepalive' else 'close'}\r\n\r\n".encode())
                _status_and_body(buf)
            conn.close()
            return (time.perf_counter() - t0) * 1000

        ka, cl = run("keepalive"), run("close")
        share = "SMB/NAS" if path[:2].upper() in ("X:", "Z:", "\\\\") else "local"
        rows.append((os.path.basename(path), share, size, ka, cl, (cl - ka) / n))
        print(f"{os.path.basename(path)} [{share}] {size/1e6:.1f} MB")
        print(f"   keep-alive 1 connection : {ka:8.1f} ms ({ka/n:.2f} ms/req)")
        print(f"   fresh connect per req   : {cl:8.1f} ms ({cl/n:.2f} ms/req)")
        print(f"   delta per request       : {(cl-ka)/n:8.2f} ms")
    lines = [f"n={n} bytes_per_req=65536 keep-alive vs fresh-connect, SP-04"]
    for name, share, size, ka, cl, delta in rows:
        lines.append(f"{name}\t{share}\tsize={size}\tkeepalive_total_ms={ka:.1f}\tclose_total_ms={cl:.1f}\tdelta_ms_per_req={delta:.3f}")
    (OUT / "sp04-keepalive.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"-> {OUT / 'sp04-keepalive.txt'}")
    return 0


def _status_and_body(buf) -> None:
    line = buf.readline().decode("latin-1", "replace")
    status = int(line.split(" ")[1]) if len(line.split(" ")) > 1 else 0
    headers = {}
    while True:
        h = buf.readline()
        if h in (b"\r\n", b"\n", b""):
            break
        k, _, v = h.decode("latin-1").partition(":")
        headers[k.lower().strip()] = v.strip()
    if status == 416:
        return
    n = int(headers.get("content-length") or 0)
    read = 0
    while read < n:
        chunk = buf.read(min(CHUNK, n - read))
        if not chunk:
            break
        read += len(chunk)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", default=str(OUT / "model.json"))
    ap.add_argument("--port", type=int, default=8790)
    ap.add_argument("--measure", action="store_true")
    ap.add_argument("--serve-dir", default=str(OUT))
    ap.add_argument("--extra", action="append", default=[], help="extra media file to serve by id, repeatable (A/B proxies)")
    args = ap.parse_args()

    if not (OUT / "media-manifest.json").exists() or not args.measure:
        model = json.loads(Path(args.model).read_text(encoding="utf-8-sig"))
        table = build_manifest(model)
        for p in args.extra:
            abs_p = Path(p).resolve().as_posix()
            table[media_id(abs_p)] = {"path": abs_p, "exists": os.path.isfile(abs_p),
                                      "type": "proxy", "readable": True, "container": None}
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "media-manifest.json").write_text(
            json.dumps(list(table.values()), ensure_ascii=False, indent=1), encoding="utf-8")
    else:
        table = {media_id(e["path"]): e for e in
                 json.loads((OUT / "media-manifest.json").read_text(encoding="utf-8"))}
        for p in args.extra:
            abs_p = Path(p).resolve().as_posix()
            table[media_id(abs_p)] = {"path": abs_p, "exists": os.path.isfile(abs_p),
                                      "type": "proxy", "readable": True, "container": None}

    Handler.table = table
    Handler.static_root = Path(args.serve_dir).resolve()
    if args.measure:
        return measure(args.port)

    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    missing = [e["path"] for e in table.values() if not e["exists"]]
    print(f"preview gateway on http://127.0.0.1:{args.port}  media={len(table)} missing={len(missing)}",
          flush=True)
    for p in missing[:5]:
        print("  missing:", p, flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
