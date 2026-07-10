"""Unit tests for scope_of_work adapter — no LLM/API required."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rag_pipeline.step5_extractor import _collect_scope_items, _extract_scope_of_work, _sections_to_legacy


def test_collect_scope_items_card():
    items = [{"type": "card", "title": "Civil Works", "description": "Foundation and structure"}]
    assert _collect_scope_items(items) == [{"category": "Civil Works", "details": "Foundation and structure"}]


def test_collect_scope_items_paragraph():
    items = [{"type": "paragraph", "title": "Supply", "description": "HT conductors and poles"}]
    assert _collect_scope_items(items) == [{"category": "Supply", "details": "HT conductors and poles"}]


def test_collect_scope_items_bullet():
    items = [{"type": "bullet", "title": "Erection", "bullets": ["Pole erection", "Conductor stringing"]}]
    result = _collect_scope_items(items)
    assert len(result) == 1
    assert result[0]["category"] == "Erection"
    assert "Pole erection" in result[0]["details"]


def test_collect_scope_items_table_row():
    items = [{"type": "table_row", "attributes": {"category": "BOQ Item 1", "details": "33 KV line"}}]
    assert _collect_scope_items(items) == [{"category": "BOQ Item 1", "details": "33 KV line"}]


def test_extract_scope_from_all_subsections():
    sections = [{
        "id": "2", "number": "2", "title": "Scope of Work",
        "subsections": [
            {
                "id": "2.1", "title": "BOQ Summary", "layout": "cards",
                "line_items": [{"type": "card", "title": "Supply", "description": "Materials"}],
            },
            {
                "id": "2.2", "title": "Technical Specifications", "layout": "list",
                "line_items": [{"type": "paragraph", "description": "As per IS standards"}],
            },
        ],
    }]
    scope = _extract_scope_of_work(sections)
    assert len(scope) == 2
    assert scope[0]["category"] == "Supply"
    assert scope[1]["category"] == "General"


def test_sections_to_legacy_includes_scope():
    sections = [{
        "id": "2", "number": "2", "title": "Scope of Work",
        "subsections": [{
            "id": "2.1", "title": "Scope of Work", "layout": "cards",
            "line_items": [{"type": "bullet", "bullets": ["HT line conversion", "LT networking"]}],
        }],
    }]
    tender = _sections_to_legacy(sections)
    assert "scope_of_work" in tender
    assert len(tender["scope_of_work"]) == 2
