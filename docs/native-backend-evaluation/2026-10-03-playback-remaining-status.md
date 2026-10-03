# Playback remaining work — evidence and decision handoff, 2026-10-03

**Release:** `f0ef7da4db3d6675a1fbee63c14bfd4cd4cc76ef` contains independently reviewed
Task 1 seek/image-commit and Task 1b native replacement/cancellation ownership fixes.
**Task 2 production candidate:** `204e731`; subsequent `25ebffa` changes tests only.
Candidate quality review does not pass strict B1 or authorize release integration/deletion.

## Exact evidence and limits

Workspace evidence is the named reports under the 024e root
`temp/superpowers/sdd/2026-10-03-playback-remaining/`; raw output remains at those report paths.
The Task 1 report's early native startup/AV failures remain valid historical RED evidence;
Task 1b subsequently passed full controller/endpoint and scoped real-native ownership checks.
Its cancellation fix is in release f0ef7da. This status records parent review/integration,
while those original reports retain their contemporaneous pre-review status.

Task 2 packs 45 eligible stills into 3 native lanes, retains PNG point render, uses JPEG q85
streaming and a standard threading.Event readiness wait without native history queues.
The application already consumes `/api/backend/stream`.

| Exact 204e731 observation | Result | Meaning |
|---|---|---|
| Native 40.0804838s profile | 29.9991931271fps; clock 0.9999731222x; CPU 62.92027% of one core; 3 lanes;warnings [] | Native sink near nominal30; exact estimator retained |
| Normal production page 20.1026018s, fixed 2s/1s exclusions |513 distinct RAF frames; **29.999238216104732 fps**;513 loads 30.007501695000087fps | **Strict RAF≥30 is unmet**; load cadence cannot substitute |
| Source PTS sequence |ZERO gaps across RAF/load/src observers | Contiguous observed source sequence does not change strict cadence arithmetic |
| UI state estimate |1.000481x; finalplaying/errorNone/seekpendingfalse | Polled UI estimate; separate native profile proves only native clock rate |

Raw source records: `task2-native-readiness-clean-204e731.json`,
`task2-native-readiness-final.log`, `task2-normal-page-204e731.json`,
`task2-page-readiness-normal-204e731.log`, `task2-readiness-final-sourceproof.json`.
Full controller/lifecycle at production 204e731 passed; core kernel evidence is retained in
`task-2-report.md`. Later test-only 25ebffa repaired readiness-test scheduling, and its focused
readiness check passed, but its one requested full-controller run **failed** at the unchanged
5s native startup-readiness gate with SDL audio timeout (8.9353034s process elapsed).
`task-2-controller-readiness-deterministic-full-failed.log` is the failure record; the original
requested `...deterministic-green.log` filename does not imply GREEN. No broad retry or
native/page remeasurement followed. Earlier production 204e731 GREEN evidence remains distinct.
Incidental Proactor WinError10054 disconnect warnings are retained; no native AV was observed
in the final 204e731 measurements. Earlier failed diagnostics and rejected1ms polling trial
remain preserved, with their original source/window provenance.

## Clock and physical capture hold

The fallback design is corrected in
`docs/superpowers/plans/2026-10-02-timestamped-browser-av-channel-design.md`.
Historical panel observations 130–165Hz (~6.1–7.7ms) are hardware-specific page evidence,
not external-camera measurements. T1 actual presentation and T2 device emission remain
unverified. DirectSound 10ms steps/interpolation do not constitute a beacon; critical T4
query gaps 2.66/2.89ms exceed 500µs.

Previous T3 fetch bound was ±799.6µs. `t3-method.md` specifies expanding endpoint errors
before interval intersection, conditional qT=101µs only after runtime clamp/high-resolution
provenance, drift and new-event quantization counted once. No new T3 capture occurred.
T3 ceiling 500µs, T4 ceiling 500µs, subtotal 3583µs, T1+T2 pool 4750µs and total 8333µs
are unchanged allocations; achieved precision has not been established.
P1b MSE/rVFC implementation has no authorization.

## Supplied project/export prerequisites

`input-evidence.md` records the user-supplied export
`微信视频2026-10-03_001812_744.mp4`: H264 1080x1920,CFR 30,54.9s/1647frames.
It plausibly targets 成片, but mapping is unverified and30fps cannot supply≥240fps
screen-plus-audible marker calibration. **No successful external≥240fps recording exists
in the supplied evidence.** The requested external path remains outstanding.

The supplied draft package is encrypted. Active 成片 source SHA256 is
`F5C2320B4B8D499E331E005103B5D66ADAE54261C23D2ECAE38537D17F395CB5`;
the bundled cache records 9eac..., a mismatch. Cache is provisional 54.8s/1644frames,
with missing projectFPS/default30; it is not a fresh decrypted current project.
Layout selects 成片`03B09C7D-44B6-4845-B509-E2801B198852`, whereas project.json's main
timeline names 时间线01`8FA0EC97-F6D2-4c0d-AF00-A46CC4AD367A`.
Do not treat the 时间线01 cache as a matched 成片 export.

Targeted workspace checks found no real jianying_project.py/jy_draft_crypto.py decoder,
compatible videoeditor.dll or installed editor path. The decoder/external paths were
requested from the user and remain absent. The integration-preview editor stub is a fixture
helper and cannot decode this project. No supplied README/CSV/package commands were executed.
Knowledge-base listing yielded only unreal-wiki/gamedesign-wiki; no relevant Jianying evidence
was retrieved. Package/runtime conclusions are workspace evidence; plausibility is inference.

## Dependencies and release decision

Step 5 export comparison requires fresh decrypted active 成片 and verified export mapping.
Phase B requires strict B1, complete T3 proof, T1/T2 pool evidence, achieved T4 cadence and
physical external/beacon calibration; Phase C then requires both modes≥30s,29 markers each,
real drops near markers and the unchanged validator gate. Task 7 depends on all those gates.
**Step 5/Phase B/Phase C/Task 7 remain blocked; all six old modules remain.** No release merge,
legacy deletion, device change, new physical capture or gate-arithmetic change is made by
this documentation correction.

Docs commands are issued from `E:/Develop/jianying-preview/docs`, but current
`git rev-parse --show-toplevel` returns parent `E:/Develop/jianying-preview`.
It is not an independent Git repository in this checkout. The documentation commit stages
only these two documents and preserves the user's original modified plan/spec/.gitignore.
