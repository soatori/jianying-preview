/** The editor-project document contract, its boundary check, and the read-only session.
 *
 * `parseEditorProject` is the only place the frontend trusts external data, so it is the
 * place that refuses: a document that is not marked read-only, does not carry the pinned
 * schema, or whose clips are not integer half-open microsecond spans, never reaches the UI.
 * What it returns is deep-frozen, which makes "the snapshot is immutable" a fact instead
 * of a convention the renderer has to remember.
 */

import { PlaybackClock, type ClockSnapshot, type PlaybackStatus } from "./playback-clock.ts";
import { resolveScene, type Scene } from "./scene.ts";

export const PROJECT_SCHEMA = "jypreview/editor-project@1";

export interface TimelineRef {
  id: string;
  name: string | null;
  deleted?: boolean;
  active?: boolean;
  encoding?: string | null;
  duration_us?: number | null;
  content_rel?: string | null;
  content_exists?: boolean;
  replica_count?: number;
  replica_errors?: string[];
  [key: string]: unknown;
}

export interface TimelineIdentity {
  id: string;
  name: string | null;
  encoding: string | null;
  content_file: string | null;
  source_path: string | null;
  source_sha256: string | null;
  active: boolean;
  mirror_drift: boolean;
  replica_drift: boolean;
  duration_us: number;
  declared_duration_us: number;
  segment_count: number;
  [key: string]: unknown;
}

export interface DraftRef {
  id: string;
  name: string;
  path: string;
  layout: string;
  active_timeline_id: string | null;
  timelines: TimelineRef[];
  [key: string]: unknown;
}

export interface CanvasBox {
  width: number;
  height: number;
  ratio: string;
  background: string;
}

export interface Asset {
  asset_id: string;
  kind: string | null;
  name: string | null;
  path_served: string | null;
  exists: boolean;
  how: string | null;
  placeholder_reason: string | null;
  clip_ids: string[];
  [key: string]: unknown;
}

export interface CssBox {
  width: string;
  height: string;
  transform: string;
  "transform-origin": string;
  opacity?: string;
  [key: string]: string | undefined;
}

export interface Clip {
  clip_id: string;
  segment_id: string;
  track_id: string;
  track_index: number;
  track_type: string;
  kind: string;
  z_index: number;
  visible: boolean;
  muted: boolean;
  target_start_us: number;
  target_end_us: number;
  target_duration_us: number;
  source_start_us: number;
  source_duration_us: number;
  source_end_us: number;
  speed: number;
  reverse: boolean;
  warnings: string[];
  asset: Asset | null;
  asset_id: string | null;
  rect: { alpha?: number; [key: string]: unknown } | null;
  css: CssBox | null;
  text: Record<string, unknown> | null;
  nest: Record<string, unknown> | null;
  labels: Record<string, unknown>[];
  animation: Record<string, unknown> | null;
  transition: Record<string, unknown> | null;
  canvas_fill: Record<string, unknown> | null;
  position: number;
  [key: string]: unknown;
}

export interface Track {
  id: string;
  index: number;
  type: string;
  name: string | null;
  group: "visual" | "audio";
  visible: boolean;
  muted: boolean;
  lane: number;
  clip_ids: string[];
  clip_count: number;
  [key: string]: unknown;
}

export interface SceneRules {
  time_unit: string;
  interval: string;
  clip_is_visible_at: string;
  paint_order: string;
  visual_kinds: string[];
}

export interface EditorProject {
  schema: typeof PROJECT_SCHEMA;
  read_only: true;
  draft: DraftRef;
  timeline: TimelineIdentity;
  canvas: CanvasBox;
  fps: number;
  duration_us: number;
  declared_duration_us: number;
  scene_rules: SceneRules;
  tracks: Track[];
  clips: Clip[];
  assets: Asset[];
  warnings: string[];
  [key: string]: unknown;
}

export class EditorProjectError extends Error {
  readonly code: string;
  readonly where: string;

  constructor(code: string, reason: string, where = "") {
    super(where ? `${code}: ${reason} (${where})` : `${code}: ${reason}`);
    this.name = "EditorProjectError";
    this.code = code;
    this.where = where;
  }
}

