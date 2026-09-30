# Jianying 只读 Web 编辑器 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current browser playback/UI with a read-only React/TypeScript editor surface backed by the existing Python Jianying reader, without modifying source drafts.

**Architecture:** Python remains the only local runtime service and owns Jianying discovery, decryption, normalization, media/font serving, and SSE. A Vite-built React frontend owns a framework-independent TypeScript `EditorCore`, microsecond playback clock, pure scene resolver, read-only timeline UI, and DOM stage renderer.

**Tech Stack:** Python 3, aiohttp, existing Jianying decrypt/cache/FrameDescriptor code, Node.js, TypeScript, Vite, React 19, Vitest, Testing Library, existing CDP/Edge browser harness.

**Spec:** `docs/superpowers/specs/2026-09-29-jianying-readonly-web-editor-design.md`

## Global Constraints

- The frontend is read-only: no cut, move, split, subtitle edit, save, export, or draft write-back.
- The source draft directory and every original file under it must remain unchanged; only `.jypreview` or user-cache files may be written.
- Time values in the normalized contract and EditorCore are integer microseconds; intervals are half-open `[start_us, end_us)`.
- Python is the only long-running local service; Node.js is used for frontend development, build, and tests.
- OpenCut and Elah are references only; do not add Rust, WASM, OpenCut source, or an external editor runtime.
- Existing dirty working-tree changes are user-owned and must not be reset, overwritten, or staged by these tasks.
- Unsupported Jianying effects must be represented by warnings/placeholders, never silently omitted.

## Review Focus

- Hybrid drafts whose root file is a stale mirror: the selected nested active timeline must win and its source hash must be reported.
- Ambiguous active timelines: the UI must require explicit selection instead of guessing.
- Clips with missing media: the timeline remains navigable and shows a stable placeholder/warning.
- Boundary timestamps: adjacent half-open clips must not both be active at a seam.
- Browser lifecycle: hidden/visible transitions, repeated same-time seeks, and end-of-timeline playback must not leave media or animation state stale.

---

### Task 1: Add the normalized read-only editor-project API

**Files:**
- Create: `scripts/jypreview/model/editor_project.py`
- Create: `scripts/jypreview/server/handlers_editor.py`
- Test: `scripts/jypreview/tools/test_editor_project.py`

**Interfaces:**
- Consumes: `PreviewSession.view()`, `FrameDescriptor`/IR layer data, existing material/path/font helpers, and timeline selection logic.
- Produces: `build_editor_project(view, timeline_id) -> dict` and `GET /api/editor-project?draft=<selector>&timeline=<id>` returning schema `jypreview/editor-project@1`.

- [ ] **Step 1: Write failing normalizer tests**

  Add fixtures/assertions for legacy-single, multi-timeline, and hybrid layouts; explicit timeline selection; `visible:false`; target/source microsecond ranges; speed/reverse; `render_index`; text styles; missing media; and `read_only:true`.

- [ ] **Step 2: Run the Python test module and verify the expected failures**

  Run: `python -X utf8 -m jypreview.tools.test_editor_project`

  Expected: failures for the missing normalizer and missing API contract.

- [ ] **Step 3: Implement `build_editor_project(view, timeline_id)`**

  Normalize existing IR into stable tracks, clips, assets, warnings, media URLs, text/style data, transforms, and labels. Flatten supported nested subdraft layers up to the existing recursion limit; emit warnings when the limit or a renderer capability is exceeded. Keep all source ranges as integers.

- [ ] **Step 4: Register the read-only API handler**

  Add the endpoint to `server/app.py`. Resolve the requested timeline explicitly, return `timeline_ambiguous` when no active timeline is provable, and never expose a write operation.

- [ ] **Step 5: Run the focused and existing Python checks**

  Run: `python -X utf8 -m jypreview.tools.test_editor_project` and `python -X utf8 scripts/preview.py selfcheck --milestone all`

  Expected: all new assertions pass; existing selfcheck remains green.

- [ ] **Step 6: Commit**

  Commit only the Task 1 files with message `feat: expose read-only editor project model`.

### Task 2: Build the framework-independent TypeScript EditorCore

**Files:**
- Create: `scripts/jypreview/web/src/core/project.ts`
- Create: `scripts/jypreview/web/src/core/playback-clock.ts`
- Create: `scripts/jypreview/web/src/core/scene.ts`
- Test: `scripts/jypreview/web/src/core/*.test.ts`

**Interfaces:**
- Consumes: `jypreview/editor-project@1` from Task 1.
- Produces: `EditorSession`, `PlaybackClock`, `resolveScene(tUs, project)`, `Scene`, `ActiveClip`, and `Renderer` interfaces for React consumers.

- [ ] **Step 1: Add failing clock tests**

  Cover play/pause, seek, rate, end, repeated same-time seek, integer microseconds, hidden-page re-anchor, epoch increments, and clamped elapsed time.

