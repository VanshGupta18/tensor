"""Invoice Extraction Service
---------------------------
Standalone service — not wired into the tender platform's cap-backend or
react-frontend. Extracts amount, PAN, and GSTIN from invoices (scanned PDFs or
photographed/scanned images) via a vision-capable LLM, then validates the result
deterministically (PAN/GSTIN format + checksum, amount arithmetic consistency).

Run: uv run uvicorn app:app --reload --port 8100
"""
import base64
import os

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from extraction.llm_client import extract_with_vision
from extraction.pdf_utils import extract_native_text, pdf_to_page_images
from extraction.schema import EXTRACTION_PROMPT, INVOICE_TOOL_SCHEMA
from extraction.validators import validate_extraction

load_dotenv()

API_URL = str(os.getenv("MODEL_BASE_URL", "")) + str(os.getenv("MODEL_ENDPOINT", ""))

MAX_UPLOAD_MB = 25
IMAGE_CONTENT_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/webp"}

app = FastAPI(title="Invoice Extraction Service")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/extract")
async def extract(file: UploadFile = File(...)):
    raw = await file.read()
    if len(raw) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"File too large. Maximum {MAX_UPLOAD_MB} MB allowed.")

    content_type = file.content_type or ""
    native_text = None
    images = []
    try:
        if content_type == "application/pdf" or (file.filename or "").lower().endswith(".pdf"):
            native_text = extract_native_text(raw)
            if not native_text:
                images = pdf_to_page_images(raw)
        elif content_type in IMAGE_CONTENT_TYPES:
            media_type = content_type if content_type != "image/jpg" else "image/jpeg"
            images = [{"media_type": media_type, "data": base64.b64encode(raw).decode("ascii")}]
        else:
            raise HTTPException(400, f"Unsupported file type: {content_type or 'unknown'}. Send a PDF or PNG/JPEG image.")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, f"Could not read file: {e}")

    if not images and not native_text:
        raise HTTPException(422, "No pages/images/text found in the uploaded file.")

    try:
        raw_result = extract_with_vision(API_URL, images, INVOICE_TOOL_SCHEMA, EXTRACTION_PROMPT, extracted_text=native_text)
    except Exception as e:
        raise HTTPException(502, f"Extraction failed: {e}")

    return JSONResponse(validate_extraction(raw_result))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=int(os.getenv("PORT", 8100)))
