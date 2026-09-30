/** The one time authority the editor plays against.
 *
 * Media elements are consumers, never sources: they observe snapshots and must not
 * write back. Position is kept as integer microseconds and derived by
 * anchor-and-integrate, so a stall, a backgrounded tab or a repeated seek cannot
 * silently move the playhead -- each of those paths is asserted in the tests.
 */

export type PlaybackStatus = "stopped" | "playing" | "paused" | "ended" | "destroyed";

export interface ClockSnapshot {
  /** Playhead position in integer microseconds. */
  tUs: number;
  status: PlaybackStatus;
  playing: boolean;
  rate: number;
  durationUs: number;
  /** Bumps on every change of authority, so a renderer can tell a new order from a echo. */
  epoch: number;
}

export type ClockListener = (snapshot: ClockSnapshot) => void;
export type CancelSchedule = () => void;

export interface PlaybackClockOptions {
  durationUs: number;
  /** Milliseconds, same domain as `performance.now()`; injectable for deterministic tests. */
  now?: () => number;
  schedule?: (task: () => void) => CancelSchedule;
  /** Longest gap integrated in one step; anything beyond it is treated as a stall. */
  maxElapsedUs?: number;
  rateMin?: number;
  rateMax?: number;
}

export const DEFAULT_MAX_ELAPSED_US = 1_000_000;
export const DEFAULT_RATE_MIN = 1 / 16;
export const DEFAULT_RATE_MAX = 16;

function frameSchedule(): (task: () => void) => CancelSchedule {
  const raf = (globalThis as { requestAnimationFrame?: (cb: () => void) => number })
    .requestAnimationFrame;
  if (typeof raf === "function") {
    return (task) => {
      const handle = raf(task);
      return () => {
        const cancel = (globalThis as { cancelAnimationFrame?: (h: number) => void })
          .cancelAnimationFrame;
        cancel?.(handle);
      };
    };
  }
  return (task) => {
    const handle = setTimeout(task, 16);
    return () => clearTimeout(handle);
  };
}

export class PlaybackClock {
  private readonly clockNow: () => number;
  private readonly scheduleTask: (task: () => void) => CancelSchedule;
  private readonly maxElapsedUs: number;
  private readonly rateMin: number;
  private readonly rateMax: number;
  private readonly listeners = new Set<ClockListener>();

  private durationValue: number;
  private positionUs: number;
  private rateValue = 1;
  private statusValue: PlaybackStatus = "stopped";
  private epochValue = 0;
  private anchorUs: number;
  private anchorNowUs: number;
  private cancel: CancelSchedule | null = null;
  private hidden = false;

  constructor(options: PlaybackClockOptions) {
    this.clockNow = options.now ?? (() => performance.now());
    this.scheduleTask = options.schedule ?? frameSchedule();
    this.maxElapsedUs = Math.max(1, Math.round(options.maxElapsedUs ?? DEFAULT_MAX_ELAPSED_US));
    this.rateMin = options.rateMin ?? DEFAULT_RATE_MIN;
    this.rateMax = options.rateMax ?? DEFAULT_RATE_MAX;
    this.durationValue = Math.max(0, Math.round(options.durationUs));
    this.positionUs = 0;
    this.anchorUs = 0;
    this.anchorNowUs = this.nowUs();
  }

  get tUs(): number {
    return this.positionUs;
  }

  get status(): PlaybackStatus {
    return this.statusValue;
  }

  get rate(): number {
    return this.rateValue;
  }

  get durationUs(): number {
    return this.durationValue;
  }

  get epoch(): number {
    return this.epochValue;
  }

  get playing(): boolean {
    return this.statusValue === "playing";
  }

  play(fromUs?: number): void {
    if (this.statusValue === "destroyed") return;
    this.settle();
    if (fromUs !== undefined) this.moveTo(this.clamp(fromUs));
    if (this.durationValue <= 0) {
      this.positionUs = 0;
      this.stopLoop();
      if (this.statusValue !== "ended") this.publish("ended");
      return;
    }
    if (this.statusValue === "ended") this.moveTo(0);
    this.stopLoop();
    this.reanchor();
    if (this.statusValue === "playing") return;
    this.publish("playing");
    this.startLoop();
  }

  pause(): void {
    if (this.statusValue === "destroyed" || this.statusValue === "stopped") return;
    this.settle();
    this.stopLoop();
    if (this.statusValue === "playing") this.publish("paused");
  }

