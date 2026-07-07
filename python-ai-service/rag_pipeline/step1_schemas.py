_TENDER_TOOL_SCHEMA = {
    "name": "structure_tender_data",
    "description": "Structure all extracted tender facts into the canonical JSON format.",
    "cache_control": {"type": "ephemeral"},
    "input_schema": {
        "type": "object",
        "properties": {
            "tenders": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "tender_overview": {
                            "type": "object",
                            "properties": {
                                "title":             {"type": "string"},
                                "reference_no":      {"type": "string"},
                                "version":           {"type": "string"},
                                "issuing_authority": {"type": "string"},
                                "contract_type":     {"type": "string"},
                                "bid_system":        {"type": "string"},
                                "funding_agency":    {"type": "string"},
                                "estimated_cost": {
                                    "type": "object",
                                    "properties": {
                                        "amount":       {"type": "number"},
                                        "currency":     {"type": "string"},
                                        "denomination": {"type": "string"}
                                    }
                                },
                                "tender_fee": {
                                    "type": "object",
                                    "properties": {
                                        "amount":   {"type": "number"},
                                        "currency": {"type": "string"}
                                    }
                                },
                                "budget_category": {"type": "string"},
                                "contacts": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "name":  {"type": "string"},
                                            "role":  {"type": "string"},
                                            "email": {"type": "string"}
                                        }
                                    }
                                },
                                "key_dates": {
                                    "type": "object",
                                    "properties": {
                                        "publication": {"type": "string"},
                                        "pre_bid_meeting": {
                                            "type": "object",
                                            "properties": {"date": {"type": "string"}, "time": {"type": "string"}, "timezone": {"type": "string"}}
                                        },
                                        "bid_submission_deadline": {
                                            "type": "object",
                                            "properties": {"date": {"type": "string"}, "time": {"type": "string"}, "timezone": {"type": "string"}}
                                        },
                                        "technical_opening": {
                                            "type": "object",
                                            "properties": {"date": {"type": "string"}, "time": {"type": "string"}, "timezone": {"type": "string"}}
                                        },
                                        "financial_opening": {
                                            "type": "object",
                                            "properties": {"date": {"type": "string"}, "time": {"type": "string"}, "timezone": {"type": "string"}}
                                        },
                                        "work_order_issuance": {"type": "string"}
                                    }
                                }
                            }
                        },
                        "scope_of_work": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "category": {"type": "string"},
                                    "details":  {"type": "string"}
                                }
                            }
                        },
                        "eligibility_and_qualification": {
                            "type": "object",
                            "properties": {
                                "contractor_class_required": {"type": "string"},
                                "bidding_capacity":          {"type": "number"},
                                "technical": {
                                    "type": "object",
                                    "properties": {
                                        "heading_note":            {"type": "string"},
                                        "options": {
                                            "type": "array",
                                            "items": {
                                                "type": "object",
                                                "properties": {
                                                    "option":      {"type": "string"},
                                                    "requirement": {"type": "string"}
                                                }
                                            }
                                        },
                                        "similar_works_definition": {"type": "string"}
                                    }
                                },
                                "financial": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "criterion":   {"type": "string"},
                                            "requirement": {"type": "string"}
                                        }
                                    }
                                }
                            }
                        },
                        "financial_terms": {
                            "type": "object",
                            "properties": {
                                "emd": {
                                    "type": "object",
                                    "properties": {
                                        "percentage":  {"type": "number"},
                                        "max_cap_inr": {"type": "number"},
                                        "form":        {"type": "string"}
                                    }
                                },
                                "bank_details": {
                                    "type": "object",
                                    "properties": {
                                        "bank":    {"type": "string"},
                                        "account": {"type": "string"},
                                        "ifsc":    {"type": "string"}
                                    }
                                },
                                "bid_validity_days": {"type": "number"},
                                "performance_guarantees": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "type":       {"type": "string"},
                                            "percentage": {"type": "number"}
                                        }
                                    }
                                },
                                "retention_money_percent": {"type": "number"},
                                "advance_payments": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "component":  {"type": "string"},
                                            "percentage": {"type": "number"},
                                            "conditions": {"type": "array", "items": {"type": "string"}}
                                        }
                                    }
                                },
                                "progressive_payments": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "component":  {"type": "string"},
                                            "milestone":  {"type": "string"},
                                            "percentage": {"type": "number"}
                                        }
                                    }
                                },
                                "standard_timeline_days":  {"type": "number"},
                                "delayed_interest_rate":   {"type": "string"}
                            }
                        },
                        "price_variation": {
                            "type": "object",
                            "properties": {
                                "is_applicable":          {"type": "boolean"},
                                "firm_components":        {"type": "array", "items": {"type": "string"}},
                                "variable_components":    {"type": "array", "items": {"type": "string"}},
                                "composite_formula":      {"type": "string"},
                                "materials": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "name":         {"type": "string"},
                                            "formula":      {"type": "string"},
                                            "index_source": {"type": "string"}
                                        }
                                    }
                                }
                            }
                        },
                        "contract_and_bidding": {
                            "type": "object",
                            "properties": {
                                "completion_time_months":        {"type": "number"},
                                "defect_liability_period_months": {"type": "number"},
                                "liquidated_damages": {
                                    "type": "object",
                                    "properties": {
                                        "rate_per_week_percent": {"type": "number"},
                                        "cap_percent":           {"type": "number"}
                                    }
                                },
                                "quality_penalties": {
                                    "type": "object",
                                    "properties": {
                                        "major_defect_percent": {"type": "number"},
                                        "minor_defect_percent": {"type": "number"}
                                    }
                                },
                                "special_requirements": {"type": "array", "items": {"type": "string"}},
                                "technical_bid_documents": {
                                    "type": "object",
                                    "properties": {
                                        "grouped_documents":            {"type": "array", "items": {"type": "string"}},
                                        "has_price_disclosure_warning": {"type": "boolean"}
                                    }
                                }
                            }
                        }
                    }
                }
            }
        },
        "required": ["tenders"]
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
        "prompt": "Extract ALL basic tender details (tender_no, title, version, issuing_authority, contract_type, bid_system, funding_agency, estimated_cost, tender_fee, budget_category, contacts) AND ALL key dates (publication, pre-bid meeting, bid submission deadline, technical opening, financial opening, work order issuance — with date/time/timezone wherever stated). Key dates are just as important as the basic details — do not omit them even if only briefly mentioned. Populate ONLY the tender_overview field, including its nested key_dates."
    },
    {
        "name": "scope_of_work",
        "keywords": ["scope of work", "bill of quantities", "boq", "technical specifications", "drawings", "site clearance", "civil works"],
        "max_pages": 10,
        "prompt": "Extract the complete scope of work categories, BOQ summary, and construction details. Populate ONLY the scope_of_work field."
    },
    {
        "name": "eligibility_and_qualification",
        "keywords": ["turnover", "liquid assets", "similar work", "bid capacity", "net worth", "experience", "class of contractor", "registration"],
        "max_pages": 10,
        "prompt": "Extract ALL technical and financial eligibility, contractor class requirements, and qualification criteria. Populate ONLY the eligibility_and_qualification field."
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
        "prompt": "Extract ALL EMD, performance security, performance guarantees (like CPG Supply/Erection), retention money, bid validity, bank details, AND ALL advance payments, RA bill/progressive payment milestones, the standard payment timeline, and the delayed interest rate on late payments. Populate ONLY the financial_terms field."
    },
    {
        "name": "price_variation",
        "keywords": ["price variation", "price adjustment", "escalation", "star rate", "cement", "steel", "bitumen", "wpir", "labour", "ieema"],
        "max_pages": 10,
        "prompt": "Extract ALL price variation and escalation details, formulas, and material indices specifically for construction materials (cement, steel, bitumen, labour) and electrical equipment (IEEMA). Populate ONLY the price_variation field."
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
        "prompt": "Extract ALL contract conditions (completion time, defect liability, liquidated damages, quality penalties, special requirements) AND the exhaustive list of forms/documents required in the technical bid (Envelope 1), noting any warning against disclosing prices. Populate ONLY the contract_and_bidding field, including its nested technical_bid_documents."
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
