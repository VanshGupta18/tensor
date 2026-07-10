"""Dynamic per-group chunk budgets scaled to document size.

Small tenders stay near the minimum (token-efficient). Large or dense documents
automatically receive more retrieval context for groups that need it (scope of
work, technical bid checklists, price-variation formula tables).
"""
import math


def compute_chunk_budget(group: dict, page_count: int, chunk_count: int) -> tuple[int, int]:
    """Return (max_retrieve, max_chunks) for one extraction group.

    Uses chunk_budget profile when present; otherwise falls back to fixed
    max_retrieve / max_chunks on the group dict.
    """
    budget = group.get("chunk_budget")
    if not budget:
        return (
            group.get("max_retrieve", group.get("max_pages", 12) * 2),
            group.get("max_chunks", 14),
        )

    min_chunks   = budget["min_chunks"]
    max_chunks   = budget["max_chunks"]
    min_retrieve = budget["min_retrieve"]
    max_retrieve = budget["max_retrieve"]
    ref_pages    = budget.get("ref_pages", 40)
    # Optional ceiling for very large tenders (200–600+ pages)
    abs_chunks   = budget.get("absolute_max_chunks", max_chunks)
    abs_retrieve = budget.get("absolute_max_retrieve", max_retrieve)
    mega_pages   = budget.get("mega_pages", 500)

    priority_mult = {"high": 1.15, "normal": 1.0, "low": 0.9}.get(
        budget.get("priority", "normal"), 1.0
    )

    pages = max(page_count, 1)
    chunks = max(chunk_count, 1)

    # Log-scaled page ratio: ~15 pages → min, ~2× ref_pages → profile max
    low_pages = 15
    high_pages = max(ref_pages * 2, low_pages + 1)
    if pages <= low_pages:
        page_ratio = 0.0
    elif pages >= high_pages:
        page_ratio = 1.0
    else:
        page_ratio = math.log(pages / low_pages) / math.log(high_pages / low_pages)

    # Dense documents (many chunks per page) need extra recall
    chunks_per_page = chunks / pages
    density_ratio = min(1.0, max(0.0, (chunks_per_page - 2.0) / 4.0))

    blend = min(1.0, (page_ratio * 0.65 + density_ratio * 0.35) * priority_mult)

    out_chunks   = round(min_chunks   + (max_chunks   - min_chunks)   * blend)
    out_retrieve = round(min_retrieve + (max_retrieve - min_retrieve) * blend)

    # Mega-doc tier: pages beyond high_pages scale toward absolute_max
    if pages > high_pages and abs_chunks > max_chunks:
        span = max(mega_pages - high_pages, 1)
        mega_ratio = min(1.0, (pages - high_pages) / span)
        out_chunks   = round(max_chunks   + (abs_chunks   - max_chunks)   * mega_ratio)
        out_retrieve = round(max_retrieve + (abs_retrieve - max_retrieve) * mega_ratio)

    # Safety: retrieve pool must be >= final chunk cap
    out_retrieve = max(out_retrieve, out_chunks + 6)

    return out_retrieve, out_chunks


def merge_and_cap_chunks(keyword_sets: list, retrieve_fn, max_retrieve: int, max_chunks: int) -> list:
    """Run one retrieval pass per keyword set, dedupe, hard-cap at max_chunks."""
    num_passes = len(keyword_sets)
    per_pass_k = math.ceil(max_retrieve / num_passes)

    seen: set = set()
    chunks: list = []
    for keywords in keyword_sets:
        query = " ".join(keywords)
        for chunk in retrieve_fn(query, top_k=per_pass_k, rerank_top_n=per_pass_k):
            if chunk not in seen:
                seen.add(chunk)
                chunks.append(chunk)

    if len(chunks) > max_chunks:
        chunks = chunks[:max_chunks]
    return chunks


def merge_boost_early_pages(
    chunks: list,
    early_chunks: list,
    max_chunks: int,
    min_early_slots: int = 4,
) -> list:
    """Prepend early-page chunks and guarantee min_early_slots survive the cap."""
    if not early_chunks:
        return chunks[:max_chunks] if len(chunks) > max_chunks else chunks

    seen: set = set()
    ordered: list = []
    for chunk in early_chunks + chunks:
        if chunk not in seen:
            seen.add(chunk)
            ordered.append(chunk)

    if len(ordered) <= max_chunks:
        return ordered

    early_set = set(early_chunks)
    kept_early = [c for c in ordered if c in early_set][:min_early_slots]
    kept_set = set(kept_early)
    rest = [c for c in ordered if c not in kept_set]
    return kept_early + rest[: max_chunks - len(kept_early)]
