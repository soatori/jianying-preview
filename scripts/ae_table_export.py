"""把入场动画的 **AE 关键帧表**导出成浏览器可读的稠密曲线，两通道读同一份。

为什么要有这份导出：`向上闪入` 这一族的律不在草稿字段里，在预设包
`AmazingFeature/lua/SeekModeScript.lua` 的明文 `ae_attribute` 表里（F-095）。通道 2 已经用
`scripts/ae_keyframe.py` 机械解表并求值；浏览器要是自己再解析一遍 lua、或者由我手抄几个数字，
就成了"第二份数学"（同族教训：P-33 的曲线表、F-079 的切片不誊写）。
所以这里用**同一个解析器**按 1/30 s 步长把 E（曝光）与 V（垂直模糊强度）采样成数组，
浏览器只做查表插值。

计数自证：包数 / 段数必须和模型里的 `stats.animation_segments`、以及通道 2 实际会加载的包数对上，
否则说明载体悄悄过期（P-33 那次代理模型缺 `animations` 就是靠这条抓的）。

用法：
    python scripts/ae_table_export.py --model temp/playback-test/model-proxy-a.json \
        --out temp/playback-test/ae-curves.json [--step-ms 33.3333]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    sys.stdout.reconfigure(errors="replace")
except Exception:                                 # noqa: BLE001
    pass

import render_frame as rf                          # noqa: E402
import ae_keyframe as aek                          # noqa: E402


def curve_for(pkg_dir: str, dur_us: int, step_us: int):
    """按 step 采样一个包的 (E, V)；解析不出来就返回 None（调用方要把它数成降级）。"""
    lua = Path(pkg_dir) / "AmazingFeature" / "lua" / "SeekModeScript.lua"
    if not lua.exists():
        return None
    pkg = rf._ae_pkg(str(lua))
    if pkg[0] == "ERR":
        return None
    mod, tools, cons, expo = pkg
    if rf.AE_VBLUR_ATTR not in tools.attrs:
        return None
    n = int(dur_us / step_us) + 1
    e_arr, v_arr = [], []
    for i in range(n):
        t = i * step_us / 1e6
        cf = mod.frame_of_clamped(t, dur_us / 1e6, cons, tools.all_frame)
        p = max(0.0, min(cf, tools.all_frame)) / tools.all_frame
        e_arr.append(round(float(tools.get_val(expo, p)[0]), 5))
        v_arr.append(round(float(tools.get_val(rf.AE_VBLUR_ATTR, p)[0]), 4))
    return {"package": str(pkg_dir).replace("\\", "/"), "attrs": sorted(tools.attrs),
            "constants": {k: cons[k] for k in ("ae_mul", "ae_div", "all_frame") if k in cons},
            "duration_us": dur_us, "step_us": step_us, "exposure": e_arr, "vblur": v_arr}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--step-ms", type=float, default=1000.0 / 30)
    args = ap.parse_args()
    step_us = max(1, int(round(args.step_ms * 1000)))
    m = json.loads(Path(args.model).read_text(encoding="utf-8-sig"))

    tables, segs_with, degraded = {}, 0, []
    for tr in m["tracks"]:
        for seg in tr.get("segments") or []:
            for a in seg.get("animations") or []:
                if a.get("kind") != "in" or not a.get("path"):
                    continue
                key = str(a["path"]).replace("\\", "/")
                if key not in tables:
                    got = curve_for(a["path"], int(a.get("duration_us") or 0), step_us)
                    if got is None:
                        degraded.append(key)
                        tables[key] = None
                        continue
                    tables[key] = got
                if tables[key] is None:
                    continue
                segs_with += 1
    out = {"step_us": step_us, "packages": sum(1 for v in tables.values() if v),
           "degraded": len(degraded), "segments_covered": segs_with,
           "k_blur": rf.AE_BLUR_K, "v_attr": rf.AE_VBLUR_ATTR,
           "curves": {k: v for k, v in tables.items() if v}}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(args.out).with_suffix(Path(args.out).suffix + ".tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    tmp.replace(Path(args.out))
    st = m.get("stats") or {}
    print(f"AE 表导出：{out['packages']} 个包可求值、{len(degraded)} 个不可求值（不算第二份数学，直接点名）；"
          f"覆盖 {segs_with} 段（模型 stats.animation_segments={st.get('animation_segments')}）")
    print(f"AE_TABLE_EXPORT packages={out['packages']} degraded={out['degraded']} "
          f"segments={segs_with} step_us={step_us} k_blur={rf.AE_BLUR_K}")
    for d in degraded[:5]:
        print(f"  不可求值：{d.split('/')[-2]}/{d.split('/')[-1]}")
    return 0 if out["packages"] else 2


if __name__ == "__main__":
    sys.exit(main())
