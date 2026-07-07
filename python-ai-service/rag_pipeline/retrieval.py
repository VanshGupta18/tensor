"""Hybrid retrieval (dense + BM25, RRF-fused, reranked) over persisted chunks.

Shared by the 6-group extraction (step5_extractor.py) and citation-grounded
chat (step6_chat.py) — both read from the same durable per-document index
built by ingestion.py.
"""
import threading

from llama_index.core import VectorStoreIndex
from llama_index.core.postprocessor import SentenceTransformerRerank
from llama_index.core.retrievers import QueryFusionRetriever
from llama_index.core.vector_stores.types import MetadataFilter, MetadataFilters
from llama_index.retrievers.bm25 import BM25Retriever

from rag_pipeline.ingestion import get_document_nodes, get_embedding_model, get_vector_store

RERANKER_MODEL = "BAAI/bge-reranker-base"

# Single global reranker to avoid loading the massive model multiple times into RAM.
_reranker_lock = threading.Lock()
_global_reranker = None

# Cache for document-specific indices to prevent CPU thrashing during concurrent retrieval.
_index_cache_lock = threading.Lock()
_index_cache = {}


def _get_global_reranker() -> SentenceTransformerRerank:
    global _global_reranker
    with _reranker_lock:
        if _global_reranker is None:
            # Initialize once with a high top_n. We slice the result to the desired size.
            _global_reranker = SentenceTransformerRerank(model=RERANKER_MODEL, top_n=100)
        return _global_reranker


def _content_hash_filter(content_hash: str) -> MetadataFilters:
    return MetadataFilters(filters=[MetadataFilter(key="content_hash", value=content_hash)])


def get_fusion_retriever(content_hash: str, sap_ai_core_llm, similarity_top_k: int = 15):
    """Dense (pgvector) + sparse (BM25) retrieval over one document, RRF-fused."""
    with _index_cache_lock:
        if content_hash not in _index_cache:
            nodes = get_document_nodes(content_hash)
            if not nodes:
                return None
            
            index = VectorStoreIndex.from_vector_store(
                vector_store=get_vector_store(), embed_model=get_embedding_model()
            )
            # Cache the BM25 index to avoid rebuilding it 9 times concurrently.
            # We set a high top_k; the QueryFusionRetriever will prune the final fused list.
            bm25 = BM25Retriever.from_defaults(nodes=nodes, similarity_top_k=100)
            
            _index_cache[content_hash] = {
                "index": index,
                "bm25": bm25
            }
            
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
    reranked = reranker.postprocess_nodes(nodes, query_str=query)
    
    # Dynamically slice to requested size
    reranked = reranked[:rerank_top_n]
    
    return [
        f"[PAGE {n.node.metadata.get('page', '?')}]\n{n.node.get_content()}"
        for n in reranked
    ]