  seek(tUs: number): void {
    if (this.statusValue === "destroyed") return;
    const target = this.clamp(tUs);
    if (this.statusValue === "playing") {
      this.positionUs = target;
      this.reanchor();
      return;
    }
    if (target === this.positionUs && this.statusValue !== "ended") return;
    this.positionUs = target;
    this.reanchor();
    const next: PlaybackStatus = this.statusValue === "ended" ? "paused" : this.statusValue;
    this.publish(next);
  }

  setRate(rate: number): void {
    if (this.statusValue === "destroyed") return;
    const safe = Number.isFinite(rate) ? Math.min(Math.max(rate, this.rateMin), this.rateMax) : this.rateValue;
    if (safe <= 0) return;
    if (safe === this.rateValue) return;
    this.settle();
    this.rateValue = safe;
    this.reanchor();
    this.publish(this.statusValue);
  }

  setDuration(durationUs: number): void {
    if (this.statusValue === "destroyed") return;
    const next = Math.max(0, Math.round(durationUs));
    if (next === this.durationValue) return;
    this.durationValue = next;
    const clamped = this.clamp(this.positionUs);
    const moved = clamped !== this.positionUs;
    this.positionUs = clamped;
    this.reanchor();
    if (moved) this.publish(next <= 0 ? "ended" : this.statusValue);
  }

  subscribe(listener: ClockListener): CancelSchedule {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  snapshot(): ClockSnapshot {
    return {
      tUs: this.positionUs,
      status: this.statusValue,
      playing: this.statusValue === "playing",
      rate: this.rateValue,
      durationUs: this.durationValue,
      epoch: this.epochValue,
    };
  }

  /** Called when the page goes background: freeze the position, do not integrate the gap. */
  onHidden(): void {
    if (this.statusValue === "destroyed" || this.hidden) return;
    this.hidden = true;
    this.settle();
  }

  /** Called on resume: adopt the current wall clock as the new anchor and re-schedule. */
  onVisible(): void {
    if (this.statusValue === "destroyed" || !this.hidden) return;
    this.hidden = false;
    this.reanchor();
    if (this.statusValue === "playing") {
      this.startLoop();
      this.publish("playing");
    }
  }

  destroy(): void {
    if (this.statusValue === "destroyed") return;
    this.stopLoop();
    this.listeners.clear();
    this.statusValue = "destroyed";
    this.epochValue += 1;
  }

  private nowUs(): number {
    return Math.round(this.clockNow() * 1000);
  }

  private clamp(tUs: number): number {
    const value = Math.round(Number.isFinite(tUs) ? tUs : 0);
    return Math.min(Math.max(value, 0), this.durationValue);
  }

  private reanchor(): void {
    this.anchorUs = this.positionUs;
    this.anchorNowUs = this.nowUs();
  }

  /** Fold the elapsed wall time into the position without announcing anything. */
  private settle(): number {
    if (this.statusValue !== "playing") return this.positionUs;
    return this.integrate(false);
  }

  private integrate(notify: boolean): number {
    const nowUs = this.nowUs();
    let elapsed = nowUs - this.anchorNowUs;
    if (elapsed < 0) elapsed = 0;
    if (elapsed > this.maxElapsedUs) elapsed = this.maxElapsedUs;
    const moved = this.anchorUs + Math.round(elapsed * this.rateValue);
    this.anchorNowUs = nowUs;
    if (moved >= this.durationValue) {
      this.anchorUs = this.durationValue;
      this.positionUs = this.durationValue;
      this.stopLoop();
      if (this.statusValue !== "ended") this.publish("ended");
      else if (notify) this.publish(this.statusValue);
      return this.positionUs;
    }
    this.anchorUs = moved;
    this.positionUs = moved;
    if (notify) this.publish(this.statusValue);
    return moved;
  }

  private startLoop(): void {
    if (this.cancel) return;
    const tick = () => {
      this.cancel = null;
      if (this.statusValue !== "playing" || this.hidden) return;
      this.integrate(true);
      if (this.statusValue === "playing") this.startLoop();
    };
    this.cancel = this.scheduleTask(tick);
  }

  private stopLoop(): void {
    this.cancel?.();
    this.cancel = null;
  }

  private moveTo(tUs: number): void {
    this.positionUs = tUs;
    this.reanchor();
  }

  private publish(status: PlaybackStatus): void {
    this.statusValue = status;
    this.epochValue += 1;
    const snapshot = this.snapshot();
    for (const listener of [...this.listeners]) {
      try {
        listener(snapshot);
      } catch (error) {
        // A renderer must never be able to stall the clock; the UI reports it instead.
        console.error("playback listener failed", error);
      }
    }
  }
}
