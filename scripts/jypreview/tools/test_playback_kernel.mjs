import assert from "node:assert/strict";
import { MltPlaybackClient } from "../web/backend.js";
import { EffectRenderer, animationStateAt } from "../web/effects.js";
import { AudioScheduler, audioSourceTimeAt } from "../web/media.js";
import { LoadingController } from "../web/loading.js";

// -- helpers -----------------------------------------------------------------

const encoder = new TextEncoder();

function installFetch(handler) {
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    const call = { url: String(url), init, method: (init.method || "GET").toUpperCase() };
    calls.push(call);
    return handler(call);
  };
  return calls;
}

function json(payload, { status = 200, headers = {} } = {}) {
  return new Response(JSON.stringify(payload), {
    status, headers: { "content-type": "application/json", ...headers },
  });
}

function ok(data, options = {}) {
  return json({ ok: true, code: "ok", reason: "", data }, options);
}

function seekHeaders({ playbackId, generation, requestId, frameIndex, ptsUs }) {
  return {
    "X-Playback-ID": playbackId,
    "X-Playback-Generation": String(generation),
    "X-Seek-Request-ID": String(requestId),
    "X-Project-Frame": String(frameIndex),
    "X-Project-PTS-US": String(ptsUs),
  };
}

function queryOf(call) {
  return new URL(call.url, "http://local").searchParams;
}

/** One synthetic multipart frame carrying every Task 4 identity/frame header. */
function multipartFrame(boundary, { playbackId, generation, requestId, frameIndex, ptsUs, payload }) {
  const head = [
    `--${boundary}`,
    "Content-Type: image/png",
    `Content-Length: ${payload.length}`,
    `X-Playback-ID: ${playbackId}`,
    `X-Playback-Generation: ${generation}`,
    `X-Seek-Request-ID: ${requestId}`,
    `X-Project-Frame: ${frameIndex}`,
    `X-Project-PTS-US: ${ptsUs}`,
    "", "",
  ].join("\r\n");
  const bytes = new Uint8Array(head.length + payload.length + 2);
  bytes.set(encoder.encode(head));
  bytes.set(payload, head.length);
  bytes[head.length + payload.length] = 13;    // trailing CRLF before the next boundary
  bytes[head.length + payload.length + 1] = 10;
  return bytes;
}

function parts(...chunks) {
  const total = chunks.reduce((sum, chunk) => sum + chunk.length, 0);
  const out = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) { out.set(chunk, offset); offset += chunk.length; }
  return out;
}

function deferred() {
  let resolve;
  const promise = new Promise((r) => { resolve = r; });
  return { promise, resolve };
}

const tick = () => new Promise((resolve) => setTimeout(resolve, 10));

function push(controller, bytes) {
  try { controller.enqueue(bytes); } catch (error) { void error; }
}

async function openClient({ playbackId, generation = 0 } = {}) {
  installFetch((call) => {
    if (call.url.includes("/api/backend/open")) {
      return ok({ playback_id: playbackId }, {
        headers: { "X-Playback-ID": playbackId, "X-Playback-Generation": String(generation) },
      });
    }
    if (call.url.includes("/api/backend/close")) return ok({ closed: true });
    throw new Error(`unexpected fetch: ${call.url}`);
  });
  const client = new MltPlaybackClient();
  const opened = await client.open("draft-x", "timeline-1");
  assert.equal(opened.stale, false, "a fresh open must apply");
  assert.equal(client.playbackId, playbackId);
  return client;
}

/** open + one accepted seek, so identity generation/request id are nonzero. */
async function openSeekingClient({ playbackId }) {
  const client = await openClient({ playbackId });
  installFetch((call) => {
    if (call.url.includes("/api/backend/seek")) {
      const rid = Number(queryOf(call).get("request_id"));
      return new Response(null, { status: 200, headers: seekHeaders({
        playbackId, generation: rid, requestId: rid, frameIndex: rid * 300, ptsUs: rid * 100_000,
      }) });
    }
    if (call.url.includes("/api/backend/close")) return ok({ closed: true });
    throw new Error(`unexpected fetch: ${call.url}`);
  });
  await client.seek(100_000);
  assert.equal(client.generation, 1);
  assert.equal(client.accepted, 1);
  return client;
}

