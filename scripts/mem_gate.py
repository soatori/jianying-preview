"""重负进程的内存门禁：跑前查 free、跑中盯自身 RSS、串行锁。

为什么是硬报错而不是口头约定：本机 16 GB，桌面底数（Doubao ~2.4 GB、Qoder worker、
Memory Compression、HipsDaemon 等）已占去大半；2026-11-18 两次把 free 顶到 0.00–0.07 GB，
一次 MemoryError + fork failure，一次系统卡死重启。约定靠不住，入口必须自己拒绝。

三个闸：
  require_free(min_gib)  跑前 free 不够 ⇒ SystemExit，不开新负
  PeakGuard(max_rss_mb)  跑中自身 RSS 超限 ⇒ SystemExit，提示改小批次
  heavy_lock()           同一时刻只允许 1 个重负进程（O_EXCL 锁文件）
"""
from __future__ import annotations

import ctypes
import os
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "temp" / ".heavy.lock"
# 有剪映在跑时（它自己就 3 GiB+），绝对门槛会把该跑的测试也挡掉，所以改成**比例**口径：
# 我们自己的 RSS 不许超过**当前可用内存**的 DEFAULT_RATIO；起跑另设一个很低的绝对底线。
# 比例可以在调用处覆盖（peak ratio 也随每次 check 重算，不是起跑时定死）。
DEFAULT_RATIO = 0.25
DEFAULT_MAX_RSS_MB = 800.0        # 绝对兜底上限（与比例取较小者生效）
DEFAULT_MIN_FREE_GIB = 1.0        # 起跑底线：可用不足 1 GiB 就不跑
TARGET_RSS_MB = 300.0             # 目标线，超了只警告不中止
MAX_LOAD_PCT = 90.0               # **硬停线**：系统占用 ≥90% 立即中止（用户口径）


class _M(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


class _PMC(ctypes.Structure):
    _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]


def free_gib() -> float:
    m = _M()
    m.dwLength = ctypes.sizeof(_M)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    return m.ullAvailPhys / 2 ** 30


def load_pct() -> float:
    """系统内存占用百分比（GlobalMemoryStatusEx.dwMemoryLoad）。90% 是硬停线。"""
    m = _M()
    m.dwLength = ctypes.sizeof(_M)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    return float(m.dwMemoryLoad)


def rss_mb() -> float:
    # 必须显式声明原型：GetCurrentProcess 返回 HANDLE，不设 restype 会被 ctypes 当 c_int
    # 截断，GetProcessMemoryInfo 就失败。第一版正是这样静默返回 0.0 ⇒ PeakGuard 永不触发
    # （哑仪器，本仓库反复栽的那一族）。读不到就抛，绝不返回 0 让闸静默放行。
    k32 = ctypes.windll.kernel32
    k32.GetCurrentProcess.restype = ctypes.c_void_p
    fn = getattr(k32, "GetProcessMemoryInfo", None) or ctypes.windll.psapi.GetProcessMemoryInfo
    fn.argtypes = [ctypes.c_void_p, ctypes.POINTER(_PMC), ctypes.c_ulong]
    fn.restype = ctypes.c_bool
    c = _PMC()
    c.cb = ctypes.sizeof(_PMC)
    if not fn(k32.GetCurrentProcess(), ctypes.byref(c), c.cb):
        raise RuntimeError("MEM GATE 读不到自身 RSS（GetProcessMemoryInfo 失败）⇒ 拒绝继续，"
                           "不许在无法计量的情况下跑重负。")
    return c.WorkingSetSize / 2 ** 20


def require_free(min_gib: float = DEFAULT_MIN_FREE_GIB,
                 max_load_pct: float = MAX_LOAD_PCT) -> float:
    """跑前闸：系统占用 ≥90% 或可用 <底线 就硬报错，绝不"先跑起来再看"。"""
    got = free_gib()
    load = load_pct()
    if load >= max_load_pct:
        raise SystemExit(
            f"MEM GATE 拒绝启动：系统内存占用 {load:.1f}% ≥ {max_load_pct:.0f}%"
            f"（可用 {got:.2f} GiB）。先腾出余量再来，不开新负。")
    if got < min_gib:
        raise SystemExit(
            f"MEM GATE 拒绝启动：可用物理内存 {got:.2f} GiB < 底线 {min_gib:.1f} GiB"
            f"（当前占用 {load:.1f}%）。先释放已有子进程/等环境腾出余量，再来。不开新负。")
    return got


