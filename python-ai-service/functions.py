import os
import json
import base64
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from pypdf import PdfReader, PdfWriter

try:
    import fitz  # pymupdf
    _FITZ_AVAILABLE = True
except ImportError:
    _FITZ_AVAILABLE = False

_session = requests.Session()

def split_pdf(input_pdf: str, pages_per_file: int):
    file_names_list=[]
    reader = PdfReader(input_pdf)
    total_pages = len(reader.pages)
    pdf_name = os.path.splitext(os.path.basename(input_pdf))[0]
    output_folder = os.path.join(os.path.dirname(input_pdf), f"{pdf_name}_split")
    os.makedirs(output_folder, exist_ok=True)
    for start_page in range(0, total_pages, pages_per_file):
        writer = PdfWriter()
        end_page = min(start_page + pages_per_file, total_pages)
        for page_num in range(start_page, end_page):
            writer.add_page(reader.pages[page_num])
        output_file = os.path.join(output_folder, f"{pdf_name}_part_{start_page // pages_per_file + 1}.pdf")
        file_names_list.append(output_file)
        with open(output_file, "wb") as f:
            writer.write(f)
    return file_names_list

def parse_ai_json(ai_text: str) -> dict:
    text = ai_text.strip()
    import re
    text = re.sub(r"^```(?:json)?\s*\n?", "", text, flags=re.MULTILINE)
    obj_start  = text.find('{')
    arr_start  = text.find('[')
    if obj_start == -1 and arr_start == -1:
        raise ValueError(f"No JSON object found in AI response.\n\nRaw:\n{text[:500]}")
    if obj_start == -1 or (arr_start != -1 and arr_start < obj_start):
        start, end_char = arr_start, ']'
    else:
        start, end_char = obj_start, '}'
    end = text.rfind(end_char)
    if end == -1 or end < start:
        raise ValueError(f"Malformed JSON (no closing '{end_char}') in AI response.\n\nRaw:\n{text[:500]}")
    text = text[start:end + 1]
    return json.loads(text)

def get_access_token(cred):
    data1 = {"grant_type": "client_credentials"}
    resp = _session.post(
        cred["TOKEN_URL"], data=data1,
        auth=(cred["CLIENT_ID"], cred["CLIENT_SECRET"]), timeout=300
    )
    resp.raise_for_status()
    return resp.json()["access_token"]

def get_result(token, API_URL, payload, retries=3, timeout=600):
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "AI-Resource-Group": "grounding",
    }
    last_exc = None
    for attempt in range(retries):
        try:
            resp = _session.post(API_URL, json=payload, headers=headers, timeout=timeout)
            resp.raise_for_status()
            response_json = resp.json()
            content_list = response_json.get("content")
            if not content_list or not isinstance(content_list, list):
                raise ValueError(f"Unexpected API response shape: {list(response_json.keys())}")
            first = content_list[0]
            text = first.get("text") if isinstance(first, dict) else None
            if not text:
                raise ValueError(f"No 'text' in API content item: {first}")
            return text
        except requests.exceptions.HTTPError as e:
            last_exc = e
            if resp.status_code >= 500 and attempt < retries - 1:
                wait = 2 ** attempt
                time.sleep(wait)
                continue
            raise
    raise last_exc

def reading_file(file_path):
    with open(file_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")

def _has_text(file_path: str) -> bool:
    try:
        reader = PdfReader(file_path)
        for page in reader.pages[:5]:
            text = page.extract_text() or ""
            if len(text.strip()) > 50:
                return True
        return False
    except Exception:
        return False

def _render_pages_as_images(file_path: str, dpi: int = 110, max_pages: int = 20) -> list:
    if not _FITZ_AVAILABLE:
        raise RuntimeError("pymupdf not installed")
    doc = fitz.open(file_path)
    try:
        mat = fitz.Matrix(dpi / 72, dpi / 72)
        images = []
        for i, page in enumerate(doc):
            if i >= max_pages: break
            pix = page.get_pixmap(matrix=mat)
            images.append(base64.b64encode(pix.tobytes("jpeg", jpg_quality=75)).decode("utf-8"))
        return images
    finally:
        doc.close()

# --- PASS 1: EXTRACT RAW FACTS PER CHUNK ---

def generate_payload_extract_facts(encoded: str) -> dict:
    prompt = """You are a specialized Power Sector Tender expert. Your task is to extract all relevant contractual, technical, and financial facts from this document chunk.
Do not format as a final JSON. Just extract a highly detailed bulleted list of facts you find.

FOCUS AREAS:
- Tender Information: Title, Number, Agency, Estimated Cost, Tender Fee
- Dates: Publication, Pre-bid, Submission, Opening
- Scope of Work: All technical categories and detailed descriptions
- Eligibility & Qualification: Technical options, MAAT, Liquid Assets, Net Worth, Pending Litigation
- Security & Financials: EMD, BGs, Bid Validity, Performance Security, CPG
- Payment Terms: Advance payments, progressive milestones, delayed interest
- Price Variation: Formulas, indices (IEEMA), firm vs variable components, materials
- Contract Conditions: Completion time, DLP, Liquidated Damages, Penalties
- Technical Bid Documents: ALL Form numbers and document names mentioned for Envelope 1

Output plain text bullet points with exact values, numbers, percentages, currencies, and form numbers."""
    return {
        "messages": [
            {"role": "user", "content": prompt},
            {"role": "user", "content": [{"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": encoded}}]}
        ],
        "max_tokens": 4000,
        "anthropic_version": "bedrock-2023-05-31"
    }

