import { useCallback, useEffect, useRef, useState } from "react";

import type { ClockSnapshot, PlaybackStatus } from "../core/playback-clock.ts";
import type { Clip, EditorProject, EditorSession } from "../core/project.ts";
import type { Scene } from "../core/scene.ts";
import { PreviewStage } from "../components/PreviewStage.tsx";
import { Timeline } from "../components/Timeline.tsx";
import { InspectorPanel } from "../components/InspectorPanel.tsx";
import { WarningsPanel } from "../components/WarningsPanel.tsx";
import { PlaybackControls } from "../components/PlaybackControls.tsx";
import { DraftPicker, TimelinePicker, type DraftOption } from "../components/Pickers.tsx";

export interface ShellError {
  code: string;
  reason: string;
  available?: string[];
  hint?: string;
}

export interface AppShellProps {
  session: EditorSession | null;
  state: "idle" | "loading" | "ready" | "error";
  error?: ShellError | null;
  drafts: DraftOption[];
  draft: string;
  onOpen: (draft: string, timeline?: string) => void;
  onPickTimeline: (timeline: string) => void;
  onRetry: () => void;
  /** false renders only the stage, which is what the PNG verification channel captures. */
  chrome?: boolean;
}

const ERROR_TITLE: Record<string, string> = {
  timeline_ambiguous: "需要选择时间线",
  decrypt_failed: "解密失败",
  draft_not_found: "找不到草稿",
  draft_without_content: "这个草稿没有可读取的内容文件",
  timeline_not_found: "时间线不存在",
  io_error: "读取文件失败",
};

export function AppShell(props: AppShellProps) {
  const { session, state, error, drafts, draft, onOpen, onPickTimeline, onRetry } = props;
  const chrome = props.chrome ?? true;
  const [scene, setScene] = useState<Scene | null>(session ? session.sceneAt() : null);
  const [status, setStatus] = useState<PlaybackStatus>(session?.status() ?? "stopped");
  const [selectedClipId, setSelectedClipId] = useState<string | null>(null);
  const [stale, setStale] = useState(session?.isStale() ?? false);

  useEffect(() => {
    if (!session) {
      setScene(null);
      setStatus("stopped");
      return;
    }
    setSelectedClipId(null);
    setScene(session.sceneAt());
    setStatus(session.status());
    setStale(session.isStale());
    const unsubscribe = session.subscribeScene((next: Scene, snapshot: ClockSnapshot) => {
      setScene(next);
      setStatus(snapshot.status);
    });
    const unsubscribeStale = session.subscribeStale(() => setStale(true));
    return () => {
      unsubscribe();
      unsubscribeStale();
    };
  }, [session]);

  const project: EditorProject | null = session && state === "ready" ? session.project() : null;
  const clip: Clip | null = project && selectedClipId
    ? project.clips.find((item) => item.clip_id === selectedClipId) ?? null
    : null;

  const refresh = useCallback(() => {
    if (!session) return;
    setScene(session.sceneAt());
    setStatus(session.status());
  }, [session]);

  useEditorHooks(session, project);

  if (state === "error" && error) {
    return (
      <div className="jy-app jy-app-error">
        <Header project={null} draftName={draft} />
        <div data-testid="app-error" className="jy-error">
          <h2>{ERROR_TITLE[error.code] ?? "无法打开草稿"}</h2>
          <p>{error.reason}</p>
          {error.hint && <p className="jy-error-hint">{error.hint}</p>}
          {error.code === "timeline_ambiguous" && error.available?.length && (
            <TimelinePicker required timelines={error.available.map((id) => ({ id }))}
                            onPick={onPickTimeline} />
          )}
          <button type="button" onClick={onRetry}>重试</button>
        </div>
      </div>
    );
  }

  if (!project || !session || !scene) {
    return (
      <div className="jy-app jy-app-empty">
        <Header project={null} draftName={draft} />
        <div data-testid="app-empty">
          {state === "loading" ? <p>读取中…</p> : <p>打开草稿以预览时间线</p>}
        </div>
        <DraftPicker drafts={drafts} value={draft} loading={state === "loading"} onOpen={onOpen} />
      </div>
    );
  }

  if (!chrome && scene) {
    return (
      <div className="jy-app jy-app-stage-only" data-testid="stage-only">
        <PreviewStage project={project} scene={scene} status={status} />
      </div>
    );
  }

  return (
    <div className="jy-app jy-app-ready">
      <Header project={project} draftName={project.draft.name} />
      {stale && (
        <div className="jy-stale" data-testid="stale-banner">
          <span>草稿已在剪映中更改，当前预览可能已过时。</span>
          <button type="button" onClick={() => {
            void session.reload().then(() => {
              setStale(false);
              refresh();
            });
          }}>重新读取</button>
        </div>
      )}
      <aside className="jy-side">
        <DraftPicker drafts={drafts} value={project.draft.id} loading={false} onOpen={onOpen} />
        <TimelinePicker required={session.activeTimelineId() === null}
                        timelines={project.draft.timelines} onPick={onPickTimeline} />
        <WarningsPanel project={project} scene={scene} />
      </aside>
      <main className="jy-main">
        <PreviewStage project={project} scene={scene} status={status} />
        <PlaybackControls status={status} tUs={scene.tUs} durationUs={project.duration_us}
                          fps={project.fps} rate={session.rate()}
                          onPlay={session.play} onPause={session.pause} onSeek={session.seekTo}
                          onRate={session.setRate} />
        <section data-testid="timeline-panel" className="jy-timeline-panel">
          <Timeline project={project} tUs={scene.tUs} selectedClipId={selectedClipId}
                    onSelectClip={setSelectedClipId} onSeek={session.seekTo} />
        </section>
      </main>
      <aside className="jy-right">
        <InspectorPanel project={project} clip={clip} />
      </aside>
    </div>
  );
}

