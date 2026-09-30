// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { parseEditorProject, type EditorProject } from "../core/project.ts";
import { resolveScene } from "../core/scene.ts";
import { clipFixture, projectFixture, trackFixture } from "../testing/project-fixture.ts";
import { InspectorPanel } from "./InspectorPanel.tsx";
import { WarningsPanel } from "./WarningsPanel.tsx";
import { PlaybackControls } from "./PlaybackControls.tsx";
import { DraftPicker, TimelinePicker } from "./Pickers.tsx";

afterEach(cleanup);

function fixtureClip(overrides: Record<string, unknown> = {}) {
  return clipFixture({ clip_id: "C-1", ...overrides });
}

function project(clips: Record<string, unknown>[]): EditorProject {
  return parseEditorProject(projectFixture({ clips, tracks: [trackFixture()] }));
}

describe("InspectorPanel", () => {
  it("prompts before a clip is selected", () => {
    render(<InspectorPanel project={project([fixtureClip()])} clip={null} />);
    expect(screen.getByTestId("inspector").textContent).toContain("选择一个片段");
  });

  it("reports identity, lane, paint order and half-open spans", () => {
    const target = project([fixtureClip({ target_start_us: 2_000_000, target_end_us: 4_000_000,
                                          target_duration_us: 2_000_000 })]);
    const clip = target.clips[0]!;
    const { container } = render(<InspectorPanel project={target} clip={clip} />);
    const text = container.textContent!;
    expect(text).toContain("C-1");
    expect(text).toContain("T-VIDEO");
    expect(text).toContain("00:02.000");
    expect(text).toContain("00:04.000");
    expect(text).toContain("2000000");
    expect(container.querySelector<HTMLElement>("[data-field='z_index']")!.textContent).toBe("0");
    expect(container.querySelectorAll("input, textarea, select")).toHaveLength(0);
  });

  it("shows source mapping including speed and reverse", () => {
    const target = project([fixtureClip({ speed: 0.5, reverse: true, source_start_us: 5_000_000,
                                          source_duration_us: 1_000_000, source_end_us: 6_000_000 })]);
    const { container } = render(<InspectorPanel project={target} clip={target.clips[0]!} />);
    expect(container.querySelector<HTMLElement>("[data-field='speed']")!.textContent).toBe("0.5");
    expect(container.querySelector<HTMLElement>("[data-field='reverse']")!.textContent).toContain("倒放");
    expect(container.querySelector<HTMLElement>("[data-field='source']")!.textContent).toContain("5000000");
  });

  it("names the media and how it was found", () => {
    const target = project([fixtureClip()]);
    const { container } = render(<InspectorPanel project={target} clip={target.clips[0]!} />);
    expect(container.textContent).toContain("a.mp4");
    expect(container.textContent).toContain("/media?f=abc");
    expect(container.querySelector<HTMLElement>("[data-field='asset-state']")!.textContent).toContain("可用");
    expect(container.querySelector<HTMLElement>("[data-field='media-how']")!.textContent).toContain("direct");
  });

  it("flags missing media as a placeholder", () => {
    const target = project([fixtureClip({ asset: {
      ...(clipFixture().asset as Record<string, unknown>), exists: false, path_served: null,
      placeholder_reason: "missing",
    }, warnings: ["media unavailable (missing)"] })]);
    const { container } = render(<InspectorPanel project={target} clip={target.clips[0]!} />);
    expect(container.querySelector<HTMLElement>("[data-field='asset-state']")!.textContent).toContain("素材缺失");
  });

  it("lists labels with their fidelity tier in Chinese", () => {
    const target = project([fixtureClip({ labels: [
      { bucket: "transitions", kind: "transition", name: "叠化", render_class: "exact" },
      { bucket: "video_effects", kind: "figure", name: "美颜", render_class: "placeholder" },
      { bucket: "material_animations", kind: "in", name: "渐隐", render_class: "approx" },
    ] })]);
    const { container } = render(<InspectorPanel project={target} clip={target.clips[0]!} />);
    const rows = [...container.querySelectorAll<HTMLElement>("[data-testid='label-row']")];
    expect(rows.map((row) => row.dataset.renderClass)).toEqual(["exact", "placeholder", "approx"]);
    expect(rows.map((row) => row.dataset.tierLabel)).toEqual(["精确", "未渲染", "近似"]);
  });

  it("shows text styling for a caption clip", () => {
    const target = project([fixtureClip({ kind: "text", text: {
      text: "字幕内容",
      font: { family: "jyfont-abc", title: "思源黑体", source: "rid_dir", resource_id: "RID" },
      box: { em_px: 67.5, line_count: 2, alignment: "center" },
      runs: [{ start: 0, end: 4, text: "字幕内容", em_px: 67.5, fill: { css: "#ffffff" },
               strokes: [{ width_em: 0.05, color: "#ff0000" }], shadows: [] }],
      deco: { background: null, has_shadow: false, global_alpha: 1 },
    } })]);
    const { container } = render(<InspectorPanel project={target} clip={target.clips[0]!} />);
    expect(container.querySelector<HTMLElement>("[data-field='text-content']")!.textContent).toContain("字幕内容");
    expect(container.textContent).toContain("思源黑体");
    expect(container.textContent).toContain("67.5");
    expect(container.textContent).toContain("描边");
  });

  it("exposes the compound clip's nesting limits", () => {
    const target = project([fixtureClip({ kind: "subdraft", nest: { depth: 2, embeddable: false,
      reason: "inner media unresolved; showing JianYing's stored cover", layers: [] } })]);
    const { container } = render(<InspectorPanel project={target} clip={target.clips[0]!} />);
    expect(container.querySelector<HTMLElement>("[data-field='nest-depth']")!.textContent).toBe("2");
    expect(container.textContent).toContain("封面");
  });

  it("carries the clip warnings", () => {
    const target = project([fixtureClip({ warnings: ["animation not rendered: 抖动"] })]);
    const { container } = render(<InspectorPanel project={target} clip={target.clips[0]!} />);
    expect(container.querySelector<HTMLElement>("[data-field='clip-warnings']")!.textContent)
      .toContain("animation not rendered");
  });
});

