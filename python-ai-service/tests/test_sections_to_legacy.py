"""Unit tests for scope-of-work adapter fallbacks in step5_extractor."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rag_pipeline.step5_extractor import (
    _collect_scope_items,
    _extract_scope_of_work,
    _sections_to_legacy,
    _extract_reference_no_from_text,
    _backfill_reference_no,
)


def test_collect_scope_cards():
    items = [
        {"type": "card", "title": "Civil Works", "description": "Foundation and structures"},
    ]
    assert _collect_scope_items(items) == [
        {"category": "Civil Works", "details": "Foundation and structures"},
    ]


def test_collect_scope_paragraph_and_field():
    items = [
        {"type": "paragraph", "title": "Survey", "description": "Field survey work"},
        {"type": "field", "label": "Testing", "value": "Commissioning tests"},
    ]
    assert _collect_scope_items(items) == [
        {"category": "Survey", "details": "Field survey work"},
        {"category": "Testing", "details": "Commissioning tests"},
    ]


def test_collect_scope_bullets():
    items = [
        {"type": "bullet", "title": "Materials", "bullets": ["Cement", "Steel"]},
    ]
    assert _collect_scope_items(items) == [
        {"category": "Materials", "details": "• Cement\n• Steel"},
    ]


def test_collect_scope_table_row():
    items = [
        {
            "type": "table_row",
            "attributes": {"category": "BOQ Item", "details": "Pole erection"},
        },
    ]
    assert _collect_scope_items(items) == [
        {"category": "BOQ Item", "details": "Pole erection"},
    ]


def test_extract_scope_section2_cards():
    sections = [{
        "id": "2", "number": "2", "title": "Scope of Work",
        "subsections": [{
            "id": "2.1", "title": "Scope of Work", "layout": "cards",
            "line_items": [
                {"type": "card", "title": "Supply", "description": "Materials supply"},
            ],
        }],
    }]
    assert _extract_scope_of_work(sections) == [
        {"category": "Supply", "details": "Materials supply"},
    ]


def test_extract_scope_boq_subsection_title():
    sections = [{
        "id": "2", "number": "2", "title": "Scope of Work",
        "subsections": [{
            "id": "2.1", "title": "Bill of Quantities", "layout": "cards",
            "line_items": [
                {"type": "card", "title": "Lines", "description": "33 kV lines"},
            ],
        }],
    }]
    assert _extract_scope_of_work(sections) == [
        {"category": "Lines", "details": "33 kV lines"},
    ]


def test_extract_scope_title_fallback_when_id_wrong():
    sections = [{
        "id": "99", "number": "99", "title": "Scope of Work",
        "subsections": [{
            "id": "99.1", "title": "Work Categories", "layout": "cards",
            "line_items": [
                {"type": "paragraph", "description": "General civil scope"},
            ],
        }],
    }]
    assert _extract_scope_of_work(sections) == [
        {"category": "General", "details": "General civil scope"},
    ]


def test_sections_to_legacy_includes_scope():
    sections = [{
        "id": "2", "number": "2", "title": "Scope of Work",
        "subsections": [{
            "id": "2.1", "title": "Scope of Work", "layout": "cards",
            "line_items": [
                {"type": "card", "title": "Erection", "description": "Installation work"},
            ],
        }],
    }]
    tender = _sections_to_legacy(sections)
    assert tender["scope_of_work"] == [
        {"category": "Erection", "details": "Installation work"},
    ]


def test_collect_scope_group():
    items = [
        {
            "type": "group",
            "title": "Civil Works",
            "children": [
                {"type": "field", "label": "Foundation", "value": "RCC foundation"},
            ],
        },
    ]
    assert _collect_scope_items(items) == [
        {"category": "Civil Works", "details": "Foundation: RCC foundation"},
    ]


def test_collect_scope_card_description_only():
    items = [{"type": "card", "description": "Supply and erection of poles"}]
    assert _collect_scope_items(items) == [
        {"category": "Scope Item", "details": "Supply and erection of poles"},
    ]


def test_extract_scope_subsection_summary_only():
    sections = [{
        "id": "2", "title": "Scope of Work",
        "subsections": [{
            "id": "2.1", "title": "Scope of Work", "summary": "Turnkey distribution works",
            "line_items": [],
        }],
    }]
    assert _extract_scope_of_work(sections) == [
        {"category": "Scope of Work", "details": "Turnkey distribution works"},
    ]


def test_extract_scope_boq_section_title():
    sections = [{
        "id": "7", "title": "Bill of Quantities",
        "subsections": [{
            "id": "7.1", "title": "Items",
            "line_items": [{"type": "card", "title": "Poles", "description": "Erection"}],
        }],
    }]
    assert _extract_scope_of_work(sections) == [
        {"category": "Poles", "details": "Erection"},
    ]
    assert _extract_scope_of_work([]) == []
    assert _extract_scope_of_work([{"id": "3", "title": "Eligibility", "subsections": []}]) == []


def test_extract_reference_no_prefers_full_number_over_numeric_id():
    text = (
        "Tender ID: 307381\n"
        "Tender Number\n"
        "MGVCL/TECH/ROBUST-III/MBAD/2026-27\n"
        "Deadline for Submission"
    )
    assert _extract_reference_no_from_text(text) == "MGVCL/TECH/ROBUST-III/MBAD/2026-27"


def test_sections_to_legacy_nit_rfb_label_alias():
    sections = [{
        "id": "1", "number": "1", "title": "Basic Tender Particulars",
        "subsections": [{
            "id": "1.1", "title": "Tender Information", "layout": "table",
            "line_items": [
                {"type": "field", "label": "NIT/RFB No", "value": "MGVCL/TECH/ROBUST-III/MBAD/2026-27"},
            ],
        }],
    }]
    tender = _sections_to_legacy(sections)
    assert tender["tender_overview"]["reference_no"] == "MGVCL/TECH/ROBUST-III/MBAD/2026-27"


def test_sections_to_legacy_tender_no_label_alias():
    sections = [{
        "id": "1", "number": "1", "title": "Basic Tender Particulars",
        "subsections": [{
            "id": "1.1", "title": "Tender Information", "layout": "table",
            "line_items": [
                {"type": "field", "label": "Tender No", "value": "CE-SPD/ADB/2026-27/T-13 (Nagpur Zone)"},
            ],
        }],
    }]
    tender = _sections_to_legacy(sections)
    assert tender["tender_overview"]["reference_no"] == "CE-SPD/ADB/2026-27/T-13 (Nagpur Zone)"


def test_extract_reference_no_from_labeled_text():
    text = "NOTICE INVITING TENDER\nTender No. : CE-SPD/ADB/2026-27/ T-13 (Nagpur Zone)\nEstimated Cost"
    assert _extract_reference_no_from_text(text) == "CE-SPD/ADB/2026-27/ T-13 (Nagpur Zone)"


def test_backfill_reference_no_from_nodes():
    from unittest.mock import patch

    class _Node:
        def __init__(self, page, text):
            self.metadata = {"page": page}
            self._text = text

        def get_content(self):
            return self._text

    fake_nodes = [
        _Node(1, "NOTICE INVITING TENDER"),
        _Node(2, "Reference No: ABC/XYZ/2026/T-99 (Zone A)"),
    ]

    with patch("rag_pipeline.step5_extractor.get_document_nodes", return_value=fake_nodes):
        tender = _backfill_reference_no({"tender_overview": {"title": "Test"}}, "fakehash")
    assert tender["tender_overview"]["reference_no"] == "ABC/XYZ/2026/T-99 (Zone A)"
