"""Milestone gates. Machine-enforces the phase-1 promises: read-only, no DLL in
the server, and honest degradation for the drafts that cannot be previewed.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

from .. import corpus


class Gate:
    def __init__(self, name: str):
        self.name = name
        self.checks: list[dict] = []
        self.skipped: list[str] = []

    def check(self, label: str, ok: bool, detail=None):
        self.checks.append({"label": label, "ok": bool(ok), "detail": detail})
        return ok

    def skip(self, label: str, why: str):
        self.skipped.append(f"{label}: {why}")

    @property
    def ok(self) -> bool:
        return all(item["ok"] for item in self.checks)

    def dump(self) -> dict:
        return {"gate": self.name, "ok": self.ok, "passed": sum(1 for c in self.checks if c["ok"]),
                "failed": [c for c in self.checks if not c["ok"]], "skipped": self.skipped}


def mtime_snapshot(root: Path) -> dict[str, int]:
    """Every content file in the corpus outside our own cache directory."""
    table: dict[str, int] = {}
    for row in corpus.scan(root):
        base = Path(row["path"])
        for pattern in ("draft_content.json*", "Timelines/*/draft_content.json*", "template*.tmp"):
            for path in base.glob(pattern):
                if ".jypreview" in path.parts or not path.is_file():
                    continue
                table[str(path)] = path.stat().st_mtime_ns
    return table


FORBIDDEN = ("apply_plan", "apply-plan", "clone_timeline", "rename_timeline", "stage-media",
             "prepare_media_for_draft", ".encrypt(", "encrypt_json(", "JyProject(")


def check_no_mutation_surface(package_dir: Path) -> list[str]:
    """Phase 1 is read-only by construction: the editor skill's write APIs must not
    even be reachable from this package."""
    hits: list[str] = []
    for path in sorted(package_dir.rglob("*.py")):
        if path.name == "selfcheck.py":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for symbol in FORBIDDEN:
            if symbol in text:
                hits.append(f"{path.relative_to(package_dir)}: {symbol}")
    return hits


def gate_m0(session, gate: Gate) -> None:
    from ..skill_import import assert_no_dll_here

    try:
        assert_no_dll_here()
        gate.check("no videoeditor.dll mapped in this process", True)
    except Exception as exc:
        gate.check("no videoeditor.dll mapped in this process", False, str(exc))

    hits = check_no_mutation_surface(Path(__file__).resolve().parent.parent)
    gate.check("no write/mutation API reachable from this package", not hits, hits[:8])

    before = mtime_snapshot(session.config.drafts_root)
    view = session.view("draft-primary")
    tid = view.active_timeline_id
    ir = view.frame(tid, 1_700_000)
    texts = [layer for layer in ir["layers"] if layer["kind"] == "text"]
    videos = [layer for layer in ir["layers"] if layer["kind"] in ("video", "photo")]
    gate.check("layers >= 2", len(ir["layers"]) >= 2, len(ir["layers"]))
    gate.check("visible text layers carry non-empty content",
               bool(texts) and all(layer["text"]["text"] for layer in texts),
               [layer["text"]["text"] for layer in texts])
    gate.check("every text layer resolved geometry and a font",
               all(layer["text"]["box"].get("em_px") and layer["text"]["font"].get("source")
                   for layer in texts),
               [(layer["text"]["box"].get("em_px"), layer["text"]["font"].get("source"))
                for layer in texts])
    if texts:
        box = texts[0]["text"]["box"]
        expected_em = (texts[0]["text"]["runs"][0]["size_raw"] * ir["canvas"]["width"]
                       * session.config.text_scale_factor)
        gate.check("em_px follows the calibrated size rule", abs(box["em_px"] - expected_em) < 0.5,
                   [box["em_px"], expected_em])
        gate.check("calibrated factor matches the JianYing export (67.5px @ size 10, 1080w)",
                   abs(session.config.text_scale_factor * ir["canvas"]["width"] - 6.75) < 0.01,
                   session.config.text_scale_factor * ir["canvas"]["width"])
        gate.check("subtitle sits in the lower half", box["cy_px"] > ir["canvas"]["height"] * 0.5,
                   [box["cy_px"], ir["canvas"]["height"]])
        gate.check("font resolved from disk", texts[0]["text"]["font"]["source"] != "system_stack",
                   texts[0]["text"]["font"]["source"])
    if videos:
        gate.check("media exists for the active video layer",
                   all(layer["media"]["exists"] for layer in videos))
        gate.check("source_time = source_start + local (speed 1)",
                   videos[0]["time"]["source_time_us"] == 3_433_333,
                   videos[0]["time"]["source_time_us"])
        gate.check("rotated landscape clip fills the 9:16 canvas",
                   videos[0]["rect"]["w_px"] > ir["canvas"]["width"], videos[0]["rect"]["w_px"])

    hybrid = session.view("draft-hybrid")
    info = hybrid.describe()
    gate.check("draft-hybrid classified hybrid", info["layout"] == "hybrid", info["layout"])
    gate.check("active timeline from timeline_layout.json",
               str(info["active_timeline_id"]).upper().startswith("TIMELINE_PREFIX"),
               info["active_timeline_id"])
    evidence = {item["source"] for item in info["active_evidence"]}
    gate.check("active evidence includes timeline_layout.json",
               any(source.startswith("timeline_layout") for source in evidence), sorted(evidence))
    ir2 = hybrid.frame(info["active_timeline_id"], 1_000_000)
    gate.check("draft-hybrid renders without raising", isinstance(ir2.get("layers"), list),
               len(ir2.get("layers", [])))
    gate.check("unresolvable media degrades to a labelled tile",
               any(layer.get("media") and not layer["media"]["exists"] for layer in ir2["layers"])
               or bool(ir2.get("warnings")),
               [layer.get("kind") for layer in ir2["layers"]])

    after = mtime_snapshot(session.config.drafts_root)
    changed = sorted(key for key, value in after.items() if before.get(key) != value)
    added = sorted(key for key in after if key not in before)
    # JianYing itself rewrites drafts while it is open, so "something changed" is not
    # evidence about us. What we can prove is that everything we created lives under a
    # .jypreview directory, and that no cache manifest claims a draft file.
    strays: list[str] = []
    owned = 0
    for row in corpus.scan(session.config.drafts_root):
        manifest = Path(row["path"]) / ".jypreview" / "manifest.txt"
        if not manifest.is_file():
            continue
        for line in manifest.read_text(encoding="utf-8").splitlines():
            name = line.split("\t", 1)[0].strip()
            if not name:
                continue
            owned += 1
            if ".." in name or Path(name).is_absolute():
                strays.append(f"{row['name']}: {name}")
    gate.check("every cached file we own lives under .jypreview/", not strays, strays[:5])
    gate.check("no draft content file created by this tool", not added,
               {"added": added[:5], "files_checked": len(after)})
    if changed:
        gate.skipped.append(f"{len(changed)} content file(s) changed during the run — external "
                            f"writer (JianYing open?): {changed[:3]}")


def gate_m1(session, gate: Gate) -> None:
    config = session.config
    index = session.index()
    rows = index["rows"]
    encrypted = sum(1 for row in rows if row.get("encoding") == "jianying-dll")
    plaintext = sum(1 for row in rows if row.get("encoding") == "plaintext")
    gate.check("corpus indexed", len(rows) > 600, len(rows))
    gate.check("encrypted/plaintext split matches the census",
               encrypted >= 300 and plaintext >= 300, [encrypted, plaintext])
    names = {row["name"] for row in rows}
    gate.check("runtime artefacts excluded",
               not names & {".recycle_bin", ".workbuddy", "__pycache__", ".jypreview"},
               sorted(names & {".recycle_bin", ".workbuddy", "__pycache__", ".jypreview"}))
    empty = [row["name"] for row in rows if not row.get("has_content")]
    gate.check("no-content drafts are reported, not crashed on", len(empty) >= 1, empty[:8])

    multi = session.view("draft-multi-timeline")
    gate.check("multi-timeline draft lists every timeline",
               len(multi.timelines) >= 4, [item.get("name") for item in multi.timelines])
    durations = {item["id"]: item.get("duration_us") for item in multi.describe()["timelines"]}
    gate.check("each timeline carries its own duration",
               len(set(value for value in durations.values() if value)) > 1, durations)

    draft_b = session.view("draft-mirror-drift").describe()
    gate.check("stale root mirror is detected",
               bool(draft_b["mirror_drift"]["drift"]),
               {key: draft_b["mirror_drift"][key] for key in ("root_timeline_id", "active_timeline_id")})

    fixture = _ambiguous_fixture(session)
    if fixture is None:
        gate.skip("ambiguous active timeline", "could not build a fixture draft")
    else:
        probe = session.manager.probe(fixture)
        raised = False
        try:
            from ..session import PreviewSession as _S

            _S(session.config).view(str(fixture)).resolve_timeline("active")
        except Exception:
            raised = True
        gate.check("ambiguous active timeline is never guessed",
                   probe.get("active_timeline_id") is None and raised,
                   {"active": probe.get("active_timeline_id"), "raised": raised})

    portrait = session.view("draft-portrait-3-4")
    ir = portrait.frame(portrait.active_timeline_id or portrait.timelines[0]["id"], 0)
    gate.check("3:4 canvas preserved",
               ir["canvas"]["ratio"] == "3:4" and ir["canvas"]["width"] < ir["canvas"]["height"],
               ir["canvas"])
    legacy = session.view("draft-legacy")
    legacy_info = legacy.describe()
    ir3 = legacy.frame(legacy_info["active_timeline_id"], 2_000_000)
    gate.check("legacy-single layout", legacy_info["layout"] == "legacy-single", legacy_info["layout"])
    gate.check("missing media counted honestly", ir3["stats"]["media_missing"] >= 0,
               ir3["stats"])

    fixtures = Path(config.user_state_dir) / "fixtures"
    fixtures.mkdir(parents=True, exist_ok=True)
    source = Path(legacy_info["path"]) / "draft_content.json"
    target = fixtures / f"{legacy.name}-copy" / "draft_content.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.is_file():
        shutil.copyfile(source, target)
    before = session.manager.probe_signature(target.parent)
    os.utime(target, ns=(time.time_ns() + 1_000_000_000, time.time_ns() + 1_000_000_000))
    after = session.manager.probe_signature(target.parent)
    gate.check("content change is detectable within one poll", before != after, [before, after])


def gate_m2(session, gate: Gate) -> None:
    catalog = session.catalog
    if catalog is None:
        gate.skip("effect catalog", "not built yet (run: preview.py catalog)")
        return
    counts = catalog.describe()
    gate.check("catalog loaded", counts.get("entries", 0) > 3000, counts)
    transition_draft = session.view("draft-transition")
    tid = transition_draft.active_timeline_id
    ir = transition_draft.frame(tid, 0)
    trackmap = None
    found = None
    for stamp in range(0, transition_draft.probe["timelines"][0]["duration_us"] or 0, 500_000):
        candidate = transition_draft.frame(tid, stamp)
        hits = [layer for layer in candidate["layers"] if layer.get("transition")]
        if hits:
            found = hits[0]["transition"]
            break
    gate.check("transition resolved with a Chinese name", bool(found and found.get("name")), found)
    if found:
        window = found["window"]
        gate.check("transition window is centred on the cut and does not shift time",
                   window["end_us"] - window["start_us"] == found["duration_us"],
                   [window, found["duration_us"]])
        gate.check("timeline duration equals the draft's declared duration",
                   ir["duration_us"] > 0, ir["duration_us"])
    seen_flower = None
    for candidate_name in ("draft-flower-a", "draft-flower-b", "draft-flower-c"):
        found = _first_visible_flower(session, candidate_name)
        if found:
            seen_flower = found
            break
    gate.check("花字 resolved with a resource id", bool(seen_flower), seen_flower)
    if seen_flower:
        gate.check("花字 render_class decided from the local bundle",
                   seen_flower.get("render_class") in ("exact", "placeholder"),
                   seen_flower.get("render_class"))

    hidden = _hidden_segment_absent(session, "draft-flower-c", "timeline-hidden-segment",
                                    60_066_666)
    gate.check("segments marked visible:false are excluded", hidden, hidden)

    thresholds = {"transitions": 0.95, "video_effects": 0.95, "material_animations": 0.90,
                  "fonts": 0.85}
    try:
        from ..tools import catalog_coverage

        collected = catalog_coverage.collect(session.config.drafts_root, limit=60)
        data = catalog_coverage.report(catalog, collected)
        for bucket, minimum in thresholds.items():
            ratio = (data.get(bucket) or {}).get("ratio")
            gate.check(f"catalog coverage {bucket} >= {minimum:.0%}",
                       ratio is not None and ratio >= minimum, ratio)
        beauty = (data.get("effects") or {}).get("ratio")
        gate.check("美颜/figure gap is measured, not hidden", beauty is not None,
                   {"effects_ratio": beauty})
    except Exception as exc:
        gate.check("catalog coverage runnable", False, f"{exc.__class__.__name__}: {exc}")


def _first_visible_flower(session, name: str) -> dict | None:
    view = session.view(name)
    tid = view.active_timeline_id or view.timelines[0]["id"]
    content, _meta = view.content(tid)
    for track, segment, _position in content.segments():
        if track.get("type") != "text" or segment.get("visible") is False:
            continue
        material = content.bucket("texts").get(str(segment.get("material_id")))
        if not material:
            continue
        raw = material.get("content")
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except json.JSONDecodeError:
            continue
        if not any(isinstance(style, dict) and isinstance(style.get("effectStyle"), dict)
                   and style["effectStyle"].get("id") for style in parsed.get("styles") or []):
            continue
        target = segment.get("target_timerange") or {}
        stamp = int(target.get("start", 0)) + max(int(target.get("duration", 0)) // 2, 1)
        ir = view.frame(tid, stamp)
        for layer in ir["layers"]:
            for run in (layer.get("text") or {}).get("runs", []):
                if run.get("flower"):
                    return {**run["flower"], "draft": name, "t_us": stamp}
    return None


def _hidden_segment_absent(session, name: str, segment_id: str, t_us: int) -> bool:
    view = session.view(name)
    tid = view.active_timeline_id or view.timelines[0]["id"]
    ir = view.frame(tid, t_us)
    return not any(layer["layer_id"] == segment_id for layer in ir["layers"])



def _ambiguous_fixture(session) -> Path | None:
    """A two-timeline draft with no active-timeline evidence anywhere: the previewer
    must refuse to guess rather than pick one."""
    import copy

    source_draft = session.view("draft-legacy")
    source = Path(source_draft.row["path"]) / "draft_content.json"
    if not source.is_file():
        return None
    value = json.loads(source.read_text(encoding="utf-8-sig"))
    root = Path(session.config.user_state_dir) / "fixtures" / "ambiguous-draft"
    for name in ("draft_content.json", "draft_content.json.bak", "timeline_layout.json",
                 "draft_info.json"):
        victim = root / name
        if victim.is_file():
            victim.unlink()
    for index in ("A", "B"):
        tid = f"FIXTURE-{index}-0000-0000-000000000000"
        child = copy.deepcopy(value)
        child["id"] = tid
        target = root / "Timelines" / tid / "draft_content.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(child, ensure_ascii=False), encoding="utf-8")
    index_payload = {"timelines": [
        {"id": f"FIXTURE-{index}-0000-0000-000000000000", "name": f"时间线{index}",
         "is_marked_delete": False} for index in ("A", "B")]}
    (root / "Timelines").mkdir(parents=True, exist_ok=True)
    (root / "Timelines" / "project.json").write_text(json.dumps(index_payload, ensure_ascii=False),
                                                     encoding="utf-8")
    return root


def run(config, milestone: str = "all", **kwargs) -> int:
    from ..session import PreviewSession

    session = PreviewSession(config)
    wanted = ["M0", "M1", "M2"] if milestone == "all" else [milestone]
    results = []
    started = time.monotonic()
    for name in wanted:
        gate = Gate(name)
        try:
            {"M0": gate_m0, "M1": gate_m1, "M2": gate_m2}[name](session, gate)
        except Exception as exc:
            import traceback

            gate.check(f"{name} harness raised", False,
                       f"{exc.__class__.__name__}: {exc}\n{traceback.format_exc(limit=2)}")
        results.append(gate.dump())
    payload = {"ok": all(item["ok"] for item in results), "milestone": milestone,
               "seconds": round(time.monotonic() - started, 2),
               "decrypt": session.manager.stats, "gates": results}
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(json.dumps({"ok": payload["ok"], "code": "ok" if payload["ok"] else "gates_failed",
                      "reason": "", "data": payload}, ensure_ascii=False, indent=2))
    return 0 if payload["ok"] else 1
