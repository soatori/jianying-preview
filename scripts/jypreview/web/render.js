// Layer pool + per-frame evaluation.
//
// The old engine reconciled one instant at a time: `/api/frame` returned the layers
// visible at `t`, `sync()` created a <video> for each of them and threw away everything
// else. A cut therefore meant a fresh HTTP round-trip plus a fresh media load, and
// nothing that changed between two fetches could ever appear.
//
// A playback window IR (`/api/frame?window_us=`) carries every layer that touches the
// span instead. `load()` builds DOM for them once and keeps it; `evalAt(tUs)` then
// decides per frame who is on screen. Cuts, subtitle changes and overlay swaps become
// CSS toggles on nodes that already exist: no request, no reload, no black gap.
import { textGroup } from "./text.js";

export const DRIFT_S = 0.12;        // resync a video only once it drifts further than this
const MAX_POOL = 240;               // hard cap on pooled nodes
const LIVE_LIMIT = 5;               // videos allowed to decode at the same time
// A <video> only starts fetching when it is given a src, so the src is withheld until the
// clip is near the playhead. Mounting every clip in a 20 s window with an eager src asked
// 17-82 elements to range-request one HTTP/1.1 origin at once (Chromium allows ~6
// connections per host), and the clip that had to play queued behind clips nobody could
// see. Sliding the horizon staggers the fetches instead of firing them all at window load.
const WARM_AHEAD_US = 2_000_000;    // start loading a clip this far before it is on screen
const WARM_AFTER_US = 2_000_000;    // keep it loaded this long after, so scrubbing back is free
const SEEK_TOLERANCE_S = 0.05;      // closer than this is not worth a seek
const DISCONTINUITY_S = 0.5;        // beyond this a nudge cannot catch up: seek
const NUDGE_CAP = 0.15;             // max playbackRate correction from one drift hit
const END_CLAMPS = 0.05;            // stop short: decoders stall on the very last sample

/** Media position (µs) for a layer whose timeline time is `timelineUs` (µs).
 *  Mirrors `model/timing.source_time_us`; nested layers carry the *inner* timeline's
 *  seconds, so the same helper maps every level of a compound clip. */
export function mediaTimeAt(time, timelineUs) {
  if (!time) return 0;
  const local = timelineUs - (time.target_start_us || 0);
  const speed = time.speed || 1;
  const offset = Math.round(Math.abs(local) * speed);
  if (time.reverse) {
    const span = time.source_duration_us || Math.round((time.target_duration_us || 0) * speed);
    return (time.source_start_us || 0) + Math.max(span - offset, 0);
  }
  return (time.source_start_us || 0) + offset;
}

/** Animation state for a layer, given its *own* local time (µs from its target start). */
export function animationStateAt(layer, localUs) {
  const anim = layer.animation;
  if (!anim || !anim.approx) return null;
  const start = anim.start_us || 0;
  const duration = anim.duration_us || 0;
  const local = localUs - start;
  if (duration <= 0) return null;
  const progress = Math.max(0, Math.min(local / duration, 1));
  const { impl, from, to } = anim.approx;
  const eased = 1 - Math.pow(1 - progress, 2);
  const value = from + (to - from) * eased;
  const state = { opacity: 1, scale: 1, translate_offset_px: [0, 0], rotation_deg: 0, blur_px: 0 };
  if (impl === "fade" || impl === "crossfade") state.opacity = value;
  else if (impl === "zoom_in" || impl === "zoom_out") state.scale = value;
  else if (impl === "slide_x") state.translate_offset_px = [value * 1000, 0];
  else if (impl === "slide_y") state.translate_offset_px = [0, value * 1000];
  else if (impl === "rotate") state.rotation_deg = value;
  else if (impl === "blur") state.blur_px = Math.max(from * (1 - progress), 0);
  else if (impl === "shake") {
    const offset = (1 - progress) * 18;
    state.translate_offset_px = [Math.sin(progress * 40) * offset, Math.cos(progress * 33) * offset * 0.6];
  } else return null;
  return state;
}

function applyTransform(node, css, state) {
  if (!css || !css.transform) return;
  let transform = css.transform;
  let opacity = css.opacity || "1";
  if (state) {
    if (state.scale !== 1) transform += ` scale(${state.scale})`;
    if (state.translate_offset_px && (state.translate_offset_px[0] || state.translate_offset_px[1])) {
      transform += ` translate(${state.translate_offset_px[0]}px, ${state.translate_offset_px[1]}px)`;
    }
    if (state.rotation_deg) transform += ` rotate(${state.rotation_deg}deg)`;
    opacity = String(Math.min(parseFloat(opacity) * (state.opacity ?? 1), 1));
    node.style.filter = state.blur_px ? `blur(${state.blur_px}px)` : "";
  }
  node.style.transform = transform;
  node.style.opacity = opacity;
}

