import json
import requests
from rag_pipeline.step2_llm_client import get_result, _session
from rag_pipeline.retrieval import retrieve_chunks

# Chat retrieval trims to a small, high-precision set of chunks (unlike the 9-group
# extraction in step5_extractor.py, which keeps a wide recall-oriented set) — chat's
# answer-context budget is much tighter than a whole-section extraction prompt.
_CHAT_RETRIEVAL_TOP_K = 15
_CHAT_RERANK_TOP_N = 8


def _retrieve_context(content_hash: str, message: str):
    """Real clause-level passages for this document, or None if ungroundable
    (no content_hash yet, nothing indexed, or retrieval itself failed) — callers
    fall back to the old document-blind assistant rather than erroring."""
    if not content_hash:
        return None
    try:
        chunks = retrieve_chunks(
            content_hash, message, top_k=_CHAT_RETRIEVAL_TOP_K, rerank_top_n=_CHAT_RERANK_TOP_N
        )
        return chunks or None
    except Exception as e:
        print(f"[chat] retrieval failed, falling back to ungrounded chat: {e}")
        return None


def _build_chat_messages(message, tender_id="", history=None, context_chunks=None):
    """Build a multi-turn messages array for the AI, including prior conversation turns.

    history: list of {"role": "user"|"assistant", "content": str} from the frontend.
    Capped at the last 20 entries (10 exchanges) to stay within token limits.
    System context is injected as a leading user/assistant exchange so it works
    with SAP AI Core's bedrock proxy regardless of top-level `system` support.

    context_chunks: real retrieved passages (each already prefixed "[PAGE N]" by
    retrieval.py) for the current tender's document. When present, the assistant is
    grounded in them and required to cite pages; when absent (no document indexed
    yet, or retrieval found nothing), falls back to the previous generic behavior.
    """
    if context_chunks:
        context_block = "\n\n---\n".join(context_chunks)
        system_line = (
            "You are an AI assistant for tender document management. Answer ONLY using "
            "the tender excerpts below — do not use outside knowledge. Every fact you state "
            "must include its source page in the form (p.N), taken from the 'PAGE N' marker "
            "in the chunk header (e.g. [PAGE 4 | Notice Inviting Tender]). If the answer isn't "
            "present in these excerpts, say so plainly instead of guessing.\n\nTENDER EXCERPTS:\n" + context_block
        )
    else:
        context = f" The user is asking about tender ID '{tender_id}'." if tender_id else ""
        system_line = (
            f"You are an AI assistant for tender document management.{context} "
            "Be concise and use prior conversation context to answer follow-up questions."
        )
    messages = [
        {"role": "user",      "content": f"[System] {system_line}"},
        {"role": "assistant", "content": "Understood. I'm ready to help."},
    ]
    for turn in (history or [])[-20:]:
        role    = turn.get("role", "")
        content = (turn.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": message})
    return messages

def generate_chat_response(token, API_URL, message, tender_id="", history=None, content_hash=""):
    context_chunks = _retrieve_context(content_hash, message)
    payload = {
        "messages": _build_chat_messages(message, tender_id, history, context_chunks),
        "max_tokens": 512,
        "anthropic_version": "bedrock-2023-05-31"
    }
    result, _ = get_result(token, API_URL, payload, retries=1, timeout=55)
    return result

def generate_chat_response_stream(token, API_URL, message, tender_id="", history=None, content_hash=""):
    """Yields text chunks as they arrive from the AI Core streaming API."""
    context_chunks = _retrieve_context(content_hash, message)
    payload = {
        "messages": _build_chat_messages(message, tender_id, history, context_chunks),
        "max_tokens": 512,
        "anthropic_version": "bedrock-2023-05-31",
        "stream": True,
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "AI-Resource-Group": "grounding",
    }
    with _session.post(API_URL, json=payload, headers=headers, stream=True, timeout=55) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines():
            if not line:
                continue
            line = line.decode("utf-8") if isinstance(line, bytes) else line
            if not line.startswith("data: "):
                continue
            data_str = line[6:]
            if data_str == "[DONE]":
                break
            try:
                data = json.loads(data_str)
                if data.get("type") == "content_block_delta":
                    text = data.get("delta", {}).get("text", "")
                    if text:
                        yield text
            except (json.JSONDecodeError, KeyError):
                continue
