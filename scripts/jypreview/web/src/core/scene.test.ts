import { describe, expect, it } from "vitest";

import { parseEditorProject, PROJECT_SCHEMA } from "./project.ts";
import { resolveScene } from "./scene.ts";
import { clipFixture, projectFixture, trackFixture } from "../testing/project-fixture.ts";

function project(clips: Record<string, unknown>[], tracks?: Record<string, unknown>[]) {
  return parseEditorProject(projectFixture({ clips, tracks: tracks ?? [trackFixture()] }));
}

describe("resolveScene visibility", () => {
  it("treats every clip span as half-open", () => {
    const scene = project([
      clipFixture({ clip_id: "A", target_start_us: 0, target_end_us: 2_000_000 }),
      clipFixture({ clip_id: "B", target_start_us: 2_000_000, target_end_us: 4_000_000 }),
    ]);
    expect(resolveScene(1_999_999, scene).clips.map((item) => item.clip.clip_id)).toEqual(["A"]);
    expect(resolveScene(2_000_000, scene).clips.map((item) => item.clip.clip_id)).toEqual(["B"]);
    expect(resolveScene(0, scene).clips).toHaveLength(1);
    expect(resolveScene(4_000_000, scene).clips).toEqual([]);
  });

  it("excludes zero-length and hidden clips, and clips outside the timeline", () => {
    const scene = project([
      clipFixture({ clip_id: "EMPTY", target_start_us: 1_000_000, target_end_us: 1_000_000,
                    target_duration_us: 0 }),
      clipFixture({ clip_id: "HIDDEN", visible: false, target_start_us: 0, target_end_us: 4_000_000 }),
      clipFixture({ clip_id: "LATE", target_start_us: 8_000_000, target_end_us: 9_000_000 }),
    ]);
    expect(resolveScene(1_000_000, scene).clips.map((item) => item.clip.clip_id)).toEqual([]);
    expect(resolveScene(8_500_000, scene).clips.map((item) => item.clip.clip_id)).toEqual(["LATE"]);
  });

  it("drops clips on a hidden track but keeps the lane data intact", () => {
    const scene = project(
      [clipFixture({ clip_id: "ON-HIDDEN-TRACK", track_id: "T-HIDE" })],
      [trackFixture({ id: "T-HIDE", visible: false })],
    );
    expect(resolveScene(0, scene).clips).toEqual([]);
    expect(scene.tracks[0]?.visible).toBe(false);
    expect(scene.clips).toHaveLength(1);
  });

  it("separates audio from the picture and honours its mute flag", () => {
    const scene = project([
      clipFixture({ clip_id: "PIC" }),
      clipFixture({ clip_id: "SOUND", kind: "audio", track_id: "T-AUDIO", track_type: "audio",
                    muted: true, asset: null, asset_id: null }),
    ], [trackFixture(), trackFixture({ id: "T-AUDIO", type: "audio", group: "audio", muted: true, lane: 1 })]);
    const at = resolveScene(0, scene);
    expect(at.clips.map((item) => item.clip.clip_id)).toEqual(["PIC"]);
    expect(at.audio.map((item) => item.clip.clip_id)).toEqual(["SOUND"]);
    expect(at.audio[0]?.muted).toBe(true);
  });

  it("keeps effect, filter and adjust layers so their chips stay on screen", () => {
    const scene = project([
      clipFixture({ clip_id: "EFFECT", kind: "effect" }),
      clipFixture({ clip_id: "FILTER", kind: "filter" }),
      clipFixture({ clip_id: "ADJUST", kind: "adjust" }),
      clipFixture({ clip_id: "TEXT", kind: "text" }),
    ]);
    expect(resolveScene(0, scene).clips.map((item) => item.clip.clip_id))
      .toEqual(["EFFECT", "FILTER", "ADJUST", "TEXT"]);
  });
});

describe("resolveScene ordering", () => {
  it("paints in ascending z_index regardless of payload order", () => {
    const scene = project([
      clipFixture({ clip_id: "TOP", z_index: 40 }),
      clipFixture({ clip_id: "MIDDLE", z_index: 12 }),
      clipFixture({ clip_id: "BOTTOM", z_index: 3 }),
    ]);
    expect(resolveScene(0, scene).clips.map((item) => item.clip.clip_id))
      .toEqual(["BOTTOM", "MIDDLE", "TOP"]);
  });

  it("is stable for equal z_index so two runs cannot disagree", () => {
    const scene = project([
      clipFixture({ clip_id: "X", z_index: 5, position: 1 }),
      clipFixture({ clip_id: "Y", z_index: 5, position: 0 }),
    ]);
    const first = resolveScene(0, scene).clips.map((item) => item.clip.clip_id);
    const second = resolveScene(0, scene).clips.map((item) => item.clip.clip_id);
    expect(second).toEqual(first);
  });
});

