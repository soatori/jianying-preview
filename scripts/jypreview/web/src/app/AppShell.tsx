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
    return () => {
      alive.current = false;
      window.removeEventListener("error", onError);
      window.removeEventListener("unhandledrejection", onRejected);
      delete hook.__editorSnapshot;
      delete hook.__editorScene;
    };
  }, [session, project]);
}

interface EditorWindow {
  __editorSnapshot?: () => Record<string, unknown>;
  __editorScene?: () => Record<string, unknown> | null;
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
