import copy
import json
import re
import threading

from concurrent.futures import ThreadPoolExecutor, as_completed

from rag_pipeline.step1_schemas import (
    _EXTRACTION_GROUPS,
    _DOCUMENT_SECTIONS_TOOL_SCHEMA,
    SHARED_EXTRACTION_PREAMBLE,
)
from rag_pipeline.step4_validators import _normalize_unknowns, _deduplicate_contacts, _sanitize_contacts, _parse_contact_channels
from rag_pipeline.step2_llm_client import get_result_tool_use, build_cached_extraction_payload
from rag_pipeline.ingestion import ingest_pdf, get_document_stats, get_document_nodes
from rag_pipeline.retrieval import retrieve_chunks, get_early_page_chunks
from rag_pipeline.chunk_budget import compute_chunk_budget, merge_and_cap_chunks, merge_boost_early_pages

_upload_semaphore = threading.Semaphore(2)

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

def _find_subsection_fuzzy(section, *needles):
    """Match subsection title containing any of the needle phrases."""
    if not section:
        return None
    needles = [n.strip().lower() for n in needles if n]
    for sub in section.get("subsections", []) or []:
        title = (sub.get("title") or "").strip().lower()
        if any(n in title for n in needles):
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

def _field_value_any(fmap, *labels):
    """First non-empty value across alternate field labels (LLM label drift)."""
    for label in labels:
        v = _field_value(fmap, label)
        if v and str(v).strip():
            return str(v).strip()
    return None

_REF_NO_PATTERNS = [
    re.compile(
        r"(?i)(?:tender\s*number|reference\s*no\.?|nit/rfb\s*no\.?|"
        r"rfb\s*notice/nit\s*no\.?|nit\s*no\.?|tender\s*no\.?|"
        r"e-?tender\s*(?:id|no\.?)|bid\s*ref(?:erence)?)\s*[:\-\s]*\s*"
        r"([^\n\r]{6,120})"
    ),
    re.compile(r"(?i)tender\s*id\s*[:\-\s]*\s*([^\n\r]{4,40})"),
]

_REFERENCE_LABELS_FULL = (
    "Reference No", "Tender Number", "Tender No", "NIT/RFB No",
    "RFB Notice/NIT No", "NIT Number", "Reference Number", "Tender Reference",
    "NIT No",
)
_REFERENCE_LABELS_FALLBACK = ("Tender ID",)

def _score_reference_candidate(val: str) -> tuple:
    """Prefer org-style refs (MGVCL/TECH/...) over bare numeric e-Tender IDs."""
    score = 0
    if "/" in val:
        score += 20
    if re.search(r"[A-Za-z]", val):
        score += 10
    if re.search(r"\d{4}-\d{2}", val):
        score += 5
    if val.strip().isdigit():
        score -= 15
    return (score, len(val))

def _clean_reference_candidate(raw: str) -> str | None:
    if not raw:
        return None
    val = raw.strip().strip(".,;")
    val = re.sub(r"\s{2,}.*$", "", val)
    # Drop deadline/date lines accidentally captured after label
    val = re.sub(r"(?i)\s*(deadline|issued on|date of).*$", "", val).strip()
    if len(val) < 4 or val.lower() in {"not stated", "n/a", "tbd", "unknown"}:
        return None
    return val

def _extract_reference_no_from_text(text: str) -> str | None:
    candidates: list[str] = []
    for pat in _REF_NO_PATTERNS:
        for m in pat.finditer(text or ""):
            cleaned = _clean_reference_candidate(m.group(1))
            if cleaned:
                candidates.append(cleaned)
    if not candidates:
        return None
    return max(candidates, key=_score_reference_candidate)

def _backfill_reference_no(tender_doc: dict, content_hash: str) -> dict:
    """Regex fallback when LLM omits reference_no — scan first N pages of indexed text."""
    overview = tender_doc.get("tender_overview") or {}
    if overview.get("reference_no"):
        return tender_doc

    nodes = get_document_nodes(content_hash)
    if not nodes:
        return tender_doc

    by_page: dict = {}
    for node in nodes:
        page = (node.metadata or {}).get("page")
        if page is None or int(page) > 12:
            continue
        by_page.setdefault(int(page), []).append(node.get_content())

    for page in sorted(by_page.keys()):
        page_text = "\n".join(by_page[page])
        ref = _extract_reference_no_from_text(page_text)
        if ref:
            tender_doc.setdefault("tender_overview", {})["reference_no"] = ref
            print(f"[RAG] backfilled reference_no from page {page}: {ref!r}")
            return tender_doc

    return tender_doc

