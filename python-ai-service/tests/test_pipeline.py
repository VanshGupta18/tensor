import hashlib
import os
import json
from dotenv import load_dotenv

from rag_pipeline.step5_extractor import extract_via_targeted_retrieval
from rag_pipeline.step4_validators import validate_correctness, ensure_schema_completeness
from rag_pipeline.step2_llm_client import get_token
from rag_pipeline.step7_pdf_generator import generate_tender_pdf

load_dotenv()
API_URL = str(os.getenv("MODEL_BASE_URL", "")) + str(os.getenv("MODEL_ENDPOINT", ""))



def main():
    docs_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "docs", "tenders")
    out_dir = os.path.dirname(os.path.abspath(__file__))
    pdfs = [
        os.path.join(docs_dir, "SBD ROBUST-III MBAD (003).pdf"),
        os.path.join(docs_dir, "FILE_CE-SPD_ ADB_ 2026-27_ T-13_version_2_1779174523191.pdf"),
    ]

    all_results = []
    for i, pdf_path in enumerate(pdfs):
        print(f"\n{'='*50}\nProcessing {pdf_path}\n{'='*50}")

        content_hash = hashlib.sha256(open(pdf_path, "rb").read()).hexdigest()
        result = extract_via_targeted_retrieval(get_token, API_URL, pdf_path, content_hash)
        result = validate_correctness(result)
        result = ensure_schema_completeness(result)

        usage = result.get("_analytics", {})
        print(f"[tokens] {json.dumps(usage)}")
        all_results.append({"pdf": os.path.basename(pdf_path), "usage": usage})

        out_json = os.path.join(out_dir, f"test_result_{i+1}.json")
        with open(out_json, "w") as f:
            json.dump(result, f, indent=2)
        print(f"Saved JSON result to {out_json}")

        out_pdf = os.path.join(out_dir, f"output_test_rag_{i+1}.pdf")
        tenders = result.get("tenders", [{}])
        if tenders:
            pdf_bytes = generate_tender_pdf(tenders[0])
            with open(out_pdf, "wb") as f:
                f.write(pdf_bytes)
            print(f"Generated PDF saved to {out_pdf}")
        else:
            print("No tenders extracted to generate a PDF.")

    print(f"\n{'='*50}\nTOKEN SUMMARY\n{'='*50}")
    print(json.dumps(all_results, indent=2))

if __name__ == "__main__":
    main()
