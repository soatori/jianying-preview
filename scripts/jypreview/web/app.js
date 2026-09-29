import { Stage } from "./render.js";
import { renderInfo, renderProps, fmtUs } from "./props.js";

const $ = (id) => document.getElementById(id);
const stageEl = $("stage");
const overlay = $("overlay");
const fit = document.createElement("div");
const canvasEl = document.createElement("div");
canvasEl.className = "canvas";
fit.appendChild(canvasEl);
stageEl.replaceChildren(fit);
canvasEl.appendChild(overlay);
const view = new Stage(canvasEl, overlay);

const params = new URLSearchParams(location.search);
// Snapshot the deep-link before anything rewrites it. `openDraft`/`selectTimeline` push the
// timeline they picked back into `params`, so reading `params` after the draft is open reports
// the app's own choice — which re-selected the same timeline, clearing the layer pool that had
// just been built and costing a second frame fetch (one blank frame at play start).
const deepLink = { did: params.get("draft") || "", timeline: params.get("timeline") || "",
                   t: params.get("t") };
const audioNodes = new Map();

// Playback runs off a *window* IR: every layer touching [t, t+WINDOW) arrives in one
// response and stays in the DOM pool, so a cut is a CSS toggle rather than a request plus
// a media reload. The playhead clock is the wall clock, corrected by the main shot.
const WINDOW_US = 20_000_000;    // how much timeline one request covers
const PREFETCH_US = 3_000_000;   // start loading the next window this early
const CATCHUP_US = 1_500_000;    // ignore media positions this far from the clock

const state = {
  did: null, tid: null, tUs: 0, playing: false, rate: 1, scale: 1,
  ir: null, trackmap: null, describe: null, durationUs: 0, fps: 30, frameDurUs: 33333,
  lastFetch: 0, pending: null, selected: null, autoSelected: null, lastFolder: "",
  ratio: params.get("ratio") || "draft", primary: null, span: null, sound: true, zoom: 0,
  windowRange: null, buffering: false,
};

let windowJob = null;

async function api(path, query = {}, method = "GET") {
  const url = new URL(path, location.origin);
  for (const [key, value] of Object.entries(query)) {
    if (value !== null && value !== undefined && value !== "") url.searchParams.set(key, value);
  }
  const response = await fetch(url, { method });
  const payload = await response.json();
  if (!payload.ok) {
    const error = new Error(`${payload.code}: ${payload.reason}`);
    error.code = payload.code;
    error.data = payload.data || {};
    throw error;
  }
  return payload.data;
}

function clearCandidates() {
  const old = document.getElementById("candidates");
  if (old) old.remove();
}

function renderCandidates(error) {
  const items = (error.data && error.data.candidates) || [];
  clearCandidates();
  const box = document.createElement("div");
  box.id = "candidates";
  box.className = "candidates";
  const label = document.createElement("span");
  label.textContent = (error.data && error.data.hint)
    ? `没找到该草稿：${error.data.hint}。相近的草稿：` : "没找到该草稿，你是想打开：";
  box.appendChild(label);
  if (!items.length) {
    const tip = document.createElement("span");
    tip.textContent = "（无相近名称。可粘贴完整草稿文件夹路径，或点「重建索引」后再试。）";
    box.appendChild(tip);
  }
  for (const item of items) {
    const chip = document.createElement("button");
    chip.className = "chip";
    chip.title = item.path || item.did;
    chip.textContent = `${item.name} · ${item.mtime || ""}`;
    chip.onclick = () => openDraft(item.did);
    box.appendChild(chip);
  }
  $("warnings").replaceChildren(box);
}

function note(text, bad = false) {
  const li = document.createElement("li");
  li.textContent = text;
  if (bad) li.style.color = "var(--miss)";
  $("warnings").appendChild(li);
}

function fitStage() {
  if (!state.ir) return;
  const { width, height } = state.ir.canvas;
  const bare = document.body.classList.contains("bare");
  const box = stageEl.getBoundingClientRect();
  const fitScale = Math.max(Math.min(box.width / width, box.height / height) * 0.98, 0.02);
  // zoom 0 means "fit to the stage box"; anything else is an explicit pixel scale.
  const scale = bare ? 1 : (state.zoom || fitScale);
  state.scale = scale;
  canvasEl.style.width = `${width}px`;
  canvasEl.style.height = `${height}px`;
  canvasEl.style.transform = `scale(${scale})`;
  fit.style.width = `${width * scale}px`;
  fit.style.height = `${height * scale}px`;
  overlay.style.width = `${width}px`;
  overlay.style.height = `${height}px`;
  paintZoom();
}

