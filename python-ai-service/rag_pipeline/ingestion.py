"""Persistent PDF ingestion: parse -> chunk -> embed -> store in Postgres/pgvector."""
import functools
import json
import os
from pathlib import Path

import fitz  # PyMuPDF

from llama_index.core import VectorStoreIndex, StorageContext
from llama_index.core.vector_stores.types import MetadataFilter, MetadataFilters
from llama_index.embeddings.fastembed import FastEmbedEmbedding
from llama_index.vector_stores.postgres import PGVectorStore
from llama_index.storage.index_store.postgres import PostgresIndexStore

from rag_pipeline.chunking import (
    CHUNK_SCHEMA_VERSION,
    build_documents_from_pdf,
    split_documents,
)

def _resolve_postgres_url() -> str:
    vcap = os.getenv("VCAP_SERVICES")
    if vcap:
        for instances in json.loads(vcap).values():
            for instance in instances:
                creds = instance.get("credentials", {})
                uri = creds.get("uri")
                if uri:
                    return uri.replace("postgres://", "postgresql://", 1)
                if creds.get("hostname") and creds.get("password"):
                    return (
                        f"postgresql://{creds['username']}:{creds['password']}"
                        f"@{creds['hostname']}:{creds.get('port', 5432)}/{creds['dbname']}"
                    )
    return os.getenv(
        "POSTGRES_URL", "postgresql://tenderflow:tenderflow@localhost:5433/tenderflow"
    )


POSTGRES_URL = _resolve_postgres_url()

STORAGE_DIR = Path(__file__).parent.parent / "storage" / "documents"
STORAGE_DIR.mkdir(parents=True, exist_ok=True)

# FastEmbed ONNX — lightweight local embeddings (no torch)
EMBED_MODEL_NAME = "BAAI/bge-small-en-v1.5"
EMBED_DIM = 384


@functools.lru_cache(maxsize=1)
def get_embedding_model() -> FastEmbedEmbedding:
    return FastEmbedEmbedding(
        model_name=EMBED_MODEL_NAME,
        threads=4,
        doc_embed_type="passage",
    )


@functools.lru_cache(maxsize=1)
def get_vector_store() -> PGVectorStore:
    return PGVectorStore.from_params(
        connection_string=POSTGRES_URL,
        async_connection_string=POSTGRES_URL.replace(
            "postgresql://", "postgresql+asyncpg://"
        ),
        table_name="tender_chunks",
        embed_dim=EMBED_DIM,
        use_jsonb=True,
    )


def _content_hash_filter(content_hash: str) -> MetadataFilters:
    return MetadataFilters(filters=[MetadataFilter(key="content_hash", value=content_hash)])


def _invalidate_caches() -> None:
    from rag_pipeline.retrieval import invalidate_retrieval_cache
    from rag_pipeline.tender_graph import get_tender_graph

    get_tender_graph.cache_clear()
    invalidate_retrieval_cache()


def save_pdf(pdf_path: str, content_hash: str) -> Path:
    dest = STORAGE_DIR / f"{content_hash}.pdf"
    if not dest.exists():
        dest.write_bytes(Path(pdf_path).read_bytes())
    return dest


def _purge_document_chunks(content_hash: str) -> int:
    vs = get_vector_store()
    nodes = vs.get_nodes(filters=_content_hash_filter(content_hash))
    if not nodes:
        return 0
    node_ids = [n.node_id for n in nodes if n.node_id]
    if node_ids:
        vs.delete_nodes(node_ids)
    _invalidate_caches()
    return len(node_ids)


def is_ingested(content_hash: str) -> bool:
    existing = get_vector_store().get_nodes(filters=_content_hash_filter(content_hash))
    if not existing:
        return False
    for node in existing[:5]:
        meta = node.metadata or {}
        stored_ver = meta.get("schema_version")
        if stored_ver != CHUNK_SCHEMA_VERSION:
            print(
                f"[ingestion] schema v{stored_ver or 'legacy'} → v{CHUNK_SCHEMA_VERSION}, "
                "will re-index"
            )
            _purge_document_chunks(content_hash)
            return False
    return True


