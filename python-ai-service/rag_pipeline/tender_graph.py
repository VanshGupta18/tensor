"""In-memory tender document graph for multi-hop retrieval."""
import functools
from dataclasses import dataclass, field


@dataclass
class SectionInfo:
    section_id: str
    title: str
    parent_section_id: str | None = None
    header_chunk_id: str | None = None
    chunk_ids: list[str] = field(default_factory=list)


class TenderGraph:
    def __init__(self) -> None:
        self.sections: dict[str, SectionInfo] = {}
        self.chunks: dict[str, dict] = {}
        self.block_order: dict[str, list[str]] = {}
        self.node_id_to_chunk_id: dict[str, str] = {}
        self.chunk_id_to_node_id: dict[str, str] = {}
        self.nodes_by_id: dict = {}

    @classmethod
    def from_nodes(cls, nodes) -> "TenderGraph":
        graph = cls()
        for node in nodes:
            meta = dict(node.metadata or {})
            chunk_id = meta.get("chunk_id")
            if not chunk_id:
                continue

            graph.chunks[chunk_id] = {
                **meta,
                "node_id": node.node_id,
                "text": node.get_content(),
            }
            graph.nodes_by_id[node.node_id] = node
            graph.node_id_to_chunk_id[node.node_id] = chunk_id
            graph.chunk_id_to_node_id[chunk_id] = node.node_id

            block_id = meta.get("block_id") or chunk_id
            graph.block_order.setdefault(block_id, []).append(chunk_id)

            section_id = meta.get("section_id") or "body"
            if section_id not in graph.sections:
                graph.sections[section_id] = SectionInfo(
                    section_id=section_id,
                    title=meta.get("section_title") or section_id,
                    parent_section_id=meta.get("parent_section_id"),
                )
            graph.sections[section_id].chunk_ids.append(chunk_id)

            if meta.get("chunk_index", 0) == 0:
                sec = graph.sections[section_id]
                if not sec.header_chunk_id:
                    sec.header_chunk_id = chunk_id

        return graph

    def expand_chunk_ids(
        self,
        seed_chunk_ids: list[str],
        max_siblings: int = 2,
        include_section_header: bool = True,
        include_parent_header: bool = True,
    ) -> list[str]:
        ordered: list[str] = []
        seen: set[str] = set()

        def _add(cid: str) -> None:
            if cid and cid not in seen and cid in self.chunks:
                seen.add(cid)
                ordered.append(cid)

        for seed in seed_chunk_ids:
            _add(seed)
            info = self.chunks.get(seed, {})
            block_id = info.get("block_id")
            if block_id and block_id in self.block_order:
                order = self.block_order[block_id]
                if seed in order:
                    idx = order.index(seed)
                    lo = max(0, idx - max_siblings)
                    hi = min(len(order), idx + max_siblings + 1)
                    for cid in order[lo:hi]:
                        _add(cid)

            section_id = info.get("section_id")
            if include_section_header and section_id:
                hdr = self.sections.get(section_id, SectionInfo(section_id, section_id)).header_chunk_id
                if hdr:
                    _add(hdr)

            parent_id = info.get("parent_section_id")
            if include_parent_header and parent_id:
                hdr = self.sections.get(parent_id, SectionInfo(parent_id, parent_id)).header_chunk_id
                if hdr:
                    _add(hdr)

        return ordered

    def expand_node_ids(self, seed_node_ids: list[str], **kwargs) -> list[str]:
        chunk_ids = [
            self.node_id_to_chunk_id[nid]
            for nid in seed_node_ids
            if nid in self.node_id_to_chunk_id
        ]
        expanded = self.expand_chunk_ids(chunk_ids, **kwargs)
        return [self.chunk_id_to_node_id[cid] for cid in expanded if cid in self.chunk_id_to_node_id]

@functools.lru_cache(maxsize=8)
def get_tender_graph(content_hash: str) -> TenderGraph | None:
    from rag_pipeline.ingestion import get_document_nodes

    nodes = get_document_nodes(content_hash)
    if not nodes:
        return None
    return TenderGraph.from_nodes(nodes)
