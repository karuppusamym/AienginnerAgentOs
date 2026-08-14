from __future__ import annotations

import hashlib
import math
import os
import re
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

try:
    from google import genai
except ImportError:
    genai = None

from .model_runtime import resolve_secret
from .models import DataAsset, GlossaryDocument, ModelProvider
from .provider_selection import default_embedding_provider

# Dimension of the deterministic hash fallback, and of Gemini's
# text-embedding-004 (the previous hardcoded default). Real embedding models
# configured via ModelProvider.embedding_model may use a different
# dimension -- ensure_collection() detects that and recreates the Qdrant
# collection to match rather than assuming this constant.
HASH_VECTOR_SIZE = 768
COLLECTION = "datapilot_knowledge_v2"
TOKEN_PATTERN = re.compile(r"[a-zA-Z0-9_]+")

# Anthropic's Messages API has no embeddings endpoint (Anthropic points
# customers at Voyage AI instead), so a ModelProvider configured as
# provider_type="claude" cannot serve embeddings directly today. local_mock
# is a deterministic test/demo provider with no external API at all. Both
# fall back to the hash embedding rather than pretending to call a real API.
_UNSUPPORTED_EMBEDDING_PROVIDER_TYPES = {"claude", "local_mock"}


def qdrant_url() -> str | None:
    value = os.getenv("QDRANT_URL", "").strip().rstrip("/")
    return value or None


def chunk_glossary_text(text: str, chunk_size: int = 1500, overlap: int = 150) -> list[str]:
    """Split into overlapping chunks so each vector point stays specific.

    Whether the active embedding is the bag-of-tokens hash fallback or a real
    embedding model (see embed_text() below), feeding one giant multi-page
    document as a single point dilutes every chunk's distinguishing signal
    into one blurry average vector. Indexing per-chunk keeps each point's
    content narrow enough for the scorer to actually discriminate between
    passages about different topics in the same document.
    """
    normalized = re.sub(r"\n{3,}", "\n\n", text.strip())
    if len(normalized) <= chunk_size:
        return [normalized] if normalized else []
    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        end = min(start + chunk_size, len(normalized))
        boundary = normalized.rfind("\n\n", start, end)
        if boundary <= start:
            boundary = end
        chunks.append(normalized[start:boundary].strip())
        start = max(boundary - overlap, start + 1) if boundary < len(normalized) else end
    return [chunk for chunk in chunks if chunk]


def _hash_embedding(value: str, size: int = HASH_VECTOR_SIZE) -> list[float]:
    """Deterministic bag-of-tokens hash used when no real embedding model is
    configured, the provider type has no embeddings API, or a live call
    fails. Not semantically meaningful, but stable, free, and dependency-free.
    """
    vector = [0.0] * size
    for token in TOKEN_PATTERN.findall(value.lower()):
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        index = int.from_bytes(digest[:4], "big") % size
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign * (1.0 + min(len(token), 12) / 12.0)
    norm = math.sqrt(sum(component * component for component in vector)) or 1.0
    return [component / norm for component in vector]


def _embed_via_gemini(value: str, model: str, api_key: str, base_url: str | None) -> list[float] | None:
    if genai is not None:
        try:
            client = genai.Client(api_key=api_key)
            result = client.models.embed_content(model=model, contents=value)
            if result and result.embeddings:
                return [float(v) for v in result.embeddings[0].values]
        except Exception as exc:
            print(f"Warning: Gemini embedding via SDK failed ({exc}); trying REST")
    rest_base = (base_url or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.post(
                f"{rest_base}/models/{model}:embedContent",
                headers={"x-goog-api-key": api_key},
                json={"model": f"models/{model}", "content": {"parts": [{"text": value}]}},
            )
            response.raise_for_status()
            payload = response.json()
        values = (payload.get("embedding") or {}).get("values")
        if values:
            return [float(v) for v in values]
    except Exception as exc:
        print(f"Warning: Gemini embedding via REST failed ({exc})")
    return None


def _embed_via_openai_compatible(value: str, model: str, api_key: str, base_url: str) -> list[float] | None:
    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.post(
                f"{base_url.rstrip('/')}/embeddings",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"model": model, "input": value},
            )
            response.raise_for_status()
            payload = response.json()
        data = payload.get("data") or []
        if data and data[0].get("embedding"):
            return [float(v) for v in data[0]["embedding"]]
    except Exception as exc:
        print(f"Warning: OpenAI-compatible embedding failed ({exc})")
    return None


