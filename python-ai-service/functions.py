import os
import json
import base64
import time
import threading
import requests
from requests.adapters import HTTPAdapter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pypdf import PdfReader, PdfWriter

try:
    import fitz  # pymupdf
    _FITZ_AVAILABLE = True
except ImportError:
    _FITZ_AVAILABLE = False

_session = requests.Session()
_session.mount('https://', HTTPAdapter(pool_connections=10, pool_maxsize=50))
_session.mount('http://',  HTTPAdapter(pool_connections=10, pool_maxsize=50))

# Max 3 concurrent PDF uploads — prevents one user from exhausting the connection pool
_upload_semaphore = threading.Semaphore(3)

def split_pdf(input_pdf: str, pages_per_file: int, overlap: int = 0):
    """Split a PDF into overlapping chunks.

    overlap=5 means consecutive chunks share 5 pages, preventing values
    that straddle a chunk boundary from being lost entirely.
    """
    file_names_list = []
    reader = PdfReader(input_pdf)
    total_pages = len(reader.pages)
    pdf_name = os.path.splitext(os.path.basename(input_pdf))[0]
    output_folder = os.path.join(os.path.dirname(input_pdf), f"{pdf_name}_split")
    os.makedirs(output_folder, exist_ok=True)
    advance = max(1, pages_per_file - overlap)
    chunk_idx = 0
    start_page = 0
    while start_page < total_pages:
        writer = PdfWriter()
        end_page = min(start_page + pages_per_file, total_pages)
        for page_num in range(start_page, end_page):
            writer.add_page(reader.pages[page_num])
        output_file = os.path.join(output_folder, f"{pdf_name}_part_{chunk_idx + 1}.pdf")
        file_names_list.append(output_file)
        with open(output_file, "wb") as f:
            writer.write(f)
        chunk_idx += 1
        start_page += advance
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
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Strip trailing commas before closing braces/brackets — a common LLM mistake
        cleaned = re.sub(r",\s*([}\]])", r"\1", text)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"AI returned unparseable JSON after cleanup. Snippet: {text[:200]!r}"
            ) from exc

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
            _u = response_json.get("usage", {})
            print(f"[tokens] in={_u.get('input_tokens','?')} out={_u.get('output_tokens','?')} cache_write={_u.get('cache_creation_input_tokens',0)} cache_read={_u.get('cache_read_input_tokens',0)}")
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
                time.sleep(2 ** attempt)
                continue
            raise
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            last_exc = e
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise
    raise last_exc

