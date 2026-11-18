"""Finding 1: the outside-window check must be able to fail."""
import unittest

import numpy as np

import animation_wiring_check as awc
import render_frame as rf


class OffArmHasTeeth(unittest.TestCase):
    def setUp(self):
        self._render = awc.render
        self._flag = rf.APPLY_ANIMATIONS

    def tearDown(self):
        awc.render = self._render
        rf.APPLY_ANIMATIONS = self._flag

    def test_flag_sequence_is_on_off_on_off(self):
        seen = []

        def fake_render(model, t):
            seen.append(rf.APPLY_ANIMATIONS)
            return np.zeros((4, 4, 3), dtype=np.int16)

        awc.render = fake_render
        awc.ab_measure({}, 0.05, 0.25)
        self.assertEqual(seen, [True, False, True, False])

    def test_resident_curve_is_detected_outside_the_window(self):
        # Negative control: a curve that stays applied everywhere must produce
        # a non-zero outside difference. With the bug both arms render ON, so
        # the difference is 0 and the gate check passes on a real defect.
        def fake_render(model, t):
            value = 10 if rf.APPLY_ANIMATIONS else 0
            return np.full((4, 4, 3), value, dtype=np.int16)

        awc.render = fake_render
        got = awc.ab_measure({}, 0.05, 0.25)
        self.assertGreater(got["max_abs_outside"], 0)
        self.assertGreater(got["max_abs_inside"], 0)


if __name__ == "__main__":
    unittest.main()