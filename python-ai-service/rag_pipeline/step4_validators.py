import copy
import re
from rag_pipeline.step1_schemas import _REQUIRED_SECTIONS

_EMAIL_RE = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}')
_PHONE_RE = re.compile(r'(?:\+?\d[\d\s\-()]{7,}\d|\d{10})')
_ADDRESS_HINTS = (
    "plot", "floor", "marg", "road", "street", "mumbai", "nagpur", "pin",
    "postal", "avenue", "lane", "bandra", "prakashgad", "kanekar", "east",
    "west", "zone", "building", "tower", "sector", "block",
)

_TITLE_KEYWORDS = frozenset({
    "engineer", "manager", "officer", "director", "chief", "superintendent",
    "commissioner", "secretary", "advisor", "executive", "assistant", "deputy",
    "joint", "additional", "general", "inspector", "incharge", "in-charge",
})

def _looks_like_title(s: str) -> bool:
    return bool(s) and any(kw in s.lower() for kw in _TITLE_KEYWORDS)

def _looks_like_address(s: str) -> bool:
    if not s:
        return False
    sl = s.lower()
    return any(h in sl for h in _ADDRESS_HINTS) or (len(s) > 70 and "@" not in s)

def _parse_contact_channels(text: str) -> tuple:
    """Split a free-text description into (email, phone), rejecting addresses."""
    if not text or _looks_like_address(text):
        return None, None
    emails = _EMAIL_RE.findall(text)
    email = emails[0] if emails else None
    phone = None
    for m in _PHONE_RE.findall(text):
        digits = re.sub(r'\D', '', m)
        if len(digits) >= 10:
            phone = m.strip()
            break
    if not email and not phone and re.fullmatch(r'[\d\s\-+()]+', text.strip()):
        phone = text.strip()
    return email, phone

def _sanitize_contacts(result: dict) -> dict:
    """Drop invalid contacts and normalise email/phone fields."""
    for tender in result.get("tenders", []):
        contacts = tender.get("tender_overview", {}).get("contacts")
        if not isinstance(contacts, list):
            continue
        cleaned = []
        for c in contacts:
            if not isinstance(c, dict):
                continue
            name = (c.get("name") or "").strip()
            if not name:
                continue
            email = (c.get("email") or "").strip() or None
            phone = (c.get("phone") or "").strip() or None
            if email and _looks_like_address(email):
                email = None
            if not email and not phone:
                email, phone = _parse_contact_channels(c.get("email") or c.get("description") or "")
            elif email:
                parsed_email, parsed_phone = _parse_contact_channels(email)
                if parsed_email:
                    email = parsed_email
                if not phone and parsed_phone:
                    phone = parsed_phone
            if not email and not phone:
                continue
            cleaned.append({
                "name": name,
                "role": (c.get("role") or "").strip() or None,
                "email": email,
                "phone": phone,
            })
        tender.setdefault("tender_overview", {})["contacts"] = cleaned
    return result

def _deduplicate_contacts(result: dict) -> dict:
    """Merge duplicate contacts within each tender.

    The AI often extracts the same person multiple times across chunks with
    different designations, and sometimes puts a job title in the 'name' field.
    We group by email (primary) or normalised name (fallback), then merge:
    - name  → whichever entry's name does NOT look like a job title
    - role  → longest string across all role fields AND any name fields that
              look like titles (since the AI often misplaces designations there)
    """
    for tender in result.get("tenders", []):
        contacts = tender.get("tender_overview", {}).get("contacts")
        if not isinstance(contacts, list) or len(contacts) <= 1:
            continue

        buckets: dict = {}
        for c in contacts:
            if not isinstance(c, dict):
                continue
            email = (c.get("email") or "").strip().lower()
            name  = (c.get("name")  or "").strip().lower()
            key   = email if email else name
            if not key:
                continue
            buckets.setdefault(key, []).append(c)

        deduped = []
        for group in buckets.values():
            if len(group) == 1:
                deduped.append(group[0])
                continue

            # Best name: prefer entries where name doesn't look like a job title
            all_names  = [(c.get("name") or "").strip() for c in group]
            real_names = [n for n in all_names if n and not _looks_like_title(n)]
            best_name  = real_names[0] if real_names else min(all_names, key=len)

            # Best role: name-fields that look like titles take priority over role fields,
            # because when the AI puts a designation in 'name' it is explicitly calling
            # out that title as the person's primary description. Tiebreak by length.
            role_candidates = []  # (priority, text)
            for c in group:
                if c.get("role"):
                    role_candidates.append((1, c["role"].strip()))
                n = (c.get("name") or "").strip()
                if _looks_like_title(n):
                    role_candidates.append((2, n))
            role_candidates.sort(key=lambda x: (x[0], len(x[1])), reverse=True)
            best_role = role_candidates[0][1] if role_candidates else None

            email = next((c.get("email") for c in group if c.get("email")), None)
            phone = next((c.get("phone") for c in group if c.get("phone")), None)
            entry = {"name": best_name, "role": best_role, "email": email}
            if phone:
                entry["phone"] = phone
            deduped.append(entry)

        tender.setdefault("tender_overview", {})["contacts"] = deduped

    return result

