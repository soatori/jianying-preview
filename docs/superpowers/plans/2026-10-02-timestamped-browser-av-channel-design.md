# Design: one timestamped browser A/V channel (`timestamped-channel-v1`)

**Status:** fallback design for coordinator review — **rev.3, corrected 2026-10-03**.
Task 1/1b are reviewed and merged into release `f0ef7da`; Task 2 production `204e731`
is a quality-reviewed candidate, pending integration. B1 is still unmet: final normal-page
RAF cadence **29.999238216104732 fps < 30**. Phase B/C and Task 7 remain blocked.
Rev.1/rev.2 historical assumptions and failed evidence are retained in the evidence trail (§9).
**Authored:** 2026-10-02 (original user decision date = 2026-10-02, per plan Step 6 fallback).
**Authorization:** plan `docs/superpowers/plans/2026-10-01-timeline-playback-preview-engine.md`
Task 6 Step 6: *"If measured playback fails, stop and write a follow-up design for one
timestamped browser A/V channel. Keep the old files until this gate passes; recapture if playback
code, native runtime, or output device changes."*
**Trigger:** both prior measurement lanes ended RED — `temp/mlt-capture/research.md`
(projected ≈13–16 ms > 8,333 µs; per-pair jitter ≈78.5 ms MAD) and
`temp/capture-rea/reassessment.md` (best projection 9,394 µs vs 8,333 budget after one
optimization round; escalation to this design).

**Non-goals:** no gate-arithmetic change, no deletion of old files/instruments. This design
replaces the *instrument*, not the gate. One branch (P1b) additionally proposes a product change
that is explicitly out of scope until approved (§1.1B).

**Historical rev.2 decisions (current corrections below):**
1. **Audio ownership:** plan Task 6 Step 1's *"local MLT audio sink"* clause is **adopted** — pulses
   exit via the server's MLT SDL/dsound sink. The rev.1 page-`AudioBuffer`/WebAudio design
   measured a path that does not exist and is **removed**; audio is now timestamped **server-side
   on the server clock** (§1.2).
2. **P1 confirmed and split:** the native display path is `<img>` (`scripts/jypreview/web/app.js`), rVFC does not
   apply as the product exists. The design now documents **both** the no-product-change branch
   **P1a** (decode → rAF paint observation) and the product-change fallback **P1b** (`<video>` +
   MSE of MLT frames, then original rVFC design) — §1.1A/§1.1B.
3. **T2 re-derived** as server device-position estimation (spike-dependent, see §4); **T3
   simplified** to a single page→server mapping (§2); budget re-totaled (§4).

---

## 1. Mechanism

One coherent design: **video timestamps are taken in the page on `performance.now()` and shipped
over the existing CDP WebSocket** (`scripts/jypreview/shot/cdp.py` → `Runtime.evaluate`, the
channel the harness already uses for `window.__state()`); **audio timestamps are taken in the
server process on the server monotonic clock** (same machine, same timebase family). One capture
clock (§2), proposed capture avoids PrintWindow/ffmpeg recording; observation overhead still needs measurement. The dose-response
cost the old instrument 0.988 → 0.892× content rate (`reassessment.md` §1).

### 1.1A. Video branch P1a (no product change, runs first in the spike)

**Verified current source:** `scripts/jypreview/web/app.js` creates `nativeFrame` as an
`<img>`; `renderMltAt` uses the point-render path and the application calls
`mlt.startStream(queueFrame, ...)`. `scripts/jypreview/web/backend.js` implements
`MltPlaybackClient.#startStream` fetching `/api/backend/stream`. Point render remains PNG;
Task 2 production candidate `204e731` streams JPEG quality 85 through
`scripts/jypreview/server/handlers_backend.py` (`_encode_jpeg` / `stream`).
These symbol/path references were checked against current 024e source; subsequent `25ebffa`
changes only tests, with no production delta from `204e731`. `<img>` has no rVFC presentation API.

Per frame, the channel observes the paint chain:

```
frame part arrives (identity: X-Project-PTS-US, exact server PTS µs)
  → decode (img.decode() / createImageBitmap)
  → nativeFrame.src swap
  → first requestAnimationFrame after decode completes   ← video_capture_us anchor
  + video_display_constant (one-time external spot-check, §3)
  → capture clock (§2)
```

