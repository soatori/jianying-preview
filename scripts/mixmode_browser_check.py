"""浏览器通道的混合模式**接线**验证（U-92/F-094 落地后的守卫）。

为什么单独一条：本草稿 0 个 `mix_mode` 段，门的 L1~L10 在真实模型上永远不会走这条路；
而 F-094 证的是**网格级**等价（17×17 注入件 == 裸 GL 出厂件，maxΔ=0），不是播放器里真的挂上了。
这条层回答三件事，都有分母（没有分母的守卫等于没有守卫）：
  B1 载体：网关取到 MixMode 索引（`mix.loaded`），且切片真的能建出滤镜（`mix.known >= 1`）；
  B2 挂载：模型里**应当**有 N 个混合段（分母 = `stats.mix_mode_segments`），浏览器自报
     `mix.applied_nodes >= 1` ⇒ 滤镜真的挂在活着的节点上了；
  B3 降级：喂一个**不存在的包 md5**，必须 `degraded >= 1` 且 `applied_nodes == 0`
     —— 这是 B2 的反fixture（negative fixture），否则"永远绿"和"根本没挂"分不开。

数学本身不在这里重测（那是 mixmode_equivalence / F-079 / F-094 的事），
像素对数也不在这里（L10 用 `--media-model` 指到注入件上就跑出来了）。

用法：
    python scripts/mixmode_browser_check.py [--carrier temp/playback-test/model-proxy-a.json]
        [--t 7.0] [--port 8819]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "temp" / "playback-test"
sys.path.insert(0, str(ROOT / "scripts"))

MARK_OK = "MIXMODE_BROWSER_WIRING ok"
MARK_BAD = "MIXMODE_BROWSER_WIRING FAIL"


def wait_port(port: int, timeout: float = 20.0) -> bool:
    import socket
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with socket.create_connection(("127.0.0.1", port), 0.5):
                return True
        except OSError:
            time.sleep(0.3)
    return False


def fixture(carrier: Path, md5: str | None, name: str, path: Path) -> int:
    """从真人载体造注入件：所有 flag=2 且带素材的段挂同一个包（与 L7 的构造件同一口径）。"""
    import mixmode_wiring_check as w
    m = json.loads(carrier.read_text(encoding="utf-8-sig"))
    out = w.inject(m, md5, name)
    n = sum(1 for tr in out["tracks"] for s in tr["segments"] if s.get("mix_mode"))
    out.setdefault("stats", {})["mix_mode_segments"] = n
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return n


def browser_mix_report(port: int, model_name: str, t: float, tag: str) -> dict:
    """跑一次无头浏览器，只取它的自报 `mix` 读数（截图由 L10 负责，这里不要像素）。

    走 **battery 路径**（`autostart=1`）而不是 `shots=`：`mix` 读数挂在 `/report` 的那份
    `r` 上，`shots=` 只发 `/shot`（第一版我就在这里读错了端点，报"浏览器一条都没回"）。
    """
    rpt = OUT / f"report-mixwire-{tag}.jsonl"
    rpt.unlink(missing_ok=True)
    url = (f"http://127.0.0.1:{port}/playback-test/player.html?model={model_name}"
           f"&autostart=1&playms=2500&seeks=0&fps=30&qmax=4&pool=4&tag=mixwire-{tag}")
    subprocess.run([sys.executable, "scripts/browser_soak.py", "--url", url,
                    "--seconds", "35", "--report", str(rpt.relative_to(ROOT)),
                    "--tag", f"mixwire-{tag}", "--timeout", "90"],
                   cwd=str(ROOT), capture_output=True, text=True,
                   encoding="utf-8", errors="replace")
    if not rpt.is_file():
        return {"error": "no report from browser"}
    rows = [json.loads(l) for l in rpt.read_text(encoding="utf-8").splitlines() if l.strip()]
    with_mix = [r for r in rows if isinstance(r.get("mix"), dict)]
    if not with_mix:
        return {"error": f"{len(rows)} 条自报里没有 mix 字段（player 未上报？）",
                "keys": sorted(rows[-1])[:20] if rows else []}
    return with_mix[-1]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--carrier", default="temp/playback-test/model-proxy-a.json")
    ap.add_argument("--t", type=float, default=7.0, help="取一个 flag=2 叠加段活着的时刻")
    ap.add_argument("--port", type=int, default=8819)
    args = ap.parse_args()

    carrier = Path(args.carrier)
    if not carrier.is_file():
        print(f"{MARK_BAD} carrier missing: {carrier}")
        return 2
    mul = fixture(carrier, "8001e07eefc5d8b69572b977ca14bef9", "正片叠底",
                  OUT / "model-mixwire-mul.json")
    bogus = fixture(carrier, "0000000000000000000000000000000", "无包",
                    OUT / "model-mixwire-bogus.json")

    gw = subprocess.Popen([sys.executable, "scripts/preview_gateway.py",
                           "--serve-dir", "temp", "--port", str(args.port),
                           "--model", str(carrier)],
                          cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    rows, code = [], 0
    try:
        if not wait_port(args.port):
            print(f"{MARK_BAD} gateway did not start on {args.port}")
            return 2
        # 注入件要单独进网关的媒体表：网关按 --model 建 manifest，但播放的是注入件，
        # 两者的 media.path 一致（inject 只改 mix_mode 字段），所以同一张表够用。
        a = browser_mix_report(args.port, "model-mixwire-mul.json", args.t, "mul")
        b = browser_mix_report(args.port, "model-mixwire-bogus.json", args.t, "bogus")
        ma, mb = a.get("mix") or {}, b.get("mix") or {}
        rows.append(("B1 carrier: mix.loaded & slice built",
                     bool(ma.get("loaded")) and (ma.get("packages", 0) > 0)
                     and (ma.get("known", 0) >= 1), ma))
        # B2 的分母是模型自己说的段数，不是浏览器的读数——否则"模型没段"也能报绿
        rows.append((f"B2 applied (denominator stats.mix_mode_segments={mul})",
                     mul > 0 and (ma.get("applied_nodes", 0) >= 1), ma))
        rows.append((f"B3 degraded on unknown md5 (denominator={bogus})",
                     bogus > 0 and (mb.get("applied_nodes", -1) == 0)
                     and len(mb.get("degraded") or []) >= 1, mb))
        if "error" in a or "error" in b:
            rows.append(("B0 browser reported at all", False, {"a": a.get("error"),
                                                              "b": b.get("error")}))
        failed = [name for name, ok, _ in rows if not ok]
        for name, ok, data in rows:
            print(f"  [{'ok ' if ok else 'FAIL'}] {name} :: "
                  f"{json.dumps(data, ensure_ascii=False)[:220]}")
        print("browser mix detail (mul): "
              f"known={ma.get('known')} applied={ma.get('applied_nodes')} "
              f"degraded={ma.get('degraded')} errors={ma.get('errors')} "
              f"detail={json.dumps(ma.get('detail'), ensure_ascii=False)[:160]}")
        if failed:
            print(f"{MARK_BAD} :: {len(failed)} 项不过 :: {'; '.join(failed)}")
            code = 1
        else:
            print(f"{MARK_OK} :: 载体取到切片并建出 {ma.get('known')} 个滤镜，"
                  f"{mul} 个应挂段里浏览器挂了 {ma.get('applied_nodes')} 个节点；"
                  f"未知包 md5 走降级 {mb.get('degraded')} 且不挂任何节点")
    finally:
        gw.terminate()
        try:
            gw.wait(timeout=10)
        except subprocess.TimeoutExpired:
            gw.kill()
    return code


if __name__ == "__main__":
    sys.exit(main())