class PeakGuard:
    """跑中闸：**比例**口径——自身 RSS 不许超过「ratio × 当前可用内存」，与绝对上限取小者。

    比例每次 check 都重算（不按起跑时的可用内存定死）：可用被别的进程吃掉时预算自动收紧，
    这样"跑着跑着系统没余量"也会被拦下，而不是等我们自己涨到绝对上限才拦。
    """

    def __init__(self, max_rss_mb: float = DEFAULT_MAX_RSS_MB, label: str = "",
                 ratio: float = DEFAULT_RATIO, max_load_pct: float = MAX_LOAD_PCT):
        self.max = float(max_rss_mb)
        self.ratio = float(ratio)
        self.max_load = float(max_load_pct)
        self.label = label or "heavy"
        self.peak = 0.0
        self.min_free_seen = float("inf")
        self.max_load_seen = 0.0

    def budget_mb(self, free: float | None = None) -> float:
        """当前预算 = min(绝对上限, ratio × 可用 GiB)。"""
        f = free_gib() if free is None else free
        return min(self.max, self.ratio * f * 1024)

    def check(self) -> float:
        got = rss_mb()
        free = free_gib()
        load = load_pct()
        self.peak = max(self.peak, got)
        self.min_free_seen = min(self.min_free_seen, free)
        self.max_load_seen = max(self.max_load_seen, load)
        # 硬停线在最前：系统占用一过 90% 立即停，不看我们自己占多少。
        if load >= self.max_load:
            raise SystemExit(
                f"MEM GATE 立即中止 {self.label}：系统内存占用 {load:.1f}% ≥ {self.max_load:.0f}%"
                f"（可用 {free:.2f} GiB，自身 RSS {got:.0f} MB）。"
                f"本轮峰值 RSS {self.peak:.0f} MB、最低可用 {self.min_free_seen:.2f} GiB、"
                f"最高占用 {self.max_load_seen:.1f}%。")
        budget = self.budget_mb(free)
        if got > budget:
            raise SystemExit(
                f"MEM GATE 中止 {self.label}：自身 RSS {got:.0f} MB > 预算 {budget:.0f} MB"
                f"（= {self.ratio:.0%} × 当前可用 {free:.2f} GiB；绝对上限 {self.max:.0f} MB）。"
                f"本轮峰值 {self.peak:.0f} MB、最低可用 {self.min_free_seen:.2f} GiB。"
                f"改小批次再跑，不许放宽比例。")
        return got

    def summary(self) -> str:
        return (f"峰值 RSS {self.peak:.1f} MB"
                + ("（超 300 MB 目标线）" if self.peak > TARGET_RSS_MB else "（≤300 MB 目标线）")
                + f"；期间最低可用 {self.min_free_seen:.2f} GiB、最高占用 {self.max_load_seen:.1f}%")


class heavy_lock:
    """串行闸：O_EXCL 建锁文件，抢不到就报错退出。陈旧锁（进程已死）可回收。"""

    def __init__(self, path: Path = LOCK, stale_seconds: float = 7200.0):
        self.path = Path(path)
        self.stale = stale_seconds
        self.fd = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for attempt in (0, 1):
            try:
                self.fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(self.fd, f"{os.getpid()} {time.time():.0f}\n".encode())
                return self
            except FileExistsError:
                age = time.time() - self.path.stat().st_mtime
                if attempt == 0 and age > self.stale:
                    self.path.unlink(missing_ok=True)   # 陈旧锁：持有者早死了
                    continue
                raise SystemExit(
                    f"MEM GATE 拒绝启动：已有重负进程持锁 {self.path}（{age:.0f}s 前）。"
                    f"同一时刻只允许 1 个重负进程，等它跑完再来。")
        return self

    def __exit__(self, *exc):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        self.path.unlink(missing_ok=True)
        return False