`video_capture_us(k)` = anchor of the first painted swap whose PTS ≥ `k·1e6` and <
`(k+1)·1e6` (markers are one-second held windows), plus the constant. The rAF anchor is a
*present-schedule observation*: actual photon timing still requires a measured present bound. The
residual — decode/paint race slipping a frame, main-thread jank, DWM scheduling — is **T1**, not
observable in-band for `<img>`; worst case cited = one measured hardware refresh (~6.1–7.7 ms over the observed 130–165 Hz range) plus race
slip. **Phase A measures the paint-chain jitter against the §4 headroom; external 240 fps
spot-check validates the constant. Vsync quantization may exceed headroom — the spike decides,
not this document.**

**B1 (frame delivery during play): implemented consumer, unmet cadence gate.**
The native page consumes `/api/backend/stream`; multipart image parts carry `X-Project-PTS-US`.
The Task 2 candidate packs the eligible 45-still fixture into 3 lanes. Its native sink is near
nominal 30 fps (final exact-source estimate 29.9991931271 fps); final normal-production page
RAF observations are **29.999238216104732 fps**, 513 distinct frames, no observed source-PTS
gaps. This is strictly below the unchanged ≥30 condition: **B1 has not passed**.
The latest candidate uses one standard `threading.Event` frame-ready wait and retains the
selected immutable frame across worker handoff; it adds no native frame-history queue.
The existing client can still coalesce frames. Snapshot polling supplies transport state,
and its clock estimate is not native master-clock or physical presentation proof.
See `task-2-report.md` and its exact-head raw files (§9); no measurement is relabelled as release.

### 1.1B. Video branch P1b (fallback if the P1a spike fails) — a PRODUCT CHANGE

If Phase A cannot bound T1 (§4) at ≤ headroom, the proposed fallback would switch the display to a presentation-timed
path: **`<video>` fed by an MSE stream of MLT frames**, restoring the original rVFC design
(`expectedDisplayTime` + `mediaTime`, §4-T1 as originally cited, drop detection via
`presentedFrames`).

Concrete entailment (checked against the repo):

* The transport exists: `/api/backend/stream` uses the candidate private `_pull_stream_frame` path and
  emits per-frame parts with PTS headers — P1b would replace the JPEG/multipart body with **fragmented
  MP4 (H.264)** produced from the same pull (server-side encoder: MLT `avformat`/openh264 pipe),
  fed to `MediaSource`/`SourceBuffer.appendBuffer` on the page; `mediaTime` = frame PTS →
  `project_frame` identity is exact (`first_frame_at_or_after` on the fMP4 timeline + the same
  segment offset arithmetic as rev.1 §5).
* Page side: MSE glue + rVFC hookup where `nativeFrame` (an `<img>` that cannot show a
  `<video>`) is replaced by a `<video>` element in `.canvas`; dropped-mode accounting comes
  back for free from `presentedFrames`/`mediaTime` gaps.
* Cost/honesty: displayed pixels become encoder-round-tripped (marker color blocks stay
  identifiable; image-accuracy checks in Task 6 Step 5 use the separate render endpoint and are
  unaffected), preview display mechanics change, low-latency fMP4 plumbing has its own tuning
  risk. **Rough effort: 2–4 sessions** (server encode+endpoint ~1–2, page MSE/rVFC ~1,
  validation ~1).
* **Scope: requires plan-level approval** (it changes preview display mechanics — coordinator/
  user decision, not an instrument-only decision). P1b is *designed here; no MSE/rVFC P1b implementation was authorized.*

### 1.2. Audio side — server-side device-position timestamping (page-WebAudio design removed)

**Verified fact:** plan Task 6 Step 1 *"normal browser URL and local MLT audio sink"* is adopted —
calibration pulses exit via the MLT SDL sink on the **server** (`SDL_AUDIODRIVER=dsound` is the
code default in the MLT lane, evidence `5f180f5`). No browser API can timestamp that path.

Timestamping target for pulse *k* (context: sample offset `S_k` from
`first_frame_at_or_after(k*1e6)` — exact integer arithmetic):

```
write_instant(S_k)   ← device-position estimate on the server clock
emission_time        = write_instant + holding_constant   (one-time loopback/mic beacon)
audio_capture_us(k)  = emission_time  (server monotonic, §2)
```

