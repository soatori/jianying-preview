"""Regression check for native-backend source paths in FrameDescriptor IR."""

from __future__ import annotations

import json
import os
import urllib.request

from ..playback_backend import clips_from_frame_ir


BASE = os.environ.get("JY_PREVIEW_TEST_BASE", "http://127.0.0.1:8765")


def main() -> int:
    url = (BASE + "/api/frame?draft=<草稿 id>&"
           "timeline=timeline-primary&t_us=0&window_us=20000000")
    with urllib.request.urlopen(url, timeout=300) as response:
        ir = json.load(response)["data"]
    videos = []

    def walk(layers):
        for layer in layers:
            media = layer.get("media") or {}
            if media.get("family") == "video" and media.get("exists"):
                videos.append(media.get("path_raw"))
            walk((layer.get("nest") or {}).get("layers") or [])

    walk(ir.get("layers") or [])
    if not videos or any(not path for path in videos):
        raise AssertionError("native backend cannot map IR media without path_raw")
    audio = [item.get("audio") or {} for item in ir.get("audio_labels") or []
             if (item.get("audio") or {}).get("exists")]
    if audio and any(not item.get("path_raw") for item in audio):
        raise AssertionError("audio IR is missing path_raw for native backend")
    clips = clips_from_frame_ir(ir)
    if not clips or not any(item["kind"] == "video" for item in clips):
        raise AssertionError("IR adapter produced no native video clips")
    if any(not item.get("path") for item in clips):
        raise AssertionError("IR adapter produced a clip without a local path")
    print(f"ok: IR exposes {len(videos)} video and {len(audio)} audio source paths")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
