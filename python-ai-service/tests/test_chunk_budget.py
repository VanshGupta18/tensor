"""Tests for dynamic chunk budget scaling."""
import unittest

from rag_pipeline.chunk_budget import compute_chunk_budget, merge_and_cap_chunks
from rag_pipeline.step1_schemas import _EXTRACTION_GROUPS


class TestDynamicChunkBudget(unittest.TestCase):

    def _group(self, name):
        return next(g for g in _EXTRACTION_GROUPS if g["name"] == name)

    def test_small_doc_stays_near_minimum(self):
        g = self._group("scope_of_work")
        retrieve, chunks = compute_chunk_budget(g, page_count=12, chunk_count=24)
        self.assertEqual(chunks, g["chunk_budget"]["min_chunks"])
        self.assertEqual(retrieve, g["chunk_budget"]["min_retrieve"])

    def test_large_doc_scales_up_for_scope(self):
        g = self._group("scope_of_work")
        b = g["chunk_budget"]
        retrieve, chunks = compute_chunk_budget(g, page_count=120, chunk_count=400)
        self.assertGreater(chunks, b["min_chunks"])
        self.assertLessEqual(chunks, b["absolute_max_chunks"])
        self.assertGreater(retrieve, b["min_retrieve"])

    def test_mega_doc_600_pages_hits_absolute_max(self):
        g = self._group("scope_of_work")
        retrieve, chunks = compute_chunk_budget(g, page_count=600, chunk_count=1800)
        self.assertEqual(chunks, g["chunk_budget"]["absolute_max_chunks"])
        self.assertEqual(retrieve, g["chunk_budget"]["absolute_max_retrieve"])

    def test_mega_doc_technical_docs_highest_chunk_cap(self):
        sow = compute_chunk_budget(self._group("scope_of_work"), 600, 1800)
        tbd = compute_chunk_budget(self._group("contract_and_bidding"), 600, 1800)
        self.assertGreaterEqual(tbd[1], sow[1])

    def test_fixed_groups_use_legacy_caps(self):
        g = self._group("eligibility_and_qualification")
        retrieve, chunks = compute_chunk_budget(g, page_count=200, chunk_count=600)
        self.assertEqual(chunks, g["max_chunks"])
        self.assertEqual(retrieve, g["max_retrieve"])

    def test_tender_overview_scales_on_300_page_doc(self):
        g = self._group("tender_overview")
        retrieve, chunks = compute_chunk_budget(g, page_count=300, chunk_count=900)
        self.assertGreater(chunks, g["chunk_budget"]["max_chunks"])
        self.assertLessEqual(chunks, g["chunk_budget"]["absolute_max_chunks"])
        self.assertGreater(retrieve, g["chunk_budget"]["max_retrieve"])

    def test_merge_and_cap_never_exceeds_limit(self):
        g = self._group("contract_and_bidding")
        max_retrieve, max_chunks = compute_chunk_budget(g, 80, 250)

        def fake_retrieve(query, top_k, rerank_top_n):
            return [f"{query}_{i}" for i in range(top_k)]

        keyword_sets = [g["keywords"]] + g.get("extra_keyword_sets", [])
        chunks = merge_and_cap_chunks(keyword_sets, fake_retrieve, max_retrieve, max_chunks)
        self.assertLessEqual(len(chunks), max_chunks)

    def test_dense_doc_gets_boost_over_sparse_same_pages(self):
        g = self._group("scope_of_work")
        sparse = compute_chunk_budget(g, page_count=60, chunk_count=120)   # 2 cpp
        dense  = compute_chunk_budget(g, page_count=60, chunk_count=360)   # 6 cpp
        self.assertGreaterEqual(dense[1], sparse[1])


if __name__ == "__main__":
    unittest.main()
