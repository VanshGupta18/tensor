import re

def test(cond):
    cond_str = str(cond)
    cond_str = re.sub(r'(?i)\bbg\s*(?:of)?\s*\d+(?:\.\d+)?\s*%', '', cond_str)
    cond_str = re.sub(r'(?i)\d+(?:\.\d+)?\s*%\s*(?:of\s*)?(?:bg|bank guarantee)', '', cond_str)
    return [float(m) for m in re.findall(r'\b(\d+(?:\.\d+)?)\s*%', cond_str)]

print(test("15% advance against BG of 110%"))
print(test("5% on signing, 10% on mobilization against 100% BG"))
print(test("10% Bank guarantee required"))
