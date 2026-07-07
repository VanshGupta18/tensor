"""SAP AI Core client for vision-based structured extraction.

Self-contained on purpose — this service does not import from python-ai-service
even though both talk to the same SAP AI Core deployment. Keeping this service
standalone means it has no code coupling to the tender platform at all.
"""
import os
import threading
import time

import requests

_session = requests.Session()

_token_lock = threading.Lock()
_token_value = ""
_token_expires_at = 0.0


def get_token() -> str:
    """Fetch an SAP AI Core OAuth token, proactively caching it for 55 minutes."""
    global _token_value, _token_expires_at
    with _token_lock:
        if time.time() >= (_token_expires_at - 60):
            token_url = os.getenv("TOKEN_URL")
            client_id = os.getenv("CLIENT_ID")
            client_secret = os.getenv("CLIENT_SECRET")
            if not token_url:
                raise ValueError("Missing TOKEN_URL in environment.")
            resp = _session.post(
                token_url,
                data={"grant_type": "client_credentials"},
                auth=(client_id, client_secret),
                timeout=30,
            )
            resp.raise_for_status()
            _token_value = resp.json()["access_token"]
            _token_expires_at = time.time() + 55 * 60
        return _token_value


def extract_with_vision(
    api_url: str, 
    images_b64: list, 
    tool_schema: dict, 
    prompt: str,
    extracted_text: str | None = None
) -> dict:
    """Send page images (or raw extracted text) + a forced tool-use call to Claude 
    (via SAP AI Core's Bedrock-style invoke endpoint) and return the structured tool-use input.

    If extracted_text is provided, it completely bypasses the image payload, saving ~80% of tokens.
    """
    token = get_token()
    
    if extracted_text:
        full_prompt = (
            f"{prompt}\n\nHere is the raw extracted text from the digital invoice:\n\n"
            f"<invoice_text>\n{extracted_text}\n</invoice_text>"
        )
        content = [{"type": "text", "text": full_prompt}]
    else:
        content = [{"type": "text", "text": prompt}]
        for img in images_b64:
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": img["media_type"], "data": img["data"]},
            })

    payload = {
        "messages": [{"role": "user", "content": content}],
        "tools": [tool_schema],
        "tool_choice": {"type": "tool", "name": tool_schema["name"]},
        "max_tokens": 2048,
        "anthropic_version": "bedrock-2023-05-31",
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "AI-Resource-Group": "grounding",
    }
    resp = _session.post(api_url, json=payload, headers=headers, timeout=120)
    try:
        resp.raise_for_status()
    except Exception as e:
        print(f"Error payload: {resp.text}")
        raise e
    body = resp.json()

    usage = body.get("usage", {})
    print(
        f"[tokens] in={usage.get('input_tokens', '?')} "
        f"out={usage.get('output_tokens', '?')} "
        f"cache_write={usage.get('cache_creation_input_tokens', 0)} "
        f"cache_read={usage.get('cache_read_input_tokens', 0)}"
    )

    for item in body.get("content", []):
        if item.get("type") == "tool_use":
            return item["input"]
    raise ValueError(f"No tool_use block in response: {body}")
