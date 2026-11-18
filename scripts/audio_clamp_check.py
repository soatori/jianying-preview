#!/usr/bin/env python3
"""audio_clamp_check.py — 钉住「clamp 诊断那行把整个音频作业炸掉」这一族缺陷。

机制（P-163，门 2026-11-06 抓到）：`player.html` 的 `flush()` 在**被夹**（`at > when+0.005`）时
往 `audioStats.clamp_at` 推一条诊断，行里写的是 `String(j.seg_id || sid || '')`：
`j.seg_id` 这个字段从没被赋过值（作业对象上只有 `seg`），于是求值走到 `sid`——
而 `sid` 是一个**从未声明的自由标识符**，读它就是 ReferenceError。
异常从 `flush()` 一路撞到 `pumpAudio` 的 `catch`，**该作业剩下的批次全部不排**：
`audio_errors++`、`lost_s += 剩余秒数`、`per_seg` 里 `ctx1 <= ctx0`（=L29 的"零排期段"）。
所以 P-154 那个"间歇性饿死的泵"不是取流饿死，是**每一次夹到就杀掉一个作业**；
间歇的只是"夹发生在第一批还是最后一批"。

三条腿（缺一条都不算立住判据）：
  C1 源级：在册页里那行必须只引用真实字段，且 `|| sid ||` 这种死引用不许存在；
  C2 真页实跑：跑一段真实播放，**先证明夹发生了**（`clamps > 0`，否则本腿不判绿，
     按 U-107 的教训"没被执行到的判据不是判据"），再要求 `audio_errors == 0` 且没有 `is not defined`；
  C3 反例 fixture：把死引用装回去**并且**强制走 clamp 分支 ⇒ 必须转红且红在 `sid is not defined`，
     证明 C2 的尺子确实咬得住这个机制（而不是永远绿）。

用法：
    python scripts/audio_clamp_check.py --model model-proxy-p157.json          # C1+C2+C3
    python scripts/audio_clamp_check.py --only-source                           # 只跑 C1（便宜，门内可用）
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "temp/playback-test"
PY = sys.executable
FAILS: list[str] = []

DEAD_READ = re.compile(r"\|\|\s*sid\b")            # 读一个从未声明的标识符
CLAMP_GUARD = "if (at > when + 0.005) {"           # 「被夹」那条守卫
JOB_FIELDS = re.compile(r"\bj\.seg_id\b")          # 作业对象上不存在的字段名
FIXED_EXPR = "String(j.seg?.id || '').slice(0, 8)"
DEAD_EXPR = "String(j.seg_id || sid || '').slice(0, 8)"


def note(ok: bool, msg: str) -> None:
    print(("  PASS  " if ok else "  FAIL  ") + msg)
    if not ok:
        FAILS.append(msg)


def push_statements(src: str) -> list[str]:
    """括号配对取出每一条 `audioStats.clamp_at.push(...)`。

    不用一行正则：诊断行里嵌着 `String((j.seg && j.seg.id) || '').slice(0, 8)`，
    两层括号，正则要么漏它、要么把「找不到」当成「没有问题」。
    """
    out: list[str] = []
    key = "audioStats.clamp_at.push("
    i = src.find(key)
    while i >= 0:
        depth, j = 0, i + len(key) - 1
        while j < len(src):
            if src[j] == "(":
                depth += 1
            elif src[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        out.append(src[i:j + 1])
        i = src.find(key, j + 1)
    return out


# ---------------- C1 源级 ----------------

def check_source(html: Path) -> None:
    src = html.read_text(encoding="utf-8")
    pushes = push_statements(src)
    if not pushes:
        note(False, "C1 找不到 clamp 诊断的 push 语句（改了形状？判据要跟着改，不许静默空跑）")
        return
    bad = [p for p in pushes if DEAD_READ.search(p) or JOB_FIELDS.search(p)]
    note(not bad,
         f"C1 `clamp_at` push 共 {len(pushes)} 处，死引用（`j.seg_id` / 读未声明的 `sid`）{len(bad)} 处"
         + (f"：{' '.join(bad[0].split())[:120]}" if bad else ""))


# ---------------- 实跑两条腿 ----------------

def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def run_page(page_rel: str, tag: str, model: str, play_ms: int) -> dict:
    """起网关跑一页，回传该次新落的报告行。"""
    report = OUT / f"report-{tag}.jsonl"
    before = len(report.read_text(encoding="utf-8", errors="replace").splitlines()) if report.exists() else 0
    port = free_port()
    gw = subprocess.Popen([PY, "-u", str(ROOT / "scripts/preview_gateway.py"), "--port", str(port),
                           "--serve-dir", "temp", "--model", str(OUT / model),
                           "--log", str(OUT / f"gw-{tag}.log")],
                          cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(2.0)
        url = (f"http://127.0.0.1:{port}/{page_rel}"
               f"?autostart=1&model={model}&playms={play_ms}&seeks=0&fps=30&qmax=4&pool=4&tag={tag}")
        subprocess.run([PY, "-u", str(ROOT / "scripts/browser_soak.py"), "--url", url,
                        "--seconds", str(int(play_ms / 1000) + 40), "--report", str(report),
                        "--tag", tag], cwd=ROOT, capture_output=True)
    finally:
        gw.terminate()
        try:
            gw.wait(timeout=10)
        except Exception:
            gw.kill()
    lines = report.read_text(encoding="utf-8", errors="replace").splitlines()[before:] if report.exists() else []
    for ln in reversed(lines):
        try:
            d = json.loads(ln)
        except Exception:
            continue
        if (d.get("play") or {}).get("audio"):
            return d
    return {}


def judge_run(d: dict, label: str, want_error: bool) -> None:
    if not d:
        note(False, f"{label}：没有旁证可读（采集失败≠通过）")
        return
    a = (d.get("play") or {}).get("audio") or {}
    errs = [str(e) for e in (d.get("errors") or [])]
    undef = [e for e in errs if "is not defined" in e]
    clamps = a.get("clamps") or 0
    if want_error:
        ok = bool(undef)
        note(ok, f"{label}（反例 fixture）：clamps={clamps}、audio_errors={a.get('audio_errors')}、"
                 f"自由标识符异常 {len(undef)} 条 {undef[:1]}" + ("" if ok else " ⇒ **尺子咬不住，C2 不可信**"))
        return
    ps = a.get("per_seg") or []
    starved = [s for s in ps if s.get("ctx0") is not None and s.get("ctx1") is not None
               and s["ctx1"] <= s["ctx0"]]
    if clamps <= 0:
        note(False, f"{label}：这一跑 **clamps=0**，clamp 分支根本没被走到 ⇒ 本腿不判绿"
                    f"（errors={len(errs)}、零排期={len(starved)}）——换个时刻/换负载重跑")
        return
    note(not undef and not (a.get("audio_errors") or 0),
         f"{label}：clamps={clamps}（分支确实被执行）、audio_errors={a.get('audio_errors')}、"
         f"`is not defined` {len(undef)} 条、零排期段={len(starved)}/{len(ps)}、lost_s={a.get('lost_s')}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--player", default="player/player.html")
    ap.add_argument("--model", default="model-proxy-p157.json", help="temp/playback-test 下的模型文件名")
    ap.add_argument("--play-ms", type=int, default=15000)
    ap.add_argument("--only-source", action="store_true", help="只跑 C1（不起浏览器）")
    args = ap.parse_args()

    print("== C1 源级（在册页）==")
    check_source(ROOT / args.player)
    if args.only_source:
        print("\n" + ("SOURCE PASS" if not FAILS else "SOURCE FAIL：" + "；".join(FAILS)))
        return 0 if not FAILS else 1

    # 同步一份服务副本（门内 L0 的口径：跑的是在册件的内容）
    served = OUT / "player.html"
    src = (ROOT / args.player).read_bytes()
    if served.read_bytes() != src:
        served.write_bytes(src)
    print("== C2 真页实跑 ==")
    judge_run(run_page("playback-test/player.html", "clampchk", args.model, args.play_ms),
              "C2 真页", want_error=False)

    print("== C3 反例 fixture（把死引用装回去 + 强制走 clamp 分支）==")
    neg_dir = OUT / "clampneg"
    neg_dir.mkdir(exist_ok=True)
    html = src.decode("utf-8")
    if FIXED_EXPR in html:
        neg = html.replace(FIXED_EXPR, DEAD_EXPR, 1)
    elif DEAD_EXPR in html:
        neg = html                      # 在册件本来就带着死引用（改前）——反例只需再强制走分支
    else:
        neg = ""
        note(False, f"C3 造不出反例：在册页里既没有 {FIXED_EXPR} 也没有 {DEAD_EXPR}"
                    f"（那行改形状了？判据要跟着改，不许静默空跑）")
    if neg and CLAMP_GUARD not in neg:
        note(False, "C3 造不出反例：clamp 分支的守卫行没找到（改形状了？）")
    elif neg:
        # 强制进入 clamp 分支：让"被夹"恒真，反例才不靠运气
        neg = neg.replace(CLAMP_GUARD, "if (true) {", 1)
        (neg_dir / "player.html").write_text(neg, encoding="utf-8")
        judge_run(run_page("playback-test/clampneg/player.html", "clampneg", args.model, args.play_ms),
                  "C3", want_error=True)

    print("\n" + ("SELFTEST PASS：源级干净、真页跑过且被夹分支有覆盖、反例仍能咬住"
                  if not FAILS else "SELFTEST FAIL：" + "；".join(FAILS)))
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