# Bump when extraction/postprocess logic changes — stale result caches are ignored.
EXTRACTION_PIPELINE_VERSION = 5

def postprocess_extraction_result(result: dict, content_hash: str = "") -> dict:
    """Normalize, sanitize contacts, and backfill missing reference_no on each tender."""
    out = copy.deepcopy(result)
    for tender in out.get("tenders", []):
        if content_hash:
            _backfill_reference_no(tender, content_hash)
    return _deduplicate_contacts(_sanitize_contacts(_normalize_unknowns(out)))

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

def _child_field_value_any(group, *labels):
    for label in labels:
        v = _child_field_value(group, label)
        if v is not None and str(v).strip():
            return v
    return None

_DLP_EXCLUDE = re.compile(
    r"warranty|equipment|extended|latent|maintenance\s+period|guarantee\s+period",
    re.I,
)

def _collect_dlp_candidates(line_items) -> list:
    """Gather DLP month values from contract-condition line items."""
    candidates = []
    for li in line_items or []:
        t = li.get("type")
        if t == "field":
            label = li.get("label") or ""
            val = _num(li.get("value"))
            blob = f"{label} {li.get('value') or ''}"
            if val is None or _DLP_EXCLUDE.search(blob):
                continue
            if "defect liability" in label.lower() or label.strip().lower() == "dlp":
                candidates.append(val)
        elif t == "group" and "defect liability" in (li.get("title") or "").lower():
            for child in li.get("children") or []:
                v = _num(child.get("value"))
                if v is not None:
                    candidates.append(v)
    return candidates

def _pick_contract_dlp(candidates: list):
    """Prefer primary contract DLP (typically 6–24 months) over long warranty periods."""
    if not candidates:
        return None
    in_band = [v for v in candidates if 6 <= v <= 24]
    if in_band:
        return min(in_band)
    reasonable = [v for v in candidates if v <= 36]
    if reasonable:
        return min(reasonable)
    return min(candidates)

def _parse_liquidated_damages(items) -> dict:
    """Parse LD rate + cap from group children or combined field text."""
    ld = {}
    gmap = _group_map(items)
    ld_grp = gmap.get("liquidated damages")
    if ld_grp:
        v = _num(_child_field_value_any(ld_grp, "Rate/Week %", "Rate per Week %", "Rate %"))
        if v is not None:
            ld["rate_per_week_percent"] = v
        v = _num(_child_field_value_any(ld_grp, "Cap %", "Maximum %", "Max %", "Cap (%)", "Maximum Cap %"))
        if v is not None:
            ld["cap_percent"] = v

    for li in items or []:
        if li.get("type") != "field":
            continue
        label = (li.get("label") or "").lower()
        val = li.get("value") or ""
        if "liquidated" not in label and label.strip() != "ld":
            continue
        if "rate_per_week_percent" not in ld:
            m = re.search(r"(\d+(?:\.\d+)?)\s*%\s*per\s*week", val, re.I)
            if m:
                ld["rate_per_week_percent"] = float(m.group(1))
        if "cap_percent" not in ld:
            m = re.search(r"(?:max(?:imum)?|cap)\s*[:.]?\s*(\d+(?:\.\d+)?)\s*%", val, re.I)
            if m:
                ld["cap_percent"] = float(m.group(1))
    return ld