// -- tests -------------------------------------------------------------------

async function multipartParsing() {
  const boundary = "frame";
  const payload = Uint8Array.from([137, 80, 78, 71, 13, 10, 26, 10, 1, 2, 3]);
  let stream = null;
  let streamController = null;
  let signal = null;
  let cancelled = false;
  const frames = [];
  let streamError = null;

  const client = await openSeekingClient({ playbackId: "pb-1" });
  installFetch((call) => {
    if (call.url.includes("/api/backend/stream")) {
      signal = call.init.signal;
      stream = new ReadableStream({
        start(controller) { streamController = controller; },
        cancel() { cancelled = true; },
      });
      return new Response(stream, {
        status: 200,
        headers: { "content-type": `multipart/x-mixed-replace; boundary=${boundary}` },
      });
    }
    if (call.url.includes("/api/backend/close")) return ok({ closed: true });
    throw new Error(`unexpected fetch: ${call.url}`);
  });

  client.startStream((frame) => { frames.push(frame); },
    (error) => { streamError = error; });
  assert.ok(stream, "startStream must request the multipart stream");

  const valid = multipartFrame(boundary, {
    playbackId: "pb-1", generation: 1, requestId: 1, frameIndex: 7, ptsUs: 100_000, payload,
  });
  const stalePlayback = multipartFrame(boundary, {
    playbackId: "pb-0", generation: 1, requestId: 1, frameIndex: 6, ptsUs: 66_666, payload,
  });
  const staleGeneration = multipartFrame(boundary, {
    playbackId: "pb-1", generation: 0, requestId: 1, frameIndex: 5, ptsUs: 55_555, payload,
  });
  const all = parts(valid, stalePlayback, staleGeneration);

  // Split mid-header and mid-payload: parsing must be incremental across chunks.
  push(streamController, all.slice(0, 40));
  await tick();
  assert.equal(frames.length, 0, "a partial frame must not be delivered");
  push(streamController, all.slice(40, valid.length - 5));
  await tick();
  assert.equal(frames.length, 0, "a frame with an incomplete body must not be delivered");
  push(streamController, all.slice(valid.length - 5));
  await tick();

  assert.equal(frames.length, 1, "only the current-identity frame is delivered");
  assert.deepEqual({
    playbackId: frames[0].playbackId,
    seekRequestId: frames[0].seekRequestId,
    generation: frames[0].generation,
    frameIndex: frames[0].frameIndex,
    ptsUs: frames[0].ptsUs,
  }, { playbackId: "pb-1", seekRequestId: 1, generation: 1, frameIndex: 7, ptsUs: 100_000 });
  assert.equal(frames[0].blob.size, payload.length, "the body must survive header parsing");
  assert.deepEqual([...new Uint8Array(await frames[0].blob.arrayBuffer())], [...payload]);
  assert.equal(streamError, null, "the stream must not report errors while healthy");

  await client.close();
  assert.equal(signal.aborted, true, "close() must abort the stream request");
  assert.equal(client.playbackId, null);
  await tick();
  assert.equal(cancelled, true, "close() must abort the reader");

  push(streamController, staleGeneration);
  await tick();
  assert.equal(frames.length, 1, "no frames may be delivered after close()");
}

