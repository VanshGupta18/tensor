import copy

import json

import re

import threading

from concurrent.futures import ThreadPoolExecutor, as_completed

from rag_pipeline.step1_schemas import _EXTRACTION_GROUPS, _DOCUMENT_SECTIONS_TOOL_SCHEMA

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


# ─────────────────────────────────────────────────────────────────────────────
# Generic Section/SubSection/LineItem  ->  legacy tender-doc adapter
# ─────────────────────────────────────────────────────────────────────────────
# Converts the LLM's generic document tree (see step1_schemas.py) back into the
# exact legacy dict shape that step4_validators.py, service.js, the frontend,
# and step7_pdf_generator.py already know how to consume. Keeping this
# conversion entirely inside the extraction layer means nothing downstream of
# extract_via_targeted_retrieval() needs to change.

def _num(s):
    """Best-effort string -> number. Returns None if nothing numeric is found.
    Whole numbers come back as int (not 90.0) since _extract_first_number always
    parses via float() — PDF/UI text rendering shouldn't show a stray '.0'."""
    if s is None:
        return None
    if isinstance(s, int):
        return s
    if isinstance(s, float):
        return int(s) if s.is_integer() else s
    n = _extract_first_number(str(s))
    if n is None:
        return None
    return int(n) if n.is_integer() else n

def _find_subsection(section, title):
    if not section:
        return None
    title = title.strip().lower()
    for sub in section.get("subsections", []) or []:
        if (sub.get("title") or "").strip().lower() == title:
            return sub
    return None

def _field_map(line_items):
    """label (lowercased) -> field line_item, for type=='field' items."""
    out = {}
    for li in line_items or []:
        if li.get("type") == "field" and li.get("label"):
            out[li["label"].strip().lower()] = li
    return out

def _group_map(line_items):
    """title (lowercased) -> group line_item, for type=='group' items."""
    out = {}
    for li in line_items or []:
        if li.get("type") == "group" and li.get("title"):
            out[li["title"].strip().lower()] = li
    return out

def _field_value(fmap, label):
    li = fmap.get(label.strip().lower())
    return li.get("value") if li else None

def _field_attrs(fmap, label):
    li = fmap.get(label.strip().lower())
    return (li.get("attributes") or {}) if li else {}

def _child_field_value(group, label):
    if not group:
        return None
    label = label.strip().lower()
    for child in group.get("children", []) or []:
        if child.get("type") == "field" and (child.get("label") or "").strip().lower() == label:
            return child.get("value")
    return None

def _table_rows(line_items, *keys):
    """All type=='table_row' items' attributes, projected onto `keys` (missing -> None)."""
    rows = []
    for li in line_items or []:
        if li.get("type") != "table_row":
            continue
        attrs = li.get("attributes") or {}
        rows.append({k: attrs.get(k) for k in keys})
    return rows

def _bullets_by_title(line_items, title):
    title = title.strip().lower()
    for li in line_items or []:
        if li.get("type") == "bullet" and (li.get("title") or "").strip().lower() == title:
            return li.get("bullets") or []
    return []

def _money_field(fmap, label):
    """Reconstruct a legacy {amount, currency, denomination?} object from a field's
    structured attributes, falling back to parsing its display value."""
    attrs = _field_attrs(fmap, label)
    if attrs:
        out = {}
        if attrs.get("amount") is not None:
            out["amount"] = _num(attrs.get("amount"))
        if attrs.get("currency"):
            out["currency"] = attrs["currency"]
        if attrs.get("denomination"):
            out["denomination"] = attrs["denomination"]
        if out:
            return out
    val = _field_value(fmap, label)
    if val:
        amt = _num(val)
        return {"amount": amt} if amt is not None else None
    return None

def _date_field(fmap, label):
    """Reconstruct a legacy date value: {date,time,timezone} object if the field
    carries structured attributes, else the plain display string."""
    attrs = _field_attrs(fmap, label)
    if attrs and any(attrs.get(k) for k in ("date", "time", "timezone")):
        return {k: attrs[k] for k in ("date", "time", "timezone") if attrs.get(k)}
    return _field_value(fmap, label) or None

def _section_by_id(sections, sec_id):
    for s in sections or []:
        if str(s.get("id")) == sec_id or str(s.get("number")) == sec_id:
            return s
    return None

