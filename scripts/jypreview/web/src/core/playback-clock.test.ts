import { describe, expect, it, vi } from "vitest";

import { PlaybackClock, type ClockSnapshot, type PlaybackStatus } from "./playback-clock.ts";

interface FakeNow {
  (): number;
  advance: (delta: number) => number;
}

/** Millisecond source the tests advance by hand; the clock converts to integer µs. */
function fakeNow(startMs = 0): FakeNow {
  let ms = startMs;
  const now = (() => ms) as FakeNow;
  now.advance = (delta: number) => {
    ms += delta;
    return ms;
  };
  return now;
}

function manualFrame() {
  let task: (() => void) | null = null;
  const schedule = (fn: () => void) => {
    task = fn;
    return () => {
      task = null;
    };
  };
  const flush = () => {
    const run = task;
    task = null;
    run?.();
  };
  return { schedule, flush, pending: () => task !== null };
}

function open(options: { durationUs?: number; now?: FakeNow; maxElapsedUs?: number } = {}) {
  const now: FakeNow = options.now ?? fakeNow();
  const frame = manualFrame();
  const clock = new PlaybackClock({
    durationUs: options.durationUs ?? 10_000_000,
    now,
    schedule: frame.schedule,
    maxElapsedUs: options.maxElapsedUs,
  });
  return { clock, now, frame };
}

function collect(clock: PlaybackClock) {
  const seen: ClockSnapshot[] = [];
  clock.subscribe((snapshot) => seen.push(snapshot));
  return { seen, last: () => seen[seen.length - 1] };
}

describe("PlaybackClock units", () => {
  it("keeps every reported time an integer number of microseconds", () => {
    const { clock, now, frame } = open();
    clock.setRate(1 / 3);
    clock.play();
    for (let step = 0; step < 20; step += 1) {
      now.advance(33.37);
      frame.flush();
      expect(Number.isInteger(clock.tUs)).toBe(true);
    }
    clock.destroy();
  });

  it("starts at zero, stopped, rate one", () => {
    const { clock } = open();
    const snapshot = clock.snapshot();
    expect(snapshot.tUs).toBe(0);
    expect(snapshot.status).toBe("stopped");
    expect(snapshot.rate).toBe(1);
    expect(snapshot.durationUs).toBe(10_000_000);
    clock.destroy();
  });
});

describe("PlaybackClock play and pause", () => {
  it("advances by elapsed wall time while playing and freezes when paused", () => {
    const { clock, now, frame } = open();
    clock.play();
    now.advance(1000);
    frame.flush();
    expect(clock.tUs).toBe(1_000_000);
    clock.pause();
    now.advance(5000);
    frame.flush();
    expect(clock.tUs).toBe(1_000_000);
    clock.play();
    now.advance(500);
    frame.flush();
    expect(clock.tUs).toBe(1_500_000);
    clock.destroy();
  });

  it("clamps a stalled frame instead of integrating the whole gap", () => {
    const { clock, now, frame } = open({ maxElapsedUs: 250_000 });
    clock.play();
    now.advance(4000);
    frame.flush();
    expect(clock.tUs).toBe(250_000);
    expect(clock.status).toBe("playing");
    clock.destroy();
  });

  it("stops scheduling once paused", () => {
    const { clock, frame } = open();
    clock.play();
    expect(frame.pending()).toBe(true);
    clock.pause();
    frame.flush();
    expect(frame.pending()).toBe(false);
    clock.destroy();
  });

  it("reports each status transition exactly once", () => {
    const { clock, now, frame } = open({ durationUs: 2_000_000 });
    const statuses: PlaybackStatus[] = [];
    clock.subscribe((snapshot) => statuses.push(snapshot.status));
    clock.play();
    now.advance(1500);
    frame.flush();
    expect(statuses).toEqual(["playing", "playing"]);
    clock.pause();
    expect(statuses).toEqual(["playing", "playing", "paused"]);
    clock.destroy();
  });
});

describe("PlaybackClock seek", () => {
  it("clamps into the timeline and keeps playing from the new position", () => {
    const { clock, now, frame } = open();
    clock.seek(-5);
    expect(clock.tUs).toBe(0);
    clock.seek(999_999_999);
    expect(clock.tUs).toBe(10_000_000);
    clock.seek(4_000_000);
    clock.play();
    now.advance(1000);
    frame.flush();
    expect(clock.tUs).toBe(5_000_000);
    clock.destroy();
  });

  it("notifies listeners for a seek that moves", () => {
    const { clock } = open();
    const { seen } = collect(clock);
    clock.seek(3_000_000);
    expect(seen.map((snapshot) => snapshot.tUs)).toEqual([3_000_000]);
    clock.destroy();
  });

  it("ignores a repeated seek to the same position", () => {
    const { clock } = open();
    const { seen } = collect(clock);
    clock.seek(3_000_000);
    const epoch = clock.epoch;
    clock.seek(3_000_000);
    clock.seek(3_000_000);
    expect(seen).toHaveLength(1);
    expect(clock.epoch).toBe(epoch);
    clock.destroy();
  });

  it("re-anchors a repeated seek while playing without moving the playhead", () => {
    const { clock, now, frame } = open();
    clock.seek(2_000_000);
    clock.play();
    const epoch = clock.epoch;
    clock.seek(2_000_000);
    expect(clock.epoch).toBe(epoch);
    expect(clock.status).toBe("playing");
    now.advance(500);
    frame.flush();
    expect(clock.tUs).toBe(2_500_000);
    clock.destroy();
  });
});

