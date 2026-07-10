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
import hashlib
import threading
import time
from collections import OrderedDict
from io import BytesIO
from pathlib import Path

from flask import Flask, request, jsonify, send_file, Response
from flask_cors import CORS
from dotenv import load_dotenv

from rag_pipeline.step2_llm_client import get_token
from rag_pipeline.step5_extractor import (
    extract_via_targeted_retrieval,
    _upload_semaphore,
    postprocess_extraction_result,
    EXTRACTION_PIPELINE_VERSION,
)
from rag_pipeline.step4_validators import validate_correctness, ensure_schema_completeness
from rag_pipeline.step6_chat import generate_chat_response, generate_chat_response_stream
from rag_pipeline.step7_pdf_generator import generate_tender_pdf

# ── Environment ────────────────────────────────────────────────────────────────
load_dotenv()

API_URL = str(os.getenv("MODEL_BASE_URL", "")) + str(os.getenv("MODEL_ENDPOINT", ""))

UPLOAD_DIR = Path(__file__).parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
CACHE_DIR = UPLOAD_DIR / "cache"
CACHE_DIR.mkdir(exist_ok=True)

# Fetch token on startup
get_token()

# ── Flask app ──────────────────────────────────────────────────────────────────
app = Flask(__name__)
# Allow CAP backend (localhost:4004) to call this service during development
CORS(app, resources={r"/*": {"origins": ["http://localhost:4004", "http://127.0.0.1:4004"]}})


# ── Health check ───────────────────────────────────────────────────────────────
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


# ── Live analytics (in-memory only — nothing here is persisted to a database) ───
# The Analytics screen polls GET /analytics/live instead of reading stored
# rows from Postgres, so this process's memory is the only source of truth.
# Capped ring buffer: entries are lost on restart and old ones evicted past
# _MAX_SESSIONS, by design.
_MAX_SESSIONS = 20
_analytics_lock = threading.Lock()
_analytics_sessions = OrderedDict()   # id -> session dict, insertion order = oldest first


def _analytics_start(session_id, filename):
    with _analytics_lock:
        _analytics_sessions[session_id] = {
            "id": session_id,
            "filename": filename,
            "status": "processing",
            "groupsDone": 0,
            "groupsTotal": 6,
            "inputTokens": 0,
            "outputTokens": 0,
            "cacheReadTokens": 0,
            "cacheWriteTokens": 0,
            "startedAt": time.time(),
            "elapsedSec": 0,
        }
        while len(_analytics_sessions) > _MAX_SESSIONS:
            _analytics_sessions.popitem(last=False)


def _analytics_progress(session_id, group_name, usage, groups_done):
    with _analytics_lock:
        session = _analytics_sessions.get(session_id)
        if not session:
            return
        session["groupsDone"] = groups_done
        session["inputTokens"] = usage.get("input_tokens", 0)
        session["outputTokens"] = usage.get("output_tokens", 0)
        session["cacheReadTokens"] = usage.get("cache_read_input_tokens", 0)
        session["cacheWriteTokens"] = usage.get("cache_creation_input_tokens", 0)
        session["elapsedSec"] = round(time.time() - session["startedAt"], 2)
        session["lastGroup"] = group_name


def _analytics_finish(session_id, status="done"):
    with _analytics_lock:
        session = _analytics_sessions.get(session_id)
        if not session:
            return
        session["status"] = status
        session["elapsedSec"] = round(time.time() - session["startedAt"], 2)


