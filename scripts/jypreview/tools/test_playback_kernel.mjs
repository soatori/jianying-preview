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
function multipartFrame(boundary, { playbackId, generation, requestId, frameIndex, ptsUs, payload, contentType = "image/png" }) {
  const head = [
    `--${boundary}`,
    `Content-Type: ${contentType}`,
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
    contentType: "image/jpeg",
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
  assert.equal(frames[0].blob.type, "image/jpeg", "the stream MIME must reach the image decoder");
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

async function backwardSeekUsesRenderedPts() {
  const client = await openClient({ playbackId: "pb-rewind" });
  let positionUs = 0;
  let generation = 0;
  installFetch((call) => {
    const params = queryOf(call);
    if (call.url.includes("/api/backend/seek")) {
      const requestId = Number(params.get("request_id"));
      generation = requestId;
      return ok({ phase: "seeking", playing: false, t_us: positionUs }, {
        headers: seekHeaders({ playbackId: "pb-rewind", generation, requestId,
          frameIndex: Math.floor(positionUs / 33_333), ptsUs: positionUs }),
      });
    }
    if (call.url.includes("/api/backend/render")) {
      const requestId = Number(params.get("request_id"));
      positionUs = Number(params.get("t_us"));
      return new Response(Uint8Array.of(1), { status: 200, headers: {
        "content-type": "image/png", ...seekHeaders({ playbackId: "pb-rewind", generation,
          requestId, frameIndex: Math.floor(positionUs / 33_333), ptsUs: positionUs }),
      } });
    }
    if (call.url.includes("/api/backend/close")) return ok({ closed: true });
    throw new Error(`unexpected fetch: ${call.url}`);
  });

  await client.renderAt(8_200_000);
  assert.equal(client.tUs, 8_200_000);
  const rewound = await client.renderAt(0);
  assert.equal(rewound.applied, true);
  assert.equal(rewound.ptsUs, 0);
  assert.equal(client.tUs, 0, "a seek acknowledgment must not block its backward rendered frame");
  await client.close();
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

async function seekCommitBarrier() {
  const client = await openClient({ playbackId: "pb-barrier" });
  client.tUs = 8_133_334;
  client.frameIndex = 244;
  const renders = new Map();
  const late = deferred();
  let snapshotMode = "buffering";
  let streamFetches = 0;
  const snapshot = (phase, ptsUs) => ok({ backend: "mlt", phase,
    playback_id: client.playbackId, seek_request_id: client.issued,
    generation: client.issued, frame_index: Math.floor(ptsUs * 30 / 1e6),
    t_us: ptsUs, duration_us: 45_000_000, playing: phase === "playing",
    error: null, open: true });
  installFetch((call) => {
    if (call.url.includes("/api/backend/seek")) return snapshot("seeking", 8_133_334);
    if (call.url.includes("/api/backend/render")) {
      const rid = Number(queryOf(call).get("request_id"));
      const reply = deferred();
      renders.set(rid, reply);
      return reply.promise;
    }
    if (call.url.includes("/api/backend/snapshot")) {
      if (snapshotMode === "late") return late.promise;
      return snapshot(snapshotMode, snapshotMode === "buffering" ? 0 : 8_200_000);
    }
    if (call.url.includes("/api/backend/play")) return snapshot("playing", 8_200_000);
    if (call.url.includes("/api/backend/pause")) return snapshot("paused", 8_200_000);
    if (call.url.includes("/api/backend/stream")) {
      streamFetches += 1;
      return new Response(new ReadableStream(), { headers: {
        "content-type": "multipart/x-mixed-replace; boundary=frame" } });
    }
    if (call.url.includes("/api/backend/close")) return ok({ closed: true });
    if (call.url.includes("/api/backend/open")) return ok({ playback_id: "pb-reopened" });
    throw new Error(`unexpected fetch: ${call.url}`);
  });
  const image = (rid, ptsUs = 0, playbackId = client.playbackId) => new Response(Uint8Array.of(1), {
    headers: { "content-type": "image/png", ...seekHeaders({ playbackId,
      generation: rid, requestId: rid, frameIndex: Math.floor(ptsUs * 30 / 1e6), ptsUs }) },
  });
  client.startStream(() => {});
  const rewind = client.renderAt(0);
  await tick();
  assert.equal(streamFetches, 1, "seek ack must not restart stream before render commits");
  await client.snapshot();
  assert.equal(client.phase, "buffering", "JSON may update transport during pending seek");
  assert.equal(client.accepted, 0, "buffering JSON must not commit the seek request");
  assert.equal(client.tUs, 8_133_334);
  snapshotMode = "playing";
  await client.snapshot();
  await client.play();
  await client.pause();
  assert.equal(client.accepted, 0);
  assert.equal(client.frameIndex, 244);
  assert.equal(client.tUs, 8_133_334);
  snapshotMode = "late";
  const oldSnapshot = client.snapshot();
  const oldReply = snapshot("playing", 8_200_000);
  renders.get(1).resolve(image(1));
  assert.equal((await rewind).applied, true);
  assert.equal(client.tUs, 0, "matching render commits the backward target");
  assert.equal(client.accepted, 1);
  assert.equal(client.frameIndex, 0);
  assert.equal(streamFetches, 2, "stream resumes after the frame commit");
  late.resolve(oldReply);
  await oldSnapshot;
  assert.equal(client.tUs, 0, "snapshot issued before commit cannot restore old clock");

  // An older render finishing cannot clear the newer seek barrier.
  const older = client.renderAt(1_000_000);
  await tick();
  const newer = client.renderAt(2_000_000);
  await tick();
  renders.get(2).resolve(image(2, 1_000_000));
  assert.equal((await older).superseded, true);
  snapshotMode = "playing";
  await client.snapshot();
  assert.equal(client.tUs, 0, "old finally must leave newer pending seek intact");
  renders.get(3).resolve(image(3, 2_000_000));
  assert.equal((await newer).applied, true);
  assert.equal(client.tUs, 2_000_000);

  // Failed/409 renders clear only their own barrier, allowing the next snapshot.
  for (const response of [new Response(null, { status: 409 }),
    json({ ok: false, code: "render_failed", reason: "failed" }, { status: 500 })]) {
    const pending = client.renderAt(0);
    const settled = pending.then((result) => result, (error) => error);
    await tick();
    renders.get(client.issued).resolve(response);
    const result = await settled;
    assert.ok(result.superseded || result instanceof Error);
    await client.snapshot();
    assert.equal(client.tUs, 8_200_000, "failure must release the clock barrier");
  }
  const ended = client.renderAt(45_000_000);
  await tick();
  renders.get(client.issued).resolve(snapshot("ended", 45_000_000));
  assert.equal((await ended).ended, true);
  assert.equal(client.phase, "ended");
  assert.equal(client.tUs, 45_000_000);
  assert.equal(client.accepted, client.issued);

  const closing = client.renderAt(0);
  await tick();
  const closedRid = client.issued;
  await client.close();
  await client.open("draft-y", "timeline-y");
  const reopened = client.renderAt(0);
  await tick();
  renders.get(closedRid).resolve(image(closedRid, 0, "pb-barrier"));
  assert.equal((await closing).stale, true);
  await client.snapshot();
  assert.equal(client.tUs, 0, "old epoch finally cannot clear reopened seek barrier");
  renders.get(1).resolve(image(1));
  assert.equal((await reopened).applied, true);
  await client.close();
}

async function selectionEpoch() {
  const firstOpen = deferred();
  const lateClose = deferred();
  const currentClose = deferred();
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
    if (call.url.includes("/api/backend/close")) {
      const id = queryOf(call).get("playback_id");
      if (id === "pb-late") return lateClose.promise.then(() => ok({ closed: true }));
      if (id === "pb-current") return currentClose.promise.then(() => ok({ closed: true }));
      return ok({ closed: true });
    }
    throw new Error(`unexpected fetch: ${call.url}`);
  });

  const client = new MltPlaybackClient();
  const late = client.open("draft-a", "timeline-a");
  await tick();
  const current = client.open("draft-b", "timeline-b");
  await tick();
  assert.equal(openCount, 1, "a superseding open must wait for the native owner in flight");
  firstOpen.resolve();
  await tick();
  assert.equal(openCount, 1, "the superseded native owner must finish closing before the next open");
  lateClose.resolve();
  const lateResult = await late;
  const currentResult = await current;
  assert.equal(currentResult.stale, false);
  assert.equal(lateResult.stale, true, "a late open must be ignored after a timeline switch");
  assert.equal(client.playbackId, "pb-current", "a late open must not overwrite the selection");
  assert.equal(client.accepts({ playbackId: "pb-late", seekRequestId: 5, generation: 5 }), false,
    "old identity cannot update the new selection");
  // The late open's echoed did/timeline must not overwrite the new selection.
  assert.equal(client.draft, "draft-b", "a stale open must not rewrite the draft selector");
  assert.equal(client.timeline, "timeline-b", "a stale open must not rewrite the timeline selector");

  // Re-open under yet another selection: the previous handle must be closed too.
  const reopening = client.open("draft-c", "timeline-c");
  await tick();
  assert.equal(openCount, 2, "a different-key switch must await its captured previous close");
  currentClose.resolve();
  const reopened = await reopening;
  assert.equal(reopened.stale, false);

  // Every discarded owner is closed with its own captured/resolved selectors.
  const closeCalls = calls.filter((call) => call.url.includes("/api/backend/close"));
  const closed = closeCalls.map((call) => queryOf(call).get("playback_id"));
  assert.ok(closed.includes("pb-late"),
    "a superseded open must best-effort close the handle it leaked");
  assert.ok(closed.includes("pb-current"),
    "a re-open must best-effort close the previous handle");
  for (const call of closeCalls) {
    const query = queryOf(call);
    const suffix = query.get("playback_id") === "pb-late" ? "a" : "b";
    assert.equal(query.get("draft"), `draft-${suffix}`, call.url);
    assert.equal(query.get("timeline"), `timeline-${suffix}`, call.url);
  }
}

async function failedLifecycleRelease() {
  const client = await openClient({ playbackId: "pb-release" });
  let failed = true;
  let opens = 0;
  installFetch((call) => {
    if (call.url.includes("/api/backend/close")) {
      assert.equal(queryOf(call).get("draft"), "draft-x");
      assert.equal(queryOf(call).get("timeline"), "timeline-1");
      return json({}, { status: failed ? 500 : 200 });
    }
    if (call.url.includes("/api/backend/open")) {
      opens += 1;
      return ok({ playback_id: "pb-recovered" });
    }
    throw new Error(`unexpected fetch: ${call.url}`);
  });
  await assert.rejects(client.open("draft-y", "timeline-y"), /could not be closed/);
  assert.equal(opens, 0, "failed cleanup cannot permit another native probe");
  failed = false;
  await client.open("draft-y", "timeline-y");
  assert.equal(opens, 1, "retry must release the captured owner before opening");

  const pendingOpen = deferred();
  const pendingClose = deferred();
  let openCalls = 0;
  installFetch((call) => {
    if (call.url.includes("/api/backend/open")) {
      openCalls += 1;
      return pendingOpen.promise.then(() => ok({ playback_id: "pb-pending" }));
    }
    if (call.url.includes("/api/backend/close")) {
      if (queryOf(call).get("playback_id") === "pb-pending") {
        return pendingClose.promise.then(() => ok({ closed: true }));
      }
      return ok({ closed: true });
    }
    throw new Error(`unexpected fetch: ${call.url}`);
  });
  const opening = client.open("draft-z", "timeline-z");
  await tick();
  let closed = false;
  const closing = client.close().then(() => { closed = true; });
  pendingOpen.resolve();
  await tick();
  assert.equal(closed, false, "close must await cleanup of a native open already in flight");
  pendingClose.resolve();
  assert.equal((await opening).stale, true);
  await closing;
  assert.equal(client.playbackId, null);
  assert.equal(openCalls, 1);
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
  await backwardSeekUsesRenderedPts();
  await seekCommitBarrier();
  await renderResponses();
  await selectionEpoch();
  await failedLifecycleRelease();
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
