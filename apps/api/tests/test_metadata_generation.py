"""Unit tests for the LLM-suggested catalog metadata in app/metadata_generation.py.

suggest_dataset_metadata() must never raise or apply anything the model wasn't
actually asked for: an empty/unusable response, malformed JSON, or a column
name the model invented should all just result in None (or a dropped entry),
never an exception. is_unreviewed_description() is the gate every ingestion
path uses to decide whether it's safe to touch a description at all.
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from app.metadata_generation import is_unreviewed_description, suggest_dataset_metadata
from app.model_runtime import ProviderGenerationResult


def make_provider() -> MagicMock:
    provider = MagicMock()
    provider.provider_type = "gemini"
    provider.default_model = "test-model"
    return provider


COLUMNS = [
    {"name": "customer_id", "type": "integer", "nullable": False},
    {"name": "opened_at", "type": "timestamp", "nullable": True},
]


class SuggestDatasetMetadataTests(unittest.TestCase):
    def test_empty_provider_response_returns_none(self) -> None:
        with patch("app.metadata_generation.generate_text", return_value=ProviderGenerationResult(content="", latency_ms=1)):
            result = suggest_dataset_metadata(make_provider(), "core", "accounts", COLUMNS, governance_business_id="proj-1")
        self.assertIsNone(result)

    def test_malformed_json_returns_none(self) -> None:
        with patch("app.metadata_generation.generate_text", return_value=ProviderGenerationResult(content="not json at all", latency_ms=1)):
            result = suggest_dataset_metadata(make_provider(), "core", "accounts", COLUMNS, governance_business_id="proj-1")
        self.assertIsNone(result)

    def test_provider_error_returns_none_instead_of_raising(self) -> None:
        with patch("app.metadata_generation.generate_text", side_effect=RuntimeError("provider unavailable")):
            result = suggest_dataset_metadata(make_provider(), "core", "accounts", COLUMNS, governance_business_id="proj-1")
        self.assertIsNone(result)

    def test_unknown_column_is_dropped(self) -> None:
        content = (
            '{"description": "Customer accounts.", "columns": {'
            '"customer_id": {"business_name": "Customer ID", "description": "Unique customer identifier"}, '
            '"not_a_real_column": {"business_name": "Ghost", "description": "Invented by the model"}'
            "}}"
        )
        with patch("app.metadata_generation.generate_text", return_value=ProviderGenerationResult(content=content, latency_ms=1)):
            result = suggest_dataset_metadata(make_provider(), "core", "accounts", COLUMNS, governance_business_id="proj-1")
        assert result is not None
        self.assertIn("customer_id", result["columns"])
        self.assertNotIn("not_a_real_column", result["columns"])

    def test_oversized_description_is_truncated(self) -> None:
        long_description = "x" * 10_000
        content = f'{{"description": "{long_description}", "columns": {{}}}}'
        with patch("app.metadata_generation.generate_text", return_value=ProviderGenerationResult(content=content, latency_ms=1)):
            result = suggest_dataset_metadata(make_provider(), "core", "accounts", COLUMNS, governance_business_id="proj-1")
        assert result is not None
        self.assertLessEqual(len(result["description"]), 5_000)

    def test_response_wrapped_in_markdown_fence_is_parsed(self) -> None:
        content = '```json\n{"description": "Customer accounts.", "columns": {}}\n```'
        with patch("app.metadata_generation.generate_text", return_value=ProviderGenerationResult(content=content, latency_ms=1)):
            result = suggest_dataset_metadata(make_provider(), "core", "accounts", COLUMNS, governance_business_id="proj-1")
        assert result is not None
        self.assertEqual(result["description"], "Customer accounts.")


class IsUnreviewedDescriptionTests(unittest.TestCase):
    def test_blank_is_unreviewed(self) -> None:
        self.assertTrue(is_unreviewed_description(None))
        self.assertTrue(is_unreviewed_description(""))
        self.assertTrue(is_unreviewed_description("   "))

    def test_known_placeholders_are_unreviewed(self) -> None:
        self.assertTrue(is_unreviewed_description("Discovered from Warehouse in read-only mode."))
        self.assertTrue(is_unreviewed_description("Ingested from customers.csv"))
        self.assertTrue(is_unreviewed_description("Mapped append ingestion from customers.csv"))

    def test_human_or_ai_written_text_is_not_unreviewed(self) -> None:
        self.assertFalse(is_unreviewed_description("Every checking and savings account opened at the bank."))


if __name__ == "__main__":
    unittest.main()