def get_result_tool_use(token, API_URL, payload, retries=3, timeout=600):
    """Like get_result but returns the structured input dict from a tool_use response.

    Falls back to JSON text parsing if the API proxy does not forward tool_use blocks,
    so this is safe even when the upstream gateway strips tool calling support.
    """
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
            _rj = resp.json()
            _u = _rj.get("usage", {})
            print(f"[tokens] in={_u.get('input_tokens','?')} out={_u.get('output_tokens','?')} cache_write={_u.get('cache_creation_input_tokens',0)} cache_read={_u.get('cache_read_input_tokens',0)}")
            content_list = _rj.get("content", [])
            for item in content_list:
                if isinstance(item, dict) and item.get("type") == "tool_use":
                    return item["input"]
            for item in content_list:
                if isinstance(item, dict) and item.get("type") == "text" and item.get("text"):
                    return parse_ai_json(item["text"])
            raise ValueError(f"No usable content in tool-use response: {content_list}")
        except requests.exceptions.HTTPError as e:
            last_exc = e
            if resp.status_code >= 500 and attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            last_exc = e
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
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
    prompt = """You are a Power Sector Tender data extractor. Extract facts from this document chunk using the EXACT structured format below. Do NOT summarize, merge, or interpret — copy values verbatim with all qualifiers.

OUTPUT FORMAT — use exactly these section headers and attribute names. Only fill attributes found in THIS chunk. Omit any line whose value you cannot find:

## TENDER_INFORMATION
title:
reference_no:
version:
issuing_authority:
contract_type:
bid_system:
funding_agency:
estimated_cost_amount:
estimated_cost_currency:
estimated_cost_denomination:
tender_fee_amount:
tender_fee_currency:
budget_category:

## KEY_DATES
publication_date:
pre_bid_meeting_date:
pre_bid_meeting_time:
pre_bid_meeting_timezone:
bid_deadline_date:
bid_deadline_time:
bid_deadline_timezone:
technical_opening_date:
technical_opening_time:
technical_opening_timezone:
financial_opening_date:
financial_opening_time:
work_order_issuance:

## ELIGIBILITY_TECHNICAL
experience_lookback_years:
experience_cutoff_date:
option_A:
option_B:
option_C:
eligible_sectors:
ineligible_conditions:
similar_works_definition:
jv_lead_member_rule:
supporting_docs:

## ELIGIBILITY_FINANCIAL
maat_percentage:
maat_reference_period:
maat_full_text:
net_worth_requirement:
liquid_assets_percentage:
liquid_assets_full_text:
pending_litigation_limit:

## SECURITY_AND_FINANCIALS
emd_percentage:
emd_amount:
emd_form:
bid_validity_days:
performance_security_percent:
cpg_supply_percent:
cpg_erection_percent:
bank_name:
bank_account_number:
bank_ifsc:

## CONTRACT_CONDITIONS
completion_time_months:
completion_time_from:
defect_liability_months:
defect_liability_from:
ld_rate_per_week_percent:
ld_cap_percent:
ld_applied_to:
quality_penalty_major_percent:
quality_penalty_minor_percent:
special_requirement_1:
special_requirement_2:
special_requirement_3:

## PAYMENT_TERMS
advance_supply_percent:
advance_supply_conditions:
advance_erection_percent:
advance_erection_conditions:
milestone_1_description:
milestone_1_percent:
milestone_2_description:
milestone_2_percent:
payment_timeline_days:
delayed_payment_interest:

## PRICE_VARIATION
is_applicable:                  ← Yes or No
firm_price_components:          ← components that are price-firm (no variation), comma-separated
variable_price_components:      ← components subject to price variation, comma-separated
composite_formula:              ← if one formula covers all materials, copy the full expression verbatim
material_1_name:                ← full item name exactly as in document, e.g. "ACSR Conductor" / "Distribution Transformer – Al wound (upto 2,500 kVA, 33 kV)"
material_1_formula:             ← complete formula + all variable definitions as written, e.g. "P = Po + WA(AL–ALo) + WF(FE–FEo) WA = wt. of aluminium (MT/km); WF = wt. of steel (MT/km); AL = EC Grade Al Ingot price; FE = Galvanized steel wire price. Prices: 30 days prior to delivery vs. 30 days prior to tender opening"
material_1_index_source:        ← exact IEEMA circular code + effective date, e.g. "IEEMA Circular: IEEMA/PVC/CONDUCTOR/2012 (eff. 1 Apr 2012)"
material_2_name:
material_2_formula:
material_2_index_source:
material_3_name:
material_3_formula:
material_3_index_source:
← CONTINUE this 3-line pattern for EVERY additional row in the price variation table
← Use material_4_, material_5_, material_6_, ..., material_N_ — there is NO upper limit
← A tender may have 6–15 material rows; extract ALL of them, do not stop at any fixed number

## SCOPE_OF_WORK
category_1:
category_1_details:
category_2:
category_2_details:
category_3:
category_3_details:
category_4:
category_4_details:

## TECHNICAL_BID_DOCUMENTS
doc_1:
doc_2:
doc_3:
doc_4:
doc_5:
doc_6:
doc_7:
doc_8:
doc_9:
doc_10:
certificate_1:
certificate_2:
certificate_3:
has_price_disclosure_warning:

## CONTACTS
contact_1_name:
contact_1_role:
contact_1_email:
contact_2_name:
contact_2_role:
contact_2_email:

RULES:
1. Only fill attributes found in THIS chunk. Omit lines entirely if the value is not present.
2. NEVER write "as per SCC/ITB/GCC/RFB/clause X" as a value — find the actual number/text or omit.
3. estimated_cost_amount is a NUMBER ONLY (e.g. 52546.85). Put currency in estimated_cost_currency (e.g. INR). Put denomination in estimated_cost_denomination (e.g. Lakhs).
4. SCOPE: major work categories only (substation, DTR, RMU, HVDS, feeder, UG cable, SCADA) — no sub-components, no environmental parameters, no post-award deliverables.
5. DOCUMENTS: bid-stage Envelope 1 documents only (forms by number+name, eligibility certs, financial statements, BGs). Exclude design drawings, as-built drawings, safety plans, PPE lists, post-award deliverables.
6. Numbers that are ONLY numbers: estimated_cost_amount, tender_fee_amount, emd_percentage, bid_validity_days, performance_security_percent, cpg_supply_percent, cpg_erection_percent, completion_time_months, defect_liability_months, ld_rate_per_week_percent, ld_cap_percent, maat_percentage, liquid_assets_percentage, milestone_1_percent, milestone_2_percent — write digits only, no units.
7. PRICE VARIATION: For each material row in the price variation / escalation table: (a) material_N_name = full item name as printed; (b) material_N_formula = the complete formula expression PLUS all variable definitions exactly as written in the document (do not abbreviate); (c) material_N_index_source = the exact IEEMA circular code and effective date, e.g. "IEEMA/PVC/CONDUCTOR/2012 (eff. 1 Apr 2012)". Extract every row in the table — there may be 6–10 materials."""
    return {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt, "cache_control": {"type": "ephemeral"}},
                    {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": encoded}},
                ],
            }
        ],
        "max_tokens": 6000,
        "anthropic_version": "bedrock-2023-05-31",
    }