async function openDraft(selector) {
  const wanted = String(selector || "").trim();
  if (!wanted) return;
  togglePlay(false);
  $("pick").disabled = true;
  clearCandidates();
  const started = Date.now();
  $("clock").textContent = "解密中…";
  const tick = setInterval(() => {
    $("clock").textContent = `解密中… ${((Date.now() - started) / 1000).toFixed(0)}s`;
  }, 500);
  try {
    const data = await api("/api/timelines", { draft: wanted });
    state.did = data.did;
    state.describe = data;
    params.set("draft", data.did);
    history.replaceState(null, "", `?${params}`);
    state.lastFolder = String(data.path || "").replace(/[\\/][^\\/]*[\\/]$/, "") || data.path;
    $("reload").disabled = false;
    $("scrub").disabled = false;
    $("timelines").disabled = false;
    const select = $("timelines");
    select.replaceChildren();
    for (const item of data.timelines) {
      const option = document.createElement("option");
      option.value = item.id;
      const ratio = item.media_hit_ratio && item.media_hit_ratio.ratio !== null
        ? ` · 素材${Math.round(item.media_hit_ratio.ratio * 100)}%` : "";
      option.textContent = `${item.name || item.id.slice(0, 8)} · ${((item.duration_us || 0) / 1e6).toFixed(1)}s`
        + (item.active ? " ★" : "") + (item.deleted ? " (已删)" : "") + ratio;
      if (item.active) option.selected = true;
      select.appendChild(option);
    }
    if (data.mirror_drift && data.mirror_drift.drift) {
      note(`根 draft_content.json 是时间线 ${String(data.mirror_drift.root_timeline_id).slice(0, 8)} 的镜像，`
        + `而活动时间是 ${String(data.mirror_drift.active_timeline_id).slice(0, 8)} —— 预览只读 Timelines/<id> 下的内容`);
    }
    if (!data.active_timeline_id) {
      $("clock").textContent = "该草稿有多条时间线且剪映未标记活动项，请手动选择";
      note("活动时间线有歧义：预览器不会替你猜，请在下拉里选一条", true);
      return;
    }
    await selectTimeline(data.active_timeline_id);
  } catch (error) {
    const secs = ((Date.now() - started) / 1000).toFixed(1);
    $("clock").textContent = `打开失败 (${secs}s)`;
    showTimelineHint(`未打开草稿 · 打开失败：${error.code || error.message}`);
    if (error.code === "draft_not_found" || error.code === "draft_without_content") {
      renderCandidates(error);
    } else {
      note(`打开失败：${error.message}`, true);
    }
    window.__error = String(error.message);
    window.__ready = true;
  } finally {
    clearInterval(tick);
    $("pick").disabled = false;
  }
}

async function selectTimeline(tid) {
  if (!tid || !state.did) return;
  togglePlay(false);
  state.tid = tid;
  params.set("timeline", tid);
  history.replaceState(null, "", `?${params}`);
  $("fontcss").href = `/api/fonts.css?draft=${state.did}&timeline=${tid}`;
  state.trackmap = await api("/api/trackmap", { draft: state.did, timeline: tid });
  state.durationUs = Math.max(state.trackmap.duration_us || 0, 1);
  state.fps = state.trackmap.fps || 30;
  state.frameDurUs = Math.round(1e6 / state.fps);
  state.windowRange = null;
  state.windowIr = null;
  state.ir = null;
  view.clear();
  $("scrub").max = String(Math.round(state.durationUs / 1000));
  drawLanes();
  await fetchFrame(0, true);
}

// -- frames ------------------------------------------------------------------
// Two channels share one layer pool: a point query for seeking/screenshots (exact
// composition at t), and a window query for playback (everything that will ever be
// needed around t, so no request is made while the timeline is rolling).

async function fetchFrame(tUs, exact = false) {
  if (!state.did || !state.tid) return;
  // While the timeline is rolling, the window IR owns the pool. A point query would
  // replace it with the single instant and blank everything the window had staged.
  if (state.playing) { loadWindowAt(tUs); return; }
  const now = performance.now();
  if (!exact && now - state.lastFetch < 120) return;
  state.lastFetch = now;
  if (state.pending) return;
  window.__ready = false;
  state.pending = api("/api/frame", { draft: state.did, timeline: state.tid,
    t_us: Math.round(tUs), ratio: state.ratio === "draft" ? "" : state.ratio })
    .then((ir) => applyFrame(ir))
    .catch((error) => {
      window.__error = String(error && error.message);
      $("warnings").replaceChildren();
      note(`取帧失败：${window.__error}`, true);
    })
    .finally(() => { state.pending = null; window.__ready = true; });
  await state.pending;
}

