import html
import re
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

_CHAR_SUBS = str.maketrans({
    '₹': 'Rs.',    # ₹ Indian Rupee
    '€': 'EUR ',   # € Euro 
    '£': 'GBP ',   # £ Pound 
    '≥': '>=',     
    '≤': '<=',     
    '×': 'x',      
    '–': '-',      
    '—': '--',     
    '‘': "'",      
    '’': "'",      
    '“': '"',      
    '”': '"',      
    '…': '...',    
    ' ': ' ',      
})

def _safe(text) -> str:
    if not text: return ""
    s = str(text).translate(_CHAR_SUBS)
    s = html.escape(s)
    s = s.encode('latin-1', errors='replace').decode('latin-1')
    return s

_NAVY      = colors.HexColor("#1e3a5f")
_WHITE     = colors.white
_COL_HDR   = colors.HexColor("#c5d5e8")
_ROW_ALT   = colors.HexColor("#f0f5fa")
_BORDER    = colors.HexColor("#9fb3c8")
_LABEL_FG  = colors.HexColor("#334155")
_BODY_FG   = colors.HexColor("#1e293b")
_MUTED     = colors.HexColor("#64748b")

def _build_styles():
    ss = getSampleStyleSheet()
    ss.add(ParagraphStyle("BannerTitle", parent=ss["Title"], fontSize=18, leading=22, textColor=_WHITE, fontName="Helvetica-Bold", spaceAfter=4))
    ss.add(ParagraphStyle("BannerOrg", parent=ss["Normal"], fontSize=12, leading=16, textColor=_WHITE, fontName="Helvetica", alignment=1))
    ss.add(ParagraphStyle("BannerMeta", parent=ss["Normal"], fontSize=10, leading=14, textColor=colors.HexColor("#cbd5e1"), fontName="Helvetica", alignment=1, spaceBefore=4))
    ss.add(ParagraphStyle("SectionHeading", parent=ss["Heading2"], fontSize=14, leading=18, textColor=_NAVY, fontName="Helvetica-Bold", spaceBefore=16, spaceAfter=8))
    ss.add(ParagraphStyle("SubLabel", parent=ss["Normal"], fontSize=11, leading=14, textColor=_NAVY, fontName="Helvetica-Bold", spaceBefore=8, spaceAfter=4))
    ss.add(ParagraphStyle("ColHeader", parent=ss["Normal"], fontSize=10, leading=12, textColor=_NAVY, fontName="Helvetica-Bold"))
    ss.add(ParagraphStyle("CellLabel", parent=ss["Normal"], fontSize=10, leading=14, textColor=_LABEL_FG, fontName="Helvetica-Bold"))
    ss.add(ParagraphStyle("CellValue", parent=ss["Normal"], fontSize=10, leading=14, textColor=_BODY_FG, fontName="Helvetica"))
    ss.add(ParagraphStyle("BodyPara", parent=ss["Normal"], fontSize=10, leading=14, textColor=_BODY_FG, fontName="Helvetica", spaceBefore=6, spaceAfter=6))
    ss.add(ParagraphStyle("BulletItem", parent=ss["Normal"], fontSize=10, leading=14, textColor=_BODY_FG, fontName="Helvetica", spaceBefore=2, leftIndent=10, firstLineIndent=-10))
    return ss

def _build_title_block(tender: dict, styles, page_w: float) -> list:
    ti = tender.get("tender_information", {})
    title = ti.get("title", "")
    org = ti.get("issuing_authority", "")
    tender_no = ti.get("reference_no", "")
    version = ti.get("version", "")
    
    rows = [[Paragraph("TENDER SYNOPSIS", styles["BannerTitle"])]]
    if org: rows.append([Paragraph(_safe(org), styles["BannerOrg"])])
    if title: rows.append([Paragraph(_safe(title), styles["BannerOrg"])])

    meta_parts = []
    if tender_no:
        line = f"Tender No: {_safe(tender_no)}"
        if version: line += f"  |  Version {_safe(version)}"
        meta_parts.append(line)
    if meta_parts:
        rows.append([Paragraph("  |  ".join(meta_parts), styles["BannerMeta"])])

    tbl = Table(rows, colWidths=[page_w])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _NAVY),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (0,  0),  10),
        ("BOTTOMPADDING", (0, 0), (0,  0),  6),
        ("TOPPADDING", (0, 1), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
    ]))
    return [tbl, Spacer(1, 10)]

