"""Tests for section-scoped retrieval helpers."""
from llama_index.core.schema import NodeWithScore, TextNode

from rag_pipeline.retrieval import _boost_section_order, _nodes_for_scope


def _ns(section_id, score=0.5):
    node = TextNode(text="x", metadata={"section_id": section_id})
    return NodeWithScore(node=node, score=score)


def test_boost_section_order_puts_target_sections_first():
    nodes = [_ns("sec-6"), _ns("sec-99"), _ns("sec-2")]
    ordered = _boost_section_order(nodes, ["sec-2", "sec-6"])
    ids = [(n.node.metadata or {}).get("section_id") for n in ordered]
    assert ids[:2] == ["sec-6", "sec-2"]


def test_nodes_for_scope_falls_back_when_sparse():
    all_nodes = [_ns("sec-1").node, _ns("sec-99").node]
    scoped = _nodes_for_scope(all_nodes, ["sec-1"])
    assert len(scoped) == 2  # only 1 match — below threshold of 6
