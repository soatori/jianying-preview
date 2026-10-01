// MLT playback client: the browser's only transport to the backend playback
// routes. All identity (playback id, seek request id, generation) is issued and
// checked here, so a stale response, late decode, or reordered frame can never
// update the UI after a newer intent or timeline selection.

const num = (value) => {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
};

function headerOf(res, name) {
  return res.headers.get(name);
}

/** Identity comes from the frozen response/frame headers, with JSON body fallbacks. */
function identityOf(res, data) {
  return {
    playbackId: headerOf(res, "X-Playback-ID")
      || (data && (data.playback_id ?? data.playbackId)) || null,
    generation: num(headerOf(res, "X-Playback-Generation")) ?? num(data && data.generation),
    seekRequestId: num(headerOf(res, "X-Seek-Request-ID")) ?? num(data && data.seek_request_id),
    frameIndex: num(headerOf(res, "X-Project-Frame")) ?? num(data && data.frame_index),
    ptsUs: num(headerOf(res, "X-Project-PTS-US")) ?? num(data && data.t_us),
  };
}

function indexOfBytes(haystack, needle) {
  outer: for (let i = 0; i <= haystack.length - needle.length; i += 1) {
    for (let j = 0; j < needle.length; j += 1) {
      if (haystack[i + j] !== needle[j]) continue outer;
    }
    return i;
  }
  return -1;
}

function startsWithBytes(haystack, needle) {
  if (haystack.length < needle.length) return false;
  for (let i = 0; i < needle.length; i += 1) {
    if (haystack[i] !== needle[i]) return false;
  }
  return true;
}

function parseHeaderBlock(text) {
  const headers = {};
  for (const line of text.split("\r\n")) {
    const colon = line.indexOf(":");
    if (colon > 0) headers[line.slice(0, colon).trim().toLowerCase()] = line.slice(colon + 1).trim();
  }
  return headers;
}

/** Incremental multipart/x-mixed-replace parser: bytes in, complete parts out. */
class MultipartParser {
  constructor(boundary) {
    this.delimiter = new TextEncoder().encode(`--${boundary}`);
    this.buffer = new Uint8Array(0);
    this.phase = "boundary";
    this.headers = null;
    this.length = 0;
  }

  push(chunk) {
    const merged = new Uint8Array(this.buffer.length + chunk.length);
    merged.set(this.buffer);
    merged.set(chunk, this.buffer.length);
    this.buffer = merged;
    const frames = [];
    for (;;) {
      if (this.phase === "boundary") {
        if (this.buffer.length >= 2 && this.buffer[0] === 13 && this.buffer[1] === 10) {
          this.buffer = this.buffer.subarray(2);
          continue;
        }
        if (this.buffer.length < this.delimiter.length + 2) break;
        if (!startsWithBytes(this.buffer, this.delimiter)) break;
        const after = String.fromCharCode(this.buffer[this.delimiter.length],
          this.buffer[this.delimiter.length + 1]);
        if (after === "--") break;                      // closing boundary: nothing follows
        if (after !== "\r\n") break;
        this.buffer = this.buffer.subarray(this.delimiter.length + 2);
        this.phase = "headers";
        continue;
      }
      if (this.phase === "headers") {
        const end = indexOfBytes(this.buffer, new Uint8Array([13, 10, 13, 10]));
        if (end < 0) break;
        this.headers = parseHeaderBlock(new TextDecoder().decode(this.buffer.subarray(0, end)));
        this.buffer = this.buffer.subarray(end + 4);
        const length = num(this.headers["content-length"]);
        this.phase = length === null ? "scan" : "body";
        this.length = length === null ? 0 : length;
        continue;
      }
      if (this.phase === "body") {
        if (this.buffer.length < this.length) break;
        frames.push({ headers: this.headers, bytes: this.buffer.slice(0, this.length) });
        this.buffer = this.buffer.subarray(this.length);
        this.phase = "boundary";
        continue;
      }
      // No Content-Length: the body runs up to the next boundary.
      const next = indexOfBytes(this.buffer, this.delimiter);
      if (next < 0) break;
      let end = next;
      if (end >= 2 && this.buffer[end - 2] === 13 && this.buffer[end - 1] === 10) end -= 2;
      frames.push({ headers: this.headers, bytes: this.buffer.slice(0, end) });
      this.buffer = this.buffer.subarray(next);
      this.phase = "boundary";
    }
    return frames;
  }
}

