import { useRef, type MouseEvent, type PointerEvent, type RefObject } from "react";

import { formatTimecode, pxPerUs as fitScale, usAt } from "../core/time-format.ts";
import type { Clip, EditorProject, Track } from "../core/project.ts";

/** The lane strip: read-only by construction -- nothing here can move a clip. */

export interface TimelineProps {
  project: EditorProject;
  tUs: number;
  selectedClipId: string | null;
  onSelectClip: (clipId: string) => void;
  onSeek: (tUs: number) => void;
  pxPerUs?: number;
}

const RULER_WIDTH_PX = 1200;

export function Timeline({ project, tUs, selectedClipId, onSelectClip, onSeek, pxPerUs }: TimelineProps) {
  const scale = pxPerUs ?? fitScale(project.duration_us, RULER_WIDTH_PX);
  const ruler = useRef<HTMLDivElement | null>(null);
  const pointerHandled = useRef(0);

  function seekFrom(offsetX: number) {
    const wanted = usAt(offsetX, scale);
    onSeek(Math.min(Math.max(wanted, 0), project.duration_us));
  }

  function offsetOf(clientX: number): number {
    return clientX - (ruler.current?.getBoundingClientRect().left ?? 0);
  }


  const rows = [...project.tracks].sort((a, b) => a.lane - b.lane);
  const clipsByTrack = groupClips(project.clips);

  return (
    <div data-testid="timeline" className="jy-timeline">
      <div className="jy-timeline-head">
        <span data-testid="timeline-read-only">只读时间线</span>
        <span>{project.tracks.length} 条轨道 · {project.clips.length} 个片段</span>
        <span>{formatTimecode(project.duration_us)}</span>
      </div>
      <TimeRuler durationUs={project.duration_us} pxPerUs={scale} rulerRef={ruler} onSeek={onSeek}
                 onScrub={(event) => {
                   pointerHandled.current = event.timeStamp;
                   seekFrom(offsetOf(event.clientX));
                 }} onMouseScrub={(event) => {
                   // A browser delivers pointerdown and then mousedown for the same press.
                   if (event.timeStamp - pointerHandled.current < 500) return;
                   seekFrom(offsetOf(event.clientX));
                 }} />
      <div className="jy-track-stack">
        {rows.map((track) => (
          <TrackRow key={track.id} track={track} clips={clipsByTrack.get(track.id) ?? []}
                    pxPerUs={scale} selectedClipId={selectedClipId} onSelectClip={onSelectClip}
                    onSeek={onSeek} />
        ))}
        <Playhead tUs={tUs} pxPerUs={scale} />
      </div>
    </div>
  );
}

function groupClips(clips: Clip[]): Map<string, Clip[]> {
  const map = new Map<string, Clip[]>();
  for (const clip of clips) {
    const list = map.get(clip.track_id);
    if (list) list.push(clip);
    else map.set(clip.track_id, [clip]);
  }
  return map;
}

interface RulerProps {
  durationUs: number;
  pxPerUs: number;
  rulerRef: RefObject<HTMLDivElement | null>;
  onSeek: (tUs: number) => void;
  onScrub: (event: PointerEvent<HTMLDivElement>) => void;
  onMouseScrub: (event: MouseEvent<HTMLDivElement>) => void;
}

function TimeRuler({ durationUs, pxPerUs, rulerRef, onSeek, onScrub, onMouseScrub }: RulerProps) {
  const step = tickStepUs(pxPerUs);
  const ticks: number[] = [];
  for (let stamp = 0; stamp <= durationUs; stamp += step) ticks.push(stamp);
  if (ticks[ticks.length - 1] !== durationUs) ticks.push(durationUs);
  return (
    <div data-testid="time-ruler" ref={rulerRef} className="jy-ruler" onPointerDown={onScrub}
         onMouseDown={onMouseScrub} aria-label="时间标尺，点击跳转">
      {ticks.map((stamp) => (
        <button key={stamp} type="button" data-tick-us={stamp} data-end={stamp === durationUs || undefined}
                className="jy-ruler-tick" style={{ left: `${stamp * pxPerUs}px` }}
                onPointerDown={(event) => event.stopPropagation()}
                onClick={() => onSeek(stamp)}>
          {formatTimecode(stamp)}
        </button>
      ))}
    </div>
  );
}

function tickStepUs(pxPerUs: number): number {
  const perSecond = pxPerUs * 1_000_000;
  if (perSecond >= 600) return 250_000;
  if (perSecond >= 300) return 500_000;
  if (perSecond >= 100) return 1_000_000;
  if (perSecond >= 40) return 5_000_000;
  if (perSecond >= 20) return 10_000_000;
  return 30_000_000;
}

interface RowProps {
  track: Track;
  clips: Clip[];
  pxPerUs: number;
  selectedClipId: string | null;
  onSelectClip: (clipId: string) => void;
  onSeek: (tUs: number) => void;
}

