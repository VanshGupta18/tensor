"""
pdf_generator.py
─────────────────
Renders a Tender Synopsis PDF that mirrors the DOCX template:
  - Navy title banner with org name, tender number, version and date
  - Numbered sections with column-header rows ("Parameter | Details", etc.)
  - Alternating row shading in all tables
  - Key Documents section rendered as a bullet list
  - Plain-text fallback for narrative sections (JV, Disclaimer)
  - Nested contact_details collapsed into a single "Contact" row

Input:  sections list from the structured tender JSON.
Output: PDF bytes (ReportLab — no system dependencies).
"""

import html
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    HRFlowable,
)

# Characters outside WinAnsiEncoding that appear in tender data — replace before
# passing to Paragraph() which uses built-in Helvetica (Latin-1 / WinAnsi only).
_CHAR_SUBS = str.maketrans({
    '₹': 'Rs.',    # ₹ Indian Rupee
    '€': 'EUR ',   # € Euro (not always in WinAnsi depending on build)
    '£': 'GBP ',   # £ Pound (is in Latin-1 but safe to keep)
    '≥': '>=',     # ≥ greater-than-or-equal (U+2265, not in Latin-1)
    '≤': '<=',     # ≤ less-than-or-equal (U+2264, not in Latin-1)
    '×': 'x',      # × multiplication sign
    '–': '-',      # – en-dash
    '—': '--',     # — em-dash
    '‘': "'",      # ' left single quote
    '’': "'",      # ' right single quote
    '“': '"',      # " left double quote
    '”': '"',      # " right double quote
    '…': '...',    # … ellipsis
    ' ': ' ',      # non-breaking space
})

def _safe(text) -> str:
    """Escape & < > and replace chars outside Latin-1/WinAnsi so ReportLab doesn't crash."""
    if not text:
        return ""
    s = str(text).translate(_CHAR_SUBS)
    s = html.escape(s)
    # Drop any remaining non-Latin-1 chars rather than crashing
    s = s.encode('latin-1', errors='replace').decode('latin-1')
    return s


# ── Colour palette ────────────────────────────────────────────────────────────
_NAVY      = colors.HexColor("#1e3a5f")
_WHITE     = colors.white
_COL_HDR   = colors.HexColor("#c5d5e8")   # column-header row fill
_ROW_ALT   = colors.HexColor("#f0f5fa")   # alternating data row fill
_BORDER    = colors.HexColor("#9fb3c8")
_LABEL_FG  = colors.HexColor("#334155")
_BODY_FG   = colors.HexColor("#1e293b")
_MUTED     = colors.HexColor("#64748b")

# ── Section configuration ─────────────────────────────────────────────────────
# Maps section heading key → (display label, [left-col, right-col] or None)
# None means the section is rendered as plain text or a bullet list.
_SECTION_CFG = {
    "tender_information":      ("Basic Tender Particulars",              ["Parameter",       "Details"]),
    "key_dates":               ("Key Dates",                             ["Event",           "Date & Time (IST)"]),
    "scope_of_work":           ("Scope of Work",                         ["Item",            "Details"]),
    "experience_requirements": ("Experience Requirements",               ["Criterion",       "Requirement"]),
    "financial_requirements":  ("Financial Requirements",                ["Criterion",       "Requirement"]),
    "eligibility_criteria":    ("Eligibility & Qualification",           ["Criterion",       "Requirement"]),
    "bid_security_financials": ("Bid Security & Financial Requirements", ["Item",            "Requirement"]),
    "payment_terms":           ("Payment Terms",                         ["Item",            "Details"]),
    "price_variation":         ("Price Variation / Escalation",          ["Material / Item", "Details"]),
    "contract_conditions":     ("Key Contract Conditions",               ["Condition",       "Details"]),
    "jv_requirements":         ("Joint Venture Requirements",            None),
    "technical_bid_documents": ("Key Documents – Technical Bid (Envelope 1)", None),
    "disclaimer":              ("Disclaimer",                            None),
}

# Sections rendered as bullet lists (content split by newlines)
_BULLET_SECTIONS = {"technical_bid_documents"}

# Sections rendered as plain paragraphs (no table)
_PLAIN_SECTIONS  = {"jv_requirements", "disclaimer"}


def _section_label(key: str) -> str:
    cfg = _SECTION_CFG.get(key)
    return cfg[0] if cfg else key.replace("_", " ").title()


def _col_headers(key: str):
    cfg = _SECTION_CFG.get(key)
    return cfg[1] if cfg else ["Item", "Details"]


# ── Styles ────────────────────────────────────────────────────────────────────

