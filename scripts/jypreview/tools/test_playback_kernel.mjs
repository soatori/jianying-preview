import assert from "node:assert/strict";
import { PlaybackController } from "../web/playback.js";
import { EffectRenderer, animationStateAt } from "../web/effects.js";
import { AudioScheduler, audioSourceTimeAt } from "../web/media.js";
import { BrowserPlaybackBackend } from "../web/backend.js";
import { LoadingController } from "../web/loading.js";

function harness({ renderAt } = {}) {
  let raf = null;
  let cancelled = false;
  let now = 0;
  const ticks = [];
  const renders = [];
  const controller = new PlaybackController({
    durationUs: 1_000_000,
    now: () => now,
    schedule: (callback) => { raf = callback; return callback; },
    cancel: () => { cancelled = true; raf = null; },
    isPlayable: () => true,
    renderAt: async (tUs, context) => {
      renders.push({ tUs, context });
      return renderAt ? renderAt(tUs, context) : { ok: true };
    },
    onTick: (tUs) => ticks.push(tUs),
  });
  return {
    controller,
    ticks,
    renders,
    step(ms) { now = ms; assert.ok(raf, "a playing controller must schedule a frame"); raf(ms); },
    wasCancelled: () => cancelled,
  };
}

async function main() {
  {
    const h = harness();
    assert.equal(h.controller.snapshot().phase, "idle");
    h.controller.play();
    assert.equal(h.controller.snapshot().tUs, 0, "initial play must not jump the timeline");
    h.step(100);
    assert.equal(h.controller.snapshot().tUs, 100_000);
    assert.deepEqual(h.ticks, [100_000]);
  }

  {
    const h = harness();
    await h.controller.seek(250_000);
    assert.equal(h.renders.at(-1).tUs, 250_000);
    assert.equal(h.controller.snapshot().phase, "paused");
    h.controller.setTimeline({ durationUs: 2_000_000 });
    assert.equal(h.controller.snapshot().tUs, 0, "timeline switch must reset the playhead");
    assert.equal(h.controller.snapshot().phase, "idle");
  }

  {
    const resolvers = [];
    const h = harness({
      renderAt: () => new Promise((resolve) => { resolvers.push(resolve); }),
    });
    const old = h.controller.seek(100_000);
    const newer = h.controller.seek(200_000);
    resolvers[0]({ ok: true });
    resolvers[1]({ ok: true });
    await old;
    await newer;
    assert.equal(h.controller.snapshot().tUs, 200_000);
    assert.equal(h.controller.snapshot().generation, 2);
  }

  {
    const h = harness();
    h.controller.play();
    h.step(100);
    h.controller.close();
    const before = h.controller.snapshot();
    assert.equal(before.phase, "idle");
    assert.equal(before.closed, true);
    assert.equal(h.wasCancelled(), true);
    assert.throws(() => h.controller.play(), /closed/);
  }

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
    const h = harness();
    const backend = new BrowserPlaybackBackend(h.controller);
    assert.equal(backend.capabilities.name, "browser");
    backend.open({ durationUs: 500_000 });
    assert.equal(backend.snapshot().tUs, 0);
    backend.close();
  }

  {
    const h = harness();
    h.controller.syncExternal(300_000, "playing");
    assert.equal(h.controller.snapshot().tUs, 300_000);
    assert.equal(h.controller.snapshot().phase, "playing");
    assert.equal(h.controller.snapshot().playing, true);
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
console.log("ok: playback controller kernel regressions");
