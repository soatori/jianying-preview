"""内存门禁的牙齿：三个闸都必须真的拒绝，不是装饰。

负控用 monkeypatch 把读数推到越界侧——不靠真把机器吃满来测（那正是本门禁要防的事）。
"""
import tempfile
import unittest
from pathlib import Path

import mem_gate as mg


class RequireFree(unittest.TestCase):
    def test_refuses_when_free_below_threshold(self):
        orig = mg.free_gib
        mg.free_gib = lambda: 1.0
        try:
            with self.assertRaises(SystemExit) as cm:
                mg.require_free(4.0)
            self.assertIn("MEM GATE", str(cm.exception))
        finally:
            mg.free_gib = orig

    def test_allows_when_free_above_threshold(self):
        orig = mg.free_gib
        mg.free_gib = lambda: 8.0
        try:
            self.assertEqual(mg.require_free(4.0), 8.0)
        finally:
            mg.free_gib = orig

    def test_boundary_is_inclusive(self):
        orig = mg.free_gib
        mg.free_gib = lambda: 4.0
        try:
            self.assertEqual(mg.require_free(4.0), 4.0)   # 恰好等于门槛 ⇒ 放行
        finally:
            mg.free_gib = orig

    def test_default_allows_jianying_open(self):
        # 有剪映在跑时典型余量 ~3 GiB；旧的 4 GiB 绝对门槛会把该跑的测试挡掉。
        orig = mg.free_gib
        mg.free_gib = lambda: 3.0
        try:
            self.assertEqual(mg.require_free(), 3.0)
        finally:
            mg.free_gib = orig

    def test_default_still_refuses_when_nothing_left(self):
        orig = mg.free_gib
        mg.free_gib = lambda: 0.3
        try:
            with self.assertRaises(SystemExit):
                mg.require_free()
        finally:
            mg.free_gib = orig


class PeakGuard(unittest.TestCase):
    """比例口径：自身 RSS ≤ ratio × **当前**可用内存（与绝对上限取小者）。

    两个读数都 mock 掉，保证与本机当前余量无关——否则测试结果会随剪映开不开而变。
    """

    def _guard(self, free_seq, rss_seq, load_seq=None, **kw):
        orig_free, orig_rss, orig_load = mg.free_gib, mg.rss_mb, mg.load_pct
        f = iter(free_seq)
        r = iter(rss_seq)
        l = iter(load_seq if load_seq is not None else [50.0] * 99)
        mg.free_gib = lambda: next(f)
        mg.rss_mb = lambda: next(r)
        mg.load_pct = lambda: next(l)
        g = mg.PeakGuard(**kw)
        self.addCleanup(lambda: (setattr(mg, "free_gib", orig_free),
                                 setattr(mg, "rss_mb", orig_rss),
                                 setattr(mg, "load_pct", orig_load)))
        return g

    def test_ratio_budget_is_fraction_of_free(self):
        g = self._guard([2.0], [400.0], ratio=0.25, max_rss_mb=800.0)
        # 0.25 × 2 GiB = 512 MB；400 MB 在预算内 ⇒ 放行
        self.assertEqual(g.check(), 400.0)
        self.assertAlmostEqual(g.budget_mb(2.0), 512.0)

    def test_over_ratio_aborts(self):
        g = self._guard([2.0], [600.0], ratio=0.25, max_rss_mb=800.0, label="pilot")
        with self.assertRaises(SystemExit) as cm:
            g.check()
        self.assertIn("pilot", str(cm.exception))
        self.assertIn("25%", str(cm.exception))

    def test_budget_shrinks_as_free_drops(self):
        # 关键：可用被别人吃掉时，同样的 RSS 也要被判超——预算不按起跑时定死。
        g = self._guard([10.0, 10.0, 0.4], [150.0, 150.0, 150.0], ratio=0.25)
        g.check()                      # 10 GiB → 预算 2560(截到 800)，150 放行
        g.check()
        with self.assertRaises(SystemExit):
            g.check()                  # 0.4 GiB → 预算 102 MB，150 MB 超了
        self.assertLessEqual(g.min_free_seen, 0.4)

    def test_absolute_cap_still_applies_when_free_is_huge(self):
        # 免费再多也不许超绝对上限：比例不能变成无限预算。
        g = self._guard([100.0], [900.0], ratio=0.25, max_rss_mb=800.0)
        with self.assertRaises(SystemExit):
            g.check()

    def test_summary_reports_peak_and_min_free(self):
        g = self._guard([5.0, 5.0], [120.0, 260.0], ratio=0.25)
        g.check()
        g.check()
        s = g.summary()
        self.assertIn("260.0", s)
        self.assertIn("5.00", s)


