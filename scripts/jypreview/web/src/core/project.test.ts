import { describe, expect, it, vi } from "vitest";

import { PlaybackClock } from "./playback-clock.ts";
import {
  EditorProjectError,
  TimelineAmbiguousError,
  openEditorSession,
  parseEditorProject,
  type EditorSession,
} from "./project.ts";
import { resolveScene } from "./scene.ts";
import { clipFixture, projectFixture, trackFixture } from "../testing/project-fixture.ts";

function envelope(data: unknown) {
  return { ok: true, code: "ok", reason: "", data };
}

describe("parseEditorProject", () => {
  it("accepts the document the Python service produces, bare or enveloped", () => {
    const parsed = parseEditorProject(projectFixture());
    expect(parsed.duration_us).toBe(4_000_000);
    expect(parsed.clips.map((clip) => clip.clip_id)).toEqual(["C-1", "C-2"]);
    expect(parseEditorProject(envelope(projectFixture())).timeline.id).toBe("TL-ACTIVE");
  });

  it("keeps the inspector data it does not understand", () => {
    const parsed = parseEditorProject(projectFixture({
      clips: [clipFixture({ canvas_fill: { type: "canvas_blur", blur: 0.6 } })],
    }));
    expect(parsed.clips[0]?.canvas_fill).toEqual({ type: "canvas_blur", blur: 0.6 });
  });

  it("refuses a payload from another schema", () => {
    expect(() => parseEditorProject(projectFixture({ schema: "jy-preview/framedesc@1" })))
      .toThrowError(EditorProjectError);
    try {
      parseEditorProject(projectFixture({ schema: "jy-preview/framedesc@1" }));
    } catch (error) {
      expect((error as EditorProjectError).code).toBe("schema_unsupported");
    }
  });

  it("refuses a document that is not read-only", () => {
    try {
      parseEditorProject(projectFixture({ read_only: false }));
      throw new Error("expected a rejection");
    } catch (error) {
      expect(error).toBeInstanceOf(EditorProjectError);
      expect((error as EditorProjectError).code).toBe("not_read_only");
    }
  });

  it("rejects a non-integer microsecond field", () => {
    const bad = projectFixture({ clips: [clipFixture({ target_end_us: 1_000_000.5 })] });
    try {
      parseEditorProject(bad);
      throw new Error("expected a rejection");
    } catch (error) {
      expect((error as EditorProjectError).code).toBe("clip_time_not_integer");
      expect((error as EditorProjectError).where).toContain("C-1");
    }
  });

  it("rejects an inverted clip span", () => {
    const bad = projectFixture({
      clips: [clipFixture({ clip_id: "BAD", target_start_us: 5_000_000, target_end_us: 4_000_000 })],
    });
    expect(() => parseEditorProject(bad)).toThrowError(/BAD/);
  });

  it("rejects duplicate clip ids, which cannot become two DOM nodes", () => {
    const bad = projectFixture({ clips: [clipFixture(), clipFixture()] });
    try {
      parseEditorProject(bad);
      throw new Error("expected a rejection");
    } catch (error) {
      expect((error as EditorProjectError).code).toBe("duplicate_clip_id");
    }
  });

  it("rejects a clip that belongs to no track", () => {
    const bad = projectFixture({
      clips: [clipFixture({ track_id: "T-GHOST" })],
      tracks: [trackFixture({ id: "T-VIDEO" })],
    });
    try {
      parseEditorProject(bad);
      throw new Error("expected a rejection");
    } catch (error) {
      expect((error as EditorProjectError).code).toBe("clip_track_missing");
    }
  });

  it("rejects a document with no timeline identity", () => {
    const bad = projectFixture({ timeline: { ...projectFixture().timeline, id: "" } });
    try {
      parseEditorProject(bad);
      throw new Error("expected a rejection");
    } catch (error) {
      expect((error as EditorProjectError).code).toBe("timeline_id_missing");
    }
  });

  it("turns a service error envelope into the matching typed error", () => {
    const failure = { ok: false, code: "timeline_ambiguous", reason: "no provable active timeline",
                      data: { available: ["TL-ACTIVE", "TL-OTHER"] } };
    try {
      parseEditorProject(failure);
      throw new Error("expected a rejection");
    } catch (error) {
      expect(error).toBeInstanceOf(TimelineAmbiguousError);
      expect((error as TimelineAmbiguousError).available).toEqual(["TL-ACTIVE", "TL-OTHER"]);
    }
  });

  it("rejects garbage that is not a document at all", () => {
    for (const value of [null, undefined, 42, "draft", [], true]) {
      expect(() => parseEditorProject(value)).toThrowError(EditorProjectError);
    }
  });

  it("freezes the snapshot so no consumer can edit it", () => {
    const parsed = parseEditorProject(projectFixture());
    expect(Object.isFrozen(parsed)).toBe(true);
    expect(Object.isFrozen(parsed.clips[0])).toBe(true);
    expect(Object.isFrozen(parsed.clips[0]?.rect?.css)).toBe(true);
    expect(() => {
      (parsed.clips[0] as { z_index: number }).z_index = 99;
    }).toThrow();
    expect(resolveScene(0, parsed).clips[0]?.clip.z_index).not.toBe(99);
  });
});

