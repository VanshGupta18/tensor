# ─────────────────────────────────────────────────────────────────────────────
# Shared extraction preamble — cached as the first message block in every
# LLM call (cache_control: ephemeral). Defines the generic format + rules once
# so each per-group prompt only needs to describe its own section structure.
# Keep this block ≥1024 tokens (combined with the tool schema's cache_control)
# to satisfy Anthropic/Bedrock's prompt-caching minimum.
# ─────────────────────────────────────────────────────────────────────────────

SHARED_EXTRACTION_PREAMBLE = """You are a specialist in extracting structured data from government tender documents (Request for Proposals, Notice Inviting Tenders, Standard Bidding Documents, BOQ documents, and similar procurement documents).

## Output Format: Section / SubSection / LineItem

You MUST use the `structure_document_sections` tool to output all results. Each call emits exactly ONE top-level Section. The section id, number, and title are fixed — use exactly what the task specifies.

### Structure hierarchy

Section
  id (string), number (string), title (string), summary (string, optional), importance ("low"|"medium"|"high", optional), order (integer, optional)
  subsections: SubSection[]
    id (dotted string, e.g. "1.1"), title (string), layout (see below), summary (string, optional)
    line_items: LineItem[]

### Subsection layout values
table | cards | list | paragraph | timeline | numbered_list | mixed

### LineItem types — all fields and usage

**field** — a labelled key/value pair (most common type)
  required: type="field", label (string), value (string)
  optional: attributes (object with string values only), description (string)
  Money fields: value = human-readable (e.g. "₹52,546.85 Lakhs"), attributes = {amount: "52546.85", currency: "INR", denomination: "Lakhs"}
  Date/time fields: value = human-readable, attributes = {date: "YYYY-MM-DD", time: "HH:MM", timezone: "IST"}

**card** — a named entity block
  required: type="card"
  optional: title (string), subtitle (string), description (string)
  Use for: contacts (title=name, subtitle=role, description=email/phone), scope categories (title=category, description=details)

**table_row** — one row of a tabular structure
  required: type="table_row", attributes (object with string values, one key per column)
  All rows in the same subsection must use consistent attribute keys.
  Example: {"criterion": "Annual Turnover", "requirement": "≥ 3× estimated cost"}

**bullet** — a titled list of items
  required: type="bullet", bullets (array of strings)
  optional: title (string)
  Use for: requirements lists, firm/variable price components, document checklists

**group** — a named cluster of children
  required: type="group", children (array of field or bullet items ONLY)
  optional: title (string), description (string)
  Children may ONLY be "field" or "bullet" types — no nested groups allowed.
  Use for: EMD (children = fields for percentage, cap, form), liquidated damages (rate %, cap %)

**formula** — a mathematical or escalation formula
  required: type="formula"
  optional: title (string), formula (string), reference (string), attributes (e.g. {index_source: "WPI"})

**rule** — a verbatim policy or contractual statement
  required: type="rule", description (string)
  Use sparingly — only for explicitly quoted regulatory or contractual clauses.

**paragraph** — free-form descriptive text
  required: type="paragraph"
  optional: title (string), description (string), value (string)

### Universal rules (apply to every extraction call)

1. Emit exactly ONE top-level Section per call. Never emit multiple top-level sections.
2. Extract ALL relevant information present in the chunks — do not summarise or truncate lists.
3. Omit a line_item, subsection, or entire subsection if and ONLY IF the data is genuinely absent from the provided document chunks. Never invent, guess, or synthesise values.
4. Do NOT output placeholder text: "N/A", "TBD", "Unknown", "Not stated", angle-bracket literals such as "<value>", or empty strings as meaningful values.
5. attributes values must always be plain strings — never nest objects or arrays inside attributes.
6. Group children use only "field" or "bullet" — no groups inside groups.
7. Numeric values in attributes.amount must be plain numbers without commas (e.g. "52546.85" not "52,546.85").
8. Date values in attributes.date: use YYYY-MM-DD if parseable, otherwise use the exact string as stated in the document.
9. Do not duplicate information across multiple subsections within the same section.
10. Every money field should have both a human-readable value AND a structured attributes object.
11. Extract ALL instances of a repeated pattern — all scope-of-work categories, all progressive payment milestones, all bid documents required — do not truncate or sample lists.
12. Prefer concrete, specific values over vague descriptions. "₹2.5 Crores" is better than "as specified in the document"."""