function Header({ project, draftName }: { project: EditorProject | null; draftName: string }) {
  return (
    <header className="jy-header">
      <strong>剪映只读预览</strong>
      <span>{draftName}</span>
      {project && (
        <>
          <span>{project.draft.layout}</span>
          <span>{project.timeline.name || project.timeline.id}</span>
          <span title={project.timeline.source_sha256 ?? ""}>
            {(project.timeline.source_sha256 ?? "").slice(0, 8)}
          </span>
        </>
      )}
      <span className="jy-readonly">只读</span>
    </header>
  );
}

function useEditorHooks(session: EditorSession | null, project: EditorProject | null): void {
  const errors = useRef<string[]>([]);
  const alive = useRef(true);

  useEffect(() => {
    const hook = (globalThis as Record<string, unknown>) as EditorWindow;
    alive.current = true;
    const record = (message: string) => {
      if (alive.current) errors.current.push(message);
    };
    const onError = (event: ErrorEvent) => record(`${event.error?.name ?? "Error"}: ${event.message}`);
    const onRejected = (event: PromiseRejectionEvent) => record(String(event.reason));
    window.addEventListener("error", onError);
    window.addEventListener("unhandledrejection", onRejected);
    hook.__editorSnapshot = () => ({
      ...(project ? { schema: project.schema, timeline: project.timeline,
                      duration_us: project.duration_us, clips: project.clips.length,
                      tracks: project.tracks.length, assets: project.assets.length,
                      warnings: project.warnings } : { schema: null }),
      state: session ? session.status() : "closed",
      t_us: session ? session.clock.tUs : 0,
      errors: [...errors.current],
    });
    hook.__editorScene = () => (session ? serializeScene(session.sceneAt()) : null);
    hook.__editorSeams = () => (project ? seamsOf(project) : []);
    hook.__editorSeek = (tUs: number) => {
      session?.seekTo(Number(tUs));
      return session?.clock.tUs ?? 0;
    };
    hook.__editorPlay = () => session?.play();
    // The shot/audit channel predates this UI and waits on these names, so the editor
    // answers to them instead of every capture script being rewritten.
    hook.__ready = Boolean(project);
    hook.__settle = () => [...document.querySelectorAll<HTMLVideoElement>("video, audio")]
      .every((node) => node.readyState >= 2 || Boolean(node.error) || node.preload === "none");
    hook.__state = () => ({
      did: project?.draft.id ?? "",
      tid: project?.timeline.id ?? "",
      tUs: session?.clock.tUs ?? 0,
      durationUs: project?.duration_us ?? 0,
      ready: Boolean(project),
      playing: session?.status() === "playing",
      loading: { kind: "idle" },
      mode: "editor",
    });
    hook.__play = (on: boolean) => {
      if (on) session?.play();
      else session?.pause();
      return session?.status() === "playing";
    };
    hook.__editorPause = () => session?.pause();
    hook.__editorClose = () => session?.destroy();
    return () => {
      alive.current = false;
      window.removeEventListener("error", onError);
      window.removeEventListener("unhandledrejection", onRejected);
      for (const name of EDITOR_HOOKS) delete hook[name];
    };
  }, [session, project]);
}

const EDITOR_HOOKS = ["__editorSnapshot", "__editorScene", "__editorSeams", "__editorSeek",
  "__editorPlay", "__editorPause", "__editorClose", "__ready", "__settle", "__state",
  "__play"] as const;

interface EditorWindow {
  [key: string]: unknown;
  __editorSnapshot?: () => Record<string, unknown>;
  __editorScene?: () => Record<string, unknown> | null;
  __editorSeams?: () => Record<string, unknown>[];
  __editorSeek?: (tUs: number) => number;
}

/** Where one clip's half-open span ends and the next begins -- the boundaries that
 *  a resolver can disagree about, so acceptance walks them. */
function seamsOf(project: EditorProject): Record<string, unknown>[] {
  const hidden = new Set(project.tracks.filter((track) => !track.visible).map((track) => track.id));
  const byTrack = new Map<string, typeof project.clips>();
  for (const clip of project.clips) {
    if (!clip.visible || hidden.has(clip.track_id) || clip.kind === "audio") continue;
    const list = byTrack.get(clip.track_id) ?? [];
    list.push(clip);
    byTrack.set(clip.track_id, list);
  }
  const seams: Record<string, unknown>[] = [];
  for (const list of byTrack.values()) {
    const ordered = [...list].sort((a, b) => a.target_start_us - b.target_start_us);
    ordered.forEach((previous, index) => {
      const next = ordered[index + 1];
      const touching = next && next.target_start_us === previous.target_end_us;
      seams.push({
        end_us: previous.target_end_us,
        leaving: previous.clip_id,
        entering: touching ? next!.clip_id : null,
      });
    });
  }
  return seams.sort((a, b) => Number(a.end_us) - Number(b.end_us)).slice(0, 40);
}

function serializeScene(scene: Scene): Record<string, unknown> {
  return {
    t_us: scene.tUs,
    clips: scene.clips.map((active) => ({
      clip_id: active.clip.clip_id,
      kind: active.clip.kind,
      z_index: active.clip.z_index,
      source_time_us: active.sourceTimeUs,
      local_us: active.localUs,
    })),
    audio: scene.audio.map((active) => active.clip.clip_id),
    warnings: scene.warnings,
  };
}
