// Finding 4: a slow paint must never overlap another paint.
// Runs the REAL tick + watchdog source from player.html in a sandbox with a
// fake clock, so the regression is caught without launching Chrome.
import { readFileSync } from "node:fs";
import vm from "node:vm";
import assert from "node:assert/strict";
import { test } from "node:test";

const HTML = readFileSync(new URL("../player/player.html", import.meta.url), "utf8");

function slice(from, to) {
  const a = HTML.indexOf(from);
  assert.ok(a >= 0, `anchor not found: ${from}`);
  const b = HTML.indexOf(to, a);
  assert.ok(b > a, `end anchor not found after ${from}: ${to}`);
  return HTML.slice(a, b);
}

// State declarations + tick, then the watchdog. Both regions are contiguous
// in the file and bounded by comments/declarations that this plan does not move.
const SRC = slice("let actxT0 = 0;", "// ---- rAF")
  + "\n" + slice("let lastRafAt = 0", "function toggle(on) {");

function harness() {
  const clock = { t: 0 };
  const calls = { paint: 0, inFlight: 0, maxInFlight: 0 };
  const pending = [];
  let intervalCb = null;

  const ctx = {
    AVCLK_ON: false, actx: null, DUR: 100,
    stat: { requests: 0, bytes: 0 },
    pool: { map: new Map() },
    intervals: [], tickErrors: [],
    now: () => clock.t,
    performance: { memory: null, now: () => clock.t },
    requestAnimationFrame: () => 0,
    setInterval: (cb) => { intervalCb = cb; return 1; },
    clearInterval: () => { intervalCb = null; },
    setTimeout, clearTimeout,
    scheduleAudio: () => {},
    toggle: () => {},
    hud: () => {},
    document: { getElementById: () => ({ style: {} }) },
    console,
    paint: () => {
      calls.paint++;
      calls.inFlight++;
      calls.maxInFlight = Math.max(calls.maxInFlight, calls.inFlight);
      return new Promise((res) => pending.push(() => { calls.inFlight--; res(); }));
    },
  };
  vm.createContext(ctx);
  vm.runInContext(SRC + `
    globalThis.__h = {
      tick, tickPumpStart, rafTick,
      setPlaying: (v) => { playing = v; },
    };`, ctx);
  return {
    ctx, clock, calls,
    fire: () => { if (intervalCb) intervalCb(); },
    drain: () => { while (pending.length) pending.shift()(); },
  };
}

// A macrotask turn guarantees every microtask (including tick's continuation
// and its `finally`) has run. A single `await Promise.resolve()` is not enough.
const flush = () => new Promise((r) => setTimeout(r, 0));

test("a slow paint never overlaps another paint", async () => {
  const h = harness();
  h.ctx.__h.setPlaying(true);
  h.ctx.__h.tickPumpStart();

  // Headless: rAF never arrives, so lastRafAt goes stale and the watchdog
  // fires every 33 ms while the first paint is still in flight.
  for (const t of [400, 800, 1200, 1600]) {
    h.clock.t = t;
    h.fire();
    await flush();
  }

  assert.equal(h.calls.maxInFlight, 1,
    `overlapping paints: maxInFlight=${h.calls.maxInFlight} (paint called ${h.calls.paint} times)`);
  h.drain();
  await flush();
});

test("the watchdog still drives frames when paint is fast", async () => {
  const h = harness();
  h.ctx.__h.setPlaying(true);
  h.ctx.__h.tickPumpStart();
  for (const t of [400, 800, 1200]) {
    h.clock.t = t;
    h.fire();
    h.drain();
    await flush();
  }
  assert.ok(h.calls.paint >= 3, `watchdog stopped driving: ${h.calls.paint} paints`);
});