def _parse_performance_guarantees(items) -> list:
    """Collect Performance Security + CPG rows from mixed line_item shapes."""
    guarantees = []
    seen = set()

    def _add(type_name, pct):
        key = (type_name or "").strip().lower()
        if not key or pct is None or key in seen:
            return
        seen.add(key)
        guarantees.append({"type": type_name.strip(), "percentage": pct})

    for r in _table_rows(items, "type", "percentage", "component", "part"):
        t = (r.get("type") or r.get("component") or r.get("part") or "").strip()
        pct = _num(r.get("percentage"))
        if t and pct is not None:
            _add(t, pct)

    for li in items or []:
        t = li.get("type")
        if t == "group":
            title = (li.get("title") or "").strip()
            tl = title.lower()
            if not any(k in tl for k in ("cpg", "performance security", "performance guarantee", "contract performance")):
                continue
            pct = _num(_child_field_value_any(li, "Percentage", "Percent", "Rate %"))
            if pct is not None:
                _add(title, pct)
            for child in li.get("children") or []:
                if child.get("type") == "field" and child.get("label"):
                    _add(f"{title} — {child['label']}", _num(child.get("value")))
        elif t == "field":
            label = (li.get("label") or "").strip()
            ll = label.lower()
            if any(k in ll for k in ("cpg", "performance security", "performance guarantee", "contract performance")):
                _add(label, _num(li.get("value")))

    return guarantees

_TIMELINE_DAY_LABELS = (
    "Standard Timeline (Days)",
    "Payment Within (Days)",
    "Payment Release (Days)",
    "Payment Timeline (Days)",
)

def _extract_payment_timeline_days(line_items) -> int | None:
    """Parse 'N days from invoice' style payment release windows without extra LLM calls."""
    fmap = _field_map(line_items)
    for label in _TIMELINE_DAY_LABELS:
        v = _num(_field_value(fmap, label))
        if v is not None:
            return int(v)
        for k, li in fmap.items():
            if "day" in k and any(w in k for w in ("timeline", "payment", "release", "within")):
                v = _num(li.get("value"))
                if v is not None:
                    return int(v)

    blob_parts = []
    for li in line_items or []:
        if li.get("type") == "field":
            blob_parts.extend([li.get("label") or "", li.get("value") or "", li.get("description") or ""])
    blob = " ".join(blob_parts)
    for pat in (
        r"(?:within|released?\s+within)\s+(\d+)\s*days?",
        r"(\d+)\s*days?\s*(?:from|of|after)\s*(?:date\s+of\s+)?(?:invoice|bill|submission|presentation)",
        r"payment\s+(?:shall\s+be\s+)?(?:made|released)\s+within\s+(\d+)\s*days?",
    ):
        m = re.search(pat, blob, re.I)
        if m:
            return int(m.group(1))
    return None

def _contract_condition_items(sections: list) -> list:
    items = []
    for sec in sections or []:
        sub = _find_subsection(sec, "Contract Conditions")
        if sub:
            items.extend(sub.get("line_items") or [])
    return items

def _financial_security_items(sections: list) -> list:
    items = []
    for sec in sections or []:
        sub = _find_subsection(sec, "Security & Financial Terms")
        if sub:
            items.extend(sub.get("line_items") or [])
    return items

def _payment_timeline_items(sections: list) -> list:
    items = []
    for sec in sections or []:
        sub = _find_subsection_fuzzy(sec, "payment timeline")
        if sub:
            items.extend(sub.get("line_items") or [])
    return items

def _normalize_tender_extraction(tender: dict, sections: list) -> None:
    """Zero-token post-process: DLP selection, LD cap, CPG rows, payment timeline."""
    cond_items = _contract_condition_items(sections)
    cb = tender.get("contract_and_bidding") or {}

    dlp = _pick_contract_dlp(_collect_dlp_candidates(cond_items))
    if dlp is not None:
        cb["defect_liability_period_months"] = dlp

    ld = _parse_liquidated_damages(cond_items)
    if ld:
        cb["liquidated_damages"] = {**(cb.get("liquidated_damages") or {}), **ld}

    if cb:
        tender["contract_and_bidding"] = cb

    ft = tender.get("financial_terms") or {}
    guarantees = _parse_performance_guarantees(_financial_security_items(sections))
    if guarantees:
        ft["performance_guarantees"] = guarantees

    days = _extract_payment_timeline_days(_payment_timeline_items(sections))
    if days is None and ft.get("payment_timeline_note"):
        days = _extract_payment_timeline_days([
            {"type": "field", "label": "Payment Timeline Note", "value": ft["payment_timeline_note"]},
        ])
    if days is not None and not ft.get("standard_timeline_days"):
        ft["standard_timeline_days"] = days

    if ft:
        tender["financial_terms"] = ft

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

_SOW_SUBSECTION_TITLES = (
    "scope of work",
    "bill of quantities",
    "boq",
    "description of work",
    "schedule of work",
    "schedule of rates",
    "technical specifications",
)