def generate_payload_extract_facts_vision(images_b64: list) -> dict:
    prompt = """You are a Power Sector Tender data extractor. Extract facts from these document images using the EXACT structured format below. Do NOT summarize, merge, or interpret — copy values verbatim with all qualifiers.

OUTPUT FORMAT — use exactly these section headers and attribute names. Only fill attributes found in THESE images. Omit any line whose value you cannot find:

## TENDER_INFORMATION
title:
reference_no:
version:
issuing_authority:
contract_type:
bid_system:
funding_agency:
estimated_cost_amount:
estimated_cost_currency:
estimated_cost_denomination:
tender_fee_amount:
tender_fee_currency:
budget_category:

## KEY_DATES
publication_date:
pre_bid_meeting_date:
pre_bid_meeting_time:
pre_bid_meeting_timezone:
bid_deadline_date:
bid_deadline_time:
bid_deadline_timezone:
technical_opening_date:
technical_opening_time:
technical_opening_timezone:
financial_opening_date:
financial_opening_time:
work_order_issuance:

## ELIGIBILITY_TECHNICAL
experience_lookback_years:
experience_cutoff_date:
option_A:
option_B:
option_C:
eligible_sectors:
ineligible_conditions:
similar_works_definition:
jv_lead_member_rule:
supporting_docs:

## ELIGIBILITY_FINANCIAL
maat_percentage:
maat_reference_period:
maat_full_text:
net_worth_requirement:
liquid_assets_percentage:
liquid_assets_full_text:
pending_litigation_limit:

## SECURITY_AND_FINANCIALS
emd_percentage:
emd_amount:
emd_form:
bid_validity_days:
performance_security_percent:
cpg_supply_percent:
cpg_erection_percent:
bank_name:
bank_account_number:
bank_ifsc:

## CONTRACT_CONDITIONS
completion_time_months:
completion_time_from:
defect_liability_months:
defect_liability_from:
ld_rate_per_week_percent:
ld_cap_percent:
ld_applied_to:
quality_penalty_major_percent:
quality_penalty_minor_percent:
special_requirement_1:
special_requirement_2:
special_requirement_3:

## PAYMENT_TERMS
advance_supply_percent:
advance_supply_conditions:
advance_erection_percent:
advance_erection_conditions:
milestone_1_description:
milestone_1_percent:
milestone_2_description:
milestone_2_percent:
payment_timeline_days:
delayed_payment_interest:

## PRICE_VARIATION
is_applicable:                  ← Yes or No
firm_price_components:          ← components that are price-firm (no variation), comma-separated
variable_price_components:      ← components subject to price variation, comma-separated
composite_formula:              ← if one formula covers all materials, copy the full expression verbatim
material_1_name:                ← full item name exactly as in document, e.g. "ACSR Conductor" / "Distribution Transformer – Al wound (upto 2,500 kVA, 33 kV)"
material_1_formula:             ← complete formula + all variable definitions as written, e.g. "P = Po + WA(AL–ALo) + WF(FE–FEo) WA = wt. of aluminium (MT/km); WF = wt. of steel (MT/km); AL = EC Grade Al Ingot price; FE = Galvanized steel wire price. Prices: 30 days prior to delivery vs. 30 days prior to tender opening"
material_1_index_source:        ← exact IEEMA circular code + effective date, e.g. "IEEMA Circular: IEEMA/PVC/CONDUCTOR/2012 (eff. 1 Apr 2012)"
material_2_name:
material_2_formula:
material_2_index_source:
material_3_name:
material_3_formula:
material_3_index_source:
← CONTINUE this 3-line pattern for EVERY additional row in the price variation table
← Use material_4_, material_5_, material_6_, ..., material_N_ — there is NO upper limit
← A tender may have 6–15 material rows; extract ALL of them, do not stop at any fixed number

## SCOPE_OF_WORK
category_1:
category_1_details:
category_2:
category_2_details:
category_3:
category_3_details:
category_4:
category_4_details:

## TECHNICAL_BID_DOCUMENTS
doc_1:
doc_2:
doc_3:
doc_4:
doc_5:
doc_6:
doc_7:
doc_8:
doc_9:
doc_10:
certificate_1:
certificate_2:
certificate_3:
has_price_disclosure_warning:

## CONTACTS
contact_1_name:
contact_1_role:
contact_1_email:
contact_2_name:
contact_2_role:
contact_2_email:

RULES:
1. Only fill attributes found in THESE images. Omit lines entirely if the value is not present.
2. NEVER write "as per SCC/ITB/GCC/RFB/clause X" as a value — find the actual number/text or omit.
3. estimated_cost_amount is a NUMBER ONLY (e.g. 52546.85). Put currency in estimated_cost_currency (e.g. INR). Put denomination in estimated_cost_denomination (e.g. Lakhs).
4. SCOPE: major work categories only (substation, DTR, RMU, HVDS, feeder, UG cable, SCADA) — no sub-components, no environmental parameters, no post-award deliverables.
5. DOCUMENTS: bid-stage Envelope 1 documents only (forms by number+name, eligibility certs, financial statements, BGs). Exclude design drawings, as-built drawings, safety plans, PPE lists, post-award deliverables.
6. Numbers that are ONLY numbers: estimated_cost_amount, tender_fee_amount, emd_percentage, bid_validity_days, performance_security_percent, cpg_supply_percent, cpg_erection_percent, completion_time_months, defect_liability_months, ld_rate_per_week_percent, ld_cap_percent, maat_percentage, liquid_assets_percentage, milestone_1_percent, milestone_2_percent — write digits only, no units.
7. PRICE VARIATION: For each material row in the price variation / escalation table: (a) material_N_name = full item name as printed; (b) material_N_formula = the complete formula expression PLUS all variable definitions exactly as written in the document (do not abbreviate); (c) material_N_index_source = the exact IEEMA circular code and effective date, e.g. "IEEMA/PVC/CONDUCTOR/2012 (eff. 1 Apr 2012)". Extract every row in the table — there may be 6–10 materials."""
    content = [{"type": "text", "text": prompt, "cache_control": {"type": "ephemeral"}}]
    for img in images_b64:
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": img}})
    return {
        "messages": [{"role": "user", "content": content}],
        "max_tokens": 6000,
        "anthropic_version": "bedrock-2023-05-31"
    }

def _extract_chunk(token_fn, API_URL, file_path):
    token = token_fn() if callable(token_fn) else token_fn
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

def extract_facts_from_chunks(token_fn, API_URL, file_path_list):
    relevant_chunks = [fp for fp in file_path_list if _chunk_is_relevant(fp)]
    dropped = len(file_path_list) - len(relevant_chunks)
    print(f"[filter] Dropped {dropped} out of {len(file_path_list)} chunks as irrelevant technical specs.")

    if not relevant_chunks:
        print("[filter] WARNING: All chunks dropped! Reverting to processing all chunks.")
        relevant_chunks = file_path_list

    max_workers = min(len(relevant_chunks), 10)
    all_facts = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_extract_chunk, token_fn, API_URL, fp): fp for fp in relevant_chunks}
        for future in as_completed(futures):
            try:
                all_facts.append(future.result())
            except Exception as e:
                print(f"[chunk error] {futures[future]}: {e}")
    if not all_facts:
        raise RuntimeError("All chunks failed.")
    return all_facts


# --- PASS 1.5: MERGE + DEDUPLICATE ---

_CLAUSE_REF_MARKERS = (
    "as per scc", "as per itb", "as per gcc", "as per rfb",
    "as per clause", "as specified in clause", "refer to clause",
)

_PLACEHOLDER_VALUES = {
    "", "n/a", "none", "null", "unknown", "tbd", "<unknown>",
    "not found", "not stated", "not mentioned", "not applicable",
    "to be announced", "tba",
}

def merge_chunk_facts(chunk_texts: list) -> dict:
    """Parse ## SECTION / attr: value lines from all chunk text strings.
    Groups by (SECTION, attribute), deduplicates values across chunks.
    Returns {SECTION: {attribute: [unique_value, ...]}} sorted for determinism.
    Clause references and placeholder values are discarded.
    """
    from collections import defaultdict
    merged = defaultdict(lambda: defaultdict(set))
    for chunk_text in chunk_texts:
        current_section = "GENERAL"
        for raw_line in chunk_text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("## "):
                current_section = line[3:].strip().upper().replace(" ", "_")
                continue
            if ": " not in line:
                continue
            attr, _, value = line.partition(": ")
            attr  = attr.strip().lower().replace(" ", "_").replace("-", "_")
            value = value.strip()
            if not attr or not value:
                continue
            if value.lower() in _PLACEHOLDER_VALUES:
                continue
            v_lower = value.lower()
            if any(marker in v_lower for marker in _CLAUSE_REF_MARKERS):
                continue
            merged[current_section][attr].add(value)
    return {
        section: {attr: sorted(vals) for attr, vals in attrs.items()}
        for section, attrs in merged.items()
    }

