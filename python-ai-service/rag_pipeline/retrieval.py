"""Dense + BM25 retrieval (RRF-fused, reranked) over persisted chunks.

Shared by extraction (step5_extractor.py) and citation-grounded chat
(step6_chat.py) — both read from the same durable per-document index
built by ingestion.py.
"""
import threading
from collections import OrderedDict

from llama_index.core import VectorStoreIndex
from llama_index.core.postprocessor import SentenceTransformerRerank
from llama_index.core.retrievers import QueryFusionRetriever
from llama_index.core.vector_stores.types import MetadataFilter, MetadataFilters
from llama_index.retrievers.bm25 import BM25Retriever

from rag_pipeline.ingestion import get_document_nodes, get_embedding_model, get_vector_store


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

# Single global reranker — loaded once, shared across all requests in the worker.
_reranker_lock = threading.Lock()
_global_reranker = None

# LRU cache for per-document BM25 + vector indices.
# Capped at 5 entries to prevent unbounded RAM growth across many tenders.
_INDEX_CACHE_MAX = 5
_index_cache_lock = threading.Lock()
_index_cache: OrderedDict = OrderedDict()


def _get_global_reranker() -> SentenceTransformerRerank:
    global _global_reranker
    with _reranker_lock:
        if _global_reranker is None:
            _global_reranker = SentenceTransformerRerank(
                model=RERANKER_MODEL, top_n=100, device=ML_DEVICE
            )
        return _global_reranker


def _content_hash_filter(content_hash: str) -> MetadataFilters:
    return MetadataFilters(filters=[MetadataFilter(key="content_hash", value=content_hash)])


def get_fusion_retriever(content_hash: str, sap_ai_core_llm, similarity_top_k: int = 15):
    """Dense (pgvector) + sparse (BM25) retrieval over one document, RRF-fused."""
    with _index_cache_lock:
        if content_hash in _index_cache:
            # Move to end (most-recently-used) on every hit.
            _index_cache.move_to_end(content_hash)
        else:
            nodes = get_document_nodes(content_hash)
            if not nodes:
                return None

            index = VectorStoreIndex.from_vector_store(
                vector_store=get_vector_store(), embed_model=get_embedding_model()
            )
            bm25 = BM25Retriever.from_defaults(nodes=nodes, similarity_top_k=100)
            _index_cache[content_hash] = {"index": index, "bm25": bm25}

            # Evict oldest entry when over the cap.
            if len(_index_cache) > _INDEX_CACHE_MAX:
                _index_cache.popitem(last=False)

        cached = _index_cache[content_hash]

    vector_retriever = cached["index"].as_retriever(
        similarity_top_k=similarity_top_k, filters=_content_hash_filter(content_hash)
    )

    return QueryFusionRetriever(
        retrievers=[vector_retriever, cached["bm25"]],
        llm=sap_ai_core_llm,
        mode="reciprocal_rerank",
        similarity_top_k=similarity_top_k,
        num_queries=1,
        use_async=False,
    )


def retrieve_chunks(
    content_hash: str,
    query: str,
    sap_ai_core_llm,
    top_k: int = 15,
    rerank_top_n: int = 8,
) -> list:
    retriever = get_fusion_retriever(content_hash, sap_ai_core_llm, similarity_top_k=top_k)
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
