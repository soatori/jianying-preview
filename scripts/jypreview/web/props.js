// Right-hand panels: 属性栏 (selected layer) and 信息栏 (timeline + coverage + cache).
// Everything is built with textContent so draft-derived strings can never become markup.

export function fmtUs(value) {
  if (value === null || value === undefined) return "-";
  return `${(value / 1e6).toFixed(3)}s`;
}

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function group(title) {
  const box = el("div", "group");
  box.appendChild(el("div", null, title));
  return box;
}

// A group with nothing in it is noise: only the selected layer's real fields get shown.
function append(box, section) {
  if (section && section.childElementCount > 1) box.appendChild(section);
  return box;
}

function row(box, key, value, cls) {
  if (value === null || value === undefined || value === "") return box;
  const line = el("div", "row");
  line.appendChild(el("span", "k", key));
  const cell = el("span", `v ${cls || ""}`.trim());
  if (typeof value === "string" && /^#[0-9a-f]{3,8}$/i.test(value)) {
    cell.appendChild(el("i", "swatch"));
    cell.firstChild.style.background = value;
    cell.appendChild(document.createTextNode(value));
  } else {
    cell.textContent = String(value);
  }
  line.appendChild(cell);
  box.appendChild(line);
  return box;
}

function fillText(fill) {
  if (!fill) return null;
  if (fill.render_type === "gradient") {
    return `渐变 ${(fill.angle ?? 0)}° → ${(fill.stops || []).map((s) => s.css).join(" ")}`;
  }
  if (fill.render_type === "texture") return `贴图 ${fill.path || ""}`;
  return `${fill.css || ""}${fill.alpha !== undefined && fill.alpha !== 1 ? ` α${fill.alpha}` : ""}`;
}