export class MltPlaybackClient {
  constructor({ baseUrl = "" } = {}) {
    this.baseUrl = baseUrl || "";
    this.epoch = 0;               // local selection epoch: invalidates late open/close work
    this.playbackId = null;
    this.draft = null;
    this.timeline = null;
    this.issued = 0;              // last request id issued (intent), monotonic per open
    this.accepted = 0;            // last request id acknowledged by the backend
    this.generation = 0;
    this.tUs = 0;
    this.frameIndex = 0;
    this.durationUs = 0;
    this.phase = "idle";
    this.playing = false;
    this.error = null;
    this.streamWanted = false;
    this.onFrame = null;
    this.onError = null;
    this.streamAbort = null;
    this.streamReader = null;
    this.frameQueue = [];
    this.draining = false;
  }

  #url(path, params) {
    const query = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
      if (value !== null && value !== undefined) query.set(key, String(value));
    }
    return `${this.baseUrl}${path}?${query}`;
  }

  async #payload(res) {
    const type = headerOf(res, "content-type") || "";
    if (!type.includes("json")) return null;
    let payload = null;
    try { payload = await res.json(); } catch (error) { void error; return null; }
    if (payload && typeof payload === "object" && typeof payload.ok === "boolean") {
      if (!payload.ok) {
        const failure = new Error(`${payload.code || "backend_error"}: ${payload.reason || ""}`);
        failure.code = payload.code;
        throw failure;
      }
      return payload.data && typeof payload.data === "object" ? payload.data : {};
    }
    return payload;
  }

  async #request(method, path, params) {
    const res = await fetch(this.#url(path, params), method === "GET" ? undefined : { method });
    const data = await this.#payload(res);
    if (!res.ok) throw new Error(`backend request failed: HTTP ${res.status}`);
    return { res, data };
  }

  /**
   * Apply one backend response under the frozen gates: selection epoch, playback
   * identity, and the latest issued request id. Returns superseded/stale instead
   * of mutating state when the response predates the newest intent.
   */
  #apply(ident, data, epoch) {
    if (epoch !== this.epoch) return { applied: false, stale: true, superseded: false };
    if (ident.playbackId === null) {
      throw new Error("backend response is missing playback identity (X-Playback-ID)");
    }
    if (ident.playbackId !== this.playbackId) {
      return { applied: false, stale: false, superseded: true };
    }
    const requestId = ident.seekRequestId;
    if (requestId !== null && requestId < this.issued) {
      return { applied: false, stale: false, superseded: true };
    }
    const previous = this.accepted;
    if (requestId !== null) this.accepted = requestId;
    if (ident.generation !== null) this.generation = ident.generation;
    if (ident.frameIndex !== null) this.frameIndex = ident.frameIndex;
    const pts = ident.ptsUs !== null ? ident.ptsUs : num(data && data.t_us);
    if (pts !== null) {
      const moved = requestId !== null && requestId !== previous;
      if (moved || pts >= this.tUs) this.tUs = pts;    // never run the playhead backwards mid-position
    }
    if (data && typeof data === "object") {
      if (data.phase) this.phase = String(data.phase);
      if (data.playing !== undefined && data.playing !== null) this.playing = !!data.playing;
      else if (data.phase) this.playing = this.phase === "playing";
      const duration = num(data.duration_us);
      if (duration !== null && duration > 0) this.durationUs = duration;
      if (data.error !== undefined) this.error = data.error ? String(data.error) : null;
    }
    return { applied: true, stale: false, superseded: false, requestId, playbackId: this.playbackId };
  }

  #resetIdentity(timeline) {
    this.playbackId = null;
    this.issued = 0;
    this.accepted = 0;
    this.generation = 0;
    this.tUs = 0;
    this.frameIndex = 0;
    this.durationUs = 0;
    this.phase = "idle";
    this.playing = false;
    this.error = null;
    if (timeline) {
      this.draft = timeline.draft;
      this.timeline = timeline.timeline;
    }
  }

  async open(draft, timeline) {
    const epoch = ++this.epoch;
    this.#stopStream();
    const previous = this.playbackId;
    this.#resetIdentity({ draft, timeline });
    if (previous) {
      try {
        await fetch(this.#url("/api/backend/close", { playback_id: previous }), { method: "POST" });
      } catch (error) { void error; }   // closing the previous handle is best-effort
    }
    const { res, data } = await this.#request("POST", "/api/backend/open", { draft, timeline });
    if (epoch !== this.epoch) return { applied: false, stale: true };
    const body = data && data.snapshot && typeof data.snapshot === "object" ? data.snapshot : data;
    const ident = identityOf(res, body);
    if (ident.playbackId === null) {
      throw new Error("backend open response is missing playback identity (X-Playback-ID)");
    }
    this.playbackId = ident.playbackId;
    if (ident.generation !== null) this.generation = ident.generation;
    if (ident.frameIndex !== null) this.frameIndex = ident.frameIndex;
    if (ident.ptsUs !== null) this.tUs = ident.ptsUs;
    if (body && typeof body === "object") {
      if (body.phase) this.phase = String(body.phase);
      this.playing = body.playing === true || this.phase === "playing";
      const duration = num(body.duration_us);
      if (duration !== null && duration > 0) this.durationUs = duration;
      if (body.error) this.error = String(body.error);
    }
    return { applied: true, stale: false, playbackId: this.playbackId };
  }

  async close() {
    this.epoch += 1;
    this.#stopStream();
    const previous = this.playbackId;
    this.#resetIdentity();
    if (!previous) return { closed: false };
    try {
      const res = await fetch(this.#url("/api/backend/close", { playback_id: previous }),
        { method: "POST" });
      return { closed: res.ok };
    } catch (error) {
      void error;
      return { closed: false };
    }
  }

  async #handle(action) {
    if (!this.playbackId) throw new Error("backend is not open");
    const epoch = this.epoch;
    const { res, data } = await this.#request("POST", `/api/backend/${action}`,
      { playback_id: this.playbackId });
    return this.#apply(identityOf(res, data), data, epoch);
  }

  play() { return this.#handle("play"); }
  pause() { return this.#handle("pause"); }

  /** Seek issues a fresh monotonic request id synchronously, before any HTTP. */
  async seek(tUs) {
    if (!this.playbackId) throw new Error("backend is not open");
    const requestId = ++this.issued;
    const epoch = this.epoch;
    this.#abortStream();
    const t = Math.max(0, Math.round(Number(tUs) || 0));
    const { res, data } = await this.#request("POST", "/api/backend/seek",
      { t_us: t, request_id: requestId, playback_id: this.playbackId });
    const ident = identityOf(res, data);
    if (ident.seekRequestId === null) ident.seekRequestId = requestId;
    const result = this.#apply(ident, data, epoch);
    if (result.applied && this.streamWanted && requestId === this.issued) this.#startStream();
    return { ...result, requestId };
  }

  /** Ordered seek then /render with the same request id; never a second seek. */
  async renderAt(tUs) {
    if (!this.playbackId) throw new Error("backend is not open");
    const requestId = ++this.issued;
    const epoch = this.epoch;
    this.#abortStream();
    const t = Math.max(0, Math.round(Number(tUs) || 0));
    const { res, data } = await this.#request("POST", "/api/backend/seek",
      { t_us: t, request_id: requestId, playback_id: this.playbackId });
    const seekIdent = identityOf(res, data);
    if (seekIdent.seekRequestId === null) seekIdent.seekRequestId = requestId;
    const seekResult = this.#apply(seekIdent, data, epoch);
    if (!seekResult.applied) return { ...seekResult, requestId };
    if (this.streamWanted && requestId === this.issued) this.#startStream();

    const response = await fetch(this.#url("/api/backend/render",
      { t_us: t, request_id: requestId, playback_id: this.playbackId }), { cache: "no-store" });
    if (epoch !== this.epoch) return { applied: false, stale: true, superseded: false, requestId };
    if (response.status === 409) {
      return { applied: false, stale: false, superseded: true, requestId };
    }
    const type = headerOf(response, "content-type") || "";
    if (!type.includes("image/")) {
      let payload = null;
      try { payload = await response.json(); } catch (error) { void error; }
      const body = payload && typeof payload === "object"
        ? (typeof payload.ok === "boolean"
          ? (payload.data && typeof payload.data === "object" ? payload.data : payload)
          : payload)
        : null;
      const code = String((payload && payload.code) || (body && body.code) || "");
      const ended = !!(body && (body.ended === true || body.phase === "ended" || /ended/i.test(code)));
      if (ended) {
        const result = this.#apply(identityOf(response, body), body, epoch);
        this.phase = "ended";
        this.playing = false;
        return { ...result, ended: true, requestId };
      }
      if (payload && payload.ok === false) {
        const failure = new Error(`${payload.code}: ${payload.reason}`);
        failure.code = payload.code;
        throw failure;
      }
      if (!response.ok) throw new Error(`backend render failed: HTTP ${response.status}`);
      throw new Error("backend render returned neither PNG nor ended");
    }
    const ident = identityOf(response, null);
    const blob = await response.blob();
    const result = this.#apply(ident, null, epoch);
    if (!result.applied) return { ...result, requestId };
    return { ...result, requestId, blob,
      playbackId: ident.playbackId, seekRequestId: ident.seekRequestId,
      generation: ident.generation, frameIndex: ident.frameIndex, ptsUs: ident.ptsUs };
  }

  async snapshot() {
    if (!this.playbackId) return { applied: false, stale: true, superseded: false };
    const epoch = this.epoch;
    const { res, data } = await this.#request("GET", "/api/backend/snapshot",
      { playback_id: this.playbackId });
    if (!data) throw new Error("backend snapshot returned no JSON");
    const result = this.#apply(identityOf(res, data), data, epoch);
    return { ...result, snapshot: data };
  }

  /** True while identity still matches the latest issued intent; used twice per
   *  frame: before decoding a blob and again before swapping the image URL. */
  accepts(identity) {
    if (!identity || identity.playbackId === null || identity.playbackId === undefined) return false;
    if (identity.playbackId !== this.playbackId) return false;
    if (identity.seekRequestId === null || identity.seekRequestId === undefined) return false;
    if (identity.seekRequestId < this.issued) return false;
    if (identity.generation === null || identity.generation === undefined) return false;
    if (identity.generation < this.generation) return false;
    return true;
  }

  startStream(onFrame, onError = null) {
    this.onFrame = onFrame;
    this.onError = onError;
    this.streamWanted = true;
    void this.#startStream();
  }

  stopStream() { this.#stopStream(); }

  #stopStream() {
    this.streamWanted = false;
    this.#abortStream();
  }

  #abortStream() {
    this.frameQueue.length = 0;
    const reader = this.streamReader;
    this.streamReader = null;
    if (reader) { try { void reader.cancel(); } catch (error) { void error; } }
    const abort = this.streamAbort;
    this.streamAbort = null;
    if (abort) { try { abort.abort(); } catch (error) { void error; } }
  }

  #streamFailed(error) {
    this.streamWanted = false;
    this.#abortStream();
    if (this.onError) { try { this.onError(error); } catch (handlerError) { void handlerError; } }
  }

  async #startStream() {
    if (!this.streamWanted || !this.playbackId) return;
    this.#abortStream();       // clear any previous reader; streamWanted stays set
    const epoch = this.epoch;
    const abort = new AbortController();
    this.streamAbort = abort;
    let res = null;
    try {
      res = await fetch(this.#url("/api/backend/stream", { playback_id: this.playbackId }),
        { cache: "no-store", signal: abort.signal });
    } catch (error) {
      if (epoch === this.epoch && !abort.signal.aborted) this.#streamFailed(error);
      return;
    }
    if (epoch !== this.epoch || abort.signal.aborted || this.streamAbort !== abort) return;
    if (!res.ok || !res.body) {
      this.#streamFailed(new Error(`stream failed: HTTP ${res.status}`));
      return;
    }
    const type = headerOf(res, "content-type") || "";
    const boundary = /boundary=(?:"([^"]+)"|([^;]+))/i.exec(type);
    if (!boundary) {
      this.#streamFailed(new Error("stream response is missing a multipart boundary"));
      return;
    }
    const parser = new MultipartParser((boundary[1] || boundary[2]).trim());
    const reader = res.body.getReader();
    this.streamReader = reader;
    try {
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        if (value) this.#deliver(parser.push(value), epoch);
      }
      if (epoch === this.epoch && this.streamWanted && !abort.signal.aborted) {
        this.#streamFailed(new Error("stream closed while playback was active"));
      }
    } catch (error) {
      if (!abort.signal.aborted && epoch === this.epoch) this.#streamFailed(error);
    } finally {
      if (this.streamReader === reader) this.streamReader = null;
    }
  }

  #deliver(parts, epoch) {
    for (const part of parts) {
      if (epoch !== this.epoch) return;
      const frame = {
        blob: new Blob([part.bytes], { type: part.headers["content-type"] || "image/png" }),
        playbackId: part.headers["x-playback-id"] || null,
        seekRequestId: num(part.headers["x-seek-request-id"]),
        generation: num(part.headers["x-playback-generation"]),
        frameIndex: num(part.headers["x-project-frame"]),
        ptsUs: num(part.headers["x-project-pts-us"]),
      };
      if (!this.accepts(frame)) continue;
      this.frameQueue.push(frame);
      while (this.frameQueue.length > 2) this.frameQueue.shift();   // keep at most two decoded frames
      void this.#drainFrames();
    }
  }

  async #drainFrames() {
    if (this.draining) return;
    this.draining = true;
    try {
      while (this.frameQueue.length) {
        const frame = this.frameQueue.shift();
        try {
          await this.onFrame(frame);
        } catch (error) {
          if (this.onError) { try { this.onError(error); } catch (handlerError) { void handlerError; } }
        }
      }
    } finally {
      this.draining = false;
    }
  }
}
