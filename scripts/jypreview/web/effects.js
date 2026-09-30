// Timeline-driven effect application. The IR remains the source of truth; this
// module only turns the already-resolved animation state into DOM properties.

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

export function applyTransform(node, css, state) {
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
  } else {
    node.style.filter = "";
  }
  node.style.transform = transform;
  node.style.opacity = opacity;
}

export class EffectRenderer {
  render(entry, at, reset) {
    const animation = entry.layer.animation;
    const labels = entry.layer.labels || [];
    const tiers = labels.map((label) => label.render_class).filter(Boolean);
    const tier = animation?.render_class || tiers.find((value) => value === "placeholder")
      || tiers.find((value) => value === "approx") || tiers[0] || "none";
    entry.root.dataset.renderClass = tier;
    entry.root.dataset.effectStatus = tier === "exact" ? "exact" :
      tier === "approx" ? "approx" : tier === "placeholder" ? "placeholder" : "none";
    if (animation) {
      // An exact catalog entry without a browser implementation must remain
      // visibly marked as unrendered; applying the keyword approximation would
      // make the preview claim fidelity it does not have.
      const state = animation.render_class === "approx"
        ? animationStateAt(entry.layer, at.local) : null;
      if (state) {
        applyTransform(entry.root, entry.layer.css || (entry.layer.rect || {}).css, state);
      } else {
        reset(entry);
        entry.root.dataset.effectStatus = animation.render_class === "exact"
          ? "exact-unimplemented" : "placeholder";
      }
      return;
    }
    if (entry.kind === "media") reset(entry);
  }
}