def _sections_to_legacy(sections: list) -> dict:
    """Adapt the generic document tree into the legacy tender-doc dict."""
    tender = {}

    # ── Section 1: Basic Tender Particulars -> tender_overview ─────────────────
    sec1 = _section_by_id(sections, "1")
    if sec1:
        ti_sub = _find_subsection(sec1, "Tender Information")
        overview = {}
        if ti_sub:
            fmap = _field_map(ti_sub.get("line_items"))
            for label, key in (
                ("Title", "title"), ("Reference No", "reference_no"), ("Version", "version"),
                ("Issuing Authority", "issuing_authority"), ("Contract Type", "contract_type"),
                ("Bid System", "bid_system"), ("Funding Agency", "funding_agency"),
                ("Budget Category", "budget_category"),
            ):
                v = _field_value(fmap, label)
                if v:
                    overview[key] = v
            cost = _money_field(fmap, "Estimated Cost")
            if cost:
                overview["estimated_cost"] = cost
            fee = _money_field(fmap, "Tender Fee")
            if fee:
                overview["tender_fee"] = fee

        contacts_sub = _find_subsection(sec1, "Contacts")
        if contacts_sub:
            contacts = []
            for li in contacts_sub.get("line_items", []) or []:
                if li.get("type") == "card" and li.get("title"):
                    contacts.append({
                        "name":  li.get("title"),
                        "role":  li.get("subtitle") or None,
                        "email": li.get("description") or None,
                    })
            if contacts:
                overview["contacts"] = contacts

        kd_sub = _find_subsection(sec1, "Key Dates")
        if kd_sub:
            kfmap = _field_map(kd_sub.get("line_items"))
            key_dates = {}
            pub = _field_value(kfmap, "Publication")
            if pub:
                key_dates["publication"] = pub
            for label, key in (
                ("Pre-Bid Meeting", "pre_bid_meeting"),
                ("Bid Submission Deadline", "bid_submission_deadline"),
                ("Technical Opening", "technical_opening"),
                ("Financial Opening", "financial_opening"),
            ):
                v = _date_field(kfmap, label)
                if v:
                    key_dates[key] = v
            woi = _field_value(kfmap, "Work Order Issuance")
            if woi:
                key_dates["work_order_issuance"] = woi
            if key_dates:
                overview["key_dates"] = key_dates

        if overview:
            tender["tender_overview"] = overview

    # ── Section 2: Scope of Work -> scope_of_work (array) ───────────────────────
    sec2 = _section_by_id(sections, "2")
    if sec2:
        sow_sub = _find_subsection(sec2, "Scope of Work")
        if sow_sub:
            scope = []
            for li in sow_sub.get("line_items", []) or []:
                if li.get("type") == "card" and li.get("title"):
                    scope.append({"category": li.get("title"), "details": li.get("description") or ""})
            if scope:
                tender["scope_of_work"] = scope

    # ── Section 3: Eligibility & Qualification ──────────────────────────────────
    sec3 = _section_by_id(sections, "3")
    if sec3:
        eq = {}
        tech_sub = _find_subsection(sec3, "Technical Eligibility")
        if tech_sub:
            items = tech_sub.get("line_items", [])
            fmap = _field_map(items)
            v = _field_value(fmap, "Contractor Class Required")
            if v:
                eq["contractor_class_required"] = v
            v = _field_value(fmap, "Bidding Capacity")
            if v is not None:
                n = _num(v)
                if n is not None:
                    eq["bidding_capacity"] = n
            technical = {}
            v = _field_value(fmap, "Heading Note")
            if v:
                technical["heading_note"] = v
            v = _field_value(fmap, "Similar Works Definition")
            if v:
                technical["similar_works_definition"] = v
            options = [r for r in _table_rows(items, "option", "requirement") if r.get("option") or r.get("requirement")]
            if options:
                technical["options"] = options
            if technical:
                eq["technical"] = technical
        fin_sub = _find_subsection(sec3, "Financial Eligibility")
        if fin_sub:
            rows = [r for r in _table_rows(fin_sub.get("line_items"), "criterion", "requirement") if r.get("criterion") or r.get("requirement")]
            if rows:
                eq["financial"] = rows
        if eq:
            tender["eligibility_and_qualification"] = eq

    # ── Section 4: Financial Terms & Security -> financial_terms ────────────────
    sec4 = _section_by_id(sections, "4")
    if sec4:
        ft = {}
        sec_sub = _find_subsection(sec4, "Security & Financial Terms")
        if sec_sub:
            items = sec_sub.get("line_items", [])
            fmap = _field_map(items)
            gmap = _group_map(items)
            emd_grp = gmap.get("emd")
            if emd_grp:
                emd = {}
                v = _num(_child_field_value(emd_grp, "Percentage"))
                if v is not None:
                    emd["percentage"] = v
                v = _num(_child_field_value(emd_grp, "Max Cap (INR)"))
                if v is not None:
                    emd["max_cap_inr"] = v
                v = _child_field_value(emd_grp, "Form")
                if v:
                    emd["form"] = v
                if emd:
                    ft["emd"] = emd
            bank_grp = gmap.get("bank details")
            if bank_grp:
                bank = {}
                for label, key in (("Bank", "bank"), ("Account", "account"), ("IFSC", "ifsc")):
                    v = _child_field_value(bank_grp, label)
                    if v:
                        bank[key] = v
                if bank:
                    ft["bank_details"] = bank
            for label, key in (
                ("Bid Validity (Days)", "bid_validity_days"),
                ("Retention Money (%)", "retention_money_percent"),
                ("Standard Timeline (Days)", "standard_timeline_days"),
            ):
                v = _num(_field_value(fmap, label))
                if v is not None:
                    ft[key] = v
            v = _field_value(fmap, "Delayed Interest Rate")
            if v:
                ft["delayed_interest_rate"] = v
            guarantees = []
            for r in _table_rows(items, "type", "percentage"):
                if r.get("type") or r.get("percentage") is not None:
                    guarantees.append({"type": r.get("type"), "percentage": _num(r.get("percentage"))})
            if guarantees:
                ft["performance_guarantees"] = guarantees

        adv_sub = _find_subsection(sec4, "Advance Payments")
        if adv_sub:
            advances = []
            for li in adv_sub.get("line_items", []) or []:
                if li.get("type") != "group":
                    continue
                for child in li.get("children", []) or []:
                    if child.get("type") != "field" or not child.get("label"):
                        continue
                    conditions = [c.strip() for c in (child.get("description") or "").split(";") if c.strip()]
                    advances.append({
                        "component":  child["label"],
                        "percentage": _num(child.get("value")),
                        "conditions": conditions,
                    })
            if advances:
                ft["advance_payments"] = advances

        prog_sub = _find_subsection(sec4, "Progressive Payments")
        if prog_sub:
            progressive = []
            for r in _table_rows(prog_sub.get("line_items"), "component", "milestone", "percentage"):
                if r.get("component") or r.get("milestone") or r.get("percentage") is not None:
                    progressive.append({
                        "component":  r.get("component"),
                        "milestone":  r.get("milestone"),
                        "percentage": _num(r.get("percentage")),
                    })
            if progressive:
                ft["progressive_payments"] = progressive

        if ft:
            tender["financial_terms"] = ft

    # ── Section 5: Price Variation ───────────────────────────────────────────────
    sec5 = _section_by_id(sections, "5")
    if sec5:
        pv_sub = _find_subsection(sec5, "Price Variation")
        if pv_sub:
            items = pv_sub.get("line_items", [])
            fmap = _field_map(items)
            pv = {}
            v = _field_value(fmap, "Is Applicable")
            if v:
                pv["is_applicable"] = v.strip().lower() in ("yes", "true", "applicable")
            firm = _bullets_by_title(items, "Firm Components")
            if firm:
                pv["firm_components"] = firm
            variable = _bullets_by_title(items, "Variable Components")
            if variable:
                pv["variable_components"] = variable
            materials = []
            for li in items:
                if li.get("type") != "formula":
                    continue
                title = (li.get("title") or "").strip()
                if title.lower() == "composite formula":
                    if li.get("formula"):
                        pv["composite_formula"] = li["formula"]
                    continue
                materials.append({
                    "name":         title or None,
                    "formula":      li.get("formula"),
                    "index_source": (li.get("attributes") or {}).get("index_source") or li.get("reference"),
                })
            if materials:
                pv["materials"] = materials
            if pv:
                tender["price_variation"] = pv

    # ── Section 6: Contract & Bidding Conditions ─────────────────────────────────
    sec6 = _section_by_id(sections, "6")
    if sec6:
        cb = {}
        cond_sub = _find_subsection(sec6, "Contract Conditions")
        if cond_sub:
            items = cond_sub.get("line_items", [])
            fmap = _field_map(items)
            gmap = _group_map(items)
            v = _num(_field_value(fmap, "Completion Time (Months)"))
            if v is not None:
                cb["completion_time_months"] = v
            v = _num(_field_value(fmap, "Defect Liability Period (Months)"))
            if v is not None:
                cb["defect_liability_period_months"] = v
            ld_grp = gmap.get("liquidated damages")
            if ld_grp:
                ld = {}
                v = _num(_child_field_value(ld_grp, "Rate/Week %"))
                if v is not None:
                    ld["rate_per_week_percent"] = v
                v = _num(_child_field_value(ld_grp, "Cap %"))
                if v is not None:
                    ld["cap_percent"] = v
                if ld:
                    cb["liquidated_damages"] = ld
            qp_grp = gmap.get("quality penalties")
            if qp_grp:
                qp = {}
                v = _num(_child_field_value(qp_grp, "Major Defect %"))
                if v is not None:
                    qp["major_defect_percent"] = v
                v = _num(_child_field_value(qp_grp, "Minor Defect %"))
                if v is not None:
                    qp["minor_defect_percent"] = v
                if qp:
                    cb["quality_penalties"] = qp
            special = _bullets_by_title(items, "Special Requirements")
            if special:
                cb["special_requirements"] = special

        tbd_sub = _find_subsection(sec6, "Technical Bid Documents")
        if tbd_sub:
            items = tbd_sub.get("line_items", []) or []
            documents = []
            has_warning = False
            for li in items:
                if li.get("type") == "bullet":
                    documents.extend(li.get("bullets") or [])
                elif li.get("type") == "rule" and li.get("description"):
                    has_warning = True
            tbd = {}
            if documents:
                tbd["grouped_documents"] = documents
            if has_warning:
                tbd["has_price_disclosure_warning"] = True
            if tbd:
                cb["technical_bid_documents"] = tbd

        if cb:
            tender["contract_and_bidding"] = cb

    return tender


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
        #
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
            return [], {}

        chunk_block = "\n\n---\n".join(retrieved_chunks)
        prompt_text = f"{group['prompt']}\n\nDOCUMENT CHUNKS:\n{chunk_block}\n\nUse the tool to output the structured data for this group."

        token = main_token
        payload = {
            "messages": [{"role": "user", "content": prompt_text}],
            "tools": [_DOCUMENT_SECTIONS_TOOL_SCHEMA],
            "tool_choice": {"type": "tool", "name": "structure_document_sections"},
            "max_tokens": 4096,
            "anthropic_version": "bedrock-2023-05-31",
        }

        result, usage = get_result_tool_use(token, API_URL, payload)
        if isinstance(result, dict):
            sections = result.get("sections", [])
            if isinstance(sections, list):
                return sections, usage
        elif isinstance(result, str):
            try:
                parsed = json.loads(result)
                sections = parsed.get("sections", []) if isinstance(parsed, dict) else []
                if isinstance(sections, list):
                    return sections, usage
            except Exception:
                pass
        return [], usage

    all_sections = []
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
                group_sections, usage = future.result()
                if usage:
                    total_usage["input_tokens"] += usage.get("input_tokens") or 0
                    total_usage["output_tokens"] += usage.get("output_tokens") or 0
                    total_usage["cache_creation_input_tokens"] += usage.get("cache_creation_input_tokens") or 0
                    total_usage["cache_read_input_tokens"] += usage.get("cache_read_input_tokens") or 0

                if group_sections:
                    all_sections.extend(group_sections)
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

    all_sections.sort(key=lambda s: _num(s.get("number")) if _num(s.get("number")) is not None else 999)
    tender_doc = _sections_to_legacy(all_sections)

    final_json = {"tenders": [tender_doc], "_analytics": total_usage}
    return _deduplicate_contacts(_normalize_unknowns(final_json))