export function renderProps(box, layer, ctx) {
  box.replaceChildren();
  if (!layer) {
    box.appendChild(el("div", "hint", "点时间线上的片段或上方图层标签选择要看的图层"));
    return;
  }
  const time = layer.time || {};
  const z = layer.z || {};
  const rect = layer.rect || {};
  const text = layer.text;
  const media = layer.media;

  const where = group("定位");
  row(where, "图层", `${layer.kind} · z${z.order ?? "?"}`, z.source === "default:video" ? "" : "");
  row(where, "轨道", `${(layer.track || {}).type || "-"} #${(layer.track || {}).index ?? "-"} ${(layer.track || {}).name || ""}`.trim());
  row(where, "z 来源", z.source);
  row(where, "画面区间", `${fmtUs(time.target_start_us)} → ${fmtUs(time.end_us)}`);
  row(where, "素材时间", `${fmtUs(time.source_time_us)}  speed=${time.speed ?? 1}${time.reverse ? " 倒放" : ""}`);
  row(where, "进度", `${Math.round((time.progress ?? 0) * 100)}%`);
  append(box, where);

  if (Object.keys(rect).length) {
    const geo = group("几何");
    row(geo, "中心 px", `${rect.cx_px}, ${rect.cy_px}`);
    row(geo, "尺寸 px", `${rect.w_px} × ${rect.h_px}`);
    row(geo, "旋转/缩放", `${rect.rotation_deg ?? 0}°  scale ${rect.scale_x ?? 1}×${rect.scale_y ?? 1}`);
    row(geo, "不透明度", rect.alpha);
    if (rect.flip_x || rect.flip_y) row(geo, "翻转", [rect.flip_x && "水平", rect.flip_y && "垂直"].filter(Boolean).join(" "));
    append(box, geo);
  }

  if (text) {
    const runs = text.runs || [];
    const first = runs[0] || {};
    const boxInfo = text.box || {};
    const t1 = group("文本");
    row(t1, "内容", text.text);
    row(t1, "字号", `${first.size_raw ?? "-"}  →  ${boxInfo.em_px ?? "-"} px`);
    row(t1, "字体", `${(text.font || {}).title || (text.font || {}).resource_id || "系统字体"}  (${(text.font || {}).source || "-"})`,
      (text.font || {}).source === "system_stack" ? "miss" : "ok");
    row(t1, "对齐/排布", `${boxInfo.alignment || "-"}${boxInfo.vertical ? " · 竖排" : " · 横排"}`);
    row(t1, "行数", `${boxInfo.line_count ?? 1}  行高 ${boxInfo.line_height_px ?? "-"}px  度量=${boxInfo.metrics || "-"}`);
    row(t1, "最大行宽", boxInfo.max_line_px ? `${boxInfo.max_line_px}px` : null);
    row(t1, "字距/行距", `${(text.deco || {}).letter_spacing_px ?? 0} / ${(text.deco || {}).line_spacing_raw ?? 0}`);
    row(t1, "类型", text.type);
    append(box, t1);

    runs.forEach((run, index) => {
      const style = group(`样式 ${index + 1}  [${run.start},${run.end})`);
      row(style, "填充", fillText(run.fill));
      (run.strokes || []).forEach((s, i) => row(style, `描边${i + 1}`, `${s.width_em}em ≈ ${(s.width_em * (run.em_px || 0)).toFixed(1)}px  ${s.color} α${s.alpha}`));
      (run.shadows || []).forEach((s, i) => row(style, `阴影${i + 1}`, `距离${s.distance_em} 角度${s.angle_deg}° ${s.color} α${s.alpha}${s.feather ? ` 羽化${s.feather}` : ""}`));
      (run.inner_shadows || []).forEach((s, i) => row(style, `内阴影${i + 1}`, `${s.color} 距离${s.distance_em} 角度${s.angle_deg}°`));
      if (run.font && run.font.family && index > 0) row(style, "该段字体", `${run.font.title || run.font.resource_id} (${run.font.source})`);
      if (run.flower) {
        row(style, "花字", `${run.flower.name || "?"}  ${run.flower.render_class}`,
          run.flower.render_class === "exact" ? "ok" : "miss");
        row(style, "花字 id", run.flower.resource_id);
      }
      append(box, style);
    });
    if ((text.deco || {}).background) {
      const bg = group("背景板");
      const background = text.deco.background;
      row(bg, "样式", `${background.style}  ${background.color} α${background.alpha}`);
      row(bg, "圆角/偏移", `${background.round_radius}  h${background.horizontal_offset} v${background.vertical_offset}`);
      append(box, bg);
    }
  }

  if (media) {
    const m = group("素材");
    row(m, "名称", media.material_name);
    row(m, "类型", `${media.material_type || "-"} / ${media.family || "-"}`);
    row(m, "可用", media.exists ? "是" : `否（${media.how}）`, media.exists ? "ok" : "miss");
    if (media.recovered) row(m, "路径来源", media.how);
    row(m, "原始路径", media.path_raw);
    if (media.path && media.path !== media.path_raw) row(m, "实际路径", media.path);
    if (media.probe) {
      row(m, "编码", `${media.probe.codec}  ${media.probe.width}×${media.probe.height}  ${media.probe.frame_rate || "-"}fps`);
      row(m, "素材时长", fmtUs(media.probe.duration_us));
    }
    row(m, "素材全长", fmtUs(media.material_duration_us));
    row(m, "音量", layer.volume);
    append(box, m);
  }

  if (layer.canvas_fill) {
    const fill = group("背景填充");
    row(fill, "类型", layer.canvas_fill.type);
    row(fill, "参数", `blur=${layer.canvas_fill.blur ?? "-"} color=${layer.canvas_fill.color ?? "-"} α=${layer.canvas_fill.ratio ?? "-"}`);
    append(box, fill);
  }

  const extras = group("效果标签");
  if (layer.transition) {
    const t = layer.transition;
    row(extras, "转场", `${t.name || "?"} ${fmtUs(t.duration_us)} [${t.render_class}]  overlap=${t.is_overlap}`);
    row(extras, "转场窗口", `${fmtUs((t.window || {}).start_us)} → ${fmtUs((t.window || {}).end_us)}  切点 ${fmtUs(t.cut_us)}`);
    if (t.approx) row(extras, "近似实现", t.approx.impl);
  }
  if (layer.animation) {
    const a = layer.animation;
    row(extras, "动画", `${a.name || "?"} ${a.anim_type} ${fmtUs(a.duration_us)} [${a.render_class}]${a.inside ? "" : " (此刻不在窗口内)"}`);
    if (a.approx) row(extras, "近似实现", `${a.approx.impl} ${a.approx.from}→${a.approx.to}`);
    if (a.at_t) row(extras, "此刻取值", JSON.stringify(a.at_t));
  }
  (layer.labels || []).forEach((label) => {
    if (label.kind === "transition" || label.kind === "in" || label.kind === "out" || label.kind === "loop") return;
    row(extras, label.bucket, `${label.name} [${label.render_class}]${label.value !== undefined && label.value !== null ? ` v=${label.value}` : ""}`);
  });
  if (layer.applies) row(extras, "作用方式", `${layer.applies}（剪映专有算法，不预览）`);
  if (layer.keyframes && layer.keyframes.length) {
    layer.keyframes.forEach((kf) => row(extras, "关键帧", `${kf.property} = ${JSON.stringify(kf.values)} (${kf.curve})`));
  }
  if (layer.nest) {
    row(extras, "复合片段", `depth=${layer.nest.depth} 内层图层=${(layer.nest.layers || []).length}`);
    if (layer.nest.reason) row(extras, "内层说明", layer.nest.reason);
    if (layer.nest.root) row(extras, "内层根目录", layer.nest.root);
  }
  append(box, extras);

  if (ctx && ctx.raw) {
    const raw = group("原始 JSON");
    const toggle = el("button", null, "展开 / 收起");
    const pre = el("pre", "detail", JSON.stringify(layer, null, 1));
    pre.style.display = "none";
    pre.style.whiteSpace = "pre-wrap";
    pre.style.fontSize = "10px";
    toggle.onclick = () => { pre.style.display = pre.style.display === "none" ? "block" : "none"; };
    raw.appendChild(toggle);
    raw.appendChild(pre);
    append(box, raw);
  }
}

