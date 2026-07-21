"""
Synopsis preparation — shapes raw extraction JSON for readable PDF/display output.

Raw extraction stays complete in storage (chat, audit). This module applies
generic, tender-agnostic rules before PDF generation: concise scope rows,
filtered boilerplate, derived eligibility amounts, grouped bid checklists, etc.
"""

from __future__ import annotations

import copy
import re
from typing import Any

# Routine erection/installation lines the LLM often dumps as "special requirements".
_GENERIC_SPECIAL_REQ_PATTERNS = (
    r"installation strictly per approved",
    r"responsible for successful installation",
    r"contractor responsible for timely procurement",
    r"contractor liable for damage",
    r"exercise care to avoid damage",
    r"make all mechanical and electrical connections",
    r"equipment to be cordoned",
    r"hand over old/dismantled",
    r"handing over works to employer",
    r"dismantling, handling and shifting",
)

_SCOPE_DETAIL_MAX = 220
_SCOPE_MAX_ROWS = 12

_DISCLAIMER_TEMPLATE = (
    "Prepared for internal reference from the source bidding document. "
    "In case of any discrepancy, the original bidding document shall prevail."
)


def _truncate(text: str, max_len: int = _SCOPE_DETAIL_MAX) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    if len(text) <= max_len:
        return text
    cut = text[: max_len + 1]
    boundary = max(cut.rfind(". "), cut.rfind("; "), cut.rfind(", "))
    if boundary > max_len // 2:
        return cut[: boundary + 1].strip()
    return cut[:max_len].rstrip() + "..."


def _normalize_category(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip().lower())


def _merge_scope_rows(scope: list[dict]) -> list[dict]:
    """Collapse duplicate/near-duplicate categories; cap row count for synopsis."""
    if not scope:
        return []

    merged: dict[str, dict] = {}
    order: list[str] = []

    for item in scope:
        cat = (item.get("category") or "Scope Item").strip()
        det = _truncate(item.get("details") or "")
        key = _normalize_category(cat)
        if key in merged:
            prev = merged[key]["details"]
            if det and det not in prev:
                merged[key]["details"] = _truncate(f"{prev}; {det}", _SCOPE_DETAIL_MAX + 40)
        else:
            merged[key] = {"category": cat, "details": det}
            order.append(key)

    rows = [merged[k] for k in order if merged[k].get("category")]

    if len(rows) <= _SCOPE_MAX_ROWS:
        return rows

    # Prefer shorter, more distinct category labels when trimming excess rows.
    rows.sort(key=lambda r: (len(r.get("details") or ""), len(r.get("category") or "")))
    kept = rows[:_SCOPE_MAX_ROWS]
    kept.sort(key=lambda r: order.index(_normalize_category(r["category"])) if _normalize_category(r["category"]) in order else 999)
    return kept


def _estimated_cost_inr_lakhs(overview: dict) -> float | None:
    cost = overview.get("estimated_cost") or {}
    amount = cost.get("amount")
    if amount is None:
        return None
    try:
        val = float(amount)
    except (TypeError, ValueError):
        return None
    denom = (cost.get("denomination") or "").strip().lower()
    if "crore" in denom:
        return val * 100.0
    if "lakh" in denom:
        return val
    # Bare INR amounts in government tenders are usually lakhs when > 1000
    if val > 1000:
        return val
    return val * 100.0


def _format_inr_from_lakhs(lakhs: float) -> str:
    if lakhs >= 100:
        crore = lakhs / 100.0
        return f"~Rs. {crore:,.2f} Crore"
    return f"~Rs. {lakhs:,.2f} Lakhs"


def _enrich_eligibility_requirements(eq: dict, est_lakhs: float | None) -> None:
    if not est_lakhs:
        return

    tech = eq.get("technical") or {}
    for opt in tech.get("options") or []:
        req = opt.get("requirement") or ""
        if not req or "~Rs." in req:
            continue
        pct = None
        m = re.search(r"(\d+(?:\.\d+)?)\s*%\s*of", req, re.I)
        if m:
            pct = float(m.group(1))
        if pct:
            derived = est_lakhs * pct / 100.0
            opt["requirement"] = f"{req} ({_format_inr_from_lakhs(derived)})"

    for row in eq.get("financial") or []:
        req = row.get("requirement") or ""
        if not req or "~Rs." in req:
            continue
        m = re.search(r"(\d+(?:\.\d+)?)\s*%\s*of", req, re.I)
        if m:
            derived = est_lakhs * float(m.group(1)) / 100.0
            row["requirement"] = f"{req} ({_format_inr_from_lakhs(derived)})"


