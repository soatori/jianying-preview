"""Immutable timeline values and deterministic project-frame evaluation."""

from __future__ import annotations

from dataclasses import dataclass, replace
from math import gcd, isfinite

from .content import DEFAULT_RI

MICRO = 1_000_000
Scalar = str | int | float | bool | None
Params = tuple[tuple[str, Scalar], ...]


def _integer(value: int, name: str) -> None:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer")


def _params(value: Params) -> Params:
    result = tuple(tuple(pair) for pair in value)
    if any(len(pair) != 2 or not isinstance(pair[0], str)
           or not isinstance(pair[1], (str, int, float, bool, type(None)))
           for pair in result):
        raise ValueError("parameters must be immutable name/scalar pairs")
    return result


@dataclass(frozen=True)
class FrameRate:
    num: int
    den: int = 1

    def __post_init__(self) -> None:
        _integer(self.num, "fps numerator")
        _integer(self.den, "fps denominator")
        if not self.num or not self.den or self.num > MICRO * self.den:
            raise ValueError("fps must be positive and at most one frame per microsecond")
        common = gcd(self.num, self.den)
        object.__setattr__(self, "num", self.num // common)
        object.__setattr__(self, "den", self.den // common)

    def sample_us(self, frame_index: int) -> int:
        _integer(frame_index, "frame index")
        return (frame_index * MICRO * self.den + self.num - 1) // self.num

    def quantize(self, t_us: int) -> tuple[int, int]:
        _integer(t_us, "time")
        frame = t_us * self.num // (MICRO * self.den)
        return frame, self.sample_us(frame)

    def first_frame_at_or_after(self, t_us: int) -> int:
        _integer(t_us, "boundary")
        return ((t_us - 1) * self.num) // (MICRO * self.den) + 1 if t_us else 0

    def frame_count(self, duration_us: int) -> int:
        return self.first_frame_at_or_after(duration_us)


@dataclass(frozen=True)
class TimeRange:
    start_us: int
    duration_us: int

    def __post_init__(self) -> None:
        _integer(self.start_us, "range start")
        _integer(self.duration_us, "range duration")

    @property
    def end_us(self) -> int:
        return self.start_us + self.duration_us

    def contains(self, t_us: int) -> bool:
        return self.start_us <= t_us < self.end_us


@dataclass(frozen=True)
class TimeMapping:
    rate_num: int = 1
    rate_den: int = 1
    direction: str = "forward"
    kind: str = "constant"

    def __post_init__(self) -> None:
        _integer(self.rate_num, "rate numerator")
        _integer(self.rate_den, "rate denominator")
        if not self.rate_num or not self.rate_den or self.direction not in ("forward", "reverse"):
            raise ValueError("mapping requires a positive rate and forward/reverse direction")
        common = gcd(self.rate_num, self.rate_den)
        object.__setattr__(self, "rate_num", self.rate_num // common)
        object.__setattr__(self, "rate_den", self.rate_den // common)

    def _unclamped_us(self, local_us: int, source: TimeRange) -> int:
        offset = local_us * self.rate_num // self.rate_den
        return source.end_us - 1 - offset if self.direction == "reverse" else source.start_us + offset

    def source_us(self, local_us: int, source: TimeRange) -> int | None:
        _integer(local_us, "local time")
        if not source.duration_us:
            return None
        return min(max(self._unclamped_us(local_us, source), source.start_us), source.end_us - 1)


@dataclass(frozen=True)
class MediaRef:
    id: str = ""
    path: str = ""
    exists: bool = False
    available_range: TimeRange | None = None
    duration_us: int | None = None
    frame_rate: FrameRate | None = None
    has_audio: bool | None = None
    width: int = 0
    height: int = 0
    rotation: int = 0

    def __post_init__(self) -> None:
        if self.duration_us is not None:
            _integer(self.duration_us, "media duration")
        _integer(self.width, "media width")
        _integer(self.height, "media height")
        # Container display rotation is signed (-90/90/180 are all seen in phone footage),
        # so it must not go through _integer's nonnegative check.
        if not isinstance(self.rotation, int) or isinstance(self.rotation, bool):
            raise ValueError("media rotation must be an integer")


@dataclass(frozen=True)
class AudioSpec:
    enabled: bool = True
    volume: float = 1.0

    def __post_init__(self) -> None:
        if not isfinite(self.volume) or self.volume < 0:
            raise ValueError("audio volume must be finite and nonnegative")


@dataclass(frozen=True)
class Transform:
    x: float = 0.0
    y: float = 0.0
    width: float = 0.0
    height: float = 0.0
    rotation: float = 0.0
    scale_x: float = 1.0
    scale_y: float = 1.0
    anchor_x: float = 0.5
    anchor_y: float = 0.5
    flip_x: bool = False
    flip_y: bool = False


@dataclass(frozen=True)
class TextPayload:
    text: str
    font_family: str = ""
    font_path: str = ""
    font_size: float = 24.0
    color: str = "#ffffff"
    box: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    style: Params = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "box", tuple(self.box))
        object.__setattr__(self, "style", _params(self.style))


@dataclass(frozen=True)
class EffectSpec:
    id: str
    kind: str
    window: TimeRange | None = None
    params: Params = ()
    supported: bool = True
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "params", _params(self.params))
        object.__setattr__(self, "warnings", tuple(self.warnings))


@dataclass(frozen=True)
class Clip:
    id: str
    kind: str
    timeline_range: TimeRange
    source_range: TimeRange = TimeRange(0, 0)
    media_ref: MediaRef | None = None
    time_mapping: TimeMapping = TimeMapping()
    audio: AudioSpec = AudioSpec()
    text_payload: TextPayload | None = None
    transform: Transform = Transform()
    opacity: float = 1.0
    crop: tuple[float, float, float, float] = (0.0, 0.0, 1.0, 1.0)
    blend_mode: str = "normal"
    effects: tuple[EffectSpec, ...] = ()
    animations: tuple[EffectSpec, ...] = ()
    render_index: int | None = None
    visible: bool = True
    nested: TimelineModel | None = None
    warnings: tuple[str, ...] = ()
    placeholder: bool = False
    # JianYing colour curves: ((channel, ((x, y), ...)), ...) with x/y normalised to 0..1,
    # already sampled from the draft's Bezier control points. Empty means "no grading curve".
    color_curve: tuple[tuple[str, tuple[tuple[float, float], ...]], ...] = ()
    # JianYing 调节/美化 scalars from `materials.effects` ((kind, value), ...) with value in
    # -1..1, summed per kind over this clip's own effect labels. Nested compounds keep their
    # own grade, so a compound and its leaf clip each contribute one gamma stage.
    grade: tuple[tuple[str, float], ...] = ()

    def __post_init__(self) -> None:
        if not isfinite(self.opacity) or not 0 <= self.opacity <= 1:
            raise ValueError("opacity must be between zero and one")
        for name in ("crop", "effects", "animations", "warnings", "color_curve", "grade"):
            object.__setattr__(self, name, tuple(getattr(self, name)))


@dataclass(frozen=True)
class Track:
    id: str
    type: str
    clips: tuple[Clip, ...] = ()
    order: int = 0
    enabled: bool = True
    muted: bool = False
    render_index: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "clips", tuple(self.clips))


@dataclass(frozen=True)
class Transition:
    id: str
    kind: str
    window: TimeRange
    from_clip_id: str | None = None
    to_clip_id: str | None = None
    duration_us: int | None = None
    params: Params = ()
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.duration_us is None:
            object.__setattr__(self, "duration_us", self.window.duration_us)
        _integer(self.duration_us, "transition duration")
        object.__setattr__(self, "params", _params(self.params))
        object.__setattr__(self, "warnings", tuple(self.warnings))


@dataclass(frozen=True)
class TimelineModel:
    id: str
    duration_us: int
    frame_rate: FrameRate = FrameRate(30)
    canvas: tuple[int, int] = (1920, 1080)
    tracks: tuple[Track, ...] = ()
    transitions: tuple[Transition, ...] = ()
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _integer(self.duration_us, "timeline duration")
        for name in ("canvas", "tracks", "transitions", "warnings"):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        if len(self.canvas) != 2 or any(type(size) is not int or size <= 0 for size in self.canvas):
            raise ValueError("canvas must have positive integer width and height")

    def rescale(self, factor: float) -> "TimelineModel":
        """Return a geometrically equivalent model rendering at ``factor`` of canvas size.

        The interactive browser session compiles against a reduced canvas: per-frame RGBA
        buffers, compositing and affine scaling all shrink with it (8.3 MB/frame at
        1080x1920 -> 2 MB at 540x960), which is the lever for the ~11.4 GB private working
        set a full-canvas open costs on a 16 GB machine. This is the one place the scale
        lives: every canvas-pixel value (canvas size, Clip.transform cx/cy/w/h, pango text
        em size and text box) is multiplied here, so downstream consumers -- the MLT
        profile, producer probe sizes and blend geometry -- need no knowledge of it.
        Unit-less values (crop, anchors, scale multipliers, opacity, blend, em-relative
        strokes) and every time value are untouched, so frame identity is unchanged.
        Validation and the export-match harness keep calling this with no rescale at all.
        """
        if not 0 < factor < 1.0:
            raise ValueError("rescale factor must be in (0, 1)")
        width, height = self.canvas
        return replace(self,
                       canvas=(max(1, round(width * factor)), max(1, round(height * factor))),
                       tracks=tuple(replace(track, clips=tuple(_rescaled_clip(clip, factor)
                                                                for clip in track.clips))
                                    for track in self.tracks))


def _rescaled_clip(clip: Clip, factor: float) -> Clip:
    """Scale one clip's canvas-pixel fields; compounds recurse through ``nested``."""
    updates: dict[str, object] = {}
    t = clip.transform
    if t != Transform():  # the identity default is already scale-invariant
        updates["transform"] = replace(t, x=t.x * factor, y=t.y * factor,
                                       width=t.width * factor, height=t.height * factor)
    text = clip.text_payload
    if text is not None:
        # font_size is the pango em in canvas px; box is (cx, cy, w, h) in canvas px.
        # Stroke widths ride in as em-relative params and follow font_size for free.
        updates["text_payload"] = replace(text, font_size=text.font_size * factor,
                                          box=tuple(value * factor for value in text.box))
    if clip.nested is not None:
        updates["nested"] = clip.nested.rescale(factor)
    return replace(clip, **updates) if updates else clip


@dataclass(frozen=True)
class SceneItem:
    clip: Clip
    track_id: str
    source_us: int | None
    local_us: int
    render_index: int
    original_track_index: int
    original_segment_index: int
    opacity: float
    volume: float
    transition_ids: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "transition_ids", tuple(self.transition_ids))
        object.__setattr__(self, "warnings", tuple(self.warnings))

    @property
    def clip_id(self) -> str:
        return self.clip.id

    @property
    def transform(self) -> Transform:
        return self.clip.transform


