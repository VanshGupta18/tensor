"""Tests for tender document graph (Phase 5)."""
from llama_index.core.schema import TextNode

from rag_pipeline.tender_graph import TenderGraph


def _node(chunk_id, block_id, section_id, parent=None, idx=0, text="x"):
    return TextNode(
        text=text,
        id_=chunk_id,
        metadata={
            "chunk_id": chunk_id,
            "block_id": block_id,
            "section_id": section_id,
            "parent_section_id": parent or "",
            "section_title": section_id,
            "chunk_index": idx,
            "page": 1,
        },
    )


def test_graph_tracks_block_siblings():
    nodes = [
        _node("c1", "b1", "sec-1", idx=0, text="row1"),
        _node("c2", "b1", "sec-1", idx=1, text="row2"),
        _node("c3", "b1", "sec-1", idx=2, text="row3"),
    ]
    g = TenderGraph.from_nodes(nodes)
    expanded = g.expand_chunk_ids(["c2"], max_siblings=1)
    assert set(expanded) == {"c1", "c2", "c3"}


def test_graph_includes_parent_section_header():
    nodes = [
        _node("hdr", "b0", "sec-3", idx=0, text="Section 3 header"),
        _node("c1", "b1", "sec-4", parent="sec-3", idx=0, text="form row"),
    ]
    g = TenderGraph.from_nodes(nodes)
    expanded = g.expand_chunk_ids(["c1"], max_siblings=0, include_parent_header=True)
    assert "hdr" in expanded
    assert "c1" in expanded
