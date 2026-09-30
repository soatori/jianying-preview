// Media scheduling is separate from scene membership. A scene says what should
// be visible; this scheduler decides which media sources may load/decode.

export function audioSourceTimeAt(time, tUs) {
  const target = Number(time?.target_start_us || 0);
  const duration = Math.max(0, Number(time?.target_duration_us || time?.duration_us || 0));
  const local = Math.max(0, Math.min(tUs - target, duration));
  const speed = Number(time?.speed || 1) || 1;
  const offset = Math.round(local * speed);
  const sourceStart = Number(time?.source_start_us || 0);
  if (!time?.reverse) return sourceStart + offset;
  const span = Number(time?.source_duration_us || Math.round(duration * speed));
  return sourceStart + Math.max(span - offset, 0);
}

export class AudioScheduler {
  constructor({ createNode } = {}) {
    this.createNode = createNode || (() => {
      const node = document.createElement("audio");
      document.body.appendChild(node);
      return node;
    });
    this.nodes = new Map();
    this.status = { active: 0, buffering: 0, failed: 0, degraded: [] };
  }

  clear() {
    for (const node of this.nodes.values()) {
      try { node.pause(); } catch (error) { void error; }
      try { node.remove(); } catch (error) { void error; }
    }
    this.nodes.clear();
    this.status = { active: 0, buffering: 0, failed: 0, degraded: [] };
  }

  sync(labels, tUs, playing, soundOn) {
    const wanted = new Map();
    for (const item of labels || []) {
      const audio = item.audio || {};
      if (!audio.exists || !audio.served || item.muted) continue;
      const start = Number(audio.target_start_us || 0);
      const duration = Number(audio.target_duration_us || audio.duration_us || 0);
      if (!(tUs >= start && tUs < start + duration)) continue;
      wanted.set(item.segment_id, {
        src: audio.served,
        volume: Number(item.volume ?? 1),
        speed: Number(audio.speed || 1) || 1,
        reverse: !!audio.reverse,
        offset: audioSourceTimeAt(audio, tUs) / 1e6,
      });
    }
    for (const [id, node] of this.nodes) {
      if (wanted.has(id)) continue;
      try { node.pause(); } catch (error) { void error; }
      try { node.remove(); } catch (error) { void error; }
      this.nodes.delete(id);
    }

    let buffering = 0;
    let failed = 0;
    const degraded = [];
    for (const [id, spec] of wanted) {
      let node = this.nodes.get(id);
      if (!node) {
        node = this.createNode();
        node.src = spec.src;
        node.preload = "auto";
        node.preservesPitch = true;
        node.mozPreservesPitch = true;
        node.webkitPreservesPitch = true;
        this.nodes.set(id, node);
        if (node.addEventListener) node.addEventListener("error", () => { node.dataset.failed = "1"; });
      }
      node.volume = soundOn ? Math.max(0, Math.min(spec.volume, 1)) : 0;
      node.playbackRate = Math.max(0.25, Math.min(spec.speed, 4));
      const drift = (node.currentTime || 0) - spec.offset;
      if (Math.abs(drift) > (playing ? 0.3 : 0.05)) {
        try { node.currentTime = spec.offset; } catch (error) { void error; }
      }
      if (spec.reverse) {
        // HTMLAudioElement has no negative playback rate. Keep the exact source
        // position observable and report the unsupported part explicitly.
        degraded.push({ id, render_class: "placeholder", reason: "reverse_audio_unsupported" });
        try { node.pause(); } catch (error) { void error; }
      } else if (playing) {
        if (Number(node.readyState || 0) < 2 && !node.error) buffering += 1;
        const promise = node.play?.();
        if (promise?.catch) promise.catch(() => {});
      } else {
        try { node.pause(); } catch (error) { void error; }
      }
      if (node.error || node.dataset?.failed) failed += 1;
    }
    this.status = { active: wanted.size, buffering, failed, degraded };
    return this.status;
  }
}

export class MediaScheduler {
  constructor(stage, { armLimit, liveLimit }) {
    this.stage = stage;
    this.armLimit = armLimit;
    this.liveLimit = liveLimit;
  }

  prepare(entries, visible, tUs, playing) {
    const candidates = entries.filter((entry) => entry.mediaKind === "video" &&
      this.stage.inWarmRange(entry, tUs)).sort((left, right) => {
      if (!!left.visible !== !!right.visible) return left.visible ? -1 : 1;
      return this.stage.warmDistance(left, tUs) - this.stage.warmDistance(right, tUs);
    });
    const allowed = new Set(candidates.slice(0, this.armLimit).map((entry) => entry.poolKey));
    for (const entry of entries) {
      if (entry.mediaKind !== "video") continue;
      if (!allowed.has(entry.poolKey) || !this.stage.arm(entry, tUs)) this.stage.disarm(entry);
    }

    const videos = visible.filter((item) => item.entry.video && item.entry.armed);
    this.stage.primaryId = videos.length ? videos[0].entry.id : null;
    this.stage.primaryKey = videos.length ? videos[0].entry.poolKey : null;
    const live = new Set();
    if (playing) {
      for (const item of videos) {
        if (live.size >= this.liveLimit) break;
        live.add(item.entry.poolKey);
      }
    }
    return { videos, live };
  }

  drive(visible, live, playing) {
    for (const item of visible) {
      if (item.entry.video) {
        this.stage.driveVideo(item.entry, item.at, playing && live.has(item.entry.poolKey), playing);
      }
    }
  }
}
