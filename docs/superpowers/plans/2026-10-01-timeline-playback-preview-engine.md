# Timeline Playback Preview Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace window-sampled browser/GES playback with a frame-quantized `TimelineModel` compiled once into an MLT graph and controlled by one authoritative project-frame clock.

**Architecture:** `DraftAdapter` converts `TimelineContent` into immutable Python values; `evaluate(model, t_us)` is the pure oracle for frame quantization, activity, source mapping, and z order. `MltCompiler` consumes only that model, while `PlaybackController` owns the compiled graph, serialized MLT access, exact seek generations, mixed audio, and video frames exposed through the existing backend HTTP surface.

**Tech Stack:** Python 3.14, stdlib dataclasses/Fraction/queue/concurrent.futures, aiohttp, Pillow, MLT 7 Python bindings (`mlt7`), existing vanilla JavaScript UI and Node assertion scripts

**Spec:** `docs/superpowers/specs/2026-10-01-timeline-playback-preview-engine-design.md`

## Global Constraints

- Run the MLT availability gate on the target Windows/Python 3.14 runtime before implementing Tasks 2-7; on failure, record evidence and stop this plan.
- Keep decrypted/plain draft content, `Timelines/`, and draft metadata read-only; write only existing `.jypreview`, user-cache, `temp/`, and documentation locations.
- Use integer microseconds and half-open ranges `[start_us, end_us)` throughout the model/API; convert to MLT frame positions only inside `MltCompiler` and `PlaybackController`.
- Represent project frame rate as exact `{num, den}` values; default missing FPS to `30/1` with a warning, and normalize common NTSC values such as `29.97` to `30000/1001`.
- Quantize with `frame = floor(t_us * num / (1_000_000 * den))` and `sample_us = floor(frame * 1_000_000 * den / num)`; never accumulate floating-point frame durations.
- Keep `FrameDescriptor` as a structural/time oracle only; it must not feed backend scheduling or the compiled MLT graph.
- Support only positive rational clip rates 0.5x, 1x, and 2x plus an independent forward/reverse direction in the first implementation; approximate readable curves by their average and warn, otherwise render a placeholder.
- Keep preview transport at 1x; clip source speed is independent of global transport speed.
- Serialize all MLT calls through the existing one-worker pattern; MLT objects never enter HTTP payloads or browser state.
- Do not add MLT to `scripts/requirements.txt`; it is an isolated native runtime whose interpreter/plugin provenance is recorded by Task 1.
- Launch the preview server and every MLT-dependent check with the gate-approved `JY_PREVIEW_MLT_PYTHON`; do not mix its native DLL/plugin paths with the default interpreter.
- Do not implement draft write-back, final export, a general edit-command layer, or private Jianying effect recreation.

## Review Focus

- A duration or clip boundary between project frames must select the first sample not earlier than the boundary, and `t_us >= duration_us` must return `ended` without pulling a frame (Task 2 tests).
- Invalid/negative ranges, empty media references, unavailable source handles, and undecodable clips must preserve interval and z order as warnings/placeholders instead of disappearing (Tasks 2-3 tests).
- Disabled tracks, invisible clips, muted tracks, clip gains greater than 1, same-track overlaps, and equal-z ties must produce deterministic visibility/audio/order (Tasks 2-3 tests).
- Repeated child IDs in different compound clips and recursion beyond `config.max_nest_depth` must not collide or recurse indefinitely (Task 2 tests).
- Rapid out-of-order seeks, late frames from an old generation, consumer/plugin failures, EOS, and dropped video frames must not move the audio-derived clock backward (Tasks 4 and 6 tests).

---

## File Structure

