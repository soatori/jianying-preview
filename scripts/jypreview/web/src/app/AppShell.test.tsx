// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { openEditorSession, TimelineAmbiguousError } from "../core/project.ts";
import { clipFixture, projectFixture, trackFixture } from "../testing/project-fixture.ts";
import { AppShell } from "../app/AppShell.tsx";

afterEach(cleanup);

function fakeClock() {
  let ms = 0;
  let task: (() => void) | null = null;
  return {
    now: () => ms,
    schedule: (fn: () => void) => {
      task = fn;
      return () => {
        task = null;
      };
    },
    tick: (delta: number) => {
      ms += delta;
      const run = task;
      task = null;
      run?.();
    },
  };
}

async function readySession(overrides: Record<string, unknown> = {}) {
  const clock = fakeClock();
  const session = await openEditorSession({
    draft: "cd30ce559c3c5b0f",
    load: async () => ({ ok: true, code: "ok", reason: "", data: projectFixture(overrides) }),
    now: clock.now,
    schedule: clock.schedule,
  });
  return { session, clock };
}

type ShellProps = React.ComponentProps<typeof AppShell>;

function shell(session: ShellProps["session"], extra: Partial<ShellProps> = {}) {
  const props: ShellProps = {
    session,
    state: extra.state ?? (session ? "ready" : "idle"),
    error: extra.error ?? null,
    drafts: extra.drafts ?? [{ id: "cd30ce559c3c5b0f", name: "YASHIDA 9月24日", layout: "hybrid",
                               timelines: 4 }],
    draft: extra.draft ?? "cd30ce559c3c5b0f",
    onOpen: extra.onOpen ?? vi.fn(),
    onPickTimeline: extra.onPickTimeline ?? vi.fn(),
    onRetry: extra.onRetry ?? vi.fn(),
    chrome: extra.chrome ?? true,
  };
  return { ...render(<AppShell {...props} />), props };
}