export function renderInfo(box, ir, describe, extra) {
  box.replaceChildren();
  if (!ir) return;
  const timeline = describe || ir.timeline || {};
  const head = group("时间线");
  row(head, "草稿", `${ir.draft.name}  (${ir.draft.layout || timeline.layout || "-"})`);
  row(head, "时间线", `${(ir.timeline || {}).name || "-"}  ${(ir.timeline || {}).encoding || ""}`);
  row(head, "内容文件", (ir.timeline || {}).content_file);
  row(head, "陈旧镜像", (ir.timeline || {}).mirror_drift ? "是（根 draft_content.json 与活动时间线不一致）" : "否",
    (ir.timeline || {}).mirror_drift ? "miss" : "ok");
  row(head, "时长", `${fmtUs(ir.duration_us)}  fps=${ir.fps}`);
  const viewRatio = ir.canvas.ratio_draft && ir.canvas.ratio !== ir.canvas.ratio_draft
    ? `  〔画幅按 ${ir.canvas.ratio} 重算，草稿是 ${ir.canvas.ratio_draft}〕` : "";
  row(head, "画布", `${ir.canvas.width}×${ir.canvas.height}  ${ir.canvas.ratio}${viewRatio}`,
    viewRatio ? "warn" : "");
  const rule = ir.size_rule || {};
  row(head, "字号规则", rule.px_per_size
    ? `em = size × ${rule.px_per_size} px  (${rule.basis}, fit=${rule.fit_mode})` : null);
  append(box, head);

  const stats = ir.stats || {};
  const cover = group("覆盖情况");
  if (ir.window) {
    const seconds = ((ir.window.to_us - ir.window.from_us) / 1e6).toFixed(1);
    row(cover, "播放窗口", `${fmtUs(ir.window.from_us)} → ${fmtUs(ir.window.to_us)}（${seconds}s）`,
      "ok");
    row(cover, "窗口内图层", `${stats.layers_total}（含尚未出现的时间段，播放时才显示）`);
  }
  row(cover, "图层", `${stats.layers_total}  缺失素材 ${stats.media_missing}`, stats.media_missing ? "miss" : "ok");
  const labels = stats.labels || {};
  row(cover, "效果标签", `精确 ${labels.exact || 0} · 近似 ${labels.approx || 0} · 占位 ${labels.placeholder || 0}`);
  row(cover, "字体来源", Object.entries(stats.fonts || {}).map(([key, value]) => `${key}×${value}`).join("  ") || "无文本");
  row(cover, "花字", stats.flowers || 0);
  const audio = (ir.audio_labels || []).filter((item) => item.audio && item.audio.exists && !item.muted);
  row(cover, "此刻音频", `${(ir.audio_labels || []).length} 段（可播 ${audio.length} 段）`);
  append(box, cover);

  if (describe) {
    const tl = group("可选时间线");
    (describe.timelines || []).forEach((item) => {
      row(tl, item.active ? "★ " + (item.name || item.id.slice(0, 8)) : (item.name || item.id.slice(0, 8)),
        `${fmtUs(item.duration_us)}  ${item.encoding || "-"}  副本${item.replica_count ?? 0}` +
        (item.media_hit_ratio && item.media_hit_ratio.ratio !== null ? `  素材${Math.round(item.media_hit_ratio.ratio * 100)}%` : ""));
    });
    append(box, tl);
  }

  if (extra && extra.cache) {
    const cache = group("缓存与服务");
    row(cache, "位置", extra.cache.location);
    row(cache, "目录", extra.cache.root);
    row(cache, "拥有文件", extra.cache.owned_files);
    if (extra.cache.fallback_reason) row(cache, "回退原因", extra.cache.fallback_reason, "miss");
    if (extra.server) row(cache, "已出图", `${extra.server.frames_built} 帧`);
    append(box, cache);
  }
}