- Create `scripts/jypreview/model/timeline.py`: immutable timeline values, rational frame math, and pure `evaluate()`.
- Create `scripts/jypreview/model/draft_adapter.py`: the only reader of raw Jianying JSON; reuse existing media, layout, paint, font, and label helpers.
- Create `scripts/jypreview/mlt_backend.py`: MLT availability probe helpers, graph compiler, rendered frame value, and playback controller.
- Modify `scripts/jypreview/session.py`: cache `TimelineModel` per draft/timeline and expose it to the backend without changing `frame()`.
- Modify `scripts/jypreview/server/handlers_backend.py`: keep the current route contract while replacing GES/window-IR inputs with the model/controller.
- Modify `scripts/jypreview/server/app.py`: manage MLT playback handles and close them during server shutdown.
- Modify `scripts/jypreview/web/backend.js`: replace the browser-controller adapter with the MLT HTTP/multipart client.
- Modify `scripts/jypreview/web/app.js`: make backend snapshot/frame output the only playback clock/output; retain point `FrameDescriptor` requests for diagnostics and property panels.
- Delete the obsolete GES adapter and browser window-playback modules only after Task 6 passes.
- Add one small executable assertion script per reviewable backend layer; use the repository's existing `python -m ...` and Node test style, not a new framework.

### Task 1: Pass or stop at the MLT runtime gate

**Files:**
- Create: `scripts/jypreview/tools/test_mlt_runtime.py`
- Create: `docs/native-backend-evaluation/2026-10-01-mlt-gate.md`
- Write runtime evidence only: `temp/mlt-runtime-gate.json`

**Interfaces:**
- Consumes: `JY_PREVIEW_TEST_VIDEO`, `JY_PREVIEW_TEST_AUDIO`, and the absolute Python executable in `JY_PREVIEW_MLT_PYTHON`.
- Produces: CLI `python -m jypreview.tools.test_mlt_runtime --video PATH --audio PATH --json temp/mlt-runtime-gate.json`; exit 0 means Tasks 2-7 may run, any nonzero exit stops this plan.
- Produces JSON keys: `python`, `mlt_version`, `repository`, `plugins`, `decoded_media`, `frame_positions`, `audio_sink`, `three_layer_rgba`, `timewarp`, `max_av_delta_frames`, and `ok`.

- [ ] **Step 1: Confirm the current default interpreter does not accidentally satisfy the gate**

Run: `py -3.14 -c "import mlt7"`

Expected on the environment described by the spec: FAIL with `ModuleNotFoundError: No module named 'mlt7'`. If it already succeeds, record that fact and still run the complete gate.

- [ ] **Step 2: Write the runtime gate script**

Use the official binding entry sequence `import mlt7 as mlt; mlt.Factory().init(None); profile = mlt.Profile()`. Assert that the chosen repository can create the exact services needed by this design: file decode (`avformat`/loader), `timewarp`, a verified affine blend (`frei0r.cairoaffineblend`), `pango`, one audio output (`sdl2_audio` or `rtaudio`), and a frame-pulling consumer. The script must exercise representative video/audio decode, three simultaneous layers, 0.5x/2x/reverse timewarp, random seek positions `(0, 15, 3, 30)` in project-frame order, RGBA output, mixed audio, and A/V timestamps within one project frame.

