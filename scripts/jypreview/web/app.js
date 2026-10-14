import { Stage } from "./render.js";
import { renderInfo, renderProps, fmtUs } from "./props.js";
import { MltPlaybackClient } from "./backend.js";
import { LoadingController } from "./loading.js";

const $ = (id) => document.getElementById(id);
const stageEl = $("stage");
const overlay = $("overlay");
const fit = document.createElement("div");
const canvasEl = document.createElement("div");
canvasEl.className = "canvas";
fit.appendChild(canvasEl);
stageEl.replaceChildren(fit);
const nativeFrame = document.createElement("img");
nativeFrame.className = "native-frame";
nativeFrame.alt = "";
nativeFrame.hidden = true;
canvasEl.append(nativeFrame, overlay);
const view = new Stage(canvasEl, overlay);
const loading = new LoadingController($("loading"));

const params = new URLSearchParams(location.search);
// Snapshot the deep-link before anything rewrites it. `openDraft`/`selectTimeline` push the
// timeline they picked back into `params`, so reading `params` after the draft is open reports
// the app's own choice — which re-selected the same timeline, clearing the layer pool that had
// just been built and costing a second frame fetch (one blank frame at play start).
const deepLink = { did: params.get("draft") || "", timeline: params.get("timeline") || "",
                   t: params.get("t") };
const leaseToken = params.get("lease") || "";
const mlt = new MltPlaybackClient();
const display = { objectUrl: "", poll: null, pollBusy: false, frameChain: Promise.resolve() };

const state = {
  did: null, tid: null, tUs: 0, playing: false, scale: 1,
  ir: null, trackmap: null, describe: null, durationUs: 0, fps: 30, frameDurUs: 33333,
  lastFetch: 0, pending: null, lastFolder: "",
  ratio: params.get("ratio") || "draft", primary: null, span: null, sound: true, zoom: 0,
  // epoch guards local UI work across timeline switches; playback identity lives on mlt.
  epoch: 0, phase: "idle", wantPlaying: false, error: null,
  lastSeekIssue: 0, displayedPtsUs: null,
  sourceSha: null,
};

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

// -- MLT playback backend ----------------------------------------------------
// The backend snapshot clock is the only writer of the playhead. Decoder PTS
// and HTTP arrival time are diagnostics: a stalled or reordered frame must
// never drag timeline time backwards.

function syncMltState() {
  if (state.phase === "error") return;   // sticky: only a timeline re-select leaves the error phase
  state.tUs = mlt.tUs;
  state.phase = mlt.phase;
  state.playing = mlt.playing;
  state.error = mlt.error || state.error;
  if (mlt.durationUs > 0 && mlt.durationUs !== state.durationUs) {
    state.durationUs = mlt.durationUs;
    $("scrub").max = String(Math.round(state.durationUs / 1000));
  }
  movePlayhead();
  paintPlay();
  const suffix = state.phase === "buffering" ? " · 缓冲中…" : "";
  $("clock").textContent = `${(state.tUs / 1e6).toFixed(3)}s  f${mlt.frameIndex}${suffix}`;
}

function enterMltError(message) {
  state.error = String(message);
  window.__error = state.error;
  if (state.phase !== "error") note(`播放后端失败：${state.error}`, true);
  state.phase = "error";
  state.playing = false;
  state.wantPlaying = false;
  stopMltPoll();          // no snapshot may clock "playing" over the error
  paintPlay();
}

async function pollMltSnapshot() {
  if (!mlt.playbackId || display.pollBusy) return;   // never overlap snapshot polls
  display.pollBusy = true;
  try {
    const result = await mlt.snapshot();
    if (!result.applied) return;
    syncMltState();
    view.evalAt(state.tUs, state.playing);
    state.primary = view.primaryAt(state.tUs);
  } catch (error) {
    enterMltError(error.message);
  } finally {
    display.pollBusy = false;
  }
}

function startMltPoll() {
  if (display.poll) return;
  display.poll = setInterval(pollMltSnapshot, 100);
}

function stopMltPoll() {
  if (display.poll) clearInterval(display.poll);
  display.poll = null;
}

function frameExpired(ptsUs) {
  if (ptsUs === null || ptsUs === undefined) return false;
  // A frame lagging the backend's snapshot clock by more than one project frame is expired.
  return ptsUs < mlt.tUs - state.frameDurUs;
}

async function showMltFrame(frame) {
  if (!mlt.accepts(frame)) return false;   // identity check before decode
  if (frameExpired(frame.ptsUs)) return false;
  const url = URL.createObjectURL(frame.blob);
  const probe = new Image();
  probe.src = url;
  try {
    await probe.decode();
  } catch (error) {
    void error;
    URL.revokeObjectURL(url);
    return false;
  }
  if (!mlt.accepts(frame)) {               // identity check before swapping the image URL
    URL.revokeObjectURL(url);
    return false;
  }
  if (display.objectUrl) URL.revokeObjectURL(display.objectUrl);
  display.objectUrl = url;
  nativeFrame.src = url;
  nativeFrame.hidden = false;
  state.displayedPtsUs = frame.ptsUs ?? null;
  return true;
}

