"""Persistent PDF ingestion: parse -> chunk -> embed -> store in Postgres/pgvector.

Replaces the old ephemeral in-memory HybridRetriever (step3_rag_retriever.py),
which was rebuilt per upload and discarded once the request finished. Chunks
here are parsed once and persisted durably, keyed by the PDF's content hash,
so the same retrieval can power both the 9-group extraction and chat later.
"""
import functools
import os
from pathlib import Path

import fitz  # PyMuPDF

from llama_index.core import Document, VectorStoreIndex, StorageContext
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.vector_stores.types import MetadataFilter, MetadataFilters
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.vector_stores.postgres import PGVectorStore
from llama_index.storage.index_store.postgres import PostgresIndexStore

from rag_pipeline.ml_device import ML_DEVICE

POSTGRES_URL = os.getenv(
    "POSTGRES_URL", "postgresql://tenderflow:tenderflow@localhost:5433/tenderflow"
)

STORAGE_DIR = Path(__file__).parent.parent / "storage" / "documents"
STORAGE_DIR.mkdir(parents=True, exist_ok=True)

EMBED_DIM = 384  # sentence-transformers/all-MiniLM-L6-v2
EMBED_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

# ── Singletons (expensive to construct; reused across requests) ────────────

@functools.lru_cache(maxsize=None)
def get_embedding_model() -> HuggingFaceEmbedding:
    return HuggingFaceEmbedding(model_name=EMBED_MODEL_NAME, device=ML_DEVICE)


@functools.lru_cache(maxsize=None)
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


def get_storage_context() -> StorageContext:
    """Fresh per call — cheap connection wrappers, no reason to cache.

    No docstore is configured: PGVectorStore already persists node text + metadata,
    and `VectorStoreIndex` skips writing it a second time into the docstore when the
    vector store itself stores text (verified empirically — no docstore table is ever
    created). `get_document_nodes()` below reads straight from the vector store, so a
    Postgres-backed docstore would be unused weight; the index_store is kept since
    VectorStoreIndex always persists its index struct there.
    """
    return StorageContext.from_defaults(
        vector_store=get_vector_store(),
        index_store=PostgresIndexStore.from_uri(
            POSTGRES_URL, namespace="tender", use_jsonb=True
        ),
    )


def _content_hash_filter(content_hash: str) -> MetadataFilters:
    return MetadataFilters(filters=[MetadataFilter(key="content_hash", value=content_hash)])


def save_pdf(pdf_path: str, content_hash: str) -> Path:
    """Persist the raw PDF to local disk, keyed by content hash."""
    dest = STORAGE_DIR / f"{content_hash}.pdf"
    if not dest.exists():
        dest.write_bytes(Path(pdf_path).read_bytes())
    return dest


def is_ingested(content_hash: str) -> bool:
    existing = get_vector_store().get_nodes(filters=_content_hash_filter(content_hash))
    return len(existing) > 0


def ingest_pdf(pdf_path: str, content_hash: str, tender_ref: str = "") -> int:
    """Parse, chunk, embed, and persist a PDF's pages. Idempotent per content_hash —
    a re-upload of the same file skips re-embedding entirely.

    Returns the number of chunks stored (0 if the document was already indexed).
    """
    if is_ingested(content_hash):
        print(f"[ingestion] {content_hash[:12]}... already indexed, skipping")
        return 0

    save_pdf(pdf_path, content_hash)

    documents = []
    with fitz.open(pdf_path) as pdf:
        for i, page in enumerate(pdf):
            text = page.get_text()
            if not text.strip():
                continue
            documents.append(
                Document(
                    text=text,
                    id_=f"{content_hash}_page_{i + 1}",
                    metadata={"page": i + 1, "content_hash": content_hash, "tender_ref": tender_ref},
                    excluded_llm_metadata_keys=["content_hash", "tender_ref", "page"],
                    excluded_embed_metadata_keys=["content_hash", "tender_ref", "page"],
                )
            )

    if not documents:
        raise ValueError("Could not extract any text from the PDF.")

    # Chunk sizes mirror the old step3_rag_retriever.py's 1500-char/200-overlap
    # windows (~380/50 tokens at a rough 4-chars-per-token estimate).
    splitter = SentenceSplitter(chunk_size=380, chunk_overlap=50)
    nodes = splitter.get_nodes_from_documents(documents)

    VectorStoreIndex(
        nodes,
        storage_context=get_storage_context(),
        embed_model=get_embedding_model(),
        show_progress=False,
    )

    print(f"[ingestion] {content_hash[:12]}...: indexed {len(nodes)} chunks from {len(documents)} pages")
    return len(nodes)


def get_document_stats(content_hash: str) -> dict:
    """Page and chunk counts for a persisted document (used for dynamic budgets)."""
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
    """All persisted chunks for one document, as LlamaIndex nodes (page/section metadata intact)."""
    return get_vector_store().get_nodes(filters=_content_hash_filter(content_hash))