# ─────────────────────────────────────────────────────────────────────────────
# Generic document schema (Section -> SubSection -> LineItem)
# ─────────────────────────────────────────────────────────────────────────────
# The LLM is asked to structure each extraction group's findings using this
# domain-agnostic block model instead of one-off per-field JSON keys, so the
# same tool schema/prompt style works for tenders, RFPs, contracts, etc.
#
# Each of the 6 extraction groups below always emits ONE top-level Section
# (fixed id/number/title so downstream code can find it deterministically),
# containing 1-3 SubSections. _sections_to_legacy() in step5_extractor.py
# adapts this generic tree back into the exact legacy dict shape
# (tender_overview / scope_of_work / eligibility_and_qualification /
# financial_terms / price_variation / contract_and_bidding) that
# step4_validators.py, service.js, the frontend, and step7_pdf_generator.py
# already consume — none of those layers change.
#
# LineItem label/title conventions are fixed here AND relied on by the
# adapter's lookup tables — if you change a label string in a prompt below,
# update the matching lookup in step5_extractor.py's _sections_to_legacy().
# ─────────────────────────────────────────────────────────────────────────────

_LINE_ITEM_CHILD_SCHEMA = {
    "type": "object",
    "properties": {
        "type":        {"type": "string", "enum": ["field", "bullet"]},
        "label":       {"type": "string"},
        "value":       {"type": "string"},
        "description": {"type": "string"},
        "bullets":     {"type": "array", "items": {"type": "string"}},
    },
    "required": ["type"]
}

_LINE_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "type": {
            "type": "string",
            "enum": ["field", "paragraph", "bullet", "table_row", "card", "formula", "rule", "heading", "group"]
        },
        "title":       {"type": "string"},
        "subtitle":    {"type": "string"},
        "label":       {"type": "string"},
        "value":       {"type": "string"},
        "description": {"type": "string"},
        "formula":     {"type": "string"},
        "reference":   {"type": "string"},
        "bullets":     {"type": "array", "items": {"type": "string"}},
        "attributes":  {"type": "object", "additionalProperties": {"type": "string"}},
        "children":    {"type": "array", "items": _LINE_ITEM_CHILD_SCHEMA},
    },
    "required": ["type"]
}

_SUBSECTION_SCHEMA = {
    "type": "object",
    "properties": {
        "id":         {"type": "string"},
        "title":      {"type": "string"},
        "summary":    {"type": "string"},
        "layout":     {"type": "string", "enum": ["table", "cards", "list", "paragraph", "timeline", "numbered_list", "mixed"]},
        "line_items": {"type": "array", "items": _LINE_ITEM_SCHEMA},
    },
    "required": ["id", "title", "layout", "line_items"]
}

_SECTION_SCHEMA = {
    "type": "object",
    "properties": {
        "id":          {"type": "string"},
        "number":      {"type": "string"},
        "title":       {"type": "string"},
        "summary":     {"type": "string"},
        "importance":  {"type": "string", "enum": ["low", "medium", "high"]},
        "order":       {"type": "integer"},
        "subsections": {"type": "array", "items": _SUBSECTION_SCHEMA},
    },
    "required": ["id", "number", "title", "subsections"]
}

_DOCUMENT_SECTIONS_TOOL_SCHEMA = {
    "name": "structure_document_sections",
    "description": "Structure the extracted facts for this topic into the canonical Section/SubSection/LineItem document format.",
    "cache_control": {"type": "ephemeral"},
    "input_schema": {
        "type": "object",
        "properties": {
            "sections": {"type": "array", "items": _SECTION_SCHEMA}
        },
        "required": ["sections"]
    }
}