def _format_merged_for_synthesis(merged_facts: dict) -> str:
    """Format merged facts dict as readable text for the synthesis prompt.
    When multiple distinct values exist for one attribute, shows attr[variant_N] lines.
    """
    lines = []
    for section, attrs in merged_facts.items():
        lines.append(f"\n## {section}")
        for attr, values in attrs.items():
            if len(values) == 1:
                lines.append(f"  {attr}: {values[0]}")
            else:
                for i, v in enumerate(values, 1):
                    lines.append(f"  {attr}[variant_{i}]: {v}")
    return "\n".join(lines)


# --- PASS 2: SYNTHESIZE FINAL JSON ---

_DOMAIN_GLOSSARY = """
POWER SECTOR DOMAIN GLOSSARY (abbreviations used in Indian distribution tenders):
DTR=Distribution Transformer | RMU=Ring Main Unit | HVDS=High Voltage Distribution System
MAAT=Minimum Annual Average Turnover | EMD=Earnest Money Deposit | BG=Bank Guarantee
eBG=Electronic Bank Guarantee | CPG=Contract Performance Guarantee | DLP=Defect Liability Period
BSD=Bid Securing Declaration | LOA=Letter of Award | GCC=General Conditions of Contract
SCC=Special Conditions of Contract | ITB=Instructions to Bidders | RFB=Request for Bids
IEEMA=Indian Electrical & Electronics Manufacturers' Association | kV=kilovolt | MVA=Megavolt-ampere
OHL=Overhead Line | UG=Underground cable | SCADA=Supervisory Control and Data Acquisition
AB switch=Air Break switch | HT=High Tension | LT=Low Tension | NIT=Notice Inviting Tender
""".strip()

_TENDER_TOOL_SCHEMA = {
    "name": "structure_tender_data",
    "description": "Structure all extracted tender facts into the canonical JSON format.",
    "input_schema": {
        "type": "object",
        "properties": {
            "tenders": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "tender_information": {
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
                        "security_and_financials": {
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
                                "bid_validity_days":          {"type": "number"},
                                "performance_security_percent": {"type": "number"},
                                "cpg_supply_percent":         {"type": "number"},
                                "cpg_erection_percent":       {"type": "number"}
                            }
                        },
                        "payment_terms": {
                            "type": "object",
                            "properties": {
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
                        "contract_conditions": {
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
                                "special_requirements": {"type": "array", "items": {"type": "string"}}
                            }
                        },
                        "technical_bid_documents": {
                            "type": "object",
                            "properties": {
                                "grouped_documents":          {"type": "array", "items": {"type": "string"}},
                                "has_price_disclosure_warning": {"type": "boolean"}
                            }
                        }
                    }
                }
            }
        },
        "required": ["tenders"]
    }
}

def synthesize_final_json(token, API_URL, merged_facts: dict) -> dict:
    """Pass 2: Organize merged+deduplicated facts into structured JSON using tool-use.

    Tool-use forces correct field types (numbers stay numbers, objects stay objects)
    and eliminates JSON parse failures. Falls back to text parsing if the upstream
    SAP AI Core proxy does not forward the tools parameter.
    Input is the output of merge_chunk_facts() — a structured dict, not raw text.
    """
    static_prefix = f"""You are an expert data extraction AI for Power Sector EPC tenders.
Facts have been extracted and deduplicated from all chunks of a large tender document.
Use the structure_tender_data tool to organize ALL facts into the canonical format.

{_DOMAIN_GLOSSARY}

SYNTHESIS RULES:
A. CLAUSE REFERENCES: Any fact containing "as per SCC/ITB/GCC/RFB/clause X" is useless for that field — skip it. Only use facts with actual values (numbers, dates, amounts).
B. CURRENCY: estimated_cost, tender_fee, and emd must be objects with amount (number), currency ("INR"), and denomination ("Lakhs"/"Crores"/"None"). A fact "INR 52,546.85 Lakhs" → amount=52546.85, currency="INR", denomination="Lakhs". Never omit currency or denomination.
C. CONTRACT NUMBERS: completion_time_months and defect_liability_period_months must be plain numbers (e.g., 24 not "24 months"). liquidated_damages must have rate_per_week_percent and cap_percent as numbers.
D. BID DOCUMENTS: grouped_documents must contain ONLY bid-stage forms and certificates (submitted before contract award). Exclude design drawings, as-built drawings, safety plans, PPE lists, post-award deliverables.
E. GROUPING: For grouped_documents, combine related forms on the same line with '+'. Always include form number AND name, e.g., "Form 3B (Bid Security eBG) + Form 3A (Bid Securing Declaration)".
F. CONTACTS: The contacts array must contain UNIQUE individuals only. If the same person appears multiple times (same name or same email), merge them into a single entry using their most senior/complete designation. The name field must always be the person's actual name (e.g. "M S Gawali"), never a job title. The role field is the designation (e.g. "Chief Engineer (Special Projects)").
G. VARIANTS: When an attribute appears as attr[variant_1] and attr[variant_2], pick the most specific/complete value. Do not use "variant_" prefixes in the output.
H. PRICE VARIATION: Build the materials array from the extracted material_N_name / material_N_formula / material_N_index_source triplets. Each entry must have name, formula (exact expression as extracted), and index_source (exact publication name as extracted). If composite_formula is present, include it at the top level. Do not paraphrase or abbreviate formulas or index source names.

STRUCTURED EXTRACTED FACTS (deduplicated across all document chunks):"""

    payload = {
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": static_prefix, "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": _format_merged_for_synthesis(merged_facts)},
            ],
        }],
        "tools": [_TENDER_TOOL_SCHEMA],
        "tool_choice": {"type": "tool", "name": "structure_tender_data"},
        "max_tokens": 8192,
        "anthropic_version": "bedrock-2023-05-31",
    }
    result = get_result_tool_use(token, API_URL, payload)
    if not isinstance(result, dict):
        raise ValueError(f"synthesize_final_json: expected dict from AI, got {type(result).__name__}")
    # Wrap in {"tenders": [...]} if the tool returned the tender object directly
    if "tenders" not in result:
        result = {"tenders": [result]}
    tenders = result.get("tenders")
    # Model sometimes returns tenders as a JSON-encoded string (e.g. when the response was
    # truncated at max_tokens or the upstream gateway serialized the array as a string).
    if isinstance(tenders, str):
        parsed = None
        try:
            parsed = json.loads(tenders)
        except (json.JSONDecodeError, ValueError):
            raw = tenders.strip()
            # Depth-tracking recovery: walk the string to find the last complete
            # tender object at depth 1 (inside the outer array), then close the array.
            # This handles deeply-nested truncation that a simple rfind('}') misses.
            depth = 0
            last_complete_end = -1
            in_str = False
            esc = False
            for i, c in enumerate(raw):
                if esc:
                    esc = False
                    continue
                if c == '\\' and in_str:
                    esc = True
                    continue
                if c == '"':
                    in_str = not in_str
                    continue
                if in_str:
                    continue
                if c in ('{', '['):
                    depth += 1
                elif c in ('}', ']'):
                    depth -= 1
                    if depth == 1:  # just closed a top-level array element
                        last_complete_end = i + 1
            if last_complete_end > 0:
                try:
                    candidate = raw[:last_complete_end].rstrip().rstrip(',') + ']'
                    parsed = json.loads(candidate)
                except (json.JSONDecodeError, ValueError):
                    pass
            # Fallback: old approach — find last } and close any open array
            if parsed is None:
                last_brace = raw.rfind('}')
                if last_brace != -1:
                    try:
                        candidate = raw[:last_brace + 1]
                        if raw.lstrip().startswith('['):
                            candidate += ']'
                        parsed = json.loads(candidate)
                    except (json.JSONDecodeError, ValueError):
                        pass
        if parsed is not None:
            tenders = parsed if isinstance(parsed, list) else [parsed]
            result["tenders"] = tenders
    if not isinstance(tenders, list) or not tenders or not isinstance(tenders[0], dict):
        raise ValueError(
            f"synthesize_final_json: 'tenders' must be a non-empty list of objects, got: {str(result)[:200]}"
        )
    return _deduplicate_contacts(_normalize_unknowns(result))