async function reorderedDispatch() {
  const client = await openClient({ playbackId: "pb-2" });
  const pending = new Map();
  const calls = installFetch((call) => {
    if (call.url.includes("/api/backend/seek")) {
      const rid = Number(queryOf(call).get("request_id"));
      if (!pending.has(rid)) pending.set(rid, deferred());
      return pending.get(rid).promise.then(() => new Response(null, {
        status: 200,
        headers: seekHeaders({ playbackId: "pb-2", generation: rid, requestId: rid,
          frameIndex: rid * 300, ptsUs: rid * 10_000_000 }),
      }));
    }
    if (call.url.includes("/api/backend/close")) return ok({ closed: true });
    throw new Error(`unexpected fetch: ${call.url}`);
  });

  const first = client.seek(10_000_000);
  const second = client.seek(20_000_000);
  const third = client.seek(30_000_000);

  // Request IDs are allocated at issue time, before any HTTP resolves.
  const seen = calls.filter((call) => call.url.includes("/api/backend/seek")).map(queryOf);
  assert.deepEqual(seen.map((query) => query.get("request_id")), ["1", "2", "3"]);
  assert.deepEqual(seen.map((query) => query.get("t_us")), ["10000000", "20000000", "30000000"]);
  assert.ok(seen.every((query) => query.get("draft") === "draft-x"
      && query.get("timeline") === "timeline-1"),
  "post-open handle requests must carry the draft and timeline selectors");
  assert.equal(client.issued, 3);

  // Responses arrive in the order 3, 1, 2.
  pending.get(3).resolve();
  const r3 = await third;
  assert.equal(r3.applied, true, "the latest issued intent must be applied");
  assert.equal(client.tUs, 30_000_000);
  assert.equal(client.generation, 3);

  pending.get(1).resolve();
  const r1 = await first;
  assert.equal(r1.superseded, true, "a response predating the latest issued intent is rejected");
  pending.get(2).resolve();
  const r2 = await second;
  assert.equal(r2.superseded, true);

  assert.equal(client.tUs, 30_000_000, "stale responses must not move the playhead");
  assert.equal(client.generation, 3, "stale responses must not move the generation");
  assert.equal(client.issued, 3);
  assert.equal(client.accepted, 3);

  // Snapshots settle on the last issued request: older ones are ignored.
  let snapshotCalls = 0;
  installFetch((call) => {
    if (call.url.includes("/api/backend/snapshot")) {
      snapshotCalls += 1;
      if (snapshotCalls === 1) {
        return ok({ backend: "mlt", phase: "paused", playback_id: "pb-2", seek_request_id: 1,
          generation: 1, frame_index: 300, t_us: 10_000_000, duration_us: 64_000_000,
          playing: false, error: null, open: true });
      }
      if (snapshotCalls === 2) {
        return ok({ backend: "mlt", phase: "playing", playback_id: "pb-2", seek_request_id: 3,
          generation: 3, frame_index: 900, t_us: 30_000_000, duration_us: 64_000_000,
          playing: true, error: null, open: true });
      }
      // In order (rid 3) but with an older PTS: frameIndex must ride the same
      // monotonic gate as tUs instead of moving backwards alone.
      return ok({ backend: "mlt", phase: "paused", playback_id: "pb-2", seek_request_id: 3,
        generation: 3, frame_index: 100, t_us: 5_000_000, duration_us: 64_000_000,
        playing: false, error: null, open: true });
    }
    if (call.url.includes("/api/backend/close")) return ok({ closed: true });
    throw new Error(`unexpected fetch: ${call.url}`);
  });
  const stale = await client.snapshot();
  assert.equal(stale.applied, false, "an older snapshot must be ignored after issued 3");
  assert.equal(client.tUs, 30_000_000);
  const fresh = await client.snapshot();
  assert.equal(fresh.applied, true);
  assert.equal(client.playing, true);
  assert.equal(client.frameIndex, 900);

  const rewound = await client.snapshot();
  assert.equal(rewound.applied, true, "an in-order snapshot still applies");
  assert.equal(client.tUs, 30_000_000, "an older PTS must not rewind the clock");
  assert.equal(client.frameIndex, 900,
    "an older PTS must not move frameIndex backwards while the clock stays");
}

