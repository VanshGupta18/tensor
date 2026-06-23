import requests
import os
import copy
import base64
from io import BytesIO
from pypdf import PdfReader, PdfWriter
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import fitz  # pymupdf — for rendering image-based PDF pages
    _FITZ_AVAILABLE = True
except ImportError:
    _FITZ_AVAILABLE = False

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

        output_file = os.path.join(
            output_folder,
            f"{pdf_name}_part_{start_page // pages_per_file + 1}.pdf"
        )
        file_names_list.append(output_file)

        with open(output_file, "wb") as f:
            writer.write(f)

    return file_names_list


def parse_ai_json(ai_text: str) -> dict:
    # Remove ```json ... ``` or ``` ... ```
    cleaned = re.sub(r"^```json\s*|^```\s*|```$", "", ai_text.strip(), flags=re.MULTILINE)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON from AI: {e}\n\nRaw:\n{cleaned}")

def get_access_token(cred):
    data1 = {
        "grant_type": "client_credentials",
    }
    resp = requests.post(
        cred["TOKEN_URL"],
        data=data1,
        auth=(cred["CLIENT_ID"], cred["CLIENT_SECRET"]),
        timeout=300,
    )
    resp.raise_for_status()
    token_payload = resp.json()
    return token_payload["access_token"]
def get_or_create_section(result_dict, section_name):

    sections = result_dict.setdefault("sections", [])

    for section in sections:
        if section.get("heading") == section_name:
            return result_dict,section

    new_section = {
        "heading": section_name,
        "sub_headings": []
    }

    sections.append(new_section)
    result_dict["sections"] = sections
    return result_dict,new_section

