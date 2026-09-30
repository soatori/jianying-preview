// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { parseEditorProject, type EditorProject } from "../core/project.ts";
import { resolveScene, type Scene } from "../core/scene.ts";
import { clipFixture, projectFixture, trackFixture } from "../testing/project-fixture.ts";
import { PreviewStage } from "./PreviewStage.tsx";

afterEach(cleanup);

function setup(clips: Record<string, unknown>[], tracks?: Record<string, unknown>[], tUs = 0) {
  const project: EditorProject = parseEditorProject(
    projectFixture({ clips, tracks: tracks ?? [trackFixture()] }),
  );
  const scene: Scene = resolveScene(tUs, project);
  const view = render(<PreviewStage project={project} scene={scene} status="paused" />);
  const layer = (clipId: string): HTMLElement | null =>
    view.container.querySelector(`[data-testid="stage-layer"][data-clip-id="${clipId}"]`);
  return { view, project, scene, layer };
}

function textMaterial(overrides: Record<string, unknown> = {}) {
  return {
    text: "标题",
    font: { family: "jyfont-abc", src: "/font?f=abc", source: "rid_dir" },
    box: { em_px: 67.5, line_count: 1, alignment: "center" },
    runs: [{ start: 0, end: 2, text: "标题", em_px: 67.5, bold: false, italic: false,
             underline: false, fill: { css: "#ffffff", alpha: 1 }, strokes: [], shadows: [],
             inner_shadows: [], use_letter_color: false, flower: null, font: null }],
    deco: { background: null, has_shadow: false, global_alpha: 1, alignment: "center",
            vertical: false, letter_spacing_px: 0, line_spacing_raw: 0.02 },
    size: { em_px: 67.5, font_size: 10 },
    ...overrides,
  };
}

describe("PreviewStage layers", () => {
  it("renders exactly the clips the scene says are on screen, in paint order", () => {
    const { scene } = setup([
      clipFixture({ clip_id: "OFF", target_start_us: 3_000_000, target_end_us: 4_000_000 }),
      clipFixture({ clip_id: "TOP", z_index: 30 }),
      clipFixture({ clip_id: "BOTTOM", z_index: 1 }),
    ]);
    const nodes = screen.getAllByTestId("stage-layer");
    expect(nodes.map((node) => node.dataset.clipId)).toEqual(["BOTTOM", "TOP"]);
    expect(nodes.map((node) => Number(node.style.zIndex))).toEqual([1, 30]);
    expect(scene.clips).toHaveLength(2);
    expect(screen.queryByTestId("layer-OFF")).toBeNull();
  });

  it("sizes the stage from the canvas", () => {
    setup([clipFixture()]);
    const root = screen.getByTestId("stage");
    expect(root.style.width).toBe("1080px");
    expect(root.style.height).toBe("1920px");
    expect(root.style.background).toContain("rgb(0, 0, 0)");
  });

  it("reconciles by clip id so a seek never rebuilds a decoding element", () => {
    const project = parseEditorProject(projectFixture({ clips: [clipFixture({ clip_id: "KEEP" })] }));
    const { rerender, container } = render(
      <PreviewStage project={project} scene={resolveScene(0, project)} status="paused" />,
    );
    const before = container.querySelector("video");
    expect(before).not.toBeNull();
    rerender(<PreviewStage project={project} scene={resolveScene(500_000, project)} status="paused" />);
    expect(container.querySelector("video")).toBe(before);
  });
});

