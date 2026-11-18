"""Finding 6: a POST body must not be able to name a file outside temp/."""
import unittest
from pathlib import Path

import preview_gateway as gw


class SafeTag(unittest.TestCase):
    def test_traversal_cannot_escape_the_scratch_root(self):
        out = gw.OUT.resolve()
        for tag in ("../../../../../../../../temp/pwned",
                    "..\\..\\..\\windows\\temp\\pwned",
                    "/etc/passwd", "C:/Windows/evil", "C:\\Windows\\evil",
                    "\\\\server\\share\\evil", "....", ".", ""):
            with self.subTest(tag=tag):
                name = f"report-{gw.safe_tag(tag)}.jsonl"
                resolved = (gw.OUT / name).resolve()
                self.assertTrue(str(resolved).startswith(str(out)),
                                f"{tag!r} escaped to {resolved}")

    def test_allowed_characters_survive(self):
        self.assertEqual(gw.safe_tag("check0"), "check0")
        self.assertEqual(gw.safe_tag("live-pacing_2.jsonl"), "live-pacing_2.jsonl")

    def test_result_is_never_empty_and_never_leading_dot(self):
        for tag in ("", ".", "..", "///", "..."):
            got = gw.safe_tag(tag)
            self.assertTrue(got)
            self.assertFalse(got.startswith("."))

    def test_length_is_bounded(self):
        self.assertLessEqual(len(gw.safe_tag("x" * 500)), 60)

    def test_separators_are_removed_not_replaced_by_traversal(self):
        got = gw.safe_tag("a/b\\c")
        self.assertNotIn("/", got)
        self.assertNotIn("\\", got)

    def test_gate_tags_are_byte_identical(self):
        # Step 5: report filenames the gate reads must not change.
        for tag in ("playback", "livepacing", "shot"):
            self.assertEqual(gw.safe_tag(tag), tag)


if __name__ == "__main__":
    unittest.main()