def get_result(token, API_URL, payload):
    """
    Generic LLM call that prepends chat history to the payload messages.
    NOTE: token expected to be a tuple (access_token, expires_in) → we use token[0].
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "AI-Resource-Group": "grounding",
    }
    
    try:
        resp = requests.post(API_URL, json=payload, headers=headers, timeout=600)
        resp.raise_for_status()
        print("result generate")
    except requests.exceptions.HTTPError as e:
        print("HTTPError:", str(e))
        raise
    return (resp.json())["content"][0]["text"]


def reading_file(file_path):
    with open(file_path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("utf-8")
    return encoded

def generate_payload(encoded, summary):
    prompt = f"""
            You are a strict data extraction system. You are not permitted to generate, infer, estimate, normalize, round off, or assume any values.

            INPUTS:
            1. Existing "summary" JSON (may be partially populated from previous documents)
            2. A new document (PDF)

            OBJECTIVE:
            Update the summary JSON strictly using values explicitly present in the document.

            MANDATORY RULES:

            1. Exact Extraction Only
            - Extract values only if they are explicitly and clearly present in the document.
            - Copy values exactly as they appear, preserving original format, units, wording, and formatting wherever possible.
            - Do not rephrase extracted content.
            - Do not convert values into different formats.

            2. No Guessing or Inference
            - Do not calculate, derive, estimate, or infer values.
            - Do not round numbers.
            - Do not approximate quantities.
            - Do not assume missing information.
            - Do not complete partially available values.
            - Do not expand abbreviations unless explicitly defined in the document.
            - Do not infer values from context or similar fields.

            3. No Overwriting of Existing Data
            - If a field already contains a value, do not replace it.
            - Existing values must remain unchanged.

            4. Controlled Enrichment
            - If a field already contains information and the document contains additional explicit information relevant to the same field:
            - Append the new information.
            - Preserve all existing content.
            - Do not rewrite or summarize existing content.
            - Use a semicolon, newline, or other clear separator.

            5. No Data Fabrication
            - If the document does not explicitly contain a value for a field, leave that field unchanged.
            - Do not insert placeholders.
            - Do not insert default values.
            - Do not generate missing content.

            6. Special Rule for "components" and "materials"
            - These fields are domain dependent.
            - Do not assume predefined categories or subfields.
            - Do not create additional JSON structure under these fields.
            - Extract all explicitly available information related to components or materials.
            - Preserve maximum factual detail.
            - Capture names, descriptions, quantities, specifications, capacities, formulae, clauses, schedules, references and requirements.
            - Do not invent categories.

            7. Token Management and Controlled Compression

            The response must always contain a complete and valid JSON object.

            If summary size and extracted data approach output token limits:

            High Priority Fields (Never Compress Unless Absolutely Necessary)
            - tender_information
            - key_dates
            - eligibility_criteria
            - bid_security_financials
            - payment_terms
            - contract_conditions

            Requirements:
            - Preserve all dates.
            - Preserve all numbers.
            - Preserve all percentages.
            - Preserve all identifiers.
            - Preserve all names.
            - Preserve all formulas.
            - Preserve all financial information.
            - Preserve all contractual information.

            Medium Priority Fields
            - technical_bid_documents
            - price_variation.rules
            - disclaimer

            Requirements:
            - Preserve all factual information.
            - Remove only repetitive wording if required.

            Low Priority Fields
            - scope_of_work.components
            - price_variation.materials

            Requirements:
            - If token budget is constrained, reduce repetitive narrative text.
            - Preserve:
            - material names
            - component names
            - quantities
            - capacities
            - ratings
            - specifications
            - percentages
            - dates
            - formulas
            - codes
            - identifiers
            - references

            Compression Rules:
            - Preserve facts.
            - Reduce verbosity only when necessary.
            - Never remove factual information.
            - Never remove figures.
            - Never remove amounts.
            - Never remove dates.
            - Never remove specifications.
            - Never replace facts with generic summaries.

            Completeness Rules:
            - Complete valid JSON is mandatory.
            - Never return partial JSON.
            - Never truncate JSON.
            - Never cut fields mid-sentence.
            - Never cut strings, objects, or arrays.

            8. Structure Integrity
            - Maintain the exact JSON structure.
            - Do not add keys.
            - Do not remove keys.
            - Do not rename keys.
            - Populate only existing fields.

            9. Output Format
            - Return only the updated JSON.
            - No explanations.
            - No comments.
            - No markdown.
            - No text outside JSON.

            MULTI-DOCUMENT CONTEXT

            - Processing occurs across multiple documents.
            - Existing data may already be populated.
            - Only add missing information.
            - Only append explicit additional details.
            - Never overwrite existing extracted values.

            FIELD DEFINITIONS (For Understanding Only - Not For Inference)

            {{
            "tender_information": {{
                "tender_title": "Exact tender name",
                "tender_no": "Tender number, tender reference, RFP number, NIT number or procurement identifier",
                "version": "Version number, amendment number or revision number",
                "date_of_issue": "Issue date or publication date",
                "issuing_authority": "Authority or organization issuing the tender",
                "tender_type": "Works, supply, services, consultancy, EPC, turnkey or other type",
                "bid_type": "Single stage, two stage, envelope system or procurement methodology",
                "funding_agency": "Funding source or financing institution",
                "estimated_cost": "Estimated project cost, tender value or contract value",
                "tender_fee": "Bid fee, tender fee or document fee",
                "budget_type": "CAPEX, OPEX or other budget classification",
                "scheme": "Project scheme, program or initiative name",
                "contact_details": {{
                "name": "Contact person name",
                "designation": "Contact designation",
                "mobile": "Mobile number",
                "email": "Email address"
                }}
            }},
            "key_dates": {{
                "release_date": "Tender release date",
                "pre_bid_meeting": "Pre-bid meeting information",
                "bid_submission_deadline": "Bid submission deadline",
                "technical_opening_date": "Technical bid opening date",
                "financial_opening_date": "Financial bid opening date"
            }},
            "scope_of_work": {{
                "type": "Project type",
                "location": "Project location",
                "components": "Detailed scope components"
            }},
            "experience_requirements": {{
                "turnover": "Average Annual Turnover (AAT) requirements",
                "projects": "Specific project experience requirements"
            }},
            "financial_requirements": {{
                "maat": "Minimum Average Annual Turnover (MAAT)",
                "liquid_assets": "Liquid Assets or Credit Facility details",
                "pending_litigation": "Pending Litigation constraints"
            }},
            "jv_requirements": "Joint Venture capacity/share allocations for lead and partner entities",
            "eligibility_criteria": {{
                "technical": "Technical qualification requirements",
                "financial": "Financial qualification requirements",
                "other_conditions": "Other eligibility conditions"
            }},
            "bid_security_financials": {{
                "emd": "Bid security or EMD",
                "bank_details": {{
                "beneficiary_name": "Beneficiary name",
                "bank_name": "Bank name",
                "account_number": "Bank account number",
                "ifsc_code": "IFSC or banking code"
                }},
                "bid_validity": "Bid validity period",
                "performance_security": "Performance security",
                "cpg_supply": "Supply guarantee",
                "cpg_erection": "Erection guarantee"
            }},
            "payment_terms": {{
                "advance_payment": "Advance payment provisions",
                "progressive_payments": "Milestone or progressive payments",
                "payment_timeline": "Payment schedule",
                "interest_on_delay": "Delayed payment provisions"
            }},
            "price_variation": {{
                "applicability": "Applicability of price variation",
                "materials": "Detailed material escalation information",
                "rules": "Price variation rules"
            }},
            "contract_conditions": {{
                "completion_time": "Project duration",
                "defect_liability_period": "DLP or warranty period",
                "liquidated_damages": "Delay penalties",
                "quality_penalties": "Penalties for quality issues",
                "tpqma_inspection": "Third Party Quality Monitoring Agency inspection details",
                "gis_asset_tagging": "GIS / Asset Tagging requirements",
                "works_license": "Electrical or works license requirements",
                "subcontracting": "Rules for subcontracting",
                "other_conditions": "Other contractual conditions"
            }},
            "technical_bid_documents": {{
                "required_documents": "Required bid documents",
                "declarations": "Declarations and undertakings",
                "other_requirements": "Additional requirements"
            }},
            "disclaimer": "Disclaimers or notes"
            }}

            Existing Summary JSON:

            {summary}

            FINAL OUTPUT:
            Return only the updated JSON object.
            """

    return {
        "messages": [
            {
                "role": "user",
                "content": prompt
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": encoded
                        }
                    }
                ]
            }
        ],
        "max_tokens": 4000,
        "anthropic_version": "bedrock-2023-05-31"
    }

def generate_payload_result(summary):
    payload = {
        "messages": [
            {
                "role": "user",
                "content": f"""
                    You are a strict JSON transformation system.

                    INPUT:
                    A summary JSON containing extracted document information.

                    OBJECTIVE:

                    Transform the provided summary JSON into a structured JSON object that may represent
                    ONE or MULTIPLE distinct tenders found in the document.

                    STRICT RULES:

                    1. No Content Generation
                    - Do not generate new facts, values, explanations, summaries, or assumptions.
                    - Use only information already present in the provided summary JSON.

                    2. Preserve Values Exactly
                    - Do not modify, summarize, paraphrase, or translate values.
                    - Do not change dates, numbers, names, units, currencies, percentages, codes, or identifiers.

                    3. Tender Detection
                    - Examine tender_information.tender_no to determine if multiple distinct tenders exist.
                    - A new tender is identified by a distinct tender_no value.
                    - If the document contains ONE tender: return array with exactly one element.
                    - If the document contains MULTIPLE distinct tenders: return one element per tender.
                    - If NO tender information is found: return an empty tenders array.

                    4. Per-Tender Structure
                    - Each tender element uses the same sections structure.
                    - Top-level JSON keys are treated as document sections.
                    - Nested JSON keys are treated as sub-sections.

                    5. Empty Fields
                    - Exclude fields having "", null, empty object, or empty array.
                    - Include only sections containing meaningful information.

                    6. Output Structure

                    Return exactly this JSON object:

                    {{
                    "tenders": [
                        {{
                        "document_title": "",
                        "sections": [
                            {{
                            "heading": "",
                            "content": "",
                            "sub_headings": []
                            }}
                        ]
                        }}
                    ]
                    }}

                    Rules:
                    - document_title = Use the tender title if available, otherwise "Tender Document".
                    - If NO tender information found: return {{ "tenders": [] }}
                    - Output valid JSON only. No markdown. No explanations. No text outside JSON.

                    Example Output (single tender):

                    {{
                    "tenders": [
                        {{
                        "document_title": "Construction of Substation",
                        "sections": [
                            {{
                            "heading": "tender_information",
                            "sub_headings": [
                                {{
                                "heading": "tender_title",
                                "content": "Construction of Substation"
                                }},
                                {{
                                "heading": "tender_no",
                                "content": "ABC123"
                                }}
                            ]
                            }},
                            {{
                            "heading": "key_dates",
                            "sub_headings": [
                                {{
                                "heading": "release_date",
                                "content": "19 May 2026"
                                }}
                            ]
                            }}
                        ]
                        }}
                    ]
                    }}

                    Summary JSON:

                    {summary}

                    FINAL OUTPUT:
                    Return only the JSON object with the "tenders" array.
                    """
            }
        ],
        "max_tokens": 4000,
        "anthropic_version": "bedrock-2023-05-31"
    }

    return payload

import json
def add_subheading(result_dict,section, heading, content):
    if not content or not str(content).strip():
        content = " "

    sub_headings = section.setdefault(
        "sub_headings",
        []
    )

    sub_headings.append(
        {
            "heading": heading,
            "content": str(content)
        }
    )
    section_heading=section["heading"]
    for i in range(0,len(result_dict["sections"])):
        if result_dict["sections"][i]["heading"]==section_heading:
            result_dict["sections"][i]["sub_headings"] = sub_headings
            return result_dict

    return result_dict

# Fields whose values are concatenated across chunks (instead of first-wins)
_ACCUMULATE_KEYS = {
    "scope_of_work.components",
    "experience_requirements.projects",
    "jv_requirements",
    "eligibility_criteria.technical",
    "eligibility_criteria.financial",
    "eligibility_criteria.other_conditions",
    "price_variation.materials",
    "contract_conditions.other_conditions",
    "technical_bid_documents.required_documents",
    "technical_bid_documents.declarations",
    "technical_bid_documents.other_requirements",
}

_EMPTY_SUMMARY = {
    "tender_information": {
        "tender_title": "", "tender_no": "", "version": "", "date_of_issue": "",
        "issuing_authority": "", "tender_type": "", "bid_type": "", "funding_agency": "",
        "estimated_cost": "", "tender_fee": "", "budget_type": "", "scheme": "",
        "contact_details": {"name": "", "designation": "", "mobile": "", "email": ""}
    },
    "key_dates": {
        "release_date": "", "pre_bid_meeting": "", "bid_submission_deadline": "",
        "technical_opening_date": "", "financial_opening_date": ""
    },
    "scope_of_work":        {"type": "", "location": "", "components": ""},
    "experience_requirements": {"turnover": "", "projects": ""},
    "financial_requirements": {"maat": "", "liquid_assets": "", "pending_litigation": ""},
    "jv_requirements": "",
    "eligibility_criteria": {"technical": "", "financial": "", "other_conditions": ""},
    "bid_security_financials": {
        "emd": "",
        "bank_details": {"beneficiary_name": "", "bank_name": "", "account_number": "", "ifsc_code": ""},
        "bid_validity": "", "performance_security": "", "cpg_supply": "", "cpg_erection": ""
    },
    "payment_terms": {
        "advance_payment": "", "progressive_payments": "", "payment_timeline": "", "interest_on_delay": ""
    },
    "price_variation":      {"applicability": "", "materials": "", "rules": ""},
    "contract_conditions":  {
        "completion_time": "", "defect_liability_period": "", "liquidated_damages": "", "quality_penalties": "",
        "tpqma_inspection": "", "gis_asset_tagging": "", "works_license": "", "subcontracting": "",
        "other_conditions": ""
    },
    "technical_bid_documents": {"required_documents": "", "declarations": "", "other_requirements": ""},
    "disclaimer": ""
}


def _merge_into(base, update, accumulated, prefix=""):
    """Merge update into base in-place. First non-empty wins for normal fields;
    accumulate fields are collected separately."""
    for key, val in update.items():
        dot_key = f"{prefix}.{key}" if prefix else key
        if isinstance(val, dict):
            if not isinstance(base.get(key), dict):
                base[key] = {}
            _merge_into(base[key], val, accumulated, dot_key)
        else:
            if dot_key in _ACCUMULATE_KEYS:
                if val and str(val).strip():
                    v = str(val).strip()
                    if v not in accumulated[dot_key]:
                        accumulated[dot_key].append(v)
            else:
                # First non-empty value wins
                if not base.get(key) and val and str(val).strip():
                    base[key] = val


def _has_text(file_path: str) -> bool:
    """Return True if the PDF has a selectable text layer."""
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
    """Render each PDF page as a base64 JPEG using pymupdf."""
    if not _FITZ_AVAILABLE:
        raise RuntimeError("pymupdf not installed — cannot process image-based PDF")
    doc = fitz.open(file_path)
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    images = []
    for i, page in enumerate(doc):
        if i >= max_pages:
            break
        pix = page.get_pixmap(matrix=mat)
        img_bytes = pix.tobytes("jpeg", jpg_quality=75)
        images.append(base64.b64encode(img_bytes).decode("utf-8"))
    return images


def generate_payload_vision(images_b64: list, summary: str) -> dict:
    """
    Build an extraction payload that sends PDF pages as images.
    Used when the PDF has no text layer (scanned / image-based).
    Prompt + images are combined in ONE user message so Claude can
    actually see the pages (two consecutive user messages would cause
    the document to be silently ignored by the API).
    """
    prompt_text = f"""
