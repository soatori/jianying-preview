"""扫本机 `Cache/effect/*/*/AmazingFeature/lua/SeekModeScript.lua`，把带**明文 `ae_attribute`
关键帧表**的包全解出来存一份 JSON（#16 的第①步）。

为什么要单独扫：`animation_tiers.py` 的 `AE_MARKS = (".lsanim", ".lsproj", ".jsdat")` 只认
**扩展名**形态的 AE 导出，而这一族的表是**写在 lua 正文里**的（F-095），所以 CSV 里这些包
`ae_export=0`——那是标记集缺口。本脚本自带分母（扫到多少 / 有表多少 / 解析失败多少），
不做「我以为没有」这种缺席断言（[[feedback-prove-scan-coverage]]）。

用法：
    python scripts/ae_table_harvest.py [--out temp/playback-test/ae-tables.json]
                                       [--draft-model temp/playback-test/model-proxy-a.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ae_keyframe as aek                       # noqa: E402

try:
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")
except Exception:                                 # noqa: BLE001
    pass

ROOT = Path.home() / "AppData/Local/JianyingPro/User Data/Cache/effect"


def join_draft(model_path: Path) -> dict:
    """把草稿里 name ↔ package_md5 的对应关系拿出来（有表包能落到几段动画上）。"""
    out: dict[str, list] = {}
    if not model_path.exists():
        return out
    d = json.loads(model_path.read_text(encoding="utf-8"))

    def walk(node):
        if isinstance(node, dict):
            if node.get("name") and node.get("path"):
                md5 = str(node["path"]).rstrip("/").split("/")[-1]
                out.setdefault(md5, []).append(
                    {"name": node["name"], "kind": node.get("kind"),
                     "duration_us": node.get("duration_us")})
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
    walk(d)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--out", type=Path, default=Path("temp/playback-test/ae-tables.json"))
    ap.add_argument("--draft-model", type=Path,
                    default=Path("temp/playback-test/model-proxy-a.json"))
    args = ap.parse_args()

    scripts = sorted(args.root.glob("*/*/AmazingFeature/lua/SeekModeScript.lua"))
    draft = join_draft(args.draft_model)
    rows, no_table, failed = [], 0, []
    for p in scripts:
        md5 = p.parents[2].name
        rid = p.parents[3].name
        try:
            src = p.read_text(encoding="utf-8", errors="replace")
        except OSError as e:                      # noqa: BLE001
            failed.append({"md5": md5, "err": f"read {e}"})
            continue
        if "ae_attribute" not in src:
            no_table += 1
            continue
        try:
            attrs = aek.parse_ae_attribute(src)
            cons = aek.extract_constants(src)
        except (AssertionError, ValueError, IndexError) as e:   # noqa: BLE001
            failed.append({"md5": md5, "err": f"parse {type(e).__name__}: {e}"})
            continue
        tools = aek.AETools(attrs)
        cov = {}
        for k, v in attrs.items():
            spans = [i[1] for i in v]
            cov[k] = {"keys": len(v), "from": spans[0][0], "to": spans[-1][1],
                      "contiguous": all(spans[i][1] == spans[i + 1][0]
                                        for i in range(len(spans) - 1))}
        rows.append({"resource_id": rid, "package_md5": md5,
                     "script": str(p), "attrs": len(attrs), "all_frame": tools.all_frame,
                     "ae_mul": cons["ae_mul"], "ae_div": cons["ae_div"],
                     "mod_eps": cons["mod_eps"], "default_duration": cons["default_duration"],
                     "noise_gain": cons["noise_gain"], "coverage": cov,
                     "contiguous_all": all(c["contiguous"] for c in cov.values()),
                     "draft_hits": draft.get(md5, [])})
    n_contig = sum(1 for r in rows if r["contiguous_all"])
    n_hits = sum(1 for r in rows if r["draft_hits"])
    print(f"AE_TABLE_HARVEST scanned={len(scripts)} with_table={len(rows)} "
          f"no_table={no_table} parse_failed={len(failed)} 首尾相接={n_contig}/{len(rows)} "
          f"本草稿命中={n_hits}")
    for r in rows:
        hit = ",".join(f"{h['name']}/{h['kind']}" for h in r["draft_hits"]) or "-"
        print(f"  {r['package_md5'][:12]}… rid={r['resource_id'][-8:]} 属性={r['attrs']} "
              f"all_frame={r['all_frame']:g} t映射={r['ae_mul']:g}/{r['ae_div']:g} 草稿={hit}")
    for f in failed:
        print(f"  FAIL {f['md5'][:12]}… {f['err']}")
    if probe_err := [r["package_md5"] for r in rows if not r["contiguous_all"]]:
        print(f"AE_TABLE_HARVEST WARN 帧区间不接续的包: {probe_err}")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.out.with_suffix(args.out.suffix + ".tmp")
    payload = {"root": str(args.root), "scanned": len(scripts), "with_table": len(rows),
               "no_table": no_table, "failed": failed, "packages": rows,
               "draft_model": str(args.draft_model)}
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    bak = args.out.with_suffix(args.out.suffix + ".bak")
    if args.out.exists():
        bak.write_bytes(args.out.read_bytes())
    tmp.replace(args.out)
    print(f"写出 {args.out}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
