from pypdf import PdfReader
from functions import split_pdf

def test_filter(file_path):
    reader = PdfReader(file_path)
    text = " ".join((p.extract_text() or "").lower() for p in reader.pages)
    
    # Original
    keywords_orig = [
        "notice inviting", "earnest money", "emd", "bid security", "liquidated damages",
        "price variation", "price adjustment", "maat", "turnover", "net worth", "payment terms", 
        "defect liability", "performance security", "bank guarantee", "ebg", "cpg",
        "bid data sheet", "instruction to bidders", "commercial terms", "qualification",
        "eligibility", "scope of work", "bill of quantities",
        "form ", "annexure ", "format ", "appendix ", "schedule "
    ]
    hits_orig = sum(1 for kw in keywords_orig if kw in text)
    
    # Stricter
    keywords_strict = [
        "notice inviting", "earnest money", "emd", "bid security", "liquidated damages",
        "price variation", "price adjustment", "maat", "turnover", "net worth", "payment terms", 
        "defect liability", "performance security", "bank guarantee", "ebg", "cpg",
        "bid data sheet", "instruction to bidders", "commercial terms", "qualification",
        "eligibility", "bill of quantities"
    ]
    hits_strict = sum(1 for kw in keywords_strict if kw in text)
    
    return hits_orig >= 2, hits_strict >= 2, hits_strict

pdf_path = "/Users/vanshgupta/Downloads/tensor/docs/SBD ROBUST-III MBAD (003).pdf"
file_path_list = split_pdf(pdf_path, 30, 2)
dropped_orig = 0
dropped_strict = 0

for fp in file_path_list:
    orig, strict, hits = test_filter(fp)
    if not orig: dropped_orig += 1
    if not strict: dropped_strict += 1

print(f"Chunks: {len(file_path_list)}")
print(f"Dropped orig: {dropped_orig}")
print(f"Dropped strict: {dropped_strict}")