function applyFrame(ir) {
  state.ir = ir;
  state.span = timelineSpan(ir);
  view.reset(ir);
  view.load(ir);
  view.evalAt(state.tUs, state.playing);
  state.primary = view.primaryAt(state.tUs);
  fitStage();
  refreshPanels(ir);
  syncAudio(state.tUs, state.playing);
  view.highlight(null);
  markSelectedSegment(null);
}

/** Load the window that starts at (or before) `fromUs` and adopt it as the playable span. */
function loadWindowAt(fromUs) {
  if (windowJob) return windowJob;
  const base = Math.max(0, Math.min(Math.round(fromUs), Math.max(state.durationUs - 1_000_000, 0)));
  const length = Math.min(WINDOW_US, Math.max(state.durationUs - base, 1_000_000));
  window.__ready = false;
  windowJob = api("/api/frame", { draft: state.did, timeline: state.tid, t_us: base,
    window_us: length, ratio: state.ratio === "draft" ? "" : state.ratio })
    .then((ir) => {
      if (!ir.window) return null;
      state.ir = ir;
      state.windowIr = ir;
      state.windowRange = [ir.window.from_us, ir.window.to_us];
      view.reset(ir);
      view.load(ir);
      view.evict(state.tUs);
      view.evalAt(state.tUs, state.playing);
      state.primary = view.primaryAt(state.tUs);
      fitStage();
      refreshPanels(ir);
      return ir;
    })
    .catch((error) => {
      window.__error = String(error && error.message);
      note(`取窗口失败：${error.message}`, true);
      state.windowRange = null;
      return null;
    })
    .finally(() => { windowJob = null; window.__ready = true; });
  return windowJob;
}

function windowCovers(tUs) {
  const range = state.windowRange;
  return !!range && tUs >= range[0] && tUs < range[1];
}

/** Re-arm one window ahead while playing; never blocks the frame. */
function prefetchWindow() {
  const range = state.windowRange;
  if (windowJob) return;
  if (!range) { loadWindowAt(state.tUs); return; }
  if (state.tUs >= range[1] - PREFETCH_US) loadWindowAt(range[1]);
}

function timelineSpan(ir) {
  // Only top-level layers are expressed in this timeline's seconds.
  let start = Infinity;
  let end = -Infinity;
  for (const layer of ir.layers) {
    const time = layer.time || {};
    if (time.target_start_us === undefined) continue;
    start = Math.min(start, time.target_start_us);
    end = Math.max(end, time.end_us ?? (time.target_start_us + (time.target_duration_us || 0)));
  }
  return end < start ? null : [start, end];
}

// -- audio -------------------------------------------------------------------

function audioOffsetUs(audio, tUs) {
  return (audio.source_start_us || 0) + Math.max(tUs - (audio.target_start_us || 0), 0) * (audio.speed || 1);
}

function syncAudio(tUs, playing) {
  const labels = (state.ir && state.ir.audio_labels) || [];
  const wanted = new Map();
  for (const item of labels) {
    const audio = item.audio;
    if (!audio || !audio.exists || !audio.served || item.muted) continue;
    const start = audio.target_start_us || 0;
    const duration = audio.target_duration_us || audio.duration_us || 0;
    if (!(tUs >= start && tUs < start + duration)) continue;
    wanted.set(item.segment_id, { src: audio.served, volume: item.volume,
      offset: audioOffsetUs(audio, tUs) / 1e6 });
  }
  for (const [id, node] of audioNodes) {
    if (!wanted.has(id)) { node.pause(); node.remove(); audioNodes.delete(id); }
  }
  for (const [id, spec] of wanted) {
    let node = audioNodes.get(id);
    if (!node) {
      node = document.createElement("audio");
      node.src = spec.src;
      node.preload = "auto";
      audioNodes.set(id, node);
      document.body.appendChild(node);
    }
    node.volume = state.sound ? Math.max(0, Math.min(spec.volume ?? 1, 1)) : 0;
    if (playing && node.paused) {
      if (Math.abs((node.currentTime || 0) - spec.offset) > 0.3) node.currentTime = spec.offset;
      node.play().catch(() => {});
    } else if (!playing) {
      if (!node.paused) node.pause();
      if (Math.abs((node.currentTime || 0) - spec.offset) > 0.05) {
        try { node.currentTime = spec.offset; } catch (error) { void error; }
      }
    }
  }
}


