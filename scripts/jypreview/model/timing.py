"""Time resolution: microseconds in, microseconds out."""

from __future__ import annotations

MICRO = 1_000_000


def frame_duration_us(fps: float, fallback: float = 30.0) -> int:
    rate = fps if fps and fps > 0 else fallback
    return int(round(MICRO / rate))


def frame_index(t_us: int, fps: float, fallback: float = 30.0) -> int:
    rate = fps if fps and fps > 0 else fallback
    return int(t_us // (MICRO / rate))


def is_visible(t_us: int, target_start_us: int, target_duration_us: int) -> bool:
    return 0 <= t_us - target_start_us < max(int(target_duration_us), 0)


def local_us(t_us: int, target_start_us: int) -> int:
    return t_us - int(target_start_us)


def source_time_us(local: int, source_start_us: int, speed: float, reverse: bool,
                   target_duration_us: int, source_duration_us: int) -> int:
    """Map a position inside the segment's target range to source media time."""
    rate = speed if speed and speed > 0 else 1.0
    offset = int(round(abs(local) * rate))
    if reverse:
        span = source_duration_us or int(round(target_duration_us * rate))
        return int(source_start_us) + max(span - offset, 0)
    return int(source_start_us) + offset


def transition_window(cut_us: int, duration_us: int) -> tuple[int, int]:
    half = int(duration_us) // 2
    return cut_us - half, cut_us + half


def progress(local: int, duration: int) -> float:
    if duration <= 0:
        return 0.0
    return round(min(max(local / duration, 0.0), 1.0), 6)


def overlap(a_start: int, a_end: int, b_start: int, b_end: int) -> int:
    return max(0, min(a_end, b_end) - max(a_start, b_start))