async function lateDecodeAfterNewerSeek() {
  const client = await openClient({ playbackId: "pb-3" });
  const seeks = new Map();
  const renders = new Map();
  const calls = installFetch((call) => {
    const url = new URL(call.url, "http://local");
    if (call.url.includes("/api/backend/seek")) {
      const rid = Number(url.searchParams.get("request_id"));
      if (!seeks.has(rid)) seeks.set(rid, deferred());
      return seeks.get(rid).promise.then(() => new Response(null, { status: 200, headers: seekHeaders({
        playbackId: "pb-3", generation: rid, requestId: rid,
        frameIndex: rid * 300, ptsUs: rid * 10_000_000,
      }) }));
    }
    if (call.url.includes("/api/backend/render")) {
      const rid = Number(url.searchParams.get("request_id"));
      if (!renders.has(rid)) renders.set(rid, deferred());
      return renders.get(rid).promise.then((bytes) => new Response(bytes, {
        status: 200, headers: { "content-type": "image/png", ...seekHeaders({
          playbackId: "pb-3", generation: rid, requestId: rid,
          frameIndex: rid * 300, ptsUs: rid * 10_000_000,
        }) },
      }));
    }
    if (call.url.includes("/api/backend/close")) return ok({ closed: true });
    throw new Error(`unexpected fetch: ${call.url}`);
  });

  const oldSeek = client.renderAt(10_000_000);
  assert.ok(seeks.has(1), "renderAt must dispatch one seek with its request id");
  seeks.get(1).resolve();
  await tick();
  assert.ok(renders.has(1), "/render waits for the seek acknowledgment");
  renders.get(1).resolve(Uint8Array.from([1, 2, 3]));
  const firstFrame = await oldSeek;
  assert.equal(firstFrame.applied, true);
  assert.equal(firstFrame.seekRequestId, 1);
  assert.equal(firstFrame.generation, 1);
  assert.equal(firstFrame.frameIndex, 300);
  assert.equal(firstFrame.ptsUs, 10_000_000);
  assert.equal(firstFrame.blob.size, 3);

  const newSeek = client.renderAt(20_000_000);
  assert.ok(seeks.has(2));
  seeks.get(2).resolve();
  await tick();
  renders.get(2).resolve(Uint8Array.from([4, 5, 6]));
  const secondFrame = await newSeek;
  assert.equal(secondFrame.applied, true);
  assert.equal(secondFrame.seekRequestId, 2);
  assert.equal(client.tUs, 20_000_000);
  assert.equal(client.generation, 2);

  // The old image decode finishes after the newer seek: it must not update display.
  assert.equal(client.accepts(firstFrame), false, "a stale decode must be rejected");
  assert.equal(client.accepts(secondFrame), true);
  let shown = null;
  const settle = (frame) => { if (client.accepts(frame)) shown = frame; };
  settle(secondFrame);
  settle(firstFrame);
  assert.equal(shown, secondFrame, "only the last issued intent may update display");

  // renderAt = one ordered seek then /render with the same request id, no second seek.
  const seekCalls = calls.filter((call) => call.url.includes("/api/backend/seek"));
  const renderCalls = calls.filter((call) => call.url.includes("/api/backend/render"));
  assert.equal(seekCalls.length, 2, "renderAt must not issue a second seek");
  assert.equal(renderCalls.length, 2);
  assert.deepEqual(seekCalls.map((call) => queryOf(call).get("request_id")), ["1", "2"]);
  assert.deepEqual(renderCalls.map((call) => queryOf(call).get("request_id")), ["1", "2"]);
}

async function renderResponses() {
  const client = await openClient({ playbackId: "pb-4" });
  let mode = "superseded";
  installFetch((call) => {
    if (call.url.includes("/api/backend/seek")) {
      const rid = Number(queryOf(call).get("request_id"));
      return new Response(null, { status: 200, headers: seekHeaders({
        playbackId: "pb-4", generation: rid, requestId: rid,
        frameIndex: rid * 300, ptsUs: rid * 10_000_000,
      }) });
    }
    if (call.url.includes("/api/backend/render")) {
      const rid = Number(queryOf(call).get("request_id"));
      if (mode === "superseded") {
        return json({ ok: false, code: "render_superseded", reason: "identity moved on" },
          { status: 409 });
      }
      if (mode === "supersededEnded") {
        // An ended payload answering an older request id: transport must not mutate.
        return ok({ ended: true, phase: "ended" }, { headers: seekHeaders({
          playbackId: "pb-4", generation: 1, requestId: rid - 1, frameIndex: 300,
          ptsUs: 10_000_000,
        }) });
      }
      return ok({ ended: true, phase: "ended" }, { headers: seekHeaders({
        playbackId: "pb-4", generation: rid, requestId: rid, frameIndex: rid * 300,
        ptsUs: rid * 10_000_000,
      }) });
    }
    if (call.url.includes("/api/backend/close")) return ok({ closed: true });
    throw new Error(`unexpected fetch: ${call.url}`);
  });

  const superseded = await client.renderAt(10_000_000);
  assert.equal(superseded.superseded, true, "render 409 must be reported as superseded");
  assert.equal(superseded.blob, undefined);

  mode = "supersededEnded";
  const staleEnded = await client.renderAt(20_000_000);
  assert.equal(staleEnded.superseded, true,
    "an ended payload answering an older request id is superseded");
  assert.notEqual(client.phase, "ended",
    "a superseded ended response must not mutate the phase");

  mode = "ended";
  const ended = await client.renderAt(30_000_000);
  assert.equal(ended.ended, true, "an ended render must not be an error");
  assert.equal(client.phase, "ended");
}

