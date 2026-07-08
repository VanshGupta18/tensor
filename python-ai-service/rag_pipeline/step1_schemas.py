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
        # Dates live on their own page/table and get out-competed by the keywords
        # above when merged into one retrieval query — a second, dates-only query
        # (still one LLM call) keeps the 6-call/token budget while giving key_dates
        # its own non-diluted retrieval pass.
        "extra_keyword_sets": [
            ["key dates", "important dates", "schedule of bidding", "pre-bid meeting", "bid submission deadline", "technical bid opening", "financial bid opening", "date of publication", "work order issuance"],
        ],
        "max_pages": 12,
        "prompt": """Extract ALL basic tender details AND ALL key dates AND ALL contact persons, using the generic Section/SubSection/LineItem format. Emit exactly ONE section:

sections: [{
  "id": "1", "number": "1", "title": "Basic Tender Particulars", "order": 1,
  "subsections": [
    {
      "id": "1.1", "title": "Tender Information", "layout": "table",
      "line_items": [
        {"type": "field", "label": "Title", "value": "<tender title>"},
        {"type": "field", "label": "Reference No", "value": "<tender/NIT number>"},
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
        {"type": "card", "title": "<contact name>", "subtitle": "<role/designation>", "description": "<email>"}
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

Omit any line item, subsection, or the whole 1.2/1.3 subsection entirely if that data genuinely is not present in the chunks — never invent placeholder values. Key dates are just as important as the basic details — do not omit them even if only briefly mentioned."""
    },
    {
        "name": "scope_of_work",
        "keywords": ["scope of work", "bill of quantities", "boq", "technical specifications", "drawings", "site clearance", "civil works"],
        "max_pages": 10,
        "prompt": """Extract the complete scope of work categories, BOQ summary, and construction details, using the generic Section/SubSection/LineItem format. Emit exactly ONE section:

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
        "prompt": """Extract ALL technical and financial eligibility, contractor class requirements, and qualification criteria, using the generic Section/SubSection/LineItem format. Emit exactly ONE section:

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
        "prompt": """Extract ALL EMD, performance security, bank details, retention money, bid validity, AND ALL advance/progressive payment milestones and the payment timeline, using the generic Section/SubSection/LineItem format. Emit exactly ONE section:

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
        "max_pages": 10,
        "prompt": """Extract ALL price variation and escalation details, formulas, and material indices for construction materials (cement, steel, bitumen, labour) and electrical equipment (IEEMA), using the generic Section/SubSection/LineItem format. Emit exactly ONE section:

sections: [{
  "id": "5", "number": "5", "title": "Price Variation", "order": 5,
  "subsections": [{
    "id": "5.1", "title": "Price Variation", "layout": "mixed",
    "line_items": [
      {"type": "field", "label": "Is Applicable", "value": "Yes|No"},
      {"type": "bullet", "title": "Firm Components", "bullets": ["<component>", "..."]},
      {"type": "bullet", "title": "Variable Components", "bullets": ["<component>", "..."]},
      {"type": "formula", "title": "Composite Formula", "formula": "<overall escalation formula, if stated>"},
      {"type": "formula", "title": "<material name, e.g. Cement>", "formula": "<material-specific formula>", "attributes": {"index_source": "<e.g. WPI, IEEMA circular>"}}
    ]
  }]
}]

One "formula" item per material/equipment index. Omit any item not present in the chunks."""
    },
    {
        "name": "contract_and_bidding",
        "keywords": ["defect liability", "liquidated damages", "completion time", "time for completion", "special conditions", "quality penalties"],
        # Same dilution risk: the technical-bid-document checklist is a distinct list
        # elsewhere in the document, so it gets its own retrieval query too.
        "extra_keyword_sets": [
            ["documents comprising the bid", "technical bid", "forms to be submitted", "envelope 1", "checklist of documents"],
        ],
        "max_pages": 12,
        "prompt": """Extract ALL contract conditions (completion time, defect liability, liquidated damages, quality penalties, special requirements) AND the exhaustive list of forms/documents required in the technical bid (Envelope 1), using the generic Section/SubSection/LineItem format. Emit exactly ONE section:

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

Include the "rule" item in 6.2 ONLY if the document explicitly warns against price disclosure in the technical bid. Omit any field/row/group not present in the chunks."""
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