function queueFrame(frame) {
  display.frameChain = display.frameChain
    .then(() => showMltFrame(frame))
    .catch((error) => enterMltError(`画面解码失败：${error.message}`));
  return display.frameChain;
}

async function renderMltAt(tUs) {
  const result = await mlt.renderAt(tUs);
  if (result.stale || result.superseded) return false;
  if (result.ended) {
    syncMltState();
    return true;
  }
  await queueFrame(result);
  syncMltState();
  // Seek while playing: resume only after the latest seek acknowledgment.
  if (result.requestId === mlt.issued && state.wantPlaying
      && mlt.phase !== "playing" && mlt.phase !== "ended") {
    try {
      await mlt.play();
      syncMltState();
    } catch (error) {
      enterMltError(`播放失败：${error.message}`);
    }
  }
  return true;
}

async function closeMlt() {
  stopMltPoll();
  state.wantPlaying = false;
  display.frameChain = Promise.resolve();
  try {
    await mlt.close();
  } catch (error) { void error; }
  if (display.objectUrl) URL.revokeObjectURL(display.objectUrl);
  display.objectUrl = "";
  nativeFrame.removeAttribute("src");
  nativeFrame.hidden = true;
  view.setNativeMode(false);
  state.displayedPtsUs = null;
  syncMltState();
}

async function activateMlt() {
  if (!state.did || !state.tid) return false;
  const token = loading.begin("mlt", "正在启动 MLT 播放内核…", {
    generation: state.epoch, blocking: true,
  });
  window.__ready = false;
  try {
    const opened = await mlt.open(state.did, state.tid);
    if (opened.stale) {
      loading.end(token);
      return false;
    }
    view.setNativeMode(true);
    startMltPoll();
    await renderMltAt(state.tUs);
    mlt.startStream(queueFrame, (error) => enterMltError(error.message || String(error)));
    window.__ready = true;
    loading.end(token);
    return true;
  } catch (error) {
    loading.fail(`MLT 播放内核不可用：${error.message}`);
    enterMltError(`MLT 播放内核不可用：${error.message}`);
    window.__ready = true;
    return false;
  }
}

function startLeaseHeartbeat() {
  if (!leaseToken) return;
  const url = `/api/lease?token=${encodeURIComponent(leaseToken)}`;
  const touch = () => fetch(url, { method: "POST", cache: "no-store" }).catch(() => {});
  touch();
  const timer = setInterval(touch, 2000);
  window.addEventListener("beforeunload", () => {
    clearInterval(timer);
    try { navigator.sendBeacon(url, new Blob([""], { type: "text/plain" })); } catch (error) { void error; }
  }, { once: true });
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
  await closeMlt();
  $("pick").disabled = true;
  clearCandidates();
  const started = Date.now();
  $("clock").textContent = "解密中…";
  let loadingToken = null;
  const tick = setInterval(() => {
    $("clock").textContent = `解密中… ${((Date.now() - started) / 1000).toFixed(0)}s`;
    if (loadingToken) loading.update(`正在解密草稿… ${((Date.now() - started) / 1000).toFixed(0)}s`, loadingToken);
  }, 500);
  try {
    state.epoch += 1;
    state.phase = "loading";
    loadingToken = loading.begin("decrypt", "正在解密草稿…", {
      generation: state.epoch, blocking: true,
    });
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
    if (loadingToken) loading.fail(`解密失败：${error.code || error.message}`);
    window.__ready = true;
  } finally {
    clearInterval(tick);
    if (loadingToken) loading.end(loadingToken);
    $("pick").disabled = false;
  }
}

async function selectTimeline(tid) {
  const loadingToken = loading.begin("timeline", "正在准备时间线…", {
    generation: state.epoch, blocking: true,
  });
  try {
    const result = await selectTimelineInternal(tid);
    await activateMlt();
    return result;
  } catch (error) {
    loading.fail(`时间线加载失败：${error.message || error}`);
    throw error;
  } finally {
    loading.end(loadingToken);
  }
}

async function selectTimelineInternal(tid) {
  if (!tid || !state.did) return;
  await closeMlt();
  state.epoch += 1;
  state.phase = "loading";
  state.error = null;
  state.tid = tid;
  params.set("timeline", tid);
  history.replaceState(null, "", `?${params}`);
  $("fontcss").href = `/api/fonts.css?draft=${state.did}&timeline=${tid}`;
  state.trackmap = await api("/api/trackmap", { draft: state.did, timeline: tid });
  state.durationUs = Math.max(state.trackmap.duration_us || 0, 1);
  state.fps = state.trackmap.fps || 30;
  state.frameDurUs = Math.round(1e6 / state.fps);
  state.ir = null;
  view.clear();
  $("scrub").max = String(Math.round(state.durationUs / 1000));
  drawLanes();
  await fetchFrame(0, true);
  state.phase = "ready";
  paintPlay();
}

// -- frames ------------------------------------------------------------------
// Point queries compose exactly at t and feed the diagnostic DOM pool: canvas
// geometry, the properties panel, and warnings. Playback itself comes from the
// MLT backend and never advances from these frames.

