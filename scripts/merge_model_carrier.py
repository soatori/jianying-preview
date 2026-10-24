"""把新 L1 的「载体字段」合并进已有的代理模型，而不是重建整套代理。

为什么需要它：门的 L4 电池吃 `model-proxy-a.json`（代理只把素材路径换成本地 4:2:0 副本），
那份是用**当时的 L1** 生成的。L1 后来加了 `animations`/`mix_mode`（F-078/F-079），
代理模型里没有 —— 于是「模型加了新通道」而浏览器通道**一个字都看不见**，门还全绿
（P-33 记了这个陷阱）。重建整套代理要跑 GPU 转码（~10 分钟），而合并载体只要几秒。

纪律：
  - 只搬白名单里的字段，**不碰** `media.path`（那是代理的意义所在）；
  - 原子写：先写 `.tmp` 再 `os.replace`，并留一份 `.bak`（`open(p,'w')` 会在抛错前就把原文件截断）；
  - 合并完自检计数，数不对就非零退出，不留「看起来成功了」。

用法:
    python scripts/merge_model_carrier.py --target temp/playback-test/model-proxy-a.json \
        --source temp/playback-test/model-check.json [--fields animations,mix_mode] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
# Windows 控制台是 GBK：读数里带中文/箭头/替换符时 print 会在最后一步抛错，
# 把已经算完的结果整个吞掉（本轮自己的统计工具就栽过一次）。只改错误处理策略，不改编码。
try:
    sys.stdout.reconfigure(errors="replace")     # type: ignore[attr-defined]
    sys.stderr.reconfigure(errors="replace")     # type: ignore[attr-defined]
except Exception:                                 # noqa: BLE001
    pass

DEFAULT_FIELDS = ("animations", "mix_mode")


def segments(model: dict) -> dict:
    return {s["id"]: s for tr in model.get("tracks", []) for s in tr.get("segments", [])}


def all_segments(model: dict) -> dict:
    """顶层段 + 复合子时间线里的段，一次走全（代理与明文模型在子层可能有不同的段集）。"""
    out: list = []
    walk_children(model, out)
    by_id = {s["id"]: s for s in out if isinstance(s, dict) and s.get("id")}
    by_id.update(segments(model))
    return by_id


def walk_children(node, out: list) -> None:
    """复合子时间线里的段也要收 —— 代理与明文模型在子层同样可能有不同的段集。"""
    for tr in node.get("tracks", []) if isinstance(node, dict) else []:
        for s in tr.get("segments", []) or []:
            out.append(s)
            if s.get("composite"):
                walk_children(s["composite"], out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--target", required=True, help="要就地更新的代理模型")
    ap.add_argument("--source", required=True, help="提供载体字段的新 L1 模型")
    ap.add_argument("--fields", default=",".join(DEFAULT_FIELDS))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    fields = [f.strip() for f in args.fields.split(",") if f.strip()]
    tgt_path = Path(args.target)
    tgt = json.loads(tgt_path.read_text(encoding="utf-8-sig"))
    src = json.loads(Path(args.source).read_text(encoding="utf-8-sig"))

    src_by_id = all_segments(src)
    tgt_by_id = all_segments(tgt)

    touched = {f: 0 for f in fields}
    missing_in_src = 0
    for sid, seg in tgt_by_id.items():
        other = src_by_id.get(sid)
        if other is None:
            missing_in_src += 1
            continue
        for f in fields:
            # 缺席 vs 空列表当同一状态，否则每个段都算「被改过」，计数就没意义了
            if f in other and (seg.get(f) or None) != (other.get(f) or None):
                seg[f] = other[f]
                touched[f] += 1

    # 统计口径用「非空」而不是「键存在」：键存在但为空数组不算带动画
    n_anim = sum(1 for s in tgt_by_id.values() if s.get("animations"))
    n_mix = sum(1 for s in tgt_by_id.values() if s.get("mix_mode"))
    src_anim = sum(1 for s in src_by_id.values() if s.get("animations"))
    print(f"段数 target={len(tgt_by_id)} source={len(src_by_id)} 源里没有同 id 的段={missing_in_src}")
    print("改动段数:", ", ".join(f"{f}={n}" for f, n in touched.items()))
    print(f"合并后计数：带动画段 {n_anim}（源 {src_anim}）/ 带混合模式段 {n_mix}")
    if n_anim != src_anim:
        print("FAIL 合并后的动画段数与源模型不一致 —— 有段没被搬过去，别把代理当新模型用",
              file=sys.stderr)
        return 1
    if args.dry_run:
        print("dry-run：不写文件")
        return 0

    tmp = tgt_path.with_suffix(tgt_path.suffix + ".tmp")
    tmp.write_text(json.dumps(tgt, ensure_ascii=False, indent=1), encoding="utf-8")
    if tgt_path.exists():
        shutil.copy2(tgt_path, tgt_path.with_suffix(tgt_path.suffix + ".bak"))
    os.replace(tmp, tgt_path)
    print(f"written -> {tgt_path}（备份 {tgt_path.name}.bak）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