def _build_styles():
    ss = getSampleStyleSheet()

    ss.add(ParagraphStyle("BannerTitle",
        parent=ss["Normal"], fontSize=22, leading=28,
        textColor=_WHITE, alignment=TA_CENTER, fontName="Helvetica-Bold",
    ))
    ss.add(ParagraphStyle("BannerOrg",
        parent=ss["Normal"], fontSize=11, leading=15,
        textColor=_WHITE, alignment=TA_CENTER, fontName="Helvetica-Bold",
    ))
    ss.add(ParagraphStyle("BannerMeta",
        parent=ss["Normal"], fontSize=10, leading=14,
        textColor=colors.HexColor("#c8dff0"), alignment=TA_CENTER,
    ))
    ss.add(ParagraphStyle("SectionHeading",
        parent=ss["Normal"], fontSize=12, leading=16,
        textColor=_NAVY, fontName="Helvetica-Bold",
        spaceBefore=18, spaceAfter=5,
    ))
    ss.add(ParagraphStyle("ColHeader",
        parent=ss["Normal"], fontSize=9, leading=12,
        textColor=_LABEL_FG, fontName="Helvetica-Bold",
    ))
    ss.add(ParagraphStyle("CellLabel",
        parent=ss["Normal"], fontSize=9, leading=12,
        textColor=_LABEL_FG, fontName="Helvetica-Bold",
    ))
    ss.add(ParagraphStyle("CellValue",
        parent=ss["Normal"], fontSize=9, leading=12,
        textColor=_BODY_FG,
    ))
    ss.add(ParagraphStyle("BodyPara",
        parent=ss["Normal"], fontSize=10, leading=14,
        textColor=_BODY_FG, spaceAfter=6,
    ))
    ss.add(ParagraphStyle("BulletItem",
        parent=ss["Normal"], fontSize=9, leading=13,
        textColor=_BODY_FG, leftIndent=14, firstLineIndent=-10, spaceAfter=4,
    ))
    ss.add(ParagraphStyle("SubLabel",
        parent=ss["Normal"], fontSize=9, leading=12,
        textColor=_MUTED, fontName="Helvetica-Bold",
        spaceBefore=6, spaceAfter=3,
    ))

    return ss


# ── Title block ───────────────────────────────────────────────────────────────

def _build_title_block(sections: list, styles, page_w: float) -> list:
    title, org, tender_no, version, date_issue = "", "", "", "", ""

    ti = next((s for s in sections if s.get("heading") == "tender_information"), None)
    if ti:
        for sh in (ti.get("sub_headings") or []):
            h = sh.get("heading", "")
            c = sh.get("content", "")
            if   h == "tender_title":        title      = c
            elif h == "issuing_authority":   org        = c
            elif h == "tender_no":           tender_no  = c
            elif h == "version":             version    = c
            elif h == "date_of_issue":       date_issue = c

    rows = [[Paragraph("TENDER SYNOPSIS", styles["BannerTitle"])]]
    if org:
        rows.append([Paragraph(_safe(org), styles["BannerOrg"])])
    if title:
        rows.append([Paragraph(_safe(title), styles["BannerOrg"])])

    meta_parts = []
    if tender_no:
        line = f"Tender No: {_safe(tender_no)}"
        if version:
            line += f"  |  Version {_safe(version)}"
        meta_parts.append(line)
    if date_issue:
        meta_parts.append(f"Date of Issue: {_safe(date_issue)}")
    if meta_parts:
        rows.append([Paragraph("  |  ".join(meta_parts), styles["BannerMeta"])])

    tbl = Table(rows, colWidths=[page_w])
    tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), _NAVY),
        ("ALIGN",         (0, 0), (-1, -1), "CENTER"),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (0,  0),  10),
        ("BOTTOMPADDING", (0, 0), (0,  0),  6),
        ("TOPPADDING",    (0, 1), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 12),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 12),
    ]))

    return [tbl, Spacer(1, 10)]


# ── Table helpers ─────────────────────────────────────────────────────────────

def _flatten_leaves(sub_headings: list) -> str:
    """
    If every child is a leaf node, concatenate as 'Key: value  |  Key: value'.
    Used to collapse contact_details into a single table cell.
    """
    parts = []
    for sh in sub_headings:
        label = sh.get("heading", "").replace("_", " ").title()
        value = (sh.get("content") or "").strip()
        if value:
            parts.append(f"{_safe(label)}: {_safe(value)}")
    return "  |  ".join(parts)


