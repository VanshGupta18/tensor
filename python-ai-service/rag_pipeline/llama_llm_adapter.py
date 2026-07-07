"""LlamaIndex LLM adapter for SAP AI Core.

Wraps the existing OAuth token management + Bedrock-proxy call in
step2_llm_client.py so SAP AI Core stays the only LLM provider even when
invoked through LlamaIndex's retrieval/query-engine abstractions (used by
Phase 4's citation-grounded chat).

Scoping note: the 9-group structured extraction (step5_extractor.py) keeps
calling step2_llm_client.get_result_tool_use() directly, not through this
adapter. LlamaIndex's function-calling LLM interface is a materially bigger
integration than plain text completion, and nothing here needed that path —
only retrieval needed persistence (ingestion.py) and chat needed real
grounding. This adapter covers chat generation only.
"""
from typing import Any

from llama_index.core.base.llms.types import (
    CompletionResponse,
    CompletionResponseGen,
    LLMMetadata,
)
from llama_index.core.llms import CustomLLM
from llama_index.core.llms.callbacks import llm_completion_callback

from rag_pipeline.step2_llm_client import get_result, get_token

DEFAULT_MAX_TOKENS = 1024
CONTEXT_WINDOW = 200_000  # Claude family context window behind SAP AI Core


class SapAiCoreLLM(CustomLLM):
    """Minimal text-completion LLM backed by SAP AI Core, for LlamaIndex's query engines."""

    api_url: str
    max_tokens: int = DEFAULT_MAX_TOKENS

    @property
    def metadata(self) -> LLMMetadata:
        return LLMMetadata(
            context_window=CONTEXT_WINDOW,
            num_output=self.max_tokens,
            model_name="sap-ai-core",
        )

    def _invoke(self, prompt: str) -> str:
        payload = {
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": self.max_tokens,
            "anthropic_version": "bedrock-2023-05-31",
        }
        result, _ = get_result(get_token(), self.api_url, payload, retries=2, timeout=90)
        return result

    @llm_completion_callback()
    def complete(self, prompt: str, formatted: bool = False, **kwargs: Any) -> CompletionResponse:
        return CompletionResponse(text=self._invoke(prompt))

    @llm_completion_callback()
    def stream_complete(
        self, prompt: str, formatted: bool = False, **kwargs: Any
    ) -> CompletionResponseGen:
        # No LlamaIndex-mediated streaming path is used today — Phase 4's chat keeps the
        # existing SSE pipe (step6_chat.py) for actual token streaming to the frontend,
        # this LLM is only used for one-shot retrieval-adjacent completions. Implemented
        # for interface completeness in case a future caller needs it.
        text = self._invoke(prompt)

        def gen() -> CompletionResponseGen:
            yield CompletionResponse(text=text)

        return gen()
