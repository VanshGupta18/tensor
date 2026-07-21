"""Structure-aware chunking for tender PDFs."""
import re
from dataclasses import dataclass, field

from llama_index.core import Document
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.schema import TextNode

# Bump when chunk metadata shape changes — triggers automatic re-index.
CHUNK_SCHEMA_VERSION = 2

_EXCLUDED_META = [
    "content_hash", "tender_ref", "page", "section_id",
    "section_title", "parent_section_id", "block_id",
    "block_type", "chunk_id", "chunk_index", "block_chunk_count",
    "schema_version",
]

_SECTION_LINE = re.compile(
    r"(?i)^\s*section\s*[-–]?\s*(\d+)\s*[:\.]?\s*(.+)?$"
)
_NIT_LINE = re.compile(
    r"(?i)^\s*(notice inviting tender|request for bids|nit/rfb\s*no)"
)
_TABLE_HEADER = re.compile(r"(?i)^\s*table\s*$")
_NUMBERED_CLAUSE = re.compile(r"^\s*(\d{1,2})\.\s+\S")
_TABLE_ROW = re.compile(r"(\S(?:\s{2,}|\t)\S)")


@dataclass
class _Block:
    page: int
    block_index: int
    section_id: str
    section_title: str
    parent_section_id: str | None
    block_type: str  # text | table | list
    lines: list[str] = field(default_factory=list)

    def text(self) -> str:
        return "\n".join(self.lines).strip()


def _slug_section(num: str, title: str) -> str:
    title = re.sub(r"\s+", " ", (title or "").strip())[:80]
    return f"sec-{num}" if num else title.lower()[:40] or "body"


def _enter_section(section_state: dict, new_id: str, new_title: str) -> None:
    """Record parent link: new section's parent is the previous active section."""
    prev_id = section_state.get("id")
    section_state["parent_id"] = prev_id if prev_id and prev_id != new_id else section_state.get("parent_id")
    section_state["id"] = new_id
    section_state["title"] = new_title


def _detect_block_type(line: str) -> str | None:
    stripped = line.strip()
    if not stripped:
        return None
    if _TABLE_HEADER.match(stripped):
        return "table"
    if _TABLE_ROW.search(stripped) and len(stripped) > 20:
        return "table"
    if _NUMBERED_CLAUSE.match(stripped):
        return "list"
    return "text"


def _parse_page_blocks(page_num: int, page_text: str, section_state: dict) -> list[_Block]:
    blocks: list[_Block] = []
    current: _Block | None = None
    block_index = 0

    def _flush():
        nonlocal current, block_index
        if current and current.text():
            blocks.append(current)
            block_index += 1
        current = None

    for raw_line in page_text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            continue

        sec_match = _SECTION_LINE.match(stripped)
        if sec_match:
            _flush()
            num, title = sec_match.group(1), (sec_match.group(2) or "").strip()
            new_id = _slug_section(num, title)
            new_title = f"Section {num}" + (f": {title}" if title else "")
            _enter_section(section_state, new_id, new_title)
            current = _Block(
                page=page_num,
                block_index=block_index,
                section_id=section_state["id"],
                section_title=section_state["title"],
                parent_section_id=section_state.get("parent_id"),
                block_type="text",
                lines=[stripped],
            )
            continue

        if _NIT_LINE.match(stripped):
            _flush()
            _enter_section(section_state, "nit", "Notice Inviting Tender")
            current = _Block(
                page=page_num,
                block_index=block_index,
                section_id="nit",
                section_title=section_state["title"],
                parent_section_id=section_state.get("parent_id"),
                block_type="text",
                lines=[stripped],
            )
            continue

        block_type = _detect_block_type(stripped) or "text"

        if current is None:
            current = _Block(
                page=page_num,
                block_index=block_index,
                section_id=section_state.get("id", "body"),
                section_title=section_state.get("title", "Document Body"),
                parent_section_id=section_state.get("parent_id"),
                block_type=block_type,
                lines=[stripped],
            )
        elif current.block_type == block_type or block_type == "text":
            current.lines.append(stripped)
            if block_type == "table" and current.block_type != "table":
                current.block_type = "table"
        else:
            _flush()
            current = _Block(
                page=page_num,
                block_index=block_index,
                section_id=section_state.get("id", "body"),
                section_title=section_state.get("title", "Document Body"),
                parent_section_id=section_state.get("parent_id"),
                block_type=block_type,
                lines=[stripped],
            )

    _flush()
    return blocks


def build_documents_from_pdf(
    pages: list[tuple[int, str]], content_hash: str, tender_ref: str = ""
) -> list[Document]:
    section_state: dict = {"id": "cover", "title": "Cover / Summary", "parent_id": None}
    documents: list[Document] = []

    for page_num, page_text in pages:
        if not page_text.strip():
            continue
        blocks = _parse_page_blocks(page_num, page_text, section_state)
        if not blocks:
            blocks = [
                _Block(
                    page_num, 0, "body", section_state.get("title", "Document Body"),
                    section_state.get("parent_id"), "text", page_text.splitlines(),
                )
            ]

        for block in blocks:
            body = block.text()
            if not body:
                continue
            block_id = f"{content_hash}_p{page_num}_b{block.block_index}"
            documents.append(
                Document(
                    text=body,
                    id_=block_id,
                    metadata={
                        "page": page_num,
                        "content_hash": content_hash,
                        "tender_ref": tender_ref,
                        "section_id": block.section_id,
                        "section_title": block.section_title,
                        "parent_section_id": block.parent_section_id or "",
                        "block_id": block_id,
                        "block_type": block.block_type,
                        "schema_version": CHUNK_SCHEMA_VERSION,
                    },
                    excluded_llm_metadata_keys=_EXCLUDED_META,
                    excluded_embed_metadata_keys=_EXCLUDED_META,
                )
            )

    return documents


def split_documents(documents: list[Document], chunk_size: int = 380, chunk_overlap: int = 50) -> list:
    """Tables stay intact; prose is sentence-split within the block."""
    splitter = SentenceSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    nodes: list = []
    chunk_counter = 0

    for doc in documents:
        meta = dict(doc.metadata or {})
        content_hash = meta.get("content_hash", "doc")
        block_type = meta.get("block_type", "text")

        # Never split table blocks mid-row
        if block_type == "table":
            chunk_counter += 1
            nodes.append(
                TextNode(
                    text=doc.text,
                    metadata={
                        **meta,
                        "chunk_id": f"{content_hash}_c{chunk_counter}",
                        "chunk_index": 0,
                        "block_chunk_count": 1,
                    },
                )
            )
            continue

        doc_nodes = splitter.get_nodes_from_documents([doc], show_progress=False)
        block_chunk_count = len(doc_nodes) or 1
        for idx, node in enumerate(doc_nodes):
            chunk_counter += 1
            node.metadata.update(meta)
            node.metadata["chunk_id"] = f"{content_hash}_c{chunk_counter}"
            node.metadata["chunk_index"] = idx
            node.metadata["block_chunk_count"] = block_chunk_count
            nodes.append(node)

    return nodes


def format_chunk_header(metadata: dict) -> str:
    page = metadata.get("page", "?")
    parts = [f"PAGE {page}"]
    section = (metadata.get("section_title") or "").strip()
    if section:
        parts.append(section)
    block = (metadata.get("block_type") or "").strip()
    if block and block != "text":
        parts.append(block)
    parent = (metadata.get("parent_section_id") or "").strip()
    if parent and parent not in (section, ""):
        parts.append(f"under {parent}")
    return "[" + " | ".join(parts) + "]"