async function selectionEpoch() {
  const firstOpen = deferred();
  let openCount = 0;
  const calls = installFetch((call) => {
    if (call.url.includes("/api/backend/open")) {
      openCount += 1;
      if (openCount === 1) {
        return firstOpen.promise.then(() => ok({
          playback_id: "pb-late", did: "draft-a", timeline: "timeline-a",
        }, { headers: { "X-Playback-ID": "pb-late" } }));
      }
      if (openCount === 2) {
        return ok({ playback_id: "pb-current" }, {
          headers: { "X-Playback-ID": "pb-current", "X-Playback-Generation": "0" },
        });
      }
      return ok({ playback_id: "pb-reopen" }, {
        headers: { "X-Playback-ID": "pb-reopen", "X-Playback-Generation": "0" },
      });
    }
    if (call.url.includes("/api/backend/close")) return ok({ closed: true });
    throw new Error(`unexpected fetch: ${call.url}`);
  });

  const client = new MltPlaybackClient();
  const late = client.open("draft-a", "timeline-a");
  const current = client.open("draft-b", "timeline-b");
  const currentResult = await current;
  assert.equal(currentResult.stale, false);
  assert.equal(client.playbackId, "pb-current");

  firstOpen.resolve();
  const lateResult = await late;
  assert.equal(lateResult.stale, true, "a late open must be ignored after a timeline switch");
  assert.equal(client.playbackId, "pb-current", "a late open must not overwrite the selection");
  assert.equal(client.accepts({ playbackId: "pb-late", seekRequestId: 5, generation: 5 }), false,
    "old identity cannot update the new selection");
  // The late open's echoed did/timeline must not overwrite the new selection.
  assert.equal(client.draft, "draft-b", "a stale open must not rewrite the draft selector");
  assert.equal(client.timeline, "timeline-b", "a stale open must not rewrite the timeline selector");

  // Re-open under yet another selection: the previous handle must be closed too.
  const reopened = await client.open("draft-c", "timeline-c");
  assert.equal(reopened.stale, false);

  // Close requests for discarded handles must carry ONLY playback_id. A merged
  // draft/timeline would resolve the NEW key server-side (404/409) and the OLD
  // handle's executor would leak; the selector-less URL forces the B1 exact-id path.
  const closeCalls = calls.filter((call) => call.url.includes("/api/backend/close"));
  const closed = closeCalls.map((call) => queryOf(call).get("playback_id"));
  assert.ok(closed.includes("pb-late"),
    "a superseded open must best-effort close the handle it leaked");
  assert.ok(closed.includes("pb-current"),
    "a re-open must best-effort close the previous handle");
  for (const call of closeCalls) {
    const query = queryOf(call);
    assert.equal(query.get("draft"), null,
      `close must not carry a draft selector (would resolve the wrong key): ${call.url}`);
    assert.equal(query.get("timeline"), null,
      `close must not carry a timeline selector (would resolve the wrong key): ${call.url}`);
  }
}

async function frameQueueCap() {
  const boundary = "frame";
  const client = await openSeekingClient({ playbackId: "pb-5" });
  let stream = null;
  let streamController = null;
  installFetch((call) => {
    if (call.url.includes("/api/backend/stream")) {
      stream = new ReadableStream({ start(controller) { streamController = controller; } });
      return new Response(stream, {
        status: 200,
        headers: { "content-type": `multipart/x-mixed-replace; boundary=${boundary}` },
      });
    }
    if (call.url.includes("/api/backend/close")) return ok({ closed: true });
    throw new Error(`unexpected fetch: ${call.url}`);
  });

  const gate = deferred();
  const delivered = [];
  client.startStream(async (frame) => {
    delivered.push(frame.frameIndex);
    if (frame.frameIndex === 10) await gate.promise;
  });

  const payload = Uint8Array.from([9]);
  push(streamController, parts(
    multipartFrame(boundary, { playbackId: "pb-5", generation: 1, requestId: 1,
      frameIndex: 10, ptsUs: 100_000, payload }),
    multipartFrame(boundary, { playbackId: "pb-5", generation: 1, requestId: 1,
      frameIndex: 20, ptsUs: 133_333, payload }),
    multipartFrame(boundary, { playbackId: "pb-5", generation: 1, requestId: 1,
      frameIndex: 30, ptsUs: 166_666, payload }),
    multipartFrame(boundary, { playbackId: "pb-5", generation: 1, requestId: 1,
      frameIndex: 40, ptsUs: 200_000, payload }),
  ));
  await tick();
  assert.deepEqual(delivered, [10], "delivery is serialized behind a slow consumer");
  gate.resolve();
  await tick();
  await tick();
  assert.deepEqual(delivered, [10, 30, 40],
    "at most two frames are kept; the oldest queued frame is dropped");
  await client.close();
}