describe("PreviewStage media", () => {
  it("points the video at the served url and seeks it to the mapped source time", () => {
    const { scene, layer } = setup([clipFixture({ clip_id: "V", source_start_us: 5_000_000 })],
                                   undefined, 500_000);
    const video = layer("V")!.querySelector("video")!;
    expect(video.getAttribute("src")).toBe("/media?f=abc");
    expect(video.currentTime).toBeCloseTo((5_000_000 + 500_000) / 1e6, 6);
    expect(layer("V")!.dataset.mediaState).toBe("ok");
    expect(scene.clips[0]?.sourceTimeUs).toBe(5_500_000);
  });

  it("applies speed but never invents a reverse decode", () => {
    const { layer } = setup([clipFixture({ clip_id: "FAST", speed: 2, target_start_us: 0,
                                           target_end_us: 1_000_000 })]);
    const video = layer("FAST")!.querySelector("video")!;
    expect(video.playbackRate).toBe(2);
    expect(layer("FAST")!.dataset.reversed).toBe("false");
  });

  it("walks a reversed clip's media backwards from the mapped source time", () => {
    const { layer } = setup([clipFixture({ clip_id: "REV", reverse: true, source_start_us: 1_000_000,
                                           source_duration_us: 3_000_000, target_start_us: 0,
                                           target_end_us: 2_000_000, target_duration_us: 2_000_000 })],
                            undefined, 0);
    const node = layer("REV")!;
    expect(node.dataset.reversed).toBe("true");
    expect(node.querySelector("video")!.currentTime).toBeCloseTo(4, 6);
  });

  it("mutes a clip whose track is muted", () => {
    const { layer } = setup([clipFixture({ clip_id: "M", muted: true })],
                            [trackFixture({ id: "T-VIDEO", muted: true })]);
    expect(layer("M")!.querySelector("video")!.muted).toBe(true);
  });

  it("shows a labelled placeholder instead of a broken element when media is missing", () => {
    const { scene, layer } = setup([clipFixture({ clip_id: "GONE", asset: {
      ...(clipFixture().asset as Record<string, unknown>), exists: false, path_served: null,
      placeholder_reason: "missing",
    } })]);
    const node = layer("GONE")!;
    expect(node.querySelector("video")).toBeNull();
    expect(node.dataset.mediaState).toBe("missing");
    expect(node.textContent).toContain("a.mp4");
    expect(node.textContent).toContain("素材缺失");
    expect(scene.clips).toHaveLength(1);
  });

  it("keeps an image clip as an image", () => {
    const { layer } = setup([clipFixture({ clip_id: "IMG", kind: "photo", asset: {
      ...(clipFixture().asset as Record<string, unknown>), kind: "image",
    } })]);
    expect(layer("IMG")!.querySelector("img")?.getAttribute("src")).toBe("/media?f=abc");
  });

  it("takes its time from the clock and never the other way round", () => {
    const project = parseEditorProject(projectFixture({ clips: [clipFixture({ clip_id: "V" })] }));
    const { rerender, container } = render(
      <PreviewStage project={project} scene={resolveScene(0, project)} status="playing" />,
    );
    const video = container.querySelector("video")!;
    video.currentTime = 7.25;
    video.dispatchEvent(new Event("timeupdate"));
    expect(resolveScene(0, project).clips[0]?.sourceTimeUs).toBe(0);
    rerender(<PreviewStage project={project} scene={resolveScene(500_000, project)} status="playing" />);
    expect(video.currentTime).toBeCloseTo(0.5, 6);
  });

  it("places audio outside the picture stack", () => {
    const { layer } = setup([
      clipFixture({ clip_id: "PIC" }),
      clipFixture({ clip_id: "SND", kind: "audio", track_id: "T-A", asset: {
        ...(clipFixture().asset as Record<string, unknown>), kind: "audio",
        path_served: "/media?f=bgm",
      } }),
    ], [trackFixture(), trackFixture({ id: "T-A", type: "audio", group: "audio", lane: 1 })]);
    expect(screen.getAllByTestId("stage-layer").map((node) => node.dataset.clipId)).toEqual(["PIC"]);
    const audio = screen.getByTestId("audio-layer");
    expect(audio.dataset.clipId).toBe("SND");
    expect(audio.querySelector("audio")?.getAttribute("src")).toBe("/media?f=bgm");
    expect(layer("SND")).toBeNull();
  });
});