_TITLE_KEYWORDS = frozenset({
    "engineer", "manager", "officer", "director", "chief", "superintendent",
    "commissioner", "secretary", "advisor", "executive", "assistant", "deputy",
    "joint", "additional", "general", "inspector", "incharge", "in-charge",
})

def _looks_like_title(s: str) -> bool:
    return bool(s) and any(kw in s.lower() for kw in _TITLE_KEYWORDS)

def _deduplicate_contacts(result: dict) -> dict:
    """Merge duplicate contacts within each tender.

    The AI often extracts the same person multiple times across chunks with
    different designations, and sometimes puts a job title in the 'name' field.
    We group by email (primary) or normalised name (fallback), then merge:
    - name  → whichever entry's name does NOT look like a job title
    - role  → longest string across all role fields AND any name fields that
              look like titles (since the AI often misplaces designations there)
    """
    for tender in result.get("tenders", []):
        contacts = tender.get("tender_information", {}).get("contacts")
        if not isinstance(contacts, list) or len(contacts) <= 1:
            continue

        buckets: dict = {}
        for c in contacts:
            if not isinstance(c, dict):
                continue
            email = (c.get("email") or "").strip().lower()
            name  = (c.get("name")  or "").strip().lower()
            key   = email if email else name
            if not key:
                continue
            buckets.setdefault(key, []).append(c)

        deduped = []
        for group in buckets.values():
            if len(group) == 1:
                deduped.append(group[0])
                continue

            # Best name: prefer entries where name doesn't look like a job title
            all_names  = [(c.get("name") or "").strip() for c in group]
            real_names = [n for n in all_names if n and not _looks_like_title(n)]
            best_name  = real_names[0] if real_names else min(all_names, key=len)

            # Best role: name-fields that look like titles take priority over role fields,
            # because when the AI puts a designation in 'name' it is explicitly calling
            # out that title as the person's primary description. Tiebreak by length.
            role_candidates = []  # (priority, text)
            for c in group:
                if c.get("role"):
                    role_candidates.append((1, c["role"].strip()))
                n = (c.get("name") or "").strip()
                if _looks_like_title(n):
                    role_candidates.append((2, n))
            role_candidates.sort(key=lambda x: (x[0], len(x[1])), reverse=True)
            best_role = role_candidates[0][1] if role_candidates else None

            email = next((c.get("email") for c in group if c.get("email")), None)
            deduped.append({"name": best_name, "role": best_role, "email": email})

        tender.setdefault("tender_information", {})["contacts"] = deduped

    return result

_CRITICAL_FIELD_CHECKS = [
    # (dot-path into tender dict, human label, validator)
    ("tender_information.estimated_cost.amount",
     "total estimated project cost (number, e.g. 52546.85)",
     lambda v: v is not None and float(v) > 0),
    ("security_and_financials.emd.percentage",
     "EMD/bid security percentage of estimated cost (number, e.g. 1.0)",
     lambda v: v is not None and float(v) > 0),
    ("contract_conditions.completion_time_months",
     "project completion period in months (number, e.g. 24)",
     lambda v: v is not None and float(v) > 0),
    ("contract_conditions.liquidated_damages.rate_per_week_percent",
     "liquidated damages weekly rate as percentage (number, e.g. 0.15)",
     lambda v: v is not None and float(v) > 0),
    ("contract_conditions.defect_liability_period_months",
     "defect liability period in months (number, e.g. 12)",
     lambda v: v is not None and float(v) > 0),
]