@dataclass(frozen=True)
class ExpectedScene:
    state: str
    frame_index: int
    sample_us: int
    video: tuple[SceneItem, ...] = ()
    audio: tuple[SceneItem, ...] = ()
    transitions: tuple[Transition, ...] = ()
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("video", "audio", "transitions", "warnings"):
            object.__setattr__(self, name, tuple(getattr(self, name)))


def evaluate(model: TimelineModel, t_us: int) -> ExpectedScene:
    """Select clips at the canonical sample, independent of previous requests."""
    frame, sample = model.frame_rate.quantize(t_us)
    if t_us >= model.duration_us:
        return ExpectedScene("ended", frame, sample, warnings=model.warnings)
    transitions = tuple(t for t in model.transitions if t.window.contains(sample))
    warnings = list(model.warnings)
    for transition in transitions:
        warnings.extend(transition.warnings)
    video, audio = [], []
    # ponytail: linear clip scan; add an interval index only if measured seek cost requires it.
    for track_index, track in enumerate(model.tracks):
        if not track.enabled:
            continue
        for segment_index, clip in enumerate(track.clips):
            linked = tuple(t for t in transitions if clip.id in (t.from_clip_id, t.to_clip_id))
            handle = any(t.kind == "crossfade" for t in linked)
            if not clip.visible or not (clip.timeline_range.contains(sample) or handle):
                continue
            local = sample - clip.timeline_range.start_us
            notes = list(clip.warnings)
            source = clip.source_range
            still = clip.kind in ("image", "photo", "sticker")
            source_time = source.start_us if still else clip.time_mapping._unclamped_us(local, source)
            bounds = clip.media_ref.available_range if handle and clip.media_ref else None
            bounds = bounds if bounds is not None else source
            if not handle and clip.media_ref and clip.media_ref.available_range is not None:
                available = clip.media_ref.available_range
                start = max(source.start_us, available.start_us)
                bounds = TimeRange(start, max(0, min(source.end_us, available.end_us) - start))
                if source.duration_us and not bounds.duration_us:
                    notes.append("source_range_unavailable")
            if not bounds.duration_us:
                source_time = None
                if clip.media_ref is not None and not still:
                    notes.append("source_range_empty")
            else:
                bounded = min(max(source_time, bounds.start_us), bounds.end_us - 1)
                if bounded != source_time:
                    notes.append("transition_handle_clamped" if handle else "source_time_clamped")
                source_time = bounded
            opacity, volume = clip.opacity, clip.audio.volume
            for transition in linked:
                if transition.kind not in ("fade", "crossfade"):
                    continue
                progress = (sample - transition.window.start_us) / transition.window.duration_us
                weight = 1 - progress if clip.id == transition.from_clip_id else progress
                opacity *= weight
                volume *= weight
            z = clip.render_index if clip.render_index is not None else track.render_index
            z = DEFAULT_RI.get(track.type, 0) if z is None else z
            item = SceneItem(clip, track.id, source_time, local, z, track_index, segment_index,
                             opacity, volume, tuple(t.id for t in linked), tuple(dict.fromkeys(notes)))
            warnings.extend(item.warnings)
            if clip.kind != "audio" and track.type != "audio":
                video.append(item)
            if clip.audio.enabled and not track.muted and clip.kind in ("audio", "video", "draft", "compound"):
                if clip.media_ref is None or clip.media_ref.has_audio is not False:
                    audio.append(item)
    def key(item: SceneItem) -> tuple[int, int, int]:
        return item.render_index, item.original_track_index, item.original_segment_index
    return ExpectedScene("active", frame, sample, tuple(sorted(video, key=key)),
                         tuple(sorted(audio, key=key)), transitions, tuple(dict.fromkeys(warnings)))