def _normalize_unknowns(obj):
    """Recursively replace '<UNKNOWN>', 'UNKNOWN', 'N/A', 'TBD' placeholder strings
    with None so downstream code and the UI see clean nulls instead of junk strings.
    Arrays whose only item is a placeholder are collapsed to [].
    """
    _PLACEHOLDERS = {"<unknown>", "unknown", "n/a", "tbd", "<n/a>", "none", "null", ""}
    if isinstance(obj, dict):
        return {k: _normalize_unknowns(v) for k, v in obj.items()}
    if isinstance(obj, list):
        cleaned = [_normalize_unknowns(i) for i in obj]
        cleaned = [i for i in cleaned if i not in (None, "", [], {})]
        return cleaned
    if isinstance(obj, str) and obj.strip().lower() in _PLACEHOLDERS:
        return None
    return obj

def validate_correctness(synthesized: dict) -> dict:
    tender = (synthesized.get("tenders") or [{}])[0]
    issues = []

    pt = tender.get("financial_terms") or {}

    # 1. Payment milestone sum-to-100 per component group
    milestones = pt.get("progressive_payments") or []
    for label in ("supply", "erection"):
        rows = [r for r in milestones if label in (r.get("component") or "").lower()]
        if rows:
            total = sum(r.get("percentage") or 0 for r in rows)
            if abs(total - 100) > 0.5:
                issues.append(
                    f"{label.title()} milestones sum to {total}% (expected 100) — "
                    f"rows: {[r.get('percentage') for r in rows]} — likely truncation"
                )

    # 2. Advance headline % vs sum of installments mentioned in conditions
    for ap in (pt.get("advance_payments") or []):
        headline = ap.get("percentage")
        parts = []
        for cond in (ap.get("conditions") or []):
            cond_str = str(cond)
            cond_str = re.sub(r'(?i)\bbg\s*(?:of)?\s*\d+(?:\.\d+)?\s*%', '', cond_str)
            cond_str = re.sub(r'(?i)\d+(?:\.\d+)?\s*%\s*(?:of\s*)?(?:bg|bank guarantee)', '', cond_str)
            parts += [float(m) for m in re.findall(r'\b(\d+(?:\.\d+)?)\s*%', cond_str)]
        if headline and parts:
            inst_sum = sum(parts)
            if abs(inst_sum - headline) > 0.5:
                issues.append(
                    f"Advance {ap.get('component','?')}: headline={headline}% but "
                    f"installments sum to {inst_sum}% {parts}"
                )

    # 3. EMD cross-check: emd_percentage × estimated_cost ≈ emd_max_cap
    sf       = tender.get("financial_terms") or {}
    emd      = sf.get("emd") or {}
    ec       = (tender.get("tender_overview") or {}).get("estimated_cost") or {}
    emd_pct  = emd.get("percentage")
    emd_cap  = emd.get("max_cap_inr")
    ec_amt   = ec.get("amount")
    ec_denom = (ec.get("denomination") or "").lower()
    if emd_pct and emd_cap and ec_amt:
        ec_lakhs = ec_amt if ec_denom in ("lakhs", "lakh", "") else ec_amt * 100
        expected_inr = (emd_pct / 100) * ec_lakhs * 100000
        
        # If expected is less than the cap, then the cap is suspiciously high.
        # If expected is greater than the cap, that is exactly how a cap works.
        if expected_inr < emd_cap:
            ratio = abs(expected_inr - emd_cap) / max(expected_inr, emd_cap, 1)
            if ratio > 0.25:
                issues.append(
                    f"EMD: {emd_pct}% × {ec_amt} {ec_denom} = {expected_inr:,.0f} INR "
                    f"which is much less than emd_max_cap={emd_cap} INR"
                )

    for issue in issues:
        print(f"[correctness] ⚠  {issue}")
    if not issues:
        print("[correctness] All arithmetic checks passed.")
    return synthesized

_ARRAY_SECTIONS = {"scope_of_work"}

def ensure_schema_completeness(synthesized: dict) -> dict:
    result = copy.deepcopy(synthesized)
    for tender in result.get("tenders", []):
        for section in _REQUIRED_SECTIONS:
            if not tender.get(section):
                tender[section] = [] if section in _ARRAY_SECTIONS else {"_status": "not_extracted"}
                print(f"[completeness] ⚠  Section '{section}' missing — added placeholder")
    return result
