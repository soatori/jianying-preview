"""Verify *playback*, not instants.

``shot``/``what-at`` are point queries: they cannot tell you whether an upper track keeps
rolling, whether a cut actually switched, or whether a subtitle appeared on time. This
drives the real preview page in a headless browser, samples ``window.__snapshot()`` -- which
reads the DOM layer pool, i.e. what a viewer would actually see -- and compares every sample
against a point query for the same microsecond.

    python -m jypreview.tools.audit_playback "draft-primary" --seconds 24
    python -m jypreview.tools.audit_playback "draft-audio" --seconds 16 --start 19

Exit status 2 means the page disagreed with the draft at least once.

Two readings that look like failures but are not:

* ``实时率`` is ``(last tUs - first tUs) / wall``. A draft shorter than ``--seconds`` stops at
  its end, which deflates the ratio -- check ``duration_us`` from ``/api/timelines`` first.
* A draft whose ``duration_us`` is 0 is an empty timeline; a pool of 0 nodes is correct.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

# Some environments export an outbound proxy that also swallows 127.0.0.1 (answering 502);
# both urllib and the CDP client honour it, so every local call fails until it is dropped.
for _key in ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
    os.environ.pop(_key, None)

SAMPLE_S = 0.25
DRIFT_TOL_S = 0.3
FROZEN_S = 0.05


def _get(base: str, path: str, **query):
    url = base + path + ("?" + urllib.parse.urlencode(query) if query else "")
    with urllib.request.urlopen(url, timeout=300) as response:
        return json.load(response)["data"]


def _flatten(layers):
    out = []
    for layer in layers:
        nested = (layer.get("nest") or {}).get("layers")
        if nested:
            out.extend(_flatten(nested))
        else:
            out.append(layer)
    return out


def _truth(base: str, did: str, tid: str, t_us: int):
    """What the draft says is on screen at ``t_us``: ids, video ids, media positions."""
    ir = _get(base, "/api/frame", draft=did, timeline=tid, t_us=int(t_us))
    ids, videos, media = set(), [], {}
    for layer in _flatten(ir["layers"]):
        ids.add(layer["layer_id"])
        media[layer["layer_id"]] = layer["time"]["source_time_us"] / 1e6
        if (layer.get("media") or {}).get("family") == "video":
            videos.append(layer["layer_id"])
    return ids, videos, media


def run(args) -> int:
    from ..shot.browser import BrowserSession
    from ..shot.cdp import CDP

    base = args.base.rstrip("/")
    info = _get(base, "/api/timelines", draft=args.draft)
    did, tid = info["did"], args.timeline or info["active_timeline_id"]
    url = (f"{base}/?draft={urllib.parse.quote(did)}&timeline={urllib.parse.quote(tid)}"
           f"&t={args.start}&chrome=1")
    print(f"{info['name']} · timeline {tid[:8]} · 从 {args.start}s 起播 {args.seconds}s")

    browser = BrowserSession(args.state_dir / "browser-cli")
    browser.start()
    page = browser.new_page("about:blank")
    client = CDP(page["webSocketDebuggerUrl"], timeout=60)
    samples: list[tuple[float, dict]] = []
    try:
        client.send("Page.enable")
        client.send("Runtime.enable")
        client.send("Emulation.setDeviceMetricsOverride",
                    {"width": 1680, "height": 950, "deviceScaleFactor": 1, "mobile": False})
        client.send("Page.navigate", {"url": url})
        deadline = time.time() + 90
        while time.time() < deadline:
            try:
                if client.evaluate("window.__ready === true && window.__state().durationUs > 0 "
                                   "&& !window.__state().playing && "
                                   "window.__state().loading.kind === 'idle'"):
                    break
            except Exception:                                   # noqa: BLE001
                pass
            time.sleep(0.2)
        else:
            print("页面始终没有 ready")
            return 1

        started = time.time()
        client.evaluate("window.__play(true)")
        play_deadline = time.time() + 10
        playing_state = None
        while time.time() < play_deadline:
            playing_state = client.evaluate("window.__state()")
            if playing_state.get("playing") or playing_state.get("phase") == "playing":
                break
            time.sleep(0.1)
        print("playing =", bool(playing_state and playing_state.get("playing")))
        # Native GStreamer may need to establish the multipart frame stream after
        # the control API reports PLAYING. Do not count that startup as playback
        # wall time or mistake a zero-clock warmup for a realtime result.
        warmup_deadline = time.time() + 10
        while time.time() < warmup_deadline:
            warm = client.evaluate("window.__state()")
            if warm.get("tUs", 0) > float(args.start) * 1e6 + 33_333:
                break
            time.sleep(0.1)
        started = time.time()
        while time.time() - started < args.seconds:
            raw = client.evaluate("JSON.stringify(window.__snapshot())")
            if raw:
                samples.append((time.time() - started, json.loads(raw)))
            time.sleep(args.sample)
        client.evaluate("window.__play(false)")
        time.sleep(0.5)
    finally:
        client.close()
        try:
            browser._http(f"/json/close/{page['id']}")       # noqa: SLF001
        except Exception:                                       # noqa: BLE001
            pass
        browser.stop()

    if not samples:
        print("没有采到样本")
        return 1

    rolled = samples[-1][1]["tUs"] - samples[0][1]["tUs"]
    wall = max(samples[-1][0] - samples[0][0], 1e-9)
    print(f"采样 {len(samples)} 次 · 时间线走了 {rolled/1e6:.2f}s / 墙钟 {wall:.1f}s "
          f"· 实时率 {rolled/1e6/wall:.2f}× · 池内节点 {samples[-1][1]['pool']} "
          f"· 窗口 {samples[-1][1]['window']}\n")

    missing = extra = black = drift = buffering = switched = 0
    previous = None
    rows = []
    tracks: dict[str, list[float]] = {}
    for index, (_, snap) in enumerate(samples):
        t_us = snap["tUs"]
        seen = {item["id"] for item in snap["layers"]}
        want, want_videos, media = _truth(base, did, tid, t_us)
        if want - seen:
            missing += 1
        if seen - want:
            extra += 1
        videos = [item for item in snap["layers"] if item["kind"] in ("video", "photo")]
        if want_videos and not videos:
            black += 1
        if snap["buffering"]:
            buffering += 1
        for item in videos:
            if item["mediaTime"] is None:
                continue
            span = tracks.setdefault(item["id"], [item["mediaTime"], item["mediaTime"]])
            span[0] = min(span[0], item["mediaTime"])
            span[1] = max(span[1], item["mediaTime"])
        if videos and videos[0]["mediaTime"] is not None:
            layer_id = videos[0]["id"]
            if layer_id in media and abs(videos[0]["mediaTime"] - media[layer_id]) > DRIFT_TOL_S:
                drift += 1
        ids = [item["id"] for item in videos]
        if previous is not None and ids != previous:
            switched += 1
        previous = ids
        if index < 14:
            rows.append((t_us, len(seen), len(want), ids,
                         videos[0]["mediaTime"] if videos else None))

    print("  时间线时刻   画面层  应为   首个视频层      媒体位置(s)")
    for t_us, got, want, ids, position in rows:
        print(f"  {t_us/1e6:7.2f}s   {got:3d}   {want:3d}   "
              f"{','.join(i[:8] for i in ids)[:24]:24s} {position}")
    print("  …")
    frozen = [key for key, (low, high) in tracks.items() if high - low < FROZEN_S]
    print(f"\n播放中出现的视频层 {len(tracks)} 个；其中画面未推进的 {len(frozen)} 个"
          + (f" → {[k[:8] for k in frozen]}" if frozen else "（全部在推进）"))
    for key, (low, high) in sorted(tracks.items(), key=lambda item: item[1][0])[:10]:
        print(f"    {key[:8]}  媒体位置 {low:7.2f}s → {high:7.2f}s")
    print(f"\n与草稿不符：缺图层 {missing} 次 · 多图层 {extra} 次 · 该有画面却空白 {black} 次"
          f"（共 {len(samples)} 次采样）")
    print(f"媒体位置漂移 > {DRIFT_TOL_S}s：{drift} 次 · 图层切换 {switched} 次 "
          f"· 缓冲中 {buffering} 次")
    return 0 if (missing == 0 and extra == 0 and black == 0) else 2


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("draft", help="草稿名（与 preview.py 同一套名字）")
    parser.add_argument("--timeline", default=None, help="默认取活动时间线")
    parser.add_argument("--seconds", type=float, default=20.0, help="播放并在其中采样多久")
    parser.add_argument("--start", type=float, default=0.0, help="起播秒数")
    parser.add_argument("--sample", type=float, default=SAMPLE_S, help="采样间隔秒")
    parser.add_argument("--base", default="http://127.0.0.1:8765", help="已运行的服务地址")
    parser.add_argument("--state-dir", type=Path, default=Path.home() / ".jypreview")
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
