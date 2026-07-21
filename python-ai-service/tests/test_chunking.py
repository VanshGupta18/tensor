"""Tests for structure-aware tender chunking (Phases 1–3)."""
from llama_index.core import Document

from rag_pipeline.chunking import (
    CHUNK_SCHEMA_VERSION,
    _parse_page_blocks,
    build_documents_from_pdf,
    format_chunk_header,
    split_documents,
)


def test_detects_nit_section_with_parent():
    state = {"id": "cover", "title": "Cover", "parent_id": None}
    blocks = _parse_page_blocks(1, "NOTICE INVITING TENDER\nTender Number\nABC/2026/T-1", state)
    nit = next(b for b in blocks if b.section_id == "nit")
    assert nit.parent_section_id == "cover"


def test_detects_numbered_section_parent_link():
    state = {"id": "nit", "title": "NIT", "parent_id": "cover"}
    text = "Section - 4: Bidding Forms - Technical Part of the Bid\nForm 1 content"
    blocks = _parse_page_blocks(10, text, state)
    assert state["id"] == "sec-4"
    assert blocks[0].parent_section_id == "nit"


def test_table_block_not_split():
    pages = [(5, "TABLE\nCol A    Col B\nVal 1    Val 2\nVal 3    Val 4")]
    docs = build_documents_from_pdf(pages, "hash123")
    assert docs[0].metadata["block_type"] == "table"
    nodes = split_documents(docs)
    assert len(nodes) == 1
    assert "Val 1" in nodes[0].get_content() and "Val 3" in nodes[0].get_content()


def test_prose_block_splits_into_multiple_chunks():
    long_text = "word " * 800
    pages = [(2, f"Section - 2: Eligibility\n{long_text}")]
    docs = build_documents_from_pdf(pages, "hash456")
    nodes = split_documents(docs, chunk_size=128, chunk_overlap=16)
    assert len(nodes) > 1
    assert all(n.metadata.get("chunk_id") for n in nodes)


def test_format_chunk_header_shows_parent():
    header = format_chunk_header({
        "page": 4,
        "section_title": "Section 4: Bidding Forms",
        "parent_section_id": "sec-3",
        "block_type": "text",
    })
    assert "under sec-3" in header


def test_schema_version_on_documents():
    docs = build_documents_from_pdf([(1, "hello world tender text here")], "h1")
    assert docs[0].metadata["schema_version"] == CHUNK_SCHEMA_VERSION