_SOW_SECTION_TITLE_HINTS = (
    "scope of work",
    "scope",
    "bill of quantities",
    "boq",
    "description of work",
    "schedule of work",
    "technical specifications",
    "name of work",
)

def _is_sow_section_title(title: str) -> bool:
    t = (title or "").strip().lower()
    return any(h in t for h in _SOW_SECTION_TITLE_HINTS)

def _collect_scope_items(line_items):
    """Map generic line_items from the scope group into {category, details} rows.

    The LLM often deviates from the prompt's card-only shape (paragraph, bullet,
    table_row, field) — accepting all of these prevents silent empty scope_of_work.
    """
    scope = []
    for li in line_items or []:
        t = li.get("type")
        if t == "card":
            cat = li.get("title") or li.get("label") or li.get("subtitle")
            det = li.get("description") or li.get("value") or ""
            if cat:
                scope.append({"category": cat, "details": det})
            elif det:
                scope.append({"category": "Scope Item", "details": det})
        elif t == "group":
            cat = li.get("title") or li.get("label")
            parts = []
            for child in li.get("children", []) or []:
                if not isinstance(child, dict):
                    continue
                label = child.get("label") or child.get("title") or ""
                val = child.get("value") or child.get("description") or ""
                if label and val:
                    parts.append(f"{label}: {val}")
                elif val:
                    parts.append(str(val))
                elif label:
                    parts.append(str(label))
            det = li.get("description") or "; ".join(parts)
            if cat and det:
                scope.append({"category": cat, "details": det})
            elif cat:
                scope.append({"category": cat, "details": ""})
            elif parts:
                scope.append({"category": "Scope Item", "details": "; ".join(parts)})
        elif t == "table_row":
            attrs = li.get("attributes") or {}
            cat = attrs.get("category") or attrs.get("item") or attrs.get("title")
            det = (attrs.get("details") or attrs.get("description")
                   or attrs.get("requirement") or attrs.get("value") or "")
            if cat:
                scope.append({"category": cat, "details": det})
        elif t == "field":
            cat = li.get("label")
            det = li.get("value") or ""
            if cat:
                scope.append({"category": cat, "details": det})
        elif t == "paragraph":
            cat = li.get("title") or li.get("label")
            det = li.get("description") or li.get("value") or ""
            if cat and det:
                scope.append({"category": cat, "details": det})
            elif det:
                scope.append({"category": "General", "details": det})
        elif t == "bullet":
            title = li.get("title") or li.get("label")
            bullets = li.get("bullets") or []
            if title and bullets:
                scope.append({
                    "category": title,
                    "details": "\n".join(f"• {b}" for b in bullets if b),
                })
            elif bullets:
                for b in bullets:
                    if b:
                        scope.append({"category": "Scope Item", "details": b})
        elif t == "rule" and li.get("description"):
            scope.append({"category": "Requirement", "details": li["description"]})
    return scope

def _scope_from_section(section) -> list:
    """Pull scope rows from a section tree — subsections, section-level items, summaries."""
    if not section:
        return []
    scope = []
    for sub in section.get("subsections", []) or []:
        scope.extend(_collect_scope_items(sub.get("line_items")))
        summary = (sub.get("summary") or "").strip()
        if summary and not sub.get("line_items"):
            scope.append({"category": sub.get("title") or "Scope", "details": summary})
    scope.extend(_collect_scope_items(section.get("line_items")))
    summary = (section.get("summary") or "").strip()
    if summary and not scope:
        scope.append({"category": section.get("title") or "Scope of Work", "details": summary})
    return scope

def _extract_scope_of_work(sections):
    """Collect scope rows from section 2, with fallbacks for title/id drift."""
    scope = []

    sec2 = _section_by_id(sections, "2")
    if sec2:
        matched_subs = []
        for sub in sec2.get("subsections", []) or []:
            title = (sub.get("title") or "").strip().lower()
            if any(title == t or t in title for t in _SOW_SUBSECTION_TITLES):
                matched_subs.append(sub)
        if matched_subs:
            for sub in matched_subs:
                scope.extend(_collect_scope_items(sub.get("line_items")))
                summary = (sub.get("summary") or "").strip()
                if summary and not sub.get("line_items"):
                    scope.append({"category": sub.get("title") or "Scope", "details": summary})
        else:
            scope.extend(_scope_from_section(sec2))

    if not scope:
        for sec in sections or []:
            if not _is_sow_section_title(sec.get("title") or ""):
                continue
            scope.extend(_scope_from_section(sec))

    return scope

