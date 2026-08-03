from __future__ import annotations

import hashlib
import math
import os
import re
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import httpx


VECTOR_SIZE = 128
COLLECTION = "datapilot_knowledge"
TOKEN_PATTERN = re.compile(r"[a-zA-Z0-9_]+")


def qdrant_url() -> str | None:
    value = os.getenv("QDRANT_URL", "").strip().rstrip("/")
    return value or None


def embed_text(value: str) -> list[float]:
    vector = [0.0] * VECTOR_SIZE
    for token in TOKEN_PATTERN.findall(value.lower()):
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        index = int.from_bytes(digest[:4], "big") % VECTOR_SIZE
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign * (1.0 + min(len(token), 12) / 12.0)
    norm = math.sqrt(sum(component * component for component in vector)) or 1.0
    return [component / norm for component in vector]


def ensure_collection() -> bool:
    base_url = qdrant_url()
    if not base_url:
        return False
    with httpx.Client(timeout=5.0) as client:
        response = client.get(f"{base_url}/collections/{COLLECTION}")
        if response.status_code == 404:
            response = client.put(
                f"{base_url}/collections/{COLLECTION}",
                json={"vectors": {"size": VECTOR_SIZE, "distance": "Cosine"}},
            )
        response.raise_for_status()
    return True


def index_document(source_id: str, title: str, text: str, payload: dict[str, Any]) -> bool:
    base_url = qdrant_url()
    if not base_url:
        return False
    ensure_collection()
    point_id = str(uuid5(NAMESPACE_URL, f"datapilot:{source_id}"))
    point = {
        "id": point_id,
        "vector": embed_text(f"{title}\n{text}"),
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


def search_documents(query: str, limit: int = 8) -> list[dict[str, Any]]:
    base_url = qdrant_url()
    if not base_url:
        return []
    try:
        ensure_collection()
        with httpx.Client(timeout=8.0) as client:
            response = client.post(
                f"{base_url}/collections/{COLLECTION}/points/query",
                json={
                    "query": embed_text(query),
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
