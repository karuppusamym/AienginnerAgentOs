from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import DataAsset, GlossaryDocument, SemanticJoinPolicy, SemanticMetric
from .vector_store import search_documents


TOKEN_PATTERN = re.compile(r"[a-zA-Z0-9_]+")


def _stable_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def normalize_query(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def context_signature(conversation_context: list[dict[str, str]]) -> str:
    compact = [
        {
            "role": str(item.get("role", ""))[:24],
            "content": normalize_query(str(item.get("content", "")))[:500],
        }
        for item in conversation_context[-16:]
        if item.get("role") in {"system", "user", "assistant"} and str(item.get("content", "")).strip()
    ]
    return _stable_hash(compact or ["no-context"])


def project_grounding_signature(db: Session, project_id: str) -> str:
    assets = db.scalars(
        select(DataAsset).where(DataAsset.project_id == project_id).order_by(DataAsset.schema_name, DataAsset.table_name)
    ).all()
    metrics = db.scalars(
        select(SemanticMetric).where(SemanticMetric.project_id == project_id).order_by(SemanticMetric.name)
    ).all()
    joins = db.scalars(
        select(SemanticJoinPolicy).where(SemanticJoinPolicy.project_id == project_id).order_by(SemanticJoinPolicy.id)
    ).all()
    payload = {
        "assets": [
            {
                "id": asset.id,
                "connector_id": asset.connector_id,
                "source_name": asset.source_name,
                "relation": f"{asset.schema_name}.{asset.table_name}",
                "asset_type": asset.asset_type,
                "row_count": asset.row_count,
                "columns": asset.columns,
                "tags": asset.tags,
                "description": asset.description,
            }
            for asset in assets
        ],
        "metrics": [
            {
                "id": metric.id,
                "name": metric.name,
                "formula": metric.formula,
                "grain": metric.grain,
                "dimensions": metric.dimensions,
                "synonyms": metric.synonyms,
                "status": metric.status,
            }
            for metric in metrics
        ],
        "joins": [
            {
                "id": policy.id,
                "left_asset_id": policy.left_asset_id,
                "right_asset_id": policy.right_asset_id,
                "left_column": policy.left_column,
                "right_column": policy.right_column,
                "join_type": policy.join_type,
                "status": policy.status,
            }
            for policy in joins
        ],
    }
    return _stable_hash(payload)


def _token_overlap_score(haystack: str, tokens: set[str], normalized_query: str) -> float:
    if not haystack:
        return 0.0
    lowered = haystack.lower()
    matches = sum(1 for token in tokens if token in lowered)
    if normalized_query and normalized_query in lowered:
        matches += max(2, len(tokens) // 2)
    return float(matches)


def project_asset_search(db: Session, project_id: str, query: str, limit: int = 8) -> list[dict[str, Any]]:
    normalized_query = normalize_query(query)
    tokens = set(TOKEN_PATTERN.findall(normalized_query))
    assets = db.scalars(
        select(DataAsset).where(DataAsset.project_id == project_id).order_by(DataAsset.schema_name, DataAsset.table_name)
    ).all()
    asset_lookup = {asset.id: asset for asset in assets}
    results: list[dict[str, Any]] = []
    seen: set[str] = set()

    for hit in search_documents(query, limit=max(limit * 2, 8)):
        asset = asset_lookup.get(str(hit.get("source_id", "")))
        if asset is None:
            continue
        relation = f"{asset.schema_name}.{asset.table_name}"
        seen.add(asset.id)
        results.append(
            {
                "asset_id": asset.id,
                "relation": relation,
                "asset_type": asset.asset_type,
                "row_count": asset.row_count,
                "columns": [str(column.get("name", "")) for column in asset.columns[:12]],
                "tags": asset.tags,
                "description": asset.description,
                "score": round(float(hit.get("score", 0.0)), 4),
                "match_type": "vector",
            }
        )

    for asset in assets:
        relation = f"{asset.schema_name}.{asset.table_name}"
        haystack = " ".join(
            [
                relation,
                asset.source_name,
                asset.description or "",
                " ".join(asset.tags),
                " ".join(str(column.get("name", "")) for column in asset.columns),
                " ".join(str(column.get("business_name", "")) for column in asset.columns),
                " ".join(str(column.get("description", "")) for column in asset.columns),
            ]
        )
        score = _token_overlap_score(haystack, tokens, normalized_query)
        if score <= 0:
            continue
        entry = {
            "asset_id": asset.id,
            "relation": relation,
            "asset_type": asset.asset_type,
            "row_count": asset.row_count,
            "columns": [str(column.get("name", "")) for column in asset.columns[:12]],
            "tags": asset.tags,
            "description": asset.description,
            "score": round(score, 4),
            "match_type": "keyword",
        }
        if asset.id in seen:
            for existing in results:
                if existing["asset_id"] == asset.id:
                    existing["score"] = round(max(float(existing["score"]), score), 4)
                    if existing["match_type"] != "vector":
                        existing["match_type"] = "hybrid"
                    break
        else:
            results.append(entry)

    results.sort(key=lambda item: (float(item["score"]), item["relation"]), reverse=True)
    return results[:limit]


def semantic_matches(db: Session, project_id: str, query: str, limit: int = 5) -> dict[str, list[dict[str, Any]]]:
    normalized_query = normalize_query(query)
    tokens = set(TOKEN_PATTERN.findall(normalized_query))
    metrics = db.scalars(
        select(SemanticMetric).where(SemanticMetric.project_id == project_id).order_by(SemanticMetric.name)
    ).all()
    asset_lookup = {
        asset.id: f"{asset.schema_name}.{asset.table_name}"
        for asset in db.scalars(select(DataAsset).where(DataAsset.project_id == project_id)).all()
    }
    joins = db.scalars(
        select(SemanticJoinPolicy)
        .where(SemanticJoinPolicy.project_id == project_id, SemanticJoinPolicy.status == "approved")
        .order_by(SemanticJoinPolicy.id)
    ).all()

    matched_metrics: list[dict[str, Any]] = []
    for metric in metrics:
        haystack = " ".join(
            [
                metric.name,
                metric.description or "",
                metric.formula,
                metric.grain,
                metric.owner,
                " ".join(metric.dimensions),
                " ".join(metric.synonyms),
            ]
        )
        score = _token_overlap_score(haystack, tokens, normalized_query)
        if score <= 0:
            continue
        matched_metrics.append(
            {
                "name": metric.name,
                "description": metric.description,
                "formula": metric.formula,
                "grain": metric.grain,
                "dimensions": metric.dimensions[:8],
                "synonyms": metric.synonyms[:8],
                "score": round(score, 4),
            }
        )

    matched_metrics.sort(key=lambda item: (float(item["score"]), item["name"]), reverse=True)

    matched_joins: list[dict[str, Any]] = []
    for policy in joins:
        left_relation = asset_lookup.get(policy.left_asset_id, policy.left_asset_id)
        right_relation = asset_lookup.get(policy.right_asset_id, policy.right_asset_id)
        haystack = " ".join(
            [
                left_relation,
                right_relation,
                policy.left_column,
                policy.right_column,
                policy.join_type,
                policy.description or "",
            ]
        )
        score = _token_overlap_score(haystack, tokens, normalized_query)
        if score <= 0:
            continue
        matched_joins.append(
            {
                "policy_id": policy.id,
                "left_relation": left_relation,
                "right_relation": right_relation,
                "left_column": policy.left_column,
                "right_column": policy.right_column,
                "join_type": policy.join_type,
                "description": policy.description,
                "score": round(score, 4),
            }
        )

    matched_joins.sort(
        key=lambda item: (float(item["score"]), item["left_relation"], item["right_relation"]),
        reverse=True,
    )
    return {"metrics": matched_metrics[:limit], "joins": matched_joins[:limit]}


def glossary_matches(db: Session, project_id: str, query: str, limit: int = 4) -> list[dict[str, Any]]:
    """Retrieve grounding passages from uploaded SOP/glossary documents.

    Mirrors project_asset_search's vector-hit pattern but scoped to
    GlossaryDocument rows for this project instead of DataAsset rows. Each
    document is chunked and indexed with source_id
    f"{document_id}:chunk:{n}" and payload source_type="glossary" (see
    upload_glossary_document in routers/workspace.py). search_documents()
    has no server-side project filter, so hits are cross-checked here
    against this project's own GlossaryDocument ids before being surfaced —
    otherwise a glossary term uploaded in one project could leak into
    another project's SQL-generation context.
    """
    documents = {
        document.id: document
        for document in db.scalars(
            select(GlossaryDocument).where(GlossaryDocument.project_id == project_id)
        ).all()
    }
    if not documents:
        return []
    results: list[dict[str, Any]] = []
    for hit in search_documents(query, limit=max(limit * 4, 12)):
        if hit.get("source_type") != "glossary":
            continue
        document = documents.get(str(hit.get("document_id", "")))
        if document is None:
            continue
        results.append(
            {
                "document_id": document.id,
                "title": document.title,
                "chunk_index": hit.get("chunk_index", 0),
                "text": str(hit.get("text", ""))[:1200],
                "score": round(float(hit.get("score", 0.0)), 4),
            }
        )
    results.sort(key=lambda item: float(item["score"]), reverse=True)
    return results[:limit]


def grounding_context(db: Session, project_id: str, question: str, limit: int = 5) -> dict[str, Any]:
    catalog_matches = project_asset_search(db, project_id, question, limit=limit)
    semantic = semantic_matches(db, project_id, question, limit=limit)
    return {
        "catalog_matches": catalog_matches,
        "vector_hits": [item for item in catalog_matches if item["match_type"] in {"vector", "hybrid"}][:limit],
        "semantic_matches": semantic["metrics"],
        "join_matches": semantic["joins"],
        "glossary_matches": glossary_matches(db, project_id, question, limit=min(limit, 4)),
    }


def grounding_prompt_text(context: dict[str, Any]) -> str:
    sections: list[str] = []
    catalog_matches = context.get("catalog_matches", [])
    if catalog_matches:
        sections.append(
            "Retrieved catalog context:\n"
            + "\n".join(
                f"- {item['relation']} ({item['match_type']}, score={item['score']}, columns={', '.join(item['columns'][:8]) or 'none'})"
                for item in catalog_matches[:5]
            )
        )
    semantic_matches = context.get("semantic_matches", [])
    if semantic_matches:
        sections.append(
            "Relevant semantic metrics:\n"
            + "\n".join(
                f"- {item['name']}: {item['formula']} | grain={item['grain']} | dimensions={', '.join(item['dimensions'][:6]) or 'none'}"
                for item in semantic_matches[:4]
            )
        )
    join_matches = context.get("join_matches", [])
    if join_matches:
        sections.append(
            "Approved semantic joins:\n"
            + "\n".join(
                f"- {item['left_relation']} {item['join_type'].upper()} JOIN {item['right_relation']} ON {item['left_column']} = {item['right_column']}"
                for item in join_matches[:4]
            )
        )
    glossary_hits = context.get("glossary_matches", [])
    if glossary_hits:
        sections.append(
            "Relevant business glossary / SOP passages:\n"
            + "\n".join(
                f"- [{item['title']}] {item['text'][:400]}"
                for item in glossary_hits[:4]
            )
        )
    return "\n\n".join(sections) or "No additional retrieved context."


def summarize_value(value: Any, depth: int = 0) -> Any:
    if depth >= 3:
        return str(value)[:500]
    if isinstance(value, dict):
        return {
            str(key): summarize_value(item, depth + 1)
            for key, item in list(value.items())[:8]
        }
    if isinstance(value, list):
        summarized = [summarize_value(item, depth + 1) for item in value[:5]]
        if len(value) > 5:
            summarized.append({"truncated_items": len(value) - 5})
        return summarized
    if isinstance(value, str):
        return value[:500]
    return value


def summarize_tool_result(result: Any) -> Any:
    if isinstance(result, dict):
        summary: dict[str, Any] = {}
        for key in ("columns", "row_count", "count", "duration_ms", "status", "error", "truncated", "limit"):
            if key in result:
                summary[key] = summarize_value(result[key], 1)
        if "rows" in result:
            summary["rows"] = summarize_value(result["rows"], 1)
        if not summary:
            summary = summarize_value(result, 1)
        return summary
    return summarize_value(result, 1)
