#!/usr/bin/env python
"""Jianying draft previewer CLI.

Read-only: parses and decrypts drafts, renders a timeline preview, and answers
"what is on screen at time t" for both a human browser and an agent.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))


def _utf8_streams() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def _emit(data, ok: bool = True, code: str = "ok", reason: str = "") -> int:
    print(json.dumps({"ok": ok, "code": code, "reason": reason, "data": data},
                     ensure_ascii=False, indent=2, default=str))
    return 0 if ok else 1


def _config(args):
    from jypreview import config as config_mod

    return config_mod.load({name: getattr(args, name, None) for name in
                            ("drafts_root", "jianying_root", "state_dir", "cache", "port", "host",
                             "text_basis", "text_scale", "fit_mode")})


def cmd_warm(args) -> int:
    from jypreview.cli import warm

    return warm.run(_config(args), full=args.probe, limit=args.limit)


def cmd_drafts(args) -> int:
    from jypreview import corpus

    config = _config(args)
    index = corpus.load_index(config.corpus_index_path)
    if index is None:
        return _emit({"drafts_root": str(config.drafts_root)}, ok=False, code="index_missing",
                     reason="run: preview.py warm")
    rows = index["rows"]
    if args.q:
        needle = args.q.lower()
        rows = [row for row in rows if needle in row["name"].lower() or needle == row["did"]]
    if args.layout:
        rows = [row for row in rows if row.get("layout") == args.layout]
    total = len(rows)
    rows = rows[args.offset:args.offset + args.limit]
    return _emit({"drafts_root": index["drafts_root"], "built_at": index["built_at"],
                  "total": total, "count": len(rows),
                  "items": [{**row, "path": row["path"] if args.paths else row["path"]} for row in rows]},
                 )


def cmd_probe(args) -> int:
    from jypreview import corpus
    from jypreview.decrypt.manager import DecryptManager

    config = _config(args)
    index = corpus.load_index(config.corpus_index_path)
    row = corpus.resolve(index, args.draft) if index else None
    if row is None:
        row = corpus.classify(Path(args.draft))
    manager = DecryptManager(config)
    probe = manager.probe(Path(row["path"]), row["did"], force=args.force)
    return _emit({"classification": {k: row.get(k) for k in
                                    ("did", "name", "layout", "has_content", "encoding",
                                     "active_timeline_id", "active_source", "timeline_count")},
                  "probe": probe, "mirror": manager.mirror_drift(probe),
                  "cache": probe.get("cache"), "decrypt": manager.stats})


def cmd_content(args) -> int:
    """Dump the decrypted timeline content JSON (the raw contract, all unknown keys kept)."""
    from jypreview import corpus
    from jypreview.decrypt.manager import DecryptManager

    config = _config(args)
    index = corpus.load_index(config.corpus_index_path)
    row = (corpus.resolve(index, args.draft) if index else None) or corpus.classify(Path(args.draft))
    manager = DecryptManager(config)
    probe = manager.probe(Path(row["path"]), row["did"])
    tid = args.timeline if args.timeline and args.timeline != "active" else probe.get("active_timeline_id")
    if not tid:
        return _emit({"timelines": [t["id"] for t in probe["timelines"]]}, ok=False,
                     code="timeline_ambiguous", reason="active timeline unresolved; pass --timeline")
    value, meta = manager.content(Path(row["path"]), tid, probe)
    if args.keys:
        materials = value.get("materials", {})
        return _emit({"timeline": tid, "top_keys": sorted(value.keys()),
                      "canvas": value.get("canvas_config"), "fps": value.get("fps"),
                      "duration_us": value.get("duration"),
                      "track_types": [track.get("type") for track in value.get("tracks", [])],
                      "material_counts": {k: len(v) for k, v in materials.items() if isinstance(v, list)}})
    if args.out:
        Path(args.out).write_text(json.dumps(value, ensure_ascii=False, indent=1), encoding="utf-8")
        return _emit({"out": args.out, "timeline": tid, "cache": meta.get("cache")})
    return _emit(value)


def cmd_frame(args) -> int:
    from jypreview.cli import dump_frame

    return dump_frame.run(_config(args), args.draft, timeline=args.timeline, t_us=args.t_us,
                          t=args.t, compact=args.compact, out=args.out, times=args.times,
                          ratio=args.ratio, window=args.window, to=args.to)


def cmd_timelines(args) -> int:
    from jypreview.session import PreviewSession

    session = PreviewSession(_config(args))
    return _emit(session.view(args.draft).describe())


def cmd_what_at(args) -> int:
    from jypreview.cli.dump_frame import parse_time
    from jypreview.session import PreviewSession
    from jypreview import summary

    config = _config(args)
    session = PreviewSession(config)
    view = session.view(args.draft)
    entry = view.resolve_timeline(args.timeline)
    ir = view.frame(entry["id"], parse_time(args.t, args.t_us), ratio=args.ratio)
    return _emit({"t_us": ir["time"]["t_us"], "canvas": ir["canvas"],
                  "duration_us": ir["duration_us"], "who": summary.who_at(ir),
                  "audio": ir["audio_labels"], "stats": ir["stats"], "warnings": ir["warnings"]})


def cmd_catalog(args) -> int:
    from pathlib import Path

    config = _config(args)
    out_dir = Path(args.out) if args.out else \
        Path(__file__).resolve().parent.parent / "assets" / "generated"
    if args.q or args.stats:
        from jypreview.model.catalog import EffectCatalog

        catalog = EffectCatalog.load(out_dir / "effect_catalog.json",
                                     allow_version_skew=args.allow_catalog_skew)
        if catalog is None:
            return _emit({"path": str(out_dir / "effect_catalog.json")}, ok=False,
                         code="catalog_missing", reason="run: preview.py catalog")
        if args.stats:
            return _emit(catalog.describe())
        return _emit({"query": args.q, "kind": args.kind, "count": len(catalog.search(
            args.q, args.kind, args.render_class, args.limit)),
            "items": catalog.search(args.q, args.kind, args.render_class, args.limit)})

    from jypreview.tools import build_effect_catalog as builder

    cache_root = (Path(config.jianying_root) / "User Data" / "Cache") if config.jianying_root else None
    metadata = builder.build(cache_root, out_dir, use_rp_db=not args.no_rp_db)
    return _emit({**metadata, "out": str(out_dir / "effect_catalog.json")})


def cmd_clean(args) -> int:
    from pathlib import Path

    from jypreview import corpus
    from jypreview.session import PreviewSession

    config = _config(args)
    session = PreviewSession(config)
    if args.draft:
        rows = [session.row(args.draft)]
    else:
        index = corpus.load_index(config.corpus_index_path) or {"rows": []}
        rows = index["rows"]
    report = []
    for row in rows:
        cache = session.manager.cache_for(Path(row["path"]), row["did"])
        removed = cache.clean() if args.apply else 0
        report.append({"did": row["did"], "name": row["name"], "cache": str(cache.root),
                       "removed": removed, "applied": bool(args.apply)})
    return _emit({"drafts": len(report), "removed_total": sum(item["removed"] for item in report),
                  "dry_run": not args.apply, "items": report[:40]})


def cmd_ir_diff(args) -> int:
    import json
    from pathlib import Path

    from jypreview.cli.dump_frame import parse_time
    from jypreview.ir_diff import diff
    from jypreview.session import PreviewSession

    config = _config(args)
    session = PreviewSession(config)
    view = session.view(args.draft)
    tid = view.resolve_timeline(args.timeline)["id"]

    def side(prefix: str) -> dict:
        explicit = getattr(args, f"{prefix}_file")
        if explicit:
            return json.loads(Path(explicit).read_text(encoding="utf-8"))
        return view.frame(tid, parse_time(getattr(args, f"{prefix}_t"), None))

    left, right = side("a"), side("b")
    payload = diff(left, right, only=args.fields.split(",") if args.fields else None)
    payload["timeline"] = tid
    payload["a_t_us"] = left["time"]["t_us"]
    payload["b_t_us"] = right["time"]["t_us"]
    return _emit(payload)


def cmd_calibrate(args) -> int:
    from pathlib import Path

    from jypreview.cli import calibrate

    return calibrate.run(_config(args), args.draft, timeline=args.timeline, samples=args.samples,
                         out=args.out, base=args.base)


def cmd_selfcheck(args) -> int:
    from jypreview.cli import selfcheck

    return selfcheck.run(_config(args), args.milestone, draft=args.draft, t_us=args.t_us)


def cmd_shot(args) -> int:
    from jypreview.cli import shot

    return shot.run(_config(args), args.draft, timeline=args.timeline, t_us=args.t_us, t=args.t,
                    out=args.out, view=args.view, width=args.w, height=args.h, base=args.base,
                    force_local=args.no_server, ratio=args.ratio)


def cmd_serve(args) -> int:
    import asyncio

    from jypreview.server.app import run
    from jypreview.server.lifecycle import SessionLease

    try:
        lease = (None if args.persistent else
                 (SessionLease(args.lease_token, args.lease_ttl) if args.lease_token else None))
        asyncio.run(run(_config(args), open_browser=not args.no_browser, lease=lease))
    except KeyboardInterrupt:
        pass
    return 0


def _forward_common(args: argparse.Namespace) -> list[str]:
    forwarded: list[str] = []
    for name, flag in (("drafts_root", "--drafts-root"), ("jianying_root", "--jianying-root"),
                       ("state_dir", "--state-dir"), ("cache", "--cache"),
                       ("host", "--host")):
        value = getattr(args, name, None)
        if value:
            forwarded.extend([flag, str(value)])
    return forwarded


def cmd_launch(args) -> int:
    """Start one leased server session and open the human preview page."""
    config = _config(args)
    token = secrets.token_urlsafe(24)
    command = [sys.executable, str(Path(__file__).resolve()), "serve", "--no-browser",
               "--port", "0", "--lease-token", token, "--lease-ttl", str(args.lease_ttl)]
    command.extend(_forward_common(args))
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, encoding="utf-8", errors="replace",
                               creationflags=creationflags)
    session_dir = Path(config.user_state_dir) / "sessions"
    session_dir.mkdir(parents=True, exist_ok=True)
    session_path = session_dir / f"{token}.json"
    try:
        line = process.stdout.readline() if process.stdout else ""
        payload = json.loads(line) if line else {}
        if not payload.get("ok"):
            detail = process.stderr.read() if process.stderr else ""
            return _emit({"stderr": detail, "child": payload}, ok=False,
                         code="launch_failed", reason="preview server did not start")
        data = payload.get("data") or {}
        query = {"lease": token, "draft": args.draft}
        if args.timeline:
            query["timeline"] = args.timeline
        url = data["url"] + "?" + urllib.parse.urlencode(query)
        session_path.write_text(json.dumps({"token": token, "url": data["url"],
                                             "pid": process.pid}, ensure_ascii=False),
                                encoding="utf-8")
        webbrowser.open(url)
        print(json.dumps({"ok": True, "code": "launched", "reason": "",
                          "data": {"url": url, "session": token, "pid": process.pid}},
                         ensure_ascii=False), flush=True)
        process.wait()
        return 0
    except KeyboardInterrupt:
        try:
            request = urllib.request.Request(data["url"].rstrip("/") + "/api/session/close?token=" +
                                             urllib.parse.quote(token), method="POST")
            urllib.request.urlopen(request, timeout=3).read()
        except Exception:
            process.terminate()
        return 130
    finally:
        try:
            session_path.unlink()
        except FileNotFoundError:
            pass


def cmd_close(args) -> int:
    config = _config(args)
    session_path = Path(config.user_state_dir) / "sessions" / f"{args.session}.json"
    if not session_path.is_file():
        return _emit({"session": args.session}, ok=False, code="session_not_found",
                     reason="preview session file not found")
    info = json.loads(session_path.read_text(encoding="utf-8"))
    request = urllib.request.Request(info["url"].rstrip("/") + "/api/session/close?token=" +
                                     urllib.parse.quote(info["token"]), method="POST")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.load(response)
    finally:
        try:
            session_path.unlink()
        except FileNotFoundError:
            pass
    return _emit(payload.get("data", {}), ok=bool(payload.get("ok")),
                 code=payload.get("code", "ok"), reason=payload.get("reason", ""))


def build_parser() -> argparse.ArgumentParser:
    from jypreview import config as config_mod

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    common = argparse.ArgumentParser(add_help=False)
    config_mod.add_arguments(common)
    sub = parser.add_subparsers(dest="command", required=True)

    warm = sub.add_parser("warm", parents=[common],
                          help="classify every draft into the corpus index (no decryption)")
    warm.add_argument("--probe", action="store_true", help="also decrypt each draft's primary content")
    warm.add_argument("--limit", type=int)
    warm.set_defaults(func=cmd_warm)

    drafts = sub.add_parser("drafts", parents=[common], help="list the indexed corpus")
    drafts.add_argument("--q")
    drafts.add_argument("--layout", choices=("legacy-single", "multi-timeline", "hybrid", "unknown"))
    drafts.add_argument("--limit", type=int, default=50)
    drafts.add_argument("--offset", type=int, default=0)
    drafts.add_argument("--paths", action="store_true")
    drafts.set_defaults(func=cmd_drafts)

    probe = sub.add_parser("probe", parents=[common],
                           help="layout, timelines, active resolution, replicas")
    probe.add_argument("draft", help="draft id, folder name or path")
    probe.add_argument("--force", action="store_true")
    probe.set_defaults(func=cmd_probe)

    content = sub.add_parser("content", parents=[common],
                             help="dump decrypted timeline content JSON")
    content.add_argument("draft")
    content.add_argument("--timeline", default="active")
    content.add_argument("--keys", action="store_true", help="only summarise keys and counts")
    content.add_argument("--out", help="write JSON to this file instead of stdout")
    content.set_defaults(func=cmd_content)

    frame = sub.add_parser("frame", parents=[common],
                           help="FrameDescriptor IR for one instant (or many)")
    frame.add_argument("draft")
    frame.add_argument("--timeline", default="active")
    frame.add_argument("--t", help="1.7 | 1.7s | 1700ms | 0:01.7 | 1700000us")
    frame.add_argument("--t-us", type=int)
    frame.add_argument("--times", help="comma separated list (<=60) for batch diffs")
    frame.add_argument("--compact", action="store_true", help="one line per layer")
    frame.add_argument("--ratio", help="override 画幅 for the what-if: 16:9 16:10 4:3 3:4 1:1 9:16")
    frame.add_argument("--window", type=float,
                       help="seconds from --t: return every layer touching that span, not one instant")
    frame.add_argument("--to", type=float, help="seconds: explicit window end (with --t as its start)")
    frame.add_argument("--out", help="write IR json to a file")
    frame.set_defaults(func=cmd_frame)

    timelines = sub.add_parser("timelines", parents=[common],
                               help="list timelines with active resolution and replicas")
    timelines.add_argument("draft")
    timelines.set_defaults(func=cmd_timelines)

    what_at = sub.add_parser("what-at", parents=[common],
                             help="compact 'who is on screen at t' (agent assertion surface)")
    what_at.add_argument("draft")
    what_at.add_argument("--timeline", default="active")
    what_at.add_argument("--t", default="0")
    what_at.add_argument("--t-us", type=int)
    what_at.add_argument("--ratio", help="override 画幅: 16:9 4:3 3:4 1:1 9:16")
    what_at.set_defaults(func=cmd_what_at)

    selfcheck = sub.add_parser("selfcheck", parents=[common], help="run milestone gates")
    selfcheck.add_argument("--milestone", default="all", choices=("M0", "M1", "M2", "M3", "M4", "all"))
    selfcheck.add_argument("--draft", default="draft-primary")
    selfcheck.add_argument("--t-us", type=int, default=1_700_000)
    selfcheck.set_defaults(func=cmd_selfcheck)

    shot = sub.add_parser("shot", parents=[common],
                          help="render one instant to PNG via headless Chromium (needs `serve`)")
    shot.add_argument("draft")
    shot.add_argument("--timeline", default="active")
    shot.add_argument("--t", help="1.7 | 1700ms | 0:01.7")
    shot.add_argument("--t-us", type=int)
    shot.add_argument("--out", help="destination png (default: ~/.jypreview/shots/…)")
    shot.add_argument("--view", choices=("stage", "ui"), default="stage")
    shot.add_argument("--ratio", help="override 画幅: 16:9 16:10 4:3 3:4 1:1 9:16")
    shot.add_argument("--w", type=int)
    shot.add_argument("--h", type=int)
    shot.add_argument("--base", help="preview server base URL (default: http://127.0.0.1:<port>/)")
    shot.add_argument("--no-server", action="store_true", help="launch a private headless browser instead")
    shot.set_defaults(func=cmd_shot)

    catalog = sub.add_parser("catalog", parents=[common],
                             help="build or query the 特效/动画/转场 对照表")
    catalog.add_argument("--q", help="search by Chinese name or id")
    catalog.add_argument("--kind", default="")
    catalog.add_argument("--render-class", default="")
    catalog.add_argument("--limit", type=int, default=30)
    catalog.add_argument("--stats", action="store_true", help="print catalog metadata")
    catalog.add_argument("--no-rp-db", action="store_true", help="vendor enums only")
    catalog.add_argument("--out", help="output directory (default: <skill>/assets/generated)")
    catalog.set_defaults(func=cmd_catalog)

    clean = sub.add_parser("clean", parents=[common],
                           help="remove the .jypreview cache this tool created inside drafts")
    clean.add_argument("draft", nargs="?", help="draft id/name/path (omit for all)")
    clean.add_argument("--apply", action="store_true", help="actually delete (default is dry-run)")
    clean.set_defaults(func=cmd_clean)

    ir = sub.add_parser("ir-diff", parents=[common],
                        help="layer-level diff of two instants or two saved IR snapshots")
    ir.add_argument("draft")
    ir.add_argument("--timeline", default="active")
    ir.add_argument("--a-t", default="0", help="time A, e.g. 1.7")
    ir.add_argument("--b-t", default="0", help="time B")
    ir.add_argument("--a-file", help="saved IR json (from: frame --out)")
    ir.add_argument("--b-file", help="saved IR json")
    ir.add_argument("--fields", help="comma separated fingerprint fields to care about")
    ir.set_defaults(func=cmd_ir_diff)

    calibrate = sub.add_parser("calibrate", parents=[common],
                               help="compare our render against JianYing's own draft_cover.jpg")
    calibrate.add_argument("draft")
    calibrate.add_argument("--timeline", default="active")
    calibrate.add_argument("--samples", type=int, default=12)
    calibrate.add_argument("--out")
    calibrate.add_argument("--base")
    calibrate.set_defaults(func=cmd_calibrate)

    serve = sub.add_parser("serve", parents=[common], help="start the read-only preview server")
    serve.add_argument("--no-browser", action="store_true", help="do not open a browser window")
    serve.add_argument("--persistent", action="store_true", help="disable lease expiry for Agent mode")
    serve.add_argument("--lease-token", help="enable an expiring browser session")
    serve.add_argument("--lease-ttl", type=float, default=15.0, help="seconds without heartbeat before exit")
    serve.set_defaults(func=cmd_serve)

    launch = sub.add_parser("launch", parents=[common],
                            help="start one leased server session and open the preview page")
    launch.add_argument("draft", help="draft id, folder name or path")
    launch.add_argument("--timeline", default="", help="optional timeline id")
    launch.add_argument("--lease-ttl", type=float, default=15.0)
    launch.set_defaults(func=cmd_launch)

    close = sub.add_parser("close", parents=[common], help="close a launched preview session")
    close.add_argument("--session", required=True, help="session token printed by launch")
    close.set_defaults(func=cmd_close)
    return parser


def main(argv: list[str] | None = None) -> int:
    _utf8_streams()
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130
    except SystemExit:
        raise
    except Exception as exc:
        payload = {"type": exc.__class__.__name__}
        for attr in ("candidates", "hint", "available", "code"):
            value = getattr(exc, attr, None)
            if value:
                payload[attr] = value
        return _emit(payload, ok=False, code=getattr(exc, "code", "error") or "error",
                     reason=str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