function compareKeys(a, b) {
  const length = Math.max(a.length, b.length);
  for (let index = 0; index < length; index += 1) {
    const left = a[index];
    const right = b[index];
    if (left === undefined) return -1;
    if (right === undefined) return 1;
    if (left === right) continue;
    return left < right ? -1 : 1;
  }
  return 0;
}

// Composite-clip time mapping: outer local time → the inner timeline's own seconds.
function mapThrough(time, tUs) {
  return (time.source_start_us || 0) + (tUs - (time.target_start_us || 0)) * (time.speed || 1);
}

export class Stage {
  constructor(canvasEl, overlayEl) {
    this.canvas = canvasEl;
    this.overlay = overlayEl;
    this.pool = new Map();       // layer_id -> entry
    this.flat = [];              // entries in paint order
    this.size = null;
    this.soundOn = true;
    this.primaryId = null;
    this.onPlayBlocked = null;
    this.errors = [];
    this.seq = 0;
  }

  setSound(on) {
    this.soundOn = !!on;
  }

  reset(ir) {
    this.size = [ir.canvas.width, ir.canvas.height];
    this.canvas.style.width = `${ir.canvas.width}px`;
    this.canvas.style.height = `${ir.canvas.height}px`;
    this.overlay.setAttribute("viewBox", `0 0 ${ir.canvas.width} ${ir.canvas.height}`);
    this.overlay.setAttribute("width", ir.canvas.width);
    this.overlay.setAttribute("height", ir.canvas.height);
  }

  /** Upsert every layer of `ir` into the pool and rebuild the paint order.
   *  A window IR brings layers that are not on screen yet; they must survive until the
   *  playhead reaches them, and layers from the *previous* window must survive the
   *  prefetch that already loaded the next one. So nothing is dropped here — visibility is
   *  always decided per layer from its own time range, and `evict()` retires old nodes. */
  load(ir) {
    this.errors = [];
    const visiting = [];
    const collect = (layers, chain, anchor, path) => {
      layers.forEach((layer, index) => {
        const here = path.concat([index]);
        const z = layer.z || {};
        if (layer.nest && layer.nest.layers && layer.nest.layers.length) {
          // A compound clip contributes its children, not a box of its own. Python already
          // rescaled them into the parent canvas, so they join the normal layers; putting
          // HTML divs inside an SVG <g> would take them out of layout entirely.
          collect(layer.nest.layers, chain.concat([layer.time || {}]),
                  anchor || [Number(z.global) || 0, String(z.tie || "")], here);
          return;
        }
        // Paint order is anchored on the top-level clip: a compound clip's own children
        // carry the inner timeline's z band, so they must sort with their parent, not with
        // each other. `z.tie` is zero-padded "track/ri/position", which string-compares
        // exactly like the server's `_sort` tuple.
        const own = anchor || [Number(z.global) || 0, String(z.tie || "")];
        visiting.push({ layer, chain, key: own.concat([anchor ? 1 : 0], here) });
      });
    };
    collect(ir.layers || [], [], null, []);

    for (const item of visiting) {
      let entry = this.pool.get(item.layer.layer_id);
      if (!entry) {
        entry = { id: item.layer.layer_id, kind: null, video: null };
        this.pool.set(item.layer.layer_id, entry);
      }
      entry.layer = item.layer;
      entry.chain = item.chain;
      entry.key = item.key;
      entry.depth = item.chain.length;
      try {
        this.build(entry);
      } catch (error) {
        this.errors.push(`${item.layer.layer_id}: ${error.message}`);
      }
    }
    this.repaint();
    this.loadLog = this.loadLog || [];
    this.loadLog.push({ layers: (ir.layers || []).length, visiting: visiting.length,
                        flat: this.flat.length, window: !!ir.window, errors: this.errors.length });
    if (this.loadLog.length > 8) this.loadLog.shift();
    if (this.errors.length) window.__renderErrors = this.errors;
  }

  repaint() {
    this.flat = [...this.pool.values()].sort((a, b) => compareKeys(a.key || [], b.key || []));
    const textNodes = [];
    this.flat.forEach((entry, index) => {
      entry.paint = index + 1;
      if (entry.kind === "text") textNodes.push(entry.root);
      else entry.root.style.zIndex = String(entry.paint);
    });
    this.overlay.replaceChildren(...textNodes);
  }

