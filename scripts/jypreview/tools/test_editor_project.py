"""Contract tests for the read-only editor-project normalizer (plan Task 1).

Runs offline: every structural promise is checked against synthetic timelines, and
the one thing synthetic data cannot prove -- that a project's visible clips match the
IR the browser already gets from ``/api/frame`` -- is checked against a real draft and
skipped when no corpus is present.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from ..config import Config
from ..model.content import TimelineContent
from ..model.editor_project import (TimelineAmbiguous, build_editor_project, scene_clips,
                                    select_timeline_entry)
from ..session import TimelineNotFound

US = 1_000_000


# -- synthetic draft fixture -------------------------------------------------
def _range(start: int, duration: int) -> dict:
    return {"start": int(start), "duration": int(duration)}


def _segment(ident: str, material_id: str, target: tuple[int, int], source: tuple[int, int] | None = None,
             **extra) -> dict:
    segment = {"id": ident, "material_id": material_id, "target_timerange": _range(*target)}
    if source is not None:
        segment["source_timerange"] = _range(*source)
    segment.update(extra)
    return segment


def _track(ident: str, track_type: str, segments: list[dict], **extra) -> dict:
    track = {"id": ident, "type": track_type, "segments": segments}
    track.update(extra)
    return track


def _video_material(ident: str, name: str, path: str) -> dict:
    return {"id": ident, "type": "video", "material_name": name, "path": path, "video_ratio": "16:9",
            "width": 1920.0, "height": 1080.0, "duration": 10 * US}


def _text_material(ident: str, text: str) -> dict:
    style = {
        "range": [0, len(text)], "size": 10.0,
        "fill": {"content": {"render_type": "solid", "solid": {"color": [1.0, 1.0, 1.0],
                                                              "alpha": 1.0}}},
        "strokes": [{"content": {"solid": {"color": [1.0, 0.0, 0.0]}}, "width": 0.05}],
        "shadows": [{"content": {"solid": {"color": [0.0, 0.0, 0.0]}}, "distance": 2.0, "angle": 45.0}],
    }
    return {"id": ident, "type": "text", "material_name": text, "content":
            json.dumps({"text": text, "styles": [style]}, ensure_ascii=False),
            "font_resource_id": "FONT-1", "font_title": "合成字体", "alignment": 1}


def _value(tracks: list[dict], materials: dict, *, duration: int, tid: str, fps: float = 30.0,
           canvas: tuple[int, int, str] = (1080, 1920, "9:16")) -> dict:
    return {
        "id": tid, "duration": duration, "fps": fps,
        "canvas_config": {"width": canvas[0], "height": canvas[1], "ratio": canvas[2]},
        "tracks": tracks, "materials": materials,
    }


class FakeSession:
    def __init__(self, config: Config):
        self.config = config
        self.registry = None
        self.font_index = None
        self.catalog = None

    def frame(self, content, meta, t_us, **kwargs):
        from ..model import framedesc

        return framedesc.build_frame(content, int(t_us), self.config, registry=None,
                                     font_index=None, catalog=None, effect_cache=None,
                                     install_fonts=None, probe_cache=None, **kwargs)


class FakeView:
    """Just enough ``DraftView`` for the normalizer: no disk, no DLL, no server."""

    def __init__(self, timelines: list[dict], values: dict, *, layout: str, did: str = "synthetic",
                 active: str | None = None, root: Path | None = None, config: Config | None = None,
                 sidecar: dict | None = None):
        self.timelines = timelines
        self._values = values
        self.layout = layout
        self.did = did
        self.name = did
        self.root = root or Path(tempfile.gettempdir()) / "jypreview-synthetic"
        self.active_timeline_id = active
        self.mirror = {"drift": False}
        self.session = FakeSession(config or _config())
        self._sidecar = sidecar or {}
        self._contents: dict[str, tuple[TimelineContent, dict]] = {}

    def resolve_timeline(self, selector: str) -> dict:
        text = str(selector)
        matches = [item for item in self.timelines
                   if str(item["id"]).upper() == text.upper() or str(item.get("name")) == text]
        if len(matches) != 1:
            raise TimelineNotFound(text, [str(item["id"]) for item in self.timelines])
        return matches[0]

    def content(self, tid: str) -> tuple[TimelineContent, dict]:
        entry = next((item for item in self.timelines if str(item["id"]).upper() == str(tid).upper()), None)
        if entry is None:
            raise TimelineNotFound(tid, [str(item["id"]) for item in self.timelines])
        cached = self._contents.get(str(tid).upper())
        if cached:
            return cached
        meta = {"src": entry.get("primary") or str(self.root / "draft_content.json"),
                "sidecar": {**{"src_sha256": f"sha-{entry['id']}"}, **self._sidecar},
                "tid": tid, "layout": self.layout}
        content = TimelineContent.build(self._values[str(tid).upper()], meta=meta)
        self._contents[str(tid).upper()] = (content, meta)
        return self._contents[str(tid).upper()]

    def frame(self, tid: str, t_us: int, ratio: str | None = None,
              window: tuple[int, int] | None = None) -> dict:
        content, meta = self.content(tid)
        entry = next((item for item in self.timelines if str(item["id"]).upper() == str(tid).upper()), {})
        return self.session.frame(content, meta, t_us, draft_root=self.root, did=self.did,
                                  timeline_info={"layout": self.layout, "name": entry.get("name"),
                                                 "encoding": entry.get("encoding"),
                                                 "content_rel": entry.get("primary"),
                                                 "mirror_drift": False, "replica_errors": []},
                                  ratio=ratio, window=window)

    def describe(self) -> dict:
        return {"did": self.did, "name": self.name, "layout": self.layout, "path": str(self.root),
                "active_timeline_id": self.active_timeline_id, "active_evidence": [],
                "mirror_drift": self.mirror,
                "timelines": [{"id": item["id"], "name": item.get("name"),
                               "deleted": item.get("deleted"),
                               "active": item["id"] == self.active_timeline_id,
                               "duration_us": item.get("duration_us")} for item in self.timelines],
                "cache": {}}


def _config() -> Config:
    root = Path(tempfile.gettempdir()) / "jypreview-editor-test"
    root.mkdir(parents=True, exist_ok=True)
    return Config(drafts_root=root, jianying_root=root, install_root=root, user_state_dir=root)


def _entry(tid: str, name: str, *, primary: str | None = None, duration: int = 4 * US,
           deleted: bool = False) -> dict:
    return {"id": tid, "name": name, "primary": primary, "duration_us": duration,
            "deleted": deleted, "encoding": "plaintext", "replicas": [], "replica_errors": []}


def _single_timeline_view(**kwargs) -> FakeView:
    tid = "T-MAIN"
    materials = {"videos": [_video_material("M-V1", "a.mp4", "missing/a.mp4")]}
    tracks = [_track("K-VIDEO", "video", [
        _segment("S-1", "M-V1", (0, 2 * US), (0, 2 * US)),
        _segment("S-2", "M-V1", (2 * US, 2 * US), (2 * US, 2 * US)),
    ])]
    values = {tid: _value(tracks, materials, duration=4 * US, tid=tid)}
    return FakeView([_entry(tid, "时间线1")], values, **kwargs)


# -- assertions ------------------------------------------------------------
def test_schema_is_read_only() -> None:
    project = build_editor_project(_single_timeline_view(layout="legacy-single", active="T-MAIN"), "T-MAIN")
    assert project["schema"] == "jypreview/editor-project@1", project["schema"]
    assert project["read_only"] is True
    assert project["draft"]["layout"] == "legacy-single"
    assert project["timeline"]["id"] == "T-MAIN"
    assert project["canvas"]["width"] == 1080 and project["canvas"]["height"] == 1920
    assert project["canvas"]["ratio"] == "9:16", project["canvas"]
    assert project["fps"] == 30.0
    assert project["duration_us"] == 4 * US
    assert "write" not in json.dumps(sorted(project.keys())).lower()


def test_all_microsecond_fields_are_integers() -> None:
    project = build_editor_project(_single_timeline_view(layout="legacy-single", active="T-MAIN"), None)
    offenders: list[str] = []

    def walk(node, path):
        if isinstance(node, dict):
            for key, value in node.items():
                if key.endswith("_us") and value is not None and not isinstance(value, int):
                    offenders.append(f"{path}.{key}={value!r}")
                walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{path}[{index}]")

    walk(project, "project")
    assert not offenders, offenders


def test_half_open_spans_and_scene_seams() -> None:
    view = _single_timeline_view(layout="legacy-single", active="T-MAIN")
    project = build_editor_project(view, None)
    clips = {clip["clip_id"]: clip for clip in project["clips"]}
    first, second = clips["S-1"], clips["S-2"]
    assert (first["target_start_us"], first["target_end_us"]) == (0, 2 * US)
    assert (second["target_start_us"], second["target_end_us"]) == (2 * US, 4 * US)
    assert first["source_start_us"] == 0 and second["source_start_us"] == 2 * US
    # Adjacent clips must never both be live at the seam.
    assert [clip["clip_id"] for clip in scene_clips(project, 2 * US)] == ["S-2"]
    assert [clip["clip_id"] for clip in scene_clips(project, 2 * US - 1)] == ["S-1"]
    assert scene_clips(project, 4 * US) == []


def test_explicit_timeline_selection_beats_active() -> None:
    tid_a, tid_b = "T-A", "T-B"
    materials = {"videos": [_video_material("M-V1", "a.mp4", "missing/a.mp4")]}
    values = {
        tid_a: _value([_track("K-A", "video", [_segment("S-A", "M-V1", (0, 2 * US), (0, 2 * US))])],
                      materials, duration=2 * US, tid=tid_a),
        tid_b: _value([_track("K-B", "video", [_segment("S-B", "M-V1", (0, 3 * US), (0, 3 * US))])],
                      materials, duration=3 * US, tid=tid_b),
    }
    view = FakeView([_entry(tid_a, "时间线A"), _entry(tid_b, "时间线B")], values,
                    layout="multi-timeline", active=tid_a)
    assert build_editor_project(view, tid_b)["timeline"]["id"] == tid_b
    assert build_editor_project(view, "active")["timeline"]["id"] == tid_a
    assert build_editor_project(view, "时间线B")["timeline"]["id"] == tid_b
    for selector in ("T-C", "不存在的名字"):
        try:
            build_editor_project(view, selector)
        except TimelineNotFound:
            continue
        raise AssertionError(f"{selector} should not resolve")


def test_ambiguous_active_timeline_is_refused() -> None:
    view = _single_timeline_view(layout="multi-timeline", active=None)
    assert select_timeline_entry(view, "T-MAIN")["id"] == "T-MAIN"
    try:
        select_timeline_entry(view, None)
    except TimelineAmbiguous as exc:
        assert "T-MAIN" in exc.available, exc.available
    else:
        raise AssertionError("an unprovable active timeline must not be guessed")


def test_hybrid_reports_nested_source_identity() -> None:
    nested = str(Path("Timelines") / "T-HYBRID" / "draft_content.json")
    tid = "T-HYBRID"
    materials = {"videos": [_video_material("M-V1", "a.mp4", "missing/a.mp4")]}
    values = {tid: _value([_track("K-1", "video", [_segment("S-1", "M-V1", (0, US), (0, US))])],
                          materials, duration=US, tid=tid)}
    view = FakeView([_entry(tid, "激活时间线", primary=nested)], values, layout="hybrid", active=tid,
                    sidecar={"src_sha256": "abc123", "encoding": "jianying-dll"})
    project = build_editor_project(view, None)
    assert project["timeline"]["content_file"] == nested.replace("\\", "/"), project["timeline"]
    assert project["timeline"]["source_sha256"] == "abc123"
    assert project["timeline"]["active"] is True
    assert project["draft"]["layout"] == "hybrid"


def test_invisible_segments_are_kept_but_never_scene() -> None:
    tid = "T-1"
    materials = {"videos": [_video_material("M-V1", "a.mp4", "missing/a.mp4")]}
    tracks = [_track("K-1", "video", [
        _segment("S-HIDDEN", "M-V1", (0, US), (0, US), visible=False),
        _segment("S-SHOWN", "M-V1", (0, US), (0, US)),
    ])]
    values = {tid: _value(tracks, materials, duration=US, tid=tid)}
    project = build_editor_project(FakeView([_entry(tid, "时间线1")], values,
                                            layout="legacy-single", active=tid), None)
    clips = {clip["clip_id"]: clip for clip in project["clips"]}
    assert clips["S-HIDDEN"]["visible"] is False and clips["S-SHOWN"]["visible"] is True
    assert [clip["clip_id"] for clip in scene_clips(project, 0)] == ["S-SHOWN"]


def test_speed_and_reverse_survive_normalization() -> None:
    tid = "T-1"
    materials = {"videos": [_video_material("M-V1", "a.mp4", "missing/a.mp4")]}
    tracks = [_track("K-1", "video", [
        _segment("S-SLOW", "M-V1", (0, 2 * US), (5 * US, US), speed=0.5),
        _segment("S-REV", "M-V1", (2 * US, US), (0, US), reverse=True),
    ])]
    values = {tid: _value(tracks, materials, duration=3 * US, tid=tid)}
    project = build_editor_project(FakeView([_entry(tid, "时间线1")], values,
                                            layout="legacy-single", active=tid), None)
    clips = {clip["clip_id"]: clip for clip in project["clips"]}
    assert clips["S-SLOW"]["speed"] == 0.5 and clips["S-SLOW"]["reverse"] is False
    assert clips["S-SLOW"]["source_start_us"] == 5 * US
    assert clips["S-REV"]["reverse"] is True and clips["S-REV"]["speed"] == 1.0
    assert clips["S-REV"]["warnings"], "a reversed clip needs an explicit support note"


def test_render_index_drives_a_stable_paint_order() -> None:
    tid = "T-1"
    materials = {"videos": [_video_material("M-V1", "a.mp4", "missing/a.mp4")]}
    tracks = [
        _track("K-BOTTOM", "video", [_segment("S-BOTTOM", "M-V1", (0, US), (0, US))]),
        _track("K-TOP", "video", [_segment("S-TOP", "M-V1", (0, US), (0, US)),
                                  _segment("S-TOP2", "M-V1", (0, US), (0, US), render_index=0)],
                 render_index=20),
    ]
    values = {tid: _value(tracks, materials, duration=US, tid=tid)}
    project = build_editor_project(FakeView([_entry(tid, "时间线1")], values,
                                            layout="legacy-single", active=tid), None)
    order = [clip["clip_id"] for clip in sorted(project["clips"], key=lambda c: c["z_index"])]
    assert order == ["S-BOTTOM", "S-TOP2", "S-TOP"], order
    assert len({clip["z_index"] for clip in project["clips"]}) == len(project["clips"])


def test_text_styles_are_normalized() -> None:
    tid = "T-1"
    materials = {"texts": [_text_material("M-T1", "标题文本")]}
    clip = {"transform": {"x": 0.0, "y": -0.8, "z": 0.0}, "scale": {"x": 1.0, "y": 1.0},
            "rotation": 0.0, "alpha": 1.0}
    tracks = [_track("K-TEXT", "text", [_segment("S-T1", "M-T1", (0, 2 * US), visible=True)],
                     flag=1)]
    tracks[0]["segments"][0]["clip"] = clip
    values = {tid: _value(tracks, materials, duration=2 * US, tid=tid)}
    project = build_editor_project(FakeView([_entry(tid, "时间线1")], values,
                                            layout="legacy-single", active=tid), None)
    node = project["clips"][0]
    assert node["kind"] == "text" and node["text"]["text"] == "标题文本"
    run = node["text"]["runs"][0]
    assert run["strokes"] and run["shadows"], run
    assert run["fill"]["css"] == "#ffffff", run["fill"]
    assert node["text"]["box"]["em_px"] > 0 and node["rect"]["cy_px"] > 1920 * 0.5
    assert node["text"]["font"]["source"] == "system_stack", node["text"]["font"]


def test_missing_media_keeps_the_timeline_navigable() -> None:
    view = _single_timeline_view(layout="legacy-single", active="T-MAIN")
    project = build_editor_project(view, None)
    clip = project["clips"][0]
    assert clip["asset_id"] and clip["asset"]["exists"] is False
    assert clip["asset"]["placeholder_reason"] == "missing"
    assert clip["warnings"], "a missing file must be reported on the clip"
    assert any("missing" in note.lower() or "media" in note.lower() for note in project["warnings"])
    assert scene_clips(project, US) and scene_clips(project, US)[0]["asset"]["exists"] is False


def test_assets_are_deduplicated_by_material() -> None:
    view = _single_timeline_view(layout="legacy-single", active="T-MAIN")
    project = build_editor_project(view, None)
    assert len(project["assets"]) == 1, project["assets"]
    assert {clip["asset_id"] for clip in project["clips"]} == {project["assets"][0]["asset_id"]}


def test_unsupported_features_become_warnings() -> None:
    tid = "T-1"
    materials = {"videos": [_video_material("M-V1", "a.mp4", "missing/a.mp4")],
                 "masks": [{"id": "M-MASK", "type": "linear", "name": "线性蒙版"}]}
    tracks = [_track("K-1", "video", [_segment("S-1", "M-V1", (0, US), (0, US))])]
    values = {tid: _value(tracks, materials, duration=US, tid=tid)}
    project = build_editor_project(FakeView([_entry(tid, "时间线1")], values,
                                            layout="legacy-single", active=tid), None)
    assert any("masks" in note for note in project["warnings"]), project["warnings"]


def test_track_flags_are_normalized() -> None:
    tid = "T-1"
    materials = {"videos": [_video_material("M-V1", "a.mp4", "missing/a.mp4")],
                 "audios": [{"id": "M-A1", "type": "audio", "material_name": "bgm.mp3",
                             "path": "missing/bgm.mp3", "duration": 5 * US}]}
    tracks = [
        _track("K-VIDEO", "video", [_segment("S-1", "M-V1", (0, US), (0, US))], is_hidden=True),
        _track("K-AUDIO", "audio", [_segment("S-A1", "M-A1", (0, US), (0, US))], muted=True),
    ]
    values = {tid: _value(tracks, materials, duration=US, tid=tid)}
    project = build_editor_project(FakeView([_entry(tid, "时间线1")], values,
                                            layout="legacy-single", active=tid), None)
    tracks_out = {track["id"]: track for track in project["tracks"]}
    assert tracks_out["K-VIDEO"]["group"] == "visual" and tracks_out["K-VIDEO"]["visible"] is False
    assert tracks_out["K-AUDIO"]["group"] == "audio" and tracks_out["K-AUDIO"]["muted"] is True
    assert tracks_out["K-AUDIO"]["lane"] != tracks_out["K-VIDEO"]["lane"]
    audio = next(clip for clip in project["clips"] if clip["kind"] == "audio")
    assert audio["track_id"] == "K-AUDIO" and audio["muted"] is True and audio["visible"] is True
    assert audio["asset"]["name"] == "bgm.mp3" and audio["asset"]["exists"] is False
    # A hidden video track leaves the visual scene empty; audio never joins it.
    assert [clip["clip_id"] for clip in scene_clips(project, 0)] == []
    assert [clip["clip_id"] for clip in scene_clips(project, 0, kinds=("audio",))] == ["S-A1"]


def test_empty_timeline_produces_a_valid_empty_project() -> None:
    tid = "T-EMPTY"
    values = {tid: _value([], {}, duration=0, tid=tid)}
    project = build_editor_project(FakeView([_entry(tid, "空", duration=0)], values,
                                            layout="legacy-single", active=tid), None)
    assert project["clips"] == [] and project["tracks"] == [] and project["assets"] == []
    assert project["duration_us"] == 0


CORPUS_DRAFTS = ("YASHIDA 9月24日", "6月7日 (全顺)", "9月28日")


def test_scene_parity_with_frame_ir_on_real_drafts() -> list[str]:
    """The one promise synthetics cannot make: what the project says is on screen at
    time ``t`` must be exactly what ``/api/frame`` already renders at ``t``."""
    from ..session import PreviewSession

    config = Config()
    if config.drafts_root is None or not Path(config.drafts_root).is_dir():
        return ["corpus absent: real-draft parity not exercised"]
    session = PreviewSession(config)
    notes: list[str] = []
    checked = 0
    for name in CORPUS_DRAFTS:
        try:
            view = session.view(name)
            tid = view.active_timeline_id or (view.timelines[0]["id"] if view.timelines else None)
            if not tid:
                continue
            project = build_editor_project(view, tid)
        except Exception as exc:
            notes.append(f"{name}: skipped ({exc.__class__.__name__}: {exc})")
            continue
        duration = int(view.content(tid)[0].duration_us or 0)
        if duration <= 0:
            notes.append(f"{name}: zero duration, no samples")
            continue
        for step in range(5):
            stamp = int(duration * (step + 0.5) / 5)
            ir = view.frame(tid, stamp)
            ir_ids = [layer["layer_id"] for layer in ir["layers"]]
            mine = [clip["clip_id"] for clip in scene_clips(project, stamp, kinds=None)
                    if clip["kind"] != "audio"]
            if ir_ids != mine:
                raise AssertionError(f"{name}@{stamp}us IR={ir_ids} project={mine}")
        checked += 1
        for clip in project["clips"]:
            for key in ("target_start_us", "target_end_us", "source_start_us"):
                value = clip.get(key)
                if value is not None and not isinstance(value, int):
                    raise AssertionError(f"{name}: {clip['clip_id']}.{key} is {value!r}")
    if checked == 0:
        notes.append(f"no corpus draft could be opened from {config.drafts_root}")
    return notes


def main() -> int:
    for key in ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        os.environ.pop(key, None)
    cases = [(name, obj) for name, obj in sorted(globals().items())
             if name.startswith("test_") and callable(obj)]
    order = ["test_schema_is_read_only", "test_all_microsecond_fields_are_integers",
             "test_half_open_spans_and_scene_seams", "test_explicit_timeline_selection_beats_active",
             "test_ambiguous_active_timeline_is_refused", "test_hybrid_reports_nested_source_identity",
             "test_invisible_segments_are_kept_but_never_scene",
             "test_speed_and_reverse_survive_normalization",
             "test_render_index_drives_a_stable_paint_order", "test_text_styles_are_normalized",
             "test_missing_media_keeps_the_timeline_navigable",
             "test_assets_are_deduplicated_by_material", "test_unsupported_features_become_warnings",
             "test_track_flags_are_normalized", "test_empty_timeline_produces_a_valid_empty_project",
             "test_scene_parity_with_frame_ir_on_real_drafts"]
    assert set(order) == {name for name, _ in cases}, set(order) ^ {name for name, _ in cases}
    failures: list[str] = []
    for name in order:
        try:
            notes = globals()[name]() or []
            for note in notes:
                print(f"note {name}: {note}")
            print(f"ok   {name}")
        except Exception as exc:
            failures.append(f"{name}: {exc.__class__.__name__}: {exc}")
            print(f"FAIL {name}: {exc.__class__.__name__}: {exc}")
    print(json.dumps({"ok": not failures, "cases": len(order), "failed": failures},
                     ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