describe("EditorSession", () => {
  function fakeClock() {
    let ms = 0;
    let task: (() => void) | null = null;
    const now = () => ms;
    const schedule = (fn: () => void) => {
      task = fn;
      return () => {
        task = null;
      };
    };
    const advance = (delta: number) => {
      ms += delta;
      const run = task;
      task = null;
      run?.();
    };
    return { now, schedule, advance };
  }

  async function session(options: { timeline?: string; project?: unknown } = {}) {
    const clock = fakeClock();
    const load = vi.fn(async (request: { draft: string; timeline?: string }) => {
      if (request.timeline === "TL-BROKEN") {
        return { ok: false, code: "decrypt_failed", reason: "dll refused", data: {} };
      }
      return envelope(options.project ?? projectFixture({
        timeline: { ...projectFixture().timeline, id: request.timeline ?? "TL-ACTIVE" },
        draft: { ...projectFixture().draft, active_timeline_id: request.timeline ? null : "TL-ACTIVE" },
      }));
    });
    const opened = await openEditorSession({
      draft: "cd30ce559c3c5b0f",
      timeline: options.timeline,
      load,
      now: clock.now,
      schedule: clock.schedule,
    });
    return { session: opened, load, clock };
  }

  it("opens a draft and clocks the timeline it was given", async () => {
    const { session: opened, load } = await session();
    expect(load).toHaveBeenCalledWith({ draft: "cd30ce559c3c5b0f", timeline: undefined });
    expect(opened.project().timeline.id).toBe("TL-ACTIVE");
    expect(opened.clock).toBeInstanceOf(PlaybackClock);
    expect(opened.clock.durationUs).toBe(4_000_000);
    expect(opened.clock.tUs).toBe(0);
    opened.destroy();
  });

  it("lists the draft's timelines and its provable active one", async () => {
    const { session: opened } = await session();
    expect(opened.timelines().map((item) => item.id)).toEqual(["TL-ACTIVE", "TL-OTHER"]);
    expect(opened.activeTimelineId()).toBe("TL-ACTIVE");
    expect(opened.currentTimelineId()).toBe("TL-ACTIVE");
    opened.destroy();
  });

  it("reports no active timeline when the service could not prove one", async () => {
    const ambiguous = projectFixture({
      draft: { ...projectFixture().draft, active_timeline_id: null },
      timeline: { ...projectFixture().timeline, active: false },
    });
    const { session: opened } = await session({ project: ambiguous });
    expect(opened.activeTimelineId()).toBeNull();
    opened.destroy();
  });

  it("switches timelines without editing anything", async () => {
    const { session: opened, load } = await session();
    opened.clock.play();
    const before = opened.project();
    const next = await opened.selectTimeline("TL-OTHER");
    expect(load).toHaveBeenLastCalledWith({ draft: "cd30ce559c3c5b0f", timeline: "TL-OTHER" });
    expect(next.timeline.id).toBe("TL-OTHER");
    expect(opened.currentTimelineId()).toBe("TL-OTHER");
    expect(opened.clock.durationUs).toBe(4_000_000);
    expect(opened.clock.status).not.toBe("playing");
    expect(before).not.toBe(next);
    expect(load).toHaveBeenCalledTimes(2);
    opened.destroy();
  });

  it("surfaces a failed timeline switch and keeps the current document", async () => {
    const { session: opened } = await session();
    await expect(opened.selectTimeline("TL-BROKEN")).rejects.toThrowError(/dll refused/);
    expect(opened.currentTimelineId()).toBe("TL-ACTIVE");
    opened.destroy();
  });

  it("emits a scene for every clock change and on subscription", async () => {
    const { session: opened, clock } = await session();
    const seen: string[] = [];
    opened.subscribeScene((scene) => seen.push(`${scene.tUs}:${scene.clips.length}`));
    opened.seekTo(500_000);
    clock.advance(1000);
    opened.play();
    clock.advance(500);
    expect(seen).toEqual(["500000:1", "500000:1", "1000000:1"]);
    expect(opened.sceneAt().tUs).toBe(1_000_000);
    opened.destroy();
  });

  it("exposes read-only playback controls that the clock honours", async () => {
    const { session: opened, clock } = await session();
    opened.play();
    clock.advance(1000);
    expect(opened.clock.tUs).toBe(1_000_000);
    opened.pause();
    clock.advance(1000);
    expect(opened.clock.tUs).toBe(1_000_000);
    opened.setRate(2);
    expect(opened.rate()).toBe(2);
    opened.seekTo(999_999_999);
    expect(opened.clock.tUs).toBe(4_000_000);
    opened.destroy();
  });

  it("marks the document stale on a draft change instead of reloading mid-playback", async () => {
    const { session: opened, load } = await session();
    const notes: string[] = [];
    opened.subscribeStale((stale) => notes.push(`${stale.reason}:${stale.duration_us}`));
    opened.clock.play();
    opened.markStale("draft-content-changed");
    expect(opened.isStale()).toBe(true);
    expect(load).toHaveBeenCalledTimes(1);
    expect(opened.clock.status).toBe("playing");
    expect(notes).toEqual(["draft-content-changed:4000000"]);
    const refreshed = await opened.reload();
    expect(refreshed.timeline.id).toBe("TL-ACTIVE");
    expect(opened.isStale()).toBe(false);
    expect(load).toHaveBeenCalledTimes(2);
    opened.destroy();
  });

  it("re-anchors the clock when the page returns from being hidden", async () => {
    const { session: opened, clock } = await session();
    opened.play();
    clock.advance(500);
    opened.onHidden();
    clock.advance(30_000);
    opened.onVisible();
    expect(opened.clock.tUs).toBe(500_000);
    expect(opened.clock.status).toBe("playing");
    opened.destroy();
  });

  it("refuses to load without naming a draft", async () => {
    await expect(openEditorSession({ draft: "", load: async () => envelope(projectFixture()) }))
      .rejects.toThrowError(EditorProjectError);
  });

  it("stops feeding scenes after destroy", async () => {
    const { session: opened, clock } = await session();
    const listener = vi.fn();
    opened.subscribeScene(listener);
    opened.destroy();
    clock.advance(1000);
    expect(listener).not.toHaveBeenCalled();
    expect(opened.clock.status).toBe("destroyed");
  });
});