  /** Create (or re-create) the DOM for one pooled layer. */
  build(entry) {
    const layer = entry.layer;
    if (layer.kind === "text") {
      this.seq += 1;
      const group = textGroup(layer, { seq: this.seq });
      if (!group) return;
      group.dataset.layer = layer.layer_id;
      if (entry.depth === 0) {
        entry.kind = "text";
        entry.root = group;
        return;
      }
      // The shared overlay sits above every media layer, which is right for the timeline's
      // own captions but wrong inside a compound clip, where a sibling clip's picture has to
      // be able to cover the label. Those get their own stacking context so z interleaves.
      let holder = entry.kind === "nested-text" ? entry.root : null;
      if (!holder) {
        holder = document.createElement("div");
        holder.className = "layer nested-text";
        holder.dataset.layer = layer.layer_id;
        const [w, h] = this.size || [0, 0];
        const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
        svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
        svg.setAttribute("width", w);
        svg.setAttribute("height", h);
        holder.appendChild(svg);
        this.canvas.appendChild(holder);
      }
      holder.firstElementChild.replaceChildren(group);
      entry.kind = "nested-text";
      entry.root = holder;
      this.resetTransform(entry);
      return;
    }

    if (entry.kind === "text" || entry.kind === "nested-text") {
      entry.root?.remove();
      entry.root = null;
      entry.video = null;
      entry.kind = null;
    }
    if (!entry.root) {
      entry.root = document.createElement("div");
      entry.root.className = "layer";
      entry.root.dataset.layer = layer.layer_id;
      this.canvas.appendChild(entry.root);
      entry.kind = "media";
    }
    const media = layer.media;
    const css = layer.css || (layer.rect && layer.rect.css) || {};
    entry.root.style.width = css.width || "0";
    entry.root.style.height = css.height || "0";

    if (!media || !media.exists) {
      if (entry.mediaKind !== "tile") {
        entry.root.replaceChildren();
        const tile = document.createElement("div");
        tile.className = "tile";
        const label = document.createElement("span");
        label.textContent = media ? (media.material_name || "素材") : (layer.kind || "图层");
        const why = document.createElement("small");
        why.textContent = media
          ? `素材不可用（${media.how || "missing"}）· ${(media.path_raw || "").slice(-46)}`
          : layer.nest ? `复合片段 ${layer.nest.reason || ""}`.slice(0, 90) : "";
        tile.append(label, why);
        entry.root.appendChild(tile);
        if (entry.video) { entry.video.pause(); entry.video = null; }
        entry.mediaKind = "tile";
      }
      this.resetTransform(entry);
      return;
    }

    if (media.family === "image" || media.material_type === "photo") {
      if (entry.mediaKind !== "image") {
        entry.root.replaceChildren();
        const img = new Image();
        img.src = media.path_served;
        entry.root.appendChild(img);
        if (entry.video) { entry.video.pause(); entry.video = null; }
        entry.mediaKind = "image";
      }
      this.resetTransform(entry);
      return;
    }

    if (entry.mediaKind !== "video") {
      entry.root.replaceChildren();
      const video = document.createElement("video");
      video.muted = true;
      video.playsInline = true;
      // Rate nudging must not change pitch.
      video.preservesPitch = true;
      video.mozPreservesPitch = true;
      video.webkitPreservesPitch = true;
      // No src yet: `arm()` gives it one once the clip approaches the playhead.
      video.preload = "auto";
      entry.root.appendChild(video);
      entry.video = video;
      entry.mediaKind = "video";
      entry.src = media.path_served;
      entry.armed = null;
    }
    this.resetTransform(entry);
  }

  /** Give the element its source once its clip is close enough to be worth fetching.
   *  Returns true when the element now has a resource it can decode. */
  arm(entry, tUs) {
    if (!entry.video || !entry.src) return !!entry.video;
    if (entry.armed === entry.src) return true;
    const time = entry.layer.time || {};
    const start = time.target_start_us || 0;
    const end = start + (time.target_duration_us || 0);
    if (tUs < start - WARM_AHEAD_US || tUs > end + WARM_AFTER_US) return false;
    entry.video.src = entry.src;
    entry.armed = entry.src;
    return true;
  }

  /** Evaluate the layer's own local time, walking the compound-clip chain.
   *  Returns null when the layer — or any ancestor clip — is out of range. */
  timeAt(entry, tUs) {
    let cursor = tUs;
    let local = 0;
    for (const time of entry.chain) {
      local = cursor - (time.target_start_us || 0);
      if (!(local >= 0 && local < Math.max(time.target_duration_us || 0, 0))) return null;
      cursor = mapThrough(time, cursor);
    }
    const time = entry.layer.time || {};
    local = cursor - (time.target_start_us || 0);
    if (!(local >= 0 && local < Math.max(time.target_duration_us || 0, 0))) return null;
    return { local, media: mediaTimeAt(time, cursor) };
  }