def _parse_advance_payments(line_items) -> list:
    """Parse advance payment rows from groups, table_rows, or fields."""
    advances = []
    for li in line_items or []:
        t = li.get("type")
        if t == "group":
            title = (li.get("title") or "").strip()
            for child in li.get("children", []) or []:
                if child.get("type") != "field" or not child.get("label"):
                    continue
                conditions = [c.strip() for c in (child.get("description") or "").split(";") if c.strip()]
                advances.append({
                    "component":  child["label"],
                    "percentage": _num(child.get("value")),
                    "conditions": conditions,
                })
            if title and not li.get("children"):
                det = li.get("description") or ""
                if det:
                    advances.append({"component": title, "percentage": _num(det), "conditions": []})
        elif t == "table_row":
            attrs = li.get("attributes") or {}
            comp = (attrs.get("component") or attrs.get("contract_part")
                    or attrs.get("part") or attrs.get("item"))
            pct = _num(attrs.get("percentage") or attrs.get("advance") or attrs.get("percent"))
            cond_raw = attrs.get("conditions") or attrs.get("trigger") or attrs.get("milestone") or ""
            conditions = [c.strip() for c in str(cond_raw).split(";") if c.strip()]
            if comp or pct is not None:
                advances.append({"component": comp, "percentage": pct, "conditions": conditions})
        elif t == "field" and li.get("label"):
            val = li.get("value") or ""
            if "%" in val or _num(val) is not None:
                conditions = [c.strip() for c in (li.get("description") or "").split(";") if c.strip()]
                advances.append({
                    "component":  li["label"],
                    "percentage": _num(val),
                    "conditions": conditions,
                })
    return advances

def _parse_progressive_payments(line_items) -> list:
    """Parse progressive/milestone payment rows."""
    progressive = []
    for li in line_items or []:
        if li.get("type") != "table_row":
            continue
        attrs = li.get("attributes") or {}
        comp = (attrs.get("component") or attrs.get("part")
                or attrs.get("contract_part") or attrs.get("installment"))
        milestone = (attrs.get("milestone") or attrs.get("trigger")
                     or attrs.get("conditions") or attrs.get("stage"))
        pct = _num(attrs.get("percentage") or attrs.get("percent"))
        if comp or milestone or pct is not None:
            progressive.append({
                "component":  comp,
                "milestone":  milestone,
                "percentage": pct,
            })
    if progressive:
        return progressive
    for r in _table_rows(line_items, "component", "milestone", "percentage"):
        if r.get("component") or r.get("milestone") or r.get("percentage") is not None:
            progressive.append({
                "component":  r.get("component"),
                "milestone":  r.get("milestone"),
                "percentage": _num(r.get("percentage")),
            })
    return progressive

def _dedupe_payment_rows(rows: list, key: str = "component") -> list:
    out = []
    seen = set()
    for row in rows:
        ident = (row.get(key) or row.get("milestone") or "").strip().lower()
        dedupe_key = ident or str(row)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        out.append(row)
    return out