describe("PreviewStage text", () => {
  it("draws the run with the resolved size, colour and font", () => {
    const { layer } = setup([clipFixture({ clip_id: "TXT", kind: "text", text: textMaterial() })]);
    const node = layer("TXT")!;
    const span = node.querySelector<HTMLElement>("[data-run='0']")!;
    expect(span.textContent).toBe("标题");
    expect(span.style.fontSize).toBe("67.5px");
    expect(span.style.color).toBe("rgb(255, 255, 255)");
    expect(node.style.fontFamily).toContain("jyfont-abc");
    expect(node.dataset.textSource).toBe("rid_dir");
  });

  it("carries stroke and shadow specs the browser CSS cannot express faithfully", () => {
    const { layer } = setup([clipFixture({ clip_id: "TXT", kind: "text", text: textMaterial({
      runs: [{ start: 0, end: 2, text: "标题", em_px: 67.5, fill: { css: "#ffffff" },
               strokes: [{ width_em: 0.05, color: "#ff0000", alpha: 1 }],
               shadows: [{ distance_em: 0.02, angle_deg: 45, color: "#000000", alpha: 1 }],
               bold: true, italic: true, underline: true, inner_shadows: [],
               use_letter_color: false, flower: null, font: null }],
    }) })]);
    const span = layer("TXT")!.querySelector<HTMLElement>("[data-run='0']")! as HTMLElement;
    expect(span.dataset.strokes).toContain("3.375px");
    expect(span.dataset.strokes).toContain("#ff0000");
    expect(span.dataset.shadows).toContain("#000000");
    expect(span.style.fontWeight).toBe("700");
    expect(span.style.fontStyle).toBe("italic");
    expect(span.style.textDecoration).toContain("underline");
  });

  it("marks a 花字 run as a placeholder instead of pretending it rendered", () => {
    const { layer } = setup([clipFixture({ clip_id: "TXT", kind: "text", text: textMaterial({
      runs: [{ start: 0, end: 2, text: "标题", em_px: 67.5, fill: { css: "#ffffff" }, strokes: [],
               shadows: [], inner_shadows: [], bold: false, italic: false, underline: false,
               use_letter_color: false, font: null,
               flower: { resource_id: "FLOWER-1", name: "流光", render_class: "placeholder" } }],
    }) })]);
    const span = layer("TXT")!.querySelector<HTMLElement>("[data-run='0']")!;
    expect(span.getAttribute("data-flower")).toBe("FLOWER-1");
    const badge = layer("TXT")!.querySelector<HTMLElement>("[data-flower-badge]")!;
    expect(badge.textContent).toContain("流光");
    expect(badge.textContent).toContain("未渲染");
  });

  it("says so when the font fell back to the system stack", () => {
    const { layer } = setup([clipFixture({ clip_id: "TXT", kind: "text", text: textMaterial({
      font: { family: '"Microsoft YaHei", sans-serif', src: null, source: "system_stack" } }) })]);
    expect(layer("TXT")!.dataset.textSource).toBe("system_stack");
  });

  it("positions the box from the resolved rect", () => {
    const { layer } = setup([clipFixture({ clip_id: "TXT", kind: "text", text: textMaterial(),
      rect: { ...(clipFixture().rect as Record<string, unknown>), cx_px: 540, cy_px: 1728,
              w_px: 400, h_px: 80, alpha: 0.5 } })]);
    const node = layer("TXT")!;
    expect(node.style.left).toBe("340px");
    expect(node.style.top).toBe("1688px");
    expect(node.style.opacity).toBe("0.5");
  });
});

describe("PreviewStage annotations", () => {
  it("badges an effect layer with its Chinese name and tier", () => {
    const { layer } = setup([clipFixture({ clip_id: "FX", kind: "effect", labels: [
      { bucket: "video_effects", kind: "video_effect", name: "模糊", render_class: "placeholder" },
    ] })]);
    expect(layer("FX")!.textContent).toContain("模糊");
    expect(layer("FX")!.dataset.renderClass).toBe("placeholder");
  });

  it("keeps an approximation distinguishable from an exact render", () => {
    const { layer } = setup([clipFixture({ clip_id: "ANIM", animation: { name: "渐隐",
      anim_type: "in", render_class: "approx", start_us: 0, duration_us: 500_000, inside: true,
      approx: { impl: "fade", from: 1, to: 0 }, at_t: null } })]);
    expect(layer("ANIM")!.dataset.renderClass).toBe("approx");
    expect(layer("ANIM")!.textContent).toContain("近似");
  });

  it("renders nested compound-clip layers with their own ids", () => {
    const { layer } = setup([clipFixture({ clip_id: "NEST", kind: "subdraft", nest: {
      depth: 1, canvas: { width: 1080, height: 1920 }, scale_to_parent: 1, duration_us: 4_000_000,
      warnings: [], layers: [{ layer_id: "INNER-1", kind: "video", time: {
        target_start_us: 0, target_duration_us: 2_000_000, end_us: 2_000_000, source_start_us: 0,
        source_time_us: 0, source_duration_us: 2_000_000, speed: 1, reverse: false, local_us: 0,
        progress: 0 }, media: null, rect: null, css: null, text: null }],
    } })]);
    expect(layer("INNER-1")).not.toBeNull();
    expect(layer("NEST")!.dataset.nestDepth).toBe("1");
  });

  it("reports the canvas fill the draft asked for", () => {
    const { layer } = setup([clipFixture({ clip_id: "BG", canvas_fill: { type: "canvas_blur", blur: 0.6 } })]);
    expect(layer("BG")!.dataset.canvasFill).toBe("canvas_blur");
  });
});
