"""Build the corpus index without decrypting anything."""

from __future__ import annotations

import json
import sys
import time

from .. import corpus


def run(config, *, full: bool = False, limit: int | None = None, quiet: bool = False) -> int:
    started = time.monotonic()
    if config.drafts_root is None:
        print(json.dumps({"ok": False, "code": "drafts_root_not_found", "reason": "", "data": {}},
                         ensure_ascii=False))
        return 1
    rows = corpus.scan(config.drafts_root, progress=False)
    if limit:
        rows = rows[:limit]
    summary = corpus.write_index(config.corpus_index_path, config.drafts_root, rows)
    summary["seconds"] = round(time.monotonic() - started, 2)
    summary["index"] = str(config.corpus_index_path)
    summary["errors"] = [row["name"] for row in rows if row.get("error")]
    summary["full_probe"] = full
    if not quiet:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        print(json.dumps({"ok": not summary["errors"], "code": "ok" if not summary["errors"] else "partial",
                          "reason": "", "data": summary}, ensure_ascii=False, indent=2))
    return 0 if not summary["errors"] else 1