// Lanes carry no properties: only coloured blocks in JianYing's stacking order
// (visual tracks top = foreground, audio below), everything else lives in the side panel.
const RULER_STEPS = [500_000, 1_000_000, 2_000_000, 5_000_000, 10_000_000, 15_000_000,
  30_000_000, 60_000_000, 120_000_000, 300_000_000, 600_000_000];

function tickLabel(us, step) {
  const seconds = us / 1e6;
  if (step < 1e6) return `${seconds.toFixed(1)}s`;
  const whole = Math.round(seconds);
  const minutes = Math.floor(whole / 60);
  return minutes ? `${minutes}:${String(whole % 60).padStart(2, "0")}` : `${whole}s`;
}

function buildRuler() {
  const total = Math.max(state.durationUs, 1);
  const step = RULER_STEPS.find((candidate) => total / candidate <= 12) || RULER_STEPS[RULER_STEPS.length - 1];
  const row = document.createElement("div");
  row.className = "lane ruler";
  const name = document.createElement("div");
  name.className = "name";
  name.textContent = "时间";
  const bar = document.createElement("div");
  bar.className = "rulerbar";
  const marks = [];
  for (let value = 0; value <= total; value += step) marks.push(value);
  marks.forEach((value, index) => {
    const percent = (value / total) * 100;
    const tick = document.createElement("i");
    tick.style.left = `${percent}%`;
    const label = document.createElement("span");
    label.textContent = tickLabel(value, step);
    label.style.left = `${percent}%`;
    // keep the end labels inside the bar instead of hanging off the edge
    if (index === 0) label.style.transform = "none";
    else if (index === marks.length - 1) label.style.transform = "translateX(-100%)";
    bar.append(tick, label);
  });
  bar.onclick = (event) => {
    const rect = bar.getBoundingClientRect();
    seek(((event.clientX - rect.left) / rect.width) * state.durationUs);
  };
  row.append(name, bar);
  return row;
}

function drawLanes() {
  const lanes = $("lanes");
  lanes.replaceChildren();
  if (!state.trackmap) return;
  lanes.appendChild(buildRuler());
  const total = Math.max(state.durationUs, 1);
  let lastGroup = null;
  for (const track of state.trackmap.tracks) {
    if (lastGroup && lastGroup !== track.group) {
      const divider = document.createElement("div");
      divider.className = "divider";
      divider.textContent = track.group === "audio" ? "音频轨" : "画面轨";
      lanes.appendChild(divider);
    }
    lastGroup = track.group;
    const lane = document.createElement("div");
    lane.className = "lane";
    const name = document.createElement("div");
    name.className = "name";
    const strong = document.createElement("b");
    strong.textContent = track.type;
    name.appendChild(strong);
    name.appendChild(document.createTextNode(` · z${track.z_ri} · ${track.segment_count}`));
    name.title = `轨道 ${(track.name || "").trim() || "(未命名)"}\n数组序号 ${track.index} · render_index ${track.z_ri}\n片段 ${track.segment_count}`;
    const bar = document.createElement("div");
    bar.className = "track";
    for (const segment of track.segments) {
      const block = document.createElement("div");
      block.className = `seg ${track.type}`;
      block.dataset.segment = segment.segment_id;
      block.style.left = `${(segment.start_us / total) * 100}%`;
      block.style.width = `${Math.max((segment.duration_us / total) * 100, 0.25)}%`;
      block.title = `${segment.name || "(无名称)"}\n${fmtUs(segment.start_us)} + ${fmtUs(segment.duration_us)}\n片段 ${segment.segment_id}`;
      const caption = document.createElement("span");
      caption.textContent = segment.name || "";
      block.appendChild(caption);
      block.onclick = (event) => { event.stopPropagation(); selectSegment(segment, track); };
      bar.appendChild(block);
    }
    const head = document.createElement("div");
    head.className = "playhead";
    bar.appendChild(head);
    bar.onclick = (event) => {
      const rect = bar.getBoundingClientRect();
      seek(((event.clientX - rect.left) / rect.width) * state.durationUs);
    };
    lane.append(name, bar);
    lanes.appendChild(lane);
  }
  if (!lastGroup) lanes.appendChild(Object.assign(document.createElement("div"), { className: "empty", textContent: "该时间线没有片段" }));
}