  videoOf(layerId) {
    const entry = this.pool.get(layerId);
    return entry ? entry.video || null : null;
  }

  /** Bottom-most visible video layer: 剪映's main shot and the clock's reference. */
  primaryAt(tUs) {
    for (const entry of this.flat) {
      if (!entry.video) continue;
      const at = this.timeAt(entry, tUs);
      if (at) return { entry, layer: entry.layer, at };
    }
    return null;
  }

  visibleVideos(tUs) {
    const out = [];
    for (const entry of this.flat) {
      if (!entry.video) continue;
      const at = this.timeAt(entry, tUs);
      if (at) out.push({ entry, at });
    }
    return out;
  }

  /** Per-frame pass: who is on screen, where inside their media, and are they running. */
  evalAt(tUs, playing) {
    const visible = [];
    for (const entry of this.flat) {
      const at = this.timeAt(entry, tUs);
      if (at) visible.push({ entry, at });
      if (entry.visible !== !!at) {
        entry.visible = !!at;
        entry.root.style.display = at ? "" : "none";
        // `data-hidden` is what window.__settle() reads: a pooled video parked off screen
        // must never hold a screenshot hostage.
        if (at) delete entry.root.dataset.hidden;
        else entry.root.dataset.hidden = "1";
      }
    }

    // Fetch only what the sliding horizon covers. This runs before anything reads
    // `readyState`, so a clip that is about to start has been loading for up to
    // WARM_AHEAD_US by the time the cut arrives.
    for (const entry of this.flat) {
      if (entry.mediaKind === "video") this.arm(entry, tUs);
    }

    const videos = visible.filter((item) => item.entry.video && item.entry.armed);
    this.primaryId = videos.length ? videos[0].entry.id : null;
    const live = new Set();
    if (playing) {
      for (const item of videos) {
        if (live.size >= LIVE_LIMIT) break;
        live.add(item.entry.id);   // paint order = bottom-most first: the main shot wins
      }
    }

    for (const item of visible) {
      const { entry, at } = item;
      if (entry.video) this.driveVideo(entry, at, playing && live.has(entry.id), playing);
      // Text and label layers carry their geometry inside the SVG they build, so an
      // animated CSS transform on them would stack on top of it. Only media boxes animate,
      // which is also exactly what the previous engine did.
      if (entry.kind !== "media") continue;
      if (entry.layer.animation) {
        const state = animationStateAt(entry.layer, at.local);
        if (state) applyTransform(entry.root, entry.layer.css || (entry.layer.rect || {}).css, state);
        else this.resetTransform(entry);
      } else {
        this.resetTransform(entry);
      }
    }
    for (const entry of this.flat) {
      if (entry.visible || !entry.video) continue;
      if (!entry.video.paused) entry.video.pause();
    }
  }

  resetTransform(entry) {
    applyTransform(entry.root, entry.layer.css || (entry.layer.rect && entry.layer.rect.css) || {}, null);
  }

