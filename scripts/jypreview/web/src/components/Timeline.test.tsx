// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { parseEditorProject, type EditorProject } from "../core/project.ts";
import { clipFixture, projectFixture, trackFixture } from "../testing/project-fixture.ts";
import { Timeline } from "./Timeline.tsx";

afterEach(cleanup);

const SCALE = 0.0002;

function setup(clips: Record<string, unknown>[] = [
  clipFixture({ clip_id: "A", target_start_us: 0, target_end_us: 2_000_000, target_duration_us: 2_000_000 }),
  clipFixture({ clip_id: "B", target_start_us: 2_000_000, target_end_us: 4_000_000,
                target_duration_us: 2_000_000, z_index: 1 }),
], tracks: Record<string, unknown>[] = [trackFixture({ id: "T-VIDEO", lane: 0 })]) {
  const project: EditorProject = parseEditorProject(projectFixture({ clips, tracks }));
  const onSelectClip = vi.fn();
  const onSeek = vi.fn();
  const view = render(<Timeline project={project} tUs={1_000_000} selectedClipId={null}
                                pxPerUs={SCALE} onSelectClip={onSelectClip} onSeek={onSeek} />);
  return { view, project, onSelectClip, onSeek };
}

const clip = (container: HTMLElement, id: string) =>
  container.querySelector<HTMLElement>(`[data-clip-id="${id}"]`);

describe("Timeline rows", () => {
  it("lays out lanes in the order the draft decided, audio last", () => {
    const { view } = setup([
      clipFixture({ clip_id: "TEXT", kind: "text", track_id: "T-TEXT" }),
      clipFixture({ clip_id: "BG" }),
      clipFixture({ clip_id: "SND", kind: "audio", track_id: "T-AUD" }),
    ], [
      trackFixture({ id: "T-AUD", type: "audio", group: "audio", lane: 2 }),
      trackFixture({ id: "T-TEXT", type: "text", z_ri: 14000, lane: 0 }),
      trackFixture({ id: "T-VIDEO", lane: 1 }),
    ]);
    expect(view.container.querySelectorAll("[data-testid='track-row']").length).toBe(3);
    const rows = [...view.container.querySelectorAll<HTMLElement>("[data-testid='track-row']")];
    expect(rows.map((row) => row.dataset.lane)).toEqual(["0", "1", "2"]);
    expect(rows.map((row) => row.dataset.group)).toEqual(["visual", "visual", "audio"]);
  });

  it("marks hidden and muted tracks without hiding them from the list", () => {
    const { view } = setup([clipFixture({ clip_id: "H", track_id: "T-HIDE" })],
                           [trackFixture({ id: "T-HIDE", visible: false })]);
    const row = view.container.querySelector<HTMLElement>("[data-testid='track-row']")!;
    expect(row.dataset.visible).toBe("false");
    expect(row.textContent).toContain("已隐藏");
  });

  it("shows a muted audio track as muted", () => {
    const { view } = setup([clipFixture({ clip_id: "S", kind: "audio", track_id: "T-A" })],
                           [trackFixture({ id: "T-A", type: "audio", group: "audio", muted: true })]);
    const row = view.container.querySelector<HTMLElement>("[data-testid='track-row']")!;
    expect(row.dataset.muted).toBe("true");
    expect(row.textContent).toContain("静音");
  });
});

