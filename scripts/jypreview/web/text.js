// SVG text renderer: reproduces JianYing's fill / multi-stroke / shadow / background /
// vertical typesetting model from the FrameDescriptor's precomputed line layout.
const NS = "http://www.w3.org/2000/svg";

function el(name, attrs = {}) {
  const node = document.createElementNS(NS, name);
  for (const [key, value] of Object.entries(attrs)) {
    if (value !== null && value !== undefined) node.setAttribute(key, value);
  }
  return node;
}

function fillAttr(run, defs, idBase) {
  const fill = run.fill || {};
  if (fill.render_type === "gradient" && fill.stops && fill.stops.length) {
    const angle = ((fill.angle || 0) * Math.PI) / 180;
    const grad = el("linearGradient", {
      id: `${idBase}-grad`,
      gradientUnits: "objectBoundingBox",
      x1: 0.5 - Math.sin(angle) / 2, y1: 0.5 + Math.cos(angle) / 2,
      x2: 0.5 + Math.sin(angle) / 2, y2: 0.5 - Math.cos(angle) / 2,
    });
    fill.stops.forEach((stop, index) => {
      grad.appendChild(el("stop", { offset: stop.offset ?? index / Math.max(fill.stops.length - 1, 1),
        "stop-color": stop.css, "stop-opacity": stop.alpha ?? 1 }));
    });
    defs.appendChild(grad);
    return `url(#${idBase}-grad)`;
  }
  if (fill.render_type === "texture") return fill.css || "#ffffff";
  return fill.css || "#ffffff";
}

function shadowFilter(defs, shadow, idBase) {
  const blur = (shadow.feather || 0) * (shadow.distance_em || 1) * 4;
  const filter = el("filter", { id: idBase, x: "-40%", y: "-40%", width: "180%", height: "180%" });
  if (blur > 0.2) filter.appendChild(el("feGaussianBlur", { stdDeviation: blur.toFixed(2) }));
  defs.appendChild(filter);
  return `url(#${idBase})`;
}

function strokeEmWidth(stroke, em) {
  return Math.max((stroke.width_em || 0) * em, 0);
}

export function textGroup(layer, ctx) {
  const text = layer.text;
  if (!text) return null;
  const box = text.box || {};
  const runs = text.runs || [];
  const lines = box.lines || [{ text: text.text || "", start: 0, end: (text.text || "").length, width_px: 0, spans: [] }];
  const lineOrder = box.line_height_px || (box.em_px || 0) * 1.2;
  const idBase = `t${ctx.seq}`;
  const group = el("g", { "data-layer": layer.layer_id, opacity: ((layer.rect && layer.rect.alpha) ?? 1) });
  const defs = el("defs");
  group.appendChild(defs);

  const w = box.w_px || 0, h = box.h_px || 0;
  const transform = `translate(${(box.cx_px || 0) - w / 2},${(box.cy_px || 0) - h / 2})`;
  const inner = el("g", { transform });
  group.appendChild(inner);

  const deco = text.deco || {};
  if (deco.background) {
    const bg = deco.background;
    const pad = Math.max((bg.width || 0.5) * w * 0.25, 6);
    inner.appendChild(el("rect", {
      x: -pad, y: -pad, width: w + pad * 2, height: h + pad * 2,
      rx: bg.round_radius || 0, fill: bg.color || "#000", "fill-opacity": bg.alpha ?? 1,
    }));
  }

  const family = (runs[0] && runs[0].font && runs[0].font.family) || (text.font && text.font.family) || "sans-serif";
  const anchorFor = (xOff, lineWidth) => box.alignment === "left" ? 0
    : box.alignment === "right" ? w - 0 : w / 2;

  lines.forEach((line, lineIndex) => {
    // SVG <text> y is the baseline, so the first line must sit one ascent below the
    // box top or the glyphs render above y=0 and get clipped away.
    const baseY = lineIndex * lineOrder + (box.em_px || 0) * 0.82;
    const startX = box.alignment === "left" ? 0 : box.alignment === "right" ? w - line.width_px : (w - line.width_px) / 2;
    let cursor = 0;
    for (const run of runs) {
      const from = Math.max(run.start, line.start);
      const to = Math.min(run.end, line.end);
      if (to <= from) continue;
      const spans = (line.spans || []).filter((span) => span.i >= from && span.i < to);
      const advance = spans.reduce((total, span) => total + (span.advance || 0), 0)
        || (run.em_px || box.em_px) * (to - from);
      const slice = (line.text || "").slice(from - line.start, to - line.start);
      cursor += to - from;
      const x = startX + leadingAdvance(line, from);
      const attrs = {
        x, y: baseY, "font-family": family, "font-size": run.em_px || box.em_px,
        "font-style": run.italic ? "italic" : "normal",
        "font-weight": run.bold ? "700" : "400",
        "text-decoration": run.underline ? "underline" : "none",
        "letter-spacing": (deco.letter_spacing_px || 0) + "px",
        "xml:space": "preserve",
      };
      if (deco.vertical) attrs["writing-mode"] = "vertical-rl";

      (run.shadows || []).forEach((shadow, index) => {
        const dx = (shadow.distance_em || 0) * Math.cos((shadow.angle_deg || 0) * Math.PI / 180) * (run.em_px || box.em_px);
        const dy = -(shadow.distance_em || 0) * Math.sin((shadow.angle_deg || 0) * Math.PI / 180) * (run.em_px || box.em_px);
        const node = el("text", { ...attrs, x: x + dx, y: baseY + dy, fill: shadow.color || "#000",
          "fill-opacity": shadow.alpha ?? 1, stroke: "none" });
        if ((shadow.feather || 0) > 0) node.setAttribute("filter",
          shadowFilter(defs, shadow, `${idBase}-sh${lineIndex}-${index}`));
        node.textContent = slice;
        inner.appendChild(node);
      });

      const strokes = (run.strokes || []).slice().sort((a, b) => (b.width_em || 0) - (a.width_em || 0));
      strokes.forEach((stroke, index) => {
        const node = el("text", {
          ...attrs, fill: "none", stroke: stroke.color || "#000",
          "stroke-opacity": stroke.alpha ?? 1, "stroke-width": strokeEmWidth(stroke, run.em_px || box.em_px),
          "stroke-linejoin": "round", "paint-order": "stroke",
        });
        node.textContent = slice;
        inner.appendChild(node);
      });

      const fill = el("text", { ...attrs, fill: fillAttr(run, defs, `${idBase}-f${lineIndex}`),
        "fill-opacity": (run.fill && run.fill.alpha) ?? 1 });
      fill.textContent = slice;
      inner.appendChild(fill);
      void anchorFor;
    }
  });
  return group;
}

function leadingAdvance(line, from) {
  let total = 0;
  for (const span of line.spans || []) {
    if (span.i < from) total += span.advance || 0;
    else break;
  }
  return total;
}
