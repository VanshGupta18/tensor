"""
PDF Generator - Tender Synopsis
================================
Produces a 9-section A4 PDF from the AI-extracted tender JSON.

New schema (6 top-level keys produced by the AI pipeline):
  tender_overview               -> sections 1 (Particulars) + 2 (Key Dates)
  scope_of_work                 -> section 3
  eligibility_and_qualification -> section 4
  financial_terms               -> section 5 (Security/EMD) + section 6 (Payment Schedule)
  price_variation               -> section 7
  contract_and_bidding          -> section 8 (Conditions) + section 9 (Technical Bid Docs)

Old-schema keys are accepted as fallbacks so existing stored rawResponse blobs
continue to render without a re-extraction:
  tender_information       <- old alias for tender_overview
  key_dates                <- old top-level (moved into tender_overview.key_dates)
  security_and_financials  <- old alias for financial_terms
  payment_terms            <- old alias for financial_terms
  contract_conditions      <- old alias for contract_and_bidding
  technical_bid_documents  <- old top-level (moved into contract_and_bidding)
"""

import html
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

# ── Unicode -> Latin-1 substitution map ───────────────────────────────────────
_CHAR_SUBS = str.maketrans({
    '\u20b9': 'Rs.',
    '\u20ac': 'EUR ',
    '\u00a3': 'GBP ',
    '\u2265': '>=',
    '\u2264': '<=',
    '\u00d7': 'x',
    '\u2013': '-',
    '\u2014': '--',
    '\u2018': "'",
    '\u2019': "'",
    '\u201c': '"',
    '\u201d': '"',
    '\u2026': '...',
    '\u00a0': ' ',
})


def _safe(text) -> str:
    """Escape and transliterate text so ReportLab's latin-1 codec never chokes."""
    if not text:
        return ""
    s = str(text).translate(_CHAR_SUBS)
    s = html.escape(s)
    s = s.encode('latin-1', errors='replace').decode('latin-1')
    return s


# ── Colour palette ────────────────────────────────────────────────────────────
_NAVY     = colors.HexColor("#1e3a5f")
_WHITE    = colors.white
_COL_HDR  = colors.HexColor("#c5d5e8")
_ROW_ALT  = colors.HexColor("#f0f5fa")
_BORDER   = colors.HexColor("#9fb3c8")
_LABEL_FG = colors.HexColor("#334155")
_BODY_FG  = colors.HexColor("#1e293b")


def _build_styles():
    ss = getSampleStyleSheet()
    ss.add(ParagraphStyle("BannerTitle",    parent=ss["Title"],    fontSize=18, leading=22, textColor=_WHITE,    fontName="Helvetica-Bold",  spaceAfter=4, alignment=1))
    ss.add(ParagraphStyle("BannerOrg",      parent=ss["Normal"],   fontSize=12, leading=16, textColor=_WHITE,    fontName="Helvetica",        alignment=1))
    ss.add(ParagraphStyle("BannerMeta",     parent=ss["Normal"],   fontSize=10, leading=14, textColor=colors.HexColor("#cbd5e1"), fontName="Helvetica", alignment=1, spaceBefore=4))
    ss.add(ParagraphStyle("SectionHeading", parent=ss["Heading2"], fontSize=14, leading=18, textColor=_NAVY,     fontName="Helvetica-Bold",  spaceBefore=16, spaceAfter=8))
    ss.add(ParagraphStyle("SubLabel",       parent=ss["Normal"],   fontSize=11, leading=14, textColor=_NAVY,     fontName="Helvetica-Bold",  spaceBefore=8,  spaceAfter=4))
    ss.add(ParagraphStyle("ColHeader",      parent=ss["Normal"],   fontSize=10, leading=12, textColor=_NAVY,     fontName="Helvetica-Bold"))
    ss.add(ParagraphStyle("CellLabel",      parent=ss["Normal"],   fontSize=10, leading=14, textColor=_LABEL_FG, fontName="Helvetica-Bold"))
    ss.add(ParagraphStyle("CellValue",      parent=ss["Normal"],   fontSize=10, leading=14, textColor=_BODY_FG,  fontName="Helvetica"))
    ss.add(ParagraphStyle("BodyPara",       parent=ss["Normal"],   fontSize=10, leading=14, textColor=_BODY_FG,  fontName="Helvetica",       spaceBefore=6, spaceAfter=6))
    ss.add(ParagraphStyle("BulletItem",     parent=ss["Normal"],   fontSize=10, leading=14, textColor=_BODY_FG,  fontName="Helvetica",       spaceBefore=2, leftIndent=10, firstLineIndent=-10))
    return ss


