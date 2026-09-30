import { formatTimecode } from "../core/time-format.ts";
import type { PlaybackStatus } from "../core/playback-clock.ts";

/** Transport only. Every control moves the playhead; none of them can move a clip. */

export interface PlaybackControlsProps {
  status: PlaybackStatus;
  tUs: number;
  durationUs: number;
  fps: number;
  rate: number;
  onPlay: () => void;
  onPause: () => void;
  onSeek: (tUs: number) => void;
  onRate: (rate: number) => void;
}

const RATES = [0.5, 1, 2];

const STATUS_LABEL: Record<PlaybackStatus, string> = {
  stopped: "就绪",
  playing: "播放中",
  paused: "已暂停",
  ended: "已结束",
  destroyed: "已关闭",
};

export function PlaybackControls({ status, tUs, durationUs, fps, rate,
                                   onPlay, onPause, onSeek, onRate }: PlaybackControlsProps) {
  const frameUs = Math.max(Math.round(1_000_000 / (fps > 0 ? fps : 30)), 1);
  const playing = status === "playing";
  return (
    <div className="jy-transport" data-testid="playback-controls">
      <span data-testid="playback-status">{STATUS_LABEL[status]}</span>
      <div className="jy-transport-buttons" role="group" aria-label="播放控制">
        <IconButton label="跳到开头" icon="jy-icon-start" onClick={() => onSeek(0)} />
        <IconButton label="上一帧" icon="jy-icon-prev" onClick={() => onSeek(Math.max(tUs - frameUs, 0))} />
        {playing
          ? <IconButton label="暂停" icon="jy-icon-pause" onClick={onPause} />
          : <IconButton label="播放" icon="jy-icon-play" onClick={onPlay} />}
        <IconButton label="下一帧" icon="jy-icon-next" onClick={() => onSeek(Math.min(tUs + frameUs, durationUs))} />
        <IconButton label="跳到结尾" icon="jy-icon-end" onClick={() => onSeek(durationUs)} />
      </div>
      <div className="jy-rates" role="group" aria-label="播放速度">
        {RATES.map((value) => (
          <button key={value} type="button" className="jy-rate" data-rate={value}
                  aria-label={`${value} 倍速`} aria-pressed={value === rate}
                  onClick={() => onRate(value)} />
        ))}
      </div>
      <span data-testid="time-readout">{`${formatTimecode(tUs)} / ${formatTimecode(durationUs)}`}</span>
      <span className="jy-readonly" data-testid="readonly-badge">只读预览</span>
    </div>
  );
}

function IconButton({ label, icon, onClick }: { label: string; icon: string; onClick: () => void }) {
  return <button type="button" className={`jy-icon ${icon}`} aria-label={label} title={label} onClick={onClick} />;
}