def _emit_table(rows: list, page_w: float, has_header: bool) -> list:
    if not rows: return []
    col_w  = [page_w * 0.33, page_w * 0.67]
    tbl = Table(rows, colWidths=col_w, hAlign="LEFT", repeatRows=1 if has_header else 0, splitByRow=1)
    cmds = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("GRID", (0, 0), (-1, -1), 0.4, _BORDER),
    ]
    start = 1 if has_header else 0
    if has_header: cmds.append(("BACKGROUND", (0, 0), (-1, 0), _COL_HDR))
    for i in range(start, len(rows)):
        if (i - start) % 2 == 0: cmds.append(("BACKGROUND", (0, i), (-1, i), _ROW_ALT))
    tbl.setStyle(TableStyle(cmds))
    return [tbl, Spacer(1, 4)]

def _to_para(label: str, style) -> Paragraph:
    return Paragraph(_safe(str(label)), style)

def generate_tender_pdf(tender: dict, doc_title: str = "Tender Synopsis") -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18*mm, rightMargin=18*mm, topMargin=15*mm, bottomMargin=15*mm, title=doc_title)
    styles = _build_styles()
    page_w = A4[0] - 36 * mm
    story = _build_title_block(tender, styles, page_w)
    display_num = 0

    # 1. Tender Information
    ti = tender.get("tender_information", {})
    if ti:
        display_num += 1
        story.append(Paragraph(f"{display_num}. Basic Tender Particulars", styles["SectionHeading"]))
        rows = [[_to_para("Parameter", styles["ColHeader"]), _to_para("Details", styles["ColHeader"])]]
        for k, v in ti.items():
            if k in ("estimated_cost", "tender_fee", "contacts"): continue
            if v: rows.append([_to_para(k.replace('_', ' ').title(), styles["CellLabel"]), _to_para(v, styles["CellValue"])])
        
        cost = ti.get("estimated_cost", {})
        if cost and cost.get("amount"):
            rows.append([_to_para("Estimated Cost", styles["CellLabel"]), _to_para(f"{cost.get('amount')} {cost.get('currency','')} {cost.get('denomination','')}".strip(), styles["CellValue"])])
        
        fee = ti.get("tender_fee", {})
        if fee and fee.get("amount"):
            rows.append([_to_para("Tender Fee", styles["CellLabel"]), _to_para(f"{fee.get('amount')} {fee.get('currency','')}".strip(), styles["CellValue"])])
            
        contacts = ti.get("contacts", [])
        for c in contacts:
            c_text = f"{c.get('name', '')} - {c.get('role', '')}".strip(" -")
            if c.get('email'): c_text += f" (Email: {c['email']})"
            rows.append([_to_para("Contact", styles["CellLabel"]), _to_para(c_text, styles["CellValue"])])
        
        story.extend(_emit_table(rows, page_w, True))

    # 2. Key Dates
    kd = tender.get("key_dates", {})
    if kd:
        display_num += 1
        story.append(Paragraph(f"{display_num}. Key Dates", styles["SectionHeading"]))
        rows = [[_to_para("Event", styles["ColHeader"]), _to_para("Date & Time", styles["ColHeader"])]]
        for k, v in kd.items():
            val = ""
            if isinstance(v, dict): val = f"{v.get('date','')} {v.get('time','')}".strip()
            elif isinstance(v, str): val = v
            if val: rows.append([_to_para(k.replace('_', ' ').title(), styles["CellLabel"]), _to_para(val, styles["CellValue"])])
        story.extend(_emit_table(rows, page_w, True))

    # 3. Scope of Work
    sow = tender.get("scope_of_work", [])
    if sow and isinstance(sow, list):
        display_num += 1
        story.append(Paragraph(f"{display_num}. Scope of Work", styles["SectionHeading"]))
        rows = [[_to_para("Category", styles["ColHeader"]), _to_para("Details", styles["ColHeader"])]]
        for item in sow:
            if item.get("category"): rows.append([_to_para(item["category"], styles["CellLabel"]), _to_para(item.get("details",""), styles["CellValue"])])
        story.extend(_emit_table(rows, page_w, True))

    # 4. Eligibility & Qualification
    eq = tender.get("eligibility_and_qualification", {})
    if eq:
        display_num += 1
        story.append(Paragraph(f"{display_num}. Eligibility & Qualification", styles["SectionHeading"]))
        
        tech = eq.get("technical", {})
        if tech:
            story.append(Paragraph("Technical", styles["SubLabel"]))
            if tech.get("heading_note"): story.append(Paragraph(_safe(tech["heading_note"]), styles["BodyPara"]))
            t_rows = [[_to_para("Option", styles["ColHeader"]), _to_para("Requirement", styles["ColHeader"])]]
            for opt in tech.get("options", []):
                t_rows.append([_to_para(opt.get("option",""), styles["CellLabel"]), _to_para(opt.get("requirement",""), styles["CellValue"])])
            if len(t_rows) > 1: story.extend(_emit_table(t_rows, page_w, True))
            if tech.get("similar_works_definition"): story.append(Paragraph(f"Similar works: {_safe(tech['similar_works_definition'])}", styles["BodyPara"]))
        
        fin = eq.get("financial", [])
        if fin:
            story.append(Paragraph("Financial / Commercial", styles["SubLabel"]))
            f_rows = [[_to_para("Criterion", styles["ColHeader"]), _to_para("Requirement", styles["ColHeader"])]]
            for f in fin:
                f_rows.append([_to_para(f.get("criterion",""), styles["CellLabel"]), _to_para(f.get("requirement",""), styles["CellValue"])])
            if len(f_rows) > 1: story.extend(_emit_table(f_rows, page_w, True))

    # 5. Security & Financials
    sf = tender.get("security_and_financials", {})
    if sf:
        display_num += 1
        story.append(Paragraph(f"{display_num}. Security & Financial Requirements", styles["SectionHeading"]))
        rows = [[_to_para("Item", styles["ColHeader"]), _to_para("Requirement", styles["ColHeader"])]]
        
        emd = sf.get("emd", {})
        if emd:
            rows.append([_to_para("EMD", styles["CellLabel"]), _to_para(f"{emd.get('percentage','')}%, Max: {emd.get('max_cap_inr','')}, Form: {emd.get('form','')}".strip(), styles["CellValue"])])
        if sf.get("bid_validity_days"):
            rows.append([_to_para("Bid Validity", styles["CellLabel"]), _to_para(f"{sf['bid_validity_days']} days", styles["CellValue"])])
        if sf.get("performance_security_percent"):
            rows.append([_to_para("Performance Security", styles["CellLabel"]), _to_para(f"{sf['performance_security_percent']}%", styles["CellValue"])])
        if sf.get("cpg_supply_percent"):
            rows.append([_to_para("CPG Supply", styles["CellLabel"]), _to_para(f"{sf['cpg_supply_percent']}%", styles["CellValue"])])
        if sf.get("cpg_erection_percent"):
            rows.append([_to_para("CPG Erection", styles["CellLabel"]), _to_para(f"{sf['cpg_erection_percent']}%", styles["CellValue"])])
        
        bd = sf.get("bank_details", {})
        if bd:
            rows.append([_to_para("Bank Details", styles["CellLabel"]), _to_para(f"{bd.get('bank','')}, Acc: {bd.get('account','')}, IFSC: {bd.get('ifsc','')}".strip(), styles["CellValue"])])
        
        story.extend(_emit_table(rows, page_w, True))

    # 6. Payment Terms
    pt = tender.get("payment_terms", {})
    if pt:
        display_num += 1
        story.append(Paragraph(f"{display_num}. Payment Terms", styles["SectionHeading"]))
        
        rows = [[_to_para("Milestone / Component", styles["ColHeader"]), _to_para("Details", styles["ColHeader"])]]
        for adv in pt.get("advance_payments", []):
            conds = ", ".join(adv.get("conditions", []))
            rows.append([_to_para(f"Advance: {adv.get('component','')}", styles["CellLabel"]), _to_para(f"{adv.get('percentage','')}%. Conditions: {conds}", styles["CellValue"])])
        for prog in pt.get("progressive_payments", []):
            rows.append([_to_para(f"Progressive: {prog.get('component','')}", styles["CellLabel"]), _to_para(f"{prog.get('percentage','')}%. {prog.get('milestone','')}", styles["CellValue"])])
        
        if pt.get("standard_timeline_days"):
            rows.append([_to_para("Standard Timeline", styles["CellLabel"]), _to_para(f"{pt['standard_timeline_days']} days", styles["CellValue"])])
        if pt.get("delayed_interest_rate"):
            rows.append([_to_para("Delayed Interest Rate", styles["CellLabel"]), _to_para(pt["delayed_interest_rate"], styles["CellValue"])])
            
        story.extend(_emit_table(rows, page_w, True))

    # 7. Price Variation
    pv = tender.get("price_variation", {})
    pv_has_data = bool(pv and (pv.get("is_applicable") or pv.get("materials") or
                               pv.get("variable_components") or pv.get("firm_components") or
                               pv.get("composite_formula")))
    if pv_has_data:
        display_num += 1
        story.append(Paragraph(f"{display_num}. Price Variation / Escalation", styles["SectionHeading"]))

        # Summary row — variable vs firm components
        summary_rows = [[_to_para("Item", styles["ColHeader"]), _to_para("Details", styles["ColHeader"])]]
        if pv.get("variable_components"):
            summary_rows.append([_to_para("Variable Components", styles["CellLabel"]), _to_para(", ".join(pv["variable_components"]), styles["CellValue"])])
        if pv.get("firm_components"):
            summary_rows.append([_to_para("Firm / Fixed Components", styles["CellLabel"]), _to_para(", ".join(pv["firm_components"]), styles["CellValue"])])
        if pv.get("composite_formula"):
            summary_rows.append([_to_para("Composite Formula", styles["CellLabel"]), _to_para(pv["composite_formula"], styles["CellValue"])])
        if len(summary_rows) > 1:
            story.extend(_emit_table(summary_rows, page_w, True))

        # Material-level 3-column table
        materials = pv.get("materials", [])
        if materials:
            mat_rows = [[
                _to_para("Material / Item", styles["ColHeader"]),
                _to_para("Formula (Summary)", styles["ColHeader"]),
                _to_para("Index Source & Reference", styles["ColHeader"]),
            ]]
            for mat in materials:
                mat_rows.append([
                    _to_para(mat.get("name", ""), styles["CellLabel"]),
                    _to_para(mat.get("formula", ""), styles["CellValue"]),
                    _to_para(mat.get("index_source", ""), styles["CellValue"]),
                ])
            # 3-col table: 20% name | 50% formula | 30% index source
            col_w = [page_w * 0.20, page_w * 0.50, page_w * 0.30]
            tbl = Table(mat_rows, colWidths=col_w, repeatRows=1)
            tbl.setStyle(TableStyle([
                ("BACKGROUND",  (0, 0), (-1, 0),  _NAVY),
                ("TEXTCOLOR",   (0, 0), (-1, 0),  colors.white),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _ROW_ALT]),
                ("GRID",        (0, 0), (-1, -1), 0.5, _BORDER),
                ("VALIGN",      (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING",  (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING",   (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING",(0, 0), (-1, -1), 5),
            ]))
            story.append(tbl)
            story.append(Spacer(1, 6))

    # 8. Contract Conditions
    cc = tender.get("contract_conditions", {})
    if cc:
        display_num += 1
        story.append(Paragraph(f"{display_num}. Contract Conditions", styles["SectionHeading"]))
        rows = [[_to_para("Condition", styles["ColHeader"]), _to_para("Details", styles["ColHeader"])]]
        
        if cc.get("completion_time_months"):
            rows.append([_to_para("Completion Time", styles["CellLabel"]), _to_para(f"{cc['completion_time_months']} months", styles["CellValue"])])
        if cc.get("defect_liability_period_months"):
            rows.append([_to_para("Defect Liability", styles["CellLabel"]), _to_para(f"{cc['defect_liability_period_months']} months", styles["CellValue"])])
        
        ld = cc.get("liquidated_damages", {})
        if ld:
            rows.append([_to_para("Liquidated Damages", styles["CellLabel"]), _to_para(f"{ld.get('rate_per_week_percent','')} per week, max {ld.get('cap_percent','')}%", styles["CellValue"])])
        
        qp = cc.get("quality_penalties", {})
        if qp:
            rows.append([_to_para("Quality Penalties", styles["CellLabel"]), _to_para(f"Major: {qp.get('major_defect_percent','')}%, Minor: {qp.get('minor_defect_percent','')}%", styles["CellValue"])])
            
        if cc.get("special_requirements"):
            rows.append([_to_para("Special Requirements", styles["CellLabel"]), _to_para(", ".join(cc["special_requirements"]), styles["CellValue"])])
            
        story.extend(_emit_table(rows, page_w, True))

    # 9. Key Documents
    kd_docs = tender.get("technical_bid_documents", {})
    if kd_docs:
        display_num += 1
        story.append(Paragraph(f"{display_num}. Key Documents – Technical Bid", styles["SectionHeading"]))
        
        for f in kd_docs.get("grouped_documents", []):
            story.append(Paragraph(f"• {_safe(f)}", styles["BulletItem"]))
        
        if kd_docs.get("has_price_disclosure_warning"):
            story.append(Paragraph("<b>WARNING: No prices to be disclosed in Envelope 1</b>", styles["BodyPara"]))

    doc.build(story)
    return buf.getvalue()
