"""Tests that merged chunks never exceed the computed budget cap."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rag_pipeline.chunk_budget import compute_chunk_budget, merge_and_cap_chunks
from rag_pipeline.step1_schemas import _EXTRACTION_GROUPS


class TestChunkCap(unittest.TestCase):

    def _cap_chunks(self, group, page_count=40, chunk_count=120, fake_per_pass=30):
        max_retrieve, max_chunks = compute_chunk_budget(group, page_count, chunk_count)
        call_counter = [0]

        def fake_retrieve(query, top_k, rerank_top_n):
            call_counter[0] += 1
            base = call_counter[0] * 1000
            return [f"chunk_{base}_{i}" for i in range(min(top_k, fake_per_pass))]

        keyword_sets = [group["keywords"]] + group.get("extra_keyword_sets", [])
        chunks = merge_and_cap_chunks(keyword_sets, fake_retrieve, max_retrieve, max_chunks)
        return chunks, max_chunks

    def test_all_groups_respect_budget_cap(self):
        for group in _EXTRACTION_GROUPS:
            with self.subTest(group=group["name"]):
                chunks, max_chunks = self._cap_chunks(group)
                self.assertLessEqual(len(chunks), max_chunks)

    def test_dynamic_groups_have_chunk_budget(self):
        for name in ("scope_of_work", "contract_and_bidding", "price_variation"):
            g = next(x for x in _EXTRACTION_GROUPS if x["name"] == name)
            self.assertIn("chunk_budget", g)
            b = g["chunk_budget"]
            self.assertGreater(b["max_chunks"], b["min_chunks"])
            self.assertGreater(b["max_retrieve"], b["min_retrieve"])

    def test_fewer_available_chunks_not_padded(self):
        for group in _EXTRACTION_GROUPS:
            with self.subTest(group=group["name"]):
                chunks, max_chunks = self._cap_chunks(group, fake_per_pass=1)
                num_passes = len([group["keywords"]] + group.get("extra_keyword_sets", []))
                self.assertLessEqual(len(chunks), num_passes)


if __name__ == "__main__":
    unittest.main()
