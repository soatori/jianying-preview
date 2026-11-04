"""重建某个剪映版本的 DLL 沙箱，用来把解密能力钉回「已知能出明文」的那一版。

为什么需要它：剪映会在会话中途自动升级（实测 11.6.0.14552 → 11.7.0.14652），而 11.7 的内存版
``decrypt`` 对任何输入都返回 ok=true / 0 字节 —— 导出表的 mangled 名字两版完全一致，所以 ctypes
绑定一个字都没报错，症状只是「解出来是空的」。升级器并没有删掉旧文件，而是把旧版本目录里的每个
文件改名成 ``X.dll_d_<tag>`` 留在原地，因此恢复动作就是：把这些改名残留还原成原名、复制到
``temp/`` 下的一个目录，再用 ``JIANYING_VIDEOEDITOR_DLL`` 钉住它。

纪律：
  - **只读安装目录。** 安装目录里只读不写；落点由 ``cache.assert_scratch_target`` 兜死在 temp/。
    videoeditor.dll 按所在目录解析同级依赖，所以整个集合必须一起搬，不能只拷它自己。
  - **sha256 必须核对。** 沙箱「建好了」不等于「是那一版」。给定 ``--sha256`` 时对不上就非零退出，
    绝不留下一个看起来成功、实际钉了错版本的目录（那是可复现性事故的起点）。
  - 一个目录里若同名残留多个 ``X_d_<tag>``，不猜 —— 列出来让人选。

用法:
    python scripts/rebuild_dll_sandbox.py --version-dir "D:/Program Files/JianyingPro/11.6.0.14552" \
        --out temp/dll-11.6 --sha256 8cfcbb61...99cb1
    # 然后按最后一行提示导出 JIANYING_VIDEOEDITOR_DLL
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "jy_crypto"))
from cache import WriteFenceError, assert_scratch_target  # noqa: E402

SUFFIX_SEP = "_d_"


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def logical_name(name: str) -> str:
    """``videoeditor.dll_d_17b9036`` -> ``videoeditor.dll``；没有 _d_ 尾巴的原样返回。"""
    return name.rsplit(SUFFIX_SEP, 1)[0] if SUFFIX_SEP in name else name


def collect(version_dir: Path) -> dict[str, list[Path]]:
    """按还原后的名字归组。同名多份意味着有多个升级残留叠在一起，不能替他选。"""
    groups: dict[str, list[Path]] = {}
    for f in sorted(version_dir.iterdir()):
        if f.is_file():
            groups.setdefault(logical_name(f.name), []).append(f)
    return groups


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--version-dir", required=True,
                    help="剪映版本目录（升级残留所在处），如 D:/Program Files/JianyingPro/11.6.0.14552")
    ap.add_argument("--out", required=True, help="沙箱目录，必须在 temp/ 下")
    ap.add_argument("--sha256", default="", help="期望的 videoeditor.dll sha256；不传则只报告不判定")
    ap.add_argument("--dll-name", default="videoeditor.dll")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    version_dir = Path(args.version_dir)
    if not version_dir.is_dir():
        print(f"FAIL 版本目录不存在：{version_dir}", file=sys.stderr)
        return 1

    try:
        out_dir = assert_scratch_target(Path(args.out) / ".keep").parent
    except WriteFenceError as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        return 1

    groups = collect(version_dir)
    ambiguous = {n: g for n, g in groups.items() if len(g) > 1}
    if ambiguous:
        print(f"FAIL {len(ambiguous)} 个名字有多份残留，无法判断哪份属于这一版：", file=sys.stderr)
        for n, g in sorted(ambiguous.items())[:10]:
            print(f"  {n}: " + ", ".join(f"{p.name}({sha256_of(p)[:12]})" for p in g), file=sys.stderr)
        print("  → 用单独的目录跑，或先确认这些残留来自哪次升级", file=sys.stderr)
        return 1

    wanted = groups.get(args.dll_name)
    if not wanted:
        print(f"FAIL 这个目录里没有 {args.dll_name}（也没有它的 _d_ 残留）——"
              f"升级器可能已经把旧文件真删了。", file=sys.stderr)
        return 1
    actual = sha256_of(wanted[0])
    renamed = sum(1 for g in groups.values() if SUFFIX_SEP in g[0].name)
    print(f"{args.dll_name}: {wanted[0].name}  sha256={actual}  bytes={wanted[0].stat().st_size}")
    print(f"可搬文件 {len(groups)} 个（升级残留改名 {renamed} 个、未改名 {len(groups) - renamed} 个）")

    if args.sha256:
        expect = args.sha256.strip().lower()
        if actual != expect:
            print(f"FAIL sha256 与基线不符（期望 {expect}）—— 不要钉这一版，"
                  f"先确认它是不是真的能出明文的那一个。", file=sys.stderr)
            return 1
        print("sha256 == 基线 OK")
    elif not args.dry_run:
        print("NOTE 没给 --sha256：建完不判定版本身份。钉之前请自己跑一次自往返或拿明文草稿验证。")

    if args.dry_run:
        print("dry-run：不写文件")
        return 0

    copied = 0
    for logical, files in sorted(groups.items()):
        src = files[0]
        dst = out_dir / logical
        if dst.exists() and dst.stat().st_size == src.stat().st_size:
            continue          # 幂等：temp/ 被反复重建时不重复拷 GB 级文件
        shutil.copyfile(src, dst)
        copied += 1
    print(f"写入 {copied} 个文件 -> {out_dir}")
    pinned = out_dir / args.dll_name
    if not pinned.exists():
        print(f"FAIL {pinned} 不存在，沙箱不可用", file=sys.stderr)
        return 1
    pinned_sha = sha256_of(pinned)
    print(f"验货：{pinned.name} sha256={pinned_sha}")
    if pinned_sha != actual:
        print("FAIL 沙箱里的副本与安装目录里的那份不是同一个字节串 —— 别用这个沙箱", file=sys.stderr)
        return 1
    print()
    print("下一步（当前 shell 里导出，然后所有脚本都带着它跑）：")
    print(f'  export JIANYING_VIDEOEDITOR_DLL="{pinned.resolve().as_posix()}"')
    return 0


if __name__ == "__main__":
    sys.exit(main())
