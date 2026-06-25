"""
Instrumented end-to-end test for the Python AI service.
Uses the pre-split chunks in uploads/_split to skip re-splitting.
Measures: wall-clock time, API call count, tokens per call.
"""
import sys, os, json, time, threading, copy
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

import functions as fn
from pdf_generator import generate_tender_pdf

# ── Instrumentation ────────────────────────────────────────────────────────────
_lock = threading.Lock()
_calls = []   # [{call_no, label, input_tokens, output_tokens, elapsed_s}]
_call_no = [0]

_orig_get_result = fn.get_result

def _instrumented_get_result(token, API_URL, payload, retries=3):
    with _lock:
        _call_no[0] += 1
        n = _call_no[0]
    t0 = time.time()
    result_text = _orig_get_result(token, API_URL, payload, retries)
    elapsed = time.time() - t0

    with _lock:
        _calls.append({
            "call_no": n,
            "elapsed_s": round(elapsed, 1),
        })
        print(f"  [call #{n:>2}] done in {elapsed:.1f}s")
    return result_text

_orig_session_post = fn._session.post

def _instrumented_session_post(url, *args, **kwargs):
    resp = _orig_session_post(url, *args, **kwargs)
    try:
        rj = resp.json()
        usage = rj.get("usage", {})
        if usage:
            with _lock:
                if _calls:
                    last = _calls[-1]
                    last["input_tokens"] = usage.get("input_tokens", "?")
                    last["output_tokens"] = usage.get("output_tokens", "?")
    except Exception:
        pass
    return resp

fn._session.post = _instrumented_session_post
fn.get_result = _instrumented_get_result

# ── Credentials ────────────────────────────────────────────────────────────────
if "SAP_AI_CORE_CREDENTIALS" in os.environ:
    cred_json = json.loads(os.environ["SAP_AI_CORE_CREDENTIALS"])
    CREDENTIALS = cred_json
else:
    CREDENTIALS = {
        "TOKEN_URL":      os.getenv("TOKEN_URL") or os.getenv("SAP_AI_CORE_TOKEN_URL"),
        "CLIENT_ID":      os.getenv("CLIENT_ID") or os.getenv("SAP_AI_CORE_CLIENT_ID"),
        "CLIENT_SECRET":  os.getenv("CLIENT_SECRET") or os.getenv("SAP_AI_CORE_CLIENT_SECRET"),
    }
API_URL = os.environ.get("SAP_AI_CORE_API_URL") or (str(os.getenv("MODEL_BASE_URL", "")) + str(os.getenv("MODEL_ENDPOINT", "")))

# ── Locate pre-split chunks ────────────────────────────────────────────────────
split_dir = os.path.join(os.path.dirname(__file__), "uploads",
    "FILE_CE-SPD_ ADB_ 2026-27_ T-13_version_2_1779174523191_split")

chunks = sorted(
    [os.path.join(split_dir, f) for f in os.listdir(split_dir) if f.endswith(".pdf")],
    key=lambda p: int(p.split("_part_")[-1].replace(".pdf", ""))
)
print(f"Found {len(chunks)} chunks in: {split_dir}")
for c in chunks:
    sz = os.path.getsize(c) // 1024
    from pypdf import PdfReader
    try:
        pages = len(PdfReader(c).pages)
        print(f"  {os.path.basename(c)}: {pages} pages, {sz} KB")
    except:
        pass

# ── Step 1: Fetch token ────────────────────────────────────────────────────────
print("\n[Step 0] Fetching access token...")
t_token = time.time()
token = fn.get_access_token(CREDENTIALS)
print(f"  Token fetched in {time.time()-t_token:.1f}s")

# ── Step 2: Pass 1 — parallel chunk extraction ─────────────────────────────────
print(f"\n[Step 1] Pass 1 — extracting raw facts from {len(chunks)} chunks in parallel...")
t1 = time.time()
raw_facts_text = fn.extract_facts_from_chunks(token, API_URL, chunks)
t1_elapsed = time.time() - t1
pass1_calls = len(_calls)
print(f"  Pass 1 done in {t1_elapsed:.1f}s — {pass1_calls} AI calls")

with open("test_intermediate_facts.txt", "w") as f:
    f.write(raw_facts_text)
print(f"\n  Intermediate facts saved → test_intermediate_facts.txt ({len(raw_facts_text)} chars)")

# ── Step 3: Pass 2 — Synthesis / Structure Transform ─────────────────────────
print(f"\n[Step 2] Pass 2 — synthesizing final strict JSON...")
t2 = time.time()
final_json_data = fn.synthesize_final_json(token, API_URL, raw_facts_text)
t2_elapsed = time.time() - t2
pass2_calls = len(_calls) - pass1_calls
print(f"  Pass 2 done in {t2_elapsed:.1f}s — {pass2_calls} AI call")

with open("test_result.json", "w") as f:
    json.dump(final_json_data, f, indent=2, ensure_ascii=False)
print(f"\n  Final result JSON saved → test_result.json")

# ── Step 4: Generate PDF ───────────────────────────────────────────────────────
print(f"\n[Step 3] Generating PDF...")
t3 = time.time()
tenders = final_json_data.get("tenders", [])
if not tenders:
    print("  WARNING: No tenders found in final JSON!")
    sys.exit(1)

tender_doc = tenders[0]
title = tender_doc.get("tender_information", {}).get("title", "Tender Synopsis")
pdf_bytes = generate_tender_pdf(tender_doc, doc_title=title)
with open("test_output_new.pdf", "wb") as f:
    f.write(pdf_bytes)
t3_elapsed = time.time() - t3
print(f"  PDF saved → test_output_new.pdf ({len(pdf_bytes)//1024} KB, {t3_elapsed:.1f}s)")

# ── Summary ────────────────────────────────────────────────────────────────────
total_wall = t1_elapsed + t2_elapsed
total_input = sum(c.get("input_tokens", 0) for c in _calls if isinstance(c.get("input_tokens"), int))
total_output = sum(c.get("output_tokens", 0) for c in _calls if isinstance(c.get("output_tokens"), int))

print(f'''
╔══════════════════════════════════════════════════════╗
║               TEST RUN SUMMARY                       ║
╠══════════════════════════════════════════════════════╣
║  Total API calls: {len(_calls):>2}  ({len(chunks)} chunk + 1 synthesize)     ║
║  Pass 1 wall-clock: {t1_elapsed:>6.1f}s (parallel, 5 workers)  ║
║  Pass 2 wall-clock: {t2_elapsed:>6.1f}s (single call)          ║
║  Total AI time  : {total_wall:>6.1f}s                          ║
║  PDF generation : {t3_elapsed:>6.2f}s                          ║
╠══════════════════════════════════════════════════════╣
║  Token usage (if reported by API):                   ║
║    Input tokens : {total_input:>7}                            ║
║    Output tokens: {total_output:>7}                            ║
╠══════════════════════════════════════════════════════╣''')
for c in _calls:
    label = f"call #{c['call_no']:>2}"
    inp = c.get('input_tokens', 'N/A')
    out = c.get('output_tokens', 'N/A')
    print(f"║  {label}: {c['elapsed_s']:>6.1f}s  | in={str(inp):>7} out={str(out):>6}  ║")
print(f"╚══════════════════════════════════════════════════════╝")
