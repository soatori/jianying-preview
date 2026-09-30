"""GStreamer/GES backend probe; run with the isolated gstreamer-bundle Python."""

from __future__ import annotations

import json
from pathlib import Path

from ..playback_backend import BackendUnavailable, GstGesBackend


MEDIA = Path(r"<素材绝对路径>\<clip>.MP4")


def main() -> int:
    if not MEDIA.exists():
        raise AssertionError(f"evaluation media is missing: {MEDIA}")
    backend = GstGesBackend()
    available, reason = backend.available()
    if not available:
        try:
            backend.open("eval", "probe", profile={"clips": []})
        except BackendUnavailable as exc:
            print(json.dumps({"ok": True, "skipped": True, "reason": str(exc)},
                             ensure_ascii=False))
            return 0
        raise AssertionError(f"backend reported unavailable but open did not fail: {reason}")
    profile = {"clips": [{
        "path": str(MEDIA), "track": 0, "kind": "video", "start_us": 0,
        "source_start_us": 3_566_666, "duration_us": 5_333_334,
    }]}
    backend.open("eval", "probe", profile=profile)
    samples = []
    try:
        for t_us in (0, 500_000, 3_000_000, 5_000_000):
            result = backend.render_at(t_us)
            if not result.get("ok") or result.get("pts_us") is None:
                raise AssertionError(f"no exact frame at {t_us}: {result}")
            samples.append({"requested_us": t_us, "pts_us": result["pts_us"],
                            "caps": result.get("caps")})
        backend.play()
        backend.pause()
        snapshot = backend.snapshot()
        if snapshot.get("phase") != "paused":
            raise AssertionError(f"pause did not settle backend: {snapshot}")
        forward = backend.render_at(0)["buffer"]
        backend.close()
        reverse_profile = {"clips": [{**profile["clips"][0], "reverse": True}]}
        backend.open("eval", "probe-reverse", profile=reverse_profile)
        reverse = backend.render_at(0)
        if not reverse.get("ok") or reverse.get("buffer") == forward:
            raise AssertionError("GES reverse did not produce a distinct source frame")
        backend.close()
        speed_profile = {"clips": [{**profile["clips"][0],
                                     "duration_us": 2_000_000, "speed": 2.0}]}
        backend.open("eval", "probe-speed", profile=speed_profile)
        speed = backend.render_at(1_000_000)
        if not speed.get("ok"):
            raise AssertionError(f"GES speed effect did not render: {speed}")
        print(json.dumps({"ok": True, "samples": samples, "snapshot": snapshot},
                         ensure_ascii=False))
        return 0
    finally:
        backend.close()


if __name__ == "__main__":
    raise SystemExit(main())