def _normalize_unknowns(obj):
    """Recursively replace '<UNKNOWN>', 'UNKNOWN', 'N/A', 'TBD' placeholder strings
    with None so downstream code and the UI see clean nulls instead of junk strings.
    Arrays whose only item is a placeholder are collapsed to [].
    """
    _PLACEHOLDERS = {"<unknown>", "unknown", "n/a", "tbd", "<n/a>", "none", "null", ""}
    if isinstance(obj, dict):
        return {k: _normalize_unknowns(v) for k, v in obj.items()}
    if isinstance(obj, list):
        cleaned = [_normalize_unknowns(i) for i in obj]
        cleaned = [i for i in cleaned if i not in (None, "", [], {})]
        return cleaned
    if isinstance(obj, str) and obj.strip().lower() in _PLACEHOLDERS:
        return None
    return obj

def _get_nested(d: dict, path: str):
    for key in path.split("."):
        if not isinstance(d, dict):
            return None
        d = d.get(key)
    return d

def _set_nested(d: dict, path: str, value):
    keys = path.split(".")
    for key in keys[:-1]:
        d = d.setdefault(key, {})
    d[keys[-1]] = value

import re as _re

_FIELD_SYNONYMS = {
    "security_and_financials.emd.percentage": [
        "emd_percentage", "bid_security_percentage", "earnest_money_percentage",
        "security_deposit_rate", "emd_rate", "bid_security_rate",
    ],
    "security_and_financials.emd.max_cap_inr": [
        "emd_amount", "bid_security_amount", "earnest_money_amount",
        "maximum_emd", "emd_cap", "maximum_bid_security",
    ],
    "contract_conditions.completion_time_months": [
        "completion_time_months", "completion_time", "completion_period",
        "project_duration", "time_for_completion", "contract_period",
    ],
    "contract_conditions.defect_liability_period_months": [
        "defect_liability_months", "defect_liability_period_months", "dlp",
        "defect_liability", "maintenance_period",
    ],
    "contract_conditions.liquidated_damages.rate_per_week_percent": [
        "ld_rate_per_week_percent", "liquidated_damages_rate", "ld_rate",
        "delay_penalty_rate", "delay_damages", "ld_percentage",
    ],
    "contract_conditions.liquidated_damages.cap_percent": [
        "ld_cap_percent", "liquidated_damages_cap", "ld_cap",
        "maximum_ld", "maximum_liquidated_damages",
    ],
    "tender_information.estimated_cost.amount": [
        "estimated_cost_amount", "project_cost", "tender_value",
        "contract_value", "estimated_value",
    ],
}

def _extract_first_number(text: str):
    """Return the first float found in text, or None."""
    m = _re.search(r'\b(\d[\d,]*(?:\.\d+)?)\b', text)
    if m:
        return float(m.group(1).replace(",", ""))
    return None

def synonym_based_validation(synthesized: dict, merged_facts: dict) -> dict:
    """For each critical field that is null/zero in synthesized output,
    search merged_facts by synonym. No AI calls — runs on already-extracted text.
    Searches ALL extracted facts (not just first 10k chars).
    """
    import copy
    tender = (synthesized.get("tenders") or [{}])[0]
    missing = []
    for path, _label, is_valid in _CRITICAL_FIELD_CHECKS:
        val = _get_nested(tender, path)
        try:
            valid = is_valid(val)
        except (TypeError, ValueError):
            valid = False
        if not valid:
            missing.append(path)

    if not missing:
        print("[validation] All critical fields present.")
        return synthesized

    print(f"[validation] Searching merged facts by synonym for: {missing}")
    result   = copy.deepcopy(synthesized)
    tender_w = (result.get("tenders") or [{}])[0]
    patched  = 0

    for output_path in missing:
        synonyms = _FIELD_SYNONYMS.get(output_path, [])
        found_value = None
        for section_attrs in merged_facts.values():
            for attr, values in section_attrs.items():
                if attr in synonyms:
                    for v in values:
                        num = _extract_first_number(v)
                        if num is not None:
                            found_value = num
                            break
                if found_value is not None:
                    break
            if found_value is not None:
                break
        if found_value is not None:
            _set_nested(tender_w, output_path, found_value)
            print(f"[validation] Patched {output_path} = {found_value}")
            patched += 1

    # Infer price_variation.is_applicable when material rows were extracted
    pv_facts = merged_facts.get("PRICE_VARIATION", {})
    pv_has_materials = any(k.startswith("material_") and k.endswith("_name") for k in pv_facts)
    tender_pv = tender_w.get("price_variation")
    if pv_has_materials and isinstance(tender_pv, dict) and not tender_pv.get("is_applicable"):
        tender_pv["is_applicable"] = True
        print("[validation] Inferred price_variation.is_applicable = True from extracted material rows")
        patched += 1

    print(f"[validation] {patched} field(s) patched from synonym search.")
    return result

# ─────────────────────────────────────────────────────────────────────────────
# PASS 1.7 — TARGETED RETRIEVAL
# After synthesis, keyword-search the full PDF for critical missing fields and
# run a small focused AI call to recover each one. Only fires for gaps.
# ─────────────────────────────────────────────────────────────────────────────

def _extract_pdf_page_texts(pdf_path: str) -> list:
    reader = PdfReader(pdf_path)
    pages = []
    for i, page in enumerate(reader.pages, 1):
        text = (page.extract_text() or "").strip()
        if text:
            pages.append((i, text))
    return pages

def _top_pages(page_texts: list, keywords: list, n: int = 8) -> list:
    kw = [k.lower() for k in keywords]
    scored = sorted(
        ((sum(1 for k in kw if k in t.lower()), pn, t)
         for pn, t in page_texts if any(k in t.lower() for k in kw)),
        reverse=True,
    )
    return [(pn, t) for _, pn, t in scored[:n]]

