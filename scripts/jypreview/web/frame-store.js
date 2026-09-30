// Point and window IR storage. Playback must never infer window validity from
// whatever layers happen to remain in the DOM pool.

export class FrameStore {
  constructor() {
    this.point = null;
    this.window = null;
    this.generation = 0;
  }

  clear(generation = this.generation) {
    this.point = null;
    this.window = null;
    this.generation = generation;
  }

  setPoint(ir, generation) {
    this.point = { ir, generation };
    this.generation = generation;
  }

  setWindow(ir, generation) {
    this.window = { ir, generation, from: ir.window.from_us, to: ir.window.to_us };
    this.generation = generation;
  }

  covers(tUs, generation = this.generation) {
    return !!this.window && this.window.generation === generation &&
      tUs >= this.window.from && tUs < this.window.to;
  }

  range(generation = this.generation) {
    return this.window && this.window.generation === generation
      ? [this.window.from, this.window.to] : null;
  }
}
