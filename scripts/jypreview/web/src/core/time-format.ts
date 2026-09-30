/** Timecode reading and writing for the timeline UI. Integer microseconds in, human text out. */

function clampUs(value: number): number {
  const parsed = Math.round(Number.isFinite(value) ? value : 0);
  return parsed < 0 ? 0 : parsed;
}

function pad(value: number, size = 2): string {
  return String(Math.max(0, Math.floor(value))).padStart(size, "0");
}

/** `mm:ss.mmm`, the form the ruler and readouts use. */
export function formatTimecode(us: number): string {
  const ms = clampUs(us) / 1000;
  return `${pad(Math.floor(ms / 60000))}:${pad(Math.floor(ms / 1000) % 60)}.${pad(ms % 1000, 3)}`;
}

/** `hh:mm:ss:frame`, the form a cut list and JianYing's own field use. */
export function timecodeAt(us: number, fps: number): string {
  const rate = Number.isFinite(fps) && fps > 0 ? fps : 0;
  const totalFrames = rate > 0 ? Math.floor((clampUs(us) / 1_000_000) * rate) : 0;
  const totalSeconds = Math.floor(totalFrames / (rate || 1));
  return `${pad(Math.floor(totalSeconds / 3600))}:${pad(Math.floor(totalSeconds / 60) % 60)}:` +
    `${pad(totalSeconds % 60)}:${pad(totalFrames % (rate || 1))}`;
}

/** Accepts `mm:ss.mmm`, `hh:mm:ss`, `hh:mm:ss:ff`, bare seconds, or nothing at all. */
export function parseTimecode(text: string, fps = 30): number | null {
  const value = String(text ?? "").trim();
  if (!value) return null;
  if (/^\d+(\.\d+)?$/.test(value)) return Math.round(Number(value) * 1_000_000);
  if (!/^[\d:.,]+$/.test(value)) return null;
  const parts = value.split(":");
  if (parts.length > 4 || parts.some((part) => part === "")) return null;
  const numbers = parts.map(Number);
  if (numbers.some((item) => !Number.isFinite(item))) return null;
  if (numbers.some((item) => item < 0)) return null;
  if (parts.length === 4) {
    const [hh = 0, mm = 0, ss = 0, ff = 0] = numbers;
    const rate = fps > 0 ? fps : 30;
    if (ff >= rate) return null;
    return Math.round(((hh * 3600 + mm * 60 + ss) * 1_000_000) + (ff / rate) * 1_000_000);
  }
  if (parts.length === 3) {
    const [hh = 0, mm = 0, ss = 0] = numbers;
    return Math.round((hh * 3600 + mm * 60 + ss) * 1_000_000);
  }
  const [mm = 0, ss = 0] = numbers;
  return Math.round((mm * 60 + ss) * 1_000_000);
}

/** Pixels per microsecond that fits the whole timeline in the viewport. */
export function pxPerUs(durationUs: number, widthPx: number): number {
  const span = Math.max(clampUs(durationUs), 1);
  const raw = Math.max(widthPx, 1) / span;
  return Math.min(Math.max(raw, 1e-7), 1);
}

export function usAt(offsetPx: number, scale: number): number {
  if (!Number.isFinite(offsetPx) || scale <= 0) return 0;
  return Math.round(offsetPx / scale);
}