def _emit_table(rows: list, page_w: float, depth: int, has_header: bool) -> list:
    indent = depth * 10 * mm
    avail  = page_w - indent
    col_w  = [avail * 0.33, avail * 0.67]

    tbl = Table(rows, colWidths=col_w, hAlign="LEFT",
                repeatRows=1 if has_header else 0)

    cmds = [
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("GRID",          (0, 0), (-1, -1), 0.4, _BORDER),
    ]

    start = 0
    if has_header:
        cmds.append(("BACKGROUND", (0, 0), (-1, 0), _COL_HDR))
        start = 1

    for i in range(start, len(rows)):
        if (i - start) % 2 == 0:
            cmds.append(("BACKGROUND", (0, i), (-1, i), _ROW_ALT))

    tbl.setStyle(TableStyle(cmds))

    if indent > 0:
        wrapper = Table([[tbl]], colWidths=[avail])
        wrapper.setStyle(TableStyle([
            ("LEFTPADDING",   (0, 0), (-1, -1), indent),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
            ("TOPPADDING",    (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        return [wrapper, Spacer(1, 4)]

    return [tbl, Spacer(1, 4)]


def _build_section_table(sub_headings: list, styles, page_w: float,
                         col_headers=None, depth: int = 0) -> list:
    """
    Render sub_headings as a 2-column table.
    - If col_headers provided, first row is a styled header row.
    - Nested leaf groups are flattened into a single value cell.
    - Nested non-leaf groups get a sub-label and their own indented table.
    """
    flowables = []
    rows      = []

    if col_headers:
        rows.append([
            Paragraph(col_headers[0], styles["ColHeader"]),
            Paragraph(col_headers[1], styles["ColHeader"]),
        ])

    for sh in sub_headings:
        heading = sh.get("heading", "")
        content = (sh.get("content") or "").strip()
        nested  = sh.get("sub_headings") or []
        label   = heading.replace("_", " ").title()

        if nested:
            all_leaves = all(not (n.get("sub_headings") or []) for n in nested)
            if all_leaves:
                # Compact: fold all children into one value cell
                rows.append([
                    Paragraph(_safe(label), styles["CellLabel"]),
                    Paragraph(_flatten_leaves(nested) or "—", styles["CellValue"]),
                ])
            else:
                # Flush current rows, then render sub-section separately
                if rows:
                    flowables.extend(_emit_table(rows, page_w, depth, bool(col_headers)))
                    rows = ([
                        [Paragraph(col_headers[0], styles["ColHeader"]),
                         Paragraph(col_headers[1], styles["ColHeader"])]
                    ] if col_headers else [])

                flowables.append(Paragraph(f"<b>{_safe(label)}</b>", styles["SubLabel"]))
                flowables.extend(
                    _build_section_table(nested, styles, page_w, depth=depth + 1)
                )
        else:
            cell_content = _safe(content).replace("\n", "<br/>") if content else "—"
            rows.append([
                Paragraph(_safe(label), styles["CellLabel"]),
                Paragraph(cell_content, styles["CellValue"]),
            ])

    if rows:
        flowables.extend(_emit_table(rows, page_w, depth, bool(col_headers)))

    return flowables


# ── Bullet-list rendering (for technical_bid_documents) ──────────────────────

def _build_bullet_list(content: str, sub_headings: list, styles) -> list:
    flowables = []
    all_text = content
    for sh in sub_headings:
        c = (sh.get("content") or "").strip()
        if c:
            all_text = (all_text + "\n" + c).strip()

    for line in all_text.split("\n"):
        line = line.strip()
        if line:
            flowables.append(Paragraph(f"• {_safe(line)}", styles["BulletItem"]))

    return flowables


# ── Plain-text rendering (for jv_requirements, disclaimer, bare content) ──────

def _build_plain_text(content: str, sub_headings: list, styles) -> list:
    flowables = []
    if content.strip():
        flowables.append(Paragraph(_safe(content).replace("\n", "<br/>"), styles["BodyPara"]))
    for sh in sub_headings:
        c = (sh.get("content") or "").strip()
        if c:
            flowables.append(Paragraph(_safe(c).replace("\n", "<br/>"), styles["BodyPara"]))
    return flowables


# ── Public API ────────────────────────────────────────────────────────────────

def generate_tender_pdf(sections: list, doc_title: str = "Tender Synopsis") -> bytes:
    """
    Generate a PDF from the tender sections JSON.

    Parameters
    ----------
    sections : list
        The ``sections`` array from the structured tender JSON.
        Each element is ``{ heading, content?, sub_headings? }``.
    doc_title : str
        Used for the PDF metadata title.

    Returns
    -------
    bytes
        The rendered PDF file contents.
    """
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=15 * mm,  bottomMargin=15 * mm,
        title=doc_title,
    )

    styles = _build_styles()
    page_w = A4[0] - 36 * mm

    story = _build_title_block(sections, styles, page_w)

    for sec_num, section in enumerate(sections, start=1):
        heading = section.get("heading", "")
        content = (section.get("content") or "").strip()
        subs    = section.get("sub_headings") or []

        label = _section_label(heading)
        story.append(Paragraph(f"{sec_num}. {_safe(label)}", styles["SectionHeading"]))

        if heading in _BULLET_SECTIONS:
            if content:
                story.append(Paragraph(_safe(content).replace("\n", "<br/>"), styles["BodyPara"]))
            story.extend(_build_bullet_list("", subs, styles))

        elif heading in _PLAIN_SECTIONS or not subs:
            story.extend(_build_plain_text(content, subs, styles))

        else:
            # Render section content paragraph first (e.g. scope_of_work summary)
            if content:
                story.append(Paragraph(_safe(content).replace("\n", "<br/>"), styles["BodyPara"]))
            hdrs = _col_headers(heading)
            story.extend(_build_section_table(subs, styles, page_w, hdrs))

    doc.build(story)
    return buf.getvalue()
