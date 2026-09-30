// The one authoritative timeline clock.
// Rendering and media elements are observers of this class. They may report that
// they are not ready, but they never own or mutate the timeline position.

export const PLAYBACK_PHASES = Object.freeze([
  "idle", "loading", "ready", "playing", "paused", "seeking", "buffering", "error", "ended",
]);

const clamp = (value, low, high) => Math.max(low, Math.min(value, high));

export class PlaybackController {
  constructor(options = {}) {
    // Compatibility adapter for the partially migrated app. New callers should
    // pass callbacks/options; only this class writes adapter state.
    this.adapter = options.state || ("tUs" in options ? options : null);
    this.durationUs = Number(options.durationUs ?? this.adapter?.durationUs ?? 0);
    this.rate = Number(options.rate ?? this.adapter?.rate ?? 1) || 1;
    this.tUs = Number(options.tUs ?? this.adapter?.tUs ?? 0) || 0;
    this.phase = options.phase || this.adapter?.phase || "idle";
    this.playing = Boolean(options.playing ?? this.adapter?.playing);
    this.buffering = Boolean(options.buffering ?? this.adapter?.buffering);
    this.generation = Number(options.generation ?? this.adapter?.generation ?? 0) || 0;
    this.closed = false;
    this.now = options.now || (() => performance.now());
    this.schedule = options.schedule || ((callback) => requestAnimationFrame(callback));
    this.cancel = options.cancel || ((handle) => cancelAnimationFrame(handle));
    this.renderCallback = options.renderAt || (async () => ({ ok: true }));
    this.isPlayable = options.isPlayable || (() => true);
    this.onNeedBuffer = options.onNeedBuffer || (() => null);
    this.onTick = options.onTick || (() => {});
    this.onState = options.onState || (() => {});
    this.onClose = options.onClose || (() => {});
    this.frame = null;
    this.lastNow = null;
    this.pending = null;
    this.intentPlaying = this.playing;
    this._sync();
  }

  _assertOpen() {
    if (this.closed) throw new Error("playback controller is closed");
  }

  _sync() {
    if (this.adapter) {
      this.adapter.tUs = this.tUs;
      this.adapter.durationUs = this.durationUs;
      this.adapter.rate = this.rate;
      this.adapter.phase = this.phase;
      this.adapter.playing = this.playing;
      this.adapter.buffering = this.buffering;
      this.adapter.generation = this.generation;
    }
    this.onState(this.snapshot());
  }

  transition(phase) {
    this._assertOpen();
    if (!PLAYBACK_PHASES.includes(phase)) throw new Error(`unknown playback phase: ${phase}`);
    this.phase = phase;
    this.buffering = phase === "buffering" || phase === "loading";
    if (phase === "playing") {
      this.intentPlaying = true;
      this.playing = true;
    } else if (["idle", "ready", "paused", "ended"].includes(phase)) {
      this.intentPlaying = false;
      this.playing = false;
    } else {
      this.playing = this.intentPlaying;
    }
    this._sync();
    return phase;
  }

  bumpGeneration() {
    this._assertOpen();
    this.generation += 1;
    this._sync();
    return this.generation;
  }

  setTimeline({ durationUs = 0, rate = this.rate } = {}) {
    this._assertOpen();
    this._stopFrame();
    this.intentPlaying = false;
    this.durationUs = Math.max(0, Number(durationUs) || 0);
    this.rate = Number(rate) || 1;
    this.tUs = 0;
    this.buffering = false;
    this.playing = false;
    this.generation += 1;
    this.phase = "idle";
    this._sync();
    return this.snapshot();
  }

  reset(tUs = 0) {
    this._assertOpen();
    this._stopFrame();
    this.intentPlaying = false;
    this.tUs = clamp(Number(tUs) || 0, 0, this.durationUs || Number(tUs) || 0);
    this.playing = false;
    this.buffering = false;
    this.generation += 1;
    this.phase = "idle";
    this._sync();
  }

  _stopFrame() {
    if (this.frame !== null) this.cancel(this.frame);
    this.frame = null;
    this.lastNow = null;
  }

  _scheduleFrame() {
    if (this.frame === null && !this.closed && this.intentPlaying && this.phase === "playing") {
      this.frame = this.schedule((now) => this._step(now));
    }
  }

  _requestBuffer(generation = this.generation) {
    const result = this.onNeedBuffer(this.tUs, generation);
    if (!result || typeof result.then !== "function") return;
    Promise.resolve(result).then((ready) => {
      if (this.closed || generation !== this.generation) return;
      this.notifyBuffer(ready !== false, generation);
    }).catch(() => {
      if (this.closed || generation !== this.generation) return;
      this.notifyBuffer(false, generation);
    });
  }

