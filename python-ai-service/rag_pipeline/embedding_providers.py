"""HTTP-based embedding provider: calls a hosted API instead of loading model
weights locally. Used when EMBED_PROVIDER=hf_api (see ingestion.py) to avoid
shipping torch/sentence-transformers in the deployed venv.
"""
from typing import List

import requests
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential
from llama_index.core.base.embeddings.base import BaseEmbedding


def _is_rate_limited(exc: BaseException) -> bool:
    return (
        isinstance(exc, requests.HTTPError)
        and exc.response is not None
        and exc.response.status_code == 429
    )

# api-inference.huggingface.co was retired in favor of the router-based
# Inference Providers API — see https://huggingface.co/docs/inference-providers
HF_API_URL = "https://router.huggingface.co/hf-inference/models/{model}/pipeline/feature-extraction"


class HFInferenceAPIEmbedding(BaseEmbedding):
    token: str = ""

    def _embed(self, texts: List[str]) -> List[List[float]]:
        resp = requests.post(
            HF_API_URL.format(model=self.model_name),
            headers={"Authorization": f"Bearer {self.token}"},
            json={"inputs": texts},
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()

    def _get_query_embedding(self, query: str) -> List[float]:
        return self._embed([query])[0]

    async def _aget_query_embedding(self, query: str) -> List[float]:
        return self._get_query_embedding(query)

    def _get_text_embedding(self, text: str) -> List[float]:
        return self._embed([text])[0]

    def _get_text_embeddings(self, texts: List[str]) -> List[List[float]]:
        return self._embed(texts)


# HF's free tier is unreliable for sentence-transformers/all-MiniLM-L6-v2 (frequent
# 500s) — Gemini's embedding API is a more reliable free alternative.
# https://ai.google.dev/gemini-api/docs/embeddings
GEMINI_BATCH_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:batchEmbedContents"


class GeminiEmbedding(BaseEmbedding):
    api_key: str = ""
    output_dim: int = 768

    # Free-tier quota is request-count limited, not just token-limited — retry
    # transient 429s with backoff instead of failing the whole ingestion/query.
    @retry(
        retry=retry_if_exception(_is_rate_limited),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    def _embed(self, texts: List[str]) -> List[List[float]]:
        resp = requests.post(
            GEMINI_BATCH_URL.format(model=self.model_name),
            headers={"x-goog-api-key": self.api_key},
            json={
                "requests": [
                    {
                        "model": f"models/{self.model_name}",
                        "content": {"parts": [{"text": t}]},
                        "output_dimensionality": self.output_dim,
                    }
                    for t in texts
                ]
            },
            timeout=60,
        )
        resp.raise_for_status()
        return [e["values"] for e in resp.json()["embeddings"]]

    def _get_query_embedding(self, query: str) -> List[float]:
        return self._embed([query])[0]

    async def _aget_query_embedding(self, query: str) -> List[float]:
        return self._get_query_embedding(query)

    def _get_text_embedding(self, text: str) -> List[float]:
        return self._embed([text])[0]

    def _get_text_embeddings(self, texts: List[str]) -> List[List[float]]:
        return self._embed(texts)