def ingest_pdf(pdf_path: str, content_hash: str, tender_ref: str = "") -> int:
    if is_ingested(content_hash):
        print(f"[ingestion] {content_hash[:12]}... already indexed, skipping")
        return 0

    save_pdf(pdf_path, content_hash)

    pages: list[tuple[int, str]] = []
    with fitz.open(pdf_path) as pdf:
        for i, page in enumerate(pdf):
            text = page.get_text()
            if text.strip():
                pages.append((i + 1, text))

    if not pages:
        raise ValueError("Could not extract any text from the PDF.")

    documents = build_documents_from_pdf(pages, content_hash, tender_ref)
    nodes = split_documents(documents)

    VectorStoreIndex(
        nodes,
        storage_context=StorageContext.from_defaults(
            vector_store=get_vector_store(),
            index_store=PostgresIndexStore.from_uri(
                POSTGRES_URL, namespace="tender", use_jsonb=True
            ),
        ),
        embed_model=get_embedding_model(),
        show_progress=False,
    )

    _invalidate_caches()
    print(
        f"[ingestion] {content_hash[:12]}...: indexed {len(nodes)} chunks from "
        f"{len(pages)} pages (fastembed/{EMBED_MODEL_NAME})"
    )
    return len(nodes)


def get_document_stats(content_hash: str) -> dict:
    nodes = get_document_nodes(content_hash)
    if not nodes:
        return {"page_count": 0, "chunk_count": 0, "chunks_per_page": 0.0}

    pages = set()
    for node in nodes:
        page = (node.metadata or {}).get("page")
        if page is not None:
            pages.add(int(page))

    page_count = len(pages) if pages else max(1, len(nodes) // 3)
    chunk_count = len(nodes)
    return {
        "page_count": page_count,
        "chunk_count": chunk_count,
        "chunks_per_page": round(chunk_count / max(page_count, 1), 2),
    }


def get_document_nodes(content_hash: str):
    return get_vector_store().get_nodes(filters=_content_hash_filter(content_hash))


def _purge_index_store_refs(content_hash: str) -> int:
    """Remove llama-index index-store rows referencing this document hash."""
    try:
        import psycopg2

        conn = psycopg2.connect(POSTGRES_URL)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM data_indexstore
                    WHERE namespace = %s
                      AND value::text LIKE %s
                    """,
                    ("tender", f"%{content_hash}%"),
                )
                deleted = cur.rowcount
            conn.commit()
            return deleted
        finally:
            conn.close()
    except Exception as exc:
        print(f"[ingestion] index store purge skipped: {exc}")
        return 0


def _purge_vector_table_rows(content_hash: str) -> int:
    """SQL fallback — delete any remaining pgvector rows for this hash."""
    try:
        import psycopg2

        conn = psycopg2.connect(POSTGRES_URL)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM tender_chunks
                    WHERE metadata_->>'content_hash' = %s
                    """,
                    (content_hash,),
                )
                deleted = cur.rowcount
            conn.commit()
            return deleted
        finally:
            conn.close()
    except Exception as exc:
        print(f"[ingestion] vector table purge skipped: {exc}")
        return 0


def purge_document(content_hash: str) -> dict:
    """
    Remove all persisted AI/RAG artifacts for *content_hash*:
    pgvector chunks, index-store refs, and the local PDF copy.
    """
    if not content_hash or len(content_hash) != 64:
        raise ValueError("content_hash must be a 64-char SHA-256 hex string")

    chunks_deleted = _purge_document_chunks(content_hash)
    sql_chunks_deleted = _purge_vector_table_rows(content_hash)
    index_refs_deleted = _purge_index_store_refs(content_hash)

    pdf_path = STORAGE_DIR / f"{content_hash}.pdf"
    pdf_deleted = False
    if pdf_path.exists():
        pdf_path.unlink()
        pdf_deleted = True

    _invalidate_caches()

    return {
        "contentHash": content_hash,
        "chunksDeleted": max(chunks_deleted, sql_chunks_deleted),
        "indexRefsDeleted": index_refs_deleted,
        "pdfDeleted": pdf_deleted,
    }