# ── Shared helpers ────────────────────────────────────────────────────────────

def _p(text, style):
    return Paragraph(_safe(str(text)), style)


def _gv(d, key, default=""):
    """dict.get(key, default) but also falls back on an explicit None value —
    the AI schema often includes a field with value null rather than omitting
    it, and plain .get() only substitutes default when the key is absent."""
    v = d.get(key)
    return default if v is None else v


def _is_real(val):
    """True only if a value has genuine extracted data (not a placeholder/empty)."""
    if not val:
        return False
    if isinstance(val, dict):
        if val.get("_status") == "not_extracted":
            return False
        return any(v not in (None, "", [], {}) for v in val.values())
    if isinstance(val, list):
        return len(val) > 0
    return bool(val)


def _kv_table(rows, page_w, has_header=True):
    """Two-column label/value table with optional header row."""
    if not rows:
        return []
    col_w = [page_w * 0.33, page_w * 0.67]
    tbl = Table(rows, colWidths=col_w, hAlign="LEFT",
                repeatRows=1 if has_header else 0, splitByRow=1)
    cmds = [
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
        ("TOPPADDING",    (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("GRID",          (0, 0), (-1, -1), 0.4, _BORDER),
    ]
    start = 1 if has_header else 0
    if has_header:
        cmds.append(("BACKGROUND", (0, 0), (-1, 0), _COL_HDR))
    for i in range(start, len(rows)):
        if (i - start) % 2 == 0:
            cmds.append(("BACKGROUND", (0, i), (-1, i), _ROW_ALT))
    tbl.setStyle(TableStyle(cmds))
    return [tbl, Spacer(1, 4)]


def _heading(story, num, title, styles):
    story.append(Paragraph(f"{num}. {title}", styles["SectionHeading"]))


# ── Banner ────────────────────────────────────────────────────────────────────

def _build_banner(tender, styles, page_w):
    ov        = tender.get("tender_overview") or tender.get("tender_information") or {}
    title     = ov.get("title", "")
    org       = ov.get("issuing_authority", "")
    tender_no = ov.get("reference_no", "")
    version   = ov.get("version", "")

    rows = [[_p("TENDER SYNOPSIS", styles["BannerTitle"])]]
    if org:
        rows.append([_p(org, styles["BannerOrg"])])
    if title:
        rows.append([_p(title, styles["BannerOrg"])])

    meta_parts = []
    if tender_no:
        line = f"Tender No: {_safe(tender_no)}"
        if version:
            line += f"  |  Version {_safe(version)}"
        meta_parts.append(line)
    if meta_parts:
        rows.append([_p("  |  ".join(meta_parts), styles["BannerMeta"])])

    tbl = Table(rows, colWidths=[page_w])
    tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), _NAVY),
        ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (0, 0),   10),
        ("BOTTOMPADDING", (0, 0), (0, 0),   6),
        ("TOPPADDING",    (0, 1), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 12),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 12),
    ]))
    return [tbl, Spacer(1, 10)]


# =============================================================================
# Nine section renderers  -  each returns the updated running counter
# =============================================================================

def _section1_particulars(tender, n, styles, page_w, story):
    """1. Basic Tender Particulars  (tender_overview flat fields)."""
    ov = tender.get("tender_overview") or tender.get("tender_information") or {}
    if not _is_real(ov):
        return n

    n += 1
    _heading(story, n, "Basic Tender Particulars", styles)

    rows = [[_p("Parameter", styles["ColHeader"]), _p("Details", styles["ColHeader"])]]
    for key in ("title", "reference_no", "version", "issuing_authority",
                "contract_type", "bid_system", "funding_agency", "budget_category"):
        val = ov.get(key)
        if val:
            rows.append([_p(key.replace("_", " ").title(), styles["CellLabel"]),
                         _p(val, styles["CellValue"])])

    cost = ov.get("estimated_cost") or {}
    if cost and cost.get("amount") not in (None, ""):
        cost_str = f"{cost.get('amount')} {_gv(cost, 'currency')} {_gv(cost, 'denomination')}".strip()
        rows.append([_p("Estimated Cost", styles["CellLabel"]), _p(cost_str, styles["CellValue"])])

    fee = ov.get("tender_fee") or {}
    if fee and fee.get("amount") not in (None, ""):
        fee_str = f"{fee.get('amount')} {_gv(fee, 'currency')}".strip()
        rows.append([_p("Tender Fee", styles["CellLabel"]), _p(fee_str, styles["CellValue"])])

    for c in (ov.get("contacts") or []):
        c_text = f"{_gv(c, 'name')} - {_gv(c, 'role')}".strip(" -")
        if c.get("email"):
            c_text += f" (Email: {c['email']})"
        if c.get("phone"):
            c_text += f" (Phone: {c['phone']})"
        rows.append([_p("Contact", styles["CellLabel"]), _p(c_text, styles["CellValue"])])

    if len(rows) > 1:
        story.extend(_kv_table(rows, page_w))
    return n


