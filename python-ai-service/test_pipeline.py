"""
Internal pipeline test — runs the full v3 extraction + synthesis pipeline on the
existing split chunks without starting Flask or re-splitting the PDF.

Usage:
    cd python-ai-service
    python test_pipeline.py
"""

import json
import os
import sys
import time
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).parent))

from functions import (
    get_access_token,
    extract_facts_from_chunks,
    merge_chunk_facts,
    synthesize_final_json,
    synonym_based_validation,
)

CREDENTIALS = {
    "TOKEN_URL":      os.getenv("TOKEN_URL"),
    "CLIENT_ID":      os.getenv("CLIENT_ID"),
    "CLIENT_SECRET":  os.getenv("CLIENT_SECRET"),
    "MODEL_BASE_URL": os.getenv("MODEL_BASE_URL"),
    "MODEL_ENDPOINT": os.getenv("MODEL_ENDPOINT"),
}
API_URL = str(os.getenv("MODEL_BASE_URL", "")) + str(os.getenv("MODEL_ENDPOINT", ""))

SPLIT_DIR = Path(__file__).parent / "uploads" / "FILE_CE-SPD_ ADB_ 2026-27_ T-13_version_2_1779174523191_split"
OUTPUT_FILE = Path(__file__).parent / "test_result.json"
MERGED_FILE = Path(__file__).parent / "test_merged.json"