export class TimelineAmbiguousError extends EditorProjectError {
  readonly available: string[];

  constructor(reason: string, available: unknown) {
    super("timeline_ambiguous", reason);
    this.name = "TimelineAmbiguousError";
    this.available = Array.isArray(available) ? available.map(String) : [];
  }
}

export interface ProjectRequest {
  draft: string;
  timeline?: string;
}

export type ProjectLoader = (request: ProjectRequest) => Promise<unknown>;

export interface EditorSessionOptions extends ProjectRequest {
  load: ProjectLoader;
  now?: () => number;
  schedule?: (task: () => void) => () => void;
  maxElapsedUs?: number;
}

export interface StaleNotice {
  reason: string;
  timeline_id: string;
  duration_us: number;
}

export interface EditorSession {
  readonly clock: PlaybackClock;
  project(): EditorProject;
  sceneAt(tUs?: number): Scene;
  timelines(): TimelineRef[];
  activeTimelineId(): string | null;
  currentTimelineId(): string;
  selectTimeline(timelineId: string): Promise<EditorProject>;
  reload(): Promise<EditorProject>;
  play(): void;
  pause(): void;
  seekTo(tUs: number): void;
  setRate(rate: number): void;
  rate(): number;
  status(): PlaybackStatus;
  onHidden(): void;
  onVisible(): void;
  subscribeScene(listener: (scene: Scene, snapshot: ClockSnapshot) => void): () => void;
  subscribeStale(listener: (notice: StaleNotice) => void): () => void;
  markStale(reason: string): void;
  isStale(): boolean;
  destroy(): void;
}

type JsonRecord = Record<string, unknown>;

function isRecord(value: unknown): value is JsonRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function unwrap(value: unknown): JsonRecord {
  if (isRecord(value) && typeof value.ok === "boolean") {
    if (!value.ok) {
      const code = typeof value.code === "string" ? value.code : "error";
      const reason = typeof value.reason === "string" ? value.reason : "";
      const data = isRecord(value.data) ? value.data : {};
      if (code === "timeline_ambiguous") {
        throw new TimelineAmbiguousError(reason, data.available ?? data.timelines);
      }
      throw new EditorProjectError(code, reason);
    }
    return isRecord(value.data) ? value.data : {};
  }
  if (!isRecord(value)) {
    throw new EditorProjectError("payload_not_an_object", "expected a JSON object from the service");
  }
  return value;
}

function stringField(source: JsonRecord, key: string, where: string, fallback = ""): string {
  const value = source[key];
  if (value === undefined || value === null) return fallback;
  if (typeof value !== "string") {
    throw new EditorProjectError("field_not_a_string", `${key} must be a string`, where);
  }
  return value;
}

function intField(source: JsonRecord, key: string, where: string, code: string, fallback?: number): number {
  const value = source[key];
  if (value === undefined || value === null) {
    if (fallback !== undefined) return fallback;
    throw new EditorProjectError("field_missing", `${key} is required`, where);
  }
  const parsed = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(parsed) || !Number.isInteger(parsed)) {
    throw new EditorProjectError(code, `${key} must be an integer microsecond value`, where);
  }
  return parsed;
}

function boolField(source: JsonRecord, key: string, where: string, fallback: boolean): boolean {
  const value = source[key];
  if (value === undefined || value === null) return fallback;
  if (typeof value !== "boolean") {
    throw new EditorProjectError("field_not_a_boolean", `${key} must be true or false`, where);
  }
  return value;
}

function arrayField(source: JsonRecord, key: string, where: string): unknown[] {
  const value = source[key];
  if (value === undefined || value === null) return [];
  if (!Array.isArray(value)) {
    throw new EditorProjectError("field_not_an_array", `${key} must be an array`, where);
  }
  return value;
}