Reference: [MLT Python bindings](https://www.mltframework.org/doxygen/group__python__bindings.html), [timewarp producer](https://www.mltframework.org/plugins/ProducerTimewarp/), [cairoaffineblend](https://www.mltframework.org/plugins/TransitionFrei0r-cairoaffineblend/).

- [ ] **Step 3: Prepare one isolated Windows/Python 3.14 MLT runtime under `temp/mlt-runtime/`**

Keep native DLLs, `mlt7`, and plugin data together outside the application dependency set. Record the build/package source, exact Python path, MLT version, and repository path; do not edit `scripts/requirements.txt` or global Python.

- [ ] **Step 4: Run the gate**

Run:

```powershell
$env:PYTHONPATH='scripts'
& $env:JY_PREVIEW_MLT_PYTHON -m jypreview.tools.test_mlt_runtime `
  --video $env:JY_PREVIEW_TEST_VIDEO `
  --audio $env:JY_PREVIEW_TEST_AUDIO `
  --json temp/mlt-runtime-gate.json
```

Expected: PASS, JSON has `"ok": true`, all required plugin names, nonempty RGBA/audio output, exact requested project-frame positions, and `max_av_delta_frames <= 1`.

If it fails: write the failure and missing capability to the gate report, commit only the probe/report, and stop. Create a separate libopenshot comparison spec/plan; do not continue with a partial MLT replacement.

- [ ] **Step 5: Record the gate result**

Write `docs/native-backend-evaluation/2026-10-01-mlt-gate.md` with runtime provenance, command, media classes tested, plugin list, pass/fail result, and the path to the ignored JSON evidence. Do not copy private absolute media paths into the document.

- [ ] **Step 6: Commit the probe and documentation separately**

```powershell
git add scripts/jypreview/tools/test_mlt_runtime.py
git commit -m "test: add MLT runtime gate"
git -C docs add native-backend-evaluation/2026-10-01-mlt-gate.md
git -C docs commit -m "docs: record MLT runtime gate"
```

### Task 2: Build the immutable model, adapter, and pure evaluator

**Files:**
- Create: `scripts/jypreview/model/timeline.py`
- Create: `scripts/jypreview/model/draft_adapter.py`
- Create: `scripts/jypreview/tools/test_timeline_model.py`
- Modify: `scripts/jypreview/session.py:36-147,150-235`

**Interfaces:**
- Consumes: `TimelineContent`, draft root, `Config`, `FileRegistry`, font/catalog/media helpers, and `config.max_nest_depth`.
- Produces in `timeline.py`: frozen values `FrameRate`, `TimeRange`, `TimeMapping`, `MediaRef`, `AudioSpec`, `Transform`, `TextPayload`, `EffectSpec`, `Clip`, `Track`, `Transition`, `TimelineModel`, `SceneItem`, and `ExpectedScene`.
- Produces: `FrameRate.quantize(t_us: int) -> tuple[int, int]` returning `(frame_index, sample_us)`.
- Produces: `TimeMapping.source_us(local_us: int, source: TimeRange) -> int | None`.
- Produces: `evaluate(model: TimelineModel, t_us: int) -> ExpectedScene`; `ExpectedScene.state` is `"active"` or `"ended"` and separates ordered `video` and `audio` tuples.
- Produces in `draft_adapter.py`: `DraftAdapter(config, registry, font_index, catalog, probe_cache).build(content: TimelineContent, *, draft_root: Path, did: str, timeline_info: dict[str, Any]) -> TimelineModel`.
- Produces in `session.py`: `DraftView.timeline_model(tid: str) -> TimelineModel`, cached beside `_contents`; existing `DraftView.frame()` stays unchanged as the oracle.

- [ ] **Step 1: Write failing rational-time and interval tests**

Add assertions equivalent to:

```python
rate = FrameRate(30_000, 1_001)
assert rate.quantize(1_000_000) == (29, 967_633)
assert evaluate(model, model.duration_us).state == "ended"
assert evaluate(model, model.duration_us).video == ()
assert forward.source_us(250_000, TimeRange(2_000_000, 1_000_000)) == 2_500_000
assert reverse.source_us(250_000, TimeRange(2_000_000, 1_000_000)) == 2_499_999
```

Also cover negative/zero ranges, a boundary between frame samples, adjacent seams, a same-track overlap, equal-z stable ordering, 0.5x/1x/2x, source clamping warnings, `visible:false`, disabled/muted tracks, and volume `1.5`.

- [ ] **Step 2: Run the model test to verify it fails**

Run: `$env:PYTHONPATH='scripts'; py -3.14 -m jypreview.tools.test_timeline_model`

Expected: FAIL with missing `jypreview.model.timeline`.

- [ ] **Step 3: Implement the frozen values and `evaluate()`**

Use `fractions.Fraction` only during normalization; store integer numerators/denominators. `evaluate()` must quantize first, reject the timeline end before selecting clips, compute each source time from absolute `sample_us`, include transition handles without mutating logical ranges, and sort by `(render_index, original_track_index, original_segment_index)`.

- [ ] **Step 4: Extend the test with adapter and malformed-input coverage**

Build small in-memory `TimelineContent` fixtures and assert exact normalized fields for media, audio, text, transform/crop/opacity/blend, fade/crossfade, missing material, unreadable speed curve, and nested clips. Assert child IDs are parent-path-qualified and recursion at `max_nest_depth + 1` becomes a placeholder warning.

- [ ] **Step 5: Implement `DraftAdapter` and the session cache**

Reuse `media.resolve()`/`media.probe()`, `layout.layer_geometry()`, `paint.build()`, font resolution, and label catalog helpers rather than copying their rules. Raw dictionaries stop at the adapter boundary. Invalid clips become traceable placeholders with stable error IDs; curve approximations carry `speed_curve_approximated`; unknown effects/animations retain interval and z without an opaque overlay.

- [ ] **Step 6: Add FrameDescriptor parity assertions**

For fixture sample times, call existing `DraftView.frame(tid, sample_us)` and compare active clip IDs, track IDs, source times, and z order to `evaluate(DraftView.timeline_model(tid), sample_us)`. Do not compare at the unquantized request time.

- [ ] **Step 7: Run the test and commit**

Run: `$env:PYTHONPATH='scripts'; py -3.14 -m jypreview.tools.test_timeline_model`

Expected: PASS with `ok: timeline model, adapter, and evaluator regressions`.

```powershell
git add scripts/jypreview/model/timeline.py scripts/jypreview/model/draft_adapter.py `
  scripts/jypreview/session.py scripts/jypreview/tools/test_timeline_model.py
git commit -m "feat: add deterministic timeline model"
```

### Task 3: Compile the model into one MLT audio/video graph

**Files:**
- Create: `scripts/jypreview/mlt_backend.py`
- Create: `scripts/jypreview/tools/test_mlt_compiler.py`

**Interfaces:**
- Consumes: `TimelineModel`; no `TimelineContent`, raw JSON, `FrameDescriptor`, or HTTP values.
- Produces: `BackendUnavailable(RuntimeError)` and frozen `RenderedFrame(frame_index: int, pts_us: int, width: int, height: int, rgba: bytes)`.
- Produces: `CompiledTimeline(model: TimelineModel, profile: object, tractor: object, duration_frames: int, warnings: tuple[str, ...])` with `close() -> None`; MLT objects remain private to this module.
- Produces: `MltCompiler().available() -> tuple[bool, str]` and `MltCompiler().compile(model: TimelineModel) -> CompiledTimeline`.

- [ ] **Step 1: Write the failing compiler integration test**

Construct a model with background plus three simultaneous visual clips, one same-track overlap, a still, text, a missing clip placeholder, two audio tracks, track mute, clip gain `1.5`, forward/0.5x/2x/reverse mappings, fade, crossfade with sufficient handles, and crossfade with a missing handle. Assert:

```python
compiled = MltCompiler().compile(model)
assert compiled.duration_frames == model.frame_rate.quantize(model.duration_us - 1)[0] + 1
assert compiled.tractor is not None
assert "transition_handle_clamped" in compiled.warnings
```

Pull frames at the overlap and transition positions from the compiled tractor and assert RGBA dimensions/position; pull mixed PCM and assert muted audio is absent while gain `1.5` is not clamped to `1.0`.

- [ ] **Step 2: Run the compiler test to verify it fails**

Run: `$env:PYTHONPATH='scripts'; & $env:JY_PREVIEW_MLT_PYTHON -m jypreview.tools.test_mlt_compiler`

Expected: FAIL with missing `jypreview.mlt_backend`.

- [ ] **Step 3: Implement `MltCompiler.compile()`**

Create one project `Profile`, background producer, per-track playlists, extra lanes only for real same-track overlaps, and a final `Tractor`. Convert target/source ranges to project/source frames only here; wrap changed-speed/reverse media with signed `timewarp`; use the gate-verified affine blend for position/scale/rotation/anchor/crop/flip/opacity/blend; reverse MLT priority at this boundary only.

- [ ] **Step 4: Add still, text, audio, transition, nesting, and placeholder compilation**

Use one static image producer for a still's whole range, Pango for normalized text content/basic style, nested tractors for compound clips, MLT mixing for source and independent audio, linear gain for clip volume, and fade/crossfade only. Missing/undecodable media gets a visible interval-preserving placeholder; unsupported effects remain warnings or transparent diagnostics.

- [ ] **Step 5: Run the compiler test and commit**

Run: `$env:PYTHONPATH='scripts'; & $env:JY_PREVIEW_MLT_PYTHON -m jypreview.tools.test_mlt_compiler`

Expected: PASS with `ok: MLT graph composition regressions`.

```powershell
git add scripts/jypreview/mlt_backend.py scripts/jypreview/tools/test_mlt_compiler.py
git commit -m "feat: compile timeline model to MLT"
```

### Task 4: Add authoritative playback control and wire the existing backend API

**Files:**
- Modify: `scripts/jypreview/mlt_backend.py`
- Create: `scripts/jypreview/tools/test_mlt_controller.py`
- Modify: `scripts/jypreview/server/handlers_backend.py:1-192`
- Modify: `scripts/jypreview/server/app.py:47-58,90-98,181-191`

**Interfaces:**
- Consumes: `TimelineModel`, `MltCompiler`, one verified MLT audio sink, and existing draft/timeline selectors.
- Produces: `PlaybackController.open(model: TimelineModel) -> dict[str, Any]`, `play() -> dict[str, Any]`, `pause() -> dict[str, Any]`, `seek(t_us: int) -> dict[str, Any]`, `snapshot() -> dict[str, Any]`, `pull_frame(timeout_ms: int = 100) -> RenderedFrame | None`, and `close() -> None`.
- Produces snapshot keys: `backend`, `phase`, `generation`, `frame_index`, `t_us`, `duration_us`, `playing`, `error`, and `open`; `t_us` is always the selected project frame's `sample_us` derived from the MLT/audio clock.
- Preserves HTTP routes: `/api/backend/capabilities`, `open`, `render`, `play`, `pause`, `seek`, `stream`, `snapshot`, and `close`; response backend name becomes `mlt`.

- [ ] **Step 1: Write failing state, generation, and clock tests**

Test `idle -> ready -> playing -> paused/seeking/buffering/ended/error`, seek quantization, seek-at-end without a frame pull, resume-after-seek, close/timeline-switch cleanup, and a consumer failure. Delay two render results and assert the older generation cannot overwrite the newer frame. Feed frame positions with a dropped video frame and assert snapshot time follows monotonic audio/project positions and never regresses.

- [ ] **Step 2: Run the controller test to verify it fails**

Run: `$env:PYTHONPATH='scripts'; & $env:JY_PREVIEW_MLT_PYTHON -m jypreview.tools.test_mlt_controller`

Expected: FAIL because `PlaybackController` is absent.

- [ ] **Step 3: Implement `PlaybackController` in `mlt_backend.py`**

Compile once in `open()`, keep one consumer per timeline, make local MLT audio the master clock, derive frame/sample time through `FrameRate`, drop stale generation results, and release consumer/tractor resources on EOS, close, error, and timeline switch. Do not expose a global transport rate other than 1x.

- [ ] **Step 4: Replace GES/window-IR construction in `handlers_backend.py`**

Rename `NativeHandle` to `PlaybackHandle`, retain its one-thread executor, and instantiate `PlaybackController`. `open_backend()` must call `view.timeline_model(tid)` directly; delete the full-duration `view.frame(...window=...)` call and `clips_from_frame_ir()`. Return quantized frame/PTS headers from render/stream and readable error payloads for initialization, plugin, consumer, and decode failures.

- [ ] **Step 5: Update app ownership and endpoint tests**

Keep `app["native_backends"]` only if renaming it would touch unrelated code; otherwise rename it once to `playback_backends`. Ensure application shutdown closes every handle. Exercise open/render/play/pause/seek/snapshot/stream/close against the representative timeline and assert end seek returns `ended` without a PNG.

- [ ] **Step 6: Run tests and commit**

Run:

```powershell
$env:PYTHONPATH='scripts'
& $env:JY_PREVIEW_MLT_PYTHON -m jypreview.tools.test_mlt_controller
node scripts/jypreview/tools/test_playback_kernel.mjs
```

Expected: both PASS; the existing browser kernel still passes because cutover is Task 5.

```powershell
git add scripts/jypreview/mlt_backend.py scripts/jypreview/tools/test_mlt_controller.py `
  scripts/jypreview/server/handlers_backend.py scripts/jypreview/server/app.py
git commit -m "feat: control MLT playback through backend API"
```

### Task 5: Make MLT output the only UI playback path

**Files:**
- Modify: `scripts/jypreview/web/backend.js:1-27`
- Modify: `scripts/jypreview/web/app.js:1-172,330-510,667-740,928-986`
- Modify: `scripts/jypreview/tools/test_playback_kernel.mjs:1-169`
- Modify: `scripts/jypreview/tools/test_playback_state.py:15-106`

**Interfaces:**
- Consumes: unchanged backend HTTP routes and snapshots from Task 4.
- Produces in `backend.js`: `MltPlaybackClient.open(draft, timeline)`, `play()`, `pause()`, `seek(tUs)`, `snapshot()`, `startStream(onFrame)`, and `close()`; each multipart frame passed to `onFrame` contains `{blob, frameIndex, ptsUs, generation}`.
- Produces: UI play/pause/seek state derived only from backend snapshots; point `/api/frame` remains diagnostic and never advances playback.
- Produces: `window.__state()` and `window.__snapshot()` with `backend: "mlt"`, quantized `frameIndex`, `tUs`, state, warning/error, and displayed video-frame PTS.

- [ ] **Step 1: Rewrite the JavaScript client and browser acceptance tests first**

In `test_playback_kernel.mjs`, feed a synthetic multipart stream with `X-Project-Frame`, `X-Project-PTS-US`, and generation headers; assert parsing preserves them, an old generation is dropped, and `close()` aborts the reader. In `test_playback_state.py`, open the normal URL without `?backend=browser`; assert backend is `mlt`, exact seek reports the requested quantized frame/PTS, rapid 10s/20s/30s seeks settle on the last generation, play timestamps are monotonic, pause freezes the frame, end seek becomes `ended`, and backend failure does not activate DOM media playback.

- [ ] **Step 2: Run it to verify the old path fails the new contract**

Run:

```powershell
node scripts/jypreview/tools/test_playback_kernel.mjs
$env:PYTHONPATH='scripts'; & $env:JY_PREVIEW_MLT_PYTHON -m jypreview.tools.test_playback_state
```

Expected: FAIL because `MltPlaybackClient` is absent and state still reports `gstreamer-ges`/browser-clock fields.

- [ ] **Step 3: Replace `BrowserPlaybackBackend` with `MltPlaybackClient`**

Reuse `backend.js` as the transport seam. Call the existing endpoints, parse `multipart/x-mixed-replace` incrementally with `ReadableStream`, keep at most two decoded frames, expose part PTS/project-frame headers, and abort/clear the stream on seek, timeline switch, error, or close. Add no transport dependency.

- [ ] **Step 4: Remove browser clock/window scheduling from `app.js`**

Remove `PlaybackController`, `BrowserPlaybackBackend`, `FrameStore`, `AudioScheduler`, `WINDOW_US`, `PREFETCH_US`, `loadWindowAt()`, `prefetchWindow()`, `advanceTimeline()`, and browser media synchronization. Keep the current native image element, endpoint helpers, timeline lanes, point-frame diagnostics, properties, warnings, ratios, and accessibility labels.

- [ ] **Step 5: Make backend state authoritative**

Open MLT on timeline selection; render/seek through the client; play its multipart stream; poll snapshots only for state/playhead; compare each parsed frame PTS to the audio-derived snapshot clock and drop expired frames before swapping the image URL. Never write timeline time from decoder PTS or HTTP arrival time. On backend failure, enter `error` with the server message and do not silently activate the old scheduler.

- [ ] **Step 6: Run browser acceptance and commit**

Run:

```powershell
node scripts/jypreview/tools/test_playback_kernel.mjs
$env:PYTHONPATH='scripts'; & $env:JY_PREVIEW_MLT_PYTHON -m jypreview.tools.test_playback_state
```

Expected: both PASS with monotonic MLT project-frame state, timestamp-aware frame drops, and no browser media element acting as a clock.

```powershell
git add scripts/jypreview/web/backend.js scripts/jypreview/web/app.js `
  scripts/jypreview/tools/test_playback_kernel.mjs scripts/jypreview/tools/test_playback_state.py
git commit -m "feat: switch preview UI to MLT clock"
```

### Task 6: Run model, composition, A/V, performance, and read-only acceptance

**Files:**
- Create: `scripts/jypreview/tools/test_mlt_acceptance.py`
- Create: `scripts/jypreview/tools/benchmark_mlt.py`
- Create: `docs/native-backend-evaluation/2026-10-01-mlt-acceptance.md`

**Interfaces:**
- Consumes: the existing 64-second/105-clip sample, representative trim/reverse/transition/text/image/audio drafts, Jianying-export reference frames, and `mtime_snapshot()` from `cli/selfcheck.py`.
- Produces: executable acceptance result plus `temp/mlt-benchmark.json`; records cold-open latency, seek samples, sustained output FPS, dropped frames, monotonicity failures, and maximum A/V delta in project frames without inventing a fixed throughput threshold.

- [ ] **Step 1: Write the acceptance script**

Assert repeated and shuffled `evaluate()` calls are identical; FrameDescriptor parity uses the same `sample_us`; three-layer geometry covers order, z, opacity, position, scale, rotation, crop, and canvas ratio; still/text/sticker/fade/crossfade intervals match; missing transition handles clamp and warn; mixed audio trim/offset/mute/gain match video; A/V delta is at most one project frame even when video frames are deliberately dropped.

- [ ] **Step 2: Add the non-mutation check**

Snapshot source draft/`Timelines/` metadata before open/seek/play/close and compare after. Assert all created files remain under the configured preview cache or root `temp/`.

- [ ] **Step 3: Add the benchmark runner**

Measure cold open, random seeks, 30 seconds of continuous output, output FPS, and drops on the 64-second/105-clip sample. Emit hardware/runtime/plugin provenance alongside raw samples; report observed values only.

- [ ] **Step 4: Run the full acceptance set**

Run:

```powershell
$env:PYTHONPATH='scripts'
py -3.14 -m jypreview.tools.test_timeline_model
& $env:JY_PREVIEW_MLT_PYTHON -m jypreview.tools.test_mlt_compiler
& $env:JY_PREVIEW_MLT_PYTHON -m jypreview.tools.test_mlt_controller
& $env:JY_PREVIEW_MLT_PYTHON -m jypreview.tools.test_mlt_acceptance
& $env:JY_PREVIEW_MLT_PYTHON -m jypreview.tools.benchmark_mlt --json temp/mlt-benchmark.json
node scripts/jypreview/tools/test_playback_kernel.mjs
```

Expected: all tests PASS; benchmark completes with zero timestamp regressions, `max_av_delta_frames <= 1`, and recorded—not predeclared—performance values.

- [ ] **Step 5: Compare representative MLT frames with Jianying exports**

Reuse the existing calibration/image comparison helpers to capture identical project frames, record similarity and visible limitations, and place only the summarized results in `docs/native-backend-evaluation/2026-10-01-mlt-acceptance.md`; keep generated images under `temp/`.

- [ ] **Step 6: Apply the cutover gate**

Proceed to Task 7 only if model/composition/continuous A/V/read-only checks pass. If local audio plus multipart video cannot stay within one project frame in the target UI, stop and write a follow-up design for one timestamped browser A/V channel; do not delete the old code yet.

- [ ] **Step 7: Commit acceptance code and report separately**

```powershell
git add scripts/jypreview/tools/test_mlt_acceptance.py scripts/jypreview/tools/benchmark_mlt.py
git commit -m "test: add MLT playback acceptance"
git -C docs add native-backend-evaluation/2026-10-01-mlt-acceptance.md
git -C docs commit -m "docs: record MLT playback acceptance"
```

### Task 7: Delete superseded GES and browser scheduling code

**Files:**
- Delete: `scripts/jypreview/playback_backend.py`
- Delete: `scripts/jypreview/tools/test_gstreamer_backend.py`
- Delete: `scripts/jypreview/tools/test_gstreamer_ir.py`
- Delete: `scripts/jypreview/web/playback.js`
- Delete: `scripts/jypreview/web/frame-store.js`
- Delete: `scripts/jypreview/web/media.js`
- Modify: `scripts/jypreview/web/app.js`
- Modify: `scripts/jypreview/web/render.js:1-31,79-111,240-300,400-415`
- Modify: `docs/native-backend-evaluation/2026-10-01-mlt-acceptance.md`

**Interfaces:**
- Consumes: the passing cutover evidence from Task 6.
- Produces: no GES backend, browser timeline clock, window-IR playback request, or per-material `<video>/<audio>` scheduler; point-frame diagnostics and `FrameDescriptor` remain.

- [ ] **Step 1: Remove obsolete imports/tests before deleting files**

Remove app/render imports and all calls tied to the three obsolete browser playback modules. In `render.js`, remove `MediaScheduler`, video/audio node creation, drift correction, and media source arming; retain image/text/placeholder nodes needed by point-frame diagnostics while native video remains the visible stage output. Keep `backend.js` and its Task 5 MLT client tests.

- [ ] **Step 2: Delete the obsolete files**

Delete the GES adapter/probes and browser backend/clock/window/audio modules listed above. Do not delete `model/framedesc.py`, `/api/frame`, the point-frame diagnostics, layout/paint/font helpers, or historical evaluation documents.

- [ ] **Step 3: Prove no legacy scheduling references remain**

Run:

```powershell
rg -n "GstGesBackend|clips_from_frame_ir|gstreamer-ges|window_us|BrowserPlaybackBackend|PlaybackController|FrameStore|AudioScheduler" scripts
```

Expected: no matches except an intentional historical comment; remove that comment if it describes current behavior.

- [ ] **Step 4: Run the final regression set**

Run:

```powershell
$env:PYTHONPATH='scripts'
py -3.14 scripts/preview.py selfcheck
py -3.14 -m jypreview.tools.test_timeline_model
& $env:JY_PREVIEW_MLT_PYTHON -m jypreview.tools.test_mlt_compiler
& $env:JY_PREVIEW_MLT_PYTHON -m jypreview.tools.test_mlt_controller
& $env:JY_PREVIEW_MLT_PYTHON -m jypreview.tools.test_mlt_acceptance
& $env:JY_PREVIEW_MLT_PYTHON -m jypreview.tools.test_playback_state
node scripts/jypreview/tools/test_playback_kernel.mjs
```

Expected: all PASS, source-draft mutation count is zero, and UI state reports only `mlt`.

- [ ] **Step 5: Update acceptance status and commit code/docs separately**

Mark cutover passed and list retained first-release limitations in the acceptance report.

```powershell
git add scripts/jypreview/playback_backend.py `
  scripts/jypreview/tools/test_gstreamer_backend.py `
  scripts/jypreview/tools/test_gstreamer_ir.py `
  scripts/jypreview/web/app.js scripts/jypreview/web/render.js `
  scripts/jypreview/web/playback.js `
  scripts/jypreview/web/frame-store.js scripts/jypreview/web/media.js
git commit -m "refactor: remove legacy playback schedulers"
git -C docs add native-backend-evaluation/2026-10-01-mlt-acceptance.md
git -C docs commit -m "docs: mark MLT playback cutover"
```

## Deliberately Deferred

- libopenshot fallback: add only if Task 1 fails, under a separate design and plan.
- Private Jianying effects/animations and exact flower fonts: add only from verified local bundle semantics.
- Browser-native multiplexed A/V transport: add only if Task 6 proves local audio sink plus timestamped frames cannot meet the one-frame sync criterion.
- Draft write-back, export, arbitrary transport rates, and a full editor command layer remain out of scope.