def _merge_payment_terms(sections: list, ft: dict) -> None:
    """Merge advance/progressive/timeline data from any section in the tree."""
    for sec in sections or []:
        adv_sub = (_find_subsection(sec, "Advance Payments")
                   or _find_subsection_fuzzy(sec, "advance payment"))
        if adv_sub:
            advances = _parse_advance_payments(adv_sub.get("line_items"))
            if advances:
                ft["advance_payments"] = _dedupe_payment_rows(
                    (ft.get("advance_payments") or []) + advances
                )

        prog_sub = (_find_subsection(sec, "Progressive Payments")
                    or _find_subsection_fuzzy(sec, "progressive payment", "milestone payment"))
        if prog_sub:
            progressive = _parse_progressive_payments(prog_sub.get("line_items"))
            if progressive:
                ft["progressive_payments"] = _dedupe_payment_rows(
                    (ft.get("progressive_payments") or []) + progressive,
                    key="milestone",
                )

        timeline_sub = _find_subsection_fuzzy(sec, "payment timeline")
        if timeline_sub:
            fmap = _field_map(timeline_sub.get("line_items"))
            v = _num(_field_value(fmap, "Standard Timeline (Days)"))
            if v is not None and not ft.get("standard_timeline_days"):
                ft["standard_timeline_days"] = v
            v = _field_value(fmap, "Delayed Interest Rate")
            if v and not ft.get("delayed_interest_rate"):
                ft["delayed_interest_rate"] = v
            note = _field_value(fmap, "Payment Timeline Note")
            if note and not ft.get("payment_timeline_note"):
                ft["payment_timeline_note"] = note
            if not ft.get("standard_timeline_days"):
                days = _extract_payment_timeline_days(timeline_sub.get("line_items"))
                if days is not None:
                    ft["standard_timeline_days"] = days

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
                ("Title", "title"), ("Version", "version"),
                ("Issuing Authority", "issuing_authority"), ("Contract Type", "contract_type"),
                ("Bid System", "bid_system"), ("Funding Agency", "funding_agency"),
                ("Budget Category", "budget_category"),
                ("Scheme / Project Code", "scheme_code"),
                ("Date of Issue", "date_of_issue"),
            ):
                v = _field_value(fmap, label)
                if v:
                    overview[key] = v
            ref = _field_value_any(fmap, *_REFERENCE_LABELS_FULL)
            if not ref:
                ref = _field_value_any(fmap, *_REFERENCE_LABELS_FALLBACK)
            if ref:
                overview["reference_no"] = ref
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
                    attrs = li.get("attributes") or {}
                    email = (li.get("description") or "").strip() or attrs.get("email")
                    phone = attrs.get("phone")
                    if email and not phone:
                        parsed_email, parsed_phone = _parse_contact_channels(email)
                        email, phone = parsed_email, parsed_phone or phone
                    entry = {
                        "name":  li.get("title"),
                        "role":  li.get("subtitle") or None,
                        "email": email or None,
                    }
                    if phone:
                        entry["phone"] = phone
                    contacts.append(entry)
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
                ("Tender Sale Start", "tender_sale_start"),
                ("Tender Sale End", "tender_sale_end"),
            ):
                v = _date_field(kfmap, label) or _field_value(kfmap, label)
                if v:
                    key_dates[key] = v
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
    scope = _extract_scope_of_work(sections)
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
            ps_grp = gmap.get("performance security")
            if ps_grp:
                v = _num(_child_field_value(ps_grp, "Percentage"))
                if v is not None:
                    guarantees.append({"type": "Performance Security", "percentage": v})
            if guarantees:
                ft["performance_guarantees"] = guarantees

        if ft:
            tender["financial_terms"] = ft

    # Payment terms may arrive in section 4 (legacy) or dedicated section 4P — merge all.
    ft = tender.get("financial_terms") or {}
    _merge_payment_terms(sections, ft)
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

            # Primary: table_row with item/formula/remark
            materials = [
                r for r in _table_rows(items, "item", "formula", "remark")
                if r.get("item") or r.get("formula")
            ]
            # Fallback: legacy formula line_items
            if not materials:
                for li in items:
                    if li.get("type") != "formula":
                        continue
                    title = (li.get("title") or "").strip()
                    if title.lower() == "composite formula":
                        continue
                    materials.append({
                        "item":    title or None,
                        "formula": li.get("formula"),
                        "remark":  (li.get("attributes") or {}).get("index_source") or li.get("reference"),
                    })
            if materials:
                pv["materials"] = materials
            rules = _bullets_by_title(items, "Key Rules")
            if rules:
                pv["key_rules"] = rules
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

    _normalize_tender_extraction(tender, sections)
    return tender


