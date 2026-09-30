"""Playback backend contract and the optional GStreamer/GES implementation.

The browser backend remains in the UI during migration.  ``GstGesBackend`` is
loaded lazily so the existing read-only preview service still starts on a
machine that does not have the GStreamer bundle installed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class BackendCapabilities:
    name: str
    exact_frame: bool = False
    audio: bool = False
    transitions: bool = False
    effects: tuple[str, ...] = field(default_factory=tuple)


class PlaybackBackend(Protocol):
    @property
    def capabilities(self) -> BackendCapabilities: ...

    def open(self, draft: str, timeline: str, *, profile: dict[str, Any] | None = None) -> None: ...

    def close(self) -> None: ...

    def seek(self, t_us: int) -> None: ...

    def play(self, rate: float = 1.0) -> None: ...

    def pause(self) -> None: ...

    def render_at(self, t_us: int) -> dict[str, Any]: ...

    def snapshot(self) -> dict[str, Any]: ...


def clips_from_frame_ir(ir: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert FrameDescriptor media entries into the native clip profile.

    Window IR can contain the same nested child sampled at several inner times;
    exact identity/range de-duplication keeps the GES timeline from receiving
    duplicate sources while preserving repeated compound instances.
    """

    clips: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()

    def mapped_range(time: dict[str, Any], parents: tuple[dict[str, Any], ...]) -> tuple[int, int]:
        start = float(time.get("target_start_us") or 0)
        duration = float(time.get("target_duration_us") or time.get("duration_us") or 0)
        for parent in reversed(parents):
            speed = float(parent.get("speed") or 1.0) or 1.0
            start = float(parent.get("target_start_us") or 0) + \
                (start - float(parent.get("source_start_us") or 0)) / speed
            duration = duration / abs(speed)
        return max(0, round(start)), max(0, round(duration))

    def add_media(media: dict[str, Any], time: dict[str, Any], track: int,
                  parents: tuple[dict[str, Any], ...]) -> None:
        raw_path = media.get("path_raw")
        resolved_path = media.get("path")
        path = raw_path if raw_path and Path(str(raw_path)).exists() else resolved_path or raw_path
        if not media.get("exists") or not path:
            return
        family = str(media.get("family") or "")
        kind = "audio" if family == "audio" else "video"
        start_us, duration_us = mapped_range(time, parents)
        key = (kind, str(path), track, start_us, duration_us,
               int(time.get("source_start_us") or 0), bool(time.get("reverse")))
        if key in seen:
            return
        seen.add(key)
        clips.append({"path": str(path), "track": track, "kind": kind,
                      "start_us": start_us, "duration_us": duration_us,
                      "source_start_us": int(time.get("source_start_us") or 0),
                      "source_duration_us": int(time.get("source_duration_us") or 0),
                      "speed": float(time.get("speed") or 1.0),
                      "reverse": bool(time.get("reverse")),
                      "volume": media.get("volume")})

    def walk(layers: list[dict[str, Any]], parents: tuple[dict[str, Any], ...] = ()) -> None:
        for layer in layers:
            time = layer.get("time") or {}
            track = int(((layer.get("track") or {}).get("index")) or 0)
            media = layer.get("media") or {}
            if media:
                add_media(media, time, track, parents)
            nested = (layer.get("nest") or {}).get("layers") or []
            if nested:
                walk(nested, parents + (time,))

    walk(ir.get("layers") or [])
    for item in ir.get("audio_labels") or []:
        audio = item.get("audio") or {}
        if not audio:
            continue
        audio = {**audio, "family": "audio", "volume": item.get("volume")}
        add_media(audio, audio, int(item.get("track_index") or 0), ())
    # Window IR may sample one compound child more than once.  Merge only
    # overlapping copies with the same source range; separated repeated
    # instances remain independent timeline clips.
    merged: list[dict[str, Any]] = []
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for clip in clips:
        key = (clip["kind"], clip["path"], clip["track"],
               clip["source_start_us"], clip["source_duration_us"], clip["speed"],
               clip["reverse"])
        groups.setdefault(key, []).append(clip)
    for group in groups.values():
        for clip in sorted(group, key=lambda item: item["start_us"]):
            if not merged or merged[-1].get("_merge_key") != (
                    clip["kind"], clip["path"], clip["track"], clip["source_start_us"],
                    clip["source_duration_us"], clip["speed"], clip["reverse"]):
                merged.append({**clip, "_merge_key": (
                    clip["kind"], clip["path"], clip["track"], clip["source_start_us"],
                    clip["source_duration_us"], clip["speed"], clip["reverse"])})
                continue
            current = merged[-1]
            current_end = current["start_us"] + current["duration_us"]
            clip_end = clip["start_us"] + clip["duration_us"]
            if clip["start_us"] < current_end:
                current["duration_us"] = max(current_end, clip_end) - current["start_us"]
            else:
                merged.append({**clip, "_merge_key": current["_merge_key"]})
    for clip in merged:
        clip.pop("_merge_key", None)
    return merged