describe("PlaybackClock rate", () => {
  it("scales elapsed time", () => {
    const { clock, now, frame } = open();
    clock.setRate(2);
    clock.play();
    now.advance(1000);
    frame.flush();
    expect(clock.tUs).toBe(2_000_000);
    expect(clock.rate).toBe(2);
    clock.setRate(0.5);
    now.advance(1000);
    frame.flush();
    expect(clock.tUs).toBe(2_500_000);
    clock.destroy();
  });

  it("keeps the position when the rate changes mid-play", () => {
    const { clock, now, frame } = open();
    clock.play();
    now.advance(1000);
    frame.flush();
    clock.setRate(4);
    expect(clock.tUs).toBe(1_000_000);
    now.advance(1000);
    frame.flush();
    expect(clock.tUs).toBe(5_000_000);
    clock.destroy();
  });

  it("clamps an unusable rate and says so in the snapshot", () => {
    const { clock } = open();
    clock.setRate(0);
    expect(clock.rate).toBeGreaterThan(0);
    clock.setRate(Number.NaN);
    expect(Number.isFinite(clock.rate)).toBe(true);
    clock.destroy();
  });
});

describe("PlaybackClock end of timeline", () => {
  it("lands on the duration, reports ended once and stops scheduling", () => {
    const { clock, now, frame } = open({ durationUs: 2_000_000 });
    const { seen } = collect(clock);
    clock.play();
    now.advance(1000);
    frame.flush();
    now.advance(5000);
    frame.flush();
    expect(clock.tUs).toBe(2_000_000);
    expect(clock.status).toBe("ended");
    expect(seen.filter((snapshot) => snapshot.status === "ended")).toHaveLength(1);
    now.advance(1000);
    frame.flush();
    expect(seen.filter((snapshot) => snapshot.status === "ended")).toHaveLength(1);
    clock.destroy();
  });

  it("replays from a seek after ending", () => {
    const { clock, now, frame } = open({ durationUs: 1_000_000 });
    clock.play();
    now.advance(2000);
    frame.flush();
    expect(clock.status).toBe("ended");
    clock.seek(0);
    expect(clock.status).toBe("paused");
    clock.play();
    now.advance(400);
    frame.flush();
    expect(clock.tUs).toBe(400_000);
    clock.destroy();
  });
});

describe("PlaybackClock page visibility", () => {
  it("re-anchors on a hidden-to-visible resume without teleporting the playhead", () => {
    const now = fakeNow(1000);
    const frame = manualFrame();
    const clock = new PlaybackClock({ durationUs: 10_000_000, now, schedule: frame.schedule });
    clock.play();
    now.advance(500);
    frame.flush();
    expect(clock.tUs).toBe(500_000);
    clock.onHidden();
    now.advance(30_000);
    clock.onVisible();
    expect(clock.tUs).toBe(500_000);
    expect(clock.status).toBe("playing");
    now.advance(200);
    frame.flush();
    expect(clock.tUs).toBe(700_000);
    clock.destroy();
  });

  it("keeps a clock that never played from starting on resume", () => {
    const now = fakeNow(0);
    const frame = manualFrame();
    const clock = new PlaybackClock({ durationUs: 10_000_000, now, schedule: frame.schedule });
    clock.seek(4_000_000);
    clock.onHidden();
    now.advance(10_000);
    clock.onVisible();
    expect(clock.tUs).toBe(4_000_000);
    expect(clock.status).toBe("stopped");
    expect(frame.pending()).toBe(false);
    clock.destroy();
  });
});

describe("PlaybackClock subscriptions", () => {
  it("delivers the snapshot to every listener and stops after unsubscribe", () => {
    const { clock } = open();
    const a = vi.fn();
    const b = vi.fn();
    const off = clock.subscribe(a);
    clock.subscribe(b);
    clock.seek(1_000_000);
    expect(a).toHaveBeenCalledTimes(1);
    expect(b).toHaveBeenCalledTimes(1);
    off();
    clock.seek(2_000_000);
    expect(a).toHaveBeenCalledTimes(1);
    expect(b).toHaveBeenCalledTimes(2);
    clock.destroy();
  });

  it("survives a listener that throws and keeps the clock authoritative", () => {
    const { clock, now, frame } = open();
    clock.subscribe(() => {
      throw new Error("renderer blew up");
    });
    const seen = vi.fn();
    clock.subscribe(seen);
    clock.play();
    now.advance(1000);
    expect(() => frame.flush()).not.toThrow();
    expect(seen).toHaveBeenCalled();
    expect(clock.tUs).toBe(1_000_000);
    clock.destroy();
  });

  it("increments the epoch on every authority change so media can defer to it", () => {
    const { clock } = open();
    const epochs: number[] = [];
    clock.subscribe((snapshot) => epochs.push(snapshot.epoch));
    clock.play();
    clock.pause();
    clock.seek(5_000_000);
    clock.setRate(2);
    clock.destroy();
    expect(new Set(epochs).size).toBe(epochs.length);
    expect(epochs.at(-1)).toBeGreaterThan(epochs[0] ?? 0);
  });

  it("refuses to notify after destroy", () => {
    const { clock, now, frame } = open();
    const seen = vi.fn();
    clock.subscribe(seen);
    clock.play();
    clock.destroy();
    const calls = seen.mock.calls.length;
    now.advance(1000);
    frame.flush();
    expect(seen).toHaveBeenCalledTimes(calls);
    expect(clock.status).toBe("destroyed");
  });
});

describe("PlaybackClock duration", () => {
  it("re-clamps the playhead when a reload shortens the timeline", () => {
    const { clock } = open({ durationUs: 10_000_000 });
    clock.seek(9_000_000);
    clock.setDuration(4_000_000);
    expect(clock.tUs).toBe(4_000_000);
    expect(clock.snapshot().durationUs).toBe(4_000_000);
    clock.destroy();
  });
});