function findLayer(ir, layerId) {
  if (!ir) return null;
  const walk = (layers) => {
    for (const layer of layers) {
      if (layer.layer_id === layerId) return layer;
      if (layer.nest && layer.nest.layers) {
        const inner = walk(layer.nest.layers);
        if (inner) return inner;
      }
    }
    return null;
  };
  return walk(ir.layers);
}

function selectSegment(segment, track) {
  const layer = findLayer(state.ir, segment.segment_id);
  renderProps($("props"), instantCopy(layer) || {
    kind: track.type, layer_id: segment.segment_id, track,
    time: { target_start_us: segment.start_us, target_duration_us: segment.duration_us,
            end_us: segment.start_us + segment.duration_us,
            source_start_us: segment.source_start_us, speed: segment.speed },
    z: { order: track.lane, source: "lane" },
    media: { material_name: segment.name, path_raw: null, exists: false, how: "此刻不在画面上（未播放到）" },
    labels: [], rect: {},
  }, { raw: false });
  markSelectedSegment(layer ? layer.layer_id : segment.segment_id);
}

/** A window IR samples `local_us` / `source_time_us` once, at the window's edge; the
 *  properties panel must show them for the playhead instead. */
function instantCopy(layer) {
  if (!layer || !layer.time) return layer;
  const entry = view.pool.get(layer.layer_id);
  if (!entry) return layer;
  const at = view.timeAt(entry, state.tUs);
  if (!at) return layer;
  const duration = Math.max(layer.time.target_duration_us || 0, 1);
  return { ...layer, time: { ...layer.time, local_us: Math.round(at.local),
    source_time_us: Math.round(at.media), progress: Math.round((at.local / duration) * 1000) / 1000 } };
}

function topVisibleLayer() {
  let best = null;
  for (const entry of view.flat) {
    if (!entry.visible) continue;
    best = entry;
  }
  return best ? best.layer : null;
}

function markSelectedSegment(layerId) {
  for (const block of $("lanes").querySelectorAll(".seg")) {
    block.classList.toggle("selected", block.dataset.segment === layerId);
  }
}

function movePlayhead() {
  const percent = `${(state.tUs / Math.max(state.durationUs, 1)) * 100}%`;
  for (const head of $("lanes").querySelectorAll(".playhead")) head.style.left = percent;
  $("scrub").value = String(Math.round(state.tUs / 1000));
}

function seek(tUs, exact = true) {
  state.tUs = Math.max(0, Math.min(tUs, state.durationUs || tUs));
  movePlayhead();
  // A jump outside the loaded window invalidates it: playback must not keep rolling on a
  // span that no longer contains the playhead.
  if (!windowCovers(state.tUs)) {
    state.windowRange = null;
    if (state.playing) { loadWindowAt(state.tUs); return; }
  }
  if (state.pending) state.pending.then(() => fetchFrame(state.tUs, exact));
  else fetchFrame(state.tUs, exact);
}

// Where the playhead is, given how far the main shot has run. Nested layers count in the
// compound clip's own seconds, so the value is mapped back out through the chain.
function invertThrough(time, value) {
  return (value - (time.source_start_us || 0)) / (time.speed || 1) + (time.target_start_us || 0);
}

function correctClock() {
  const primary = view.primaryAt(state.tUs);
  state.primary = primary;
  if (!primary) return;
  const video = primary.entry.video;
  const time = primary.layer.time || {};
  if (!video || video.paused || !Number.isFinite(video.duration)) return;
  const speed = time.speed || 1;
  const local = (video.currentTime * 1e6 - (time.source_start_us || 0)) / speed;
  if (!(local >= 0 && local < Math.max(time.target_duration_us || 0, 0))) return;
  // `local` is measured inside the clip; the playhead lives on the outer timeline.
  let implied = local + (time.target_start_us || 0);
  for (let index = primary.entry.chain.length - 1; index >= 0; index -= 1) {
    implied = invertThrough(primary.entry.chain[index], implied);
  }
  if (Math.abs(implied - state.tUs) < CATCHUP_US) state.tUs = Math.max(0, implied);
}

