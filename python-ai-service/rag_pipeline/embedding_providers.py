"""HTTP-based embedding provider: calls a hosted API instead of loading model
weights locally. Used when EMBED_PROVIDER=hf_api (see ingestion.py) to avoid
shipping torch/sentence-transformers in the deployed venv.
"""
from typing import List

import requests
from llama_index.core.base.embeddings.base import BaseEmbedding

HF_API_URL = "https://api-inference.huggingface.co/models/{model}"


class HFInferenceAPIEmbedding(BaseEmbedding):
    token: str = ""

    def _embed(self, texts: List[str]) -> List[List[float]]:
        resp = requests.post(
            HF_API_URL.format(model=self.model_name),
            headers={"Authorization": f"Bearer {self.token}"},
            json={"inputs": texts, "options": {"wait_for_model": True}},
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