_EXTRACTION_GROUPS = [
    {
        "name": "tender_overview",
        "keywords": ["notice inviting", "nit", "estimated cost", "tender no", "brief description", "name of work", "tender fee", "issuing authority", "contract type", "bid system", "funding agency", "contact details"],
        # Dates and tender-reference each get their own retrieval pass so neither
        # crowds out the other on large PDFs (NIT/cover page vs schedule tables).
        "extra_keyword_sets": [
            ["key dates", "important dates", "schedule of bidding", "pre-bid meeting", "bid submission deadline", "technical bid opening", "financial bid opening", "date of publication", "work order issuance"],
            ["tender no", "reference no", "nit no", "notice inviting tender", "e-tender", "bid reference", "tender id", "tender number", "nit/rfb", "rfb notice"],
        ],
        "max_pages": 12,
        "chunk_budget": {
            "min_chunks": 18, "max_chunks": 28,
            "absolute_max_chunks": 40,
            "min_retrieve": 28, "max_retrieve": 44,
            "absolute_max_retrieve": 60,
            "ref_pages": 40, "mega_pages": 400, "priority": "high",
        },
        "boost_early_pages": True,
        "early_page_max": 10,
        "early_page_slots": 8,
        "prompt": """Extract ALL basic tender details, key dates, and contact persons. Emit exactly ONE section:

sections: [{
  "id": "1", "number": "1", "title": "Basic Tender Particulars", "order": 1,
  "subsections": [
    {
      "id": "1.1", "title": "Tender Information", "layout": "table",
      "line_items": [
        {"type": "field", "label": "Title", "value": "<tender title>"},
        {"type": "field", "label": "Reference No", "value": "<full tender/NIT reference exactly as printed on cover or NIT page — MANDATORY if present>"},
        {"type": "field", "label": "Version", "value": "<version number if stated>"},
        {"type": "field", "label": "Issuing Authority", "value": "<organization>"},
        {"type": "field", "label": "Contract Type", "value": "<e.g. Turnkey, Item Rate>"},
        {"type": "field", "label": "Bid System", "value": "<e.g. Single/Two-cover>"},
        {"type": "field", "label": "Funding Agency", "value": "<if any>"},
        {"type": "field", "label": "Budget Category", "value": "<if any>"},
        {"type": "field", "label": "Estimated Cost", "value": "<formatted amount with currency>", "attributes": {"amount": "<number as string>", "currency": "<e.g. INR>", "denomination": "<e.g. Lakhs, Crores, or empty>"}},
        {"type": "field", "label": "Tender Fee", "value": "<formatted amount with currency>", "attributes": {"amount": "<number as string>", "currency": "<e.g. INR>"}}
      ]
    },
    {
      "id": "1.2", "title": "Contacts", "layout": "cards",
      "line_items": [
        {"type": "card", "title": "<person name only — not a job title>", "subtitle": "<role/designation>", "description": "<email address only>", "attributes": {"phone": "<phone/mobile number if stated>"}}
      ]
    },
    {
      "id": "1.3", "title": "Key Dates", "layout": "table",
      "line_items": [
        {"type": "field", "label": "Publication", "value": "<date, plain string>"},
        {"type": "field", "label": "Pre-Bid Meeting", "value": "<date time timezone, human readable>", "attributes": {"date": "<YYYY-MM-DD or as stated>", "time": "<time or empty>", "timezone": "<e.g. IST or empty>"}},
        {"type": "field", "label": "Bid Submission Deadline", "value": "<...>", "attributes": {"date": "...", "time": "...", "timezone": "..."}},
        {"type": "field", "label": "Technical Opening", "value": "<...>", "attributes": {"date": "...", "time": "...", "timezone": "..."}},
        {"type": "field", "label": "Financial Opening", "value": "<...>", "attributes": {"date": "...", "time": "...", "timezone": "..."}},
        {"type": "field", "label": "Work Order Issuance", "value": "<date, plain string>"}
      ]
    }
  ]
}]

Omit any line item, subsection, or the whole 1.2/1.3 subsection entirely if that data genuinely is not present in the chunks — never invent placeholder values. Reference No (tender/NIT number) is mandatory — always emit it when any cover-page or NIT-page chunk shows a tender number, reference number, or NIT identifier; use the exact printed string including zone/region suffixes. For Contacts (1.2): extract ONLY named contact persons with email or phone — do NOT put office addresses, plot numbers, or issuing-authority addresses in the email field. If only one contact person is named in the chunks, emit only one card. Key dates are just as important as the basic details — do not omit them even if only briefly mentioned."""
    },
    {
        "name": "scope_of_work",
        "keywords": ["scope of work", "bill of quantities", "boq", "technical specifications", "drawings", "site clearance", "civil works"],
        # Electrical/distribution tenders often label scope differently — separate
        # retrieval passes so those chunks aren't crowded out by civil-work terms.
        "extra_keyword_sets": [
            ["distribution infrastructure", "system strengthening", "supply erection", "turnkey works", "HT line", "LT line", "substation", "transformer"],
            ["description of work", "schedule of work", "schedule of rates", "item description", "work to be executed", "nature of work"],
        ],
        "max_pages": 10,
        "chunk_budget": {
            "min_chunks": 20, "max_chunks": 36,
            "absolute_max_chunks": 60,
            "min_retrieve": 36, "max_retrieve": 56,
            "absolute_max_retrieve": 90,
            "ref_pages": 50, "mega_pages": 600, "priority": "high",
        },
        "prompt": """Extract the complete scope of work categories, BOQ summary, and construction details. Emit exactly ONE section:

sections: [{
  "id": "2", "number": "2", "title": "Scope of Work", "order": 2,
  "subsections": [{
    "id": "2.1", "title": "Scope of Work", "layout": "cards",
    "line_items": [
      {"type": "card", "title": "<work category>", "description": "<details of that category>"}
    ]
  }]
}]

One card per distinct scope-of-work category. Do not invent categories that aren't in the chunks."""
    },
    {
        "name": "eligibility_and_qualification",
        "keywords": ["turnover", "liquid assets", "similar work", "bid capacity", "net worth", "experience", "class of contractor", "registration"],
        "max_pages": 10,
        "max_retrieve": 20,
        "max_chunks": 12,
        "prompt": """Extract ALL technical and financial eligibility, contractor class requirements, and qualification criteria. Emit exactly ONE section:

sections: [{
  "id": "3", "number": "3", "title": "Eligibility & Qualification", "order": 3,
  "subsections": [
    {
      "id": "3.1", "title": "Technical Eligibility", "layout": "table",
      "line_items": [
        {"type": "field", "label": "Contractor Class Required", "value": "<class/category>"},
        {"type": "field", "label": "Bidding Capacity", "value": "<number>"},
        {"type": "field", "label": "Heading Note", "value": "<any prefatory note about technical eligibility>"},
        {"type": "field", "label": "Similar Works Definition", "value": "<what counts as 'similar work'>"},
        {"type": "table_row", "attributes": {"option": "<option label, e.g. Option A>", "requirement": "<requirement text>"}}
      ]
    },
    {
      "id": "3.2", "title": "Financial Eligibility", "layout": "table",
      "line_items": [
        {"type": "table_row", "attributes": {"criterion": "<e.g. Annual Turnover>", "requirement": "<requirement text>"}}
      ]
    }
  ]
}]

Omit any field/row not present in the chunks."""
    },
    {
        "name": "financial_terms",
        "keywords": ["earnest money", "emd", "bank guarantee", "performance security", "retention money", "bid validity", "bank details"],
        # Same dilution risk as tender_overview above: payment-schedule keywords get
        # their own retrieval query so they don't get crowded out by EMD/security terms.
        "extra_keyword_sets": [
            ["advance payment", "progressive payment", "milestone", "ra bill", "running account bill", "delayed payment interest"],
        ],
        "max_pages": 12,
        "max_retrieve": 24,
        "max_chunks": 16,
        "prompt": """Extract ALL EMD, performance security, bank details, retention money, bid validity, and all advance/progressive payment milestones and the payment timeline. Emit exactly ONE section:

sections: [{
  "id": "4", "number": "4", "title": "Financial Terms & Security", "order": 4,
  "subsections": [
    {
      "id": "4.1", "title": "Security & Financial Terms", "layout": "mixed",
      "line_items": [
        {"type": "group", "title": "EMD", "children": [
          {"type": "field", "label": "Percentage", "value": "<number>"},
          {"type": "field", "label": "Max Cap (INR)", "value": "<number>"},
          {"type": "field", "label": "Form", "value": "<e.g. Bank Guarantee, DD>"}
        ]},
        {"type": "group", "title": "Bank Details", "children": [
          {"type": "field", "label": "Bank", "value": "<bank name>"},
          {"type": "field", "label": "Account", "value": "<account number>"},
          {"type": "field", "label": "IFSC", "value": "<IFSC code>"}
        ]},
        {"type": "field", "label": "Bid Validity (Days)", "value": "<number>"},
        {"type": "field", "label": "Retention Money (%)", "value": "<number>"},
        {"type": "field", "label": "Standard Timeline (Days)", "value": "<number>"},
        {"type": "field", "label": "Delayed Interest Rate", "value": "<rate text>"},
        {"type": "table_row", "attributes": {"type": "<e.g. CPG Supply>", "percentage": "<number>"}}
      ]
    },
    {
      "id": "4.2", "title": "Advance Payments", "layout": "list",
      "line_items": [
        {"type": "group", "title": "Advance Payment", "children": [
          {"type": "field", "label": "<component, e.g. Supply>", "value": "<percentage>%", "description": "<conditions for this component, semicolon-separated if multiple>"}
        ]}
      ]
    },
    {
      "id": "4.3", "title": "Progressive Payments", "layout": "table",
      "line_items": [
        {"type": "table_row", "attributes": {"component": "<e.g. Supply>", "milestone": "<milestone text>", "percentage": "<number>"}}
      ]
    }
  ]
}]

Every advance-payment component (Supply, Erection, etc.) is one child field inside the single "Advance Payment" group — do not create a separate group per component. Omit any field/row/group not present in the chunks."""
    },
    {
        "name": "price_variation",
        "keywords": ["price variation", "price adjustment", "escalation", "star rate", "cement", "steel", "bitumen", "wpir", "labour", "ieema"],
        "extra_keyword_sets": [
            ["IEEMA", "ACSR conductor", "power transformer", "distribution transformer", "price variation formula", "index source"],
            ["firm components", "variable components", "composite formula", "escalation formula"],
        ],
        "max_pages": 10,
        "chunk_budget": {
            "min_chunks": 16, "max_chunks": 28,
            "absolute_max_chunks": 44,
            "min_retrieve": 30, "max_retrieve": 46,
            "absolute_max_retrieve": 70,
            "ref_pages": 80, "mega_pages": 600, "priority": "normal",
        },
        "prompt": """Extract ALL price-variation material formulas as table rows — one row per material/item. Emit exactly ONE section:

sections: [{
  "id": "5", "number": "5", "title": "Price Variation", "order": 5,
  "subsections": [{
    "id": "5.1", "title": "Price Variation", "layout": "table",
    "line_items": [
      {"type": "field", "label": "Is Applicable", "value": "Yes|No"},
      {"type": "table_row", "attributes": {"item": "<material or item name, e.g. ACSR Conductor>", "formula": "<price variation formula verbatim>", "remark": "<index source and reference, e.g. IEEMA circular>"}}
    ]
  }]
}]

Rules:
- Output ONE table_row per distinct material/item formula found in the chunks.
- Do NOT output separate Firm/Variable Components bullet lists — fold any such summary into remark only if no formula exists for that item.
- remark = index source, circular reference, or qualifying note (e.g. "Excise duty units"); leave empty if not stated.
- Extract every formula row even if the table spans multiple pages. Omit rows not present in the chunks."""
    },
    {
        "name": "contract_and_bidding",
        "keywords": ["defect liability", "liquidated damages", "completion time", "time for completion", "special conditions", "quality penalties"],
        # Same dilution risk: the technical-bid-document checklist is a distinct list
        # elsewhere in the document, so it gets its own retrieval query too.
        "extra_keyword_sets": [
            ["documents comprising the bid", "technical bid", "envelope 1", "letter of bid technical part", "form 1 section 4", "integral part of the technical part"],
            ["Form 9", "Form 10", "Form 11", "Form 12", "Form 13", "Form 14", "Form 15", "Form 16", "Form 17", "Form 18", "Form 19", "Form 20", "Form 21", "Integrity Pact"],
            ["special conditions of contract", "completion time", "performance security", "latent defect", "electrical inspector", "quality penalty", "defect liability period"],
        ],
        "max_output_tokens": 8192,
        "max_pages": 12,
        "chunk_budget": {
            "min_chunks": 24, "max_chunks": 40,
            "absolute_max_chunks": 68,
            "min_retrieve": 38, "max_retrieve": 60,
            "absolute_max_retrieve": 100,
            "ref_pages": 60, "mega_pages": 600, "priority": "high",
        },
        "prompt": """Extract ALL contract conditions (completion time, defect liability, liquidated damages, quality penalties, special requirements) and the exhaustive list of forms/documents required in the technical bid (Envelope 1). Emit exactly ONE section:

sections: [{
  "id": "6", "number": "6", "title": "Contract & Bidding Conditions", "order": 6,
  "subsections": [
    {
      "id": "6.1", "title": "Contract Conditions", "layout": "table",
      "line_items": [
        {"type": "field", "label": "Completion Time (Months)", "value": "<number>"},
        {"type": "field", "label": "Defect Liability Period (Months)", "value": "<number>"},
        {"type": "group", "title": "Liquidated Damages", "children": [
          {"type": "field", "label": "Rate/Week %", "value": "<number>"},
          {"type": "field", "label": "Cap %", "value": "<number>"}
        ]},
        {"type": "group", "title": "Quality Penalties", "children": [
          {"type": "field", "label": "Major Defect %", "value": "<number>"},
          {"type": "field", "label": "Minor Defect %", "value": "<number>"}
        ]},
        {"type": "bullet", "title": "Special Requirements", "bullets": ["<requirement>", "..."]}
      ]
    },
    {
      "id": "6.2", "title": "Technical Bid Documents", "layout": "numbered_list",
      "line_items": [
        {"type": "bullet", "bullets": ["<required document/form 1>", "<required document/form 2>", "..."]},
        {"type": "rule", "description": "<verbatim warning against disclosing prices in the technical bid, if present>"}
      ]
    }
  ]
}]

Include the "rule" item in 6.2 ONLY if the document explicitly warns against price disclosure in the technical bid.

CRITICAL — Technical Bid Documents (6.2):
- Locate the Form 1 "Letter of Bid – Technical Part" checklist table (Sr. 1 through 21, often spanning multiple pages).
- Output ONE bullet line_item whose bullets array contains EVERY row (typically 21–25 entries). Do NOT truncate after ~10 items.
- Must include Forms 9–21 when present: qualification data (Form 9), subcontractor details (Form 10), undertaking (Form 11), deviation statement (Form 12), work schedule (Form 13), guarantee (Form 14), ex-employees (Form 15), price adjustment (Form 16), advance payment (Form 17), tax exemptions (Form 18), bank guarantee checklist (Form 19), additional info (Form 20), Integrity Pact (Form 21).
- Include JV-only items (Form 7 Power of Attorney, Form 8 JDU, JV Agreement) as separate bullets when applicable.

CRITICAL — Contract Conditions (6.1):
- Extract completion time, defect liability, liquidated damages, AND quality penalties when stated.
- List EVERY distinct special requirement / SCC condition as a separate bullet — do not summarize multiple conditions into one.

Omit any field/row/group not present in the chunks."""
    },
]

_REQUIRED_SECTIONS = [
    "tender_overview",
    "scope_of_work",
    "eligibility_and_qualification",
    "financial_terms",
    "contract_and_bidding",
    "price_variation"
]