def _section2_key_dates(tender, n, styles, page_w, story):
    """2. Key Dates  (tender_overview.key_dates; top-level key_dates as fallback)."""
    ov = tender.get("tender_overview") or tender.get("tender_information") or {}
    kd = ov.get("key_dates") or {}
    if not kd:
        kd = tender.get("key_dates") or {}
    if not _is_real(kd):
        return n

    n += 1
    _heading(story, n, "Key Dates", styles)

    rows = [[_p("Event", styles["ColHeader"]), _p("Date & Time", styles["ColHeader"])]]
    for key, val in kd.items():
        display = ""
        if isinstance(val, dict):
            parts = [val.get("date", ""), val.get("time", ""), val.get("timezone", "")]
            display = " ".join(p for p in parts if p).strip()
        elif isinstance(val, str):
            display = val
        if display:
            rows.append([_p(key.replace("_", " ").title(), styles["CellLabel"]),
                         _p(display, styles["CellValue"])])
    if len(rows) > 1:
        story.extend(_kv_table(rows, page_w))
    return n


def _section3_scope(tender, n, styles, page_w, story):
    """3. Scope of Work."""
    sow = tender.get("scope_of_work") or []
    if not _is_real(sow) or not isinstance(sow, list):
        return n

    n += 1
    _heading(story, n, "Scope of Work", styles)

    rows = [[_p("Category", styles["ColHeader"]), _p("Details", styles["ColHeader"])]]
    for item in sow:
        if item.get("category"):
            rows.append([_p(item["category"], styles["CellLabel"]),
                         _p(item.get("details", ""), styles["CellValue"])])
    if len(rows) > 1:
        story.extend(_kv_table(rows, page_w))
    return n


def _section4_eligibility(tender, n, styles, page_w, story):
    """4. Eligibility & Qualification."""
    eq = tender.get("eligibility_and_qualification") or {}
    if not _is_real(eq):
        return n

    n += 1
    _heading(story, n, "Eligibility & Qualification", styles)

    tech = eq.get("technical") or {}
    if tech:
        story.append(Paragraph("Technical", styles["SubLabel"]))
        if tech.get("heading_note"):
            story.append(Paragraph(_safe(tech["heading_note"]), styles["BodyPara"]))
        t_rows = [[_p("Option", styles["ColHeader"]), _p("Requirement", styles["ColHeader"])]]
        for opt in (tech.get("options") or []):
            t_rows.append([_p(opt.get("option", ""), styles["CellLabel"]),
                           _p(opt.get("requirement", ""), styles["CellValue"])])
        if len(t_rows) > 1:
            story.extend(_kv_table(t_rows, page_w))
        if tech.get("similar_works_definition"):
            story.append(Paragraph(
                f"Similar works definition: {_safe(tech['similar_works_definition'])}",
                styles["BodyPara"]))

    fin = eq.get("financial") or []
    if fin:
        story.append(Paragraph("Financial / Commercial", styles["SubLabel"]))
        f_rows = [[_p("Criterion", styles["ColHeader"]), _p("Requirement", styles["ColHeader"])]]
        for f in fin:
            f_rows.append([_p(f.get("criterion", ""), styles["CellLabel"]),
                           _p(f.get("requirement", ""), styles["CellValue"])])
        if len(f_rows) > 1:
            story.extend(_kv_table(f_rows, page_w))

    if eq.get("contractor_class_required"):
        story.append(Paragraph(
            f"Contractor Class Required: {_safe(eq['contractor_class_required'])}",
            styles["BodyPara"]))
    if eq.get("bidding_capacity"):
        story.append(Paragraph(
            f"Bidding Capacity: {_safe(str(eq['bidding_capacity']))}",
            styles["BodyPara"]))
    return n


