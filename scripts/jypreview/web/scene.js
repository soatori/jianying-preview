// Pure-ish scene evaluation: time range visibility is separate from media loading.
// The Stage still owns DOM nodes, but this class owns the scene membership decision.

export class SceneGraph {
  evaluate(entries, tUs, timeAt) {
    const visible = [];
    for (const entry of entries) {
      const at = timeAt(entry, tUs);
      if (at) visible.push({ entry, at });
      const shouldShow = !!at;
      if (entry.visible !== shouldShow) {
        entry.visible = shouldShow;
        entry.root.style.display = shouldShow ? "" : "none";
        entry.root.style.visibility = shouldShow ? "visible" : "hidden";
        if (shouldShow) delete entry.root.dataset.hidden;
        else entry.root.dataset.hidden = "1";
      }
    }
    return visible;
  }
}
