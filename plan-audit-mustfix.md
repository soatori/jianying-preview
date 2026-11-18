# Audit Must-Fix (Findings 1–9) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the nine Must-fix defects from the 2026-11-18 repo audit so the verification layer stops reporting passes it did not earn, and stops being able to write outside its sandbox.

**Architecture:** Each fix is the smallest change that removes the defect, paired with a regression test that fails on the old code. Two fixes need a small seam extracted (an A/B measurement function, a report-wait loop) so the behaviour can be tested without launching Chrome. One fix replaces twelve scattered `else` branches with a single layer registry plus a reconciliation pass. The browser fix is tested by running the real `tick` source in a Node `vm` sandbox with a fake clock.

**Tech Stack:** Python 3.15.2 (project venv), stdlib `unittest`, numpy 2.5.4, Pillow 13.0.0, Node v26.13.0 (`node:test` + `node:vm`) for the one JS test. No new dependencies.

**Spec:** the audit report delivered in this session on 2026-11-18 (findings 1–9, "Must fix"). There is no separate spec file; the finding text is reproduced per task below so each task stands alone.

**Plan location note:** the writing-plans default is `docs/superpowers/plans/`. This repo's `.gitignore` ignores `/docs/`, and the established tracked convention is a root-level `plan-*.md` (see `plan-m2-playback-tail.md`). This plan follows the repo convention so it is version-controlled. `AGENTS.md`'s claim that `docs/` is a separate git repo is stale — `docs/` does not exist.

## Global Constraints

Every task's requirements implicitly include this section.

- **Interpreter:** always `temp/venv/Scripts/python.exe`. Never bare `python` — the PATH interpreter has no Pillow, so `render_frame` and `playback_check` raise `ImportError`.
- **Test runner:** `temp/venv/Scripts/python.exe -m unittest discover -s tests -t . -v` run from the repo root. Verified working.
- **JS test runner:** `node --test tests/` run from the repo root. Node v26.13.0 confirmed on PATH.
- **No new dependencies.** stdlib `unittest` only. Do not add pytest. `requirements.txt` documents an unreliable PyPI link (15 s read timeouts, connection resets).
- **CRLF — every file you will edit is CRLF.** Verified for all fourteen target files. Preserve CRLF exactly. After editing, run `git diff --ignore-cr-at-eol --stat`; if a file shows a whole-file rewrite instead of a few lines, line endings were mangled — fix that before committing. Never let an editor normalize to LF.
- **Scratch output only under `temp/`.** Tests must not write anywhere else. `temp/` is gitignored.
- **Tests use synthetic in-memory data only.** No real drafts, no media files, no exported films, no fixture binaries. `AGENTS.md` forbids committing draft copies, test fixtures and exported films. Generate models as dicts and images with `Image.new` inside the test.
- **Read-only toward JianYing.** Nothing in this plan writes into a draft folder or the JianYing install.
- **Do not change any criterion threshold.** No line in `CRITERIA`, no `--min-export`, no `--min-cross`, no luma band may be edited by this plan. Task 6 changes *measured numbers*; it must report the delta and stop for a human decision, never silently re-baseline.
- **Commits need consent.** `AGENTS.md` requires asking before committing. Before each commit step, show `git diff --ignore-cr-at-eol` and get the user's OK. Stage files by name, never `git add -A`.
- **Do not touch `evidence/`, `spec/`, or `plan-m2-playback-tail.md`.** This plan changes code and adds tests only.

---

## File Structure

**Created:**

| File | Responsibility |
|---|---|
| `tests/__init__.py` | One place that puts `scripts/` and `scripts/jy_crypto/` on `sys.path`. Every test file relies on it; no per-file path boilerplate. |
| `tests/test_playback_model.py` | Task 1 — material resolution must not crash. |
| `tests/test_animation_wiring.py` | Task 2 — the off-arm must really disable animations. |
| `tests/test_evidence_paths.py` | Task 3 — output paths point at the tracked tables. |
| `tests/test_color_alpha.py` | Task 4 — colour adjustment preserves alpha. |
| `tests/test_gateway_tag.py` | Task 5 — report filenames stay inside the scratch root. |
| `tests/test_frame_ruler.py` | Task 6 — one ruler, shared with `browser_shot_check`. |
| `tests/test_soak_wait.py` | Task 7 — the report wait sleeps and is bounded. |
| `tests/test_layer_registry.py` | Task 8 — no criterion disappears silently. |
| `tests/player_tick_guard.test.mjs` | Task 9 — a slow paint never overlaps another paint. |

**Modified:**

| File | Change | Task |
|---|---|---|
| `scripts/playback_model.py:215` | tolerate an unresolved material | 1 |
| `scripts/animation_wiring_check.py:86-95` | extract `ab_measure`, reset the flag for the off-arm | 2 |
| `scripts/field_census.py:25`, `track_matrix.py:20`, `track_flag_census.py:23`, `render_index_allocators.py:32`, `mixmode_join.py:26` | `docs/evidence/tables` → `evidence/tables` | 3 |
| `scripts/js_model_extract.py:24` | `parents[2]` → `parents[1]` | 3 |
| `scripts/render_frame.py:639-702` | carry alpha through colour adjustment | 4 |
| `scripts/preview_gateway.py:207,240` | one `safe_tag` helper, used by `/wave` and `/report` | 5 |
| `scripts/frame_parity.py:34,155-183` | import the shared ruler, delete the local copies | 6 |
| `scripts/browser_soak.py:109-120` | extract `wait_for_report`, add a sleep | 7 |
| `scripts/playback_check.py:302,970,+end of main` | normalize two names, add registry + reconciliation | 8 |
| `player/player.html:2151-2186` | re-entrancy guard on `tick` | 9 |

All fourteen modules the tests import were verified import-safe (no side effects that raise). All fourteen target files verified CRLF.

---

## Task 1: Model builder survives an unresolved material

**Finding 2.** `scripts/playback_model.py:215` does `bucket, mat = self.material_of(seg.get("material_id"))`. `material_of` returns `None` when the id is absent or dangling, so unpacking raises `TypeError` — before line 217, which exists to report exactly that case. Proven by execution: both a dangling id and an absent id crash. The advertised error path is unreachable.

**Files:**
- Create: `tests/__init__.py`, `tests/test_playback_model.py`
- Modify: `scripts/playback_model.py:215`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `tests/__init__.py` puts `scripts/` and `scripts/jy_crypto/` on `sys.path` for **every** later test file. Later tasks import modules directly (`import render_frame`) with no path setup of their own.

- [x] **Step 1: Create the shared test bootstrap**

Create `tests/__init__.py`:

```python
"""Puts the script directories on sys.path once for the whole test package."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "scripts", ROOT / "scripts" / "jy_crypto"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
```

- [x] **Step 2: Write the failing test**

Create `tests/test_playback_model.py`:

```python
"""Finding 2: an unresolved material must be reported, not crash the build."""
import unittest
from pathlib import Path

import playback_model as pm


def _seg(**kw):
    base = {"id": "S1",
            "target_timerange": {"start": 0, "duration": 1_000_000},
            "source_timerange": {"start": 0, "duration": 1_000_000}}
    base.update(kw)
    return base


class MaterialResolution(unittest.TestCase):
    def setUp(self):
        self.model = pm.Model({"materials": {}, "tracks": []}, Path("."))

    def test_dangling_material_id_is_reported(self):
        out = self.model.segment(_seg(material_id="NOPE"), {"type": "video"})
        self.assertEqual(out["material"]["id"], "NOPE")
        self.assertIsNone(out["material"]["type"])
        self.assertTrue(any("dangling material_id" in e for e in self.model.errors),
                        self.model.errors)

    def test_absent_material_id_is_reported(self):
        out = self.model.segment(_seg(), {"type": "video"})
        self.assertIsNone(out["material"]["bucket"])
        self.assertTrue(any("dangling material_id" in e for e in self.model.errors),
                        self.model.errors)

    def test_resolved_material_still_works(self):
        model = pm.Model({"materials": {"videos": [{"id": "V1", "type": "video"}]},
                          "tracks": []}, Path("."))
        out = model.segment(_seg(material_id="V1"), {"type": "video"})
        self.assertEqual(out["material"]["bucket"], "videos")
        self.assertEqual(out["material"]["type"], "video")
        self.assertEqual(model.errors, [])


if __name__ == "__main__":
    unittest.main()
```

- [x] **Step 3: Run the test to verify it fails**

Run: `temp/venv/Scripts/python.exe -m unittest discover -s tests -t . -v`