let previous = performance.now();
function loop(now) {
  const delta = Math.min(now - previous, 250);
  previous = now;
  if (state.playing && !state.buffering) {
    state.tUs = Math.max(0, Math.min(state.tUs + delta * 1000 * state.rate, state.durationUs));
    correctClock();
    movePlayhead();
    view.evalAt(state.tUs, true);
    syncAudio(state.tUs, true);
    prefetchWindow();
    if (state.tUs >= state.durationUs - 1000) togglePlay(false);
  }
  if (state.playing) {
    const suffix = state.buffering ? " · 缓冲中…" : "";
    $("clock").textContent = `${(state.tUs / 1e6).toFixed(3)}s${suffix}`;
  }
  requestAnimationFrame(loop);
}

function paintPlay() {
  const label = state.playing ? "暂停" : "播放";
  const button = $("play");
  button.classList.toggle("playing", state.playing);
  button.title = label;
  button.setAttribute("aria-label", label);
}

function togglePlay(force) {
  const next = force === undefined ? !state.playing : force;
  if (next === state.playing) return;
  if (next && !state.tid) return;   // nothing loaded yet: the button must not lie
  state.playing = next;
  paintPlay();
  previous = performance.now();
  if (state.playing) {
    if (windowCovers(state.tUs)) {
      state.buffering = false;
      view.evalAt(state.tUs, true);
    } else {
      state.buffering = true;
      loadWindowAt(state.tUs).then(() => { state.buffering = false; previous = performance.now(); });
    }
    syncAudio(state.tUs, true);
  } else {
    state.buffering = false;
    view.evalAt(state.tUs, false);
    syncAudio(state.tUs, false);
  }
}

function refreshPanels(ir) {
  const shown = state.selected ? findLayer(ir, state.selected) : null;
  renderProps($("props"), instantCopy(shown || topVisibleLayer()), { raw: true });
  renderInfo($("info"), ir, state.describe, { cache: state.describe && state.describe.cache });
  $("warnings").replaceChildren(...(ir.warnings || []).map((text) => {
    const li = document.createElement("li");
    li.textContent = text;
    return li;
  }));
  $("clock").textContent = `${(ir.time.t_us / 1e6).toFixed(3)}s  f${ir.time.frame_index}`;
  const scope = ir.window ? `窗口 ${((ir.window.to_us - ir.window.from_us) / 1e6).toFixed(0)}s`
    : `f${ir.time.frame_index}`;
  $("framerate").textContent = `${state.fps.toFixed(0)}fps · ${ir.layers.length}层 · ${scope} · ${(state.durationUs / 1e6).toFixed(1)}s`;
}

$("pick").onclick = async () => {
  // The OS folder picker does the browsing; the server only returns the chosen path.
  $("pick").disabled = true;
  $("clock").textContent = "等待选择文件夹…";
  try {
    const data = await api("/api/pick-folder", { path: state.lastFolder });
    if (data.cancelled) {
      $("clock").textContent = state.did ? `${(state.tUs / 1e6).toFixed(3)}s` : "未打开草稿";
      return;
    }
    await openDraft(data.path);
  } catch (error) {
    $("clock").textContent = "文件夹选择器不可用";
    note(`系统文件夹选择器不可用（${error.message}）。可在地址栏用 ?draft=<草稿文件夹路径> 打开。`, true);
  } finally {
    $("pick").disabled = false;
  }
};
const FOLD_KEY = "jy-preview.folds";
let folds = {};
try {
  folds = JSON.parse(localStorage.getItem(FOLD_KEY) || "{}") || {};
} catch (error) {
  folds = {};
}

function applyFold(section, folded) {
  section.classList.toggle("folded", folded);
  const header = section.querySelector("h3.fold");
  if (header) header.setAttribute("aria-expanded", folded ? "false" : "true");
}

for (const header of document.querySelectorAll("h3.fold")) {
  const section = header.closest("section");
  const key = header.dataset.fold;
  applyFold(section, !!folds[key]);
  const toggle = (event) => {
    event.preventDefault();
    event.stopPropagation();
    const folded = !section.classList.contains("folded");
    applyFold(section, folded);
    folds[key] = folded;
    try {
      localStorage.setItem(FOLD_KEY, JSON.stringify(folds));
    } catch (error) { void error; }
  };
  header.onclick = toggle;
  header.onkeydown = (event) => {
    if (event.key === "Enter" || event.key === " ") toggle(event);
  };
}

// The zoom lever stays hidden until asked for: the row only carries 缩放, and clicking it
// reveals the slider, the live percentage, and a way back to "fit".
let zoomOpen = false;