def embed_text(value: str, provider: ModelProvider | None = None) -> list[float]:
    """Embed `value` with the given provider's embedding_model.

    Falls back to a deterministic hash vector when: no provider is passed
    (e.g. no ModelProvider configured yet), the provider type has no
    embeddings API (claude, local_mock), the provider has no usable secret,
    or the live call fails for any reason (network error, bad response,
    missing embedding_model, ...). Callers never see an exception from this
    function -- indexing/search stay best-effort even when a provider is
    misconfigured.
    """
    if provider is not None and provider.provider_type not in _UNSUPPORTED_EMBEDDING_PROVIDER_TYPES:
        secret = resolve_secret(provider.secret_reference) or (
            os.getenv("GOOGLE_API_KEY") if provider.provider_type == "gemini" else None
        )
        if secret:
            vector: list[float] | None = None
            if provider.provider_type == "gemini":
                model = provider.embedding_model or "text-embedding-004"
                vector = _embed_via_gemini(value, model, secret, provider.base_url)
            elif provider.provider_type in ("openai", "openai_compatible"):
                model = provider.embedding_model
                default_url = "https://api.openai.com/v1" if provider.provider_type == "openai" else ""
                base_url = provider.base_url or default_url
                if model and base_url:
                    vector = _embed_via_openai_compatible(value, model, secret, base_url)
                elif not model:
                    print(f"Warning: provider '{provider.name}' has no embedding_model set; using hash fallback")
            if vector:
                return vector
    return _hash_embedding(value)


def _collection_vector_size(client: httpx.Client, base_url: str) -> int | None:
    response = client.get(f"{base_url}/collections/{COLLECTION}")
    if response.status_code == 404:
        return None
    response.raise_for_status()
    try:
        return int(response.json()["result"]["config"]["params"]["vectors"]["size"])
    except (KeyError, TypeError, ValueError):
        return None


def ensure_collection(dim: int, *, allow_resize: bool = False) -> bool:
    """Make sure the Qdrant collection exists with vector size `dim`.

    Different embedding models produce different-sized vectors (Gemini
    text-embedding-004 = 768, OpenAI text-embedding-3-small = 1536, ...), and
    Qdrant collections are created with a fixed size. When `allow_resize` is
    True (the write path, index_document) and the existing collection's size
    no longer matches, the collection is dropped and recreated at the new
    size -- this is a destructive migration, so callers should follow up with
    reindex_all() to repopulate it. The read path (search_documents) passes
    allow_resize=False so a stale/mismatched collection is never wiped by a
    query; a dimension mismatch there just yields a Qdrant error, caught by
    the caller as "no results" until someone reindexes.
    """
    base_url = qdrant_url()
    if not base_url:
        return False
    with httpx.Client(timeout=8.0) as client:
        existing_size = _collection_vector_size(client, base_url)
        if existing_size is None:
            client.put(
                f"{base_url}/collections/{COLLECTION}",
                json={"vectors": {"size": dim, "distance": "Cosine"}},
            ).raise_for_status()
        elif existing_size != dim and allow_resize:
            print(
                f"Warning: embedding dimension changed ({existing_size} -> {dim}); "
                f"recreating Qdrant collection '{COLLECTION}'. Previously indexed "
                "content is no longer searchable until reindexed -- see "
                "POST /model-providers/reindex-embeddings."
            )
            client.delete(f"{base_url}/collections/{COLLECTION}").raise_for_status()
            client.put(
                f"{base_url}/collections/{COLLECTION}",
                json={"vectors": {"size": dim, "distance": "Cosine"}},
            ).raise_for_status()
    return True