describe("WarningsPanel", () => {
  it("says nothing is wrong when the document has no warnings", () => {
    render(<WarningsPanel project={project([fixtureClip()])} scene={resolveScene(0, project([fixtureClip()]))} />);
    expect(screen.getByTestId("warnings").textContent).toContain("无告警");
  });

  it("splits document warnings from the ones on screen", () => {
    const target = parseEditorProject(projectFixture({
      warnings: ["hsl: 26 item(s) not previewed", "fps absent; defaulted to 30.0"],
      clips: [fixtureClip({ target_start_us: 0, target_end_us: 2_000_000,
                            warnings: ["media unavailable (missing): a.mp4"] })],
    }));
    const { container } = render(<WarningsPanel project={target} scene={resolveScene(1_000_000, target)} />);
    expect(container.querySelector<HTMLElement>("[data-testid='project-warnings']")!.textContent)
      .toContain("hsl: 26 item(s) not previewed");
    expect(container.querySelector<HTMLElement>("[data-testid='scene-warnings']")!.textContent)
      .toContain("media unavailable");
    expect(container.textContent).toContain("26 项未预览");
  });

  it("counts the tiers it degraded", () => {
    const target = project([fixtureClip({ labels: [
      { bucket: "video_effects", kind: "figure", name: "美颜", render_class: "placeholder" },
      { bucket: "material_animations", kind: "in", name: "渐隐", render_class: "approx" },
    ] })]);
    const { container } = render(<WarningsPanel project={target} scene={resolveScene(0, target)} />);
    expect(container.querySelector<HTMLElement>("[data-testid='tier-counts']")!.textContent)
      .toContain("未渲染 1");
    expect(container.querySelector<HTMLElement>("[data-testid='tier-counts']")!.textContent).toContain("近似 1");
  });
});