function paintZoom() {
  const percent = Math.round((state.zoom || state.scale) * 100);
  const button = $("zoombtn");
  button.title = state.zoom ? `缩放 ${percent}%（点击可固定拉杆）` : `缩放 ${percent}%`;
  button.setAttribute("aria-label", `缩放 ${percent}%`);
  // the icon alone cannot show a number, so mark "not fit" on the button itself
  button.classList.toggle("active", !!state.zoom);
  $("zoompct").textContent = `${percent}%`;
  // never fight the thumb while the pointer is on it
  if (document.activeElement !== $("zoomrange")) $("zoomrange").value = String(percent);
  stageEl.classList.toggle("zoomed", !!state.zoom);
}

// Hover opens it; clicking pins it open for keyboard and touch users.
function setZoomOpen(open) {
  zoomOpen = open;
  $("zoombox").classList.toggle("open", open);
  $("zoombtn").setAttribute("aria-expanded", open ? "true" : "false");
}

$("zoombtn").onclick = () => setZoomOpen(!zoomOpen);
$("zoomrange").oninput = (event) => {
  state.zoom = Math.max(0.05, Number(event.target.value) / 100);
  fitStage();
};
$("zoomfit").onclick = () => {
  state.zoom = 0;
  fitStage();
};

$("play").onclick = () => togglePlay();
$("scrub").addEventListener("input", (event) => seek(Number(event.target.value) * 1000, false));
$("scrub").addEventListener("change", () => seek(state.tUs, true));
$("timelines").onchange = (event) => selectTimeline(event.target.value);

function paintSound() {
  const label = `声音：${state.sound ? "开" : "关"}`;
  const button = $("sound");
  button.classList.toggle("off", !state.sound);
  button.title = label;
  button.setAttribute("aria-label", label);
  button.setAttribute("aria-pressed", state.sound ? "true" : "false");
  view.setSound(state.sound);
}

// The stage may have to mute itself to get the picture moving; keep the button honest about it.
view.onPlayBlocked = () => {
  if (!state.sound) return;
  state.sound = false;
  paintSound();
  note("浏览器拦住了带声音的自动播放，已静音继续播放。点「播放」按钮（真实点击）即可恢复声音。", true);
};

paintSound();
paintPlay();
$("sound").onclick = () => {
  state.sound = !state.sound;
  paintSound();
  syncAudio(state.tUs, state.playing);
};

// 画幅 is the canvas ratio, not a zoom: switching it re-asks the server for geometry rebuilt
// at that ratio (font sizes included), which is what changing 画幅 does inside 剪映.
const RATIOS = [["draft", "原始"], ["16:9", "16:9"], ["16:10", "16:10"], ["4:3", "4:3"],
  ["3:4", "3:4"], ["1:1", "1:1"], ["9:16", "9:16"], ["2:1", "2:1"], ["21:9", "21:9"]];
for (const [value, label] of RATIOS) {
  const option = document.createElement("option");
  option.value = value;
  option.textContent = label;
  $("ratio").appendChild(option);
}
$("ratio").value = RATIOS.some(([value]) => value === state.ratio) ? state.ratio : "draft";
$("ratio").onchange = async (event) => {
  state.ratio = event.target.value;
  params.set("ratio", state.ratio);
  history.replaceState(null, "", `?${params}`);
  state.windowRange = null;
  state.windowIr = null;
  await fetchFrame(state.tUs, true);
  if (state.playing) loadWindowAt(state.tUs);
};

$("reload").onclick = async () => {
  $("reload").textContent = "解密中…";
  try {
    await api("/api/reload", { draft: state.did });
    const data = await api("/api/timelines", { draft: state.did });
    state.describe = data;
    await selectTimeline(state.tid || data.active_timeline_id);
  } catch (error) {
    note(`刷新失败：${error.message}`, true);
  } finally {
    $("reload").textContent = "刷新";
  }
};

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && zoomOpen) { setZoomOpen(false); return; }
  if (["INPUT", "SELECT", "TEXTAREA"].includes(event.target.tagName)) return;
  if (event.code === "Space") { event.preventDefault(); togglePlay(); }
  if (event.code === "ArrowRight") seek(state.tUs + state.frameDurUs);
  if (event.code === "ArrowLeft") seek(state.tUs - state.frameDurUs);
});

new EventSource("/api/events").addEventListener("draft.changed", (event) => {
  const data = JSON.parse(event.data || "{}");
  if (data.did && data.did === state.did) {
    note("检测到草稿文件被改写，正在重新解密…");
    openDraft(state.did);
  }
});

