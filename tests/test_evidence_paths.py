"""Finding 9: census output must land in the tracked tables, not a dead docs/ tree."""
import importlib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULES = ("field_census", "track_matrix", "track_flag_census",
           "render_index_allocators", "mixmode_join")


class EvidencePaths(unittest.TestCase):
    def test_out_points_at_the_tracked_tables(self):
        want = (ROOT / "evidence" / "tables").resolve()
        self.assertTrue(want.is_dir(), f"missing {want}")
        for name in MODULES:
            with self.subTest(module=name):
                mod = importlib.import_module(name)
                self.assertEqual(Path(mod.OUT).resolve(), want)

    def test_js_model_extract_root_is_the_repo(self):
        mod = importlib.import_module("js_model_extract")
        self.assertEqual(Path(mod.ROOT).resolve(), ROOT.resolve())
        self.assertEqual(Path(mod.OUT).resolve(), (ROOT / "evidence" / "tables").resolve())

    def test_glsl_join_is_not_empty(self):
        mod = importlib.import_module("mixmode_join")
        table = mod.load_glsl()
        self.assertTrue(table, "load_glsl() returned {} — it is reading a path that does not exist")
        self.assertTrue(all(len(k) == 32 for k in table), list(table)[:3])


if __name__ == "__main__":
    unittest.main()