Expected: `test_dangling_material_id_is_reported` and `test_absent_material_id_is_reported` ERROR with
`TypeError: cannot unpack non-iterable NoneType object`. `test_resolved_material_still_works` passes.

- [x] **Step 4: Apply the one-line fix**

In `scripts/playback_model.py`, line 215, replace:

```python
        bucket, mat = self.material_of(seg.get("material_id"))
```

with:

```python
        bucket, mat = self.material_of(seg.get("material_id")) or (None, None)
```

This is the idiom the same file already uses at line 208 in `speed_for`. Everything downstream of line 215 already guards `mat` (`if mat and mat.get("path")`, `(mat or {}).get("type")`, `if bucket == "audios" and mat`), so no other line changes.

- [x] **Step 5: Run the test to verify it passes**

Run: `temp/venv/Scripts/python.exe -m unittest discover -s tests -t . -v`

Expected: `Ran 3 tests ... OK`.

- [x] **Step 6: Confirm no line-ending damage, then commit with consent**

Run: `git diff --ignore-cr-at-eol --stat`
Expected: `scripts/playback_model.py | 2 +-` plus the two new test files. A whole-file rewrite means CRLF was mangled — fix before committing.

Show the diff to the user, get consent, then:

```bash
git add tests/__init__.py tests/test_playback_model.py scripts/playback_model.py
git commit -m "fix: 材料解不出来时记错误而不是崩掉建模（审查 2）"
```

---

## Task 2: The animation off-arm must really turn animations off

**Finding 1.** `scripts/animation_wiring_check.py:86-92` renders four frames. Line 88 sets `APPLY_ANIMATIONS = False` for the inside off-arm, but line 90 sets it back to `True` and line 92 never resets it. So `on_out` and `off_out` are identical renders, `max_abs_outside` is always 0, and the check "动画期外逐字节相同（曲线不常驻）" (line 117) can never fail. This script is a live gate layer — `playback_check.py:920` runs it for L8.

**Files:**
- Create: `tests/test_animation_wiring.py`
- Modify: `scripts/animation_wiring_check.py:86-95` (extract a function), and the call site at `:93-100`

**Interfaces:**
- Consumes: `tests/__init__.py` from Task 1.
- Produces: `animation_wiring_check.ab_measure(model: dict, inside: float, outside: float) -> dict` with keys `on_in`, `off_in` (both `np.ndarray`), `max_abs_inside` (int), `cells_changed_inside` (int), `max_abs_outside` (int). Task 2's test patches the module-global `render`, so `ab_measure` must call `render(...)` by its module-level name, not a local alias.

- [x] **Step 1: Write the failing test**

Create `tests/test_animation_wiring.py`:

```python
"""Finding 1: the outside-window check must be able to fail."""
import unittest

import numpy as np

import animation_wiring_check as awc
import render_frame as rf


class OffArmHasTeeth(unittest.TestCase):
    def setUp(self):
        self._render = awc.render
        self._flag = rf.APPLY_ANIMATIONS

    def tearDown(self):
        awc.render = self._render
        rf.APPLY_ANIMATIONS = self._flag

    def test_flag_sequence_is_on_off_on_off(self):
        seen = []

        def fake_render(model, t):
            seen.append(rf.APPLY_ANIMATIONS)
            return np.zeros((4, 4, 3), dtype=np.int16)

        awc.render = fake_render
        awc.ab_measure({}, 0.05, 0.25)
        self.assertEqual(seen, [True, False, True, False])

    def test_resident_curve_is_detected_outside_the_window(self):
        # Negative control: a curve that stays applied everywhere must produce
        # a non-zero outside difference. With the bug both arms render ON, so
        # the difference is 0 and the gate check passes on a real defect.
        def fake_render(model, t):
            value = 10 if rf.APPLY_ANIMATIONS else 0
            return np.full((4, 4, 3), value, dtype=np.int16)

        awc.render = fake_render
        got = awc.ab_measure({}, 0.05, 0.25)
        self.assertGreater(got["max_abs_outside"], 0)
        self.assertGreater(got["max_abs_inside"], 0)


if __name__ == "__main__":
    unittest.main()
```

- [x] **Step 2: Run the test to verify it fails**

Run: `temp/venv/Scripts/python.exe -m unittest discover -s tests -t . -v`

Expected: both new tests ERROR with `AttributeError: module 'animation_wiring_check' has no attribute 'ab_measure'`.

- [x] **Step 3: Extract the seam and fix the missing reset**

In `scripts/animation_wiring_check.py`, insert this function immediately after `render` (after line 55, before `def main`):

```python
def ab_measure(model: dict, inside: float, outside: float) -> dict:
    """开/关各画一次。off 臂必须真的关掉动画，否则窗外那条判据恒过。"""
    rf.APPLY_ANIMATIONS = True
    on_in = render(model, inside)
    rf.APPLY_ANIMATIONS = False
    off_in = render(model, inside)
    rf.APPLY_ANIMATIONS = True
    on_out = render(model, outside)
    rf.APPLY_ANIMATIONS = False
    off_out = render(model, outside)
    return {"on_in": on_in, "off_in": off_in,
            "max_abs_inside": int(np.abs(on_in - off_in).max()),
            "cells_changed_inside": int((np.abs(on_in - off_in) > 2).sum()),
            "max_abs_outside": int(np.abs(on_out - off_out).max())}
```

Then in `main`, replace lines 86-95 (the eight flag/render lines and the three difference lines) with:

```python
        ab = ab_measure(model, inside, outside)
        on_in, off_in = ab["on_in"], ab["off_in"]
        d_in = ab["max_abs_inside"]
        cells_in = ab["cells_changed_inside"]
        d_out = ab["max_abs_outside"]
```

Lines 96 onward (the two `.save` calls, `rows.append`, the `print`) stay exactly as they are. Line 106's `rf.APPLY_ANIMATIONS = True` stays.

- [x] **Step 4: Run the test to verify it passes**

Run: `temp/venv/Scripts/python.exe -m unittest discover -s tests -t . -v`

Expected: `Ran 5 tests ... OK`.

- [x] **Step 5: Prove the real gate layer still runs**

Run: `temp/venv/Scripts/python.exe scripts/animation_wiring_check.py --model temp/playback-test/model-proxy-p157.json --out-dir temp/playback-test/animwiring`

Expected: five PASS/FAIL lines and `N of 5 animation wiring checks passed`. The outside Δmax column may now be **non-zero** — that is the check finally measuring something. Record the numbers; do not adjust any threshold to make them pass. If a check now fails, that is a real defect surfaced, not a regression from this task: report it and stop for a decision.

- [x] **Step 6: Confirm no line-ending damage, then commit with consent**

Run: `git diff --ignore-cr-at-eol --stat`
Expected: only `scripts/animation_wiring_check.py` plus the new test file.

Show the diff, get consent, then:

```bash
git add tests/test_animation_wiring.py scripts/animation_wiring_check.py
git commit -m "fix: 动画窗外判据的 off 臂真的关掉动画（审查 1，此前恒过）"
```

---

## Task 3: Output paths point at the tracked tables

**Finding 9.** `docs/` was merged into the repo root; the tables live at `evidence/tables/`. Five scripts still use `ROOT/'docs'/'evidence'/'tables'`, which does not exist and is gitignored — so their output lands where nothing reads it. `mixmode_join.load_glsl()` returns `{}` silently, emptying the blend-function column. Separately `js_model_extract.py:24` uses `parents[2]`, resolving to `D:\Agents\develop` (above the repo). All confirmed by importing the modules and printing `OUT`/`ROOT`.

**Files:**
- Create: `tests/test_evidence_paths.py`
- Modify: `scripts/field_census.py:25`, `scripts/track_matrix.py:20`, `scripts/track_flag_census.py:23`, `scripts/render_index_allocators.py:32`, `scripts/mixmode_join.py:26`, `scripts/js_model_extract.py:24`

**Interfaces:**
- Consumes: `tests/__init__.py` from Task 1.
- Produces: each module's `OUT` resolves to `<repo>/evidence/tables`; `js_model_extract.ROOT` resolves to the repo root. `mixmode_join.load_glsl()` returns a non-empty dict keyed by `package_md5`.

- [x] **Step 1: Write the failing test**

Create `tests/test_evidence_paths.py`:

