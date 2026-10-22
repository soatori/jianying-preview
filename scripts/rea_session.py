"""Run a batch of REA MCP tool calls against ONE live Ghidra provider session.

Why this exists: REA's snapshot holds *cached observations*, not a saved provider
database (vendor docs cli.md:200), cancelling a request destroys the ephemeral
database (native-investigation.md:77), and the provider socket only opens after
default auto-analysis completes (ghidra-provider.md:38). On a 72 MB target that
analysis is ~40-60 minutes, so asking questions one CLI call at a time pays that
cost per question. One `open_binary` + many `tools/call` + `close_binary` pays it
once.

The server is started as a child process of this script only. Nothing here
registers REA with any agent config or writes outside the artifact directory
(keep that under temp/).

Plan file is a JSON array of steps:
    {"tool": "open_binary", "args": {...}, "save": "00-open.json"}
Results land in <out>/<save>; a step that returns isError stops the batch unless
`--continue-on-error` is given.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

_PKG = "rea-agents@6.5.0"
_PROTOCOL_VERSION = "2025-06-18"


class McpError(RuntimeError):
    pass


class McpStdioClient:
    """Newline-delimited JSON-RPC 2.0 client for an MCP stdio server."""

    def __init__(self, argv: list[str], env: dict[str, str], log_path: Path):
        self.log = log_path.open("w", encoding="utf-8")
        self.proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self.log,
            env=env,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        self._id = 0
        self._pending: dict[int, dict] = {}
        self._lock = threading.Lock()
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    def _read_loop(self) -> None:
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                self.log.write(f"[unparsed] {line[:400]}\n")
                self.log.flush()
                continue
            mid = msg.get("id")
            if mid is None:
                continue  # server-initiated notification, nothing to dispatch
            with self._lock:
                slot = self._pending.get(mid)
            if slot:
                slot["msg"] = msg
                slot["event"].set()

    def _send(self, payload: dict) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
        self.proc.stdin.flush()

    def request(self, method: str, params: dict, timeout_s: float) -> dict:
        with self._lock:
            self._id += 1
            mid = self._id
            self._pending[mid] = {"event": threading.Event(), "msg": None}
        self._send({"jsonrpc": "2.0", "id": mid, "method": method, "params": params})
        slot = self._pending[mid]
        if not slot["event"].wait(timeout_s):
            with self._lock:
                self._pending.pop(mid, None)
            raise McpError(f"{method}: no reply within {timeout_s:.0f}s")
        with self._lock:
            self._pending.pop(mid, None)
        msg = slot["msg"] or {}
        if "error" in msg:
            raise McpError(f"{method}: {json.dumps(msg['error'], ensure_ascii=False)[:600]}")
        return msg.get("result", {})

    def notify(self, method: str) -> None:
        self._send({"jsonrpc": "2.0", "method": method})

    def close(self) -> None:
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
        except OSError:
            pass
        self.proc.terminate()
        try:
            self.proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.log.close()


def find_key(node, key: str):
    """First value stored under `key` anywhere in a nested result."""
    if isinstance(node, dict):
        if key in node:
            return node[key]
        for v in node.values():
            got = find_key(v, key)
            if got is not None:
                return got
    elif isinstance(node, list):
        for v in node:
            got = find_key(v, key)
            if got is not None:
                return got
    return None


def error_envelope(result: dict) -> dict:
    """Parse REA's error JSON out of a tools/call text content block."""
    for block in result.get("content") or []:
        if isinstance(block, dict) and block.get("text"):
            try:
                return json.loads(block["text"])
            except json.JSONDecodeError:
                continue
    return {}


def call_paged(client: McpStdioClient, tool: str, args: dict, out: Path, save: str,
               timeout_s: float, max_pages: int, page_limit: int = 2048) -> tuple[bool, str]:
    """Call a tool, then page any over-budget result through inspect_analysis_view.

    Inventory tools like `list_procedures` expose no limit/offset of their own, so
    a 116,637-row answer always trips the ~10 MiB stdio response budget. REA keeps
    the full result as session-scoped retained Evidence and hands back continuation
    arguments -- so the page loop has to run inside the same live session, which is
    exactly the thing this driver exists to preserve.
    """
    ok, detail = one_call(client, tool, args, out, save, timeout_s)
    if ok:
        return True, detail
    parsed = error_envelope(json.loads((out / save).read_text(encoding="utf-8")))
    cont = find_key(parsed, "continuation")
    if not (isinstance(cont, dict) and cont.get("name") == "inspect_analysis_view"):
        return False, detail
    step_args = cont["arguments"]
    if page_limit and isinstance(step_args.get("view"), dict):
        # The server's default page is 64 rows; at 116,637 procedures that would be
        # ~1,800 round-trips. Ask bigger, stay inside the same response budget.
        step_args = {**step_args, "view": {**step_args["view"], "limit": page_limit}}
    pages = 0
    while pages < max_pages:
        pages += 1
        page_save = save.replace(".json", f".page{pages:03d}.json")
        ok, detail = one_call(client, "inspect_analysis_view", step_args, out, page_save, timeout_s)
        print(f"      page {pages} {'ok' if ok else 'ERROR'} {detail}", flush=True)
        if not ok:
            return False, detail
        body = json.loads((out / page_save).read_text(encoding="utf-8"))
        nxt = find_key(body, "next_offset")
        if nxt is None:
            return True, f"{detail} +{pages} pages"
        step_args = {**step_args, "view": {**step_args["view"], "offset": nxt}}
    return True, f"stopped at max_pages={max_pages}"


