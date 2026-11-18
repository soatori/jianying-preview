"""Finding 7: a transparent logo must stay transparent after colour adjustment."""
import unittest

import numpy as np
from PIL import Image

import render_frame as rf


def _seg(**values):
    return {"features": {"effect_values": values}}


class ColorAdjustAlpha(unittest.TestCase):
    def test_transparent_logo_keeps_its_alpha(self):
        logo = Image.new("RGBA", (40, 40), (255, 0, 0, 0))
        out = rf.apply_color_adjust(logo, _seg(brightness=0.2))
        self.assertEqual(out.getchannel("A").getextrema(), (0, 0))

    def test_partial_alpha_is_preserved_per_pixel(self):
        arr = np.zeros((8, 8, 4), dtype=np.uint8)
        arr[..., :3] = 120
        arr[..., 3] = np.arange(64, dtype=np.uint8).reshape(8, 8) * 4
        logo = Image.fromarray(arr, "RGBA")
        out = rf.apply_color_adjust(logo, _seg(brightness=0.1))
        self.assertEqual(out.getchannel("A").tobytes(), logo.getchannel("A").tobytes())

    def test_opaque_image_alpha_stays_opaque(self):
        img = Image.new("RGBA", (8, 8), (10, 20, 30, 255))
        out = rf.apply_color_adjust(img, _seg(brightness=0.2))
        self.assertEqual(out.getchannel("A").getextrema(), (255, 255))

    def test_no_adjustment_returns_the_same_object(self):
        img = Image.new("RGBA", (8, 8), (10, 20, 30, 128))
        self.assertIs(rf.apply_color_adjust(img, _seg()), img)
        self.assertIs(rf.apply_color_adjust(img, _seg(contrast=0.5)), img)

    def test_brightness_still_changes_the_colour(self):
        img = Image.new("RGBA", (8, 8), (100, 100, 100, 255))
        out = rf.apply_color_adjust(img, _seg(brightness=0.2))
        self.assertGreater(np.asarray(out)[..., 0].mean(), 100)


if __name__ == "__main__":
    unittest.main()