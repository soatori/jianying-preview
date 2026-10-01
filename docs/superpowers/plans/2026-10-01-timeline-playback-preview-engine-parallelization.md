# Timeline Playback Preview Engine: Parallel Work Items

Companion to [the implementation plan](2026-10-01-timeline-playback-preview-engine.md). This document identifies safe parallel work and coordination points; it does not change the task order, scope, gates, or acceptance criteria in that plan.

## Dependency gates

```text
Task 1 MLT gate PASS
  -> Task 2 model and adapter
  -> Task 3 MLT compiler
  -> Task 4 HTTP contract frozen
       -> Task 4 controller and HTTP API implementation
       -> Task 5 browser client and UI implementation
       -> Task 4 + Task 5 end-to-end acceptance PASS
            -> Task 6 acceptance and captured A/V gate PASS
                 -> Task 7 legacy removal
```

The MLT runtime gate blocks implementation in Tasks 2-7. Task 7 must wait for Task 6's synchronized normal and dropped-video captures to pass; internal graph timestamps alone do not unblock deletion.

## Parallelizable work by task

| Plan task | Parallel work | Start condition and coordination |
| --- | --- | --- |
| 1. MLT runtime gate | Implement `test_mlt_runtime.py` while preparing the isolated runtime under `temp/mlt-runtime/`. | Agree on the test media and environment variable names first. Run the gate only after both are ready; Task 2 and later remain blocked until it passes. |
| 2. Model and adapter | After the model values and public signatures are fixed, implement adapter normalization in `model/draft_adapter.py` alongside `DraftView.timeline_model()` caching in `session.py`. | Keep the required test-first sequence for the core model. Freeze the model dataclasses and `DraftAdapter.build()` signature before splitting adapter/session work. Keep a single owner for `test_timeline_model.py`; merge both lanes before adding/running parity assertions. |
| 3. MLT compiler | No safe implementation split inside this task: the required compiler test-first sequence and shared `mlt_backend.py` make the steps serial. | Keep Task 3 complete before Task 4, which also edits `mlt_backend.py`. Independent review of fixtures/contracts can happen before implementation, without changing the step order. |
| 4. Controller and HTTP API | Implement `PlaybackController` in `mlt_backend.py` alongside HTTP route integration in `handlers_backend.py` and handle lifecycle in `server/app.py`. | Start route wiring once the controller method names, snapshot fields, and immutable frame envelope are fixed. Give the server files one owner; keep one owner for `test_mlt_controller.py`. Run endpoint acceptance after both lanes integrate. |
| 5. Browser cutover | After the client contract and test-first steps are settled, implement `MltPlaybackClient` in `web/backend.js` alongside UI integration in `web/app.js`. | Freeze the HTTP route/header contract first. Keep one owner for `test_playback_kernel.mjs` and one for `app.js`; run `test_playback_state.py` only once the backend API and UI integration are both available. |
| 6. Acceptance | Build `benchmark_mlt.py` in parallel with `test_mlt_acceptance.py` and the acceptance report draft. | Share the fixture timeline and evidence schema first. Keep a single owner for the acceptance script/report. Benchmark execution and synchronized browser/audio capture must use separate runs so one does not distort the other's timing or output. |
| 7. Legacy removal | After the Task 6 gate passes, remove the obsolete Python/GES backend and its tests in parallel with browser scheduler/media cleanup in `web/app.js`, `web/render.js`, and the listed browser modules. | First agree on the import/call-site removal list. Keep Python and browser file ownership separate, then run both reference searches and the final regression set after merging the lanes. Update the acceptance report after cleanup is complete. |

## Work that stays serial

- Task 1 gate execution and result recording follow runtime preparation and probe implementation.
- In Task 2, model contracts precede adapter integration; parity assertions use the completed model and adapter.
- Task 3 compilation follows the passing Task 2 model tests.
- Task 4 route wiring depends on the controller contract; endpoint acceptance depends on both.
- Task 5 client/UI coding may overlap Task 4 after the HTTP contract is frozen; end-to-end browser state checks depend on the Task 4 API and UI integration.
- Task 6 full acceptance, including the two synchronized capture modes, precedes its cutover decision.
- Task 7 cleanup and final regression follow a passing cutover decision.

## Suggested worker boundaries

For parallel execution, assign work by the file groups above. Freeze shared interfaces before splitting dependent work, avoid concurrent edits to the same test or UI file, and integrate each task's lanes before its existing run-and-commit step. Keep all existing plan gates, read-only draft constraints, and runtime requirements in force.
