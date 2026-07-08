"""Structured-extraction tool schema and prompt for invoice fields.

Field layout mirrors the headerFields/lineItemFields convention used by the
platform's other PO-extraction schema (every leaf value wrapped in an object
with a `value` key), so downstream consumers can handle both the same way.
panNumber, bankAccountNumber/bankIfscCode, currencyCode, and taxRate aren't
part of that shared convention but are kept as extra headerFields — they're
what let `validators.py` checksum-verify PAN/GSTIN and cross-check
netAmount + taxAmount ≈ grossAmount.
"""


def _field(value_type, description):
    return {
        "type": "object",
        "properties": {"value": {"type": [value_type, "null"], "description": description}},
        "required": ["value"],
    }


INVOICE_TOOL_SCHEMA = {
    "name": "extract_invoice_fields",
    "description": "Extract header and line-item fields from an invoice image.",
    "input_schema": {
        "type": "object",
        "properties": {
            "headerFields": {
                "type": "object",
                "properties": {
                    "documentNumber": _field("string", "The invoice number printed on the document."),
                    "documentDate": _field("string", "The date of the invoice exactly as printed (e.g., DD/MM/YYYY, YYYY-MM-DD, or text)."),
                    "vendorName": _field("string", "The name of the vendor/supplier issuing the invoice."),
                    "buyerName": _field("string", "The name of the buyer/customer being billed."),
                    "buyerAddress": _field("string", "The billing address of the buyer/customer, if printed."),
                    "shipToName": _field("string", "The name of the party goods/services were shipped/delivered to, if different from the buyer."),
                    "shipToAddress": _field("string", "The delivery/shipping address, if printed."),
                    "purchaseOrderNumber": _field("string", "The Purchase Order (PO) or Work Order (WO) number. Often labelled 'PO', 'Work Order', or 'WO No'."),
                    "purchaseOrderDate": _field("string", "The date of the referenced Purchase Order, if printed."),
                    "gstNumber": _field("string", "The 15-character GSTIN printed on the invoice (the issuing party's, not the buyer's, unless only one is present)."),
                    "panNumber": _field("string", "The 10-character PAN printed on the invoice, if shown separately from the GSTIN."),
                    "currencyCode": _field("string", "e.g. INR, USD — from the symbol/code printed, not assumed."),
                    "netAmount": _field("number", "Amount before tax (subtotal / taxable value)."),
                    "taxAmount": _field("number", "Total tax charged (sum of CGST+SGST, or IGST, or GST as printed)."),
                    "taxRate": _field("number", "The GST percentage rate applied (e.g., 18 for 18%). Null if multiple rates apply or not clearly printed."),
                    "grossAmount": _field("number", "The final payable / grand total amount."),
                    "bankAccountNumber": _field("string", "Bank account number for payment, if printed."),
                    "bankIfscCode": _field("string", "The IFSC code or routing number for the bank branch, if printed."),
                },
                "required": [
                    "documentNumber", "documentDate", "vendorName", "buyerName", "buyerAddress",
                    "shipToName", "shipToAddress", "purchaseOrderNumber", "purchaseOrderDate",
                    "gstNumber", "panNumber", "currencyCode", "netAmount", "taxAmount", "taxRate",
                    "grossAmount", "bankAccountNumber", "bankIfscCode",
                ],
            },
            "lineItemFields": {
                "type": "array",
                "description": "One entry per invoice line item, in the order printed. Empty array if no itemized line table is present.",
                "items": {
                    "type": "object",
                    "properties": {
                        "description": _field("string", "The item/service description as printed."),
                        "materialNumber": _field("string", "The material/part number, if printed."),
                        "itemNumber": _field("string", "The line item number/serial number on the invoice."),
                        "quantity": _field("number", "The quantity billed for this line."),
                        "unitOfMeasure": _field("string", "The unit of measure (e.g. NOS, KG, HRS), if printed."),
                        "unitPrice": _field("number", "The per-unit price for this line."),
                        "netAmount": _field("number", "The line total before tax."),
                        "currencyCode": _field("string", "e.g. INR, USD, if printed per line."),
                    },
                    "required": [
                        "description", "materialNumber", "itemNumber", "quantity",
                        "unitOfMeasure", "unitPrice", "netAmount", "currencyCode",
                    ],
                },
            },
        },
        "required": ["headerFields", "lineItemFields"],
    },
}

EXTRACTION_PROMPT = (
    "This image is a page of a scanned invoice. Extract exactly what is printed — "
    "do not guess or infer a value that isn't legible. If a field isn't present or "
    "isn't clearly readable, return null for its value rather than a best guess. "
    "GSTIN is 15 characters (e.g. 27ABCDE1234F1Z5); PAN is 10 characters embedded "
    "within it (characters 3-12) or sometimes printed separately. Extract ship-to and "
    "buyer name/address, and purchase order number/date, exactly as they appear — look "
    "carefully for PO or Work Order numbers (often labelled 'PO', 'Work Order', or 'WO No'). "
    "For taxRate, extract the percentage number if a single GST rate applies. List every "
    "itemized line under lineItemFields in the order printed; return an empty array if the "
    "invoice has no line-item table. Use the tool to return the structured result."
)
