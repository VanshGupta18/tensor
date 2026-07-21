"""Tests for document purge (cache, PDF, vectors)."""

from pathlib import Path
from unittest.mock import patch

import pytest

from rag_pipeline.ingestion import STORAGE_DIR, purge_document


def test_purge_document_rejects_invalid_hash():
    with pytest.raises(ValueError):
        purge_document("not-a-hash")


def test_purge_document_removes_pdf_and_calls_chunk_purge(tmp_path, monkeypatch):
    content_hash = "a" * 64
    pdf_path = tmp_path / f"{content_hash}.pdf"
    pdf_path.write_bytes(b"%PDF-test")

    monkeypatch.setattr("rag_pipeline.ingestion.STORAGE_DIR", tmp_path)

    with patch("rag_pipeline.ingestion._purge_document_chunks", return_value=3) as mock_chunks, \
         patch("rag_pipeline.ingestion._purge_vector_table_rows", return_value=0), \
         patch("rag_pipeline.ingestion._purge_index_store_refs", return_value=1), \
         patch("rag_pipeline.ingestion._invalidate_caches"):
        result = purge_document(content_hash)

    assert result["chunksDeleted"] == 3
    assert result["pdfDeleted"] is True
    assert result["indexRefsDeleted"] == 1
    assert not pdf_path.exists()
    mock_chunks.assert_called_once_with(content_hash)