def _deep_fill(target: dict, patch: dict):
    """Fill null/absent fields in target from patch. Never overwrites existing data."""
    for k, v in patch.items():
        if v in (None, [], {}):
            continue
        if k not in target or target[k] in (None, [], {}):
            target[k] = v
        elif isinstance(v, dict) and isinstance(target.get(k), dict):
            _deep_fill(target[k], v)
        elif isinstance(v, list) and isinstance(target.get(k), list) and not target[k]:
            target[k] = v

_RETRIEVAL_GROUPS = [
    {
        "name": "defect_liability",
        "check": lambda t: _get_nested(t, "contract_conditions.defect_liability_period_months") in (None, 0),
        "keywords": ["defect liability", "defect liab", "dlp", "maintenance period"],
        "max_pages": 6,
        "section_key": "contract_conditions",
        "prompt": (
            "Extract ONLY defect liability period details from the pages below.\n"
            'Return JSON: {"contract_conditions": {"defect_liability_period_months": <number or null>,'
            ' "defect_liability_from": "<string or null>"}}'
        ),
    },
    {
        "name": "payment_milestones",
        "check": lambda t: not _get_nested(t, "payment_terms.progressive_payments"),
        "keywords": ["advance", "payment", "milestone", "supply", "erection",
                     "progressive", "installment", "dispatch", "delivery"],
        "max_pages": 10,
        "section_key": "payment_terms",
        "prompt": (
            "Extract ALL payment terms from the pages below.\n"
            'Return JSON: {"payment_terms": {"advance_payments": [{"component": "...", '
            '"percentage": <number>, "conditions": ["..."]}], '
            '"progressive_payments": [{"component": "...", "milestone": "...", "percentage": <number>}], '
            '"standard_timeline_days": <number or null>, "delayed_interest_rate": "<string or null>"}}\n'
            "Capture EVERY milestone row. Percentages must be numbers."
        ),
    },
    {
        "name": "qualification_options",
        "check": lambda t: not _get_nested(t, "eligibility_and_qualification.technical.options"),
        "keywords": ["option a", "option b", "option c", "similar work",
                     "70%", "40%", "30%", "experience", "qualification criteria"],
        "max_pages": 8,
        "section_key": "eligibility_and_qualification",
        "prompt": (
            "Extract technical qualification options from the pages below.\n"
            'Return JSON: {"eligibility_and_qualification": {"technical": {"heading_note": "...", '
            '"options": [{"option": "A", "requirement": "..."}], '
            '"similar_works_definition": "..."}}}\n'
            "Quote requirements verbatim."
        ),
    },
    {
        "name": "financial_criteria",
        "check": lambda t: not _get_nested(t, "eligibility_and_qualification.financial"),
        "keywords": ["turnover", "maat", "average annual", "net worth", "liquid assets",
                     "solvency", "pending litigation", "financial capability"],
        "max_pages": 6,
        "section_key": "eligibility_and_qualification",
        "prompt": (
            "Extract financial eligibility criteria from the pages below.\n"
            'Return JSON: {"eligibility_and_qualification": {"financial": ['
            '{"criterion": "MAAT", "requirement": "..."}, ...]}}\n'
            "Capture MAAT, net worth, liquid assets, pending litigation."
        ),
    },
    {
        "name": "price_variation",
        "check": lambda t: not _get_nested(t, "price_variation.materials") and not _get_nested(t, "price_variation.composite_formula"),
        "keywords": ["price variation", "price adjustment", "escalation", "ieema"],
        "max_pages": 10,
        "section_key": "price_variation",
        "prompt": (
            "Extract ALL price variation and escalation details from the pages below.\n"
            'Return JSON: {"price_variation": {"is_applicable": true, "firm_components": ["..."], '
            '"variable_components": ["..."], "composite_formula": "...", '
            '"materials": [{"name": "...", "formula": "...", "index_source": "..."}]}}\n'
            "Capture COMPLETE formulas exactly as written. Extract EVERY material row."
        ),
    },
]

def targeted_retrieval(token_fn, API_URL: str, pdf_path: str, synthesized: dict) -> dict:
    """Pass 1.7 — keyword-search full PDF for critical missing fields;
    recover each with a focused AI call. Only fires for gaps, so it's
    effectively free when Pass 1 worked well."""
    import copy
    page_texts = _extract_pdf_page_texts(pdf_path)
    if not page_texts:
        return synthesized

    result = copy.deepcopy(synthesized)
    tender = (result.get("tenders") or [{}])[0]
    patched = 0

    for group in _RETRIEVAL_GROUPS:
        try:
            needs = group["check"](tender)
        except Exception:
            needs = True
        if not needs:
            continue

        print(f"[retrieval] '{group['name']}' missing — scanning {len(page_texts)} pages")
        pages = _top_pages(page_texts, group["keywords"], group["max_pages"])
        if not pages:
            print(f"[retrieval] '{group['name']}': no keyword hits in PDF")
            continue

        page_block = "\n\n---\n".join(f"[PAGE {pn}]\n{text}" for pn, text in pages)
        prompt = f"{group['prompt']}\n\nDOCUMENT PAGES:\n{page_block}"

        token = token_fn() if callable(token_fn) else token_fn
        payload = {
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 2000,
            "anthropic_version": "bedrock-2023-05-31",
        }
        try:
            raw = get_result(token, API_URL, payload, retries=2, timeout=120)
            patch = parse_ai_json(raw)
            sk = group["section_key"]
            if sk in patch and patch[sk]:
                _deep_fill(tender.setdefault(sk, {}), patch[sk])
                print(f"[retrieval] '{group['name']}': patched {sk}")
                patched += 1
        except Exception as e:
            print(f"[retrieval] '{group['name']}' error: {e}")

    print(f"[retrieval] {patched} section(s) recovered")
    return result


# ─────────────────────────────────────────────────────────────────────────────
# PASS 2.5 — CORRECTNESS VALIDATION
# Arithmetic and cross-field consistency checks. Logs warnings; does not
# modify data — a flagged issue is evidence to investigate, not auto-patch.
# ─────────────────────────────────────────────────────────────────────────────