class HeavyLock(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory(dir="temp")
        self.addCleanup(self._d.cleanup)
        self.lock = Path(self._d.name) / "x.lock"

    def test_second_holder_is_refused(self):
        with mg.heavy_lock(self.lock):
            self.assertTrue(self.lock.is_file())
            with self.assertRaises(SystemExit) as cm:
                with mg.heavy_lock(self.lock):
                    pass
            self.assertIn("只允许 1 个", str(cm.exception))

    def test_lock_released_on_exit(self):
        with mg.heavy_lock(self.lock):
            pass
        self.assertFalse(self.lock.is_file())
        with mg.heavy_lock(self.lock):   # 释放后能再拿
            pass

    def test_lock_released_on_exception(self):
        with self.assertRaises(ValueError):
            with mg.heavy_lock(self.lock):
                raise ValueError("boom")
        self.assertFalse(self.lock.is_file())

    def test_stale_lock_is_reclaimed(self):
        self.lock.write_text("999999 0\n")
        import os
        old = self.lock.stat().st_mtime - 99999
        os.utime(self.lock, (old, old))
        with mg.heavy_lock(self.lock, stale_seconds=10.0):
            self.assertIn(str(os.getpid()), self.lock.read_text())


class LoadStop(unittest.TestCase):
    """硬停线：系统占用 ≥90% 立即中止——**不看我们自己占多少**。"""

    def test_load_over_90_aborts_even_with_tiny_rss(self):
        g = mg.PeakGuard(label="t")
        orig = mg.free_gib, mg.rss_mb, mg.load_pct
        mg.free_gib, mg.rss_mb, mg.load_pct = lambda: 5.0, lambda: 10.0, lambda: 91.5
        try:
            with self.assertRaises(SystemExit) as cm:
                g.check()
            self.assertIn("91.5%", str(cm.exception))
            self.assertIn("90%", str(cm.exception))
        finally:
            mg.free_gib, mg.rss_mb, mg.load_pct = orig

    def test_load_under_90_passes(self):
        g = mg.PeakGuard(label="t")
        orig = mg.free_gib, mg.rss_mb, mg.load_pct
        mg.free_gib, mg.rss_mb, mg.load_pct = lambda: 5.0, lambda: 10.0, lambda: 89.9
        try:
            self.assertEqual(g.check(), 10.0)
            self.assertAlmostEqual(g.max_load_seen, 89.9)
        finally:
            mg.free_gib, mg.rss_mb, mg.load_pct = orig

    def test_load_boundary_is_inclusive(self):
        g = mg.PeakGuard(label="t")
        orig = mg.free_gib, mg.rss_mb, mg.load_pct
        mg.free_gib, mg.rss_mb, mg.load_pct = lambda: 5.0, lambda: 10.0, lambda: 90.0
        try:
            with self.assertRaises(SystemExit):     # 恰好 90 ⇒ 停
                g.check()
        finally:
            mg.free_gib, mg.rss_mb, mg.load_pct = orig

    def test_require_free_refuses_at_90(self):
        orig = mg.free_gib, mg.load_pct
        mg.free_gib, mg.load_pct = lambda: 5.0, lambda: 92.0
        try:
            with self.assertRaises(SystemExit) as cm:
                mg.require_free()
            self.assertIn("92.0%", str(cm.exception))
        finally:
            mg.free_gib, mg.load_pct = orig


class RealReadings(unittest.TestCase):
    def test_free_and_rss_are_plausible(self):
        self.assertGreater(mg.free_gib(), 0.0)
        self.assertGreater(mg.rss_mb(), 1.0)      # 本进程自己总得占点
        self.assertLess(mg.rss_mb(), mg.TARGET_RSS_MB)   # 测试进程本身必须轻（<300 MB 目标线）