  /** A visible video plays from its trimmed in-point; a hidden one is parked.
   *
   *  Continuous drift is corrected with `playbackRate`, not with a seek. Every seek can
   *  restart a keyframe/GOP decode, and the measured failure was one clip taking 15
   *  `currentTime` writes in 22 s — each one stalling the pipeline it was chasing. A hard
   *  seek is reserved for a real discontinuity: a cut, a scrub, a window swap.
   *
   *  Reverse is a property of the timeline, never of the element: `mediaTimeAt` already
   *  walks the source backwards, so a reversed clip is stepped by seek. HTMLMediaElement
   *  has no negative rate. */
  driveVideo(entry, at, running, timelineRolling) {
    const video = entry.video;
    const time = entry.layer.time || {};
    const speed = time.speed || 1;
    const duration = Number.isFinite(video.duration) ? video.duration : 0;
    // Decoders stall or hand back an empty frame on the very last sample.
    const wanted = Math.min(at.media / 1e6, duration ? duration - END_CLAMPS : Infinity);
    const base = Math.max(0.25, Math.min(speed, 4));
    const now = performance.now();

    // A target further away than the clock could have carried since last frame is a
    // discontinuity, not drift.
    const elapsed = entry.lastWantedAt ? (now - entry.lastWantedAt) / 1000 : 0;
    const jumped = entry.lastWanted === undefined
      || Math.abs(wanted - entry.lastWanted) > Math.max(DISCONTINUITY_S, elapsed * base * 2);
    entry.lastWanted = wanted;
    entry.lastWantedAt = now;

    // A seek that never got its `seeked` back would otherwise wedge the element forever.
    if (entry.seekInFlight && now - (entry.seekStarted || 0) > 1500) entry.seekInFlight = false;

    if (running && !time.reverse) {
      if (video.readyState < 2) { this.seekTo(entry, video, wanted); return; }
      const drift = (video.currentTime || 0) - wanted;      // < 0: behind the timeline
      if (jumped || Math.abs(drift) > DRIFT_S) {
        this.seekTo(entry, video, wanted);
        video.playbackRate = base;
      } else {
        const correction = Math.min(NUDGE_CAP, Math.max(0.02, Math.abs(drift) * 0.2));
        const rate = Math.max(0.25, Math.min(4,
          drift < 0 ? base * (1 + correction) : base * (1 - correction)));
        if (Math.abs(video.playbackRate - rate) > 0.01) video.playbackRate = rate;
      }
      video.muted = !(this.primaryId === entry.id && this.soundOn);
      if (video.paused) {
        const promise = video.play();
        if (promise && promise.catch) {
          promise.catch(() => {
            // Blocked autoplay must not cost the picture: fall back to muted so the frame
            // keeps running and the sound button tells the truth about what happened.
            if (!video.muted) {
              video.muted = true;
              this.soundOn = false;
              if (this.onPlayBlocked) this.onPlayBlocked();
              video.play().catch(() => {});
            }
          });
        }
      }
      return;
    }

    if (!video.paused) video.pause();
    video.playbackRate = base;
    const drift = Math.abs((video.currentTime || 0) - wanted);
    if (drift <= (jumped ? 0 : SEEK_TOLERANCE_S)) return;
    if (timelineRolling && !time.reverse) {
      // Over the decoder budget while the timeline rolls: hold the frame that is already
      // there rather than queueing seeks behind the clips that are actually playing.
      return;
    }
    this.seekTo(entry, video, wanted);
  }

  /** One seek in flight per element. A target that arrives while the browser is still
   *  seeking is remembered and replayed on `seeked`, instead of being assigned on top of
   *  the running seek — which the browser silently drops, leaving a stale frame. */
  seekTo(entry, video, seconds) {
    if (video.readyState < 1) return;      // nothing to seek into yet; preload is still fetching
    if (video.seeking || entry.seekInFlight) {
      entry.pendingSeek = seconds;
      return;
    }
    if (Math.abs((video.currentTime || 0) - seconds) < 0.005) return;
    entry.seekInFlight = true;
    entry.seekStarted = performance.now();
    entry.pendingSeek = null;
    const done = () => {
      entry.seekInFlight = false;
      if (entry.pendingSeek !== null && entry.pendingSeek !== undefined) {
        const next = entry.pendingSeek;
        entry.pendingSeek = null;
        this.seekTo(entry, video, next);
      }
    };
    video.addEventListener("seeked", done, { once: true });
    try {
      video.currentTime = seconds;
    } catch (error) {
      video.removeEventListener("seeked", done);
      entry.seekInFlight = false;
    }
  }

  /** Free nodes the playhead has left behind, then cap the pool.
   *  A node whose clip ended well before the playhead can never be needed again in this
   *  direction of travel: seeking back re-loads its window and `build()` re-creates it. */
  evict(tUs) {
    for (const entry of [...this.pool.values()]) {
      if (entry.depth) continue;   // nested layers follow their parent clip's lifetime
      const time = entry.layer.time || {};
      const end = (time.target_start_us || 0) + (time.target_duration_us || 0);
      if (end < tUs - 20_000_000) this.drop(entry);
    }
    if (this.pool.size <= MAX_POOL) return;
    const rest = [...this.pool.values()].filter((entry) => !entry.depth)
      .sort((a, b) => ((a.layer.time || {}).target_start_us || 0) - ((b.layer.time || {}).target_start_us || 0));
    for (const entry of rest) {
      if (this.pool.size <= MAX_POOL) break;
      this.drop(entry);
    }
    this.repaint();
  }

  drop(entry) {
    try { entry.video?.pause?.(); } catch (error) { void error; }
    entry.root?.remove();
    this.pool.delete(entry.id);
  }

  /** Drop everything: the pool belongs to one timeline, and timelines do not share ids. */
  clear() {
    for (const entry of [...this.pool.values()]) this.drop(entry);
    this.flat = [];
    this.overlay.replaceChildren();
  }

  highlight(layerId) {
    for (const entry of this.pool.values()) {
      entry.root.classList.toggle("selected", entry.id === layerId);
    }
  }
}
