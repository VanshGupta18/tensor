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
import uuid
import shutil
import threading
import time
from io import BytesIO
from pathlib import Path

from flask import Flask, request, jsonify, send_file, Response
from flask_cors import CORS
from dotenv import load_dotenv

from functions import (
    get_access_token,
    split_pdf,
    extract_facts_from_chunks,
    merge_chunk_facts,
    synthesize_final_json,
    synonym_based_validation,
    generate_chat_response,
    generate_chat_response_stream,
    _has_text,
    _upload_semaphore,
)
from pdf_generator import generate_tender_pdf

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

# ── Token — proactive refresh with a lock ─────────────────────────────────────
# SAP AI Core tokens typically expire after 60 min. We treat them as valid for
# 55 min and refresh proactively 60 s before expiry so no request ever hits a
# stale token. A lock ensures only one thread refreshes at a time.
_token_lock      = threading.Lock()
_token_value: str = ""
_token_expires_at: float = 0.0

def get_token() -> str:
    global _token_value, _token_expires_at
    with _token_lock:
        if time.time() >= (_token_expires_at - 60):
            _token_value      = get_access_token(CREDENTIALS)
            _token_expires_at = time.time() + 55 * 60
        return _token_value

# Fetch on startup
get_token()

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
    if "invoice" not in request.files:
        return jsonify({"error": "No file uploaded. Expected field name: 'invoice'"}), 400

    file = request.files["invoice"]
    if not file.filename:
        return jsonify({"error": "Empty filename"}), 400

    # Guard against oversized uploads before touching the filesystem
    MAX_UPLOAD_MB = 100
    file.seek(0, 2)
    upload_size = file.tell()
    file.seek(0)
    if upload_size > MAX_UPLOAD_MB * 1024 * 1024:
        return jsonify({"error": f"File too large. Maximum {MAX_UPLOAD_MB} MB allowed."}), 400

    # 1 + 2. Save uploaded PDF with a unique prefix to prevent filename collisions
    # between concurrent uploads of identically-named files.
    safe_filename = f"{uuid.uuid4().hex[:8]}_{file.filename}"
    file_path = UPLOAD_DIR / safe_filename
    file.save(str(file_path))
    split_dir = file_path.parent / (file_path.stem + "_split")

    # 3. Split — 50 pages for text PDFs, 20 for image PDFs (vision API page limit)
    # overlap=5 means consecutive chunks share 5 pages, preventing boundary losses
    is_text_pdf     = _has_text(str(file_path))
    pages_per_chunk = 30 if is_text_pdf else 15
    chunk_overlap   = 2  if is_text_pdf else 0
    file_path_list  = split_pdf(str(file_path), pages_per_chunk, overlap=chunk_overlap)

    if not _upload_semaphore.acquire(timeout=10):
        return jsonify({"error": "Server busy — too many uploads in progress. Please try again shortly."}), 503

    try:
        # Pass get_token as a callable so each chunk call fetches a fresh token,
        # preventing 401 errors when extraction runs longer than the token lifetime.
        chunk_texts  = extract_facts_from_chunks(get_token, API_URL, file_path_list)
        merged_facts = merge_chunk_facts(chunk_texts)
        final_json   = synthesize_final_json(get_token(), API_URL, merged_facts)
        final_json   = synonym_based_validation(final_json, merged_facts)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        _upload_semaphore.release()
        # Clean up the original upload and all split chunks regardless of outcome
        try:
            file_path.unlink(missing_ok=True)
        except Exception:
            pass
        if split_dir.exists():
            shutil.rmtree(str(split_dir), ignore_errors=True)

    raw_tenders = final_json.get("tenders", [])

    # Handle empty tenders (no tender info found in PDF)
    if not raw_tenders:
        return jsonify({"tenders": [], "message": "No tender information found in the document"})

    output_tenders = []
    for tender_doc in raw_tenders:
        title = tender_doc.get("tender_information", {}).get("title", "")
        output_tenders.append({
            "confidenceScore": "high",
            "summary":         title or "Tender document processed",
            "keyTerms":        ["tender_information", "key_dates", "scope_of_work", "eligibility_and_qualification", "security_and_financials", "payment_terms", "price_variation", "contract_conditions", "technical_bid_documents"],
            **tender_doc
        })

    return jsonify({"tenders": output_tenders})


# ── POST /generate_pdf ─────────────────────────────────────────────────────────
# Called by CAP when the user clicks "Download" on a tender.
# Receives the tender's structured JSON sections and returns a formatted PDF.
# ──────────────────────────────────────────────────────────────────────────────
@app.route("/generate_pdf", methods=["POST"])
def generate_pdf():
    data = request.get_json(force=True) or {}
    tender = data.get("tender", {})
    title  = data.get("title", tender.get("tender_information", {}).get("title", "Tender Synopsis"))

    if not tender:
        return jsonify({"error": "No tender data provided"}), 400

    try:
        pdf_bytes = generate_tender_pdf(tender, doc_title=title)
    except Exception as e:
        return jsonify({"error": f"PDF generation failed: {str(e)}"}), 500

    buf = BytesIO(pdf_bytes)
    buf.seek(0)
    return send_file(
        buf,
        mimetype="application/pdf",
        as_attachment=True,
        download_name="tender_synopsis.pdf",
    )


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
    data      = request.get_json(force=True) or {}
    message   = (data.get("message")  or "").strip()
    tender_id = (data.get("tenderId") or "").strip()

    if not message:
        return jsonify({"error": "No message provided"}), 400
    if len(message) > 10_000:
        return jsonify({"error": "Message too long. Maximum 10,000 characters."}), 400

    try:
        reply = generate_chat_response(get_token(), API_URL, message, tender_id)
    except Exception as e:
        reply = f"AI service error: {str(e)}"

    return jsonify({"reply": reply})


# ── POST /stream-response ──────────────────────────────────────────────────────
# Streaming variant of /response — emits SSE chunks as the model generates them.
# Each chunk: `data: {"text": "..."}\n\n`   Final event: `data: [DONE]\n\n`
# ──────────────────────────────────────────────────────────────────────────────
@app.route("/stream-response", methods=["POST"])
def stream_response():
    data      = request.get_json(force=True) or {}
    message   = (data.get("message")  or "").strip()
    tender_id = (data.get("tenderId") or "").strip()

    if not message:
        return jsonify({"error": "No message provided"}), 400
    if len(message) > 10_000:
        return jsonify({"error": "Message too long. Maximum 10,000 characters."}), 400

    try:
        token = get_token()
    except Exception as e:
        return jsonify({"error": f"Auth token error: {e}"}), 503

    def generate():
        try:
            for chunk in generate_chat_response_stream(token, API_URL, message, tender_id):
                yield f"data: {json.dumps({'text': chunk})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        yield "data: [DONE]\n\n"

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"[AI Service] Starting on port {port}")
    print(f"[AI Service] Endpoints: POST /process_file  |  POST /response  |  GET /health")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