async function fetchFrame(tUs, exact = false) {
  if (!state.did || !state.tid) return;
  const now = performance.now();
  if (!exact && now - state.lastFetch < 120) return;
  state.lastFetch = now;
  window.__ready = false;
  const epoch = state.epoch;
  const loadingToken = loading.begin("frame", exact ? "正在准备当前画面…" : "正在定位画面…", {
    generation: epoch, blocking: true,
  });
  const pending = api("/api/frame", { draft: state.did, timeline: state.tid,
    t_us: Math.round(tUs), ratio: state.ratio === "draft" ? "" : state.ratio })
    .then((ir) => {
      if (epoch !== state.epoch) return null;
      applyFrame(ir);
      return ir;
    })
    .catch((error) => {
      if (epoch !== state.epoch) return null;
      window.__error = String(error && error.message);
      $("warnings").replaceChildren();
      note(`取帧失败：${window.__error}`, true);
    })
    .finally(() => {
      if (state.pending === pending) state.pending = null;
      if (epoch === state.epoch) window.__ready = true;
      loading.end(loadingToken);
    });
  state.pending = pending;
  await pending;
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
  view.highlight(null);
  markSelectedSegment(null);
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
  const entry = view.entryForLayer(layer.layer_id);
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
  if (!mlt.playbackId) return Promise.resolve(null);
  if (!exact) {
    // ponytail: scrub drags issue one seek per 120ms; release fires the exact seek
    const now = performance.now();
    if (now - state.lastSeekIssue < 120) return Promise.resolve(null);
  }
  state.lastSeekIssue = performance.now();
  const target = Math.max(0, Math.min(Math.round(tUs), state.durationUs || tUs));
  return renderMltAt(target).catch((error) => {
    enterMltError(`定位失败：${error && error.message}`);
    return null;
  });
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
  if (!state.tid || !mlt.playbackId) return;   // nothing loaded yet: the button must not lie
  state.wantPlaying = next;
  const request = next ? mlt.play() : mlt.pause();
  request.then(() => {
    syncMltState();
    view.evalAt(state.tUs, state.playing);
    state.primary = view.primaryAt(state.tUs);
  }).catch((error) => enterMltError(`${next ? "播放" : "暂停"}失败：${error.message}`));
}

function refreshPanels(ir) {
  renderProps($("props"), instantCopy(topVisibleLayer()), { raw: true });
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
    if (data.drafts_root_like) {
      $("clock").textContent = "选的是 Drafts 根目录";
      note("这是 Drafts 根目录（里面是一堆草稿），不是单个草稿。请在左侧列表里点要看的草稿，或进入某个草稿文件夹后再选。", true);
      $("pick").disabled = false;
      return;
    }
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
  void error;
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
$("scrub").addEventListener("change", () => seek(Number($("scrub").value) * 1000, true));
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
  await fetchFrame(state.tUs, true);
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
    if (mlt.playbackId || state.phase === "loading" || loading.snapshot().kind === "mlt") return;
    if (data.source_sha256 && data.source_sha256 === state.sourceSha) return;
    if (data.source_sha256) state.sourceSha = data.source_sha256;
    note("检测到草稿文件被改写，正在重新解密…");
    openDraft(state.did);
  }
});

window.__renderAt = async (tUs) => {
  window.__ready = false;
  try {
    await renderMltAt(Number(tUs));
  } catch (error) {
    enterMltError(String(error && error.message));
  }
  while (state.pending) await state.pending;
  window.__ready = true;
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
  playing: state.playing, buffering: state.phase === "buffering", phase: state.phase,
  backend: "mlt", playbackId: mlt.playbackId, seekRequestId: mlt.issued,
  generation: mlt.generation, frameIndex: mlt.frameIndex, fps: state.fps,
  displayedPtsUs: state.displayedPtsUs, error: state.error || null,
  pending: !!state.pending, ratio: state.ratio, scale: state.scale,
  durationUs: state.durationUs, span: state.span,
  media: view.mediaStatus,
  loading: loading.snapshot(),
  pool: view.pool.size, armed: [...view.pool.values()].filter(e => e.armed).length,
  visible: view.flat.filter((entry) => entry.visible).length,
  flat: view.flat.length, loads: view.loadLog || [],
  primary: state.primary ? { id: state.primary.entry.id, kind: state.primary.layer.kind,
    nested: state.primary.entry.depth > 0 } : null });

// What the viewer actually sees right now, read off the DOM pool rather than off the IR:
// the honest way to assert on playback without taking a screenshot.
window.__snapshot = () => ({
  tUs: state.tUs, playing: state.playing, buffering: state.phase === "buffering",
  phase: state.phase, backend: "mlt", playbackId: mlt.playbackId,
  seekRequestId: mlt.issued, generation: mlt.generation, frameIndex: mlt.frameIndex,
  displayedPtsUs: state.displayedPtsUs, error: state.error || null,
  media: view.mediaStatus,
  loading: loading.snapshot(),
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
window.__backend = mlt;
window.__close = () => closeMlt();

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
  startLeaseHeartbeat();
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
})();