def generate_payload_extract_facts_vision(images_b64: list) -> dict:
    prompt = """You are a specialized Power Sector Tender expert. Your task is to extract all relevant contractual, technical, and financial facts from these images.
Do not format as a final JSON. Just extract a highly detailed bulleted list of facts you find.

FOCUS AREAS:
- Tender Information: Title, Number, Agency, Estimated Cost, Tender Fee
- Dates: Publication, Pre-bid, Submission, Opening
- Scope of Work: All technical categories and detailed descriptions
- Eligibility & Qualification: Technical options, MAAT, Liquid Assets, Net Worth, Pending Litigation
- Security & Financials: EMD, BGs, Bid Validity, Performance Security, CPG
- Payment Terms: Advance payments, progressive milestones, delayed interest
- Price Variation: Formulas, indices (IEEMA), firm vs variable components, materials
- Contract Conditions: Completion time, DLP, Liquidated Damages, Penalties
- Technical Bid Documents: ALL Form numbers and document names mentioned for Envelope 1

Output plain text bullet points with exact values, numbers, percentages, currencies, and form numbers."""
    content = [{"type": "text", "text": prompt}]
    for img in images_b64:
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": img}})
    return {
        "messages": [{"role": "user", "content": content}],
        "max_tokens": 4000,
        "anthropic_version": "bedrock-2023-05-31"
    }

def _extract_chunk(token, API_URL, file_path):
    if _has_text(file_path):
        encoded = reading_file(file_path)
        payload = generate_payload_extract_facts(encoded)
    else:
        images_b64 = _render_pages_as_images(file_path)
        payload = generate_payload_extract_facts_vision(images_b64)
    
    result = get_result(token, API_URL, payload)
    print(f"[chunk extracted] {os.path.basename(file_path)}")
    return result

def _chunk_is_relevant(file_path: str) -> bool:
    try:
        reader = PdfReader(file_path)
        text = " ".join((p.extract_text() or "").lower() for p in reader.pages)
        keywords = [
            "notice inviting", "earnest money", "emd", "bid security", "liquidated damages",
            "price variation", "price adjustment", "maat", "turnover", "net worth", "payment terms", 
            "defect liability", "performance security", "bank guarantee", "ebg", "cpg",
            "bid data sheet", "instruction to bidders", "commercial terms", "qualification",
            "eligibility", "scope of work", "bill of quantities",
            "form ", "annexure ", "format ", "appendix ", "schedule "
        ]
        hits = sum(1 for kw in keywords if kw in text)
        return hits >= 2
    except Exception as e:
        return True

def extract_facts_from_chunks(token, API_URL, file_path_list):
    relevant_chunks = [fp for fp in file_path_list if _chunk_is_relevant(fp)]
    dropped = len(file_path_list) - len(relevant_chunks)
    print(f"[filter] Dropped {dropped} out of {len(file_path_list)} chunks as irrelevant technical specs.")
    
    if not relevant_chunks:
        print("[filter] WARNING: All chunks dropped! Reverting to processing all chunks.")
        relevant_chunks = file_path_list

    max_workers = min(len(relevant_chunks), 5)
    all_facts = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_extract_chunk, token, API_URL, fp): fp for fp in relevant_chunks}
        for future in as_completed(futures):
            try:
                all_facts.append(future.result())
            except Exception as e:
                print(f"[chunk error] {futures[future]}: {e}")
    if not all_facts:
        raise RuntimeError("All chunks failed.")
    return "\\n\\n---NEXT CHUNK---\\n\\n".join(all_facts)


# --- PASS 2: SYNTHESIZE FINAL JSON ---

