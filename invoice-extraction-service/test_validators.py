import os
import json
import asyncio
from extraction.pdf_utils import pdf_to_page_images
from extraction.llm_client import extract_with_vision
from extraction.schema import INVOICE_TOOL_SCHEMA, EXTRACTION_PROMPT
from extraction.validators import validate_extraction
from app import API_URL

pdf_path = "/Users/vanshgupta/Downloads/tensor/docs/KC0073.pdf"

print(f"\n--- Testing {os.path.basename(pdf_path)} ---", flush=True)
try:
    with open(pdf_path, "rb") as f:
        raw = f.read()
    print("Converting to images...", flush=True)
    images = pdf_to_page_images(raw)
    print(f"Extracted {len(images)} images. Calling LLM...", flush=True)
    raw_result = extract_with_vision(API_URL, images, INVOICE_TOOL_SCHEMA, EXTRACTION_PROMPT)
    print("LLM returned, validating...", flush=True)
    final_result = validate_extraction(raw_result)
    print(f"Result: {json.dumps(final_result, indent=2)}", flush=True)
except Exception as e:
    print(f"Error: {e}", flush=True)
