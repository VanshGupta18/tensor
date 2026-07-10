"""Tests for build_cached_extraction_payload — verifies 3-block message structure
and that cache_control is correctly placed on the shared preamble block only."""
import unittest

from rag_pipeline.step2_llm_client import build_cached_extraction_payload
from rag_pipeline.step1_schemas import SHARED_EXTRACTION_PREAMBLE, _DOCUMENT_SECTIONS_TOOL_SCHEMA


SAMPLE_PROMPT = "Extract the scope of work. Emit exactly ONE section: ..."
SAMPLE_CHUNKS = "Chunk A text\n\n---\nChunk B text"


class TestCachedPayloadStructure(unittest.TestCase):

    def setUp(self):
        self.payload = build_cached_extraction_payload(
            SHARED_EXTRACTION_PREAMBLE,
            SAMPLE_PROMPT,
            SAMPLE_CHUNKS,
            _DOCUMENT_SECTIONS_TOOL_SCHEMA,
        )

    def test_has_messages_key(self):
        self.assertIn("messages", self.payload)
        self.assertEqual(len(self.payload["messages"]), 1)

    def test_user_role(self):
        self.assertEqual(self.payload["messages"][0]["role"], "user")

    def test_content_is_block_array(self):
        content = self.payload["messages"][0]["content"]
        self.assertIsInstance(content, list, "content must be a list of blocks, not a plain string")

    def test_exactly_three_blocks(self):
        content = self.payload["messages"][0]["content"]
        self.assertEqual(len(content), 3, f"Expected 3 content blocks, got {len(content)}")

    def test_first_block_is_preamble_with_cache_control(self):
        block = self.payload["messages"][0]["content"][0]
        self.assertEqual(block["type"], "text")
        self.assertEqual(block["text"], SHARED_EXTRACTION_PREAMBLE)
        self.assertIn("cache_control", block, "First block must have cache_control for prompt caching")
        self.assertEqual(block["cache_control"]["type"], "ephemeral")

    def test_second_block_is_group_prompt_no_cache_control(self):
        block = self.payload["messages"][0]["content"][1]
        self.assertEqual(block["type"], "text")
        self.assertEqual(block["text"], SAMPLE_PROMPT)
        self.assertNotIn("cache_control", block, "Group prompt block must NOT have cache_control")

    def test_third_block_contains_chunks(self):
        block = self.payload["messages"][0]["content"][2]
        self.assertEqual(block["type"], "text")
        self.assertIn("DOCUMENT CHUNKS", block["text"])
        self.assertIn(SAMPLE_CHUNKS, block["text"])
        self.assertNotIn("cache_control", block, "Chunk block must NOT have cache_control")

    def test_tool_schema_attached(self):
        self.assertIn("tools", self.payload)
        self.assertEqual(len(self.payload["tools"]), 1)
        self.assertEqual(self.payload["tools"][0]["name"], "structure_document_sections")

    def test_tool_choice_forced(self):
        self.assertEqual(self.payload["tool_choice"]["type"], "tool")
        self.assertEqual(self.payload["tool_choice"]["name"], "structure_document_sections")

    def test_anthropic_version_present(self):
        self.assertIn("anthropic_version", self.payload)

    def test_max_tokens_present(self):
        self.assertIn("max_tokens", self.payload)
        self.assertGreater(self.payload["max_tokens"], 0)


class TestSharedPreambleMinLength(unittest.TestCase):
    """The preamble must be long enough to benefit from Anthropic prompt caching
    (minimum ~1024 tokens; rough proxy: >3000 characters)."""

    def test_preamble_exceeds_minimum_length(self):
        self.assertGreater(
            len(SHARED_EXTRACTION_PREAMBLE),
            3000,
            "SHARED_EXTRACTION_PREAMBLE is too short to benefit from prompt caching "
            "(need >3000 chars ≈ 1000+ tokens)",
        )

    def test_preamble_not_in_per_group_prompts(self):
        """Group prompts must NOT repeat the 'Section/SubSection/LineItem' schema description,
        since that's now exclusively in the shared preamble."""
        from rag_pipeline.step1_schemas import _EXTRACTION_GROUPS
        for group in _EXTRACTION_GROUPS:
            with self.subTest(group=group["name"]):
                self.assertNotIn(
                    "using the generic Section/SubSection/LineItem format",
                    group["prompt"],
                    f"Group '{group['name']}' prompt still contains redundant schema description",
                )


if __name__ == "__main__":
    unittest.main()
