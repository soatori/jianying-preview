import { useEffect, useRef, useState, type CSSProperties, type RefObject } from "react";

import type { Asset, Clip, EditorProject } from "../core/project.ts";
import type { ActiveClip, Scene } from "../core/scene.ts";
import type { PlaybackStatus } from "../core/playback-clock.ts";

/** The DOM stage: one node per clip id, positioned from the rect Python resolved.
 *
 * Media elements only ever receive instructions here -- `currentTime`, `playbackRate`,
 * `muted` -- and never the reverse. The clock is the sole time authority.
 */

const SEEK_EPSILON_S = 0.02;

type Tier = "exact" | "approx" | "placeholder";

interface LayerView {
  clipId: string;
  kind: string;
  rect: Record<string, unknown> | null;
  asset: Asset | null;
  text: Record<string, unknown> | null;
  labels: Record<string, unknown>[];
  animation: Record<string, unknown> | null;
  canvasFill: Record<string, unknown> | null;
  nest: Record<string, unknown> | null;
  speed: number;
  reversed: boolean;
  muted: boolean;
  opacity: number;
  zIndex: number;
  sourceTimeUs: number;
  tier: Tier | null;
  children: LayerView[];
}

export interface PreviewStageProps {
  project: EditorProject;
  scene: Scene;
  status: PlaybackStatus;
}

export function PreviewStage({ project, scene, status }: PreviewStageProps) {
  const playing = status === "playing";
  const [fit, scale] = useFitScale(project.canvas.width, project.canvas.height);
  return (
    <div ref={fit} data-testid="stage-fit" className="jy-stage-fit">
    <div
      data-testid="stage-frame"
      className="jy-stage-frame"
      style={{ width: `${project.canvas.width * scale}px`, height: `${project.canvas.height * scale}px` }}
    >
    <div
      data-testid="stage"
      className="jy-stage"
      style={{
        width: `${project.canvas.width}px`,
        height: `${project.canvas.height}px`,
        background: project.canvas.background,
        transform: `scale(${scale})`,
      }}
    >
      {scene.clips.map((active) => (
        <LayerNode key={active.clip.clip_id} view={viewOf(active)} playing={playing} />
      ))}
      {scene.audio.map((active) => (
        <AudioNode key={active.clip.clip_id} view={viewOf(active)} playing={playing} />
      ))}
    </div>
    </div>
    </div>
  );
}

/** The canvas keeps its authored pixel size; only the view of it shrinks. */
/** The fit box is sized by CSS; the canvas keeps its authored pixels and only the view shrinks. */
function useFitScale(width: number, height: number): [RefObject<HTMLDivElement | null>, number] {
  const fit = useRef<HTMLDivElement | null>(null);
  const [scale, setScale] = useState(1);
  useEffect(() => {
    const box = fit.current;
    if (typeof ResizeObserver === "undefined" || !box) return;
    const observer = new ResizeObserver((entries) => {
      const rect = entries[0]?.contentRect;
      if (!rect || !rect.width || !rect.height) return;
      setScale(Math.min(rect.width / width, rect.height / height, 1));
    });
    observer.observe(box);
    return () => observer.disconnect();
  }, [width, height]);
  return [fit, scale];
}

function tierOf(labels: Record<string, unknown>[], animation: Record<string, unknown> | null): Tier | null {
  const tiers = labels.map((label) => String(label.render_class ?? ""));
  if (animation) tiers.push(String(animation.render_class ?? ""));
  if (tiers.includes("placeholder")) return "placeholder";
  if (tiers.includes("approx")) return "approx";
  return tiers.includes("exact") ? "exact" : null;
}

function viewOf(active: ActiveClip): LayerView {
  const clip = active.clip;
  return {
    clipId: clip.clip_id,
    kind: clip.kind,
    rect: clip.rect,
    asset: clip.asset,
    text: clip.text,
    labels: (clip.labels ?? []) as Record<string, unknown>[],
    animation: (clip.animation ?? null) as Record<string, unknown> | null,
    canvasFill: (clip.canvas_fill ?? null) as Record<string, unknown> | null,
    nest: clip.nest,
    speed: clip.speed,
    reversed: clip.reverse,
    muted: active.muted,
    opacity: active.opacity,
    zIndex: clip.z_index,
    sourceTimeUs: active.sourceTimeUs,
    tier: tierOf((clip.labels ?? []) as Record<string, unknown>[],
                 (clip.animation ?? null) as Record<string, unknown> | null),
    children: nestedViews(clip),
  };
}