def harvest_rows(data: dict, fe: dict) -> list[str]:
    """Pick the identifiers a search result's rows expose, for a follow-up call.

    Analysis tools wrap their envelope under ``structuredContent``; rows are
    ``{address, value}`` under it -- not a top-level ``name`` field (an early
    version walked the envelope for ``name`` and harvested the subject and
    provider names instead, and a later one looked for ``normalized_result`` on
    the outside and silently produced zero follow-ups). Addresses are preferred
    because a demangled display name is not always a valid procedure selector.
    """
    envelope = data.get("structuredContent") if isinstance(data.get("structuredContent"), dict) else data
    rows = envelope.get("normalized_result") or envelope.get("raw_result") or []
    if isinstance(rows, dict):
        rows = rows.get("results") or rows.get("items") or []
    needles = fe.get("filter_substring") or []
    out: list[str] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        name = row.get("value") or row.get("name") or ""
        if needles and not any(n.lower() in str(name).lower() for n in needles):
            continue
        pick = row.get(fe.get("pick", "address")) or name
        if isinstance(pick, str) and pick and pick not in out:
            out.append(pick)
        if len(out) >= int(fe.get("max", 8)):
            break
    return out


def one_call(client: McpStdioClient, tool: str, args: dict, out: Path, save: str, timeout_s: float) -> tuple[bool, str]:
    try:
        result = client.request("tools/call", {"name": tool, "arguments": args}, timeout_s)
    except McpError as exc:
        return False, str(exc)
    (out / save).write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return not bool(result.get("isError")), f"{(out / save).stat().st_size} B"


def run_plan(client: McpStdioClient, plan: list[dict], out: Path, timeout_s: float, keep_going: bool, max_pages: int = 400, page_limit: int = 2048) -> int:
    rc = 0
    for i, step in enumerate(plan):
        tool = step["tool"]
        t0 = time.time()
        if "foreach" in step:
            fe = step["foreach"]
            src = out / fe["from"]
            if not src.exists():
                print(f"[{i:02d}] foreach FAILED: missing {fe['from']}", flush=True)
                rc = 1
                if not keep_going:
                    break
                continue
            values = harvest_rows(json.loads(src.read_text(encoding="utf-8")), fe)
            print(f"[{i:02d}] {tool} foreach {fe['from']} -> {len(values)} calls", flush=True)
            for j, value in enumerate(values):
                args = dict(step.get("args", {}))
                args[fe.get("arg", "procedure")] = value
                save = f"{i:02d}-{tool}-{j:02d}.json"
                ok, detail = call_paged(client, tool, args, out, save, timeout_s, max_pages, page_limit)
                print(f"      [{j:02d}] {'ok' if ok else 'ERROR'} {detail}  {value[:70]}", flush=True)
                if not ok and not keep_going:
                    return 1
            print(f"[{i:02d}] {tool} foreach done in {time.time() - t0:.1f}s", flush=True)
            continue
        save = step.get("save") or f"{i:02d}-{tool}.json"
        ok, detail = call_paged(client, tool, step.get("args", {}), out, save, timeout_s, max_pages, page_limit)
        print(f"[{i:02d}] {tool} {'ok' if ok else 'ERROR'} {time.time() - t0:.1f}s -> {save} ({detail})", flush=True)
        if not ok:
            rc = 1
            if not keep_going:
                break
    return rc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True, help="JSON array of MCP tool steps")
    parser.add_argument("--out", type=Path, required=True, help="artifact dir (keep under temp/)")
    parser.add_argument("--maxmem", default="4G", help="GHIDRA_HEADLESS_MAXMEM (JVM heap cap)")
    parser.add_argument(
        "--startup-timeout-ms",
        type=int,
        default=5_400_000,
        help="REA_GHIDRA_STARTUP_TIMEOUT_MS; 90 min default, max 2147483647",
    )
    parser.add_argument("--step-timeout-s", type=float, default=7_200, help="client-side per-call budget")
    parser.add_argument("--max-pages", type=int, default=400, help="page cap for over-budget results")
    parser.add_argument("--page-limit", type=int, default=2048, help="rows per page when paging an over-budget result")
    parser.add_argument("--continue-on-error", action="store_true")
    parser.add_argument("--catalog", action="store_true", help="dump tools/list into <out>/tools-list.json")
    args = parser.parse_args()

    if "temp" not in [p.lower() for p in args.out.resolve().parts]:
        parser.error("--out must live under a temp/ path (scope.md: artifacts never enter git)")
    args.out.mkdir(parents=True, exist_ok=True)

    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    if not isinstance(plan, list) or not plan:
        parser.error("plan must be a non-empty JSON array")

    env = dict(os.environ)
    env["GHIDRA_HEADLESS_MAXMEM"] = args.maxmem
    env["REA_GHIDRA_STARTUP_TIMEOUT_MS"] = str(args.startup_timeout_ms)
    env.setdefault("REA_ANALYSIS_PROVIDER", "ghidra")
    npx = "npx.cmd" if os.name == "nt" else "npx"

    client = McpStdioClient(
        [npx, "-y", _PKG, "mcp"],
        env,
        args.out / "server-stderr.log",
    )
    rc = 0
    try:
        info = client.request(
            "initialize",
            {
                "protocolVersion": _PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "jianying-preview-native-re", "version": "1"},
            },
            120,
        )
        print("server:", info.get("serverInfo"), "protocol:", info.get("protocolVersion"), flush=True)
        client.notify("notifications/initialized")
        if args.catalog:
            tools = client.request("tools/list", {}, 300)
            (args.out / "tools-list.json").write_text(
                json.dumps(tools, ensure_ascii=False, indent=1), encoding="utf-8"
            )
            names = [t["name"] for t in tools.get("tools", [])]
            print(f"tools/list: {len(names)} tools -> tools-list.json", flush=True)
        rc = run_plan(client, plan, args.out, args.step_timeout_s, args.continue_on_error, args.max_pages, args.page_limit)
    finally:
        client.close()
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