/** A failed stream must not latch the transport off: the next accepted seek reissues it. */
async function streamFailureRecoversOnSeek() {
  const boundary = "frame";
  const client = await openSeekingClient({ playbackId: "pb-6" });
  let failing = true;
  let streamFetches = 0;
  let streamController = null;
  const errors = [];
  const delivered = [];
  installFetch((call) => {
    if (call.url.includes("/api/backend/stream")) {
      streamFetches += 1;
      if (failing) return new Response("nope", { status: 500 });
      const stream = new ReadableStream({ start(controller) { streamController = controller; } });
      return new Response(stream, {
        status: 200,
        headers: { "content-type": `multipart/x-mixed-replace; boundary=${boundary}` },
      });
    }
    if (call.url.includes("/api/backend/seek")) {
      const rid = Number(queryOf(call).get("request_id"));
      return new Response(null, { status: 200, headers: seekHeaders({
        playbackId: "pb-6", generation: rid, requestId: rid,
        frameIndex: rid * 300, ptsUs: rid * 100_000,
      }) });
    }
    if (call.url.includes("/api/backend/close")) return ok({ closed: true });
    throw new Error(`unexpected fetch: ${call.url}`);
  });

  client.startStream((frame) => { delivered.push(frame.ptsUs); },
    (error) => { errors.push(error); });
  await tick();
  assert.equal(streamFetches, 1, "startStream must issue the stream fetch");
  assert.equal(errors.length, 1, "an HTTP-failed stream must report the error");

  // The next accepted seek must re-arm the stream and reissue the fetch.
  failing = false;
  await client.seek(200_000);
  await tick();
  assert.equal(streamFetches, 2, "a seek after a stream failure must restart the stream");
  assert.ok(streamController, "the restarted stream must expose a readable body");

  push(streamController, multipartFrame(boundary, {
    playbackId: "pb-6", generation: 2, requestId: 2, frameIndex: 600, ptsUs: 200_000,
    payload: Uint8Array.from([7]),
  }));
  await tick();
  assert.deepEqual(delivered, [200_000], "the restarted stream must deliver frames again");
  assert.equal(errors.length, 1, "the recovery must not report new errors");
  await client.close();
}

/** The stream close is a failure only while playback was active, never at ended. */
async function streamCloseOnlyFailsWhileActive() {
  const boundary = "frame";
  const client = await openSeekingClient({ playbackId: "pb-7" });
  let phase = "ended";
  const controllers = [];
  const errors = [];
  installFetch((call) => {
    if (call.url.includes("/api/backend/snapshot")) {
      return ok({ backend: "mlt", phase, playback_id: "pb-7", seek_request_id: 1,
        generation: 1, frame_index: 300, t_us: 100_000, duration_us: 64_000_000,
        playing: phase === "playing", error: null, open: true });
    }
    if (call.url.includes("/api/backend/stream")) {
      const stream = new ReadableStream({ start(controller) { controllers.push(controller); } });
      return new Response(stream, {
        status: 200,
        headers: { "content-type": `multipart/x-mixed-replace; boundary=${boundary}` },
      });
    }
    if (call.url.includes("/api/backend/close")) return ok({ closed: true });
    throw new Error(`unexpected fetch: ${call.url}`);
  });

  const ended = await client.snapshot();
  assert.equal(ended.applied, true);
  assert.equal(client.phase, "ended");
  client.startStream(() => {}, (error) => { errors.push(error); });
  await tick();
  controllers[0].close();
  await tick();
  assert.equal(errors.length, 0, "a stream closing at ended is not a failure");

  phase = "playing";
  const playing = await client.snapshot();
  assert.equal(playing.applied, true);
  assert.equal(client.phase, "playing");
  client.startStream(() => {}, (error) => { errors.push(error); });
  await tick();
  controllers[1].close();
  await tick();
  assert.equal(errors.length, 1, "a stream closing while playback is active is a failure");
  await client.close();
}