function parseTrack(raw: unknown, index: number): Track {
  if (!isRecord(raw)) throw new EditorProjectError("track_not_an_object", "tracks must be objects", `tracks[${index}]`);
  const id = stringField(raw, "id", `tracks[${index}]`);
  if (!id) throw new EditorProjectError("track_id_missing", "a track has no id", `tracks[${index}]`);
  const type = stringField(raw, "type", id, "");
  const where = `track ${id}`;
  const group = stringField(raw, "group", where, type === "audio" ? "audio" : "visual");
  if (group !== "audio" && group !== "visual") {
    throw new EditorProjectError("track_group_unknown", `group must be audio or visual`, where);
  }
  return {
    ...(raw as object),
    id,
    index: intField(raw, "index", where, "track_index_not_integer", index),
    type,
    name: stringField(raw, "name", where) || null,
    group,
    visible: boolField(raw, "visible", where, true),
    muted: boolField(raw, "muted", where, false),
    lane: intField(raw, "lane", where, "track_lane_not_integer", index),
    clip_ids: arrayField(raw, "clip_ids", where).map(String),
    clip_count: intField(raw, "clip_count", where, "track_count_not_integer", 0),
  } as Track;
}

function parseClip(raw: unknown, index: number, trackIds: Set<string>): Clip {
  if (!isRecord(raw)) throw new EditorProjectError("clip_not_an_object", "clips must be objects", `clips[${index}]`);
  const clipId = stringField(raw, "clip_id", `clips[${index}]`);
  if (!clipId) throw new EditorProjectError("clip_id_missing", "a clip has no clip_id", `clips[${index}]`);
  const where = `clip ${clipId}`;
  const start = intField(raw, "target_start_us", where, "clip_time_not_integer");
  const duration = intField(raw, "target_duration_us", where, "clip_time_not_integer", 0);
  const end = intField(raw, "target_end_us", where, "clip_time_not_integer", start + duration);
  if (end < start) {
    throw new EditorProjectError("clip_span_inverted", "target_end_us is before target_start_us", where);
  }
  if (duration !== end - start) {
    throw new EditorProjectError("clip_span_mismatch", "target_duration_us does not match the span", where);
  }
  if (!trackIds.has(stringField(raw, "track_id", where, ""))) {
    throw new EditorProjectError("clip_track_missing", "the clip belongs to a track that is not in the document", where);
  }
  const speed = raw.speed === undefined || raw.speed === null ? 1 : Number(raw.speed);
  if (!Number.isFinite(speed) || speed <= 0) {
    throw new EditorProjectError("clip_speed_unusable", "speed must be a positive number", where);
  }
  const sourceStart = intField(raw, "source_start_us", where, "clip_time_not_integer", 0);
  const sourceDuration = intField(raw, "source_duration_us", where, "clip_time_not_integer", 0);
  const warnings = arrayField(raw, "warnings", where);
  return {
    ...(raw as object),
    clip_id: clipId,
    segment_id: stringField(raw, "segment_id", where, clipId),
    track_id: stringField(raw, "track_id", where),
    track_index: intField(raw, "track_index", where, "clip_field_not_integer", 0),
    track_type: stringField(raw, "track_type", where, ""),
    kind: stringField(raw, "kind", where, "none"),
    z_index: intField(raw, "z_index", where, "clip_z_index_not_integer", index),
    visible: boolField(raw, "visible", where, true),
    muted: boolField(raw, "muted", where, false),
    target_start_us: start,
    target_end_us: end,
    target_duration_us: duration,
    source_start_us: sourceStart,
    source_duration_us: sourceDuration,
    source_end_us: intField(raw, "source_end_us", where, "clip_time_not_integer", sourceStart + sourceDuration),
    speed,
    reverse: boolField(raw, "reverse", where, false),
    warnings: warnings.map(String),
    labels: arrayField(raw, "labels", where).filter(isRecord) as Record<string, unknown>[],
    animation: isRecord(raw.animation) ? (raw.animation as Record<string, unknown>) : null,
    transition: isRecord(raw.transition) ? (raw.transition as Record<string, unknown>) : null,
    canvas_fill: isRecord(raw.canvas_fill) ? (raw.canvas_fill as Record<string, unknown>) : null,
    position: intField(raw, "position", where, "clip_field_not_integer", 0),
  } as Clip;
}