def synthesize_final_json(token, API_URL, raw_facts: str) -> dict:
    prompt = """You are an expert data structured extraction AI for Power Sector EPC tenders.
I am providing you with raw facts extracted from multiple chunks of a large tender document.
Your task is to organize these facts into ONE perfectly formatted JSON document matching the exact schema below.

STRICT SCHEMA ENFORCEMENT:
- You must return ONLY valid JSON.
- If a value is missing or not found, use "" (empty string), null, or [] (empty list) as appropriate for the type.
- Do NOT add keys that are not in this schema.
- For `estimated_cost` and `tender_fee`, extract the numerical amount and currency.
- For `technical_bid_documents.grouped_documents`, logically group related forms/documents together to save space and concatenate with '+'. ALWAYS include the detailed form name alongside its number (e.g., "Bid Security eBG (Form 3B) + Bid Securing Declaration (Form 3A)").

SCHEMA:
{
  "tenders": [
    {
      "tender_information": {
        "title": "Exact string",
        "reference_no": "Exact string",
        "version": "Exact string",
        "issuing_authority": "Exact string",
        "contract_type": "Turnkey, Supply, etc.",
        "bid_system": "Two Bid, Single Bid, etc.",
        "funding_agency": "ADB, REC, etc.",
        "estimated_cost": {"amount": 0.0, "currency": "INR", "denomination": "Lakhs/Crores/None"},
        "tender_fee": {"amount": 0.0, "currency": "INR"},
        "budget_category": "Capex, Opex, etc.",
        "contacts": [{"name": "string", "role": "string", "email": "string"}]
      },
      "key_dates": {
        "publication": "YYYY-MM-DD or raw string",
        "pre_bid_meeting": {"date": "string", "time": "string"},
        "bid_submission_deadline": {"date": "string", "time": "string"},
        "technical_opening": {"date": "string", "time": "string"}
      },
      "scope_of_work": [
        {"category": "string (e.g. New Substations)", "details": "string (detailed description)"}
      ],
      "eligibility_and_qualification": {
        "technical": {
          "heading_note": "string",
          "options": [{"option": "A", "requirement": "string"}],
          "similar_works_definition": "string"
        },
        "financial": [
          {"criterion": "Net Worth", "requirement": "string"},
          {"criterion": "MAAT", "requirement": "string"},
          {"criterion": "Liquid Assets / Credit Facility", "requirement": "string"},
          {"criterion": "Pending Litigation", "requirement": "string"}
        ]
      },
      "security_and_financials": {
        "emd": {"percentage": 0.0, "max_cap_inr": 0.0, "form": "string"},
        "bank_details": {"bank": "string", "account": "string", "ifsc": "string"},
        "bid_validity_days": 0,
        "performance_security_percent": 0.0,
        "cpg_supply_percent": 0.0,
        "cpg_erection_percent": 0.0
      },
      "payment_terms": {
        "advance_payments": [
          {"component": "string", "percentage": 0.0, "conditions": ["string"]}
        ],
        "progressive_payments": [
          {"component": "string", "milestone": "string", "percentage": 0.0}
        ],
        "standard_timeline_days": 0,
        "delayed_interest_rate": "string"
      },
      "price_variation": {
        "is_applicable": true,
        "applicable_components": ["string"],
        "firm_components": ["string"],
        "materials": [
          {"name": "string", "index_reference": "string", "formula_variables": ["string"]}
        ]
      },
      "contract_conditions": {
        "completion_time_months": 0,
        "defect_liability_period_months": 0,
        "liquidated_damages": {"rate_per_week_percent": 0.0, "cap_percent": 0.0},
        "quality_penalties": {"major_defect_percent": 0.0, "minor_defect_percent": 0.0},
        "special_requirements": ["string"]
      },
      "technical_bid_documents": {
        "grouped_documents": ["string"],
        "has_price_disclosure_warning": true
      }
    }
  ]
}

RAW EXTRACTED FACTS:
""" + raw_facts + """

FINAL OUTPUT:
Return ONLY the JSON document. Do not include markdown formatting or explanations.
"""
    payload = {
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 4000,
        "anthropic_version": "bedrock-2023-05-31"
    }
    result_text = get_result(token, API_URL, payload)
    return parse_ai_json(result_text)

def generate_chat_response(token, API_URL, message, tender_id=""):
    context = f" The user is asking about tender '{tender_id}'." if tender_id else ""
    prompt = (
        f"You are an AI assistant helping with tender document management.{context}\n\n"
        f"User question: {message}\n\n"
        "Provide a concise answer in under 150 words."
    )
    payload = {
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 512,
        "anthropic_version": "bedrock-2023-05-31"
    }
    return get_result(token, API_URL, payload, retries=1, timeout=55)
