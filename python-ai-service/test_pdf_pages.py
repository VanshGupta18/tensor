from pypdf import PdfReader

reader = PdfReader("/Users/vanshgupta/Downloads/tensor/docs/SBD ROBUST-III MBAD (003).pdf")
for i, page in enumerate(reader.pages):
    text = page.extract_text() or ""
    if "price variation" in text.lower() or "price adjustment" in text.lower():
        print(f"--- PAGE {i+1} ---")
        lines = text.split('\n')
        for idx, line in enumerate(lines):
            if "price" in line.lower() or "variation" in line.lower() or "XX" in line:
                print(f"L{idx}: {line}")