function deepFreeze<T>(value: T): T {
  if (value && typeof value === "object") {
    for (const inner of Object.values(value as Record<string, unknown>)) deepFreeze(inner);
    Object.freeze(value);
  }
  return value;
}

export function parseEditorProject(payload: unknown): EditorProject {
  const source = unwrap(payload);
  const schema = stringField(source, "schema", "project");
  if (schema !== PROJECT_SCHEMA) {
    throw new EditorProjectError("schema_unsupported", `expected ${PROJECT_SCHEMA}, got ${schema || "nothing"}`);
  }
  if (source.read_only !== true) {
    throw new EditorProjectError("not_read_only", "the editor refuses a document that is not marked read-only");
  }
  if (!isRecord(source.timeline) || !stringField(source.timeline, "id", "timeline")) {
    throw new EditorProjectError("timeline_id_missing", "the document carries no timeline identity");
  }
  if (!isRecord(source.canvas)) throw new EditorProjectError("canvas_missing", "the document carries no canvas box");
  const canvas = source.canvas;
  const width = intField(canvas, "width", "canvas", "canvas_not_sized");
  const height = intField(canvas, "height", "canvas", "canvas_not_sized");
  if (width <= 0 || height <= 0) throw new EditorProjectError("canvas_not_sized", "canvas must be positive", "canvas");

  const tracks = arrayField(source, "tracks", "project").map(parseTrack);
  const trackIds = new Set(tracks.map((track) => track.id));
  if (trackIds.size !== tracks.length) {
    throw new EditorProjectError("duplicate_track_id", "two tracks share an id");
  }
  const seen = new Set<string>();
  const clips = arrayField(source, "clips", "project").map((raw, index) => {
    const clip = parseClip(raw, index, trackIds);
    if (seen.has(clip.clip_id)) {
      throw new EditorProjectError("duplicate_clip_id", "two clips share an id", `clip ${clip.clip_id}`);
    }
    seen.add(clip.clip_id);
    return clip;
  });

  const timeline = source.timeline as JsonRecord;
  const duration = intField(source, "duration_us", "project", "duration_not_integer",
                            clips.reduce((high, clip) => Math.max(high, clip.target_end_us), 0));
  const draft = isRecord(source.draft) ? source.draft : {};

  return deepFreeze({
    ...(source as object),
    schema: PROJECT_SCHEMA,
    read_only: true as const,
    draft: {
      ...(draft as object),
      id: stringField(draft, "id", "draft"),
      name: stringField(draft, "name", "draft"),
      path: stringField(draft, "path", "draft"),
      layout: stringField(draft, "layout", "draft", "unknown"),
      active_timeline_id: stringField(draft, "active_timeline_id", "draft") || null,
      timelines: arrayField(draft, "timelines", "draft").map((raw) => (isRecord(raw) ? raw : {})) as TimelineRef[],
    } as DraftRef,
    timeline: {
      ...(timeline as object),
      id: stringField(timeline, "id", "timeline"),
      name: stringField(timeline, "name", "timeline") || null,
      encoding: stringField(timeline, "encoding", "timeline") || null,
      content_file: stringField(timeline, "content_file", "timeline") || null,
      source_path: stringField(timeline, "source_path", "timeline") || null,
      source_sha256: stringField(timeline, "source_sha256", "timeline") || null,
      active: boolField(timeline, "active", "timeline", false),
      duration_us: intField(timeline, "duration_us", "timeline", "duration_not_integer", duration),
    } as TimelineIdentity,
    canvas: {
      ...(canvas as object),
      width, height,
      ratio: stringField(canvas, "ratio", "canvas", ""),
      background: stringField(canvas, "background", "canvas", "#000000"),
    } as CanvasBox,
    fps: Number.isFinite(Number(source.fps)) && Number(source.fps) > 0 ? Number(source.fps) : 0,
    duration_us: duration,
    declared_duration_us: intField(source, "declared_duration_us", "project", "duration_not_integer", duration),
    scene_rules: (isRecord(source.scene_rules) ? source.scene_rules : {
      time_unit: "us", interval: "half_open", paint_order: "ascending z_index",
    }) as unknown as SceneRules,
    tracks,
    clips,
    assets: arrayField(source, "assets", "project")
      .filter(isRecord)
      .map((raw, index) => ({
        ...(raw as object),
        asset_id: stringField(raw, "asset_id", `assets[${index}]`, `assets[${index}]`),
        kind: stringField(raw, "kind", `assets[${index}]`) || null,
        name: stringField(raw, "name", `assets[${index}]`) || null,
        path_served: stringField(raw, "path_served", `assets[${index}]`) || null,
        exists: boolField(raw, "exists", `assets[${index}]`, false),
        how: stringField(raw, "how", `assets[${index}]`) || null,
        placeholder_reason: stringField(raw, "placeholder_reason", `assets[${index}]`) || null,
        clip_ids: arrayField(raw, "clip_ids", `assets[${index}]`).map(String),
      })) as Asset[],
    warnings: arrayField(source, "warnings", "project").map(String),
  } as unknown as EditorProject);
}