```python
"""Finding 9: census output must land in the tracked tables, not a dead docs/ tree."""
import importlib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULES = ("field_census", "track_matrix", "track_flag_census",
           "render_index_allocators", "mixmode_join")


class EvidencePaths(unittest.TestCase):
    def test_out_points_at_the_tracked_tables(self):
        want = (ROOT / "evidence" / "tables").resolve()
        self.assertTrue(want.is_dir(), f"missing {want}")
        for name in MODULES:
            with self.subTest(module=name):
                mod = importlib.import_module(name)
                self.assertEqual(Path(mod.OUT).resolve(), want)

    def test_js_model_extract_root_is_the_repo(self):
        mod = importlib.import_module("js_model_extract")
        self.assertEqual(Path(mod.ROOT).resolve(), ROOT.resolve())
        self.assertEqual(Path(mod.OUT).resolve(), (ROOT / "evidence" / "tables").resolve())

    def test_glsl_join_is_not_empty(self):
        mod = importlib.import_module("mixmode_join")
        table = mod.load_glsl()
        self.assertTrue(table, "load_glsl() returned {} — it is reading a path that does not exist")
        self.assertTrue(all(len(k) == 32 for k in table), list(table)[:3])


if __name__ == "__main__":
    unittest.main()
```

- [x] **Step 2: Run the test to verify it fails**

Run: `temp/venv/Scripts/python.exe -m unittest discover -s tests -t . -v`

Expected: all three FAIL. The first reports `docs\evidence\tables != evidence\tables` for five subtests; the second reports `D:\Agents\develop != D:\Agents\develop\jianying-preview`; the third reports `load_glsl() returned {}`.

- [x] **Step 3: Fix the six paths**

In each of `scripts/field_census.py:25`, `scripts/track_matrix.py:20`, `scripts/track_flag_census.py:23`, `scripts/render_index_allocators.py:32`, `scripts/mixmode_join.py:26`, replace:

```python
OUT = ROOT / 'docs' / 'evidence' / 'tables'
```

with:

```python
OUT = ROOT / 'evidence' / 'tables'
```

In `scripts/js_model_extract.py:24`, replace:

```python
ROOT = Path(__file__).resolve().parents[2]
```

with:

```python
ROOT = Path(__file__).resolve().parents[1]
```

`js_model_extract.py:29` (`OUT = ROOT / 'docs' / 'evidence' / 'tables'`) becomes correct once `ROOT` is fixed only if the `docs` segment is also dropped — change that line to:

```python
OUT = ROOT / 'evidence' / 'tables'
```

- [x] **Step 4: Run the test to verify it passes**

Run: `temp/venv/Scripts/python.exe -m unittest discover -s tests -t . -v`

Expected: `Ran 8 tests ... OK`.

