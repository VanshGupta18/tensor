from pypdf import PdfReader
reader = PdfReader("/Users/vanshgupta/Downloads/tensor/docs/output_test.pdf")
for page in reader.pages:
    text = page.extract_text()
    if "Price Variation" in text or "Price Adjustment" in text:
        print(text)
