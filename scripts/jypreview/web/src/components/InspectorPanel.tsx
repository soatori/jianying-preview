import type { Clip, EditorProject } from "../core/project.ts";
import { formatTimecode } from "../core/time-format.ts";
import { TIER_LABEL } from "./PreviewStage.tsx";

/** Everything the selected clip is, and nothing you can change about it. */

export interface InspectorPanelProps {
  project: EditorProject;
  clip: Clip | null;
}

export function InspectorPanel({ clip }: InspectorPanelProps) {
  if (!clip) {
    return <div data-testid="inspector" className="jy-inspector jy-inspector-empty">
      在时间线上选择一个片段
    </div>;
  }
  const asset = clip.asset;
  const labels = (clip.labels ?? []) as Record<string, unknown>[];
  const text = clip.text as Record<string, unknown> | null;
  const runs = (text?.runs ?? []) as Record<string, unknown>[];
  const nest = clip.nest as Record<string, unknown> | null;
  const transition = clip.transition as Record<string, unknown> | null;

  return (
    <div data-testid="inspector" className="jy-inspector">
      <Section title="身份">
        <Field name="clip_id" value={clip.clip_id} />
        <Field name="kind" value={clip.kind} />
        <Field name="track" value={`${clip.track_id} · ${clip.track_type || "?"}`} />
        <Field name="z_index" value={clip.z_index} />
        <Field name="position" value={Number(clip.position ?? 0)} />
      </Section>
      <Section title="时间">
        <Field name="target" value={`${formatTimecode(clip.target_start_us)} → ` +
          `${formatTimecode(clip.target_end_us)}`} />
        <Field name="source" value={`${clip.source_start_us} – ${clip.source_end_us} µs ` +
          `(${clip.source_duration_us} µs)`} />
        <Field name="speed" value={clip.speed} />
        <Field name="reverse" value={clip.reverse ? "倒放" : "正向"} />
      </Section>
      <Section title="素材">
        <Field name="asset-state" value={asset ? (asset.exists ? "可用" : `素材缺失 · ${asset.placeholder_reason ?? asset.how ?? ""}`) : "无素材"} />
        <Field name="asset-name" value={asset?.name ?? "—"} />
        <Field name="asset-url" value={asset?.path_served ?? "—"} />
        <Field name="media-how" value={asset?.how ?? "—"} />
      </Section>
      {(labels.length > 0 || transition !== null || clip.animation !== null) && (
        <Section title="样式与效果">
          {transition && <Field name="transition"
                                value={`${String(transition.name ?? "转场")} · ${TIER_LABEL[String(transition.render_class ?? "placeholder") as keyof typeof TIER_LABEL] ?? ""}`} />}
          {labels.map((label, index) => (
            <div key={`${label.bucket}-${index}`} data-testid="label-row"
                 data-render-class={String(label.render_class ?? "")}
                 data-tier-label={TIER_LABEL[String(label.render_class ?? "placeholder") as keyof typeof TIER_LABEL] ?? ""}>
              {String(label.name ?? label.kind)} <em>{String(label.bucket)}</em>
            </div>
          ))}
        </Section>
      )}
      {text && (
        <Section title="文本">
          <Field name="text-content" value={String(text.text ?? "")} />
          <Field name="text-font" value={fontSummary(text)} />
          <Field name="text-size" value={`${sizeEm(text)} px`} />
          <Field name="text-stroke" value={strokeSummary(runs)} />
          <Field name="text-align" value={String(((text.box ?? {}) as Record<string, unknown>).alignment ?? "")} />
        </Section>
      )}
      {nest && (
        <Section title="复合片段">
          <Field name="nest-depth" value={Number(nest.depth ?? 0)} />
          <Field name="nest-note" value={nestNote(nest)} />
          <Field name="nest-layers" value={((nest.layers ?? []) as unknown[]).length} />
        </Section>
      )}
      {clip.warnings.length > 0 && (
        <Section title="告警">
          <ul data-field="clip-warnings">
            {clip.warnings.map((note) => <li key={note}>{note}</li>)}
          </ul>
        </Section>
      )}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="jy-inspector-section">
      <h3>{title}</h3>
      <dl>{children}</dl>
    </section>
  );
}

function Field({ name, value }: { name: string; value: string | number | null }) {
  return (
    <div className="jy-field">
      <dt>{name}</dt>
      <dd data-field={name}>{value}</dd>
    </div>
  );
}

function fontSummary(text: Record<string, unknown>): string {
  const font = (text.font ?? {}) as Record<string, unknown>;
  const parts = [font.title, font.family, font.source].filter(Boolean).map(String);
  return parts.length ? parts.join(" · ") : "系统字体";
}

function sizeEm(text: Record<string, unknown>): number {
  const box = (text.box ?? {}) as Record<string, unknown>;
  const runs = (text.runs ?? []) as Record<string, unknown>[];
  return Number(box.em_px ?? runs[0]?.em_px ?? 0);
}

function strokeSummary(runs: Record<string, unknown>[]): string {
  const strokes = runs.reduce((total, run) => total + ((run.strokes ?? []) as unknown[]).length, 0);
  const shadows = runs.reduce((total, run) => total + ((run.shadows ?? []) as unknown[]).length, 0);
  const flowers = runs.filter((run) => run.flower).length;
  const parts: string[] = [];
  if (strokes) parts.push(`描边 ${strokes}`);
  if (shadows) parts.push(`阴影 ${shadows}`);
  if (flowers) parts.push(`花字 ${flowers} · ${TIER_LABEL.placeholder}`);
  return parts.length ? parts.join(" · ") : "无描边";
}

function nestNote(nest: Record<string, unknown>): string {
  if (Array.isArray(nest.layers) && (nest.layers as unknown[]).length) return "内层已展平";
  const reason = String(nest.reason ?? "");
  if (reason.includes("cover")) return "改用剪映自带的复合片段封面";
  return reason || "内层不可解析";
}