@app.route("/analytics/live", methods=["GET"])
def analytics_live():
    with _analytics_lock:
        sessions = list(reversed(_analytics_sessions.values()))
    return jsonify({"sessions": sessions})


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
# CAP stores this JSON in Postgres (AIResults.rawResponse) and links it
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

    # ── Cache check ───────────────────────────────────────────────────────────
    # SHA-256 the raw bytes so the same PDF uploaded twice skips the AI pipeline.
    # Results are stored under uploads/cache/<hash>.json after the first run.
    #
    # CACHE_REPLAY_DELAY_SECS lets you simulate slow processing in dev/demo mode.
    # Default is 3 s — long enough for the frontend timeline animation to show a
    # couple of steps, but short enough to avoid proxy socket-idle timeouts.
    #
    # ⚠️  NEVER set this above ~60 s in dev: the Vite proxy's socket idle timeout
    # will fire and the client receives a 502 before the response arrives.
    # For true no-delay (CI / automated tests), set CACHE_REPLAY_DELAY_SECS=0.
    CACHE_REPLAY_DELAY_SECS = int(os.getenv("CACHE_REPLAY_DELAY_SECS", "3"))

    start_time = time.time()
    pdf_bytes = file.read()
    file_hash = hashlib.sha256(pdf_bytes).hexdigest()
    file.seek(0)

    cache_path = CACHE_DIR / f"{file_hash}.json"
    if cache_path.exists():
        try:
            cached_output = json.loads(cache_path.read_text())
            if cached_output.get("_pipeline_version") != EXTRACTION_PIPELINE_VERSION:
                raise ValueError("stale extraction pipeline version")
            cached_output = postprocess_extraction_result(cached_output, file_hash)
            if CACHE_REPLAY_DELAY_SECS:
                time.sleep(CACHE_REPLAY_DELAY_SECS)
            return jsonify(cached_output)
        except Exception:
            # Corrupted, stale, or pre-version cache — fall through to full pipeline
            try:
                cache_path.unlink(missing_ok=True)
            except Exception:
                pass

    # 1 + 2. Save uploaded PDF with a unique prefix to prevent filename collisions
    # between concurrent uploads of identically-named files. Doubles as the live
    # analytics session id — already unique per upload.
    safe_filename = f"{uuid.uuid4().hex[:8]}_{file.filename}"
    file_path = UPLOAD_DIR / safe_filename
    file.save(str(file_path))

    if not _upload_semaphore.acquire(timeout=10):
        return jsonify({"error": "Server busy — too many uploads in progress. Please try again shortly."}), 503

    _analytics_start(safe_filename, file.filename)
    try:
        # Pass get_token as a callable so each chunk call fetches a fresh token,
        # preventing 401 errors when extraction runs longer than the token lifetime.
        final_json   = extract_via_targeted_retrieval(
            get_token, API_URL, str(file_path), file_hash,
            on_group_done=lambda name, usage, n: _analytics_progress(safe_filename, name, usage, n),
        )
        final_json   = validate_correctness(final_json)
        final_json   = ensure_schema_completeness(final_json)
    except Exception as e:
        _analytics_finish(safe_filename, status="error")
        return jsonify({"error": str(e)}), 500
    finally:
        _upload_semaphore.release()
        # The upload-temp copy is no longer needed — ingest_pdf() already persisted a
        # durable copy under storage/documents/<hash>.pdf for later chat retrieval.
        try:
            file_path.unlink(missing_ok=True)
        except Exception:
            pass
    _analytics_finish(safe_filename, status="done")

    raw_tenders = final_json.get("tenders", [])

    # Handle empty tenders (no tender info found in PDF)
    if not raw_tenders:
        return jsonify({"tenders": [], "message": "No tender information found in the document"})

    output_tenders = []
    for tender_doc in raw_tenders:
        # Support both new schema (tender_overview) and old (tender_information)
        overview = tender_doc.get("tender_overview") or tender_doc.get("tender_information") or {}
        title = overview.get("title", "")
        output_tenders.append({
            # summary feeds the PDF title (CAP's generatePDF action); keep generating it.
            "summary":      title or "Tender document processed",
            "documentHash": file_hash,
            **tender_doc
        })

    end_time = time.time()
    analytics = final_json.get("_analytics", {})
    analytics["processingTimeSec"] = round(end_time - start_time, 2)

    output = {"tenders": output_tenders, "_analytics": analytics, "_pipeline_version": EXTRACTION_PIPELINE_VERSION}

    # Persist result so re-upload of the same PDF returns instantly
    try:
        cache_path.write_text(json.dumps(output))
    except Exception:
        pass  # non-fatal — cache miss on next upload is acceptable

    return jsonify(output)


# ── POST /generate_pdf ─────────────────────────────────────────────────────────
# Called by CAP when the user clicks "Download" on a tender.
# Receives the tender's structured JSON sections and returns a formatted PDF.
# ──────────────────────────────────────────────────────────────────────────────
@app.route("/generate_pdf", methods=["POST"])
def generate_pdf():
    data = request.get_json(force=True) or {}
    tender = data.get("tender", {})
    # Support both new (tender_overview) and old (tender_information) key for PDF title
    _overview = tender.get("tender_overview") or tender.get("tender_information") or {}
    title = data.get("title", _overview.get("title", "Tender Synopsis"))

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



# ── POST /stream-response ──────────────────────────────────────────────────────
# Streaming variant of /response — emits SSE chunks as the model generates them.
# Each chunk: `data: {"text": "..."}\n\n`   Final event: `data: [DONE]\n\n`
# ──────────────────────────────────────────────────────────────────────────────
@app.route("/stream-response", methods=["POST"])
def stream_response():
    data      = request.get_json(force=True) or {}
    message   = (data.get("message")  or "").strip()
    tender_id = (data.get("tenderId") or "").strip()
    history   = data.get("history") or []
    content_hash = (data.get("contentHash") or "").strip()
    if not isinstance(history, list):
        history = []

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
            # Attempt true streaming; SAP AI Core /invoke drops connection when
            # stream=True is unsupported, so fall back to non-streaming on any error.
            streamed = False
            try:
                for chunk in generate_chat_response_stream(token, API_URL, message, tender_id, history, content_hash):
                    yield f"data: {json.dumps({'text': chunk})}\n\n"
                    streamed = True
            except Exception:
                reply = generate_chat_response(token, API_URL, message, tender_id, history, content_hash)
                yield f"data: {json.dumps({'text': reply})}\n\n"
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