- [ ] **Step 2: Run the focused Vitest file and verify it fails**

  Run: `npm test -- --run src/core/playback-clock.test.ts`

  Expected: missing-module or missing-method failures, not setup failures.

- [ ] **Step 3: Implement `PlaybackClock`**

  Use anchor-and-integrate arithmetic with integer `tUs`; expose `play()`, `pause()`, `seek(tUs)`, `setRate(rate)`, `subscribe(listener)`, `snapshot()`, and `destroy()`.

- [ ] **Step 4: Add failing resolver tests**

  Cover half-open visibility, source mapping, speed/reverse, track/clip visibility, stable z-order, missing media, and deterministic repeated resolution.

- [ ] **Step 5: Implement `resolveScene(tUs, project)`**

  Keep it pure: no DOM, React, fetch, media seeking, or state mutation. Return sorted active media/text layers plus warnings and timeline metadata.

- [ ] **Step 6: Add the API schema and `EditorSession`**

  Validate the Python response at the boundary, hold the immutable snapshot, expose read-only timeline selection, and connect the clock to scene subscriptions.

- [ ] **Step 7: Run the full Node test suite**

  Run: `npm test`

  Expected: all core tests pass with no browser dependency.

- [ ] **Step 8: Commit**

  Commit only the Task 2 frontend core files with message `feat: add read-only editor core and playback clock`.

### Task 3: Implement the React editor surface and DOM renderer

**Files:**
- Create: `scripts/jypreview/web/src/app/AppShell.tsx`
- Create: `scripts/jypreview/web/src/components/PreviewStage.tsx`
- Create: `scripts/jypreview/web/src/components/Timeline.tsx`
- Test: `scripts/jypreview/web/src/components/*.test.tsx`

**Interfaces:**
- Consumes: `EditorSession`, `Scene`, `PlaybackClock`, and `Renderer` from Task 2.
- Produces: read-only DraftPicker, TimelinePicker, PreviewStage, TimeRuler, TrackRow, ClipBlock, Playhead, InspectorPanel, WarningsPanel, and PlaybackControls.

- [ ] **Step 1: Write failing component tests**

  Assert read-only labels, draft/timeline metadata, track rendering, clip selection, ruler seeking, play/pause control, inspector fields, warning display, and missing-media placeholders.

- [ ] **Step 2: Run the component tests and verify they fail**

  Run: `npm test -- --run src/components`

  Expected: missing component/module failures.

- [ ] **Step 3: Implement the app shell and API loading states**

  Provide empty, loading, ambiguous-timeline, decrypt-failed, missing-media, and stale-draft states. Keep selection/panel state local to the UI and do not mutate the project snapshot.

- [ ] **Step 4: Implement `DomStageRenderer`**

  Reconcile stable layer nodes by clip ID; use `<video>`, `<audio>`, `<img>`, and text DOM; apply resolved transforms and opacity; synchronize media from clock snapshots without allowing media events to update the clock.

- [ ] **Step 5: Implement the timeline and inspector**

  Render tracks and clips from normalized data, seek on ruler/clip click, show source/target times and z-order, and omit all mutation affordances.

- [ ] **Step 6: Run component and build checks**

  Run: `npm test` and `npm run build`

  Expected: tests pass and Vite emits a production bundle.

- [ ] **Step 7: Commit**

  Commit only the Task 3 frontend UI files with message `feat: add read-only timeline editor surface`.

### Task 4: Integrate Vite output, Python static serving, media, and SSE

**Files:**
- Modify: `scripts/jypreview/server/_http.py`
- Modify: `scripts/jypreview/server/handlers_drafts.py`
- Modify: `scripts/jypreview/web/package.json`
- Test: `scripts/jypreview/tools/test_editor_integration.py`

**Interfaces:**
- Consumes: built frontend from Task 3 and `/api/editor-project` from Task 1.
- Produces: Python-served production UI, Vite development proxy configuration, media/font URLs, and draft-change invalidation.

- [ ] **Step 1: Write failing integration tests**

  Assert `/` serves the built application, `/web/*` serves hashed/static assets, API responses are reachable, SSE draft changes mark the UI stale, and media/font endpoints remain available.

- [ ] **Step 2: Run the integration test and verify failure**

  Run: `python -X utf8 -m jypreview.tools.test_editor_integration`

  Expected: failure until the built-output serving path and endpoint wiring are implemented.

- [ ] **Step 3: Add the Vite/React package configuration**

  Use Node.js/TypeScript/Vite/Vitest/React. Configure development requests to proxy to the Python service; configure production output under the Python-served web directory. Do not add a Node runtime server.

- [ ] **Step 4: Update Python static serving**

  Serve `dist` when present and retain a clear development fallback. Keep cache-busting and path traversal protection. Do not serve source files when a production bundle exists.

- [ ] **Step 5: Connect media, fonts, and SSE**

  Use existing asset endpoints, validate URL failures as placeholders, subscribe to `/api/events`, and mark the current project stale instead of silently reloading during playback.

