"""Dense + BM25 retrieval (RRF-fused, reranked) over persisted chunks.

Shared by extraction (step5_extractor.py) and citation-grounded chat
(step6_chat.py) — both read from the same durable per-document index
built by ingestion.py.
"""
import functools
import threading

from llama_index.core import VectorStoreIndex
from llama_index.core.postprocessor import SentenceTransformerRerank
from llama_index.core.retrievers import QueryFusionRetriever
from llama_index.retrievers.bm25 import BM25Retriever

from rag_pipeline.ingestion import (
    _content_hash_filter,
    get_document_nodes,
    get_embedding_model,
    get_vector_store,
)


def get_early_page_chunks(content_hash: str, max_page: int = 8, max_chunks: int = 8) -> list:
    """Return chunks from the first N pages — NIT/tender reference is almost always there."""
    nodes = get_document_nodes(content_hash)
    if not nodes:
        return []

    by_page: dict = {}
    for node in nodes:
        page = (node.metadata or {}).get("page")
        if page is None or int(page) > max_page:
            continue
        by_page.setdefault(int(page), []).append(node)

    out = []
    for page in sorted(by_page.keys()):
        for node in by_page[page]:
            out.append(f"[PAGE {page}]\n{node.get_content()}")
            if len(out) >= max_chunks:
                return out
    return out
from rag_pipeline.ml_device import ML_DEVICE

# Smaller cross-encoder (~90MB vs ~1.1GB for bge-reranker-base).
RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"

# Reranker inference is not thread-safe under concurrent extraction groups —
# this lock serializes calls to postprocess_nodes() below (unrelated to caching).
_reranker_lock = threading.Lock()


@functools.lru_cache(maxsize=None)
def _get_global_reranker() -> SentenceTransformerRerank:
    return SentenceTransformerRerank(model=RERANKER_MODEL, top_n=100, device=ML_DEVICE)


# Capped at 5 entries to prevent unbounded RAM growth across many tenders.
@functools.lru_cache(maxsize=5)
def _build_index(content_hash: str):
    """Build (and cache) the BM25 + vector index pair for one document."""
    nodes = get_document_nodes(content_hash)
    if not nodes:
        return None
    index = VectorStoreIndex.from_vector_store(
        vector_store=get_vector_store(), embed_model=get_embedding_model()
    )
    bm25 = BM25Retriever.from_defaults(nodes=nodes, similarity_top_k=100)
    return {"index": index, "bm25": bm25}


def get_fusion_retriever(content_hash: str, similarity_top_k: int = 15):
    """Dense (pgvector) + sparse (BM25) retrieval over one document, RRF-fused."""
    cached = _build_index(content_hash)
    if cached is None:
        return None

    vector_retriever = cached["index"].as_retriever(
        similarity_top_k=similarity_top_k, filters=_content_hash_filter(content_hash)
    )

    return QueryFusionRetriever(
        retrievers=[vector_retriever, cached["bm25"]],
        mode="reciprocal_rerank",
        similarity_top_k=similarity_top_k,
        num_queries=1,
        use_async=False,
    )


def retrieve_chunks(
    content_hash: str,
    query: str,
    top_k: int = 15,
    rerank_top_n: int = 8,
) -> list:
    retriever = get_fusion_retriever(content_hash, similarity_top_k=top_k)
    if retriever is None:
        return []

    nodes = retriever.retrieve(query)
    if not nodes:
        return []

    reranker = _get_global_reranker()
    # Serialize reranker inference — cross-encoder forward pass is not thread-safe
    # under concurrent extraction groups.
    with _reranker_lock:
        reranked = reranker.postprocess_nodes(nodes, query_str=query)

    return [
        f"[PAGE {n.node.metadata.get('page', '?')}]\n{n.node.get_content()}"
        for n in reranked[:rerank_top_n]
    ]