window.__renderAt = async (tUs) => {
  window.__ready = false;
  seek(Number(tUs), true);
  while (state.pending) await state.pending;
  return state.tUs;
};
window.__settle = () => [...document.querySelectorAll("video")].every((video) => {
  // Pooled videos parked outside the current window are not on screen; waiting for them
  // would stall a screenshot forever.
  if (video.closest('[data-hidden="1"]')) return true;
  if (video.readyState >= 2 && video.videoWidth > 0) return !video.seeking;
  if (video.error) return true;   // a broken asset must not hang the screenshot forever
  // Chromium sometimes leaves a freshly attached element at readyState 0 / networkState 2
  // with no load in flight; re-arming it once turns a permanent stall into a normal load.
  if (video.networkState === 0 || (video.readyState === 0 && !video.dataset.rearmed)) {
    video.dataset.rearmed = "1";
    try { video.load(); } catch (error) { void error; }
  }
  return false;
});
window.__state = () => ({ did: state.did, tid: state.tid, tUs: state.tUs, ready: !!window.__ready,
  playing: state.playing, buffering: state.buffering, ratio: state.ratio, scale: state.scale,
  durationUs: state.durationUs, span: state.span, window: state.windowRange,
  pool: view.pool.size, visible: view.flat.filter((entry) => entry.visible).length,
  flat: view.flat.length, loads: view.loadLog || [],
  primary: state.primary ? { id: state.primary.entry.id, kind: state.primary.layer.kind,
    nested: state.primary.entry.depth > 0 } : null });

// What the viewer actually sees right now, read off the DOM pool rather than off the IR:
// the honest way to assert on playback without taking a screenshot.
window.__snapshot = () => ({
  tUs: state.tUs, playing: state.playing, buffering: state.buffering, window: state.windowRange,
  pool: view.pool.size,
  layers: view.flat.filter((entry) => entry.visible).map((entry) => ({
    id: entry.id, kind: entry.layer.kind, depth: entry.depth,
    text: (entry.layer.text || {}).text || null,
    media: (entry.layer.media || {}).material_name || null,
    mediaTime: entry.video ? Math.round(entry.video.currentTime * 1e6) / 1e6 : null,
    paused: entry.video ? entry.video.paused : null,
    seeking: entry.video ? entry.video.seeking : null,
    ready: entry.video ? entry.video.readyState : null,
    rate: entry.video ? entry.video.playbackRate : null,
  })),
});
window.__play = (on) => { togglePlay(on === undefined ? true : !!on); return state.playing; };

// Diagnostics: one line per pooled layer, straight out of the DOM bookkeeping.
window.__layers = () => view.flat.map((entry) => ({
  id: entry.id.slice(0, 8), kind: entry.kind, depth: entry.depth, visible: !!entry.visible,
  display: entry.root.style.display || "(default)", parent: entry.root.parentNode
    ? entry.root.parentNode.id || entry.root.parentNode.className : null,
  start: (entry.layer.time || {}).target_start_us, dur: (entry.layer.time || {}).target_duration_us,
}));
window.__renderErrors = [];
window.__stage = view;   // handle for runtime probes (which path dropped a pooled node)

// The timeline strip carries the "nothing open yet" state, so the empty case is visible where
// the tracks would be rather than only in the small header clock.
function showTimelineHint(text) {
  const lanes = $("lanes");
  lanes.replaceChildren();
  const hint = document.createElement("div");
  hint.className = "empty";
  hint.textContent = text;
  lanes.appendChild(hint);
  $("picker").replaceChildren();
  $("props").replaceChildren();
  $("info").replaceChildren();
}

(async function start() {
  if (params.get("chrome") === "0") document.body.classList.add("bare");
  const wanted = deepLink.did;
  if (wanted) {
    await openDraft(wanted);
    // `openDraft` already loaded the active timeline; only honour a deep link that names a
    // different one, and never re-select what is already on screen.
    if (deepLink.timeline && deepLink.timeline !== state.tid) await selectTimeline(deepLink.timeline);
    if (deepLink.t !== null && deepLink.t !== "") await window.__renderAt(Number(deepLink.t) * 1e6);
  } else {
    $("clock").textContent = "未打开草稿";
    showTimelineHint("未打开草稿 · 点「打开草稿」选择草稿文件夹（URL 也支持 ?draft=<路径>&t=<秒>）");
    window.__ready = true;
  }
  requestAnimationFrame(loop);
})();