- [ ] **Step 6: Run integration and build checks**

  Run: `npm run build` and `python -X utf8 -m jypreview.tools.test_editor_integration`

  Expected: production assets load through `preview.py serve`; no Node server is required.

- [ ] **Step 7: Commit**

  Commit only the integration/configuration files with message `feat: serve the read-only editor through the Python service`.

### Task 5: Add browser parity and non-mutation acceptance

**Files:**
- Create: `scripts/jypreview/tools/test_editor_ui.py`
- Modify: `scripts/jypreview/tools/audit_playback.py` or replace it with an editor-specific audit entrypoint
- Test: existing fixture corpus plus new synthetic editor-project fixtures

**Interfaces:**
- Consumes: the running Python service, built frontend, `/api/editor-project`, `/api/frame`, and existing CDP/Edge harness.
- Produces: repeatable browser acceptance of loading, playback, scene parity, and source immutability.

- [ ] **Step 1: Record source signatures before browser use**

  Capture SHA-256, mtime, and file list for the selected draft and assert the allowed cache roots.

- [ ] **Step 2: Write the failing browser assertions**

  Cover draft open, explicit timeline selection, timeline rows, sampled layer IDs, five seconds of monotonic playback, seek across boundaries, warning display, no per-frame `/api/frame` storm, and unchanged source signatures.

- [ ] **Step 3: Run the browser test to establish the expected failure**

  Run: `python -X utf8 -m jypreview.tools.test_editor_ui`

  Expected: failures identify missing editor debug hooks or UI behavior, not a missing browser executable.

- [ ] **Step 4: Add stable debug hooks**

  Expose `window.__editorSnapshot()`, `window.__editorScene()`, `window.__editorErrors()`, and `window.__editorClose()` for acceptance only; keep them read-only.

- [ ] **Step 5: Run browser acceptance and existing selfcheck**

  Run: `python -X utf8 -m jypreview.tools.test_editor_ui` and `python -X utf8 scripts/preview.py selfcheck --milestone all`

  Expected: scene layer IDs match Python IR at sample points, playback is monotonic, and source drafts remain unchanged.

- [ ] **Step 6: Commit**

  Commit only the acceptance/audit files with message `test: verify read-only editor playback and draft safety`.

### Task 6: Remove old browser playback path and update documentation

**Files:**
- Modify: `scripts/jypreview/web/*` legacy entrypoints and `SKILL.md`
- Modify: `references/agent-verification-loop.md`
- Test: full Python and Node suites plus browser acceptance

**Interfaces:**
- Consumes: the new production UI and all acceptance tests from Tasks 1–5.
- Produces: one documented read-only editor path with no live imports of the old playback controller/window-pool implementation.

- [ ] **Step 1: Search for old playback imports and debug hooks**

  Run: `rg -n "PlaybackController|FrameStore|MediaScheduler|SceneGraph|__play|__state|__layers" scripts/jypreview/web scripts/jypreview/server scripts/jypreview/tools`

  Expected: only intentional compatibility/audit references remain.

- [ ] **Step 2: Remove or quarantine unused old playback modules**

  Remove old browser playback code only after the new UI is the default and acceptance passes. Do not delete Python decoding/IR logic used as the parity oracle.

- [ ] **Step 3: Update Skill and verification documentation**

  Document the new Node build commands, Python runtime command, normalized API, read-only guarantee, debug hooks, known degradations, and browser acceptance loop.

- [ ] **Step 4: Run the final full suite**

  Run: `npm test`, `npm run build`, `python -X utf8 scripts/preview.py selfcheck --milestone all`, and `python -X utf8 -m jypreview.tools.test_editor_ui`.

  Expected: all suites pass; no source draft writes occur.

- [ ] **Step 5: Commit**

  Commit documentation and cleanup with message `docs: document the read-only web editor architecture`.

## Delegation protocol

The implementation conversations are sequential because each stage produces a shared interface consumed by the next stage:

1. **Subtask conversation A — Python model/API**
   - Read the Task 1 brief only.
   - Implement and test the normalized editor-project endpoint.
   - Do not touch frontend files or write any draft file.

2. **Subtask conversation B — TypeScript core**
   - Read the Task 2 brief and the committed API contract.
   - Implement clock, scene resolver, and session tests.
   - Do not redesign the Python payload.

3. **Subtask conversation C — React UI**
   - Read the Task 3 brief and consume the frozen TypeScript interfaces.
   - Implement only read-only UI and DOM rendering.
   - Do not add edit commands or persistence.

4. **Subtask conversation D — integration**
   - Read the Task 4 brief and integrate Vite output with Python serving.
   - Do not introduce a second runtime server.

5. **Subtask conversation E — acceptance**
   - Read the Task 5 brief and run browser parity/non-mutation checks.
   - Report exact failures, sample times, request counts, and source signatures.

6. **Main conversation**
   - Review each task result, resolve interface conflicts, run final suite, remove old playback path, and perform final code review.

Each delegated conversation must return its commit hash, changed files, tests run, test output summary, uncovered capabilities, and plan conflicts.
