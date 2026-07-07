"""Deterministic validation of LLM-extracted fields.

The vision model reads the invoice; these checks catch misreads. None of this
requires a second LLM call — it's pure regex/checksum arithmetic, so it's free and
instant, and it's what makes the extraction "accurate" rather than just "plausible."
"""
import re
from datetime import datetime

PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")

# 4th character of a PAN encodes the holder type — useful as a soft sanity check.
PAN_HOLDER_TYPES = {
    "P": "Individual", "C": "Company", "H": "HUF", "F": "Firm/LLP",
    "A": "AOP", "T": "Trust", "B": "BOI", "L": "Local Authority",
    "J": "Artificial Judicial Person", "G": "Government",
}

# GST state codes currently in use (01-37 states/UTs, 97 other territory, 99 centre
# jurisdiction). Not exhaustive of every historical code, so an unknown code is
# flagged as a warning, not a hard failure.
_KNOWN_STATE_CODES = {f"{i:02d}" for i in range(1, 38)} | {"97", "99"}

_GSTIN_CODEPOINTS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _gstin_checksum_char(gstin_14: str) -> str:
    """Computes the 15th (check) character per the published GSTIN checksum algorithm."""
    factor = 1
    total = 0
    for ch in gstin_14:
        code = _GSTIN_CODEPOINTS.index(ch)
        product = factor * code
        total += (product // 36) + (product % 36)
        factor = 2 if factor == 1 else 1
    return _GSTIN_CODEPOINTS[(36 - (total % 36)) % 36]


def validate_pan(pan: str | None) -> dict:
    if not pan:
        return {"present": False, "format_valid": False}
    pan = pan.strip().upper()
    format_valid = bool(PAN_RE.match(pan))
    holder_type = PAN_HOLDER_TYPES.get(pan[3]) if format_valid else None
    
    if format_valid and not holder_type:
        format_valid = False

    return {
        "present": True,
        "value": pan,
        "format_valid": format_valid,
        "holder_type": holder_type,
    }


def validate_gstin(gstin: str | None) -> dict:
    if not gstin:
        return {"present": False, "format_valid": False}
    gstin = gstin.strip().upper()
    format_valid = bool(GSTIN_RE.match(gstin))
    if not format_valid:
        return {"present": True, "value": gstin, "format_valid": False}

    state_code = gstin[:2]
    embedded_pan = gstin[2:12]
    expected_check_char = _gstin_checksum_char(gstin[:14])
    checksum_valid = expected_check_char == gstin[14]

    return {
        "present": True,
        "value": gstin,
        "format_valid": True,
        "checksum_valid": checksum_valid,
        "state_code": state_code,
        "state_code_known": state_code in _KNOWN_STATE_CODES,
        "embedded_pan": embedded_pan,
    }


def cross_check_amounts(amount: dict) -> dict:
    """Flags an inconsistent total — e.g. the model misread one figure — by checking
    taxable_amount + tax_amount ≈ total_amount, when all three are present. Also checks
    if tax_rate * taxable_amount ≈ tax_amount."""
    taxable = amount.get("taxable_amount")
    tax = amount.get("tax_amount")
    total = amount.get("total_amount")
    rate = amount.get("tax_rate")
    
    result = {"checked": False}
    if taxable is not None and tax is not None and total is not None:
        diff = abs((taxable + tax) - total)
        result.update({"checked": True, "consistent": diff < 1.0, "difference": round(diff, 2)})
        
    if rate is not None and taxable is not None and tax is not None:
        expected_tax = taxable * (rate / 100.0)
        rate_diff = abs(expected_tax - tax)
        result.update({
            "rate_checked": True, 
            "rate_consistent": rate_diff < 1.0, 
            "rate_difference": round(rate_diff, 2)
        })
    else:
        result.update({"rate_checked": False})
        
    return result


def validate_invoice_date(date_str: str | None) -> dict:
    if not date_str:
        return {"present": False, "valid": False}
    date_str = date_str.strip()
    
    formats = [
        "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d.%m.%Y",
        "%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y"
    ]
    
    for fmt in formats:
        try:
            parsed = datetime.strptime(date_str, fmt)
            if 1990 <= parsed.year <= 2100:
                return {"present": True, "value": date_str, "valid": True, "parsed": parsed.strftime("%Y-%m-%d")}
        except ValueError:
            continue
            
    return {"present": True, "value": date_str, "valid": False}


def normalize_invoice_number(inv_num: str | None) -> dict:
    if not inv_num:
        return {"present": False}
    normalized = re.sub(r'\s+', ' ', inv_num).strip()
    return {"present": True, "value": normalized}


def validate_ifsc_code(ifsc: str | None) -> dict:
    if not ifsc:
        return {"present": False, "format_valid": False}
    ifsc = ifsc.strip().upper()
    format_valid = bool(IFSC_RE.match(ifsc))
    return {"present": True, "value": ifsc, "format_valid": format_valid}


def validate_extraction(result: dict) -> dict:
    """Runs all checks and attaches a `validation` block to the raw extraction,
    plus cross-checks the PAN against the GSTIN's embedded PAN when both are present.
    Also computes a confidence score."""
    pan_check = validate_pan(result.get("pan_number"))
    gstin_check = validate_gstin(result.get("gst_number"))
    amount_check = cross_check_amounts(result.get("amount") or {})
    date_check = validate_invoice_date(result.get("invoice_date"))
    inv_num_check = normalize_invoice_number(result.get("invoice_number"))
    po_num_check = normalize_invoice_number(result.get("po_number"))
    
    bank_details = result.get("bank_details") or {}
    acc_num_check = normalize_invoice_number(bank_details.get("account_number"))
    ifsc_check = validate_ifsc_code(bank_details.get("ifsc_code"))

    pan_gstin_match = None
    if pan_check.get("format_valid") and gstin_check.get("format_valid"):
        pan_gstin_match = pan_check["value"] == gstin_check["embedded_pan"]

    # Simple Confidence Scoring
    score = 100
    
    if gstin_check.get("present"):
        if not gstin_check.get("format_valid"): score -= 20
        elif not gstin_check.get("checksum_valid"): score -= 30
    
    if pan_check.get("present"):
        if not pan_check.get("format_valid"): score -= 20
        
    if pan_gstin_match is False:
        score -= 40
        
    if amount_check.get("checked") and not amount_check.get("consistent"):
        score -= 30
        
    if amount_check.get("rate_checked") and not amount_check.get("rate_consistent"):
        score -= 20
        
    if date_check.get("present") and not date_check.get("valid"):
        score -= 10
        
    if ifsc_check.get("present") and not ifsc_check.get("format_valid"):
        score -= 15
        
    score = max(0, score)

    return {
        **result,
        "vendor_name": (result.get("vendor_name") or "").strip() or None,
        "buyer_name": (result.get("buyer_name") or "").strip() or None,
        "validation": {
            "pan": pan_check,
            "gstin": gstin_check,
            "amount_consistency": amount_check,
            "invoice_date": date_check,
            "invoice_number": inv_num_check,
            "po_number": po_num_check,
            "bank_details": {
                "account_number": acc_num_check,
                "ifsc_code": ifsc_check,
            },
            "pan_matches_gstin": pan_gstin_match,
            "confidence_score": score
        },
    }
