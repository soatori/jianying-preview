import type { EditorProject } from "../core/project.ts";
import type { Scene } from "../core/scene.ts";
import { TIER_LABEL } from "./PreviewStage.tsx";

/** What the previewer could not reproduce, stated in the open. */

export interface WarningsPanelProps {
  project: EditorProject;
  scene: Scene;
}

export function WarningsPanel({ project, scene }: WarningsPanelProps) {
  const tiers = tierCounts(project);
  const skipped = notPreviewed(project.warnings);
  const counted = hasTiers(tiers);
  const clean = !counted && !skipped && project.warnings.length === 0 && scene.warnings.length === 0;
  return (
    <div data-testid="warnings" className="jy-warnings">
      {clean && <span>无告警</span>}
      {counted && (
        <div data-testid="tier-counts">
          {Object.entries(tiers)
            .filter(([, count]) => count > 0)
            .map(([tier, count]) => `${TIER_LABEL[tier as keyof typeof TIER_LABEL] ?? tier} ${count}`)
            .join(" · ")}
        </div>
      )}
      {skipped > 0 && <div data-testid="skipped-count">{`${skipped} 项未预览`}</div>}
      {project.warnings.length > 0 && (
        <ul data-testid="project-warnings">
          {project.warnings.map((note) => <li key={note}>{note}</li>)}
        </ul>
      )}
      {scene.warnings.length > 0 && (
        <ul data-testid="scene-warnings">
          {scene.warnings.map((note) => <li key={note}>{note}</li>)}
        </ul>
      )}
    </div>
  );
}

function tierCounts(project: EditorProject): Record<string, number> {
  const counts: Record<string, number> = { exact: 0, approx: 0, placeholder: 0 };
  for (const clip of project.clips) {
    const labels = (clip.labels ?? []) as Record<string, unknown>[];
    const animation = clip.animation as Record<string, unknown> | null;
    for (const item of [...labels, ...(animation ? [animation] : [])]) {
      const tier = String(item.render_class ?? "");
      if (tier in counts) counts[tier] = (counts[tier] ?? 0) + 1;
    }
  }
  return counts;
}

function hasTiers(counts: Record<string, number>): boolean {
  return Object.values(counts).some((count) => count > 0);
}

function notPreviewed(warnings: string[]): number {
  return warnings.reduce((total, note) => {
    const match = /(\d+) item\(s\) not previewed/.exec(note);
    return total + (match ? Number(match[1]) : 0);
  }, 0);
}
