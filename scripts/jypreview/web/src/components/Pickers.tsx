import { useState } from "react";

import { formatTimecode } from "../core/time-format.ts";

/** Draft and timeline navigation -- choosing is the only change this editor can make. */

export interface DraftOption {
  id: string;
  name: string;
  layout: string;
  timelines: number;
}

export interface DraftPickerProps {
  drafts: DraftOption[];
  value: string;
  loading: boolean;
  onOpen: (draft: string, timeline?: string) => void;
}

export function DraftPicker({ drafts, value, loading, onOpen }: DraftPickerProps) {
  const [query, setQuery] = useState("");
  const needle = query.trim().toLowerCase();
  const rows = needle
    ? drafts.filter((draft) => draft.name.toLowerCase().includes(needle)
        || draft.id.toLowerCase().includes(needle))
    : drafts;
  return (
    <div className="jy-picker" data-testid="draft-picker">
      <h2>打开草稿</h2>
      <input type="search" value={query} placeholder="按名称搜索" aria-label="搜索草稿"
             onChange={(event) => setQuery(event.target.value)} />
      {loading && <div data-testid="draft-loading">读取中…</div>}
      <ul className="jy-picker-list">
        {rows.map((draft) => (
          <li key={draft.id} data-testid="draft-row" data-current={String(draft.id === value)}>
            <button type="button" onClick={() => onOpen(draft.id)}>
              {draft.name}
              <em>{draft.layout}</em>
              <em>{draft.timelines} 条时间线</em>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

export interface TimelineOption {
  id: string;
  name?: string | null;
  active?: boolean;
  deleted?: boolean;
  duration_us?: number | null;
}

export interface TimelinePickerProps {
  timelines: TimelineOption[];
  required: boolean;
  onPick: (timeline: string) => void;
}

export function TimelinePicker({ timelines, required, onPick }: TimelinePickerProps) {
  return (
    <div className="jy-picker" data-testid="timeline-picker">
      {required && <h2>需要选择时间线</h2>}
      <ul className="jy-picker-list">
        {timelines.map((timeline) => (
          <li key={timeline.id} data-testid="timeline-option" data-timeline-id={timeline.id}
              data-active={String(Boolean(timeline.active))} data-deleted={String(Boolean(timeline.deleted))}>
            <button type="button" onClick={() => onPick(timeline.id)}>
              {timeline.name || timeline.id}
              <em>{timeline.duration_us ? formatTimecode(timeline.duration_us) : "时长未知"}</em>
              {timeline.active && <span className="jy-flag">当前</span>}
              {timeline.deleted && <span className="jy-flag">已删除</span>}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
