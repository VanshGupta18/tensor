"""
Python AI Service for Tender Management Platform
-------------------------------------------------
Exposes two endpoints consumed by the SAP CAP backend:

  POST /process_file  — receives a PDF, splits it into 50-page chunks,
                        sends each chunk to AI, accumulates the results,
                        and returns the final structured JSON.

  POST /response      — receives a plain-text chat message and returns
                        an AI-generated reply as plain text.

All HTML-rendering routes have been removed.
This service is never called directly from React — all traffic goes
React → CAP (Node.js) → this service.
"""

import os
import json
from pathlib import Path

from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv

from functions import (
    get_access_token,
    split_pdf,
    generate_summary,
    parse_ai_json,
    generate_result,
    get_or_create_section,
    add_subheading,
    generate_chat_response,
    _has_text,
)

# ── Environment ────────────────────────────────────────────────────────────────
load_dotenv()

API_URL = str(os.getenv("MODEL_BASE_URL", "")) + str(os.getenv("MODEL_ENDPOINT", ""))

CREDENTIALS = {
    "TOKEN_URL":      os.getenv("TOKEN_URL"),
    "CLIENT_ID":      os.getenv("CLIENT_ID"),
    "CLIENT_SECRET":  os.getenv("CLIENT_SECRET"),
    "MODEL_BASE_URL": os.getenv("MODEL_BASE_URL"),
    "MODEL_ENDPOINT": os.getenv("MODEL_ENDPOINT"),
}

UPLOAD_DIR = Path(__file__).parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

# ── Token (fetched once at startup; refresh on 401) ────────────────────────────
def fetch_token():
    return get_access_token(CREDENTIALS)

token = fetch_token()

# ── Flask app ──────────────────────────────────────────────────────────────────
app = Flask(__name__)
# Allow CAP backend (localhost:4004) to call this service during development
CORS(app, resources={r"/*": {"origins": ["http://localhost:4004", "http://127.0.0.1:4004"]}})


# ── Health check ───────────────────────────────────────────────────────────────
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