You are a strict data extraction system. You are not permitted to generate, infer, estimate, normalize, round off, or assume any values.

Extract values ONLY if they are explicitly and clearly present in the provided page images.
Copy values exactly as they appear, preserving original format, units, wording, and formatting wherever possible.

MANDATORY RULES:
1. Exact Extraction Only — do not rephrase, convert formats, or abbreviate.
2. No Guessing or Inference — if a field is not visible, leave it as empty string.
3. No Data Fabrication — do not insert placeholders or default values.
4. Structure Integrity — maintain the exact JSON structure, do not add or remove keys.
5. Output Format — return ONLY the updated JSON object, no markdown, no explanations.

FIELD DEFINITIONS (populate only if explicitly present in images):

tender_information.tender_title, tender_no, version, date_of_issue, issuing_authority,
tender_type, bid_type, funding_agency, estimated_cost, tender_fee, budget_type, scheme,
contact_details (name, designation, mobile, email)

key_dates: release_date, pre_bid_meeting, bid_submission_deadline, technical_opening_date, financial_opening_date

scope_of_work: type, location, components
experience_requirements: turnover, projects
financial_requirements: maat, liquid_assets, pending_litigation
jv_requirements
eligibility_criteria: technical, financial, other_conditions
bid_security_financials: emd, bank_details (beneficiary_name, bank_name, account_number, ifsc_code), bid_validity, performance_security, cpg_supply, cpg_erection
payment_terms: advance_payment, progressive_payments, payment_timeline, interest_on_delay
price_variation: applicability, materials, rules
contract_conditions: completion_time, defect_liability_period, liquidated_damages, quality_penalties, tpqma_inspection, gis_asset_tagging, works_license, subcontracting, other_conditions
technical_bid_documents: required_documents, declarations, other_requirements
disclaimer

