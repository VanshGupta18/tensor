import os
import json
import time
import requests
import threading

_session = requests.Session()

# ── Token Caching ─────────────────────────────────────────────────────────────
_token_lock      = threading.Lock()
_token_value: str = ""
_token_expires_at: float = 0.0

def get_token() -> str:
    """Fetch an SAP AI Core OAuth token, proactively caching it for 55 minutes."""
    global _token_value, _token_expires_at
    with _token_lock:
        if time.time() >= (_token_expires_at - 60):
            credentials = {
                "TOKEN_URL":      os.getenv("TOKEN_URL"),
                "CLIENT_ID":      os.getenv("CLIENT_ID"),
                "CLIENT_SECRET":  os.getenv("CLIENT_SECRET"),
            }
            if not credentials["TOKEN_URL"]:
                raise ValueError("Missing authentication credentials in environment (TOKEN_URL).")
                
            _token_value      = get_access_token(credentials)
            _token_expires_at = time.time() + 55 * 60
        return _token_value

def get_access_token(cred: dict) -> str:
    data = {"grant_type": "client_credentials"}
    resp = _session.post(
        cred["TOKEN_URL"], data=data,
        auth=(cred["CLIENT_ID"], cred["CLIENT_SECRET"]), timeout=30
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def parse_ai_json(ai_text: str) -> dict:
    text = ai_text.strip()
    import re
    text = re.sub(r"^```(?:json)?\s*\n?", "", text, flags=re.MULTILINE)
    obj_start  = text.find('{')
    arr_start  = text.find('[')
    if obj_start == -1 and arr_start == -1:
        raise ValueError(f"No JSON object found in AI response.\n\nRaw:\n{text[:500]}")
    if obj_start == -1 or (arr_start != -1 and arr_start < obj_start):
        start, end_char = arr_start, ']'
    else:
        start, end_char = obj_start, '}'
    end = text.rfind(end_char)
    if end == -1 or end < start:
        raise ValueError(f"Malformed JSON (no closing '{end_char}') in AI response.\n\nRaw:\n{text[:500]}")
    text = text[start:end + 1]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        cleaned = re.sub(r",\s*([}\]])", r"\1", text)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise ValueError(f"AI returned unparseable JSON after cleanup. Snippet: {text[:200]!r}") from exc


def get_result(token: str, API_URL: str, payload: dict, retries: int = 3, timeout: int = 600) -> tuple:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "AI-Resource-Group": "grounding",
    }
    last_exc = None
    for attempt in range(retries):
        try:
            resp = _session.post(API_URL, json=payload, headers=headers, timeout=timeout)
            resp.raise_for_status()
            response_json = resp.json()
            _u = response_json.get("usage", {})
            print(f"[tokens] in={_u.get('input_tokens','?')} out={_u.get('output_tokens','?')} cache_write={_u.get('cache_creation_input_tokens',0)} cache_read={_u.get('cache_read_input_tokens',0)}")
            content_list = response_json.get("content")
            if not content_list or not isinstance(content_list, list):
                raise ValueError(f"Unexpected API response shape: {list(response_json.keys())}")
            first = content_list[0]
            text = first.get("text") if isinstance(first, dict) else None
            if not text:
                raise ValueError(f"No 'text' in API content item: {first}")
            return text, _u
        except requests.exceptions.HTTPError as e:
            last_exc = e
            if resp.status_code >= 500 and attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            last_exc = e
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise
    raise last_exc


def build_cached_extraction_payload(
    preamble: str,
    group_prompt: str,
    chunk_block: str,
    tool_schema: dict,
    max_tokens: int = 4096,
) -> dict:
    """Build the 3-block extraction payload with cache_control on the shared preamble.

    Placing the preamble in a separate content block with cache_control: ephemeral
    tells Anthropic/Bedrock to cache it after the first call. Calls 2-6, which share
    the same preamble + tool schema, will read from the cache instead of re-tokenising
    those ~1k tokens six times.
    """
    return {
        "messages": [{
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": preamble,
                    "cache_control": {"type": "ephemeral"},
                },
                {
                    "type": "text",
                    "text": group_prompt,
                },
                {
                    "type": "text",
                    "text": f"DOCUMENT CHUNKS:\n{chunk_block}\n\nUse the tool to output the structured data for this group.",
                },
            ],
        }],
        "tools": [tool_schema],
        "tool_choice": {"type": "tool", "name": "structure_document_sections"},
        "max_tokens": 4096,
        "anthropic_version": "bedrock-2023-05-31",
    }


def get_result_tool_use(token: str, API_URL: str, payload: dict, retries: int = 3, timeout: int = 600) -> tuple:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "AI-Resource-Group": "grounding",
    }
    last_exc = None
    for attempt in range(retries):
        try:
            resp = _session.post(API_URL, json=payload, headers=headers, timeout=timeout)
            resp.raise_for_status()
            _rj = resp.json()
            _u = _rj.get("usage", {})
            print(f"[tokens] in={_u.get('input_tokens','?')} out={_u.get('output_tokens','?')} cache_write={_u.get('cache_creation_input_tokens',0)} cache_read={_u.get('cache_read_input_tokens',0)}")
            content_list = _rj.get("content", [])
            for item in content_list:
                if isinstance(item, dict) and item.get("type") == "tool_use":
                    return item["input"], _u
            for item in content_list:
                if isinstance(item, dict) and item.get("type") == "text" and item.get("text"):
                    return parse_ai_json(item["text"]), _u
            raise ValueError(f"No usable content in tool-use response: {content_list}")
        except requests.exceptions.HTTPError as e:
            last_exc = e
            if resp.status_code >= 500 and attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            last_exc = e
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise
    raise last_exc
