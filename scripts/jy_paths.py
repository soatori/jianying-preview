r"""剪映安装位置的自动检测与本机记录（安装路径的唯一裁判）。

为什么要有这一支：安装根此前散在 9 个脚本的模块常量里，全部 pin 成
``D:\Program Files\JianyingPro\11.6.0.14552``。换机、换盘、剪映自己升级都会让这些常量
指向不存在的文件，而 subprocess 只会回一句"找不到程序"。现在按候选根扫描，取**完整安装**
里版本号最大的版本目录，并把结果记进 skill 根目录的 ``config.local.json``（已 gitignore，
不进代码历史）。

优先级：``JY_INSTALL_DIR``（精确到版本目录）> ``config.local.json`` 记录且仍然有效 > 扫描。
扫描结果会写回记录，所以下次运行不再走盘。

口径纪律：只读——本模块不写剪映目录，唯一的写操作是自己那一个配置文件；不做 PATH 兜底，
`ffmpeg()` 拿不到就报错，绝不静默换成另一个版本的 ffmpeg（换版本就是换像素）。

用法：
    python scripts/jy_paths.py            # 打印当前解析结果与候选根
    python scripts/jy_paths.py --rescan    # 忽略记录，重扫并更新
    python scripts/jy_paths.py --json      # 机器可读
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

# Windows 控制台是 GBK：读数里带中文/箭头/替换符时 print 会在最后一步抛错，把已经算完的结果
# 整个吞掉。只改错误处理策略，不改编码（和 playback_check.py 同一道闸）。
try:
    sys.stdout.reconfigure(errors="replace")      # type: ignore[attr-defined]
    sys.stderr.reconfigure(errors="replace")      # type: ignore[attr-defined]
except Exception:                                  # noqa: BLE001
    pass

SKILL_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = SKILL_ROOT / "config.local.json"
ENV_PIN = "JY_INSTALL_DIR"

# 和 jy_crypto/dll.py 同一套版本识别：必须有点分段的版本号，
# "202687173850092_1"（更新包暂存目录）拿不到号，自然排不到前面。
_VERSION_RE = re.compile(r"(?<!\d)(\d+(?:\.\d+){1,4})(?!\d)")
_MARKERS = ("ffmpeg.exe", "videoeditor.dll")


class InstallNotFound(RuntimeError):
    pass


def version_key(path: Path) -> tuple[int, ...]:
    found = _VERSION_RE.findall(path.name)
    if not found:
        return (0,)
    return max(tuple(int(p) for p in v.split(".")) for v in found)


def is_complete(path: Path) -> bool:
    """一个真正可用的安装：有 Resources/，且 ffmpeg.exe 与 videoeditor.dll 至少有一个。

    F-051 实测安装根下 15 个子目录里只有 2 个是完整安装，其余 12 个是 37~77 文件的更新载荷
    （无 Resources/、无 exe）——这条判据就是把它们筛掉的那道闸。
    """
    try:
        return path.is_dir() and (path / "Resources").is_dir() and any(
            (path / m).is_file() for m in _MARKERS)
    except OSError:
        return False


def candidate_roots() -> list[Path]:
    """默认检查的安装根（其子目录才是版本目录），按 C → D → user 顺序去重。"""
    raw: list[Path] = []
    for var in ("ProgramFiles", "ProgramFiles(x86)"):
        value = os.environ.get(var)
        if value:
            raw.append(Path(value) / "JianyingPro")
    for drive in ("C:", "D:"):
        for folder in ("Program Files", "Program Files (x86)"):
            raw.append(Path(drive + os.sep) / folder / "JianyingPro")
    for base in (os.environ.get("LOCALAPPDATA"), str(Path.home() / "AppData" / "Local")):
        if base:
            raw.append(Path(base) / "JianyingPro" / "Apps")
    out: list[Path] = []
    seen: set[str] = set()
    for path in raw:
        key = str(path).casefold().rstrip(os.sep)
        if key not in seen:
            seen.add(key)
            out.append(path)
    return out


def discovered() -> list[tuple[Path, Path]]:
    """所有候选根下的完整安装：(安装根, 版本目录)，保持候选根顺序。"""
    found: list[tuple[Path, Path]] = []
    for root in candidate_roots():
        try:
            children = sorted(root.iterdir())
        except OSError:
            continue
        found.extend((root, child) for child in children if is_complete(child))
    return found


def read_config() -> dict:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_config(install_dir: Path, method: str) -> None:
    """原子写：先 .tmp 再 os.replace，避免半截 JSON 把下次运行一起带倒。"""
    payload = {
        "install_dir": str(install_dir),
        "detected_at": datetime.now().isoformat(timespec="seconds"),
        "method": method,
    }
    tmp = CONFIG_PATH.with_suffix(".json.tmp")
    try:
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(tmp, CONFIG_PATH)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass


_cache: dict[str, Path] = {}


def install_dir(save: bool = True) -> Path:
    """当前生效的版本目录。找不到就报错，并列出查过哪些候选根。"""
    if "install_dir" in _cache:
        return _cache["install_dir"]

    pinned = os.environ.get(ENV_PIN, "").strip().strip('"')
    if pinned:
        path = Path(pinned)
        if not is_complete(path):
            raise InstallNotFound(
                f"{ENV_PIN} 指向的不是完整安装（缺 Resources/ 或 ffmpeg.exe/videoeditor.dll）：{path}")
        _cache["install_dir"] = path
        return path

    recorded = read_config().get("install_dir")
    if recorded:
        path = Path(recorded)
        if is_complete(path):
            _cache["install_dir"] = path
            return path

    picks = discovered()
    if not picks:
        raise InstallNotFound(
            "自动检测没有找到可用的剪映安装。查过这些根："
            + os.pathsep.join(str(p) for p in candidate_roots())
            + f"；如果装在不同盘，设 {ENV_PIN} 指向版本目录，或直接写 {CONFIG_PATH.name} 的 install_dir"
        )
    best = max(picks, key=lambda item: version_key(item[1]))[1]
    if save:
        write_config(best, "scan")
    _cache["install_dir"] = best
    return best


def parent_root() -> Path:
    return install_dir().parent


def guard_roots() -> list[Path]:
    """写栅栏该覆盖的目录：存在的候选根 + 配置里记录的版本目录。

    刻意不做扫描——栅栏必须在检测坏掉时照样生效，所以只用静态候选和已记录的答案。
    """
    out = [root for root in candidate_roots() if root.is_dir()]
    recorded = read_config().get("install_dir")
    if recorded:
        out.append(Path(recorded))
    return out


def resources_dir() -> Path:
    return install_dir() / "Resources"


def ffmpeg() -> Path:
    path = install_dir() / "ffmpeg.exe"
    if not path.is_file():
        raise InstallNotFound(f"检测到的安装里没有 ffmpeg.exe：{path}")
    return path


def videoeditor_dll() -> Path:
    path = install_dir() / "videoeditor.dll"
    if not path.is_file():
        raise InstallNotFound(f"检测到的安装里没有 videoeditor.dll：{path}")
    return path


def app_js_dir() -> Path:
    return resources_dir() / "canvas_agent" / "app" / "static" / "js"


def snapshot() -> dict:
    data = {"install_dir": str(install_dir()), "parent_root": str(parent_root()),
            "version": install_dir().name, "config": str(CONFIG_PATH)}
    for name, getter in (("ffmpeg", ffmpeg), ("videoeditor_dll", videoeditor_dll),
                         ("app_js", app_js_dir)):
        try:
            data[name] = str(getter())
        except InstallNotFound as exc:
            data[name] = f"缺失（{exc}）"
    return data


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--rescan", action="store_true",
                    help="忽略已有记录，重扫全部候选根并更新记录")
    ap.add_argument("--json", action="store_true", help="输出机器可读的 JSON")
    args = ap.parse_args(argv)

    if args.rescan and CONFIG_PATH.is_file():
        CONFIG_PATH.unlink()
    _cache.clear()
    try:
        data = snapshot()
    except InstallNotFound as exc:
        print(f"检测失败：{exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return 0
    for key, value in data.items():
        print(f"{key:15s} {value}")
    print(f"{'recorded':15s} {read_config().get('method', '-')}"
          f" @ {read_config().get('detected_at', '-')}")
    print(f"{'candidates':15s} {len(candidate_roots())} 个根，"
          f"{len(discovered())} 个完整安装")
    return 0


if __name__ == "__main__":
    sys.exit(main())