Existing Summary JSON (update it, do not overwrite existing non-empty values):
{summary}

FINAL OUTPUT: Return only the updated JSON object.
"""
    content = [{"type": "text", "text": prompt_text}]
    for img_b64 in images_b64:
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": img_b64}
        })
    return {
        "messages": [{"role": "user", "content": content}],
        "max_tokens": 4000,
        "anthropic_version": "bedrock-2023-05-31"
    }


def _call_chunk(args):
    """Process a single PDF chunk. Auto-detects text vs image PDF. Runs in a thread."""
    token, API_URL, file_path = args
    summary_str = json.dumps(_EMPTY_SUMMARY, indent=2, ensure_ascii=False)

    if _has_text(file_path):
        # Text-based PDF — send as base64 document
        encoded = reading_file(file_path)
        payload = generate_payload(encoded, summary_str)
    else:
        # Image-based PDF (scanned) — render pages and send as images
        print(f"[image PDF detected] {os.path.basename(file_path)} — using vision extraction")
        images_b64 = _render_pages_as_images(file_path)
        payload = generate_payload_vision(images_b64, summary_str)

    result = get_result(token, API_URL, payload)
    print(f"[chunk done] {os.path.basename(file_path)}")
    return parse_ai_json(result)


def generate_summary(token, API_URL, file_path_list):
    accumulated = {k: [] for k in _ACCUMULATE_KEYS}
    merged = copy.deepcopy(_EMPTY_SUMMARY)

    # Process all chunks in parallel — wall-clock time = slowest single chunk
    max_workers = min(len(file_path_list), 5)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_call_chunk, (token, API_URL, fp)): fp
            for fp in file_path_list
        }
        for future in as_completed(futures):
            try:
                chunk_result = future.result()
                _merge_into(merged, chunk_result, accumulated)
            except Exception as e:
                print(f"[chunk error] {futures[future]}: {e}")

    # Restore concatenated fields
    for dot_key, values in accumulated.items():
        if '.' in dot_key:
            section, field = dot_key.split('.', 1)
            merged[section][field] = "\n\n".join(values)
        else:
            merged[dot_key] = "\n\n".join(values)

    return json.dumps(merged, indent=4, ensure_ascii=False)

def generate_result(token, API_URL,summary):
    payload=generate_payload_result(summary)
    result=get_result(token,API_URL,payload)
    print(result)
    return result


def generate_chat_response(token, API_URL, message, tender_id=""):
    context = f" The user is asking about tender '{tender_id}'." if tender_id else ""
    prompt = (
        f"You are an AI assistant helping with tender document management.{context}\n\n"
        f"User question: {message}\n\n"
        "Please provide a helpful, concise answer. "
        "If the question is about a specific tender, answer based on general tender management knowledge "
        "since you may not have the specific document. "
        "Keep your response under 300 words."
    )
    payload = {
        "messages": [
            {
                "role": "user",
                "content": prompt
            }
        ],
        "max_tokens": 1024,
        "anthropic_version": "bedrock-2023-05-31"
    }
    return get_result(token, API_URL, payload)
