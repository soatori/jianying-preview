"""Finding 5: a skipped layer must still leave a line, so the denominator cannot shrink."""
import re
import unittest
from pathlib import Path

import playback_check as pc

ROOT = Path(__file__).resolve().parents[1]

# Rows that are reports, not criteria: INFO readings and fatal-error reports.
NON_CRITERIA = {
    "L1 track coverage",
    "mix headroom (no agreed basis, Q-8)",
    "session memory (600 s criterion is separate)",
    "gateway",
    "L4 criteria",
}


class LayerRegistry(unittest.TestCase):
    def test_empty_run_reports_every_layer_as_skip(self):
        got = pc.fill_missing_checks([])
        self.assertEqual(len(got), len(pc.EXPECTED_LAYERS))
        self.assertTrue(all(state == "SKIP" for _, state, _ in got))

    def test_present_rows_are_not_duplicated_or_overwritten(self):
        one = [("L2 pixel layer", "PASS", "kept")]
        got = pc.fill_missing_checks(one)
        rows = [r for r in got if r[0] == "L2 pixel layer"]
        self.assertEqual(rows, one)
        self.assertEqual(len(got), len(pc.EXPECTED_LAYERS))

    def test_fail_rows_survive(self):
        one = [("L6 guard has teeth", "FAIL", "fixture produced no black streaks")]
        got = pc.fill_missing_checks(one)
        self.assertIn(one[0], got)

    def test_the_layers_that_used_to_vanish_are_registered(self):
        for name in ("L6 guard has teeth",
                     "L10 browser pixels (vs channel 2 and vs export, same frame)",
                     "L11 flash in/out A/B (channel 2 vs export, same frame index)",
                     "L3 video band",
                     "L9 cross-channel curve parity (browser == channel 2)"):
            self.assertIn(name, pc.EXPECTED_LAYERS)

    def test_inconsistent_name_variants_are_gone(self):
        self.assertNotIn("L0 tracked player present", pc.EXPECTED_LAYERS)
        self.assertNotIn("L11 flash in/out A/B", pc.EXPECTED_LAYERS)

    def test_every_name_main_can_emit_is_registered_or_allowlisted(self):
        src = (ROOT / "scripts" / "playback_check.py").read_text(encoding="utf-8")
        emitted = set(re.findall(r'verdict\(\s*"([^"]+)"', src))
        emitted |= set(re.findall(r'checks\.append\(\(\s*"([^"]+)"', src))
        unknown = emitted - set(pc.EXPECTED_LAYERS) - NON_CRITERIA
        self.assertEqual(unknown, set(),
                         f"emit sites not covered by the registry: {sorted(unknown)}")


    def test_skip_is_never_counted_as_passed(self):
        # 24 层没跑 + 1 层通过：旧口径印 "25 of 25 checks passed"、退出码 0。
        # passed 只许数**测过且没失败**的行（审查 5 的后半）。
        rows = [("L2 pixel layer", "PASS", "x")] + [("s%d" % i, "SKIP", "") for i in range(24)]
        self.assertEqual(pc.summary_counts(rows), (1, 24, 0))

    def test_summary_counts_distinguish_all_three_states(self):
        self.assertEqual(
            pc.summary_counts([("a", "PASS", ""), ("b", "SKIP", ""), ("c", "FAIL", "")]),
            (1, 1, 1))
        self.assertEqual(pc.summary_counts([]), (0, 0, 0))


if __name__ == "__main__":
    unittest.main()