export async function openEditorSession(options: EditorSessionOptions): Promise<EditorSession> {
  const draft = (options.draft ?? "").trim();
  if (!draft) {
    throw new EditorProjectError("draft_selector_missing", "a draft selector (did, name or path) is required");
  }
  const clock = new PlaybackClock({
    durationUs: 0,
    now: options.now,
    schedule: options.schedule,
    maxElapsedUs: options.maxElapsedUs,
  });
  let current = parseEditorProject(await options.load({ draft, timeline: options.timeline }));
  let activeTimeline = options.timeline;
  clock.setDuration(current.duration_us);
  let stale: StaleNotice | null = null;
  let destroyed = false;
  const sceneListeners = new Set<(scene: Scene, snapshot: ClockSnapshot) => void>();
  const staleListeners = new Set<(notice: StaleNotice) => void>();
  const detachClock = clock.subscribe((snapshot) => {
    if (destroyed) return;
    const scene = resolveScene(snapshot.tUs, current);
    for (const listener of [...sceneListeners]) {
      try {
        listener(scene, snapshot);
      } catch (error) {
        console.error("scene listener failed", error);
      }
    }
  });

  async function adopt(timeline: string | undefined): Promise<EditorProject> {
    const next = parseEditorProject(await options.load({ draft, timeline }));
    clock.pause();
    current = next;
    activeTimeline = timeline;
    stale = null;
    clock.setDuration(next.duration_us);
    clock.seek(0);
    return next;
  }

  const session: EditorSession = {
    clock,
    project: () => current,
    sceneAt: (tUs?: number) => resolveScene(tUs ?? clock.tUs, current),
    timelines: () => current.draft.timelines,
    activeTimelineId: () => current.draft.active_timeline_id,
    currentTimelineId: () => current.timeline.id,
    async selectTimeline(timelineId: string): Promise<EditorProject> {
      const wanted = (timelineId ?? "").trim();
      if (!wanted) {
        throw new EditorProjectError("timeline_selector_missing", "name the timeline to open");
      }
      return adopt(wanted);
    },
    reload: () => adopt(activeTimeline),
    play: () => clock.play(),
    pause: () => clock.pause(),
    seekTo: (tUs: number) => clock.seek(tUs),
    setRate: (rate: number) => clock.setRate(rate),
    rate: () => clock.rate,
    status: () => clock.status,
    onHidden: () => clock.onHidden(),
    onVisible: () => clock.onVisible(),
    subscribeScene(listener) {
      sceneListeners.add(listener);
      return () => sceneListeners.delete(listener);
    },
    subscribeStale(listener) {
      staleListeners.add(listener);
      return () => staleListeners.delete(listener);
    },
    markStale(reason: string) {
      if (destroyed || stale) return;
      stale = { reason, timeline_id: current.timeline.id, duration_us: current.duration_us };
      for (const listener of [...staleListeners]) listener(stale);
    },
    isStale: () => stale !== null,
    destroy() {
      if (destroyed) return;
      destroyed = true;
      detachClock();
      sceneListeners.clear();
      staleListeners.clear();
      clock.destroy();
    },
  };
  return session;
}