function TrackRow({ track, clips, pxPerUs, selectedClipId, onSelectClip, onSeek }: RowProps) {
  return (
    <div data-testid="track-row" data-lane={track.lane} data-group={track.group}
         data-visible={String(track.visible)} data-muted={String(track.muted)}
         data-track-id={track.id} className="jy-track-row">
      <div className="jy-track-label">
        <span>{track.name || `轨道 ${track.index}`}</span>
        <span className="jy-track-kind">{track.type}</span>
        {!track.visible && <span className="jy-track-flag">已隐藏</span>}
        {track.muted && <span className="jy-track-flag">静音</span>}
      </div>
      <div className="jy-track-lane">
        {clips.map((clip) => (
          <ClipBlock key={clip.clip_id} clip={clip} pxPerUs={pxPerUs}
                    selected={clip.clip_id === selectedClipId} onSelectClip={onSelectClip}
                    onSeek={onSeek} />
        ))}
      </div>
    </div>
  );
}

function ClipBlock({ clip, pxPerUs, selected, onSelectClip, onSeek }: {
  clip: Clip;
  pxPerUs: number;
  selected: boolean;
  onSelectClip: (clipId: string) => void;
  onSeek: (tUs: number) => void;
}) {
  const missing = clip.asset !== null && !clip.asset.exists;
  const tiers = tierList(clip);
  return (
    <>
      <button
        type="button"
        data-testid="clip-block"
        data-clip-id={clip.clip_id}
        data-kind={clip.kind}
        data-visible={String(clip.visible)}
        data-selected={String(selected)}
        data-status={missing ? "missing" : clip.visible ? "ok" : "hidden"}
        data-tiers={tiers.join(",") || undefined}
        className="jy-clip"
        style={{
          left: `${clip.target_start_us * pxPerUs}px`,
          width: `${Math.max(clip.target_duration_us * pxPerUs, 2)}px`,
        }}
        onClick={() => {
          onSelectClip(clip.clip_id);
          onSeek(clip.target_start_us);
        }}
      >
        <span className="jy-clip-name">{clipTitle(clip)}</span>
        {missing && <span className="jy-clip-flag">素材缺失</span>}
        {!clip.visible && <span className="jy-clip-flag">已隐藏</span>}
        {clip.reverse && <span className="jy-clip-flag">倒放</span>}
        {clip.speed !== 1 && <span className="jy-clip-flag">{`×${clip.speed}`}</span>}
        {clip.animation !== null && <span className="jy-clip-flag" data-render-class={String(clip.animation.render_class ?? "")}>{String(clip.animation.name ?? "动画")}</span>}
        {tiers.map((tier) => <span key={tier} className="jy-clip-dot" data-render-class={tier} />)}
      </button>
      {clip.transition !== null && (
        <TransitionMarker clip={clip} pxPerUs={pxPerUs} />
      )}
    </>
  );
}

function TransitionMarker({ clip, pxPerUs }: { clip: Clip; pxPerUs: number }) {
  const span = (clip.transition?.window ?? {}) as Record<string, number>;
  const startUs = span.start_us ?? 0;
  const endUs = span.end_us ?? startUs;
  return (
    <span data-testid="transition-marker" data-left={round(startUs * pxPerUs)}
          className="jy-transition"
          style={{ left: `${startUs * pxPerUs}px`, width: `${Math.max((endUs - startUs) * pxPerUs, 4)}px` }}>
      {String(clip.transition?.name ?? "转场")}
    </span>
  );
}

function Playhead({ tUs, pxPerUs }: { tUs: number; pxPerUs: number }) {
  return <div data-testid="playhead" data-left={round(tUs * pxPerUs)} className="jy-playhead"
              style={{ left: `${tUs * pxPerUs}px` }} />;
}

function clipTitle(clip: Clip): string {
  const text = clip.text?.text;
  return String(firstLabel(clip) ?? clip.asset?.name
    ?? (text ? String(text) : KIND_LABEL[clip.kind] ?? clip.kind));
}

const KIND_LABEL: Record<string, string> = {
  text: "文本",
  video: "视频",
  photo: "图片",
  image: "图片",
  sticker: "贴纸",
  audio: "音频",
  subdraft: "复合片段",
  effect: "特效",
  filter: "滤镜",
  adjust: "调节",
};

function firstLabel(clip: Clip): string | null {
  for (const item of clip.labels ?? []) {
    const label = item as Record<string, unknown>;
    if (label.name) return String(label.name);
  }
  const animation = clip.animation as Record<string, unknown> | null;
  return animation?.name ? String(animation.name) : null;
}

function tierList(clip: Clip): string[] {
  const tiers = new Set<string>();
  for (const item of clip.labels ?? []) {
    const tier = String((item as Record<string, unknown>).render_class ?? "");
    if (tier && tier !== "exact") tiers.add(tier);
  }
  const animation = clip.animation as Record<string, unknown> | null;
  const animTier = String(animation?.render_class ?? "");
  if (animTier && animTier !== "exact") tiers.add(animTier);
  return [...tiers];
}

function round(value: number): number {
  return Math.round(value * 1e4) / 1e4;
}