function nestedViews(clip: Clip): LayerView[] {
  const layers = (clip.nest?.layers ?? []) as Record<string, unknown>[];
  return layers.map((layer) => {
    const time = (layer.time ?? {}) as Record<string, number>;
    const media = (layer.media ?? null) as Record<string, unknown> | null;
    const labels = (layer.labels ?? []) as Record<string, unknown>[];
    const animation = (layer.animation ?? null) as Record<string, unknown> | null;
    return {
      clipId: String(layer.layer_id ?? ""),
      kind: String(layer.kind ?? "video"),
      rect: (layer.rect ?? null) as Record<string, unknown> | null,
      asset: media ? { ...(media as object), asset_id: String(media.material_id ?? ""),
                       exists: Boolean(media.exists), name: (media.material_name ?? null) as string | null,
                       path_served: (media.path_served ?? null) as string | null,
                       kind: (media.family ?? null) as string | null, how: null,
                       placeholder_reason: (media.placeholder_reason ?? null) as string | null,
                       clip_ids: [] } as unknown as Asset : null,
      text: (layer.text ?? null) as Record<string, unknown> | null,
      labels,
      animation,
      canvasFill: null,
      nest: null,
      speed: Number(time.speed ?? 1),
      reversed: Boolean(time.reverse),
      muted: false,
      opacity: Number(((layer.rect ?? {}) as Record<string, unknown>).alpha ?? 1),
      zIndex: Number((((layer.z ?? {}) as Record<string, unknown>).order as number) ?? 0),
      sourceTimeUs: Number(time.source_time_us ?? 0),
      tier: tierOf(labels, animation),
      children: [],
    } satisfies LayerView;
  });
}

function geometry(rect: Record<string, unknown> | null): CSSProperties {
  if (!rect) return { position: "absolute", inset: "0px" };
  const width = Number(rect.w_px ?? 0);
  const height = Number(rect.h_px ?? 0);
  const rotation = Number(rect.rotation_deg ?? 0);
  const scaleX = Number(rect.scale_x ?? 1) * (rect.flip_x ? -1 : 1);
  const scaleY = Number(rect.scale_y ?? 1) * (rect.flip_y ? -1 : 1);
  return {
    position: "absolute",
    left: `${Number(rect.cx_px ?? 0) - width / 2}px`,
    top: `${Number(rect.cy_px ?? 0) - height / 2}px`,
    width: `${width}px`,
    height: `${height}px`,
    transform: `rotate(${rotation}deg) scale(${scaleX}, ${scaleY})`,
    transformOrigin: "center",
    opacity: Number(rect.alpha ?? 1),
  };
}

function syncMedia(element: HTMLMediaElement | null, view: LayerView, playing: boolean): void {
  if (!element) return;
  const seconds = view.sourceTimeUs / 1e6;
  const mustTrack = !playing || view.reversed;
  const drifted = Math.abs(element.currentTime - seconds) > SEEK_EPSILON_S;
  if (mustTrack || drifted) element.currentTime = seconds;
  element.playbackRate = view.speed;
  element.muted = view.muted;
  if (playing && !view.reversed) {
    // Only a media element that has read its metadata can be told to play; asking any
    // earlier only queues a rejected promise per frame.
    if (element.paused && element.readyState > 0) {
      try {
        void element.play()?.catch(() => undefined);
      } catch {
        // The clock keeps running either way; a silent element is a rendering problem.
      }
    }
  } else if (!element.paused) {
    element.pause();
  }
}

function useMediaSync(view: LayerView, playing: boolean) {
  const ref = useRef<HTMLMediaElement | null>(null);
  useEffect(() => {
    syncMedia(ref.current, view, playing);
  }, [view, playing]);
  return ref;
}

function mediaState(view: LayerView): "ok" | "missing" | null {
  if (view.kind === "text" || view.kind === "subdraft") return null;
  if (["effect", "filter", "adjust"].includes(view.kind)) return null;
  if (!view.asset) return view.kind === "video" || view.kind === "photo" || view.kind === "image"
    || view.kind === "sticker" ? "missing" : null;
  return view.asset.exists ? "ok" : "missing";
}

function LayerNode({ view, playing }: { view: LayerView; playing: boolean }) {
  const state = mediaState(view);
  const family = view.text ? String(((view.text.font ?? {}) as Record<string, unknown>).family ?? "") : "";
  const style: CSSProperties = { ...geometry(view.rect), zIndex: view.zIndex };
  const ref = useMediaSync(view, playing);
  const isImage = view.asset?.kind === "image" || view.kind === "photo" || view.kind === "sticker";
  const served = view.asset?.path_served ?? null;

  return (
    <div
      data-testid="stage-layer"
      data-clip-id={view.clipId}
      data-kind={view.kind}
      data-media-state={state ?? undefined}
      data-reversed={String(view.reversed)}
      data-render-class={view.tier ?? undefined}
      data-text-source={view.text ? String(((view.text.font ?? {}) as Record<string, unknown>).source ?? "") : undefined}
      data-canvas-fill={view.canvasFill?.type as string | undefined}
      data-nest-depth={view.nest?.depth as number | undefined}
      style={{ ...style, fontFamily: family || undefined }}
    >
      {state === "missing" && (
        <div className="jy-placeholder">
          <span>{view.asset?.name ?? view.clipId}</span>
          <span>素材缺失</span>
        </div>
      )}
      {state === "ok" && served && view.kind === "audio" && (
        <audio ref={ref as RefObject<HTMLAudioElement>} src={served} preload="auto" />
      )}
      {state === "ok" && served && isImage && <img src={served} alt="" />}
      {state === "ok" && served && !isImage && view.kind !== "audio" && (
        <video ref={ref as RefObject<HTMLVideoElement>} src={served} preload="auto" playsInline
               muted={view.muted} />
      )}
      {view.text && <TextLayer text={view.text} />}
      {view.children.map((child) => (
        <LayerNode key={child.clipId} view={child} playing={playing} />
      ))}
      <AnnotationChips view={view} />
    </div>
  );
}