class BackendUnavailable(RuntimeError):
    """Raised when an optional native backend is not installed."""


class GstGesBackend:
    """Small GES-backed timeline player used by the native backend probe.

    ``profile["clips"]`` is intentionally a normalized adapter input.  The
    Jianying IR adapter can be tested independently from GES and can later add
    transitions/effects without leaking GObject objects into the HTTP API.
    """

    def __init__(self) -> None:
        self._Gst = None
        self._GES = None
        self._pipeline = None
        self._timeline = None
        self._video_sink = None
        self._audio_sink = None
        self._assets: dict[str, Any] = {}
        self._layers: list[Any] = []
        self._t_us = 0
        self._rate = 1.0
        self._phase = "idle"
        self._error: str | None = None
        self._draft = None
        self._timeline_id = None

    @property
    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            name="gstreamer-ges",
            exact_frame=True,
            audio=True,
            transitions=True,
            effects=("native-video", "native-audio", "placeholder"),
        )

    @staticmethod
    def available() -> tuple[bool, str]:
        try:
            import gi  # type: ignore

            gi.require_version("Gst", "1.0")
            gi.require_version("GES", "1.0")
            from gi.repository import Gst, GES  # type: ignore

            Gst.init(None)
            GES.init()
            return True, f"GStreamer {Gst.version_string()} / GES available"
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)

    def _load_gi(self) -> tuple[Any, Any]:
        if self._Gst is not None and self._GES is not None:
            return self._Gst, self._GES
        try:
            import gi  # type: ignore

            gi.require_version("Gst", "1.0")
            gi.require_version("GES", "1.0")
            from gi.repository import Gst, GES  # type: ignore

            Gst.init(None)
            GES.init()
        except Exception as exc:  # noqa: BLE001
            raise BackendUnavailable(
                "GStreamer/GES Python bindings are unavailable; install gstreamer-bundle"
            ) from exc
        self._Gst, self._GES = Gst, GES
        return Gst, GES

    def open(self, draft: str, timeline: str, *, profile: dict[str, Any] | None = None) -> None:
        self.close()
        Gst, GES = self._load_gi()
        profile = profile or {}
        clips = profile.get("clips") or []
        if not clips:
            raise ValueError("GstGesBackend requires normalized profile['clips']")
        self._draft, self._timeline_id = draft, timeline
        self._layers = []
        timeline_obj = GES.Timeline.new_audio_video()
        for clip_index, item in enumerate(clips):
            path = str(item.get("path") or "")
            if not path:
                raise ValueError("GStreamer clip is missing path")
            track = int(item.get("track", 0) or 0)
            # One layer per normalized clip avoids illegal overlaps inside a
            # GESLayer.  The IR adapter already carries z/track order, and a
            # later pass can assign explicit layer priorities for composites.
            layer = GES.Layer.new()
            try:
                layer.set_priority(clip_index)
            except Exception:
                pass
            if not timeline_obj.add_layer(layer):
                raise RuntimeError(f"failed to add GES layer {track}")
            self._layers.append(layer)
            uri = path if "://" in path else Gst.filename_to_uri(str(Path(path)))
            asset = self._assets.get(uri)
            if asset is None:
                asset = GES.UriClipAsset.request_sync(uri)
                if asset is None:
                    raise RuntimeError(f"failed to load GES asset: {path}")
                self._assets[uri] = asset
            kind = str(item.get("kind") or "av").lower()
            track_types = GES.TrackType.VIDEO | GES.TrackType.AUDIO
            if kind == "video":
                track_types = GES.TrackType.VIDEO
            elif kind == "audio":
                track_types = GES.TrackType.AUDIO
            start_ns = int(item.get("start_us", 0) or 0) * 1000
            inpoint_ns = int(item.get("source_start_us", 0) or 0) * 1000
            duration_ns = int(item.get("duration_us", 0) or 0) * 1000
            clip = layer.add_asset(asset, start_ns, inpoint_ns, duration_ns, track_types)
            if clip is None:
                raise RuntimeError(f"failed to add GES clip {clip_index}: {path} "
                                   f"start={start_ns} in={inpoint_ns} duration={duration_ns}")
            if bool(item.get("reverse")):
                try:
                    clip.set_child_property("reverse", True)
                except Exception as exc:  # noqa: BLE001
                    raise NotImplementedError("GES reverse property is unavailable") from exc
            speed = float(item.get("speed", 1.0) or 1.0)
            if abs(speed - 1.0) > 1e-6:
                try:
                    effect_name = "videorate" if kind == "video" else "pitch"
                    effect = GES.Effect.new(effect_name)
                    if effect is None or not clip.add_top_effect(effect, -1):
                        raise RuntimeError(f"failed to add {effect_name} time effect")
                    if not effect.set_child_property("rate", speed):
                        raise RuntimeError(f"failed to set {effect_name}.rate")
                    if kind == "audio":
                        # Keep the audio timeline rate aligned while preserving
                        # pitch as far as the installed GStreamer plugin allows.
                        effect.set_child_property("tempo", speed)
                except Exception as exc:  # noqa: BLE001
                    raise NotImplementedError("GES speed time-effect is unavailable") from exc
        pipeline = GES.Pipeline.new()
        pipeline.set_timeline(timeline_obj)
        pipeline.set_mode(GES.PipelineFlags.FULL_PREVIEW)
        video_sink = Gst.ElementFactory.make("appsink", "jypreview-video-sink")
        audio_sink_name = str(profile.get("audio_sink") or "fakesink")
        audio_sink = Gst.ElementFactory.make(audio_sink_name, "jypreview-audio-sink")
        if video_sink is None or audio_sink is None:
            raise RuntimeError("GStreamer appsink/fakesink is unavailable")
        video_sink.set_property("sync", bool(profile.get("realtime", False)))
        video_sink.set_property("max-buffers", 2)
        video_sink.set_property("drop", True)
        video_sink.set_property("emit-signals", False)
        video_sink.set_property("caps", Gst.Caps.from_string("video/x-raw,format=RGBA"))
        audio_sink.set_property("sync", bool(profile.get("realtime", False)))
        pipeline.set_property("video-sink", video_sink)
        pipeline.set_property("audio-sink", audio_sink)
        state = pipeline.set_state(Gst.State.PAUSED)
        if state == Gst.StateChangeReturn.FAILURE:
            pipeline.set_state(Gst.State.NULL)
            raise RuntimeError("GStreamer pipeline failed to enter PLAYING")
        self._pipeline, self._timeline = pipeline, timeline_obj
        self._video_sink, self._audio_sink = video_sink, audio_sink
        self._phase, self._error, self._t_us = "ready", None, 0

    def _seek_ns(self, t_us: int) -> bool:
        Gst = self._Gst
        return bool(self._pipeline.seek_simple(
            Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.ACCURATE, int(t_us) * 1000
        ))

    def seek(self, t_us: int) -> None:
        if self._pipeline is None:
            raise RuntimeError("GStreamer backend is not open")
        self._phase = "seeking"
        if not self._seek_ns(int(t_us)):
            self._phase = "error"
            self._error = f"GStreamer seek failed at {t_us}us"
            raise RuntimeError(self._error)
        self._t_us = max(0, int(t_us))
        self._phase = "paused"

    def play(self, rate: float = 1.0) -> None:
        if self._pipeline is None:
            raise RuntimeError("GStreamer backend is not open")
        self._rate = float(rate or 1.0)
        if abs(self._rate - 1.0) > 1e-6:
            raise NotImplementedError("GES rate control is not enabled in v1")
        Gst = self._Gst
        if self._pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
            self._phase = "error"
            self._error = "GStreamer failed to enter PLAYING"
            raise RuntimeError(self._error)
        self._phase = "playing"

    def pause(self) -> None:
        if self._pipeline is None:
            return
        Gst = self._Gst
        self._pipeline.set_state(Gst.State.PAUSED)
        self._phase = "paused"

    def render_at(self, t_us: int) -> dict[str, Any]:
        if self._pipeline is None or self._video_sink is None:
            raise RuntimeError("GStreamer backend is not open")
        # Exact rendering is a paused/preroll operation.  Leaving the pipeline
        # PLAYING while issuing several random seeks lets it reach EOS between
        # requests and makes the next seek look like a backend failure.
        self._pipeline.set_state(self._Gst.State.PAUSED)
        self._pipeline.get_state(3_000_000_000)
        while self._video_sink.emit("try-pull-sample", 0) is not None:
            pass
        self._phase = "seeking"
        if not self._seek_ns(int(t_us)):
            self._phase = "error"
            self._error = f"GStreamer seek failed at {t_us}us"
            raise RuntimeError(self._error)
        self._t_us = max(0, int(t_us))
        self._pipeline.set_state(self._Gst.State.PLAYING)
        sample = self._video_sink.emit("try-pull-sample", 3_000_000_000)
        self._pipeline.set_state(self._Gst.State.PAUSED)
        if sample is None:
            self._phase = "buffering"
            return {"ok": False, "phase": self._phase, "t_us": self._t_us,
                    "reason": "no video sample before timeout"}
        buffer = sample.get_buffer()
        caps = sample.get_caps()
        raw = buffer.extract_dup(0, buffer.get_size())
        structure = caps.get_structure(0)
        pts_us = None if buffer.pts == self._Gst.CLOCK_TIME_NONE else int(buffer.pts // 1000)
        if pts_us is not None and abs(pts_us - int(t_us)) > 100_000:
            self._phase = "buffering"
            return {"ok": False, "phase": self._phase, "t_us": int(t_us),
                    "pts_us": pts_us, "reason": "stale GStreamer sample after seek"}
        self._t_us = int(t_us)
        self._phase = "paused"
        return {"ok": True, "phase": self._phase, "t_us": self._t_us,
                "pts_us": pts_us, "duration_us": int(buffer.duration // 1000)
                if buffer.duration != self._Gst.CLOCK_TIME_NONE else None,
                "caps": caps.to_string(), "width": int(structure.get_value("width")),
                "height": int(structure.get_value("height")), "format": str(structure.get_value("format")),
                "buffer": raw}

    def pull_frame(self, timeout_ms: int = 100) -> dict[str, Any] | None:
        """Pull the next frame from a PLAYING pipeline for a multipart stream."""
        if self._pipeline is None or self._video_sink is None:
            raise RuntimeError("GStreamer backend is not open")
        if self._phase != "playing":
            return None
        sample = self._video_sink.emit("try-pull-sample", max(0, int(timeout_ms)) * 1_000_000)
        if sample is None:
            return None
        buffer = sample.get_buffer()
        caps = sample.get_caps()
        structure = caps.get_structure(0)
        pts_us = None if buffer.pts == self._Gst.CLOCK_TIME_NONE else int(buffer.pts // 1000)
        self._t_us = pts_us if pts_us is not None else self._t_us
        return {"ok": True, "pts_us": pts_us, "caps": caps.to_string(),
                "width": int(structure.get_value("width")),
                "height": int(structure.get_value("height")),
                "format": str(structure.get_value("format")),
                "buffer": buffer.extract_dup(0, buffer.get_size())}

    def snapshot(self) -> dict[str, Any]:
        return {"backend": self.capabilities.name, "phase": self._phase,
                "draft": self._draft, "timeline": self._timeline_id,
                "t_us": self._t_us, "rate": self._rate, "error": self._error,
                "open": self._pipeline is not None}

    def close(self) -> None:
        if self._pipeline is not None and self._Gst is not None:
            self._pipeline.set_state(self._Gst.State.NULL)
        self._pipeline = self._timeline = None
        self._video_sink = self._audio_sink = None
        self._layers = []
        self._phase = "idle"
        self._t_us = 0