describe("resolveScene time mapping", () => {
  it("maps local time through speed", () => {
    const scene = project([
      clipFixture({ clip_id: "FAST", speed: 2, target_start_us: 0, target_end_us: 1_000_000,
                    target_duration_us: 1_000_000, source_start_us: 5_000_000,
                    source_duration_us: 2_000_000 }),
    ]);
    const active = resolveScene(500_000, scene).clips[0];
    expect(active?.localUs).toBe(500_000);
    expect(active?.sourceTimeUs).toBe(6_000_000);
    expect(active?.progress).toBe(0.5);
  });

  it("walks the source backwards for a reversed clip", () => {
    const scene = project([
      clipFixture({ clip_id: "REV", reverse: true, target_start_us: 0, target_end_us: 2_000_000,
                    target_duration_us: 2_000_000, source_start_us: 1_000_000,
                    source_duration_us: 3_000_000 }),
    ]);
    expect(resolveScene(0, scene).clips[0]?.sourceTimeUs).toBe(4_000_000);
    expect(resolveScene(1_000_000, scene).clips[0]?.sourceTimeUs).toBe(3_000_000);
    expect(resolveScene(1_999_999, scene).clips[0]?.sourceTimeUs).toBe(2_000_001);
  });

  it("falls back to speed-scaled span when the source range is empty", () => {
    const scene = project([
      clipFixture({ clip_id: "NO-SRC", source_duration_us: 0, source_end_us: 0,
                    target_start_us: 0, target_end_us: 2_000_000, target_duration_us: 2_000_000 }),
    ]);
    expect(resolveScene(1_000_000, scene).clips[0]?.sourceTimeUs).toBe(1_000_000);
  });

  it("reports progress zero for a degenerate span", () => {
    const scene = project([clipFixture({ clip_id: "P", target_start_us: 0, target_end_us: 1 })]);
    expect(resolveScene(0, scene).clips[0]?.progress).toBe(0);
  });
});

describe("resolveScene purity", () => {
  it("returns the same scene twice and never mutates the project", () => {
    const scene = project([clipFixture({ clip_id: "A" }), clipFixture({ clip_id: "B" })]);
    const before = JSON.stringify(scene);
    const first = resolveScene(500_000, scene);
    const second = resolveScene(500_000, scene);
    expect(second).toEqual(first);
    expect(JSON.stringify(scene)).toBe(before);
  });

  it("runs with no browser globals present", () => {
    const scene = project([clipFixture({ clip_id: "A" })]);
    // Vitest's node environment has no DOM at all: a resolver that reached for one would throw.
    expect(typeof document).toBe("undefined");
    expect(typeof window).toBe("undefined");
    expect(resolveScene(0, scene).clips).toHaveLength(1);
  });

  it("coerces a fractional time to whole microseconds", () => {
    const scene = project([clipFixture({ clip_id: "A" })]);
    expect(resolveScene(123_456.7, scene).tUs).toBe(123_457);
  });

  it("carries the timeline identity the inspector shows", () => {
    const scene = project([clipFixture({ clip_id: "A" })]);
    const at = resolveScene(0, scene);
    expect(at.timeline.id).toBe("TL-ACTIVE");
    expect(at.timeline.source_sha256).toBe("9eac9dd0f23824aa4201ca61dde1c010");
    expect(at.durationUs).toBe(4_000_000);
    expect(at.canvas.width).toBe(1080);
    expect(at.frameUs).toBe(33_333);
  });
});

describe("resolveScene warnings", () => {
  it("surfaces only the warnings of clips that are on screen", () => {
    const scene = project([
      clipFixture({ clip_id: "OFFSCREEN", target_start_us: 3_000_000, target_end_us: 4_000_000,
                    warnings: ["media unavailable (missing)"] }),
      clipFixture({ clip_id: "ONSCREEN", warnings: ["animation not rendered: 渐隐"] }),
    ]);
    const at = resolveScene(0, scene);
    expect(at.warnings).toEqual(["ONSCREEN: animation not rendered: 渐隐"]);
    expect(resolveScene(3_500_000, scene).warnings)
      .toEqual(["OFFSCREEN: media unavailable (missing)"]);
  });

  it("keeps a clip with no asset navigable by labelling the placeholder", () => {
    const scene = project([clipFixture({ clip_id: "NO-ASSET", asset: null, asset_id: null })]);
    const at = resolveScene(0, scene);
    expect(at.clips).toHaveLength(1);
    expect(at.clips[0]?.clip.asset).toBeNull();
  });
});

describe("schema constant", () => {
  it("pins the contract this core was written against", () => {
    expect(PROJECT_SCHEMA).toBe("jypreview/editor-project@1");
  });
});