describe("PlaybackControls", () => {
  const base = {
    status: "paused" as const, tUs: 1_000_000, durationUs: 4_000_000, fps: 30, rate: 1,
    onPlay: vi.fn(), onPause: vi.fn(), onSeek: vi.fn(), onRate: vi.fn(),
  };

  it("uses icon-only buttons with accessible names", () => {
    const { container } = render(<PlaybackControls {...base} />);
    const play = screen.getByRole("button", { name: "播放" });
    expect(play.textContent).toBe("");
    expect(play.getAttribute("aria-label")).toBe("播放");
    expect(container.querySelectorAll("button")).toHaveLength(8);
  });

  it("switches to pause while playing", () => {
    render(<PlaybackControls {...base} status="playing" />);
    expect(screen.getByRole("button", { name: "暂停" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "播放" })).toBeNull();
  });

  it("steps one frame at a time and jumps to the ends", () => {
    const handlers = { ...base, onSeek: vi.fn() };
    render(<PlaybackControls {...handlers} />);
    fireEvent.click(screen.getByRole("button", { name: "上一帧" }));
    expect(handlers.onSeek).toHaveBeenLastCalledWith(1_000_000 - 33_333);
    fireEvent.click(screen.getByRole("button", { name: "下一帧" }));
    expect(handlers.onSeek).toHaveBeenLastCalledWith(1_000_000 + 33_333);
    fireEvent.click(screen.getByRole("button", { name: "跳到结尾" }));
    expect(handlers.onSeek).toHaveBeenLastCalledWith(4_000_000);
    fireEvent.click(screen.getByRole("button", { name: "跳到开头" }));
    expect(handlers.onSeek).toHaveBeenLastCalledWith(0);
  });

  it("reads out the timecode and offers only the speeds it can honour", () => {
    const { rerender } = render(<PlaybackControls {...base} />);
    expect(screen.getByTestId("time-readout").textContent).toBe("00:01.000 / 00:04.000");
    fireEvent.click(screen.getByRole("button", { name: "2 倍速" }));
    expect(base.onRate).toHaveBeenCalledWith(2);
    rerender(<PlaybackControls {...base} rate={2} />);
    expect(screen.getByRole("button", { name: "2 倍速" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("button", { name: "1 倍速" }).getAttribute("aria-pressed")).toBe("false");
  });

  it("shows the clock status without pretending to edit", () => {
    const { container } = render(<PlaybackControls {...base} status="ended" />);
    expect(screen.getByTestId("playback-status").textContent).toContain("已结束");
    expect(container.textContent).toContain("只读");
  });
});

describe("Pickers", () => {
  it("asks for a draft when nothing is open", () => {
    const onOpen = vi.fn();
    const { container } = render(<DraftPicker drafts={[
      { id: "did-1", name: "YASHIDA 9月24日", layout: "hybrid", timelines: 4 },
      { id: "did-2", name: "6月7日 (全顺)", layout: "legacy-single", timelines: 1 },
    ]} value="" onOpen={onOpen} loading={false} />);
    expect(container.textContent).toContain("打开草稿");
    fireEvent.click(screen.getByRole("button", { name: /YASHIDA/ }));
    expect(onOpen).toHaveBeenCalledWith("did-1");
    expect(container.querySelectorAll("[data-testid='draft-row']")).toHaveLength(2);
  });

  it("filters the list by name", () => {
    const { container } = render(<DraftPicker drafts={[
      { id: "did-1", name: "YASHIDA 9月24日", layout: "hybrid", timelines: 4 },
      { id: "did-2", name: "6月7日 (全顺)", layout: "legacy-single", timelines: 1 },
    ]} value="" onOpen={() => {}} loading={false} />);
    fireEvent.change(container.querySelector("input[type='search']")!, { target: { value: "全顺" } });
    expect(container.querySelectorAll("[data-testid='draft-row']")).toHaveLength(1);
  });

  it("refuses to guess an ambiguous timeline", () => {
    const onPick = vi.fn();
    const { container } = render(<TimelinePicker timelines={[
      { id: "A", name: "时间线A", active: false, duration_us: 4_000_000 },
      { id: "B", name: "时间线B", active: false, duration_us: 2_000_000 },
    ]} required={true} onPick={onPick} />);
    expect(container.textContent).toContain("需要选择时间线");
    fireEvent.click(screen.getByRole("button", { name: /时间线B/ }));
    expect(onPick).toHaveBeenCalledWith("B");
  });

  it("marks which timeline is active and which are deleted", () => {
    const { container } = render(<TimelinePicker timelines={[
      { id: "A", name: "成片", active: true, duration_us: 4_000_000 },
      { id: "B", name: "废弃", active: false, deleted: true, duration_us: 1_000_000 },
    ]} required={false} onPick={() => {}} />);
    expect(container.querySelector<HTMLElement>("[data-timeline-id='A']")!.dataset.active).toBe("true");
    expect(container.querySelector<HTMLElement>("[data-timeline-id='B']")!.textContent).toContain("已删除");
  });

  it("shows a loading state without a spinner that blocks the picker", () => {
    render(<DraftPicker drafts={[]} value="did-1" onOpen={() => {}} loading={true} />);
    expect(screen.getByTestId("draft-loading").textContent).toContain("读取中");
  });
});
