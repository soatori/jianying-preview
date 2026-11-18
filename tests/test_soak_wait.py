"""Finding 3: waiting for the page must not spin at 100% CPU."""
import tempfile
import unittest
from pathlib import Path

import browser_soak as bs


class FakeProc:
    def __init__(self):
        self.exited = False

    def poll(self):
        return 1 if self.exited else None


class WaitLoop(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory(dir="temp/parallel/task7")
        self.addCleanup(self._dir.cleanup)
        self.report = Path(self._dir.name) / "report.jsonl"
        self.report.write_text("one\n", encoding="utf-8")

    def _run(self, seconds, grow_after=None, timeout=0):
        clock = {"t": 0.0}
        naps = []

        def now():
            return clock["t"]

        def sleep(dt):
            naps.append(dt)
            clock["t"] += dt
            if grow_after is not None and len(naps) >= grow_after:
                self.report.write_text("one\ntwo\n", encoding="utf-8")

        bs.wait_for_report(FakeProc(), self.report, 1, seconds, timeout,
                           sleep=sleep, now=now)
        return naps, clock["t"]

    def test_it_sleeps_between_polls(self):
        naps, _ = self._run(seconds=5)
        self.assertTrue(naps, "the wait loop never slept — it is spinning")
        self.assertTrue(all(dt > 0 for dt in naps))

    def test_iteration_count_is_bounded_by_the_sleep(self):
        naps, elapsed = self._run(seconds=5)
        self.assertLessEqual(len(naps), 5 / min(naps) + 2)
        self.assertGreaterEqual(elapsed, 5)

    def test_it_stops_as_soon_as_the_report_grows(self):
        naps, elapsed = self._run(seconds=600, grow_after=2)
        self.assertLessEqual(len(naps), 3)
        self.assertLess(elapsed, 600)

    def test_it_stops_when_chrome_exits(self):
        proc = FakeProc()
        proc.exited = True
        naps = []
        bs.wait_for_report(proc, self.report, 1, 600, 0,
                           sleep=lambda dt: naps.append(dt), now=lambda: 0.0)
        self.assertEqual(naps, [])

    def test_a_missing_report_does_not_spin(self):
        clock = {"t": 0.0}
        naps = []

        def sleep(dt):
            naps.append(dt)
            clock["t"] += dt

        bs.wait_for_report(FakeProc(), Path(self._dir.name) / "absent.jsonl", 0, 3, 0,
                           sleep=sleep, now=lambda: clock["t"])
        self.assertTrue(naps)
        self.assertLessEqual(len(naps), 3 / min(naps) + 2)

    def test_timeout_terminates_the_wait(self):
        naps, elapsed = self._run(seconds=600, timeout=2)
        self.assertTrue(naps)
        self.assertLessEqual(len(naps), 2 / min(naps) + 2)
        self.assertGreaterEqual(elapsed, 2)
        self.assertLess(elapsed, 600)


if __name__ == "__main__":
    unittest.main()