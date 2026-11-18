"""Finding 2: an unresolved material must be reported, not crash the build."""
import unittest
from pathlib import Path

import playback_model as pm


def _seg(**kw):
    base = {"id": "S1",
            "target_timerange": {"start": 0, "duration": 1_000_000},
            "source_timerange": {"start": 0, "duration": 1_000_000}}
    base.update(kw)
    return base


class MaterialResolution(unittest.TestCase):
    def setUp(self):
        self.model = pm.Model({"materials": {}, "tracks": []}, Path("."))

    def test_dangling_material_id_is_reported(self):
        out = self.model.segment(_seg(material_id="NOPE"), {"type": "video"})
        self.assertEqual(out["material"]["id"], "NOPE")
        self.assertIsNone(out["material"]["type"])
        self.assertTrue(any("dangling material_id" in e for e in self.model.errors),
                        self.model.errors)

    def test_absent_material_id_is_reported(self):
        out = self.model.segment(_seg(), {"type": "video"})
        self.assertIsNone(out["material"]["bucket"])
        self.assertTrue(any("dangling material_id" in e for e in self.model.errors),
                        self.model.errors)

    def test_resolved_material_still_works(self):
        model = pm.Model({"materials": {"videos": [{"id": "V1", "type": "video"}]},
                          "tracks": []}, Path("."))
        out = model.segment(_seg(material_id="V1"), {"type": "video"})
        self.assertEqual(out["material"]["bucket"], "videos")
        self.assertEqual(out["material"]["type"], "video")
        self.assertEqual(model.errors, [])


if __name__ == "__main__":
    unittest.main()