describe("Timeline clip blocks", () => {
  it("places a block by its half-open span and the zoom", () => {
    const { view } = setup();
    const block = clip(view.container, "B")!;
    expect(block.style.left).toBe("400px");
    expect(block.style.width).toBe("400px");
    expect(block.dataset.kind).toBe("video");
  });

  it("selects and jumps when a clip is clicked", () => {
    const { view, onSelectClip, onSeek } = setup();
    fireEvent.click(clip(view.container, "B")!);
    expect(onSelectClip).toHaveBeenCalledWith("B");
    expect(onSeek).toHaveBeenCalledWith(2_000_000);
  });

  it("marks the selected clip", () => {
    const project = parseEditorProject(projectFixture());
    const { rerender, container } = render(<Timeline project={project} tUs={0} selectedClipId="C-2"
                                                     pxPerUs={SCALE} onSelectClip={() => {}} onSeek={() => {}} />);
    expect(clip(container, "C-2")!.dataset.selected).toBe("true");
    expect(clip(container, "C-1")!.dataset.selected).toBe("false");
    rerender(<Timeline project={project} tUs={0} selectedClipId="C-1" pxPerUs={SCALE}
                       onSelectClip={() => {}} onSeek={() => {}} />);
    expect(clip(container, "C-1")!.dataset.selected).toBe("true");
  });

  it("keeps a hidden segment visible in the list but dimmed", () => {
    const { view } = setup([clipFixture({ clip_id: "HIDDEN", visible: false })]);
    const block = clip(view.container, "HIDDEN")!;
    expect(block.dataset.visible).toBe("false");
    expect(block.textContent).toContain("已隐藏");
  });

  it("labels a clip whose media is missing", () => {
    const { view } = setup([clipFixture({ clip_id: "GONE", asset: {
      ...(clipFixture().asset as Record<string, unknown>), exists: false,
    }, warnings: ["media unavailable (missing)"] })]);
    expect(clip(view.container, "GONE")!.dataset.status).toBe("missing");
    expect(clip(view.container, "GONE")!.textContent).toContain("素材缺失");
  });

  it("carries the animation and effect tiers as text, never as blank space", () => {
    const { view } = setup([clipFixture({ clip_id: "FX", labels: [
      { bucket: "video_effects", kind: "video_effect", name: "美颜", render_class: "placeholder" },
    ], animation: { name: "渐隐", render_class: "approx", anim_type: "in", start_us: 0,
                    duration_us: 500_000 } })]);
    const block = clip(view.container, "FX")!;
    expect(block.textContent).toContain("美颜");
    expect(block.textContent).toContain("渐隐");
    expect(block.dataset.tiers).toContain("placeholder");
    expect(block.dataset.tiers).toContain("approx");
  });

  it("shows a transition as a marker over the cut", () => {
    const { view } = setup([clipFixture({ clip_id: "T1", target_start_us: 0, target_end_us: 2_000_000,
      target_duration_us: 2_000_000, transition: { name: "叠化", duration_us: 500_000,
      window: { start_us: 1_750_000, end_us: 2_250_000 }, render_class: "approx",
      cut_us: 2_000_000 } })]);
    const mark = view.container.querySelector<HTMLElement>("[data-testid='transition-marker']")!;
    expect(mark.textContent).toContain("叠化");
    expect(mark.getAttribute("data-left")).toBe("350");
  });
});

describe("Timeline ruler and playhead", () => {
  it("seeks to the second a tick names", () => {
    const { view, onSeek } = setup();
    fireEvent.click(view.container.querySelector<HTMLElement>("[data-tick-us='2000000']")!);
    expect(onSeek).toHaveBeenCalledWith(2_000_000);
  });

  it("seeks by position on the ruler itself", () => {
    const { view, onSeek } = setup();
    const ruler = view.container.querySelector<HTMLElement>("[data-testid='time-ruler']")!;
    fireEvent.mouseDown(ruler, { clientX: 500 });
    expect(onSeek).toHaveBeenCalledWith(2_500_000);
  });

  it("clamps a scrub past the end of the timeline", () => {
    const { view, onSeek } = setup();
    fireEvent.mouseDown(view.container.querySelector<HTMLElement>("[data-testid='time-ruler']")!,
                        { clientX: 500_000 });
    expect(onSeek).toHaveBeenCalledWith(4_000_000);
  });

  it("draws the playhead at the clock position", () => {
    const { view } = setup();
    expect(view.container.querySelector<HTMLElement>("[data-testid='playhead']")!.getAttribute("data-left"))
      .toBe("200");
  });

  it("numbers every second up to the duration", () => {
    const { view } = setup();
    const ticks = view.container.querySelectorAll("[data-tick-us]");
    expect([...ticks].map((tick) => tick.getAttribute("data-tick-us")))
      .toEqual(["0", "1000000", "2000000", "3000000", "4000000"]);
  });
});

describe("Timeline is read-only", () => {
  it("offers no drag, resize or delete affordance", () => {
    const { view } = setup();
    expect(view.container.querySelectorAll("[draggable='true']")).toHaveLength(0);
    expect(view.container.querySelectorAll("[data-resize]")).toHaveLength(0);
    expect(view.container.querySelectorAll("input, textarea, select")).toHaveLength(0);
    expect(view.container.textContent).toContain("只读");
  });
});
