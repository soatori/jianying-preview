// Replaceable browser backend seam. The first backend deliberately delegates to
// the controller and DOM adapters; native engines are not part of this previewer.

export class BrowserPlaybackBackend {
  constructor(controller) {
    this.controller = controller;
    this.capabilities = Object.freeze({
      name: "browser",
      exact_frame: false,
      audio: true,
      transitions: "approx",
      effects: Object.freeze(["exact", "approx", "placeholder"]),
    });
  }

  open(profile = {}) {
    this.controller.setTimeline(profile);
    return this.snapshot();
  }

  close() { return this.controller.close(); }
  seek(tUs, exact = true) { return this.controller.seek(tUs, exact); }
  play() { return this.controller.play(); }
  pause() { return this.controller.pause(); }
  renderAt(tUs, exact = true) { return this.controller.renderAt(tUs, exact); }
  snapshot() { return this.controller.snapshot(); }
}
