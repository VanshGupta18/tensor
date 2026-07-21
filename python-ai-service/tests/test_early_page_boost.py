"""Tests for early-page chunk boost used by tender_overview retrieval."""
import unittest

from rag_pipeline.chunk_budget import merge_boost_early_pages


class TestEarlyPageBoost(unittest.TestCase):

    def test_early_chunks_prepended(self):
        early = ["[PAGE 1]\nNIT cover", "[PAGE 2]\nTender No ABC"]
        retrieved = ["[PAGE 50]\nEMD details", "[PAGE 1]\nNIT cover"]
        out = merge_boost_early_pages(retrieved, early, max_chunks=4, min_early_slots=2)
        self.assertEqual(out[0], "[PAGE 1]\nNIT cover")
        self.assertEqual(out[1], "[PAGE 2]\nTender No ABC")
        self.assertLessEqual(len(out), 4)

    def test_early_slots_survive_cap(self):
        early = [f"[PAGE {i}]\nearly {i}" for i in range(1, 7)]
        retrieved = [f"[PAGE {i+20}]\nlate {i}" for i in range(1, 20)]
        out = merge_boost_early_pages(retrieved, early, max_chunks=8, min_early_slots=4)
        self.assertEqual(len(out), 8)
        self.assertTrue(all("early" in c for c in out[:4]))


if __name__ == "__main__":
    unittest.main()
