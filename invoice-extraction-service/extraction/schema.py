"""Structured-extraction tool schema and prompt for invoice fields.

Scope is deliberately narrow — amount, PAN, GSTIN — per what was asked. The
taxable/tax sub-fields under `amount` aren't a separate ask; they exist purely so
`validators.py` can cross-check taxable_amount + tax_amount ≈ total_amount, catching
a misread total the same way GSTIN-embeds-PAN catches a misread PAN/GSTIN.
"""

INVOICE_TOOL_SCHEMA = {
    "name": "extract_invoice_fields",
    "description": "Extract amount, PAN, GSTIN, invoice date, invoice number, vendor name, buyer name, PO number, and bank details from an invoice image.",
    "input_schema": {
        "type": "object",
        "properties": {
            "vendor_name": {
                "type": ["string", "null"],
                "description": "The name of the vendor/supplier issuing the invoice. Null if not visible.",
            },
            "buyer_name": {
                "type": ["string", "null"],
                "description": "The name of the buyer/customer being billed. Null if not visible.",
            },
            "po_number": {
                "type": ["string", "null"],
                "description": "The Purchase Order (PO) or Work Order (WO) number. Null if not visible.",
            },
            "invoice_number": {
                "type": ["string", "null"],
                "description": "The invoice number printed on the document. Null if not visible.",
            },
            "invoice_date": {
                "type": ["string", "null"],
                "description": "The date of the invoice exactly as printed (e.g., DD/MM/YYYY, YYYY-MM-DD, or text). Null if not visible.",
            },
            "gst_number": {
                "type": ["string", "null"],
                "description": "The 15-character GSTIN printed on the invoice (the issuing party's, not the buyer's, unless only one is present). Null if not visible.",
            },
            "pan_number": {
                "type": ["string", "null"],
                "description": "The 10-character PAN printed on the invoice, if shown separately from the GSTIN. Null if not visible.",
            },
            "amount": {
                "type": "object",
                "properties": {
                    "currency": {"type": ["string", "null"], "description": "e.g. INR, USD — from the symbol/code printed, not assumed."},
                    "taxable_amount": {"type": ["number", "null"], "description": "Amount before tax (subtotal / taxable value)."},
                    "tax_amount": {"type": ["number", "null"], "description": "Total tax charged (sum of CGST+SGST, or IGST, or GST as printed)."},
                    "tax_rate": {"type": ["number", "null"], "description": "The GST percentage rate applied (e.g., 18 for 18%). Null if multiple rates apply or not clearly printed."},
                    "total_amount": {"type": ["number", "null"], "description": "The final payable / grand total amount."},
                },
                "required": ["total_amount"],
            },
            "bank_details": {
                "type": ["object", "null"],
                "properties": {
                    "account_number": {"type": ["string", "null"], "description": "Bank account number for payment."},
                    "ifsc_code": {"type": ["string", "null"], "description": "The IFSC code or routing number for the bank branch."},
                },
                "description": "Bank account and IFSC code details if printed for payment.",
            }
        },
        "required": ["vendor_name", "buyer_name", "po_number", "invoice_number", "invoice_date", "gst_number", "pan_number", "amount", "bank_details"],
    },
}

EXTRACTION_PROMPT = (
    "This image is a page of a scanned invoice. Extract exactly what is printed — "
    "do not guess or infer a value that isn't legible. If a field isn't present or "
    "isn't clearly readable, return null for it rather than a best guess. "
    "GSTIN is 15 characters (e.g. 27ABCDE1234F1Z5); PAN is 10 characters embedded "
    "within it (characters 3-12) or sometimes printed separately. Extract the invoice number, date, "
    "vendor name, buyer name, and bank details exactly as they appear. Look carefully for PO or Work Order "
    "numbers (often labelled 'PO', 'Work Order', or 'WO No'). For tax_rate, extract the percentage number "
    "if a single GST rate applies. Use the tool to return the structured result."
)
