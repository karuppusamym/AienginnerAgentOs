"""Standalone unit tests for the embedding fallback logic in app/vector_store.py.

No database, Qdrant, or FastAPI app needed here -- embed_text() is pure and
default_embedding_provider() only needs something that looks like a Session's
.scalar(). This targets the specific chain of "when do we use a real model
embedding vs. the deterministic hash fallback" decisions: unsupported provider
types, missing secrets, missing embedding_model, and live-call failures should
all fall back to the hash embedding rather than raising or returning nothing.
"""
from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

from app.vector_store import (
    HASH_VECTOR_SIZE,
    _hash_embedding,
    embed_text,
)
from app.provider_selection import default_embedding_provider


def make_provider(**overrides):
    provider = MagicMock()
    provider.provider_type = overrides.get("provider_type", "gemini")
    provider.embedding_model = overrides.get("embedding_model", "text-embedding-004")
    provider.secret_reference = overrides.get("secret_reference", "env:TEST_EMBEDDING_KEY")
    provider.base_url = overrides.get("base_url", None)
    provider.name = overrides.get("name", "Test Provider")
    return provider


class EmbedTextFallbackTests(unittest.TestCase):
    def test_hash_embedding_is_deterministic_and_normalized(self) -> None:
        first = _hash_embedding("customer churn by segment")
        second = _hash_embedding("customer churn by segment")
        self.assertEqual(first, second)
        self.assertEqual(len(first), HASH_VECTOR_SIZE)
        norm = sum(component * component for component in first) ** 0.5
        self.assertAlmostEqual(norm, 1.0, places=6)

    def test_hash_embedding_differs_for_different_text(self) -> None:
        self.assertNotEqual(_hash_embedding("accounts"), _hash_embedding("transactions"))

    def test_no_provider_falls_back_to_hash(self) -> None:
        value = "no provider configured"
        self.assertEqual(embed_text(value, None), _hash_embedding(value))

    def test_unsupported_provider_type_claude_falls_back_to_hash(self) -> None:
        provider = make_provider(provider_type="claude")
        value = "claude has no embeddings endpoint"
        self.assertEqual(embed_text(value, provider), _hash_embedding(value))

    def test_unsupported_provider_type_local_mock_falls_back_to_hash(self) -> None:
        provider = make_provider(provider_type="local_mock")
        value = "local mock is deterministic test data only"
        self.assertEqual(embed_text(value, provider), _hash_embedding(value))

    def test_missing_secret_falls_back_to_hash(self) -> None:
        provider = make_provider(provider_type="gemini", secret_reference=None)
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GOOGLE_API_KEY", None)
            value = "no secret reference and no GOOGLE_API_KEY fallback"
            self.assertEqual(embed_text(value, provider), _hash_embedding(value))

    def test_openai_provider_with_no_embedding_model_falls_back_to_hash(self) -> None:
        provider = make_provider(provider_type="openai", embedding_model=None, base_url="https://api.openai.com/v1")
        value = "provider has a secret but no embedding_model configured"
        self.assertEqual(embed_text(value, provider), _hash_embedding(value))

    @patch("app.vector_store._embed_via_gemini")
    def test_gemini_live_call_failure_falls_back_to_hash(self, mock_gemini) -> None:
        mock_gemini.return_value = None
        provider = make_provider(provider_type="gemini")
        value = "gemini call failed for any reason"
        with patch.dict(os.environ, {"TEST_EMBEDDING_KEY": "fake-secret"}):
            self.assertEqual(embed_text(value, provider), _hash_embedding(value))
        mock_gemini.assert_called_once()

    @patch("app.vector_store._embed_via_gemini")
    def test_gemini_live_call_success_is_used_verbatim(self, mock_gemini) -> None:
        fake_vector = [0.1, 0.2, 0.3]
        mock_gemini.return_value = fake_vector
        provider = make_provider(provider_type="gemini")
        with patch.dict(os.environ, {"TEST_EMBEDDING_KEY": "fake-secret"}):
            self.assertEqual(embed_text("a real embedding call succeeded", provider), fake_vector)

    @patch("app.vector_store._embed_via_openai_compatible")
    def test_openai_compatible_live_call_failure_falls_back_to_hash(self, mock_openai) -> None:
        mock_openai.return_value = None
        provider = make_provider(provider_type="openai_compatible", embedding_model="local-embed", base_url="http://localhost:9999/v1")
        value = "openai-compatible call failed"
        with patch.dict(os.environ, {"TEST_EMBEDDING_KEY": "fake-secret"}):
            self.assertEqual(embed_text(value, provider), _hash_embedding(value))
        mock_openai.assert_called_once()

    def test_embed_text_never_raises_even_if_genai_import_missing(self) -> None:
        provider = make_provider(provider_type="gemini")
        with patch("app.vector_store.genai", None):
            # No SDK available should fall through to the REST path inside
            # _embed_via_gemini, which itself catches network errors -- either
            # way embed_text() must not propagate an exception to the caller.
            try:
                embed_text("resilience under a missing optional dependency", provider)
            except Exception as exc:  # pragma: no cover - failure path
                self.fail(f"embed_text raised unexpectedly: {exc}")


class DefaultEmbeddingProviderTests(unittest.TestCase):
    def test_prefers_the_default_enabled_provider(self) -> None:
        default_provider = make_provider(name="Default")
        db = MagicMock()
        db.scalar.side_effect = [default_provider]
        self.assertIs(default_embedding_provider(db), default_provider)
        db.scalar.assert_called_once()

    def test_falls_back_to_first_enabled_provider_when_no_default(self) -> None:
        fallback_provider = make_provider(name="First enabled")
        db = MagicMock()
        db.scalar.side_effect = [None, fallback_provider]
        self.assertIs(default_embedding_provider(db), fallback_provider)
        self.assertEqual(db.scalar.call_count, 2)

    def test_returns_none_when_nothing_is_enabled(self) -> None:
        db = MagicMock()
        db.scalar.side_effect = [None, None]
        self.assertIsNone(default_embedding_provider(db))


if __name__ == "__main__":
    unittest.main()
