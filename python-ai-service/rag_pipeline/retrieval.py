"""Dense + BM25 retrieval with section-scoping and graph expansion."""
import functools

from llama_index.core import VectorStoreIndex
from llama_index.core.llms import MockLLM
from llama_index.core.retrievers import QueryFusionRetriever
from llama_index.core.schema import NodeWithScore
from llama_index.retrievers.bm25 import BM25Retriever

from rag_pipeline.chunking import format_chunk_header
from rag_pipeline.ingestion import (
    _content_hash_filter,
    get_document_nodes,
    get_embedding_model,
    get_vector_store,
)
from rag_pipeline.tender_graph import get_tender_graph


def _format_node(node) -> str:
    return f"{format_chunk_header(node.metadata or {})}\n{node.get_content()}"


def invalidate_retrieval_cache() -> None:
    _build_index.cache_clear()


def get_early_page_chunks(content_hash: str, max_page: int = 8, max_chunks: int = 8) -> list:
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
            out.append(_format_node(node))
            if len(out) >= max_chunks:
                return out
    return out


def _section_cache_key(section_ids: list[str] | None) -> str:
    if not section_ids:
        return "*"
    return ",".join(sorted(section_ids))


def _nodes_for_scope(all_nodes: list, section_ids: list[str] | None) -> list:
    if not section_ids:
        return all_nodes
    sid_set = set(section_ids)
    scoped = [n for n in all_nodes if (n.metadata or {}).get("section_id") in sid_set]
    return scoped if len(scoped) >= 6 else all_nodes


def _boost_section_order(nodes: list[NodeWithScore], section_ids: list[str] | None) -> list[NodeWithScore]:
    if not section_ids:
        return nodes
    sid_set = set(section_ids)
    in_sec = [n for n in nodes if (n.node.metadata or {}).get("section_id") in sid_set]
    out_sec = [n for n in nodes if (n.node.metadata or {}).get("section_id") not in sid_set]
    return in_sec + out_sec


def _graph_expand_nodes(
    content_hash: str,
    seeds: list[NodeWithScore],
    max_siblings: int = 2,
) -> list:
    graph = get_tender_graph(content_hash)
    if not graph:
        return [s.node for s in seeds]

    seed_ids = [s.node.node_id for s in seeds]
    expanded_ids = graph.expand_node_ids(
        seed_ids,
        max_siblings=max_siblings,
        include_section_header=True,
        include_parent_header=True,
    )

    ordered = []
    seen: set[str] = set()
    for nid in expanded_ids:
        if nid in seen:
            continue
        seen.add(nid)
        if nid in graph.nodes_by_id:
            ordered.append(graph.nodes_by_id[nid])
    return ordered


@functools.lru_cache(maxsize=20)
def _build_index(content_hash: str, section_key: str):
    all_nodes = get_document_nodes(content_hash)
    if not all_nodes:
        return None

    section_ids = None if section_key == "*" else section_key.split(",")
    scoped_nodes = _nodes_for_scope(all_nodes, section_ids)

    index = VectorStoreIndex.from_vector_store(
        vector_store=get_vector_store(), embed_model=get_embedding_model()
    )
    bm25 = BM25Retriever.from_defaults(nodes=scoped_nodes, similarity_top_k=100)
    return {"index": index, "bm25": bm25}


def retrieve_chunks(
    content_hash: str,
    query: str,
    top_k: int = 15,
    rerank_top_n: int = 8,
    section_ids: list[str] | None = None,
    max_siblings: int = 2,
) -> list:
    cached = _build_index(content_hash, _section_cache_key(section_ids))
    if cached is None:
        return []

    retriever = QueryFusionRetriever(
        retrievers=[
            cached["index"].as_retriever(
                similarity_top_k=top_k, filters=_content_hash_filter(content_hash)
            ),
            cached["bm25"],
        ],
        mode="reciprocal_rerank",
        similarity_top_k=top_k,
        num_queries=1,
        use_async=False,
        llm=MockLLM(),
    )

    nodes = retriever.retrieve(query)
    if not nodes:
        return []

    nodes = _boost_section_order(nodes, section_ids)
    expanded = _graph_expand_nodes(content_hash, nodes[:top_k], max_siblings=max_siblings)
    return [_format_node(n) for n in expanded[:rerank_top_n]]
