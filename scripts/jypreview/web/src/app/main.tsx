import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { AppShell, type ShellError } from "./AppShell.tsx";
import { openEditorSession, TimelineAmbiguousError, type EditorSession, type ProjectLoader } from "../core/project.ts";
import { parseTimecode } from "../core/time-format.ts";
import type { DraftOption } from "../components/Pickers.tsx";
import "./editor.css";

const params = new URLSearchParams(window.location.search);
const root = createRoot(document.getElementById("root")!);

interface ShellState {
  state: "idle" | "loading" | "ready" | "error";
  session: EditorSession | null;
  error: ShellError | null;
  drafts: DraftOption[];
  draft: string;
}

let view: ShellState = { state: "idle", session: null, error: null, drafts: [], draft: "" };

function render(): void {
  root.render(
    <StrictMode>
      <AppShell
        session={view.session}
        state={view.state}
        error={view.error}
        drafts={view.drafts}
        draft={view.draft}
        onOpen={(draft, timeline) => {
          void open(draft, timeline);
        }}
        onPickTimeline={(timeline) => {
          void open(view.draft, timeline);
        }}
        onRetry={() => {
          void open(view.draft);
        }}
      />
    </StrictMode>,
  );
}

const load: ProjectLoader = async (request) => {
  const query = new URLSearchParams({ draft: request.draft });
  if (request.timeline) query.set("timeline", request.timeline);
  const response = await fetch(`/api/editor-project?${query.toString()}`);
  return response.json();
};

async function openDrafts(): Promise<DraftOption[]> {
  const response = await fetch("/api/drafts");
  const payload = await response.json();
  const rows = (payload?.data?.rows ?? []) as Record<string, unknown>[];
  return rows.filter((row) => row.has_content).map((row) => ({
    id: String(row.did),
    name: String(row.name),
    layout: String(row.layout ?? "unknown"),
    timelines: Number(row.timeline_count ?? (row.timelines as unknown[] | undefined)?.length ?? 0),
  }));
}

async function open(draft: string, timeline?: string): Promise<void> {
  const previous = view.session;
  view = { ...view, state: "loading", draft, error: null };
  render();
  try {
    const session = await openEditorSession({ draft, timeline, load });
    const at = parseTimecode(params.get("t") ?? params.get("t_us") ?? "", session.project().fps);
    if (at !== null) session.seekTo(at);
    previous?.destroy();
    view = { ...view, state: "ready", session, error: null };
  } catch (error) {
    view = { ...view, state: "error", session: null, error: describe(error) };
  }
  render();
}

function describe(error: unknown): ShellError {
  if (error instanceof TimelineAmbiguousError) {
    return { code: error.code, reason: error.message, available: error.available };
  }
  if (error instanceof Error) return { code: "error", reason: error.message };
  return { code: "error", reason: String(error) };
}

function subscribeEvents(): void {
  const source = new EventSource("/api/events");
  source.addEventListener("draft.changed", (event) => {
    const message = event as MessageEvent<string>;
    let changed = "";
    try {
      changed = String(JSON.parse(message.data).did ?? "");
    } catch {
      changed = "";
    }
    if (!view.session || !changed || changed === view.session.project().draft.id) {
      view.session?.markStale("draft-content-changed");
    }
  });
  source.addEventListener("draft.error", () => view.session?.markStale("draft-unreadable"));
  source.addEventListener("draft.created", () => {
    void openDrafts().then((drafts) => {
      view = { ...view, drafts };
      render();
    });
  });
}

document.addEventListener("visibilitychange", () => {
  if (!view.session) return;
  if (document.hidden) view.session.onHidden();
  else view.session.onVisible();
});

(async function start(): Promise<void> {
  const drafts = await openDrafts().catch(() => [] as DraftOption[]);
  view = { ...view, drafts };
  render();
  subscribeEvents();
  const draft = params.get("draft") ?? "";
  if (draft) await open(draft, params.get("timeline") ?? undefined);
})();