- [x] **Step 5: Check the docstrings that still say docs/**

Run: `grep -rn "docs/evidence" scripts/*.py`

Expected: only docstring/comment hits remain (e.g. `build_evidence_tables.py:1`, `mixmode_join.py:6,8`, `media_probe.py:6,14`). Update those docstring paths to `evidence/...` in the same six files you touched, so the next reader is not sent to a dead directory. Do not edit files outside the six.

- [x] **Step 6: Confirm no line-ending damage, then commit with consent**

Run: `git diff --ignore-cr-at-eol --stat`
Expected: six scripts, one or two lines each, plus the new test file.

Show the diff, get consent, then:

```bash
git add tests/test_evidence_paths.py scripts/field_census.py scripts/track_matrix.py scripts/track_flag_census.py scripts/render_index_allocators.py scripts/mixmode_join.py scripts/js_model_extract.py
git commit -m "fix: 六个脚本的产物路径跟上 docs 并库（审查 9，GLSL 连接此前恒空）"
```

---

## Task 4: Colour adjustment must not make transparent layers opaque

**Finding 7.** `scripts/render_frame.py:648` does `img.convert("RGB")` (dropping alpha) and line 702 returns `Image.fromarray(...).convert("RGBA")` (alpha = 255 everywhere). Proven by execution: a fully transparent 40×40 RGBA logo with `brightness=0.2` goes from alpha extrema `(0, 0)` to `(255, 255)`. Stretched to the canvas it then hides everything beneath — the exact failure the comment at line 102 warns about for `decode_frame`.

**Files:**
- Create: `tests/test_color_alpha.py`
- Modify: `scripts/render_frame.py:639-702` (`apply_color_adjust`)

**Interfaces:**
- Consumes: `tests/__init__.py` from Task 1.
- Produces: `render_frame.apply_color_adjust(img: Image.Image, seg: dict) -> Image.Image` preserves the input alpha channel exactly when any adjustment is applied, and returns the input unchanged (identity) when no branch fires.

- [x] **Step 1: Write the failing test**

Create `tests/test_color_alpha.py`:

```python
"""Finding 7: a transparent logo must stay transparent after colour adjustment."""
import unittest

import numpy as np
from PIL import Image

import render_frame as rf


def _seg(**values):
    return {"features": {"effect_values": values}}


class ColorAdjustAlpha(unittest.TestCase):
    def test_transparent_logo_keeps_its_alpha(self):
        logo = Image.new("RGBA", (40, 40), (255, 0, 0, 0))
        out = rf.apply_color_adjust(logo, _seg(brightness=0.2))
        self.assertEqual(out.getchannel("A").getextrema(), (0, 0))

    def test_partial_alpha_is_preserved_per_pixel(self):
        arr = np.zeros((8, 8, 4), dtype=np.uint8)
        arr[..., :3] = 120
        arr[..., 3] = np.arange(64, dtype=np.uint8).reshape(8, 8) * 4
        logo = Image.fromarray(arr, "RGBA")
        out = rf.apply_color_adjust(logo, _seg(brightness=0.1))
        self.assertEqual(out.getchannel("A").tobytes(), logo.getchannel("A").tobytes())

    def test_opaque_image_alpha_stays_opaque(self):
        img = Image.new("RGBA", (8, 8), (10, 20, 30, 255))
        out = rf.apply_color_adjust(img, _seg(brightness=0.2))
        self.assertEqual(out.getchannel("A").getextrema(), (255, 255))

    def test_no_adjustment_returns_the_same_object(self):
        img = Image.new("RGBA", (8, 8), (10, 20, 30, 128))
        self.assertIs(rf.apply_color_adjust(img, _seg()), img)
        self.assertIs(rf.apply_color_adjust(img, _seg(contrast=0.5)), img)

    def test_brightness_still_changes_the_colour(self):
        img = Image.new("RGBA", (8, 8), (100, 100, 100, 255))
        out = rf.apply_color_adjust(img, _seg(brightness=0.2))
        self.assertGreater(np.asarray(out)[..., 0].mean(), 100)


if __name__ == "__main__":
    unittest.main()
```

Note: `contrast=0.5` is deliberately outside `COLOR["branches"]` (`brightness`, `light_sensation`), so it must be a no-op. Do not widen `COLOR["branches"]` — the other branches are gated back pending calibration and that is a recorded decision, not a defect.

- [x] **Step 2: Run the test to verify it fails**

Run: `temp/venv/Scripts/python.exe -m unittest discover -s tests -t . -v`

Expected: `test_transparent_logo_keeps_its_alpha` FAILS with `(255, 255) != (0, 0)`; `test_partial_alpha_is_preserved_per_pixel` FAILS on the byte comparison. The other three pass.

- [x] **Step 3: Carry the alpha channel through**

In `scripts/render_frame.py`, inside `apply_color_adjust`, replace line 648:

```python
    a = np.asarray(img.convert("RGB"), dtype=np.float32) / 255.0
```

with:

```python
    src_alpha = img.getchannel("A") if img.mode in ("RGBA", "LA") else None
    a = np.asarray(img.convert("RGB"), dtype=np.float32) / 255.0
```

and replace the return at line 702:

```python
    return Image.fromarray((a * 255).astype(np.uint8)).convert("RGBA")
```

with:

```python
    out = Image.fromarray((a * 255).astype(np.uint8)).convert("RGBA")
    if src_alpha is not None:
        out.putalpha(src_alpha)
    return out
```

No other line in the function changes. The early returns at lines 641-647 already return `img` untouched, which is why `test_no_adjustment_returns_the_same_object` passes both before and after.

- [x] **Step 4: Run the test to verify it passes**

Run: `temp/venv/Scripts/python.exe -m unittest discover -s tests -t . -v`

Expected: `Ran 13 tests ... OK`.

- [x] **Step 5: Confirm an unadjusted frame is still byte-identical**

Run:
```bash
temp/venv/Scripts/python.exe scripts/render_frame.py --model temp/playback-test/model-proxy-p157.json --t 1.0 --out temp/playback-test/alpha-after-1.0.png
```

Expected: a PNG is written and the run exits 0. If a pre-change render of the same moment exists, compare bytes; if not, note that the pixel re-baseline belongs to Task 6's checkpoint and do not claim pixel equality here.

- [x] **Step 6: Confirm no line-ending damage, then commit with consent**

Run: `git diff --ignore-cr-at-eol --stat`
Expected: `scripts/render_frame.py` a few lines, plus the new test file.

Show the diff, get consent, then:

```bash
git add tests/test_color_alpha.py scripts/render_frame.py
git commit -m "fix: 调色不再把透明叠层刷成不透明（审查 7）"
```

---

## Task 5: Report filenames must stay inside the scratch root

**Finding 6.** `scripts/preview_gateway.py:240` builds `name = f"report-{tag}.jsonl"` from a `tag` taken straight out of the POST body, with no filtering, then appends to `OUT / name`. Proven: `tag="../../../../../../temp/pwned"` resolves to `D:\Agents\temp\pwned.jsonl`, outside the scratch root. There is no Origin check, so any page open in that browser can append text to any path the process can write. The `/wave` handler at line 207 already sanitizes correctly — reuse it.

**Files:**
- Create: `tests/test_gateway_tag.py`
- Modify: `scripts/preview_gateway.py` — add `safe_tag`, use it at `/wave` (line 207) and `/report` (line 240)

**Interfaces:**
- Consumes: `tests/__init__.py` from Task 1.
- Produces: `preview_gateway.safe_tag(raw: str) -> str` — returns a non-empty filename fragment containing only `[A-Za-z0-9._-]`, never starting with a dot, at most 60 characters. Both POST handlers use it.

- [x] **Step 1: Write the failing test**

Create `tests/test_gateway_tag.py`:

```python
"""Finding 6: a POST body must not be able to name a file outside temp/."""
import unittest
from pathlib import Path

import preview_gateway as gw


class SafeTag(unittest.TestCase):
    def test_traversal_cannot_escape_the_scratch_root(self):
        out = gw.OUT.resolve()
        for tag in ("../../../../../../../../temp/pwned",
                    "..\\..\\..\\windows\\temp\\pwned",
                    "/etc/passwd", "C:/Windows/evil", "....", ".", ""):
            with self.subTest(tag=tag):
                name = f"report-{gw.safe_tag(tag)}.jsonl"
                resolved = (gw.OUT / name).resolve()
                self.assertTrue(str(resolved).startswith(str(out)),
                                f"{tag!r} escaped to {resolved}")

    def test_allowed_characters_survive(self):
        self.assertEqual(gw.safe_tag("check0"), "check0")
        self.assertEqual(gw.safe_tag("live-pacing_2.jsonl"), "live-pacing_2.jsonl")

    def test_result_is_never_empty_and_never_leading_dot(self):
        for tag in ("", ".", "..", "///", "..."):
            got = gw.safe_tag(tag)
            self.assertTrue(got)
            self.assertFalse(got.startswith("."))

    def test_length_is_bounded(self):
        self.assertLessEqual(len(gw.safe_tag("x" * 500)), 60)

    def test_separators_are_removed_not_replaced_by_traversal(self):
        got = gw.safe_tag("a/b\\c")
        self.assertNotIn("/", got)
        self.assertNotIn("\\", got)


if __name__ == "__main__":
    unittest.main()
```

- [x] **Step 2: Run the test to verify it fails**

Run: `temp/venv/Scripts/python.exe -m unittest discover -s tests -t . -v`

Expected: all five ERROR with `AttributeError: module 'preview_gateway' has no attribute 'safe_tag'`.

- [x] **Step 3: Add the helper and use it in both handlers**

In `scripts/preview_gateway.py`, insert immediately after `media_id` (after line 52):

```python
def safe_tag(raw: str) -> str:
    """POST  body 里的名字只能落成 scratch 根下的一个文件名，不许带路径。"""
    cleaned = "".join(c for c in str(raw) if c.isalnum() or c in "._-").lstrip(".")
    return cleaned[:60] or "report"
```

In `do_POST`, replace the `/wave` line 207:

```python
            nm = "".join(c for c in nm if c.isalnum() or c in "._-").lstrip(".") or "preview-capture"
```

with:

```python
            nm = safe_tag(nm) or "preview-capture"
```

and replace the `/report` lines 239-241:

```python
            tag = obj.get("tag")
            if tag:
                name = f"report-{tag}.jsonl"
```

with:

```python
            tag = obj.get("tag")
            if tag:
                name = f"report-{safe_tag(tag)}.jsonl"
```

Leave the `/shot` handler alone: its `tag` comes from `t` with dots already replaced, and changing its filename scheme would break `browser_shot_check`'s and `frame_parity`'s name matching. That is out of scope for this finding.

- [x] **Step 4: Run the test to verify it passes**

Run: `temp/venv/Scripts/python.exe -m unittest discover -s tests -t . -v`

Expected: `Ran 18 tests ... OK`.

- [x] **Step 5: Confirm the gate's own tags are unchanged**

The gate posts with tags `playback` (page default), `livepacing`, and `shot`. Verify `safe_tag` leaves all three byte-identical, so no report filename the gate reads changes:

Run:
```bash
temp/venv/Scripts/python.exe -c "import sys; sys.path.insert(0,'scripts'); import preview_gateway as g; print([g.safe_tag(t) for t in ('playback','livepacing','shot')])"
```
Expected: `['playback', 'livepacing', 'shot']`.

- [x] **Step 6: Confirm no line-ending damage, then commit with consent**

Run: `git diff --ignore-cr-at-eol --stat`
Expected: `scripts/preview_gateway.py` a few lines, plus the new test file.

Show the diff, get consent, then:

```bash
git add tests/test_gateway_tag.py scripts/preview_gateway.py
git commit -m "fix: 网关报告名不再能被 POST body 带出 scratch 根（审查 6）"
```

---

## Task 6: One ruler for frame parity, shared with the gate

**Finding 8.** `scripts/frame_parity.py` claims to inherit `browser_shot_check.py`'s convention and thresholds. Three disagreements, all confirmed by execution:
1. `frame_parity.luma` resizes with Pillow's default, verified to be **BICUBIC** in Pillow 13; `browser_shot_check.luma_at` uses **BOX**.
2. `frame_parity.corr` returns **1.0** when both images are flat — black versus white scores a perfect 1.0. `browser_shot_check.corr` gives **0.0** for the same pair.
3. It is pure Python over 129,600 pixels, ~7,735 calls per judge run (~9 minutes), where numpy takes seconds.

**Files:**
- Create: `tests/test_frame_ruler.py`
- Modify: `scripts/frame_parity.py:34` (drop the now-unused PIL import), `:155-183` (delete local `corr`/`mean_lum`, rewire the cache), and the import block near `:36`

**Interfaces:**
- Consumes: `tests/__init__.py` from Task 1; `browser_shot_check.luma_at(path_or_arr, w, h) -> np.ndarray`, `browser_shot_check.corr(a, b) -> float`, `browser_shot_check.mean_lum(path_or_arr, w, h) -> float` — all three already exist and are unchanged by this task.
- Produces: `frame_parity.luma(png, w, h)` returns the same normalized `np.ndarray` as `browser_shot_check.luma_at`, memoized. `frame_parity.corr` and `frame_parity.mean_lum` are the shared functions, re-exported by import.

- [x] **Step 1: Write the failing test**

Create `tests/test_frame_ruler.py`:

```python
"""Finding 8: frame_parity must use the same ruler as browser_shot_check."""
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

import browser_shot_check as bsc
import frame_parity as fp

W, H = 270, 480


class OneRuler(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory(dir="temp")
        self.addCleanup(self._dir.cleanup)
        self.root = Path(self._dir.name)

    def _png(self, name, colour):
        p = self.root / name
        Image.new("RGB", (W, H), colour).save(p)
        return p

    def test_flat_black_vs_white_is_not_a_perfect_score(self):
        black, white = self._png("b.png", (0, 0, 0)), self._png("w.png", (255, 255, 255))
        got = fp.corr(fp.luma(black, W, H), fp.luma(white, W, H))
        want = bsc.corr(bsc.luma_at(black, W, H), bsc.luma_at(white, W, H))
        self.assertEqual(got, want)
        self.assertLess(got, 0.5, "a wholly wrong flat frame must not read as perfect")

    def test_luma_matches_the_shared_ruler_pixel_for_pixel(self):
        rng = np.random.default_rng(7)
        p = self.root / "noise.png"
        Image.fromarray(rng.integers(0, 256, (960, 540, 3), dtype=np.uint8)).save(p)
        np.testing.assert_array_equal(fp.luma(p, W, H), bsc.luma_at(p, W, H))

    def test_mean_lum_matches_the_shared_ruler(self):
        p = self._png("grey.png", (128, 128, 128))
        self.assertAlmostEqual(fp.mean_lum(p, W, H), bsc.mean_lum(p, W, H), places=4)

    def test_identical_images_score_one(self):
        p = self._png("grey.png", (90, 120, 150))
        self.assertAlmostEqual(fp.corr(fp.luma(p, W, H), fp.luma(p, W, H)), 1.0, places=5)


if __name__ == "__main__":
    unittest.main()
```

- [x] **Step 2: Run the test to verify it fails**

Run: `temp/venv/Scripts/python.exe -m unittest discover -s tests -t . -v`

Expected: `test_flat_black_vs_white_is_not_a_perfect_score` FAILS (`1.0 != 0.0`), `test_luma_matches_the_shared_ruler_pixel_for_pixel` FAILS on the array comparison (BICUBIC vs BOX, and bytes vs ndarray). The other two may pass or fail depending on dtype; record what you see.

- [x] **Step 3: Import the shared ruler and delete the local copies**

In `scripts/frame_parity.py`, add to the import block after line 37:

```python
from browser_shot_check import corr, luma_at, mean_lum  # noqa: E402  同一把尺，不另抄一份
```

Delete the whole local `def corr(a: bytes, b: bytes) -> float:` block (lines 171-178) and the whole local `def mean_lum(png, w, h)` block (lines 181-183).

Replace the body of `luma` (line 163) so the cache stores the shared ruler's array:

```python
        v = luma_at(png, w, h)
```

**Also lower the cache cap in the same function.** The old cache stored `bytes` (129,600 B per entry); the shared ruler returns a normalized `float32` array (518,400 B per entry — 4× larger). Keeping the existing cap of 2600 would grow the cache from a measured 321 MB to **1285 MB**, on a machine that is also running Chrome. Replace the two eviction lines:

```python
        if len(_LUMA) > 2600:
            for k in list(_LUMA)[: 600]:
```

with:

```python
        if len(_LUMA) > 600:
            for k in list(_LUMA)[: 150]:
```

That holds the cache near 297 MB, comparable to before. The ±3 alignment search only ever touches seven consecutive export frames, so 600 entries is far more than the working set needs. The surrounding `key` / `_LUMA.get` lines stay exactly as they are.

Delete line 34 `from PIL import Image` — verified that line 163 was its only use.

- [x] **Step 4: Run the test to verify it passes**

Run: `temp/venv/Scripts/python.exe -m unittest discover -s tests -t . -v`

Expected: `Ran 22 tests ... OK`.

- [x] **Step 5: Measure the speed win on synthetic data**

Run:
```bash
temp/venv/Scripts/python.exe -c "import sys,time; sys.path.insert(0,'scripts'); sys.path.insert(0,'tests'); import test_frame_ruler as t; import frame_parity as fp; from PIL import Image; import numpy as np; p='temp/ruler-speed.png'; Image.fromarray(np.random.default_rng(1).integers(0,256,(1920,1080,3),dtype=np.uint8)).save(p); a=fp.luma(p,270,480); b=fp.luma(p,270,480); t0=time.perf_counter(); [fp.corr(a,b) for _ in range(200)]; print('200 corr calls: %.3f s' % (time.perf_counter()-t0))"
```
Expected: well under one second for 200 calls (the old pure-Python version took roughly 70 ms per call). Record the number.

- [ ] **Step 6: CHECKPOINT — the numbers change, so stop for a decision**

Switching BICUBIC → BOX changes every measured correlation. The `0.90` line was pre-registered against the old ruler. **Do not accept a new verdict silently.**

The pixel artifacts are currently **absent** from `temp/` (verified: 0 oracle frames, 0 browser shots). So this checkpoint cannot run today. It must run before the change is accepted as a measurement:

1. Regenerate the oracle frames from the export and re-sweep the preview:
   `temp/venv/Scripts/python.exe scripts/frame_parity.py --sweep --stride 1 --model model-proxy-p157.json`
   (`--model` is a name relative to `temp/playback-test/`; `model-proxy-p157.json` is the script's default and is present. The export mp4 and the dense oracle frames must be regenerated first — supply `--frames-dir` if they land somewhere other than the default `temp/playback-test/oracle/dense216`.)
2. Judge with the new ruler and keep the report:
   `temp/venv/Scripts/python.exe scripts/frame_parity.py --judge --report temp/playback-test/frame-parity-newruler.json`
3. Report to the user: the pass/fail counts, the corr distribution (min / p05 / p50 / p95 / max), and the luma out-of-band count, **alongside the historical baseline of 1105 frames / 9 red / 318 out-of-band**.
4. Ask whether `0.90` and the `0.96–1.04` luma band still stand under the new ruler. Do not edit either threshold yourself.

If the artifacts cannot be regenerated in this session, say so explicitly and leave the checkpoint open. The unit tests above prove the ruler is now shared; they do **not** prove the pixel verdict is unchanged.

- [x] **Step 7: Confirm no line-ending damage, then commit with consent**

Run: `git diff --ignore-cr-at-eol --stat`
Expected: `scripts/frame_parity.py` roughly -25/+3 lines, plus the new test file.

Show the diff, get consent, then:

```bash
git add tests/test_frame_ruler.py scripts/frame_parity.py
git commit -m "fix: 逐帧尺子改用与门同一把（审查 8：BICUBIC/BOX 不一致、纯色恒 1.0、纯 Python 相关）"
```

---

## Task 7: The report wait must sleep

**Finding 3.** `scripts/browser_soak.py:110-120` waits for the page to post its results with no sleep in the loop. It re-reads the entire report file every iteration — measured at 1.23 MB for `report-playback.jsonl` — for the whole run (10 s battery, ~40 s live pacing, up to 600 s soak). That saturates a CPU core and hammers the disk on the machine whose frame timings the gate judges against a 33.4 ms line. Independently found by both audit passes.

**Files:**
- Create: `tests/test_soak_wait.py`
- Modify: `scripts/browser_soak.py:109-120` (extract `wait_for_report`, add a sleep)

**Interfaces:**
- Consumes: `tests/__init__.py` from Task 1.
- Produces: `browser_soak.wait_for_report(proc, report, before, seconds, timeout, *, sleep=time.sleep, now=time.time) -> None`. `proc` needs `.poll()`; `report` is a `Path` or `None`; `before` is the line count at entry. The two keyword hooks exist so the test can drive a fake clock; production callers pass neither.

- [x] **Step 1: Write the failing test**

Create `tests/test_soak_wait.py`:

```python
"""Finding 3: waiting for the page must not spin at 100% CPU."""
import tempfile
import unittest
from pathlib import Path

import browser_soak as bs


class FakeProc:
    def __init__(self):
        self.exited = False

    def poll(self):
        return 1 if self.exited else None


class WaitLoop(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory(dir="temp")
        self.addCleanup(self._dir.cleanup)
        self.report = Path(self._dir.name) / "report.jsonl"
        self.report.write_text("one\n", encoding="utf-8")

    def _run(self, seconds, grow_after=None):
        clock = {"t": 0.0}
        naps = []

        def now():
            return clock["t"]

        def sleep(dt):
            naps.append(dt)
            clock["t"] += dt
            if grow_after is not None and len(naps) >= grow_after:
                self.report.write_text("one\ntwo\n", encoding="utf-8")

        bs.wait_for_report(FakeProc(), self.report, 1, seconds, 0,
                           sleep=sleep, now=now)
        return naps, clock["t"]

    def test_it_sleeps_between_polls(self):
        naps, _ = self._run(seconds=5)
        self.assertTrue(naps, "the wait loop never slept — it is spinning")
        self.assertTrue(all(dt > 0 for dt in naps))

    def test_iteration_count_is_bounded_by_the_sleep(self):
        naps, elapsed = self._run(seconds=5)
        self.assertLessEqual(len(naps), 5 / min(naps) + 2)
        self.assertGreaterEqual(elapsed, 5)

    def test_it_stops_as_soon_as_the_report_grows(self):
        naps, elapsed = self._run(seconds=600, grow_after=2)
        self.assertLessEqual(len(naps), 3)
        self.assertLess(elapsed, 600)

    def test_it_stops_when_chrome_exits(self):
        proc = FakeProc()
        proc.exited = True
        naps = []
        bs.wait_for_report(proc, self.report, 1, 600, 0,
                           sleep=lambda dt: naps.append(dt), now=lambda: 0.0)
        self.assertEqual(naps, [])

    def test_a_missing_report_does_not_spin(self):
        clock = {"t": 0.0}
        naps = []

        def sleep(dt):
            naps.append(dt)
            clock["t"] += dt

        bs.wait_for_report(FakeProc(), Path(self._dir.name) / "absent.jsonl", 0, 3, 0,
                           sleep=sleep, now=lambda: clock["t"])
        self.assertTrue(naps)
        self.assertLessEqual(len(naps), 3 / min(naps) + 2)


if __name__ == "__main__":
    unittest.main()
```

- [x] **Step 2: Run the test to verify it fails**

Run: `temp/venv/Scripts/python.exe -m unittest discover -s tests -t . -v`

Expected: all five ERROR with `AttributeError: module 'browser_soak' has no attribute 'wait_for_report'`.

- [x] **Step 3: Extract the loop and add the sleep**

In `scripts/browser_soak.py`, insert this function immediately before `def main()` (before line 72):

```python
def wait_for_report(proc, report, before, seconds, timeout, *, sleep=time.sleep, now=time.time) -> None:
    """等页面自报。**必须睡**：不睡就是满核自旋＋每轮重读整个 jsonl，
    而门正在同一台机器上判 33.4 ms 的帧预算——仪器自己把读数搅了。"""
    t0 = now()
    deadline = t0 + (timeout or seconds + 30)
    while now() - t0 < seconds:
        if proc.poll() is not None:
            return
        if report:
            try:
                if len(report.read_text(encoding="utf-8").splitlines()) > before:
                    return
            except OSError:
                pass
        if now() > deadline:
            return
        sleep(0.25)
```

Then in `main`, replace lines 109-120 (the `deadline = ...` line and the whole `while` loop) with:

```python
    wait_for_report(proc, report, before, args.seconds, args.timeout)
```

Keep `t0 = time.time()` at line 106 — the sampler thread and the `wall` calculation still use it. The behaviour is otherwise identical, including the existing `timeout` semantics (it can only shorten the wait, never extend it). Do not "fix" that here; it is finding 19, out of scope.

- [x] **Step 4: Run the test to verify it passes**

Run: `temp/venv/Scripts/python.exe -m unittest discover -s tests -t . -v`

Expected: `Ran 27 tests ... OK`.

- [x] **Step 5: Confirm the driver still works end to end**

Run:
```bash
temp/venv/Scripts/python.exe scripts/browser_soak.py --url about:blank --seconds 3 --tag audit-wait --report temp/playback-test/report-audit-wait.jsonl
```
Expected: it returns within roughly 3-33 s (Chrome exits on `about:blank`, or the wait elapses), writes `temp/playback-test/rss-audit-wait.txt`, and does not pin a core. If Chrome is not at the hardcoded path this will fail with `FileNotFoundError` — that is finding 19, out of scope; note it and rely on the unit tests.

- [x] **Step 6: Confirm no line-ending damage, then commit with consent**

Run: `git diff --ignore-cr-at-eol --stat`
Expected: `scripts/browser_soak.py` roughly -12/+18 lines, plus the new test file.

Show the diff, get consent, then:

```bash
git add tests/test_soak_wait.py scripts/browser_soak.py
git commit -m "fix: 等页面自报时睡 0.25 s，不再满核自旋重读整个 jsonl（审查 3）"
```

---

## Task 8: No criterion may disappear from the gate's denominator

**Finding 5.** `scripts/playback_check.py` appends nothing for a layer that is skipped or whose input is missing: L6-teeth (`:775`), L10 (`:710`), three L7 (`:829`), L9 and three L8 (`:794`, `:894`), L11 (`:937`), L3 (`:403`). The final line prints `len(checks) - len(failed)` of `len(checks)`, so the denominator silently shrinks and a run that tested almost nothing reports "all passed". Only the two frame-budget layers got a SKIP line (`:582`, `:658`). The missing-input case is live: the negative fixture lives in gitignored `temp/`. Two layer names are also inconsistent between their emit sites: L0 (`:302` "present" vs `:308` "in place") and L11 (`:962` full name vs `:970` short name).

**Files:**
- Create: `tests/test_layer_registry.py`
- Modify: `scripts/playback_check.py:302` (name), `:970` (name), plus a module-level registry and one call before the summary print at `:972`

**Interfaces:**
- Consumes: `tests/__init__.py` from Task 1.
- Produces: `playback_check.EXPECTED_LAYERS: tuple[str, ...]` (25 criteria names) and `playback_check.fill_missing_checks(checks: list[tuple[str, str, str]], expected=EXPECTED_LAYERS) -> list[tuple[str, str, str]]`, which appends a `SKIP` row for every expected name not already present and never duplicates an existing row.

- [x] **Step 1: Write the failing test**

Create `tests/test_layer_registry.py`:

```python
"""Finding 5: a skipped layer must still leave a line, so the denominator cannot shrink."""
import re
import unittest
from pathlib import Path

import playback_check as pc

ROOT = Path(__file__).resolve().parents[1]

# Rows that are reports, not criteria: INFO readings and fatal-error reports.
NON_CRITERIA = {
    "L1 track coverage",
    "mix headroom (no agreed basis, Q-8)",
    "session memory (600 s criterion is separate)",
    "gateway",
    "L4 criteria",
}


class LayerRegistry(unittest.TestCase):
    def test_empty_run_reports_every_layer_as_skip(self):
        got = pc.fill_missing_checks([])
        self.assertEqual(len(got), len(pc.EXPECTED_LAYERS))
        self.assertTrue(all(state == "SKIP" for _, state, _ in got))

    def test_present_rows_are_not_duplicated_or_overwritten(self):
        one = [("L2 pixel layer", "PASS", "kept")]
        got = pc.fill_missing_checks(one)
        rows = [r for r in got if r[0] == "L2 pixel layer"]
        self.assertEqual(rows, one)
        self.assertEqual(len(got), len(pc.EXPECTED_LAYERS))

    def test_fail_rows_survive(self):
        one = [("L6 guard has teeth", "FAIL", "fixture produced no black streaks")]
        got = pc.fill_missing_checks(one)
        self.assertIn(one[0], got)

    def test_the_layers_that_used_to_vanish_are_registered(self):
        for name in ("L6 guard has teeth",
                     "L10 browser pixels (vs channel 2 and vs export, same frame)",
                     "L11 flash in/out A/B (channel 2 vs export, same frame index)",
                     "L3 video band",
                     "L9 cross-channel curve parity (browser == channel 2)"):
            self.assertIn(name, pc.EXPECTED_LAYERS)

    def test_inconsistent_name_variants_are_gone(self):
        self.assertNotIn("L0 tracked player present", pc.EXPECTED_LAYERS)
        self.assertNotIn("L11 flash in/out A/B", pc.EXPECTED_LAYERS)

    def test_every_name_main_can_emit_is_registered_or_allowlisted(self):
        src = (ROOT / "scripts" / "playback_check.py").read_text(encoding="utf-8")
        emitted = set(re.findall(r'verdict\(\s*"([^"]+)"', src))
        emitted |= set(re.findall(r'checks\.append\(\(\s*"([^"]+)"', src))
        unknown = emitted - set(pc.EXPECTED_LAYERS) - NON_CRITERIA
        self.assertEqual(unknown, set(),
                         f"emit sites not covered by the registry: {sorted(unknown)}")


if __name__ == "__main__":
    unittest.main()
```

- [x] **Step 2: Run the test to verify it fails**

Run: `temp/venv/Scripts/python.exe -m unittest discover -s tests -t . -v`

Expected: all six ERROR with `AttributeError: module 'playback_check' has no attribute 'fill_missing_checks'`.

- [x] **Step 3: Add the registry and the reconciliation pass**

In `scripts/playback_check.py`, insert immediately after the `CRITERIA` dict (after line 72):

```python
# 每一条判据的规范名。跳过或输入缺失时也必须留一行，否则末尾的 "N of N"
# 会按缩小后的分母宣称全绿（审查 5）。新增判据必须同时登记在这里。
EXPECTED_LAYERS = (
    "L0 tracked player in place",
    "L1 errors/warnings",
    "L1 geometry channel",
    "L1 carrier freshness",
    "L2 pixel layer",
    "L3 video band",
    "L4 continuous playback",
    "L4 seek",
    "L4 first frame",
    "L4 Range streaming",
    "L4 frame budget (whole timeline, tail not mean)",
    "L4 live pacing + A/V residual (drive=timer, not real rAF)",
    "L6 no silent black frame",
    "L5 mixer",
    "L10 browser pixels (vs channel 2 and vs export, same frame)",
    "L6 guard has teeth",
    "L9 cross-channel curve parity (browser == channel 2)",
    "L7 mixmode shipped GLSL",
    "L7 mixmode wiring (constructed fixture)",
    "L7 mixmode browser wiring (fixture + negative fixture)",
    "L7 mixmode GPU three-way (vendor GLSL = oracle)",
    "L8 curves table rebuilt from the model",
    "L8 animation wiring (real draft, covered presets)",
    "L8 typewriter wiring (prefix law live on channel 2 + carrier)",
    "L11 flash in/out A/B (channel 2 vs export, same frame index)",
)


def fill_missing_checks(checks, expected=EXPECTED_LAYERS):
    """没留下行的判据补一条 SKIP：未测不等于通过，分母不许悄悄缩小。"""
    seen = {name for name, _, _ in checks}
    out = list(checks)
    for name in expected:
        if name not in seen:
            out.append((name, "SKIP",
                        "本跑没执行到这一层（旗标跳过或输入缺失）⇒ 未测，不是通过"))
    return out
```

- [x] **Step 4: Normalize the two inconsistent emit sites**

At line 302, replace:

```python
        verdict("L0 tracked player present", False, f"{src} missing")
```

with:

```python
        verdict("L0 tracked player in place", False, f"{src} missing")
```

At line 970, replace:

```python
            checks.append(("L11 flash in/out A/B", "SKIP", "no --oracle-mp4 given"))
```

with:

```python
            checks.append(("L11 flash in/out A/B (channel 2 vs export, same frame index)",
                           "SKIP", "no --oracle-mp4 given"))
```

- [x] **Step 5: Call the reconciliation before the summary**

At line 972, immediately before `width = max(len(name) for name, _, _ in checks) + 2`, insert:

```python
    checks = fill_missing_checks(checks)
```

- [x] **Step 6: Run the test to verify it passes**

Run: `temp/venv/Scripts/python.exe -m unittest discover -s tests -t . -v`

Expected: `Ran 33 tests ... OK`. If `test_every_name_main_can_emit_is_registered_or_allowlisted` fails, it has found an emit site this plan missed — add that exact name to `EXPECTED_LAYERS` (if it is a criterion) or to the test's `NON_CRITERIA` set (if it is an INFO/error report), and say which you did and why.

- [x] **Step 7: Prove the denominator no longer shrinks**

Run:
```bash
temp/venv/Scripts/python.exe -c "import sys; sys.path.insert(0,'scripts'); import playback_check as p; c=p.fill_missing_checks([('L2 pixel layer','PASS','x')]); print(len(c),'rows;',sum(1 for _,s,_ in c if s=='SKIP'),'SKIP'); print('criteria registered:',len(p.EXPECTED_LAYERS))"
```
Expected: `25 rows; 24 SKIP` and `criteria registered: 25`.

- [x] **Step 8: Confirm no line-ending damage, then commit with consent**

Run: `git diff --ignore-cr-at-eol --stat`
Expected: `scripts/playback_check.py` roughly +40 lines and two changed lines, plus the new test file.

Show the diff, get consent, then:

```bash
git add tests/test_layer_registry.py scripts/playback_check.py
git commit -m "fix: 跳过的判据也留 SKIP 行，分母不再悄悄缩小（审查 5）"
```

---

## Task 9: A slow paint must never overlap another paint

**Finding 4.** `player/player.html:2153` `tick()` has no in-flight guard. The rAF watchdog (`:2199`) calls `tick(now())` every 33 ms once no real animation frame has arrived for 250 ms, and only `rafTick` refreshes `lastRafAt`. In headless Chrome — where the file itself documents that zero rAF frames arrive — any paint over 250 ms makes the watchdog re-enter while the first `await paint()` is still running. Concurrent paints clear shared per-frame sets mid-flight, hiding layers and inventing black streaks. `&drive=timer` (`:2562`), which the gate's L4 live pacing uses, is a **second** independent interval calling the same `tick`, so the guard must live in `tick` itself, not in the watchdog.

**Files:**
- Create: `tests/player_tick_guard.test.mjs`
- Modify: `player/player.html:2151` (add the flag), `:2153-2186` (wrap the body in try/finally)

**Interfaces:**
- Consumes: nothing from earlier tasks (this is the only JS task).
- Produces: `tick` is re-entrant-safe. The test extracts the real source between two stable anchors, so it tests the shipped code, not a copy.

- [x] **Step 1: Write the failing test**

Create `tests/player_tick_guard.test.mjs`:

```js
// Finding 4: a slow paint must never overlap another paint.
// Runs the REAL tick + watchdog source from player.html in a sandbox with a
// fake clock, so the regression is caught without launching Chrome.
import { readFileSync } from "node:fs";
import vm from "node:vm";
import assert from "node:assert/strict";
import { test } from "node:test";

const HTML = readFileSync(new URL("../player/player.html", import.meta.url), "utf8");

function slice(from, to) {
  const a = HTML.indexOf(from);
  assert.ok(a >= 0, `anchor not found: ${from}`);
  const b = HTML.indexOf(to, a);
  assert.ok(b > a, `end anchor not found after ${from}: ${to}`);
  return HTML.slice(a, b);
}

// State declarations + tick, then the watchdog. Both regions are contiguous
// in the file and bounded by comments/declarations that this plan does not move.
const SRC = slice("let actxT0 = 0;", "// ---- rAF")
  + "\n" + slice("let lastRafAt = 0", "function toggle(on) {");

function harness() {
  const clock = { t: 0 };
  const calls = { paint: 0, inFlight: 0, maxInFlight: 0 };
  const pending = [];
  let intervalCb = null;

  const ctx = {
    AVCLK_ON: false, actx: null, DUR: 100,
    stat: { requests: 0, bytes: 0 },
    pool: { map: new Map() },
    intervals: [], tickErrors: [],
    now: () => clock.t,
    performance: { memory: null, now: () => clock.t },
    requestAnimationFrame: () => 0,
    setInterval: (cb) => { intervalCb = cb; return 1; },
    clearInterval: () => { intervalCb = null; },
    setTimeout, clearTimeout,
    scheduleAudio: () => {},
    toggle: () => {},
    hud: () => {},
    document: { getElementById: () => ({ style: {} }) },
    console,
    paint: () => {
      calls.paint++;
      calls.inFlight++;
      calls.maxInFlight = Math.max(calls.maxInFlight, calls.inFlight);
      return new Promise((res) => pending.push(() => { calls.inFlight--; res(); }));
    },
  };
  vm.createContext(ctx);
  vm.runInContext(SRC + `
    globalThis.__h = {
      tick, tickPumpStart, rafTick,
      setPlaying: (v) => { playing = v; },
    };`, ctx);
  return {
    ctx, clock, calls,
    fire: () => { if (intervalCb) intervalCb(); },
    drain: () => { while (pending.length) pending.shift()(); },
  };
}

// A macrotask turn guarantees every microtask (including tick's continuation
// and its `finally`) has run. A single `await Promise.resolve()` is not enough.
const flush = () => new Promise((r) => setTimeout(r, 0));

test("a slow paint never overlaps another paint", async () => {
  const h = harness();
  h.ctx.__h.setPlaying(true);
  h.ctx.__h.tickPumpStart();

  // Headless: rAF never arrives, so lastRafAt goes stale and the watchdog
  // fires every 33 ms while the first paint is still in flight.
  for (const t of [400, 800, 1200, 1600]) {
    h.clock.t = t;
    h.fire();
    await flush();
  }

  assert.equal(h.calls.maxInFlight, 1,
    `overlapping paints: maxInFlight=${h.calls.maxInFlight} (paint called ${h.calls.paint} times)`);
  h.drain();
  await flush();
});

test("the watchdog still drives frames when paint is fast", async () => {
  const h = harness();
  h.ctx.__h.setPlaying(true);
  h.ctx.__h.tickPumpStart();
  for (const t of [400, 800, 1200]) {
    h.clock.t = t;
    h.fire();
    h.drain();
    await flush();
  }
  assert.ok(h.calls.paint >= 3, `watchdog stopped driving: ${h.calls.paint} paints`);
});
```

- [x] **Step 2: Run the test to verify it fails**

Run: `node --test tests/`

Expected: `a slow paint never overlaps another paint` FAILS with `overlapping paints: maxInFlight=4`. The second test passes.

- [x] **Step 3: Add the guard**

In `player/player.html`, line 2151, add `ticking` to the existing declaration list. Replace:

```js
let pos = 0, playing = false, measuring = false, lastWall = 0, frames = 0, winStart = 0, intervals = [], lastAt = 0, framesDecoded = 0, lastFiles = [];
```

with:

```js
let pos = 0, playing = false, measuring = false, lastWall = 0, frames = 0, winStart = 0, intervals = [], lastAt = 0, framesDecoded = 0, lastFiles = [];
let ticking = false;   // tick 不许重入：看门狗与 &drive=timer 都会在 paint 还没返回时再敲一次
```

Then replace the whole `tick` function (lines 2153-2186) with:

```js
async function tick(t) {
  if (ticking) return;
  ticking = true;
  try {
    if (measuring) { requestAnimationFrame(rafTick); return; }
    let gapMs = -1, gapPos = 0;
    if (playing) {
      scheduleAudio(pos);
      // 播放头跟随**音频时钟**，不再跟墙钟。这个文件的第 150 行早就写着
      // "AudioContext is the clock authority"，但 tick() 一直用 performance.now() 推进——
      // 于是每次 `await paint()` 超预算（实测整条时间轴累计 942 ms、21 帧过线），
      // 画面冻住而音频照播 ⇒ 音频一路领先画面，听起来就是"轨道没混合、有的该响没响"。
      // 视频跟音频是播放器的标准做法：超预算时宁可少画一帧，也不让两条时钟分叉。
      const clk = (AVCLK_ON && actx) ? (actx.currentTime - actxT0) * 1000 : t;
      if (lastWall) {
        const dt = (clk - lastWall) / 1000;
        pos = Math.min(DUR, pos + Math.max(0, dt));
        if (pos >= DUR) toggle(false);
      }
      lastWall = clk;
      if (!winStart) winStart = t;
      if (lastAt) { gapMs = Math.round(t - lastAt); gapPos = +pos.toFixed(2); }
      lastAt = t; frames++;
    }
    const paintT0 = now();
    try { await paint(pos * 1e6); }
    catch (e) { tickErrors.push(String(e && e.message || e).slice(0, 120)); }
    // 当帧 paint 耗时和帧间隔一起记：gap≈paint 是我们画得慢，gap≫paint 是浏览器没给帧。
    if (gapMs >= 0) intervals.push([gapMs, gapPos, Math.round(now() - paintT0)]);
    hud('pos', `${pos.toFixed(2)} / ${DUR.toFixed(2)} s`);
    hud('stat', `req ${stat.requests} / bytes ${(stat.bytes / 1e6).toFixed(1)} MB`);
    hud('heap', performance.memory ? `heap ${(performance.memory.usedJSHeapSize / 1048576).toFixed(0)} MB` : 'heap -');
    const el = (t - winStart) / 1000;
    if (playing && el > 0.5) hud('fps', `fps ${(frames / el).toFixed(2)} 池 ${pool.map.size}`);
    document.getElementById('play').style.left = `${(pos / DUR) * 100}%`;
    requestAnimationFrame(rafTick);
  } finally { ticking = false; }
}
```

The body is unchanged apart from indentation; every comment is preserved verbatim. `try/finally` is required, not optional: if anything outside the inner `try` throws (for example `scheduleAudio`), a bare flag reset would leave `ticking` stuck true and freeze playback permanently.

The sandbox must stub `pool` (as `{ map: new Map() }`): the `hud('fps', ...)` line reads `pool.map.size`, and it is reached once more than 0.5 s of fake time has elapsed since `winStart` — which the second test does. This was confirmed by running the test against the unfixed page.

- [x] **Step 4: Run the test to verify it passes**

Run: `node --test tests/`

Expected: both tests pass, `maxInFlight=1`.

- [x] **Step 5: Run the whole suite**

Run: `temp/venv/Scripts/python.exe -m unittest discover -s tests -t . -v`
Expected: `Ran 33 tests ... OK`.

Run: `node --test tests/`
Expected: 2 pass, 0 fail.

- [ ] **Step 6: CHECKPOINT — the runtime copy must be re-materialized**

The gateway serves `temp/playback-test/player.html`, not the tracked file. `playback_check.py:299-309` (L0) and `frame_parity.sync_player()` both copy the tracked file over the runtime copy and assert byte equality. Until that happens, any browser reading is of the **old** page.

Run:
```bash
temp/venv/Scripts/python.exe -c "from pathlib import Path; import shutil; src=Path('player/player.html'); dst=Path('temp/playback-test/player.html'); dst.write_bytes(src.read_bytes()); print('synced', dst, dst.stat().st_size, 'bytes; identical:', dst.read_bytes()==src.read_bytes())"
```
Expected: `identical: True`.

A full browser re-verification (L4 live pacing, L6, L10) is **not** part of this task and must not be claimed. Report that the guard is unit-tested against the real source, and that the browser layers need a fresh gate run to confirm.

- [x] **Step 7: Confirm no line-ending damage, then commit with consent**

Run: `git diff --ignore-cr-at-eol --stat`
Expected: `player/player.html` roughly +40/-34 lines (the re-indentation), plus the new test file. **This is the task most likely to mangle CRLF** — if the diff shows all 2605 lines changed, stop and fix the line endings before committing.

Show the diff, get consent, then:

```bash
git add tests/player_tick_guard.test.mjs player/player.html
git commit -m "fix: tick 加重入闸，慢 paint 不再与看门狗/drive=timer 并发（审查 4）"
```

---

## Final Verification

- [x] **Run both suites from the repo root**

```bash
temp/venv/Scripts/python.exe -m unittest discover -s tests -t . -v
node --test tests/
```
Expected: 33 Python tests OK, 2 JS tests pass.

- [x] **Confirm the tracked diff is only what this plan intended**

```bash
git diff --ignore-cr-at-eol --stat HEAD~9
git status --short
```
Expected: fourteen modified source files plus ten new files under `tests/`. No changes to `evidence/`, `spec/`, `requirements.txt`, or `plan-m2-playback-tail.md`. No stray files in the repo root. `temp/` stays untracked.

- [x] **Report the two open checkpoints honestly**

1. **Task 6 Step 6** — the pixel re-baseline could not run (0 oracle frames, 0 browser shots in `temp/`). The ruler is now shared and unit-tested; the `0.90` / `0.96–1.04` lines have **not** been re-registered against it.
2. **Task 9 Step 6** — the tick guard is unit-tested against the real source; the browser layers (L4 live pacing, L6, L10) have **not** been re-run.

Neither is a pass. State both as open, and state that Task 2 Step 5 may have surfaced a genuine previously-hidden animation defect.

---

## Validation Already Performed

Before this plan was handed off, the two highest-risk harnesses were extracted **verbatim from the code blocks above** and run against the unfixed source in a scratch sandbox at `temp/plan-validate/` (gitignored). No repo source was modified.

| Check | Result |
|---|---|
| Task 1 test vs unfixed `playback_model.py` | 2 ERROR `TypeError: cannot unpack non-iterable NoneType object` at line 215, 1 pass — exactly as Step 3 predicts |
| Task 1 post-fix behaviour (simulated via the corrected resolution) | dangling and absent both return and record `dangling material_id …`; resolved material still yields `bucket=videos, type=video, errors=[]` — all three assertions would pass |
| Task 9 test vs unfixed `player.html` | FAIL `overlapping paints: maxInFlight=4 (paint called 4 times)` — exactly as Step 2 predicts; second test passes |
| Task 9 test vs the plan's fix spliced into a scratch copy | **2 pass, 0 fail, node exit 0** |
| CRLF preservation on that splice | 2609 CRLF, 0 bare LF — the re-indentation did not mangle line endings |
| `unittest discover -s tests -t .` package bootstrap | works; `tests/__init__.py` alone puts both script dirs on `sys.path` |
| Import safety of all 14 modules the tests touch | all import cleanly |
| Line endings of all 14 target files | all CRLF |

One plan defect was found and fixed by this validation: the Task 9 sandbox originally omitted a `pool` stub, on the incorrect assumption that the `hud('fps', …)` branch is never reached. The second test does reach it. `pool: { map: new Map() }` is now in the sandbox unconditionally.

The scratch sandbox is left in place for the executor to reuse or delete; it is inside gitignored `temp/` and is not part of the deliverable.

---

## Out of Scope (deliberately deferred)

Findings 10–20 from the audit are **not** in this plan: the wrong `med()` (three copies), the oracle frame cache key, shrinking battery `n`, the false `loaded` flag, dead `audioGen`, composite-blind stats, the missing render fence, the fitted `--video-scan` pass, the 6–11× helper duplication, the hardcoded Chrome path, the dead `--timeout`, and the small dead-code sweep. Finding 18 (duplication) spans ~30 scripts and needs its own plan with a regression baseline.