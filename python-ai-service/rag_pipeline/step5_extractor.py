import copy

import json

import re

import threading

from concurrent.futures import ThreadPoolExecutor, as_completed

from rag_pipeline.step1_schemas import _EXTRACTION_GROUPS, _TENDER_TOOL_SCHEMA

from rag_pipeline.step4_validators import _normalize_unknowns, _deduplicate_contacts

from rag_pipeline.step2_llm_client import get_result_tool_use

from rag_pipeline.ingestion import ingest_pdf

from rag_pipeline.retrieval import retrieve_chunks

from rag_pipeline.llama_llm_adapter import SapAiCoreLLM

_upload_semaphore = threading.Semaphore(2)

def _get_nested(d: dict, path: str):
    for key in path.split("."):
        if not isinstance(d, dict):
            return None
        d = d.get(key)
    return d

def _set_nested(d: dict, path: str, value):
    keys = path.split(".")
    for key in keys[:-1]:
        d = d.setdefault(key, {})
    d[keys[-1]] = value

def _extract_first_number(text: str):
    """Return the first float found in text, or None."""
    m = re.search(r'\b(\d[\d,]*(?:\.\d+)?)\b', text)
    if m:
        return float(m.group(1).replace(",", ""))
    return None

def _deep_fill(target: dict, patch: dict):
    """Fill null/absent fields in target from patch. Never overwrites existing data."""
    for k, v in patch.items():
        if v in (None, [], {}):
            continue
        if k not in target or target[k] in (None, [], {}):
            target[k] = v
        elif isinstance(v, dict) and isinstance(target.get(k), dict):
            _deep_fill(target[k], v)
        elif isinstance(v, list) and isinstance(target.get(k), list) and not target[k]:
            target[k] = v

def extract_via_targeted_retrieval(token_fn, API_URL: str, pdf_path: str, content_hash: str, tender_ref: str = "", on_group_done=None) -> dict:
    """
    on_group_done, if given, is called after each of the 6 groups finishes with
    (group_name, cumulative_usage_dict, groups_completed_count) — lets callers
    (app.py) surface live token/progress counters without persisting anything.
    """
    # Persist the PDF's pages/chunks/embeddings once (idempotent — a re-upload of the
    # same file skips straight to retrieval). Replaces the old per-call ephemeral
    # extract_and_chunk_pdf() + in-memory HybridRetriever, which was rebuilt and thrown
    # away on every request and left nothing durable for chat to ground on later.
    ingest_pdf(pdf_path, content_hash, tender_ref)

    main_token = token_fn() if callable(token_fn) else token_fn
    llm = SapAiCoreLLM(api_url=API_URL)

    def _process_group(group):
        print(f"[RAG] searching for group: '{group['name']}'")

        # A page is roughly 3 chunks. rerank_top_n == top_k: extraction wants recall
        # across the whole section (e.g. an exhaustive document checklist), so the
        # reranker only reorders the candidate set here, it doesn't shrink it — unlike
        # chat (step6_chat.py), which trims to a small, high-precision set for its
        # tighter answer-context budget.
        top_k = group.get("max_pages", 12) * 3

        # A group can cover two sub-topics (e.g. tender basics + key dates) whose
        # keywords would otherwise be merged into one query and let the busier
        # sub-topic crowd out the other in the ranked results. Each keyword set —
        # primary plus any extras — gets its own retrieval pass; the results are
        # merged (deduped) into a single prompt so this still costs exactly ONE
        # LLM call per group, preserving the 6-call token budget.
        keyword_sets = [group["keywords"]] + group.get("extra_keyword_sets", [])
        seen = set()
        retrieved_chunks = []
        for keywords in keyword_sets:
            query = " ".join(keywords)
            for chunk in retrieve_chunks(content_hash, query, llm, top_k=top_k, rerank_top_n=top_k):
                if chunk not in seen:
                    seen.add(chunk)
                    retrieved_chunks.append(chunk)

        if not retrieved_chunks:
            print(f"[RAG] '{group['name']}': no chunks retrieved")
            return {}, {}

        chunk_block = "\n\n---\n".join(retrieved_chunks)
        prompt_text = f"{group['prompt']}\n\nDOCUMENT CHUNKS:\n{chunk_block}\n\nUse the tool to output the structured data for this group."
        
        token = main_token
        payload = {
            "messages": [{"role": "user", "content": prompt_text}],
            "tools": [_TENDER_TOOL_SCHEMA],
            "tool_choice": {"type": "tool", "name": "structure_tender_data"},
            "max_tokens": 4096,
            "anthropic_version": "bedrock-2023-05-31",
        }
        
        result, usage = get_result_tool_use(token, API_URL, payload)
        if isinstance(result, dict):
            if "tenders" not in result:
                result = {"tenders": [result]}
            tenders = result.get("tenders", [])
            if tenders and isinstance(tenders[0], dict):
                return tenders[0], usage
        elif isinstance(result, str):
            try:
                parsed = json.loads(result)
                tenders = parsed.get("tenders", []) if isinstance(parsed, dict) else (parsed if isinstance(parsed, list) else [parsed])
                if tenders and isinstance(tenders[0], dict):
                    return tenders[0], usage
            except Exception:
                pass
        return {}, usage

    all_tenders = [{}]
    total_usage = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0
    }

    groups_completed = 0
    with ThreadPoolExecutor(max_workers=9) as executor:
        futures = {executor.submit(_process_group, g): g for g in _EXTRACTION_GROUPS}
        for future in as_completed(futures):
            group = futures[future]
            try:
                group_result, usage = future.result()
                if usage:
                    total_usage["input_tokens"] += usage.get("input_tokens") or 0
                    total_usage["output_tokens"] += usage.get("output_tokens") or 0
                    total_usage["cache_creation_input_tokens"] += usage.get("cache_creation_input_tokens") or 0
                    total_usage["cache_read_input_tokens"] += usage.get("cache_read_input_tokens") or 0

                if group_result:
                    _deep_fill(all_tenders[0], group_result)
                    print(f"[RAG] '{group['name']}': Successfully populated section.")
            except Exception as e:
                print(f"[RAG] Error processing '{group['name']}': {e}")
            finally:
                groups_completed += 1
                if on_group_done:
                    try:
                        on_group_done(group["name"], dict(total_usage), groups_completed)
                    except Exception as cb_err:
                        print(f"[RAG] on_group_done callback failed: {cb_err}")
                
    final_json = {"tenders": all_tenders, "_analytics": total_usage}
    return _deduplicate_contacts(_normalize_unknowns(final_json))
