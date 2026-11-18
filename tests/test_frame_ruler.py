"""Finding 8: frame_parity must use the same ruler as browser_shot_check."""
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

import browser_shot_check as bsc
import frame_parity as fp

W, H = 270, 480


class OneRuler(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory(dir="temp")
        self.addCleanup(self._dir.cleanup)
        self.root = Path(self._dir.name)

    def _png(self, name, colour):
        p = self.root / name
        Image.new("RGB", (W, H), colour).save(p)
        return p

    def test_flat_black_vs_white_is_not_a_perfect_score(self):
        black, white = self._png("b.png", (0, 0, 0)), self._png("w.png", (255, 255, 255))
        got = fp.corr(fp.luma(black, W, H), fp.luma(white, W, H))
        want = bsc.corr(bsc.luma_at(black, W, H), bsc.luma_at(white, W, H))
        self.assertEqual(got, want)
        self.assertLess(got, 0.5, "a wholly wrong flat frame must not read as perfect")

    def test_luma_matches_the_shared_ruler_pixel_for_pixel(self):
        rng = np.random.default_rng(7)
        p = self.root / "noise.png"
        Image.fromarray(rng.integers(0, 256, (960, 540, 3), dtype=np.uint8)).save(p)
        np.testing.assert_array_equal(fp.luma(p, W, H), bsc.luma_at(p, W, H))

    def test_mean_lum_matches_the_shared_ruler(self):
        p = self._png("grey.png", (128, 128, 128))
        self.assertAlmostEqual(fp.mean_lum(p, W, H), bsc.mean_lum(p, W, H), places=4)

    def test_identical_images_score_one(self):
        rng = np.random.default_rng(11)
        p = self.root / "noise.png"
        Image.fromarray(rng.integers(0, 256, (960, 540, 3), dtype=np.uint8)).save(p)
        a = fp.luma(p, W, H)
        self.assertAlmostEqual(fp.corr(a, a), 1.0, places=5)
        # 纯色帧另说：共享尺子是 float32，去均值只剩舍入残差，自点积实测 1.0000551。
        # 这里不另立精度口径，只要求读数与门那把尺**逐位相同**。
        flat = self._png("grey.png", (90, 120, 150))
        fa = fp.luma(flat, W, H)
        self.assertEqual(fp.corr(fa, fa), bsc.corr(bsc.luma_at(flat, W, H), bsc.luma_at(flat, W, H)))


if __name__ == "__main__":
    unittest.main()