def main():
    chunks = sorted(SPLIT_DIR.glob("*.pdf"), key=lambda p: int(p.stem.split("_part_")[-1]))
    if not chunks:
        print(f"[ERROR] No chunks found in {SPLIT_DIR}")
        sys.exit(1)
    print(f"[test] Found {len(chunks)} chunks")

    print("[test] Getting access token…")
    token = get_access_token(CREDENTIALS)

    # Pass 1: extract facts (returns list[str])
    print("[test] Pass 1: extracting facts from chunks (parallel)…")
    t0 = time.time()
    chunk_texts = extract_facts_from_chunks(token, API_URL, [str(c) for c in chunks])
    print(f"[test] Pass 1 done in {time.time()-t0:.1f}s  |  {len(chunk_texts)} chunk texts")

    # Pass 1.5: merge + deduplicate
    print("[test] Pass 1.5: merging and deduplicating facts…")
    merged_facts = merge_chunk_facts(chunk_texts)
    MERGED_FILE.write_text(json.dumps(merged_facts, indent=2, ensure_ascii=False))
    total_attrs = sum(len(attrs) for attrs in merged_facts.values())
    print(f"[test] Pass 1.5 done — {len(merged_facts)} sections, {total_attrs} total attributes")

    # Pass 2: synthesize with tool-use + glossary
    print("[test] Pass 2: synthesizing final JSON (tool-use)…")
    t1 = time.time()
    synthesized = synthesize_final_json(token, API_URL, merged_facts)
    print(f"[test] Pass 2 done in {time.time()-t1:.1f}s")

    # Pass 2.5: synonym-based validation (zero AI calls)
    print("[test] Pass 2.5: synonym-based validation…")
    t2 = time.time()
    final = synonym_based_validation(synthesized, merged_facts)
    print(f"[test] Pass 2.5 done in {time.time()-t2:.1f}s")

    OUTPUT_FILE.write_text(json.dumps(final, indent=2, ensure_ascii=False))
    print(f"\n[test] Result written → {OUTPUT_FILE}")
    print(f"[test] Merged facts written → {MERGED_FILE}")

    # Quality check
    tender = (final.get("tenders") or [{}])[0]
    ti   = tender.get("tender_information", {})
    kd   = tender.get("key_dates", {})
    sf   = tender.get("security_and_financials", {})
    cc   = tender.get("contract_conditions", {})
    tbd  = tender.get("technical_bid_documents", {})
    eq   = tender.get("eligibility_and_qualification", {})

    print("\n" + "="*60)
    print("QUALITY CHECK")
    print("="*60)

    def chk(label, value, good_fn=None):
        val_str = str(value)[:80] if value not in (None, "", {}, []) else "(empty)"
        bad = "(empty)" in val_str or (good_fn and not good_fn(value))
        flag = "  OK" if not bad else "  MISSING"
        print(f"{flag}  {label}: {val_str}")

    chk("Title",              ti.get("title"))
    chk("Reference No",       ti.get("reference_no"))
    chk("Issuing Authority",  ti.get("issuing_authority"))
    chk("Estimated Cost",     ti.get("estimated_cost"),
        lambda v: isinstance(v, dict) and v.get("currency") and v.get("amount"))
    chk("Tender Fee",         ti.get("tender_fee"),
        lambda v: isinstance(v, dict) and v.get("currency") and v.get("amount"))
    chk("Publication Date",   kd.get("publication"))
    chk("Bid Deadline date",  (kd.get("bid_submission_deadline") or {}).get("date"))
    chk("Bid Deadline time",  (kd.get("bid_submission_deadline") or {}).get("time"))
    chk("Bid Deadline tz",    (kd.get("bid_submission_deadline") or {}).get("timezone"))
    chk("Tech Opening",       (kd.get("technical_opening") or {}).get("date"))
    chk("Fin Opening",        (kd.get("financial_opening") or {}).get("date"))
    chk("EMD %",              (sf.get("emd") or {}).get("percentage"),
        lambda v: v is not None and float(v) > 0)
    chk("EMD max cap",        (sf.get("emd") or {}).get("max_cap_inr"))
    chk("Bid validity days",  sf.get("bid_validity_days"),
        lambda v: v is not None and float(v) > 0)
    chk("Perf security %",    sf.get("performance_security_percent"),
        lambda v: v is not None and float(v) > 0)
    chk("Completion months",  cc.get("completion_time_months"),
        lambda v: v is not None and float(v) > 0)
    chk("DLP months",         cc.get("defect_liability_period_months"),
        lambda v: v is not None and float(v) > 0)
    chk("LD rate/week %",     (cc.get("liquidated_damages") or {}).get("rate_per_week_percent"),
        lambda v: v is not None and float(v) > 0)
    chk("LD cap %",           (cc.get("liquidated_damages") or {}).get("cap_percent"),
        lambda v: v is not None and float(v) > 0)
    docs = tbd.get("grouped_documents") or []
    chk("Grouped documents",  f"{len(docs)} groups", lambda v: len(docs) > 0)

    # Eligibility completeness
    print("\n--- ELIGIBILITY COMPLETENESS ---")
    tech = eq.get("technical") or {}
    fin  = eq.get("financial") or {}
    chk("Tech options",  tech.get("options"), lambda v: isinstance(v, list) and len(v) > 0)
    chk("MAAT",          fin.get("maat"))
    chk("Net Worth",     fin.get("net_worth"))
    chk("Liquid Assets", fin.get("liquid_assets"))

    # Merged facts section dump
    print("\n--- MERGED FACTS SECTIONS ---")
    for section, attrs in merged_facts.items():
        print(f"  {section}: {len(attrs)} attributes")

    # Clause reference scan
    print("\n--- CLAUSE REFERENCE SCAN ---")
    clause_patterns = ["as per scc", "as per itb", "as per gcc", "as per rfb",
                       "as specified in", "refer to clause", "as per clause"]
    full_text = json.dumps(final).lower()
    hits = [p for p in clause_patterns if p in full_text]
    if hits:
        print(f"  WARNING: clause references still present: {hits}")
        for p in hits:
            idx = full_text.find(p)
            print(f"    ...{full_text[max(0,idx-30):idx+60]}...")
    else:
        print("  OK — no clause references found in output")

    print(f"\n[test] Total time: {time.time()-t0:.1f}s")

if __name__ == "__main__":
    main()
