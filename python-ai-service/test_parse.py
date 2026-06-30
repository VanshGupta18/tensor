import functions

test1 = """```json
{
  "tenders": [
    {
      "tender_information": {
        "title": "Title",
      },
    }
  ]
}
```"""
print(functions.parse_ai_json(test1))