function AudioNode({ view, playing }: { view: LayerView; playing: boolean }) {
  const ref = useMediaSync(view, playing);
  const served = view.asset?.path_served ?? null;
  return (
    <div data-testid="audio-layer" data-clip-id={view.clipId} data-media-state={mediaState(view) ?? undefined}>
      {served && <audio ref={ref as RefObject<HTMLAudioElement>} src={served} preload="auto" muted={view.muted} />}
      {!served && <span data-testid="audio-missing">{view.asset?.name ?? view.clipId} 素材缺失</span>}
    </div>
  );
}

function AnnotationChips({ view }: { view: LayerView }) {
  const chips = view.labels.map((label, index) => ({
    key: `${label.bucket}-${index}`,
    name: String(label.name ?? label.kind ?? ""),
    tier: String(label.render_class ?? "placeholder") as Tier,
  }));
  if (view.animation) {
    chips.push({ key: "animation", name: String(view.animation.name ?? "动画"),
                 tier: String(view.animation.render_class ?? "placeholder") as Tier });
  }
  if (!chips.length) return null;
  return (
    <div className="jy-chips" data-testid="layer-chips">
      {chips.map((chip) => (
        <span key={chip.key} className="jy-chip" data-render-class={chip.tier}>
          {TIER_LABEL[chip.tier]} · {chip.name}
        </span>
      ))}
    </div>
  );
}

export const TIER_LABEL: Record<Tier, string> = {
  exact: "精确",
  approx: "近似",
  placeholder: "未渲染",
};

function TextLayer({ text }: { text: Record<string, unknown> }) {
  const runs = (text.runs ?? []) as Record<string, unknown>[];
  const box = (text.box ?? {}) as Record<string, unknown>;
  const vertical = Boolean(box.vertical);
  return (
    <div className="jy-text" data-vertical={String(vertical)}
         data-alignment={String(box.alignment ?? "center")}
         style={{ writingMode: vertical ? "vertical-rl" : "horizontal-tb" }}>
      {runs.map((run, index) => (
        <span key={index} data-run={index}
              style={{
                fontSize: `${Number(run.em_px ?? 0)}px`,
                color: String(((run.fill ?? {}) as Record<string, unknown>).css ?? "#ffffff"),
                fontWeight: run.bold ? 700 : 400,
                fontStyle: run.italic ? "italic" : "normal",
                textDecoration: run.underline ? "underline" : "none",
              }}
              data-strokes={strokeSpec(run)}
              data-shadows={shadowSpec(run)}
              data-flower={run.flower ? String((run.flower as Record<string, unknown>).resource_id ?? "") : undefined}
        >
          {String(run.text ?? "")}
          {Boolean(run.flower) && (
            <span data-flower-badge="true" className="jy-flower-badge">
              {String((run.flower as Record<string, unknown>).name ?? "花字")} · {TIER_LABEL.placeholder}
            </span>
          )}
        </span>
      ))}
    </div>
  );
}

function strokeSpec(run: Record<string, unknown>): string {
  const em = Number(run.em_px ?? 0);
  return ((run.strokes ?? []) as Record<string, unknown>[])
    .map((stroke) => `${round(em * Number(stroke.width_em ?? 0))}px ${stroke.color ?? ""}`.trim())
    .join(", ");
}

function shadowSpec(run: Record<string, unknown>): string {
  const em = Number(run.em_px ?? 0);
  return ((run.shadows ?? []) as Record<string, unknown>[])
    .map((shadow) => {
      const distance = em * Number(shadow.distance_em ?? 0);
      const angle = Number(shadow.angle_deg ?? 0) * (Math.PI / 180);
      return `${round(Math.cos(angle) * distance)}px ${round(Math.sin(angle) * distance)}px ` +
        `${shadow.color ?? ""}`.trim();
    })
    .join(", ");
}

function round(value: number): number {
  return Math.round(value * 1e4) / 1e4;
}
