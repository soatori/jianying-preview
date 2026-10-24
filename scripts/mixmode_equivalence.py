"""要求 1 的判定器：剪映 MixMode 包内 GLSL vs 独立实现（W3C 标准式）逐 texel 数值比对。

为什么这样判：00-overview 里「唯一还没证的基座判据」写的是「PixiJS 自定义 blend shader 与
`*BlendPreMul` GLSL 的数值等价」。等价不能靠人对 GLSL 的阅读来宣布，所以 oracle 用包内 frag
**原文**（headless Chrome 的 WebGL1 直接编译，脚本不誊写公式），对照腿用 W3C
Compositing and Blending 的标准可分离式（独立实现，不看包内代码）。两条腿吃**同一份 8-bit 输入字节**，
所以差值只可能来自公式差异与 GPU 精度，不会来自量化口径。

判据（口径要说清）：
  - `<=1/255` 视为等价：GPU 输出是 RGBA8，1 个单位是量化下界，不是缺陷。
  - 预乘分支（blendAlphaState=1）是播放器要走的那条（Pixi 的纹理是预乘的）；
    直通分支也测，因为包内 main() 由引擎给的状态选路，而 config.json 的 alphaState=2
    并不在材质属性表里（属性表只有 inputWidth/inputHeight/_alpha/baseTex/_MainTex）。
  - 结论是「哪些模式可以用标准式/CSS 混合，哪些必须移植包内数学」，不是「全部通过」。

用法：
    python scripts/mixmode_equivalence.py [--install ...] [--repeat 1] [--keep-table]
输出：docs/evidence/tables/mixmode_equivalence.csv、temp/playback-test/mixmode-verdict.json
前置：headless Chrome（与门同一启动器 scripts/browser_soak.py）、网关（scripts/preview_gateway.py）
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import time

import numpy as np
from pathlib import Path
# Windows 控制台是 GBK：读数里带中文/箭头/替换符时 print 会在最后一步抛错，
# 把已经算完的结果整个吞掉（本轮自己的统计工具就栽过一次）。只改错误处理策略，不改编码。
try:
    sys.stdout.reconfigure(errors="replace")     # type: ignore[attr-defined]
    sys.stderr.reconfigure(errors="replace")     # type: ignore[attr-defined]
except Exception:                                 # noqa: BLE001
    pass

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "temp" / "playback-test"
PY = sys.executable


def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def free_port() -> int:
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def wait_port(port: int, timeout: float = 25.0) -> bool:
    import socket
    t0 = time.time()
    while time.time() - t0 < timeout:
        with socket.socket() as s:
            s.settimeout(0.5)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.2)
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--install", default=r"D:/Program Files/JianyingPro/11.6.0.14552")
    ap.add_argument("--model", default=str(OUT / "model-check.json"))
    ap.add_argument("--seconds", type=int, default=120)
    ap.add_argument("--tolerance", type=int, default=1, help="8-bit units treated as equal")
    args = ap.parse_args()

    # 1. 抽取 frag 原文到网关可服务的目录（sha256 与安装目录逐字节一致，见 manifest.json）
    ex = run([PY, "scripts/mixmode_extract.py", "--install", args.install,
              "--out-dir", str(OUT / "mixmode")])
    if ex.returncode:
        print(ex.stdout, ex.stderr)
        return 2
    manifest = json.loads((OUT / "mixmode" / "manifest.json").read_text(encoding="utf-8"))

    # 2. 起网关（serve-dir=temp => 页面 URL /playback-test/mixmode-eq.html）
    port = free_port()
    report = OUT / "report-mixmode.jsonl"
    if report.exists():
        report.unlink()
    gw = subprocess.Popen([PY, "scripts/preview_gateway.py", "--port", str(port),
                           "--serve-dir", "temp", "--model", args.model],
                          cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    rows: list[dict] = []
    payload: dict = {}
    try:
        if not wait_port(port):
            print("gateway never came up", file=sys.stderr)
            return 2
        so = run([PY, "scripts/browser_soak.py", "--url",
                  f"http://127.0.0.1:{port}/playback-test/mixmode-eq.html",
                  "--seconds", str(args.seconds), "--report", str(report.relative_to(ROOT)),
                  "--tag", "mixmode", "--timeout", str(args.seconds + 30)])
        if report.exists():
            lines = [ln for ln in report.read_text(encoding="utf-8").splitlines() if ln.strip()]
            if lines:
                payload = json.loads(lines[-1]).get("mixmode") or {}
                rows = payload.get("rows") or []
                gpu = payload.get("gpu")
                if payload.get("error"):
                    print("page error:", payload["error"])
                    return 3
    finally:
        gw.terminate()
        try:
            gw.wait(timeout=10)
        except subprocess.TimeoutExpired:
            gw.kill()

    if not rows:
        print(f"no rows came back\n{so.stdout[-1500:]}\n{so.stderr[-800:]}", file=sys.stderr)
        return 3

    # 2b. 三方对照：包内原文(GPU) vs 出厂件(GPU) vs 我们的 numpy 实现
    #     oracle 永远是包内原文在 GPU 上的输出；出厂件与 numpy 都必须落在 1/255 里。
    import base64
    from mixmode_blend import blend, MODE_BY_FUNCTION
    md5_by_name = {p["nameId"]: p["package_md5"] for p in manifest["packages"]}
    fn_by_md5 = {p["package_md5"]: p["premul_fn"] for p in manifest["packages"]}
    impl: dict[str, dict] = {}
    for pb in payload.get("pass_bytes") or []:
        if pb["state"] != 1:
            continue                      # 我们的实现固定预乘支（U-90 未判前不做直通支）
        n = int(pb["n"])
        fg = np.frombuffer(base64.b64decode(pb["fg_in"]), dtype=np.uint8).reshape(n, n, 4) / 255.0
        bg = np.frombuffer(base64.b64decode(pb["bg_in"]), dtype=np.uint8).reshape(n, n, 4) / 255.0
        ven = np.frombuffer(base64.b64decode(pb["vendor"]), dtype=np.uint8).reshape(n, n, 4)
        shp = np.frombuffer(base64.b64decode(pb["shipped"]), dtype=np.uint8).reshape(n, n, 4)
        mode = MODE_BY_FUNCTION[fn_by_md5[md5_by_name[pb["name_id"]]]]
        mine = blend(mode, fg.astype(np.float32), bg.astype(np.float32),
                     fg_alpha=float(pb["fg_alpha"]))
        mine8 = np.clip(np.round(mine * 255.0), 0, 255).astype(np.uint8)
        d_ship = int(np.abs(ven.astype(np.int16) - shp.astype(np.int16)).max())
        d_numpy = int(np.abs(ven.astype(np.int16) - mine8.astype(np.int16)).max())
        slot = impl.setdefault(pb["name_id"], {"max_ship": 0, "max_numpy": 0, "passes": 0,
                                              "cells_numpy_over": 0, "cells_total": 0})
        slot["max_ship"] = max(slot["max_ship"], d_ship)
        slot["max_numpy"] = max(slot["max_numpy"], d_numpy)
        slot["passes"] += 1
        slot["cells_numpy_over"] += int((np.abs(ven.astype(np.int16) - mine8.astype(np.int16))
                                         > args.tolerance).sum())
        slot["cells_total"] += int(ven.size)

    # 3. 逐模式汇总：两个分支分别取最差读数（分布而不是单点）
    modes: dict[str, dict] = {}
    for r in rows:
        m = modes.setdefault(r["name_id"], {"op": r["op"], "passes": 0, "texels": 0,
                                            "over_1": 0, "s1": {}, "s2": {}})
        m["passes"] += 1
        m["texels"] += r["texels"]
        m["over_1"] += r["over_1"]
        key = "s1" if r["state"] == 1 else "s2"
        m[key]["max_abs"] = max(m[key].get("max_abs", 0), r["max_abs_255"])
        m[key]["worst_case"] = (f"fa={r['fa']} ba={r['ba']} _alpha={r['fg_alpha']}")
    order = [p["nameId"] for p in manifest["packages"]]

    tbl = ROOT / "docs" / "evidence" / "tables" / "mixmode_equivalence.csv"
    with tbl.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["name_id", "glsl_op", "w3c_op", "passes", "channel_comparisons",
                    "over_tolerance", "premul_branch_max_abs_255", "premul_worst_case",
                    "straight_branch_max_abs_255", "straight_worst_case",
                    "shipped_vs_vendor_max_abs_255", "numpy_vs_vendor_max_abs_255",
                    "numpy_cells_over_tolerance", "numpy_cells_total", "impl_passes", "verdict"])
        for nid in order:
            m = modes[nid]
            pkg = next(p for p in manifest["packages"] if p["nameId"] == nid)
            ok1 = m["s1"]["max_abs"] <= args.tolerance
            ok2 = m["s2"]["max_abs"] <= args.tolerance
            verdict = ("等价" if ok1 and ok2 else
                       ("预乘分支等价（播放器可用标准式）" if ok1 else
                        "必须移植包内数学（标准式/CSS 混合会改变像素）"))
            ip = impl.get(nid, {"max_ship": -1, "max_numpy": -1, "passes": 0,
                               "cells_numpy_over": 0, "cells_total": 0})
            w.writerow([nid, pkg["premul_fn"], m["op"], m["passes"], m["texels"], m["over_1"],
                        m["s1"]["max_abs"], m["s1"]["worst_case"],
                        m["s2"]["max_abs"], m["s2"]["worst_case"],
                        ip["max_ship"], ip["max_numpy"], ip["cells_numpy_over"],
                        ip["cells_total"], ip["passes"], verdict])

    print(f"gpu={gpu}  install={manifest['install']}  index_sha={manifest['index_sha256'][:12]}")
    print(f"{'nameId':<20} {'op':<11} {'preMul maxΔ8b':>13} {'straight maxΔ8b':>16}  verdict")
    for nid in order:
        m = modes[nid]
        ip = impl.get(nid, {})
        print(f"{nid:<20} {m['op']:<11} {m['s1']['max_abs']:>13} {m['s2']['max_abs']:>16} "
              f"ship={ip.get('max_ship','-'):>3} numpy={ip.get('max_numpy','-'):>3} "
              f"over={ip.get('cells_numpy_over','-')}/{ip.get('cells_total','-')}  "
              f"{'等价' if m['s1']['max_abs'] <= args.tolerance and m['s2']['max_abs'] <= args.tolerance else '需移植'}")
    (OUT / "mixmode-verdict.json").write_text(
        json.dumps({"install": manifest["install"], "index_sha256": manifest["index_sha256"],
                    "tolerance": args.tolerance, "gpu": gpu, "modes": modes,
                    "raw_passes": len(rows)}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"table -> {tbl}")
    print(f"json  -> {OUT / 'mixmode-verdict.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