def _is_boilerplate_special(text: str) -> bool:
    tl = (text or "").lower()
    return any(re.search(p, tl) for p in _GENERIC_SPECIAL_REQ_PATTERNS)


def _filter_special_requirements(items: list[str], max_items: int = 8) -> list[str]:
    kept = [s for s in items if s and not _is_boilerplate_special(s)]
    if kept:
        return kept[:max_items]
    originals = [s for s in items if s]
    originals.sort(key=len)
    return originals[:max_items]


def _group_technical_documents(docs: list[str]) -> list[str]:
    """Cluster form names into readable checklist bullets (generic patterns)."""
    if not docs:
        return []

    buckets: dict[str, list[str]] = {
        "Bid security & declarations": [],
        "Bid forms & authority": [],
        "Qualification & financial data": [],
        "Compliance, schedule & deviations": [],
        "Price adjustment & payment options": [],
        "Integrity & additional forms": [],
        "Other required documents": [],
    }

    def _bucket(doc: str) -> str:
        dl = doc.lower()
        if any(k in dl for k in ("form 3", "bid secur", "bank guarantee", "emd", "earnest")):
            return "Bid security & declarations"
        if any(k in dl for k in ("form 1", "form 2", "form 4", "letter of bid", "power of attorney", "bidder information")):
            return "Bid forms & authority"
        if any(k in dl for k in ("form 9", "qualification", "experience", "audited", "turnover", "banker")):
            return "Qualification & financial data"
        if any(k in dl for k in ("form 6", "form 11", "form 12", "form 13", "local content", "deviation", "undertaking", "completion schedule")):
            return "Compliance, schedule & deviations"
        if any(k in dl for k in ("form 16", "form 17", "price adjustment", "advance payment", "e-payment")):
            return "Price adjustment & payment options"
        if any(k in dl for k in ("form 21", "integrity pact", "form 7", "form 8", "joint deed", "jv")):
            return "Integrity & additional forms"
        return "Other required documents"

    for doc in docs:
        buckets[_bucket(doc)].append(doc)

    grouped: list[str] = []
    for title, items in buckets.items():
        if not items:
            continue
        if len(items) == 1:
            grouped.append(items[0])
        elif len(items) <= 3:
            grouped.append(f"{title}: " + "; ".join(items))
        else:
            grouped.append(f"{title} ({len(items)} forms): " + "; ".join(items[:3]) + "; ...")
    return grouped


def _resolve_date_of_issue(overview: dict) -> str:
    if overview.get("date_of_issue"):
        return str(overview["date_of_issue"])
    kd = overview.get("key_dates") or {}
    pub = kd.get("publication")
    if isinstance(pub, dict):
        return pub.get("date") or pub.get("value") or ""
    return str(pub) if pub else ""


def prepare_synopsis(tender: dict) -> dict:
    """
    Return a copy of *tender* shaped for synopsis PDF output.
    Does not mutate the input dict.
    """
    out = copy.deepcopy(tender)
    overview = out.get("tender_overview") or out.get("tender_information") or {}
    out["tender_overview"] = overview

    doi = _resolve_date_of_issue(overview)
    if doi:
        overview["date_of_issue"] = doi

    scope = out.get("scope_of_work")
    if isinstance(scope, list) and scope:
        out["scope_of_work"] = _merge_scope_rows(scope)

    est_lakhs = _estimated_cost_inr_lakhs(overview)
    eq = out.get("eligibility_and_qualification")
    if isinstance(eq, dict):
        _enrich_eligibility_requirements(eq, est_lakhs)

    cb = out.get("contract_and_bidding") or out.get("contract_conditions") or {}
    special = cb.get("special_requirements")
    if isinstance(special, list) and len(special) > 3:
        cb["special_requirements"] = _filter_special_requirements(special)

    tbd = cb.get("technical_bid_documents") or {}
    docs = tbd.get("grouped_documents") or []
    if len(docs) > 6:
        tbd["grouped_documents_synopsis"] = _group_technical_documents(docs)
        tbd["grouped_documents_full"] = docs
    elif docs:
        tbd["grouped_documents_synopsis"] = docs

    ref = overview.get("reference_no") or ""
    version = overview.get("version") or ""
    out["_synopsis_meta"] = {
        "disclaimer": _DISCLAIMER_TEMPLATE,
        "source_reference": ref,
        "source_version": version,
        "date_of_issue": doi,
    }
    return out
