"""Unit tests for generic synopsis preparation (step6_synopsis)."""

from rag_pipeline.step6_synopsis import prepare_synopsis


def test_prepare_synopsis_truncates_scope():
    long_detail = "word " * 80
    raw = {
        "tender_overview": {"title": "Test Tender"},
        "scope_of_work": [{"category": "Civil", "details": long_detail}],
    }
    out = prepare_synopsis(raw)
    assert len(out["scope_of_work"][0]["details"]) <= 225
    assert raw["scope_of_work"][0]["details"] == long_detail  # input unchanged


def test_prepare_synopsis_merges_duplicate_categories():
    raw = {
        "tender_overview": {},
        "scope_of_work": [
            {"category": "HT Lines", "details": "New 33 kV lines"},
            {"category": "ht lines", "details": "Stringing work"},
        ],
    }
    out = prepare_synopsis(raw)
    assert len(out["scope_of_work"]) == 1
    assert "33 kV" in out["scope_of_work"][0]["details"]


def test_prepare_synopsis_enriches_eligibility_percentages():
    raw = {
        "tender_overview": {
            "estimated_cost": {"amount": 1000, "currency": "INR", "denomination": "Lakhs"},
        },
        "eligibility_and_qualification": {
            "technical": {
                "options": [{"option": "A", "requirement": "1 contract >= 70% of tender cost"}],
            },
            "financial": [{"criterion": "MAAT", "requirement": ">= 30% of estimated tender cost"}],
        },
    }
    out = prepare_synopsis(raw)
    assert "~Rs." in out["eligibility_and_qualification"]["technical"]["options"][0]["requirement"]
    assert "~Rs." in out["eligibility_and_qualification"]["financial"][0]["requirement"]


def test_prepare_synopsis_filters_boilerplate_special_requirements():
    raw = {
        "contract_and_bidding": {
            "special_requirements": [
                "Installation strictly per approved drawings with Site Engineer approval",
                "GIS asset tagging mandatory before final payment",
                "Contractor liable for damage to other equipment during repair work",
                "Valid electrical works licence required within 2 months of award",
            ],
        },
    }
    out = prepare_synopsis(raw)
    kept = out["contract_and_bidding"]["special_requirements"]
    assert any("GIS" in s for s in kept)
    assert not any("Installation strictly" in s for s in kept)


def test_prepare_synopsis_groups_long_technical_checklist():
    docs = [f"Form {i} - Document {i}" for i in range(1, 22)]
    raw = {
        "contract_and_bidding": {
            "technical_bid_documents": {"grouped_documents": docs},
        },
    }
    out = prepare_synopsis(raw)
    tbd = out["contract_and_bidding"]["technical_bid_documents"]
    assert len(tbd["grouped_documents_synopsis"]) < len(docs)
    assert tbd["grouped_documents_full"] == docs


def test_prepare_synopsis_sets_date_of_issue_from_publication():
    raw = {
        "tender_overview": {
            "key_dates": {"publication": "2026-05-19"},
        },
    }
    out = prepare_synopsis(raw)
    assert out["tender_overview"]["date_of_issue"] == "2026-05-19"
    assert out["_synopsis_meta"]["disclaimer"]


def test_prepare_synopsis_generates_pdf_bytes():
    from rag_pipeline.step7_pdf_generator import generate_tender_pdf

    tender = prepare_synopsis({
        "tender_overview": {
            "title": "Sample Works",
            "reference_no": "REF/2026/01",
            "estimated_cost": {"amount": 100, "currency": "INR", "denomination": "Lakhs"},
            "key_dates": {"publication": "2026-01-01"},
        },
        "financial_terms": {
            "advance_payments": [{"component": "Supply", "percentage": 15, "conditions": ["BG required"]}],
            "progressive_payments": [{"component": "Supply", "milestone": "Delivery", "percentage": 60}],
        },
        "price_variation": {
            "materials": [{"item": "Steel", "formula": "P = Po + x", "remark": "WPI"}],
            "key_rules": ["Not applicable on advance component"],
        },
    })
    pdf = generate_tender_pdf(tender)
    assert pdf[:4] == b"%PDF"