**Candidate position sources, probed in Phase A (fidelity is now a spike item — SDL2 makes no
guarantees here):**

1. **SDL2 queued-audio accounting** — if the MLT sdl2 consumer uses the queued path
   (`SDL_QueueAudio`), `SDL_GetQueuedAudioSize()` returns *bytes submitted but not yet handed to
   the device*; `submitted − queued` is a **staircase**: it jumps by one mix period per SDL audio
   thread callback. SDL2 documents the byte count only — **no** guarantee about step cadence or
   correlation to hardware emission. Spike measures: the consumer's actual open parameters (mix
   period; SDL's default of 4096 frames would be 85,333 µs @ 48 kHz — cited worst, almost
   certainly RED if that is what is used), step-instant detectability under a tight server-side
   poll (target ≤ 500 µs cadence around marker instants), and
   **write→hardware delivery jitter** (Lock-to-play-cursor holding variation on the dsound ring).
2. **Direct device play-position** (preferred if 1's delivery jitter exceeds headroom): a
   DirectSound play-cursor query (`IDirectSoundBuffer::GetCurrentPosition`) against the sink's
   buffer — play position is a device-position estimate requiring emission validation; granularity is driver/mixer
   granularity on Windows' dsound-over-WASAPI path must be measured against physical emission.
   Historical cursor steps were 10 ms; interpolation does not supply a physical beacon.

**Current T4 evidence:** critical query gaps of **2.66/2.89 ms exceed 500 µs**.
Ten-millisecond DirectSound steps and interpolation are not a beacon. The ≤500 µs
cadence budget is neither achieved nor re-priced; **T2 physical emission remains unverified**.
The *write-instant* query is scheduled by the instrument; the
*write→emission* jitter is a property of the driver/sink and is **NEEDS-SPIKE** with a cited
worst of one device mix period. If neither candidate bounds it, the audio side does not reach
the budget and the gate reports `unverified` — the spike, not this document, decides. Zero-return
/ unavailable position data ⇒ `unverified` (fail-closed), same rule as rev.1.

### 1.3. Why this is still "one timestamped browser A/V channel"

The channel = **one instrument, one capture clock, both observations timestamped at their
presentation boundary** (video: paint-schedule observation in the page; audio: device-position
observation in the server process), shipped over existing transports (CDP for page events, the
server's own clock for audio). What it is *not*: no consumer-clock callbacks, no HTTP arrival
timestamps, no `image.onload`/`onload` as the capture observation (arrival/decode are used only
for *identity*; presentation is the rAF anchor + validated constant on video, and device position
+ beacon constant on audio) — the plan's Task 6 Step 1 ban list is respected (§3).

---

## 2. One clock — conservative T3 method, not a passed gate

Capture clock is server monotonic; video observations use the same document's
`performance.now()` and require a bounded page→server conversion. RTT/2 medians or
bootstrap repeatability do not prove absolute ≤500 µs precision. The previous fetch-derived
bound was **±799.6 µs**; no new T3 capture was performed for this correction.

The independent `temp/superpowers/sdd/2026-10-03-playback-remaining/t3-method.md` specifies,
in µs, browser endpoints T0/T1, server endpoints S0/S1, endpoint errors qT/qS,
reference time tref and drift allowance D:

```
I_i = [S1-T1-qS1-qT1-D(T1,tref), S0-T0+qS0+qT0+D(T0,tref)]
L = max(lower endpoints); U = min(upper endpoints)
require L <= U; offset = (L+U)/2; parameter bound = (U-L)/2
```

Expand timestamp quantization/error **before** intersecting. A truly empty expanded
intersection fails; samples must not be discarded to improve the bound. Chromium's ordinary
100 µs randomized-clamp buckets do not justify ±50 µs. **qT=101 µs is conditional** on
validating the installed Chromium clamp/high-resolution implementation and runtime provenance
(version, timer increments, isolation, unchanged document origin). The fixed clamped origin is
absorbed in the effective same-document offset; do not add Unix `performance.timeOrigin` again.
Record QPF, server `time.get_clock_info` resolution and integer conversion. Python Windows uses
QPC, while Chromium can choose QPC or millisecond `RolloverProtectedNow`; common provenance
must be verified. Same-QPC implies no independent oscillator drift, but pre/post agreement
alone cannot bound an interior excursion without provenance.

The expanded radius already includes calibration endpoint errors. A **new** rAF/performance.now
event adds its qT exactly once; a new server timestamp adds qS if applicable. Include the drift
bound from reference to event exactly once. The **complete new-event conversion** must meet
the unchanged T3 ceiling **500 µs**; constant calibration does not erase an unproved bound.
T3 remains unverified. Video display and audio emission constants still require physical
calibration and recapture on playback-code/runtime/output-device changes.

---

## 3. The "displayed pixels" objection — addressed honestly

Plan Task 6 Step 1 bans substitutes: *"Internal consumer callbacks, `image.onload`, DOM-reported PTS,
and HTTP arrival timestamps are not substitutes for this capture."* Two questions:

1. **Authorization.** Task 6 Step 6 orders *this* design on measured failure. Adopting it is the
   documented escalation path, not a quiet substitution.

2. **In-band timestamps never observe photons** — and **P1a sits closer to the banned category
   than rVFC did**, which this design states rather than hides: an rAF anchor is a page-side
   scheduling observation, not a compositor-present API. The gap is closed by the same deliberate
   split, with the external check doing *more* of the work:

   * **Per-pair precision must be established by the channel** (bounded event anchors,
     timestamp conversion and audio query cadence), and
   * **correctness of the constants comes from one coarse external measurement**: a single phone
     recording (target ≥ 240 fps, one device framing screen + audible output at marker instants)
     measures `photon_time − channel_video_estimate` and `audible_time − channel_audio_estimate`
     directly (half-frame quantization ±2,083 µs → constants; a bracketing repeat bounds drift).
     It does **not** measure per-pair jitter (4,167 µs frames cannot) and does not claim to.
   * **What remains unobservable in-band** on P1a — paint-race/frame-slip and DWM scheduling —
     is bounded by *measurement + rule*: Phase A statistics on the paint chain, plus any
     slip the instrument can flag; unexplained slips flagged in raw capture make the run
     `unverified`. **Until Phase A measures it, this is the binding uncertainty (§4, T1).**
   * P1b exists precisely because P1a's residual may prove too large: it restores a spec'd
     compositor-present API (`expectedDisplayTime`) in exchange for a product change (§1.1B).

---

## 4. Uncertainty budget (allocations preserved, current status corrected)

Budget: `uncertainty_us ≤ 8,333` (`uncertainty_us * 4 * num ≤ 1_000_000 * den`), 30 fps, one
30 s run. Terms with no spec/measurement backing are marked **NEEDS-SPIKE** and excluded from the
"allocated" subtotal; they draw from a stated pool.

| # | term | worst-case (µs) | basis / status |
|---|---|---|---|
| **T1** | **Video paint-commit/present jitter (P1a)**: decode→rAF→actual-present residual after the calibrated constant; frame-slip under load; DWM scheduling. Cited worst = **one measured hardware refresh (~6.1–7.7 ms at 130–165 Hz)** for an undetected slip | **NEEDS-SPIKE** | No API observes `<img>` presentation; Phase A measures the paint chain vs headroom; external spot-check validates the constant. (P1b would replace this with rVFC `expectedDisplayTime`, pending its own measured bound) |
| **T2** | **Audio write→hardware delivery jitter** (device-position estimate vs actual emission after the beacon constant): SDL queue-step→dsound play-cursor holding variation, driver scheduling. Cited worst = **one device mix period** (unknown until probed; SDL default period would be 85,333 µs @ 48 kHz — would be RED) | **NEEDS-SPIKE** | SDL2 guarantees only byte counts, not step cadence or emission correlation (§1.2); Phase A probes queued-accounting fidelity and, if needed, the DirectSound play-cursor candidate |
| T3 | Complete page→server new-event conversion: expanded endpoint-error intervals, drift and new-event quantization (§2) | ≤ 500 ceiling | **UNVERIFIED**; previous fetch bound ±799.6 µs; runtime clock/clamp provenance pending |
| T4 | Audio pulse **write-instant detection**: device-position query cadence | ≤ 500 ceiling | **NOT ACHIEVED**; historical critical gaps 2.66/2.89 ms; 10 ms steps/interpolation do not prove emission |
| T5 | One-time constant calibration residual: video external 240 fps half-frame 2,083 + audio loopback/mic beacon onset ±500 | 2,583 | instrument quantization (phone frame period; 48 kHz WAV onset) |
| T6 | Marker/pulse identity quantization: server frame PTS (`X-Project-PTS-US`, exact µs; P1b: fMP4 `mediaTime`) and `first_frame_at_or_after` integer arithmetic on sample offsets | 0 | exact by construction (FrameRate integer arithmetic) |
| | **Known subtotal T3–T6** | **3,583** | |
| | **Budget** | **8,333** | |
| | **Spike pool shared by T1 + T2** | **4,750** | split decided by measured values; the gate needs the *sum* |

**Current verdict: the total uncertainty is unverified.** The unchanged bookkeeping subtotal
T3–T6 is **3,583 µs**, with **4,750 µs** reserved for T1+T2 against the **8,333 µs** budget.
This is an allocation, not an achieved measurement: T3 is unverified and T4's cadence ceiling
has not been achieved. The observed panel range is **130–165 Hz (~6.1–7.7 ms per refresh)**,
specific to this hardware and derived from page observation, **not external-camera evidence**.
T1 actual present jitter and T2 physical emission still need proof. Their measured sum must fit
4,750 µs while all other ceilings hold. No arithmetic, ceiling or pool has been relaxed.
Failure remains `unverified`; P1b requires separate authorization.

Cross-check of the per-pair gate (unchanged arithmetic): at `uncertainty_us = 8,333` the plan
requires `|video_capture_us − audio_capture_us| ≤ 25,000 µs` per pair at 30 fps. The gate must use the run's measured complete uncertainty. Historical
92,043 µs worst residual remains failed evidence; the replacement instrument has not yet
proved that its own error terms close.

---

## 5. Event schema — plan contract preserved exactly

`temp/mlt-av-evidence.json` keeps the plan's fields and the **unchanged** validator arithmetic
(`test_mlt_acceptance.validate_av_evidence`; the validator is not modified):

```json
{
  "frame_rate": {
    "num": 30,
    "den": 1
  },
  "runtime": "mlt:<runtime id> | browser: chrome/<ver> | os: windows <ver> | device: <output device>",
  "capture_method": "timestamped-channel-v1",
  "raw_capture": "temp/timestamped-channel/",
  "uncertainty_us": 7950,
  "runs": [
    {
      "mode": "normal",
      "duration_us": 30000000,
      "dropped_frames": 0,
      "events": [
        {
          "project_frame": 30,
          "video_capture_us": 8116450200,
          "audio_capture_us": 8116407700
        },
        {
          "project_frame": 60,
          "video_capture_us": 8117450900,
          "audio_capture_us": 8117407600
        }
      ]
    },
    {
      "mode": "dropped_video",
      "duration_us": 30000000,
      "dropped_frames": 1,
      "drops": [
        61
      ],
      "events": [
        {
          "project_frame": 60,
          "video_capture_us": 8117450900,
          "audio_capture_us": 8117407600
        }
      ]
    }
  ]
}
```

**This fragment illustrates field shapes only and is not valid full evidence.** Full evidence
requires both `normal` and `dropped_video`, each ≥30 s and exactly 29 events,
with dropped-video `dropped_frames >= 1` and `drops: [project_frame, ...]`, including a drop
within one frame of a marker. Every event has **exactly** three integer keys:
`project_frame`, `video_capture_us`, `audio_capture_us`; diagnostics stay in raw logs.

(29 events per run, `k = 1..29`, `project_frame = rate.first_frame_at_or_after(k * 1_000_000)`
(= 30k at 30 fps); `uncertainty_us` = the measured §4 sum; examples illustrative.)

* `capture_method` = **"timestamped-channel-v1"** (kept).
* `video_capture_us` / `audio_capture_us`: integer µs **on the server capture clock** after the
  two documented constants (`video_display_constant`, with the bounded clock conversion in §2;
  `emission holding`); raw pre-constant values + constants live in `raw_capture` —
  "documented capture-skew correction".
* `raw_capture` directory (under `temp/`, per plan): handshake record (offset, RTT, server clock
  source); video frame-arrival log (PTS sequence received) **and** paint-anchor log (PTS → rAF
  timestamps); server audio log (device-position queries, step instants, derived write times);
  both calibration records; probe artifacts from Phase A consumed by the run; device/backend/
  browser provenance; frame/drop schedule; anomaly counters; external spot-check artifacts.
* **Dropped-video mode, honest identity (P1a):** identity comes from the frame's server PTS
  (`X-Project-PTS-US`), which travels with the image — no float timeline involved. For marker
  *k*, `video_capture_us` = paint anchor of the first *painted* part with PTS ≥ `k·1e6`; identity
  holds iff that PTS < `(k+1)·1e6` (one-second held marker windows: a skipped part inside the
  window cannot falsify identity — same argument as rev.1). Whole-window loss ⇒ marker missing ⇒
  **run fails** per plan. `dropped_frames` = missing PTS slots in the expected 30 fps
  cadence, split into *not received* vs *received but not painted* (both logs exist), recorded
  in run-level `drops` and separate raw diagnostics; no extra event keys are accepted. (Under
  P1b this reverts to the rev.1 `presentedFrames`/`mediaTime` accounting, which MDN explicitly
  endorses for missed-frame detection.)
* `max_presented_av_delta_frames` (Task 6 playback metric) is derived by the acceptance script from these
  events including uncertainty; recorded separately, not an evidence-JSON field.

---

## 6. Validation experiment — channel vs. old instrument (before the channel replaces anything)

Unchanged in structure from rev.1 (coordinator retained it):

**Setup:** one calibration playback with **both instruments live** — the old instrument
(burst-gated PrintWindow + loopback WAV + flash/beep bridge, `pilot_run.py` as validated in
`opt1`) observes the same run; the channel records in-band. The old instrument's load affects the
*playback*; both instruments observe the same playback.

**Comparison:** per pair *k*, `Δ_old(k)` (old skew-corrected video−audio) vs `Δ_ch(k)` (channel,
constants applied). Fit `c = median_k(Δ_old(k) − Δ_ch(k))`.

**Pass criteria:**

1. `|Δ_old(k) − Δ_ch(k) − c| ≤ 9,394 µs` for ≥ 27 of 29 pairs (the old instrument's own best
   measured total projection, `reassessment.md` — agreement cannot be demanded tighter than the
   comparator's resolution; any violation disclosed pair-by-pair).
2. `c` stable across two side-by-side runs within 2,067 µs (old bridge's best robust residual).
3. Channel-internal: after removing its own constant, `max |Δ_ch(k) − median| ≤ 8,333 µs`, zero
   anomaly flags, 29/29 pairs in short probes.
4. External spot-check (≥ 1 marker instant, screen + audio in one ≥ 240 fps phone shot):
   `|measured pair delta − channel pair delta| ≤ 4,167 + 2×2,083 µs`.

**Fail:** criteria 1/2 violated after re-checking calibrations → stop, diagnose; **no Phase C**.

**Stated limit:** side-by-side validates agreement at the old instrument's noise floor
(±9,394 µs) and constant stability — not precision below that. Precision rests on the
spike-validated §4 terms and is finally certified only by the gate run with `uncertainty_us`
reported at face value.

---

## 7. Phased plan

**Phase A — spike (effort: hours, 3–6 h hands-on; temp-only, no tracked-file changes).**
Order is prescribed: **P1a first (it is free), audio second.**

* **A1 — P1a paint-chain measurement (first):** page probe on the acceptance head: stream parts →
  decode → swap → rAF anchor; ≥ 900 frames; report anchor-to-anchor distribution vs refresh
  period (p50/p95/max), slip/race frequency, main-thread-load sensitivity; feasibility test of
  slip *detection* rules. Go/no-go: **can T1 be bounded ≤ the agreed share of 4,750 µs?**
  Optional same-session 10 s phone shot (240 fps) to confirm the constant measurement path and
  size the external instrument.
* **A2 — audio device-position probe:** against the MLT runtime's SDL sink: consumer's open
  parameters (mix period), `SDL_GetQueuedAudioSize` step cadence under a ≤500 µs server poll,
  write-instant detection quality at marker instants, **write→emission delivery jitter** (vs a
  loopback beacon recording); if queued-accounting jitter exceeds headroom → prototype the
  DirectSound play-cursor query. Go/no-go: **can T2 be bounded ≤ the agreed share of 4,750 µs?**
* **A3 — clock provenance:** validate installed server/browser clock and clamp implementation;
  expand endpoint errors before interval intersection, include drift and new-event quantization
  once, and bound complete conversion against the existing 500 µs ceiling (§2). RTT/2 medians
  alone cannot pass. No new T3 capture has been performed.
* Deliverable: `temp/design/phase-a-spike.md` with measured values into the §4 table and a
  **combined go/no-go: T1 + T2 ≤ 4,750 or not**. If A1 fails → P1b proposal to the coordinator
  (§1.1B, 2–4 sessions, product-change approval required) before any implementation.

**Phase B — implement + calibrate + external spot-check + side-by-side (effort: 1–3 sessions,
~2–3 working days).**
* Hour 0 preconditions: **B1** (display cadence of the acceptance head ≥ 30 fps stream-consumed
  parts — consumer exists, but candidate 204e731 is 29.999238216104732fps<30;
  hold remains), sink-clause adoption already granted (§9), P1a/P1b decision
  from Phase A.
* Channel work: existing page stream reader + proposed paint anchors + read-out over CDP; server audio
  timestamp hook (position query + write-instant log); calibration scripts (audio beacon,
  display constant); bracketing external spot-checks.
* Run §6 side-by-side twice; write the comparison analysis. **Only on PASS does Phase C start.**

**Phase B′ — P1b (contingency, designed not built):** only if A1 fails *and* the coordinator
approves the product change: MSE/h264 stream endpoint + `<video>` display swap + rVFC hookup
(§1.1B, 2–4 sessions), then re-enter Phase B with rVFC-based T1.

**Phase C — full both-modes run → evidence → unchanged gate (effort: 1–3 sessions, 1–2 days +
re-runs).**
* `normal` and `dropped_video`, each ≥ 30 s, exactly 29 marker/pulse pairs; drop injection =
  documented CPU-contention bursts during play (`research.md` §6: no drop-injection hook exists);
  must observe actual drops incl. near markers, else iterate injection and re-run.
* Emit `temp/mlt-av-evidence.json` (§5), run
  `py -3.14 -m jypreview.tools.test_mlt_acceptance --av-evidence temp/mlt-av-evidence.json`
  with **unchanged** validator arithmetic; then the coordinator decides on Task 7. Keep old
  files until the gate passes; recapture on playback-code / native-runtime / output-device
  change (Task 6 Step 6).

---

## 8. Risks and open questions

1. **Two spike terms may not close (§4).** T1 (P1a paint jitter) *or* T2 (audio delivery jitter)
   exceeding the 4,750 pool ⇒ `unverified`, escalation back to the coordinator. T1's known
   fallback is P1b (approval needed); T2's is the DirectSound play-cursor probe; if both fail,
   the design honestly reports failure rather than a friendlier number.
2. **B1 — display cadence:** the normal application consumes the native stream, but the
   final exact 204e731 page measurement is 29.999238216104732fps<30. No observed source gaps
   does not change this strict condition. Phase B remains on hold.
3. **Release/candidate provenance:** main release is f0ef7da (Task1/1b); Task2 production
   is 204e731 candidate, with subsequent test-only 25ebffa. Runtime/device/fixture/source
   evidence must remain tied to each original commit; never transfer candidate measurements
   silently to release.

4. **SDL2/dsound fidelity** (§1.2): byte counts are guaranteed, timing fidelity is not; period
   defaults can be pathologically large; driver-side delivery jitter is unmeasured. Fail-closed
   on unavailable/zero position data.
5. **rAF-anchor semantics under load:** P1a depends on the paint chain staying timely; Phase A
   must test at realistic page load, and raw capture must retain anomaly counters so a slipped
   frame is disclosed, not averaged away.
6. **Audio-sink scope (resolved):** Task 6 Step 1's "local MLT audio sink" is adopted — measured audio
   *is* the product sink now (rev.1's deviation is gone). Residual scope note: the browser's own
   legacy `<audio>` scheduler (`media.js`) is not exercised by the acceptance — same as plan.
7. **Dropped-mode:** full-second marker freeze = planned failure; drop injection must produce
   skips near markers without total stalls; near-marker drops are the hard case.
8. **Hardware acceleration / display topology:** GPU vs software compositing, VRR, multi-monitor,
   refresh changes alter the present path → constants invalidated → recalibrate; disclose
   topology in `raw_capture` (Task 6 Step 6 triggers cover this).
9. **Side-by-side floor:** agreement beyond the old instrument's 9,394 µs is not demonstrable —
   do not claim more.

---

## 9. Provenance

**Plan clauses this extends/supersedes (quoted):**

* Task 6 Step 1 (capture clause): *"Capture the displayed browser pixels and actual
  audio output on one capture clock, using synchronized screen/audio-output recording with
  measured capture latency/skew, or an external recording of the screen and audible output.
  Internal consumer callbacks, `image.onload`, DOM-reported PTS, and HTTP arrival timestamps are
  not substitutes for this capture."* — extended by this design (instrument = presentation-
  boundary timestamps + one-time external constant check; §3 addresses the ban list and P1a's
  proximity to it honestly). *"Run it through the normal browser URL and local MLT audio sink"* —
  **adopted as-is in rev.2** (audio stays the MLT sink; rev.1's page-audio deviation withdrawn).
* Task 6 Step 6 (fallback, authorization): *"If measured playback fails, stop and write a
  follow-up design for one timestamped browser A/V channel. Keep the old files until this gate
  passes; recapture if playback code, native runtime, or output device changes."* — this
  document is that design; keep-old-files and recapture rules remain in force.

**Gate arithmetic: unchanged.** Same evidence JSON, same `uncertainty_us ≤ 1/4 project frame`,
same per-pair `(abs(video−audio) + uncertainty_us) * num <= 1_000_000 * den`, same 29-pair /
both-modes / ≥30 s requirements.

**Current source/evidence check: 2026-10-03.** Stable symbols were checked in the
index-free 024e checkout (current 25ebffa; zero production delta from 204e731 for the cited paths):
`web/app.js` nativeFrame/renderMltAt/mlt.startStream; `web/backend.js`
MltPlaybackClient.#startStream; `server/handlers_backend.py` _frame_headers/_encode_jpeg/
stream; `mlt_backend.py` PlaybackController._pull_stream_frame and _frame_ready;
`tools/test_mlt_acceptance.py` validate_av_evidence. All paths are under `scripts/jypreview/`.
Source line numbers from rev.2 are removed; the older main CodeGraph index is not candidate proof.
Release f0ef7da contains reviewed seek/ownership work; candidate 204e731 adds the 3-lane,
JPEG q85 and Event readiness changes. P1b MSE/rVFC remains unauthorized.

The runtime helper at `temp/superpowers/sdd/2026-10-03-playback-remaining/task-1-live/runtime.ps1`
uses editor stub `C:/Users/cbsjz/.codex/worktrees/integration-preview/jianying-preview/temp/mlt-capture/editor-stub`.
That fixture stub cannot decrypt the supplied real encrypted project.

**2026-10-03 handoff:** `docs/native-backend-evaluation/2026-10-03-playback-remaining-status.md`
records exact candidate evidence, retained failures and external/decryption blockers.
Original user decision date is 2026-10-02; this correction authorizes documentation only.

**Evidence trail (what this design is built on):**
`temp/capture-rea/reassessment.md` — WASAPI→dsound fix recovered punctuality 0.7056× →
0.982–0.993×; pair-jitter MAD 78.5 → 39.6 → 18.4 ms (opt1); PrintWindow p95 10.8–12.1 ms;
marker quant best 5,827 µs; bridge residual best 2,067 µs; projection best **9,394 µs > 8,333**
(AMBER-over, then RED); burst gate 3/10 unbracketed; verdict RED, escalation = this design.
`temp/mlt-capture/research.md` — uncertainty decomposition (quant / audio allowance / skew
residual), calibration flash/beep pair method, +251 ms presentation constant, per-pair jitter
78.5 ms MAD ≈ 9.4× budget → RED, "the plan's fallback … is the path".

**UNVERIFIED until Phase C passes:** the Task 6 cutover gate itself
(`test_mlt_acceptance --av-evidence temp/mlt-av-evidence.json` with both modes green); **every
spike-measured term — T1 and T2 above all** (their sum must fit 4,750 µs); T3's complete conversion bound and runtime provenance; T4's query cadence; precondition B1 (display cadence on the acceptance head); P1a-vs-P1b outcome;
drop-injection sufficiency for `dropped_video`; the external spot-check constants.
**Task 7 deletion remains blocked until the unchanged gate passes on this channel's evidence.**
