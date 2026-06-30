import json
from functions import validate_correctness

with open('example.json') as f:
    data = json.load(f)

# Wrap it in a tender array to match synthesized output format
synthesized = {"tenders": [data]}
validate_correctness(synthesized)
