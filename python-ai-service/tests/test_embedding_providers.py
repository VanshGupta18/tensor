from unittest.mock import Mock, patch

from rag_pipeline.embedding_providers import HFInferenceAPIEmbedding


def test_hf_api_embedding_calls_inference_endpoint():
    model = HFInferenceAPIEmbedding(model_name="sentence-transformers/all-MiniLM-L6-v2", token="tok")
    fake_resp = Mock(status_code=200)
    fake_resp.json.return_value = [[0.1, 0.2, 0.3]]
    fake_resp.raise_for_status = Mock()

    with patch("rag_pipeline.embedding_providers.requests.post", return_value=fake_resp) as post:
        vec = model._get_text_embedding("hello world")

    assert vec == [0.1, 0.2, 0.3]
    _, kwargs = post.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer tok"
    assert kwargs["json"]["inputs"] == ["hello world"]
