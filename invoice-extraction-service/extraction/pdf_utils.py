"""PDF -> page images. No OCR — pages are rasterized and handed to the vision LLM
directly, which reads scanned/photographed invoices without a text layer."""
import base64

import fitz  # PyMuPDF

# 200 DPI keeps small print (PAN/GSTIN) legible without producing huge payloads.
RENDER_DPI = 150
MAX_PAGES = 3  # invoices are almost always 1-2 pages; cap to bound cost/latency


def pdf_to_page_images(pdf_bytes: bytes) -> list:
    """Returns a list of {"media_type": "image/png", "data": "<base64>"} — one per page,
    capped at MAX_PAGES (an invoice with more pages than that is almost certainly not
    a single invoice, or the extra pages are terms/annexures irrelevant to the fields
    this service extracts)."""
    images = []
    zoom = RENDER_DPI / 72  # PDF units are 72 DPI by default
    matrix = fitz.Matrix(zoom, zoom)
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        for page in doc:
            if len(images) >= MAX_PAGES:
                break
            pix = page.get_pixmap(matrix=matrix)
            png_bytes = pix.tobytes("png")
            images.append({
                "media_type": "image/png",
                "data": base64.b64encode(png_bytes).decode("ascii"),
            })
    return images


def extract_native_text(pdf_bytes: bytes) -> str | None:
    """Attempts to extract native digital text from the PDF.
    If the PDF is a flat scan, the text will be empty or very short.
    Returns the raw string if substantial digital text is found, else None."""
    extracted_text = []
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        for i, page in enumerate(doc):
            if i >= MAX_PAGES:
                break
            # Use 'blocks' or basic 'text' extraction. Basic 'text' preserves natural layout fairly well.
            page_text = page.get_text("text").strip()
            if page_text:
                extracted_text.append(f"--- PAGE {i+1} ---\n{page_text}")
                
    full_text = "\n\n".join(extracted_text)
    if len(full_text) > 100:  # arbitrary threshold to ensure it's actually digital text, not just a random stray character or watermark on a scan
        return full_text
    return None