def index_document(source_id: str, title: str, text: str, payload: dict[str, Any], db: Session | None = None) -> bool:
    base_url = qdrant_url()
    if not base_url:
        return False
    provider = default_embedding_provider(db) if db is not None else None
    vector = embed_text(f"{title}\n{text}", provider)
    ensure_collection(len(vector), allow_resize=True)
    point_id = str(uuid5(NAMESPACE_URL, f"datapilot:{source_id}"))
    point = {
        "id": point_id,
        "vector": vector,
        "payload": {"source_id": source_id, "title": title, "text": text[:8000], **payload},
    }
    with httpx.Client(timeout=8.0) as client:
        response = client.put(
            f"{base_url}/collections/{COLLECTION}/points",
            params={"wait": "true"},
            json={"points": [point]},
        )
        response.raise_for_status()
    return True


def delete_document(source_id: str) -> bool:
    base_url = qdrant_url()
    if not base_url:
        return False
    point_id = str(uuid5(NAMESPACE_URL, f"datapilot:{source_id}"))
    try:
        with httpx.Client(timeout=8.0) as client:
            response = client.post(
                f"{base_url}/collections/{COLLECTION}/points/delete",
                params={"wait": "true"},
                json={"points": [point_id]},
            )
            response.raise_for_status()
        return True
    except httpx.HTTPError:
        return False


def search_documents(query: str, limit: int = 8, db: Session | None = None) -> list[dict[str, Any]]:
    base_url = qdrant_url()
    if not base_url:
        return []
    try:
        provider = default_embedding_provider(db) if db is not None else None
        vector = embed_text(query, provider)
        ensure_collection(len(vector), allow_resize=False)
        with httpx.Client(timeout=8.0) as client:
            response = client.post(
                f"{base_url}/collections/{COLLECTION}/points/query",
                json={
                    "query": vector,
                    "limit": limit,
                    "with_payload": True,
                    "score_threshold": 0.05,
                },
            )
            response.raise_for_status()
        points = response.json().get("result", {}).get("points", [])
        return [
            {"score": point.get("score", 0), **(point.get("payload") or {})}
            for point in points
        ]
    except (httpx.HTTPError, ValueError):
        return []


def reindex_all(db: Session) -> dict[str, int]:
    """Re-embed every DataAsset and GlossaryDocument under the currently
    active embedding provider. Needed after changing which ModelProvider is
    default/enabled or after editing embedding_model, since ensure_collection()
    only migrates the Qdrant collection lazily on the next write -- existing
    points aren't automatically recomputed with the new model.
    """
    assets = db.scalars(select(DataAsset)).all()
    assets_indexed = 0
    for asset in assets:
        try:
            if index_document(
                asset.id,
                f"{asset.schema_name}.{asset.table_name}",
                f"{asset.description or ''} Columns: " + ", ".join(column.get("name", "") for column in asset.columns),
                {"source_type": "dataset", "schema_name": asset.schema_name, "table_name": asset.table_name, "tags": asset.tags},
                db=db,
            ):
                assets_indexed += 1
        except Exception:
            pass

    documents = db.scalars(select(GlossaryDocument)).all()
    chunks_total = 0
    chunks_indexed = 0
    for document in documents:
        chunks = chunk_glossary_text(document.extracted_text)
        chunks_total += len(chunks)
        for index, chunk in enumerate(chunks):
            try:
                if index_document(
                    f"{document.id}:chunk:{index}",
                    document.title,
                    chunk,
                    {"source_type": "glossary", "document_id": document.id, "chunk_index": index, "chunk_count": len(chunks)},
                    db=db,
                ):
                    chunks_indexed += 1
            except Exception:
                pass

    return {
        "assets_total": len(assets),
        "assets_indexed": assets_indexed,
        "glossary_documents_total": len(documents),
        "glossary_chunks_total": chunks_total,
        "glossary_chunks_indexed": chunks_indexed,
    }
