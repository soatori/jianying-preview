/** Hand-written `jypreview/editor-project@1` fixtures for the core tests.
 *
 * Field-for-field the shape `scripts/jypreview/model/editor_project.py` emits, so a test
 * that passes here cannot pass against a payload Python never produces.
 */

import { PROJECT_SCHEMA } from "../core/project.ts";

export function clipFixture(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  const start = (overrides.target_start_us as number | undefined) ?? 0;
  const explicitEnd = overrides.target_end_us as number | undefined;
  const explicitDuration = overrides.target_duration_us as number | undefined;
  // Keep start/end/duration consistent: the parser rejects a span that contradicts itself.
  const duration = explicitDuration ?? (explicitEnd !== undefined ? explicitEnd - start : 1_000_000);
  const end = explicitEnd ?? start + duration;
  return {
    clip_id: "C-1",
    segment_id: "C-1",
    track_id: "T-VIDEO",
    track_index: 0,
    track_type: "video",
    position: 0,
    kind: "video",
    z_index: 0,
    visible: true,
    muted: false,
    target_start_us: start,
    target_end_us: end,
    target_duration_us: duration,
    source_start_us: 0,
    source_duration_us: duration,
    source_end_us: duration,
    speed: 1,
    reverse: false,
    material_id: "M-1",
    asset_id: "m:M-1",
    asset: {
      asset_id: "m:M-1",
      kind: "video",
      material_id: "M-1",
      name: "a.mp4",
      path_raw: "D:/media/a.mp4",
      path_served: "/media?f=abc",
      exists: true,
      how: "direct",
      material_type: "video",
      material_duration_us: 10_000_000,
      probe: { codec: "h264", width: 1920, height: 1080, duration_us: 10_000_000, frame_rate: 30 },
      placeholder_reason: null,
      clip_ids: ["C-1"],
    },
    warnings: [],
    sampled: null,
    media: null,
    rect: {
      cx_px: 540, cy_px: 960, w_px: 1080, h_px: 607.5, rotation_deg: 0, flip_x: false,
      flip_y: false, alpha: 1, scale_x: 1, scale_y: 1, z_px: 0,
      css: { width: "1080px", height: "607.5px", transform: "translate(0px, 356.25px)",
             "transform-origin": "center", opacity: "1" },
    },
    css: { width: "1080px", height: "607.5px", transform: "translate(0px, 356.25px)",
           "transform-origin": "center", opacity: "1" },
    text: null,
    labels: [],
    transition: null,
    animation: null,
    keyframes: null,
    applies: null,
    nest: null,
    ...overrides,
  };
}

export function trackFixture(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: "T-VIDEO",
    index: 0,
    type: "video",
    name: null,
    group: "visual",
    visible: true,
    muted: false,
    flag: null,
    attribute: null,
    render_index: null,
    z_ri: 0,
    clip_ids: ["C-1"],
    clip_count: 1,
    span_end_us: 1_000_000,
    hidden_segment_count: 0,
    lane: 0,
    ...overrides,
  };
}

export type RawProject = {
  [key: string]: unknown;
  timeline: Record<string, unknown>;
  draft: Record<string, unknown>;
}

export function projectFixture(overrides: Record<string, unknown> = {}): RawProject {
  return {
    schema: PROJECT_SCHEMA,
    read_only: true,
    draft: {
      id: "cd30ce559c3c5b0f",
      name: "fixture-draft",
      path: "D:/JianyingPro/JianyingPro Drafts/fixture-draft",
      layout: "hybrid",
      active_timeline_id: "TL-ACTIVE",
      timelines: [
        { id: "TL-ACTIVE", name: "成片", active: true, deleted: false, duration_us: 4_000_000 },
        { id: "TL-OTHER", name: "备用", active: false, deleted: false, duration_us: 2_000_000 },
      ],
    },
    timeline: {
      id: "TL-ACTIVE",
      name: "成片",
      encoding: "jianying-dll",
      content_file: "Timelines/TL-ACTIVE/draft_content.json",
      source_sha256: "9eac9dd0f23824aa4201ca61dde1c010",
      replica_drift: false,
      mirror_drift: false,
      active: true,
      source_path: "D:/JianyingPro/JianyingPro Drafts/fixture-draft/Timelines/TL-ACTIVE/draft_content.json",
      duration_us: 4_000_000,
      declared_duration_us: 4_000_000,
      segment_count: 2,
    },
    canvas: { width: 1080, height: 1920, ratio: "9:16", background: "#000000" },
    fps: 30,
    duration_us: 4_000_000,
    declared_duration_us: 4_000_000,
    size_rule: { px_per_size: 6.75, basis: "width", scale_factor: 0.00625, fit_mode: "contain_unrotated" },
    scene_rules: {
      time_unit: "us",
      interval: "half_open",
      clip_is_visible_at: "target_start_us <= t_us < target_end_us",
      paint_order: "ascending z_index",
      visual_kinds: ["video", "photo", "image", "sticker", "text", "subdraft", "effect", "filter", "adjust"],
    },
    tracks: [trackFixture()],
    clips: [clipFixture({ target_start_us: 0, target_end_us: 2_000_000, target_duration_us: 2_000_000 }),
            clipFixture({ clip_id: "C-2", segment_id: "C-2", z_index: 1, source_start_us: 2_000_000,
                          source_end_us: 4_000_000, target_start_us: 2_000_000,
                          target_end_us: 4_000_000, target_duration_us: 2_000_000 })],
    assets: [(clipFixture().asset as Record<string, unknown>)],
    warnings: [],
    stats: { layers_total: 2, media_missing: 0, fonts: {}, labels: { exact: 0, approx: 0, placeholder: 0 },
             flowers: 0, mode: "window", window_layers: 2 },
    ...overrides,
  } as RawProject;
}