async function main() {
  await multipartParsing();
  await reorderedDispatch();
  await lateDecodeAfterNewerSeek();
  await renderResponses();
  await selectionEpoch();
  await frameQueueCap();
  await streamFailureRecoversOnSeek();
  await streamCloseOnlyFailsWhileActive();

  {
    const layer = { animation: { start_us: 100_000, duration_us: 400_000,
      render_class: "approx", approx: { impl: "fade", from: 0, to: 1 } } };
    assert.equal(animationStateAt(layer, 50_000).opacity, 0);
    assert.ok(animationStateAt(layer, 300_000).opacity > 0);
    assert.equal(animationStateAt(layer, 600_000).opacity, 1);
    const node = { dataset: {}, style: {}, classList: { toggle() {} } };
    new EffectRenderer().render({ layer, root: node, kind: "text" },
      { local: 50_000 }, () => {});
    assert.equal(node.dataset.renderClass, "approx");
  }

  {
    const time = { target_start_us: 1_000_000, target_duration_us: 2_000_000,
      source_start_us: 500_000, source_duration_us: 2_000_000, speed: 1.5, reverse: false };
    assert.equal(audioSourceTimeAt(time, 2_000_000), 2_000_000);
    assert.equal(audioSourceTimeAt({ ...time, reverse: true }, 2_000_000), 1_000_000);
  }

  {
    const nodes = [];
    const scheduler = new AudioScheduler({ createNode: () => {
      const node = { readyState: 0, paused: true, currentTime: 0, dataset: {},
        play() { this.paused = false; return Promise.resolve(); },
        pause() { this.paused = true; }, remove() {}, addEventListener() {} };
      nodes.push(node);
      return node;
    } });
    const label = { segment_id: "a", volume: 0.5, muted: false,
      audio: { exists: true, served: "/a.m4a", target_start_us: 0,
        target_duration_us: 2_000_000, source_start_us: 0, source_duration_us: 2_000_000,
        speed: 1, reverse: false } };
    const status = scheduler.sync([label], 500_000, true, true);
    assert.equal(status.active, 1);
    assert.equal(status.buffering, 1, "audio readyState must be explicit buffering");
    assert.equal(nodes[0].currentTime, 0.5);
    const reverse = scheduler.sync([{ ...label, segment_id: "r",
      audio: { ...label.audio, reverse: true } }], 500_000, true, true);
    assert.equal(reverse.degraded[0].reason, "reverse_audio_unsupported");
    scheduler.sync([], 0, false, true);
    assert.equal(scheduler.nodes.size, 0, "leaving a range must release old audio nodes");
  }

  {
    const classes = new Set();
    const host = {
      hidden: true,
      classList: { toggle(name, value) { if (value) classes.add(name); else classes.delete(name); } },
      dataset: {},
      textContent: "",
      setAttribute(name, value) { this[name] = value; },
      removeAttribute(name) { delete this[name]; },
    };
    const loading = new LoadingController(host);
    const old = loading.begin("window", "正在读取窗口…", { generation: 1 });
    const newer = loading.begin("prefetch", "正在预取下一段…", { generation: 2 });
    assert.equal(loading.snapshot().kind, "prefetch");
    assert.equal(host.textContent, "正在预取下一段…");
    loading.end(old);
    assert.equal(loading.snapshot().kind, "prefetch", "stale load must not hide newer load");
    loading.end(newer);
    assert.equal(loading.snapshot().active, false);
    loading.fail("窗口加载失败");
    assert.equal(loading.snapshot().kind, "error");
    assert.equal(host.textContent, "窗口加载失败");
  }
}

await main();
console.log("ok: MLT playback client kernel regressions");
