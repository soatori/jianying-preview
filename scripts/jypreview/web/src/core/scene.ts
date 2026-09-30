/** The picture at one instant, derived only from the project snapshot and a time.
 *
 * Pure and synchronous on purpose: no DOM, no fetch, no timers, no state. That is what
 * lets the same function answer "what should be on screen" for the renderer, for a
 * test, and for the acceptance harness that compares against the Python IR.
 */

import type { CanvasBox, Clip, EditorProject, TimelineIdentity } from "./project.ts";

export const AUDIO_KIND = "audio";
const NONE_KIND = "none";
const FALLBACK_FPS = 30;

export interface ActiveClip {
  clip: Clip;
  /** Microseconds since the clip's own target start. */
  localUs: number;
  /** Position inside the source media, already mapped through speed and reverse. */
  sourceTimeUs: number;
  progress: number;
  muted: boolean;
  opacity: number;
}

export interface Scene {
  tUs: number;
  frameUs: number;
  durationUs: number;
  canvas: CanvasBox;
  timeline: TimelineIdentity;
  clips: ActiveClip[];
  audio: ActiveClip[];
  warnings: string[];
}

export function isVisualKind(kind: string): boolean {
  return kind !== AUDIO_KIND && kind !== NONE_KIND;
}

/** Mirrors `jypreview.model.timing.source_time_us` exactly. */
export function sourceTimeUs(localUs: number, clip: Clip): number {
  const rate = clip.speed > 0 ? clip.speed : 1;
  const offset = Math.round(Math.abs(localUs) * rate);
  if (!clip.reverse) return clip.source_start_us + offset;
  const span = clip.source_duration_us || Math.round(clip.target_duration_us * rate);
  return clip.source_start_us + Math.max(span - offset, 0);
}

export function resolveScene(tUs: number, project: EditorProject): Scene {
  const stamp = Math.round(Number.isFinite(tUs) ? tUs : 0);
  const hidden = new Set(project.tracks.filter((track) => !track.visible).map((track) => track.id));
  const clips: ActiveClip[] = [];
  const audio: ActiveClip[] = [];
  const warnings: string[] = [];

  for (const clip of project.clips) {
    if (!clip.visible || clip.kind === NONE_KIND) continue;
    if (hidden.has(clip.track_id)) continue;
    if (stamp < clip.target_start_us || stamp >= clip.target_end_us) continue;
    const localUs = stamp - clip.target_start_us;
    const active: ActiveClip = {
      clip,
      localUs,
      sourceTimeUs: sourceTimeUs(localUs, clip),
      progress: clip.target_duration_us > 0
        ? Math.round(Math.min(Math.max(localUs / clip.target_duration_us, 0), 1) * 1e6) / 1e6
        : 0,
      muted: clip.muted || trackMuted(project, clip),
      opacity: clip.rect ? numberOr(clip.rect.alpha, 1) : 1,
    };
    (clip.kind === AUDIO_KIND ? audio : clips).push(active);
    for (const note of clip.warnings) warnings.push(`${clip.clip_id}: ${note}`);
  }

  const byZ = (left: ActiveClip, right: ActiveClip) => left.clip.z_index - right.clip.z_index;
  clips.sort(byZ);
  audio.sort(byZ);

  return {
    tUs: stamp,
    frameUs: frameUs(project.fps),
    durationUs: project.duration_us,
    canvas: project.canvas,
    timeline: project.timeline,
    clips,
    audio,
    warnings,
  };
}

function trackMuted(project: EditorProject, clip: Clip): boolean {
  return project.tracks.some((track) => track.id === clip.track_id && track.muted);
}

function frameUs(fps: number): number {
  const rate = fps > 0 ? fps : FALLBACK_FPS;
  return Math.round(1_000_000 / rate);
}

function numberOr(value: unknown, fallback: number): number {
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}