  play() {
    this._assertOpen();
    if (!this.durationUs) return false;
    this.intentPlaying = true;
    this.lastNow = this.now();
    if (this.isPlayable(this.tUs, this.generation)) {
      this.phase = "playing";
      this.playing = true;
      this.buffering = false;
      this._scheduleFrame();
    } else {
      this.phase = "buffering";
      this.playing = true;
      this.buffering = true;
      this._requestBuffer();
    }
    this._sync();
    return true;
  }

  pause() {
    this._assertOpen();
    this.intentPlaying = false;
    this._stopFrame();
    this.playing = false;
    this.buffering = false;
    this.phase = this.durationUs > 0 && this.tUs >= this.durationUs ? "ended" : "paused";
    this._sync();
    return this.snapshot();
  }

  syncExternal(tUs, phase = "paused") {
    this._assertOpen();
    if (!PLAYBACK_PHASES.includes(phase)) throw new Error(`unknown playback phase: ${phase}`);
    this._stopFrame();
    this.tUs = clamp(Number(tUs) || 0, 0, this.durationUs || Number(tUs) || 0);
    this.phase = phase;
    this.intentPlaying = phase === "playing";
    this.playing = phase === "playing";
    this.buffering = phase === "buffering" || phase === "loading";
    this._sync();
    return this.snapshot();
  }

  notifyBuffer(ready, generation = this.generation) {
    this._assertOpen();
    if (generation !== this.generation) return false;
    if (!ready) {
      this.phase = "error";
      this.buffering = true;
      this.playing = this.intentPlaying;
      this._stopFrame();
      this._sync();
      return false;
    }
    this.buffering = false;
    if (this.intentPlaying) {
      this.phase = "playing";
      this.playing = true;
      this.lastNow = this.now();
      this._scheduleFrame();
    } else {
      this.phase = "ready";
      this.playing = false;
    }
    this._sync();
    return true;
  }

  async renderAt(tUs, exact = true) {
    this._assertOpen();
    const next = clamp(Number(tUs) || 0, 0, this.durationUs || Number(tUs) || 0);
    const generation = ++this.generation;
    const wasPlaying = this.intentPlaying;
    this._stopFrame();
    this.tUs = next;
    this.phase = "seeking";
    this.playing = false;
    this.buffering = false;
    this._sync();
    const request = Promise.resolve(this.renderCallback(next, { exact, generation }));
    this.pending = request;
    try {
      const result = await request;
      if (this.closed || generation !== this.generation) return result;
      this.pending = null;
      if (wasPlaying) {
        this.intentPlaying = true;
        if (this.isPlayable(this.tUs, generation)) {
          this.phase = "playing";
          this.playing = true;
          this.lastNow = this.now();
          this._scheduleFrame();
        } else {
          this.phase = "buffering";
          this.playing = true;
          this.buffering = true;
          this._requestBuffer(generation);
        }
      } else {
        this.intentPlaying = false;
        this.phase = "paused";
        this.playing = false;
      }
      this._sync();
      return result;
    } catch (error) {
      if (!this.closed && generation === this.generation) {
        this.pending = null;
        this.phase = "error";
        this.playing = false;
        this.buffering = false;
        this._sync();
      }
      throw error;
    }
  }

  seek(tUs, exact = true) {
    return this.renderAt(tUs, exact);
  }

  _step(now) {
    this.frame = null;
    if (this.closed || !this.intentPlaying || this.phase !== "playing") return;
    const current = Number(now) || this.now();
    const previous = this.lastNow === null ? current : this.lastNow;
    this.lastNow = current;
    const deltaMs = clamp(current - previous, 0, 250);
    const next = clamp(this.tUs + deltaMs * 1000 * this.rate, 0, this.durationUs);
    if (!this.isPlayable(next, this.generation)) {
      this.phase = "buffering";
      this.buffering = true;
      this.playing = true;
      this._sync();
      this._requestBuffer();
      return;
    }
    this.tUs = next;
    this._sync();
    this.onTick(this.tUs, { generation: this.generation });
    if (this.tUs >= this.durationUs) {
      this.intentPlaying = false;
      this.playing = false;
      this.phase = "ended";
      this._sync();
      return;
    }
    this._scheduleFrame();
  }

  snapshot() {
    return {
      phase: this.phase,
      generation: this.generation,
      tUs: this.tUs,
      durationUs: this.durationUs,
      rate: this.rate,
      playing: this.playing,
      buffering: this.buffering,
      closed: this.closed,
    };
  }

  close() {
    if (this.closed) return this.snapshot();
    this._stopFrame();
    this.intentPlaying = false;
    this.playing = false;
    this.buffering = false;
    this.closed = true;
    this.phase = "idle";
    this.onClose(this.snapshot());
    this._sync();
    return this.snapshot();
  }
}
