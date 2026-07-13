"""Tests for contact sanitization and price-variation table adapter."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rag_pipeline.step4_validators import _sanitize_contacts, _parse_contact_channels
from rag_pipeline.step5_extractor import _sections_to_legacy


def test_parse_contact_channels_email_and_phone():
    email, phone = _parse_contact_channels("9000000000, contact.office@example.com")
    assert email == "contact.office@example.com"
    assert phone is not None
    assert "9000000000" in phone.replace(" ", "")


def test_parse_contact_channels_rejects_address():
    addr = "Plot no. 1, 5th floor, Example Tower, Example Road, Example City - 400001"
    email, phone = _parse_contact_channels(addr)
    assert email is None
    assert phone is None


def test_sanitize_contacts_drops_address_hallucination():
    result = {
        "tenders": [{
            "tender_overview": {
                "contacts": [
                    {"name": "A B Sharma", "role": "Executive Engineer (Distribution)", "email": "9000000000, contact.office@example.com"},
                    {"name": "Chief Engineer (Special Projects)", "role": "Example Utility Co.", "email": "Plot no. 1, 5th floor, Example Tower, Example City - 400001"},
                ]
            }
        }]
    }
    out = _sanitize_contacts(result)
    contacts = out["tenders"][0]["tender_overview"]["contacts"]
    assert len(contacts) == 1
    assert contacts[0]["name"] == "A B Sharma"
    assert contacts[0]["email"] == "contact.office@example.com"
    assert "9000000000" in contacts[0]["phone"].replace(" ", "")


def test_price_variation_table_rows_adapter():
    sections = [{
        "id": "5", "number": "5", "title": "Price Variation",
        "subsections": [{
            "id": "5.1", "title": "Price Variation", "layout": "table",
            "line_items": [
                {"type": "field", "label": "Is Applicable", "value": "Yes"},
                {"type": "table_row", "attributes": {
                    "item": "ACSR Conductor",
                    "formula": "P = Po + WA (AL - ALo)",
                    "remark": "IEEMA circular IEEMA/PVC/CONDUCTOR/2012",
                }},
            ],
        }],
    }]
    tender = _sections_to_legacy(sections)
    pv = tender["price_variation"]
    assert pv["is_applicable"] is True
    assert len(pv["materials"]) == 1
    assert pv["materials"][0]["item"] == "ACSR Conductor"
    assert "Po" in pv["materials"][0]["formula"]
    assert "IEEMA" in pv["materials"][0]["remark"]
    assert "variable_components" not in pv
    assert "firm_components" not in pv