def extract_via_targeted_retrieval(token_fn, API_URL: str, pdf_path: str, content_hash: str, tender_ref: str = "", on_group_done=None) -> dict:
    """
    on_group_done, if given, is called after each extraction group finishes with
    (group_name, cumulative_usage_dict, groups_completed_count) — lets callers
    (app.py) surface live token/progress counters without persisting anything.
    """
    # Persist the PDF's pages/chunks/embeddings once (idempotent — a re-upload of the
    # same file skips straight to retrieval). Replaces the old per-call ephemeral
    # extract_and_chunk_pdf() + in-memory HybridRetriever, which was rebuilt and thrown
    # away on every request and left nothing durable for chat to ground on later.
    ingest_pdf(pdf_path, content_hash, tender_ref)
    doc_stats = get_document_stats(content_hash)
    page_count = doc_stats["page_count"]
    chunk_count = doc_stats["chunk_count"]
    print(
        f"[RAG] document stats: {page_count} pages, {chunk_count} chunks "
        f"({doc_stats['chunks_per_page']} chunks/page)"
    )

    # Keep token_fn callable so each LLM call can refresh the token on long runs
    _token_fn = token_fn if callable(token_fn) else None
    _static_token = token_fn() if callable(token_fn) else token_fn

    def _fresh_token() -> str:
        return _token_fn() if _token_fn else _static_token

    def _retrieve_for_group(group) -> list:
        """Retrieval phase — runs in parallel across all groups.

        Chunk budget scales with document size: small PDFs stay token-efficient,
        large/dense PDFs automatically get more context for high-priority groups
        (scope of work, technical bid documents).
        """
        max_retrieve, max_chunks = compute_chunk_budget(group, page_count, chunk_count)
        keyword_sets = [group["keywords"]] + group.get("extra_keyword_sets", [])

        section_ids = group.get("section_ids")

        def _retrieve(query, top_k, rerank_top_n):
            return retrieve_chunks(
                content_hash,
                query,
                top_k=top_k,
                rerank_top_n=rerank_top_n,
                section_ids=section_ids,
            )

        chunks = merge_and_cap_chunks(keyword_sets, _retrieve, max_retrieve, max_chunks)

        if group.get("boost_early_pages"):
            early = get_early_page_chunks(
                content_hash,
                max_page=group.get("early_page_max", 10),
                max_chunks=group.get("early_page_slots", 8),
            )
            chunks = merge_boost_early_pages(
                chunks,
                early,
                max_chunks,
                min_early_slots=min(4, group.get("early_page_slots", 8)),
            )

        budget_note = "dynamic" if group.get("chunk_budget") else "fixed"
        print(
            f"[RAG] '{group['name']}': {len(chunks)} chunks → LLM "
            f"(cap {max_chunks}, retrieve {max_retrieve}, {budget_note})"
        )
        return chunks

    def _call_llm_for_group(group, chunks) -> tuple:
        """LLM call phase — runs sequentially (1→6) to enable prompt-cache hits."""
        if not chunks:
            print(f"[RAG] '{group['name']}': no chunks retrieved")
            return [], {}

        chunk_block = "\n\n---\n".join(chunks)
        payload = build_cached_extraction_payload(
            SHARED_EXTRACTION_PREAMBLE,
            group["prompt"],
            chunk_block,
            _DOCUMENT_SECTIONS_TOOL_SCHEMA,
            max_tokens=group.get("max_output_tokens", 4096),
        )

        result, usage = get_result_tool_use(_fresh_token(), API_URL, payload)
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
        "cache_read_input_tokens": 0,
    }

    # ── Phase 1: parallel retrieval ──────────────────────────────────────────
    retrieved_per_group: dict = {}
    with ThreadPoolExecutor(max_workers=9) as executor:
        futures = {executor.submit(_retrieve_for_group, g): g for g in _EXTRACTION_GROUPS}
        for future in as_completed(futures):
            group = futures[future]
            try:
                retrieved_per_group[group["name"]] = future.result()
            except Exception as exc:
                print(f"[RAG] '{group['name']}': retrieval failed: {exc}")
                retrieved_per_group[group["name"]] = []

    # ── Phase 2: sequential LLM calls (group 1→6, enables prompt-cache reads) ─
    groups_completed = 0
    for group in _EXTRACTION_GROUPS:
        chunks = retrieved_per_group.get(group["name"], [])
        try:
            group_sections, usage = _call_llm_for_group(group, chunks)
            if usage:
                total_usage["input_tokens"]               += usage.get("input_tokens") or 0
                total_usage["output_tokens"]              += usage.get("output_tokens") or 0
                total_usage["cache_creation_input_tokens"] += usage.get("cache_creation_input_tokens") or 0
                total_usage["cache_read_input_tokens"]     += usage.get("cache_read_input_tokens") or 0

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
    return postprocess_extraction_result(final_json, content_hash)