# ── POST /process_file ─────────────────────────────────────────────────────────
# Called by CAP when the user uploads a PDF in the Chatbot.
#
# Flow (per TASK.txt):
#   1. Receive PDF from CAP
#   2. Save to uploads/
#   3. Split into 50-page chunks
#   4. Send each chunk to AI → accumulate JSON results
#   5. Run a second AI pass to produce the final structured document JSON
#   6. Return:
#        {
#          "confidenceScore": "high" | "medium" | "low",
#          "summary":         "<tender title>",
#          "keyTerms":        ["field1", "field2", ...],
#          "sections":        [ ...full document sections... ]
#        }
#
# CAP stores this JSON in HANA (AIResults.rawResponse) and links it
# to the tender so Screen 2 and Screen 3 can display the extracted data.
# ──────────────────────────────────────────────────────────────────────────────
@app.route("/process_file", methods=["POST"])
def process_file():
    global token

    if "invoice" not in request.files:
        return jsonify({"error": "No file uploaded. Expected field name: 'invoice'"}), 400

    file = request.files["invoice"]
    if not file.filename:
        return jsonify({"error": "Empty filename"}), 400

    # 1 + 2. Save uploaded PDF
    file_path = UPLOAD_DIR / file.filename
    file.save(str(file_path))

    # 3. Split — 50 pages for text PDFs, 20 for image PDFs (vision API page limit)
    pages_per_chunk = 20 if not _has_text(str(file_path)) else 50
    file_path_list = split_pdf(str(file_path), pages_per_chunk)

    # 4. Send each chunk to AI and accumulate structured extraction
    try:
        summary_json_str = generate_summary(token, API_URL, file_path_list)
    except Exception as e:
        if "401" in str(e) or "Unauthorized" in str(e):
            token = fetch_token()
            summary_json_str = generate_summary(token, API_URL, file_path_list)
        else:
            raise

    summary_dict = parse_ai_json(summary_json_str)

    # Extract long-form text fields before the second AI pass
    # (these are injected back after to preserve full content)
    long_fields = {
        ("scope_of_work",           "components"):         summary_dict.get("scope_of_work", {}).get("components", ""),
        ("eligibility_criteria",    "technical"):          summary_dict.get("eligibility_criteria", {}).get("technical", ""),
        ("eligibility_criteria",    "financial"):          summary_dict.get("eligibility_criteria", {}).get("financial", ""),
        ("eligibility_criteria",    "other_conditions"):   summary_dict.get("eligibility_criteria", {}).get("other_conditions", ""),
        ("price_variation",         "materials"):          summary_dict.get("price_variation", {}).get("materials", ""),
        ("contract_conditions",     "other_conditions"):   summary_dict.get("contract_conditions", {}).get("other_conditions", ""),
        ("technical_bid_documents", "required_documents"): summary_dict.get("technical_bid_documents", {}).get("required_documents", ""),
        ("technical_bid_documents", "declarations"):       summary_dict.get("technical_bid_documents", {}).get("declarations", ""),
        ("technical_bid_documents", "other_requirements"): summary_dict.get("technical_bid_documents", {}).get("other_requirements", ""),
    }

    # Clear them so the second prompt stays compact
    for (section, field) in long_fields:
        if section in summary_dict and field in summary_dict[section]:
            summary_dict[section][field] = ""

    compact_summary = json.dumps(summary_dict, indent=2, ensure_ascii=False)

    # 5. Second AI pass: transform flat JSON → hierarchical document structure
    try:
        result_raw = generate_result(token, API_URL, compact_summary)
    except Exception as e:
        if "401" in str(e) or "Unauthorized" in str(e):
            token = fetch_token()
            result_raw = generate_result(token, API_URL, compact_summary)
        else:
            raise

    result_dict = parse_ai_json(result_raw)

    # result_dict should now be { "tenders": [...] }
    # Fall back gracefully if the AI returned the old single-document format
    if "tenders" not in result_dict:
        # Wrap old-format single document into the new array shape
        result_dict = {"tenders": [result_dict]}

    raw_tenders = result_dict.get("tenders", [])

    # Handle empty tenders (no tender info found in PDF)
    if not raw_tenders:
        return jsonify({"tenders": [], "message": "No tender information found in the document"})

    # Inject long-form fields back into each tender's sections
    output_tenders = []
    for tender_doc in raw_tenders:
        for (section_name, heading), content in long_fields.items():
            tender_doc, section = get_or_create_section(tender_doc, section_name)
            tender_doc = add_subheading(tender_doc, section, heading, content)

        sections = tender_doc.get("sections", [])
        summary_text = tender_doc.get("document_title", "")
        key_terms = []

        tender_info_section = next(
            (s for s in sections if s.get("heading") == "tender_information"), None
        )
        if tender_info_section:
            sub_headings = tender_info_section.get("sub_headings", [])
            if not summary_text:
                title_sh = next((h for h in sub_headings if h.get("heading") == "tender_title"), None)
                summary_text = title_sh.get("content", "") if title_sh else ""
            key_terms = [h.get("heading") for h in sub_headings if h.get("heading")]

        output_tenders.append({
            "confidenceScore": "high",
            "summary":         summary_text or "Tender document processed",
            "keyTerms":        key_terms,
            "sections":        sections,
        })

    return jsonify({"tenders": output_tenders})


# ── POST /response ─────────────────────────────────────────────────────────────
# Called by CAP when the user types a plain-text message in the Chatbot.
#
# Flow (per TASK.txt):
#   1. Receive { message, tenderId, user }
#   2. Send to AI with a tender-management context prompt
#   3. Return { reply: "<AI response text>" }
#
# Conversation history is persisted in HANA by CAP (ChatHistories entity).
# This endpoint is stateless — each call is a standalone AI request.
# ──────────────────────────────────────────────────────────────────────────────
@app.route("/response", methods=["POST"])
def response():
    global token

    data      = request.get_json(force=True) or {}
    message   = (data.get("message")  or "").strip()
    tender_id = (data.get("tenderId") or "").strip()

    if not message:
        return jsonify({"error": "No message provided"}), 400

    try:
        reply = generate_chat_response(token, API_URL, message, tender_id)
    except Exception as e:
        if "401" in str(e) or "Unauthorized" in str(e):
            token = fetch_token()
            reply = generate_chat_response(token, API_URL, message, tender_id)
        else:
            reply = f"AI service error: {str(e)}"

    return jsonify({"reply": reply})


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"[AI Service] Starting on port {port}")
    print(f"[AI Service] Endpoints: POST /process_file  |  POST /response  |  GET /health")
    app.run(host="0.0.0.0", port=port, debug=False)
