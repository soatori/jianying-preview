// Small UI-only loading state. Request ownership is token-based so a stale
// frame/window response cannot clear a newer loading message.

export class LoadingController {
  constructor(host) {
    this.host = host;
    this.sequence = 0;
    this.current = null;
    this.error = null;
    this._render();
  }

  begin(kind, message, { generation = null, blocking = kind !== "prefetch" } = {}) {
    const token = { id: ++this.sequence, kind, generation };
    this.current = { ...token, message, blocking };
    this.error = null;
    this._render();
    return token;
  }

  update(message, token = this.current) {
    if (!this.current || !token || token.id !== this.current.id) return false;
    this.current.message = message;
    this._render();
    return true;
  }

  end(token = this.current) {
    if (!this.current || !token || token.id !== this.current.id) return false;
    this.current = null;
    this._render();
    return true;
  }

  fail(message) {
    this.current = null;
    this.error = { kind: "error", message: String(message || "加载失败") };
    this._render();
    return this.snapshot();
  }

  snapshot() {
    const item = this.current || this.error;
    return {
      active: !!item,
      kind: item?.kind || "idle",
      generation: item?.generation ?? null,
      message: item?.message || "",
      blocking: !!this.current?.blocking,
    };
  }

  _render() {
    if (!this.host) return;
    const item = this.current || this.error;
    this.host.hidden = !item;
    this.host.classList?.toggle("active", !!item);
    this.host.classList?.toggle("blocking", !!this.current?.blocking);
    this.host.classList?.toggle("error", !!this.error);
    this.host.textContent = item?.message || "";
    if (item) this.host.setAttribute?.("aria-busy", this.current ? "true" : "false");
    else this.host.removeAttribute?.("aria-busy");
  }
}
