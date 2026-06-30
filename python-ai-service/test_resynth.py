"""
Quick re-synthesis test — skips Pass 1 by reloading saved raw_facts from test_result.json's
sibling raw file, then re-runs Pass 2 + Pass 2.5 to verify _normalize_unknowns fix.
"""
import json, os, sys, time
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()
sys.path.insert(0, str(Path(__file__).parent))

from functions import (
    get_access_token, extract_facts_from_chunks,
    synthesize_final_json, confidence_gated_reextract,
    _normalize_unknowns,
)

CREDENTIALS = {
    "TOKEN_URL":      os.getenv("TOKEN_URL"),
    "CLIENT_ID":      os.getenv("CLIENT_ID"),
    "CLIENT_SECRET":  os.getenv("CLIENT_SECRET"),
    "MODEL_BASE_URL": os.getenv("MODEL_BASE_URL"),
    "MODEL_ENDPOINT": os.getenv("MODEL_ENDPOINT"),
}
API_URL = str(os.getenv("MODEL_BASE_URL","")) + str(os.getenv("MODEL_ENDPOINT",""))

# Load existing test result to check normalization without re-running AI calls
with open("test_result.json") as f:
    existing = json.load(f)

normalized = _normalize_unknowns(existing)
Path("test_normalized.json").write_text(json.dumps(normalized, indent=2, ensure_ascii=False))

t = normalized["tenders"][0]
cc  = t.get("contract_conditions", {})
pv  = t.get("price_variation", {})
ld  = cc.get("liquidated_damages", {})
mats = pv.get("materials", [])

print("After _normalize_unknowns:")
print("  LD rate_per_week_percent :", ld.get("rate_per_week_percent"))
print("  LD cap_percent           :", ld.get("cap_percent"))
print("  firm_components          :", pv.get("firm_components"))
print("  materials[0].formula_vars:", mats[0].get("formula_variables") if mats else "n/a")
print()
print("test_normalized.json written.")