def _section5_financial_terms(ft, n, styles, page_w, story):
    """5. Financial Terms & Security  (EMD, guarantees, bid validity, bank details)."""
    if not _is_real(ft):
        return n

    n += 1
    _heading(story, n, "Financial Terms & Security", styles)

    rows = [[_p("Item", styles["ColHeader"]), _p("Requirement", styles["ColHeader"])]]

    emd = ft.get("emd") or {}
    if emd:
        parts = []
        if emd.get("percentage"):
            parts.append(f"{emd['percentage']}%")
        if emd.get("max_cap_inr"):
            cap = emd["max_cap_inr"]
            parts.append(f"Max: Rs. {cap:,.0f}" if isinstance(cap, (int, float)) else f"Max: {cap}")
        if emd.get("form"):
            parts.append(f"Form: {emd['form']}")
        rows.append([_p("EMD", styles["CellLabel"]), _p(", ".join(parts), styles["CellValue"])])

    if ft.get("bid_validity_days"):
        rows.append([_p("Bid Validity", styles["CellLabel"]),
                     _p(f"{ft['bid_validity_days']} days", styles["CellValue"])])

    if ft.get("retention_money_percent"):
        rows.append([_p("Retention Money", styles["CellLabel"]),
                     _p(f"{ft['retention_money_percent']}%", styles["CellValue"])])

    for pg in (ft.get("performance_guarantees") or []):
        rows.append([_p(f"Performance Guarantee - {_gv(pg, 'type')}", styles["CellLabel"]),
                     _p(f"{_gv(pg, 'percentage')}%", styles["CellValue"])])

    bd = ft.get("bank_details") or {}
    if bd:
        bd_parts = [bd.get("bank") or ""]
        if bd.get("account"):
            bd_parts.append(f"Acc: {bd['account']}")
        if bd.get("ifsc"):
            bd_parts.append(f"IFSC: {bd['ifsc']}")
        rows.append([_p("Bank Details", styles["CellLabel"]),
                     _p(", ".join(p for p in bd_parts if p), styles["CellValue"])])

    if len(rows) > 1:
        story.extend(_kv_table(rows, page_w))
    return n


def _section6_payment_schedule(ft, n, styles, page_w, story):
    """6. Payment Schedule  (advance + progressive payments from financial_terms)."""
    adv  = ft.get("advance_payments")     or []
    prog = ft.get("progressive_payments") or []
    std  = ft.get("standard_timeline_days")
    rate = ft.get("delayed_interest_rate")

    if not (adv or prog or std or rate):
        return n

    n += 1
    _heading(story, n, "Payment Schedule", styles)

    rows = [[_p("Milestone / Component", styles["ColHeader"]),
             _p("Details", styles["ColHeader"])]]

    for a in adv:
        conds  = ", ".join(a.get("conditions") or [])
        detail = f"{_gv(a, 'percentage')}%"
        if conds:
            detail += f". Conditions: {conds}"
        rows.append([_p(f"Advance - {_gv(a, 'component')}", styles["CellLabel"]),
                     _p(detail, styles["CellValue"])])

    for pr in prog:
        detail = f"{_gv(pr, 'percentage')}%"
        if pr.get("milestone"):
            detail += f" - {pr['milestone']}"
        rows.append([_p(f"Progressive - {_gv(pr, 'component')}", styles["CellLabel"]),
                     _p(detail, styles["CellValue"])])

    if std:
        rows.append([_p("Standard Timeline", styles["CellLabel"]),
                     _p(f"{std} days", styles["CellValue"])])
    if rate:
        rows.append([_p("Delayed Interest Rate", styles["CellLabel"]),
                     _p(str(rate), styles["CellValue"])])

    if len(rows) > 1:
        story.extend(_kv_table(rows, page_w))
    return n