def validate_correctness(synthesized: dict) -> dict:
    import re as _re3
    tender = (synthesized.get("tenders") or [{}])[0]
    issues = []

    pt = tender.get("payment_terms") or {}

    # 1. Payment milestone sum-to-100 per component group
    milestones = pt.get("progressive_payments") or []
    for label in ("supply", "erection"):
        rows = [r for r in milestones if label in (r.get("component") or "").lower()]
        if rows:
            total = sum(r.get("percentage") or 0 for r in rows)
            if abs(total - 100) > 0.5:
                issues.append(
                    f"{label.title()} milestones sum to {total}% (expected 100) — "
                    f"rows: {[r.get('percentage') for r in rows]} — likely truncation"
                )

    # 2. Advance headline % vs sum of installments mentioned in conditions
    for ap in (pt.get("advance_payments") or []):
        headline = ap.get("percentage")
        parts = []
        for cond in (ap.get("conditions") or []):
            cond_str = str(cond)
            cond_str = _re3.sub(r'(?i)\bbg\s*(?:of)?\s*\d+(?:\.\d+)?\s*%', '', cond_str)
            cond_str = _re3.sub(r'(?i)\d+(?:\.\d+)?\s*%\s*(?:of\s*)?(?:bg|bank guarantee)', '', cond_str)
            parts += [float(m) for m in _re3.findall(r'\b(\d+(?:\.\d+)?)\s*%', cond_str)]
        if headline and parts:
            inst_sum = sum(parts)
            if abs(inst_sum - headline) > 0.5:
                issues.append(
                    f"Advance {ap.get('component','?')}: headline={headline}% but "
                    f"installments sum to {inst_sum}% {parts}"
                )

    # 3. EMD cross-check: emd_percentage × estimated_cost ≈ emd_max_cap
    sf       = tender.get("security_and_financials") or {}
    emd      = sf.get("emd") or {}
    ec       = (tender.get("tender_information") or {}).get("estimated_cost") or {}
    emd_pct  = emd.get("percentage")
    emd_cap  = emd.get("max_cap_inr")
    ec_amt   = ec.get("amount")
    ec_denom = (ec.get("denomination") or "").lower()
    if emd_pct and emd_cap and ec_amt:
        ec_lakhs = ec_amt if ec_denom in ("lakhs", "lakh", "") else ec_amt * 100
        expected_inr = (emd_pct / 100) * ec_lakhs * 100000
        
        # If expected is less than the cap, then the cap is suspiciously high.
        # If expected is greater than the cap, that is exactly how a cap works.
        if expected_inr < emd_cap:
            ratio = abs(expected_inr - emd_cap) / max(expected_inr, emd_cap, 1)
            if ratio > 0.25:
                issues.append(
                    f"EMD: {emd_pct}% × {ec_amt} {ec_denom} = {expected_inr:,.0f} INR "
                    f"which is much less than emd_max_cap={emd_cap} INR"
                )

    for issue in issues:
        print(f"[correctness] ⚠  {issue}")
    if not issues:
        print("[correctness] All arithmetic checks passed.")
    return synthesized


# ─────────────────────────────────────────────────────────────────────────────
# SCHEMA COMPLETENESS
# Every required top-level section must be present in the output.
# Missing sections get a placeholder so the UI never sees a key-absent dict.
# ─────────────────────────────────────────────────────────────────────────────

_REQUIRED_SECTIONS = [
    "tender_information", "key_dates", "scope_of_work",
    "eligibility_and_qualification", "security_and_financials",
    "payment_terms", "price_variation", "contract_conditions",
    "technical_bid_documents",
]

def ensure_schema_completeness(synthesized: dict) -> dict:
    import copy
    result = copy.deepcopy(synthesized)
    for tender in result.get("tenders", []):
        for section in _REQUIRED_SECTIONS:
            if not tender.get(section):
                tender[section] = {"_status": "not_extracted"}
                print(f"[completeness] ⚠  Section '{section}' missing — added placeholder")
    return result


def _build_chat_messages(message, tender_id="", history=None):
    """Build a multi-turn messages array for the AI, including prior conversation turns.

    history: list of {"role": "user"|"assistant", "content": str} from the frontend.
    Capped at the last 20 entries (10 exchanges) to stay within token limits.
    System context is injected as a leading user/assistant exchange so it works
    with SAP AI Core's bedrock proxy regardless of top-level `system` support.
    """
    context = f" The user is asking about tender ID '{tender_id}'." if tender_id else ""
    system_line = (
        f"You are an AI assistant for tender document management.{context} "
        "Be concise and use prior conversation context to answer follow-up questions."
    )
    messages = [
        {"role": "user",      "content": f"[System] {system_line}"},
        {"role": "assistant", "content": "Understood. I'm ready to help."},
    ]
    for turn in (history or [])[-20:]:
        role    = turn.get("role", "")
        content = (turn.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": message})
    return messages


def generate_chat_response(token, API_URL, message, tender_id="", history=None):
    payload = {
        "messages": _build_chat_messages(message, tender_id, history),
        "max_tokens": 512,
        "anthropic_version": "bedrock-2023-05-31"
    }
    return get_result(token, API_URL, payload, retries=1, timeout=55)


def generate_chat_response_stream(token, API_URL, message, tender_id="", history=None):
    """Yields text chunks as they arrive from the AI Core streaming API."""
    payload = {
        "messages": _build_chat_messages(message, tender_id, history),
        "max_tokens": 512,
        "anthropic_version": "bedrock-2023-05-31",
        "stream": True,
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "AI-Resource-Group": "grounding",
    }
    with _session.post(API_URL, json=payload, headers=headers, stream=True, timeout=55) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines():
            if not line:
                continue
            line = line.decode("utf-8") if isinstance(line, bytes) else line
            if not line.startswith("data: "):
                continue
            data_str = line[6:]
            if data_str == "[DONE]":
                break
            try:
                data = json.loads(data_str)
                if data.get("type") == "content_block_delta":
                    text = data.get("delta", {}).get("text", "")
                    if text:
                        yield text
            except (json.JSONDecodeError, KeyError):
                continue