describe("AppShell states", () => {
  it("prompts for a draft when nothing is open", () => {
    shell(null);
    expect(screen.getByTestId("app-empty").textContent).toContain("打开草稿");
    expect(screen.queryByTestId("stage")).toBeNull();
  });

  it("shows a loading state without a half-built timeline", () => {
    const { container } = shell(null, { state: "loading", session: null });
    expect(container.textContent).toContain("读取中");
    expect(screen.queryByTestId("timeline-panel")).toBeNull();
  });

  it("forces an explicit choice when the active timeline is not provable", () => {
    const error = new TimelineAmbiguousError("无法确定当前时间线", ["A", "B"]);
    const { container } = shell(null, { state: "error", session: null, error: {
      code: error.code, reason: error.message, available: error.available } });
    expect(container.textContent).toContain("需要选择时间线");
    expect(screen.getAllByTestId("timeline-option")).toHaveLength(2);
    expect(screen.queryByTestId("stage")).toBeNull();
  });

  it("reports a decrypt failure with a retry that changes nothing on disk", () => {
    const { props } = shell(null, { state: "error", session: null, error: {
      code: "decrypt_failed", reason: "videoeditor.dll refused the file", hint: "close JianYing" } });
    expect(screen.getByTestId("app-error").textContent).toContain("解密失败");
    expect(screen.getByTestId("app-error").textContent).toContain("close JianYing");
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    expect(props.onRetry).toHaveBeenCalled();
  });

  it("renders the full editor once a session is open", async () => {
    const { session } = await readySession();
    const { container } = shell(session);
    expect(screen.getByTestId("stage")).toBeTruthy();
    expect(screen.getByTestId("timeline-panel")).toBeTruthy();
    expect(screen.getByTestId("inspector")).toBeTruthy();
    expect(screen.getByTestId("warnings")).toBeTruthy();
    expect(container.textContent).toContain("YASHIDA 9月24日");
    expect(container.textContent).toContain("成片");
    expect(container.textContent).toContain("hybrid");
    expect(container.textContent).toContain("只读");
    expect(container.textContent).toContain("9eac9dd0");
    session.destroy();
  });

  it("selecting a clip on the timeline fills the inspector", async () => {
    const { session } = await readySession();
    const { container } = shell(session);
    const block = container.querySelector<HTMLElement>("[data-testid='clip-block'][data-clip-id='C-2']")!;
    fireEvent.click(block);
    expect(screen.getByTestId("inspector").textContent).toContain("C-2");
    expect(block.dataset.selected).toBe("true");
    session.destroy();
  });

  it("plays from the shell controls and the stage follows the clock", async () => {
    const { session, clock } = await readySession({
      duration_us: 4_000_000,
      clips: [
        clipFixture({ clip_id: "FIRST", target_start_us: 0, target_end_us: 2_000_000,
                      target_duration_us: 2_000_000 }),
        clipFixture({ clip_id: "SECOND", target_start_us: 2_000_000, target_end_us: 4_000_000,
                      target_duration_us: 2_000_000, z_index: 1 }),
      ],
      tracks: [trackFixture()],
    });
    shell(session);
    expect(screen.getByTestId("stage").querySelector<HTMLElement>("[data-clip-id='FIRST']")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "播放" }));
    await waitFor(() => expect(session.status()).toBe("playing"));
    // One tick never integrates more than the clock's stall clamp, so the harness advances
    // the way a real animation loop would.
    act(() => clock.tick(1000));
    act(() => clock.tick(1000));
    await waitFor(() => expect(screen.getByTestId("stage").querySelector<HTMLElement>("[data-clip-id='SECOND']"))
      .toBeTruthy());
    expect(screen.getByTestId("stage").querySelector<HTMLElement>("[data-clip-id='FIRST']")).toBeNull();
    session.destroy();
  });

  it("banners a changed draft instead of reloading under the playhead", async () => {
    const { session } = await readySession();
    session.markStale("draft-content-changed");
    const { container } = shell(session);
    await waitFor(() => expect(container.textContent).toContain("草稿已在剪映中更改"));
    fireEvent.click(screen.getByRole("button", { name: "重新读取" }));
    expect(container.textContent).toContain("重新读取");
    session.destroy();
  });

  it("offers no command that could touch the draft", async () => {
    const { session } = await readySession();
    const { container } = shell(session);
    const names = [...container.querySelectorAll("button")].map((button) => button.getAttribute("aria-label")
      ?? button.textContent ?? "");
    const forbidden = ["保存", "导出", "剪切", "删除", "分割", "写入", "撤销", "重做", "应用"];
    for (const name of names) {
      expect(forbidden.some((word) => name.includes(word))).toBe(false);
    }
    expect(container.querySelectorAll("video[controls], audio[controls]")).toHaveLength(0);
    session.destroy();
  });

  it("drops every panel when the capture channel asks for the stage alone", async () => {
    const { session } = await readySession();
    const { container } = shell(session, { chrome: false });
    expect(screen.getByTestId("stage")).toBeTruthy();
    expect(screen.queryByTestId("timeline-panel")).toBeNull();
    expect(screen.queryByTestId("playback-controls")).toBeNull();
    expect(container.textContent).not.toContain("只读时间线");
    session.destroy();
  });

  it("keeps the media elements uncontrolled so the clock stays authoritative", async () => {
    const { session } = await readySession();
    const { container } = shell(session);
    const video = container.querySelector("video")!;
    expect(video.controls).toBe(false);
    expect(video.getAttribute("src")).toBe("/media?f=abc");
    session.destroy();
  });
});

describe("AppShell project handoff", () => {
  it("exposes the loaded document to an acceptance harness, read-only", async () => {
    const { session } = await readySession();
    shell(session);
    const snapshot = (window as unknown as { __editorSnapshot?: () => Record<string, unknown> })
      .__editorSnapshot!();
    expect(snapshot.schema).toBe("jypreview/editor-project@1");
    expect(Number(snapshot.clips)).toBeGreaterThan(0);
    expect(Number(snapshot.tracks)).toBeGreaterThan(0);
    expect(snapshot.timeline).toMatchObject({ id: "TL-ACTIVE" });
    expect(snapshot.errors).toEqual([]);
    const scene = (window as unknown as { __editorScene?: () => Record<string, unknown> })
      .__editorScene!();
    expect((scene?.clips as unknown[]).length).toBe(1);
    session.destroy();
  });
});