def _section7_price_variation(tender, n, styles, page_w, story):
    """7. Price Variation / Escalation — single Item / Formula / Remark table."""
    pv = tender.get("price_variation") or {}
    materials = pv.get("materials") or []
    has_data = bool(pv.get("is_applicable") is not None or materials)
    if not has_data:
        return n

    n += 1
    _heading(story, n, "Price Variation / Escalation", styles)

    materials = pv.get("materials") or []
    if materials:
        col_w = [page_w * 0.25, page_w * 0.45, page_w * 0.30]
        mat_rows = [[
            _p("Item", styles["ColHeader"]),
            _p("Formula", styles["ColHeader"]),
            _p("Remark", styles["ColHeader"]),
        ]]
        for m in materials:
            mat_rows.append([
                _p(m.get("item") or m.get("name", ""),    styles["CellLabel"]),
                _p(m.get("formula", ""),                   styles["CellValue"]),
                _p(m.get("remark") or m.get("index_source", ""), styles["CellValue"]),
            ])
        tbl = Table(mat_rows, colWidths=col_w, repeatRows=1)
        tbl.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, 0),  _NAVY),
            ("TEXTCOLOR",     (0, 0), (-1, 0),  _WHITE),
            ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.white, _ROW_ALT]),
            ("GRID",          (0, 0), (-1, -1), 0.5, _BORDER),
            ("VALIGN",        (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING",   (0, 0), (-1, -1), 6),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
            ("TOPPADDING",    (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(tbl)
        story.append(Spacer(1, 6))
    return n


def _section8_contract_conditions(cb, n, styles, page_w, story):
    """8. Contract Conditions  (contract_and_bidding, excluding technical_bid_documents)."""
    cb_check = {k: v for k, v in cb.items() if k != "technical_bid_documents"}
    if not _is_real(cb_check):
        return n

    n += 1
    _heading(story, n, "Contract Conditions", styles)

    rows = [[_p("Condition", styles["ColHeader"]), _p("Details", styles["ColHeader"])]]

    if cb.get("completion_time_months"):
        rows.append([_p("Completion Time", styles["CellLabel"]),
                     _p(f"{cb['completion_time_months']} months", styles["CellValue"])])
    if cb.get("defect_liability_period_months"):
        rows.append([_p("Defect Liability Period", styles["CellLabel"]),
                     _p(f"{cb['defect_liability_period_months']} months", styles["CellValue"])])

    ld = cb.get("liquidated_damages") or {}
    if ld:
        rows.append([_p("Liquidated Damages", styles["CellLabel"]),
                     _p(f"{_gv(ld, 'rate_per_week_percent')}% per week, "
                        f"max {_gv(ld, 'cap_percent')}%", styles["CellValue"])])

    qp = cb.get("quality_penalties") or {}
    if qp:
        rows.append([_p("Quality Penalties", styles["CellLabel"]),
                     _p(f"Major: {_gv(qp, 'major_defect_percent')}%, "
                        f"Minor: {_gv(qp, 'minor_defect_percent')}%", styles["CellValue"])])

    for req in (cb.get("special_requirements") or []):
        rows.append([_p("Special Requirement", styles["CellLabel"]),
                     _p(req, styles["CellValue"])])

    if len(rows) > 1:
        story.extend(_kv_table(rows, page_w))
    return n


def _section9_technical_bid_docs(cb, tender, n, styles, page_w, story):
    """9. Key Documents - Technical Bid.

    New schema: contract_and_bidding.technical_bid_documents
    Old schema: top-level technical_bid_documents
    """
    tbd = cb.get("technical_bid_documents") or {}
    if not tbd:
        tbd = tender.get("technical_bid_documents") or {}

    docs = tbd.get("grouped_documents") or []
    if not docs:
        return n

    n += 1
    _heading(story, n, "Key Documents - Technical Bid", styles)

    for doc in docs:
        story.append(Paragraph(f"- {_safe(doc)}", styles["BulletItem"]))

    if tbd.get("has_price_disclosure_warning"):
        story.append(Paragraph(
            "<b>WARNING: No prices to be disclosed in Envelope 1</b>",
            styles["BodyPara"]))
    return n


# =============================================================================
# Public entry point
# =============================================================================

def generate_tender_pdf(tender, doc_title="Tender Synopsis"):
    """
    Build a 9-section A4 PDF from *tender* (new or old schema).

    *tender* is the AI-extracted object for a single tender.

    New schema top-level keys:
        tender_overview, scope_of_work, eligibility_and_qualification,
        financial_terms, price_variation, contract_and_bidding

    Old-schema aliases are accepted as fallbacks (see module docstring).

    Returns raw PDF bytes.
    """
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=15 * mm, bottomMargin=15 * mm,
        title=doc_title,
    )
    styles = _build_styles()
    page_w = A4[0] - 36 * mm
    story  = _build_banner(tender, styles, page_w)
    n      = 0   # running section counter

    # Resolve financial_terms (new) with old-schema aliases
    ft = (tender.get("financial_terms")
          or tender.get("security_and_financials")
          or tender.get("payment_terms")
          or {})

    # Resolve contract_and_bidding (new) with old-schema alias
    cb = (tender.get("contract_and_bidding")
          or tender.get("contract_conditions")
          or {})

    # Render all 9 sections in order
    n = _section1_particulars(tender, n, styles, page_w, story)
    n = _section2_key_dates(tender, n, styles, page_w, story)
    n = _section3_scope(tender, n, styles, page_w, story)
    n = _section4_eligibility(tender, n, styles, page_w, story)
    n = _section5_financial_terms(ft, n, styles, page_w, story)
    n = _section6_payment_schedule(ft, n, styles, page_w, story)
    n = _section7_price_variation(tender, n, styles, page_w, story)
    n = _section8_contract_conditions(cb, n, styles, page_w, story)
    n = _section9_technical_bid_docs(cb, tender, n, styles, page_w, story)

    doc.build(story)
    return buf.getvalue()
