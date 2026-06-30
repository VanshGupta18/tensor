import os
import json
from dotenv import load_dotenv

load_dotenv()

from functions import (
    get_access_token,
    split_pdf,
    extract_facts_from_chunks,
    merge_chunk_facts,
    synthesize_final_json,
    synonym_based_validation,
    targeted_retrieval,
    validate_correctness,
    ensure_schema_completeness,
    _has_text
)
from pdf_generator import generate_tender_pdf

CREDENTIALS = {
    "TOKEN_URL":      os.getenv("TOKEN_URL"),
    "CLIENT_ID":      os.getenv("CLIENT_ID"),
    "CLIENT_SECRET":  os.getenv("CLIENT_SECRET"),
}
API_URL = str(os.getenv("MODEL_BASE_URL", "")) + str(os.getenv("MODEL_ENDPOINT", ""))

def test_pipeline():
    pdf_path = "/Users/vanshgupta/Downloads/tensor/docs/SBD ROBUST-III MBAD (003).pdf"
    print(f"Processing {pdf_path}")
    
    is_text_pdf = _has_text(pdf_path)
    pages_per_chunk = 30 if is_text_pdf else 15
    chunk_overlap = 2 if is_text_pdf else 0
    file_path_list = split_pdf(pdf_path, pages_per_chunk, chunk_overlap)
    print(f"Split into {len(file_path_list)} chunks.")

    def get_token():
        return get_access_token(CREDENTIALS)
    
    token = get_token()
    chunk_texts = extract_facts_from_chunks(get_token, API_URL, file_path_list)
    merged_facts = merge_chunk_facts(chunk_texts)
    
    final_json = synthesize_final_json(token, API_URL, merged_facts)
    final_json = synonym_based_validation(final_json, merged_facts)
    final_json = targeted_retrieval(get_token, API_URL, pdf_path, final_json)
    final_json = validate_correctness(final_json)
    final_json = ensure_schema_completeness(final_json)
    
    raw_tenders = final_json.get("tenders", [])
    if raw_tenders:
        tender = raw_tenders[0]
        pdf_bytes = generate_tender_pdf(tender, doc_title="Tender Synopsis")
        out_pdf = "/Users/vanshgupta/Downloads/tensor/docs/output_test.pdf"
        with open(out_pdf, "wb") as f:
            f.write(pdf_bytes)
        print(f"Generated PDF saved to {out_pdf}")
    else:
        print("No tender found!")

if __name__ == "__main__":
    test_pipeline()
