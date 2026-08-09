from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode
from uuid import uuid4

import httpx
import jwt


MAX_PREVIEW_COLUMNS = 6
MAX_DASHBOARD_DIMENSIONS = 2


def _embed_allowed_domains() -> list[str]:
    """Return the explicitly trusted portal origins for embedded dashboards."""
    configured = os.getenv("SUPERSET_EMBED_ALLOWED_DOMAINS", "").strip()
    domains = [item.strip().rstrip("/") for item in configured.split(",") if item.strip()]
    # Include both the Compose port and the standard Next.js development port.
    # This prevents an otherwise healthy dashboard from being blank when the web
    # application is run outside Compose.
    return domains or [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
    ]


def _settings() -> tuple[str, str, str, str]:
    internal_url = os.getenv("SUPERSET_INTERNAL_URL", "").strip().rstrip("/")
    public_url = os.getenv("SUPERSET_PUBLIC_URL", "http://localhost:8088").strip().rstrip("/")
    username = os.getenv("SUPERSET_ADMIN_USERNAME", "admin")
    password = os.getenv("SUPERSET_ADMIN_PASSWORD", "")
    if not internal_url or not password:
        raise RuntimeError("Embedded analytics is not configured")
    return internal_url, public_url, username, password


def _admin_session() -> tuple[httpx.Client, str, str, str]:
    internal_url, public_url, username, password = _settings()
    client = httpx.Client(timeout=20.0)
    response = client.post(
        f"{internal_url}/api/v1/security/login",
        json={"username": username, "password": password, "provider": "db", "refresh": True},
    )
    response.raise_for_status()
    token = response.json()["access_token"]
    csrf = client.get(
        f"{internal_url}/api/v1/security/csrf_token/",
        headers={"Authorization": f"Bearer {token}"},
    )
    csrf.raise_for_status()
    return client, token, csrf.json()["result"], public_url


def _slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return cleaned or "project"


def _dashboard_slug(project_slug: str) -> str:
    return f"datapilot-project-{_slugify(project_slug)}"[:140]


def _chart_name(project_slug: str, suffix: str) -> str:
    return f"DataPilot {project_slug} {suffix}"[:240]


def _dashboard_title(project_name: str, dataset: dict[str, Any]) -> str:
    return f"{project_name} analytics: {dataset['schema_name']}.{dataset['table_name']}"[:240]


def _list_results(client: httpx.Client, token: str, internal_url: str, path: str) -> list[dict[str, Any]]:
    response = client.get(
        f"{internal_url}{path}",
        headers={"Authorization": f"Bearer {token}"},
        params={"q": "(page_size:200)"},
    )
    response.raise_for_status()
    return response.json().get("result", [])


def _postgres_database_id(client: httpx.Client, token: str, internal_url: str) -> int:
    databases = _list_results(client, token, internal_url, "/api/v1/database/")
    database = next(
        (item for item in databases if item.get("database_name") == "DataPilot PostgreSQL"),
        None,
    )
    if database is None:
        raise RuntimeError("The DataPilot PostgreSQL database is not registered in Superset")
    return int(database["id"])


def _ensure_dataset(
    client: httpx.Client,
    token: str,
    csrf_token: str,
    internal_url: str,
    database_id: int,
    dataset: dict[str, Any],
) -> int:
    virtual_sql = str(dataset.get("sql") or "").strip()

    def matches(item: dict[str, Any]) -> bool:
        database = item.get("database") or {}
        database_id_value = database.get("id") if isinstance(database, dict) else None
        # Virtual datasets are identified by their stable DataPilot name and
        # exact governed SQL.  A physical relation with the same name must
        # never be reused for a query publication.
        if virtual_sql:
            return (
                item.get("table_name") == dataset["table_name"]
                and (database_id_value is None or int(database_id_value) == database_id)
            )
        return (
            item.get("schema") == dataset["schema_name"]
            and item.get("table_name") == dataset["table_name"]
            and (database_id_value is None or int(database_id_value) == database_id)
        )

    existing = next(
        (item for item in _list_results(client, token, internal_url, "/api/v1/dataset/") if matches(item)),
        None,
    )
    if existing:
        return int(existing["id"])
    create_payload: dict[str, Any] = {
        "database": database_id,
        "schema": dataset["schema_name"],
        "table_name": dataset["table_name"],
    }
    if virtual_sql:
        create_payload["sql"] = virtual_sql
    created = client.post(
        f"{internal_url}/api/v1/dataset/",
        headers={"Authorization": f"Bearer {token}", "X-CSRFToken": csrf_token},
        json=create_payload,
    )
    if created.is_success:
        body = created.json()
        created_id = body.get("id") or (body.get("result") or {}).get("id")
        if created_id is not None:
            return int(created_id)

    # Superset can return 400 for a duplicate datasource during concurrent
    # config/token requests. Re-list once so that an idempotent provision does
    # not turn into an unavailable embedded dashboard.
    if created.status_code in {400, 409}:
        existing = next(
            (item for item in _list_results(client, token, internal_url, "/api/v1/dataset/") if matches(item)),
            None,
        )
        if existing:
            return int(existing["id"])
    try:
        detail = created.json().get("message") or created.json().get("errors")
    except ValueError:
        detail = created.text[:500]
    raise RuntimeError(
        f"Superset could not register {dataset['schema_name']}.{dataset['table_name']}: {detail or created.status_code}"
    )


def _column_name(column: dict[str, Any]) -> str:
    return str(column.get("name", "")).strip()


def _column_type(column: dict[str, Any]) -> str:
    return str(column.get("type", "")).lower()


def _choose_dimensions(columns: list[dict[str, Any]]) -> list[str]:
    chosen: list[str] = []
    for column in columns:
        name = _column_name(column)
        if not name:
            continue
        lowered_name = name.lower()
        lowered_type = _column_type(column)
        if lowered_name.endswith("_id"):
            continue
        if any(token in lowered_type for token in ("char", "text", "string")) or lowered_type in {
            "bool",
            "boolean",
        }:
            chosen.append(name)
        if len(chosen) >= MAX_DASHBOARD_DIMENSIONS:
            break
    return chosen


def _choose_dimension(columns: list[dict[str, Any]]) -> str | None:
    dimensions = _choose_dimensions(columns)
    return dimensions[0] if dimensions else None


def _choose_preview_columns(columns: list[dict[str, Any]]) -> list[str]:
    names = [_column_name(column) for column in columns]
    filtered = [name for name in names if name]
    return filtered[:MAX_PREVIEW_COLUMNS]


def _choose_order_column(columns: list[dict[str, Any]]) -> str | None:
    for column in columns:
        name = _column_name(column)
        lowered_type = _column_type(column)
        if any(token in lowered_type for token in ("date", "time", "timestamp")):
            return name
    preview = _choose_preview_columns(columns)
    return preview[0] if preview else None


def _rls_column(columns: list[dict[str, Any]]) -> str | None:
    names = {(_column_name(column)).lower(): _column_name(column) for column in columns if _column_name(column)}
    for candidate in ("project_id", "datapilot_project_id", "project_slug", "datapilot_project_slug"):
        if candidate in names:
            return names[candidate]
    return None


def _rls_value(dataset: dict[str, Any], column_name: str) -> str | None:
    lowered = column_name.lower()
    if lowered in {"project_slug", "datapilot_project_slug"}:
        return str(dataset.get("project_slug", "")).strip() or None
    return str(dataset.get("project_id", "")).strip() or None


def _build_rls_rules(dataset: dict[str, Any], superset_dataset_id: int) -> tuple[list[dict[str, Any]], str, str | None]:
    columns = list(dataset.get("columns") or [])
    column_name = _rls_column(columns)
    if not column_name:
        return [], "dashboard_scope", None
    value = _rls_value(dataset, column_name)
    if not value:
        return [], "dashboard_scope", None
    escaped = value.replace("'", "''")
    return (
        [{"clause": f"{column_name} = '{escaped}'", "dataset": superset_dataset_id}],
        "guest_token_project_rls",
        column_name,
    )


def _chart_params(
    chart_kind: str,
    dataset_id: int,
    columns: list[dict[str, Any]],
    groupby_column: str | None = None,
) -> dict[str, Any]:
    common = {
        "viz_type": chart_kind,
        "datasource": f"{dataset_id}__table",
        "adhoc_filters": [],
        "time_range": "No filter",
    }
    if chart_kind == "big_number_total":
        return {**common, "metric": "count", "y_axis_format": "SMART_NUMBER"}
    if chart_kind == "pie":
        dimension = groupby_column or _choose_dimension(columns)
        if not dimension:
            raise RuntimeError("A categorical column is required for the distribution chart")
        return {
            **common,
            "groupby": [dimension],
            "metric": "count",
            "row_limit": 100,
            "sort_by_metric": True,
            "donut": True,
            "show_legend": True,
            "label_type": "key_value",
            "number_format": "SMART_NUMBER",
        }
    preview_columns = _choose_preview_columns(columns)
    params = {
        **common,
        "all_columns": preview_columns,
        "row_limit": 100,
        "include_search": True,
        "table_timestamp_format": "%Y-%m-%d %H:%M:%S",
    }
    order_column = _choose_order_column(columns)
    if order_column:
        params["order_by_cols"] = [f'["{order_column}", false]']
    return params


def _chart_query_context(
    chart_kind: str,
    dataset_id: int,
    dashboard_id: int,
    chart_id: int,
    columns: list[dict[str, Any]],
    groupby_column: str | None = None,
) -> dict[str, Any]:
    form_data = _chart_params(chart_kind, dataset_id, columns, groupby_column)
    form_data["dashboardId"] = dashboard_id
    form_data["slice_id"] = chart_id
    query = {
        "filters": [],
        "extras": {"having": "", "where": ""},
        "time_range": "No filter",
        "applied_time_extras": {},
        "annotation_layers": [],
        "row_limit": 100,
        "series_limit": 0,
        "order_desc": True,
        "url_params": {},
        "custom_params": {},
        "custom_form_data": {},
    }
    if chart_kind == "big_number_total":
        query.update({"columns": [], "metrics": ["count"], "orderby": [["count", False]]})
    elif chart_kind == "pie":
        dimension = groupby_column or _choose_dimension(columns)
        if not dimension:
            raise RuntimeError("A categorical column is required for the distribution chart")
        query.update({"columns": [dimension], "metrics": ["count"], "orderby": [["count", False]]})
    else:
        preview_columns = _choose_preview_columns(columns)
        order_column = _choose_order_column(columns)
        query.update({"columns": preview_columns, "metrics": []})
        if order_column:
            query["orderby"] = [[order_column, False]]
    return {
        "datasource": {"id": dataset_id, "type": "table"},
        "force": False,
        "queries": [query],
        "form_data": form_data,
        "result_format": "json",
        "result_type": "full",
    }


def _ensure_chart(
    client: httpx.Client,
    token: str,
    csrf_token: str,
    internal_url: str,
    dataset_id: int,
    dashboard_id: int,
    project_slug: str,
    suffix: str,
    chart_kind: str,
    columns: list[dict[str, Any]],
    groupby_column: str | None = None,
) -> int:
    name = _chart_name(project_slug, suffix)
    existing = next(
        (item for item in _list_results(client, token, internal_url, "/api/v1/chart/") if item.get("slice_name") == name),
        None,
    )
    payload = {
        "slice_name": name,
        "viz_type": chart_kind,
        "datasource_id": dataset_id,
        "datasource_type": "table",
        "dashboards": [dashboard_id],
        "params": json.dumps(_chart_params(chart_kind, dataset_id, columns, groupby_column)),
    }
    headers = {"Authorization": f"Bearer {token}", "X-CSRFToken": csrf_token}
    if existing:
        chart_id = int(existing["id"])
    else:
        created = client.post(f"{internal_url}/api/v1/chart/", headers=headers, json=payload)
        created.raise_for_status()
        chart_id = int(created.json()["id"])
    payload["query_context"] = json.dumps(
        _chart_query_context(
            chart_kind,
            dataset_id,
            dashboard_id,
            chart_id,
            columns,
            groupby_column,
        )
    )
    updated = client.put(f"{internal_url}/api/v1/chart/{chart_id}", headers=headers, json=payload)
    updated.raise_for_status()
    return chart_id


def _dashboard_chart_specs(columns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = [{"suffix": "total rows", "kind": "big_number_total"}]
    for dimension in _choose_dimensions(columns):
        specs.append(
            {
                "suffix": f"by {dimension.replace('_', ' ')}",
                "kind": "pie",
                "groupby": dimension,
            }
        )
    specs.append({"suffix": "preview", "kind": "table"})
    return specs


def _row_widths(row: list[dict[str, Any]]) -> list[int]:
    if len(row) == 1:
        return [12]
    first_kind = str(row[0]["kind"])
    second_kind = str(row[1]["kind"])
    if first_kind == "big_number_total":
        return [4, 8]
    if second_kind == "table":
        return [4, 8]
    return [6, 6]


def _dashboard_positions(charts: list[dict[str, Any]]) -> dict[str, Any]:
    root = "ROOT_ID"
    grid = "GRID_ID"
    row_ids = ["ROW-OVERVIEW", "ROW-DETAIL"]
    rows = [charts[:2], charts[2:]] if len(charts) > 2 else [charts]
    positions: dict[str, Any] = {
        "DASHBOARD_VERSION_KEY": "v2",
        root: {"id": root, "type": "ROOT", "children": [grid]},
        grid: {"id": grid, "type": "GRID", "children": row_ids[: len(rows)], "parents": [root]},
    }
    for row_id, row in zip(row_ids, rows, strict=False):
        positions[row_id] = {
            "id": row_id,
            "type": "ROW",
            "children": [f"CHART-{chart['id']}" for chart in row],
            "meta": {"background": "BACKGROUND_TRANSPARENT"},
            "parents": [root, grid],
        }
        for chart, width in zip(row, _row_widths(row), strict=False):
            height = 30 if chart["kind"] == "table" else 20
            positions[f"CHART-{chart['id']}"] = {
                "id": f"CHART-{chart['id']}",
                "type": "CHART",
                "children": [],
                "meta": {"chartId": chart["id"], "height": height, "width": width},
                "parents": [root, grid, row_id],
            }
    return positions


def _ensure_dashboard(
    client: httpx.Client,
    token: str,
    csrf_token: str,
    internal_url: str,
    project_name: str,
    project_slug: str,
    dataset: dict[str, Any],
    dashboard_key: str | None = None,
) -> dict[str, Any]:
    # A dashboard's Superset slug must uniquely identify *what it shows*, not
    # just the project it belongs to. The project's single primary dashboard
    # (its mapped/staged dataset) keys off project_slug alone, as before. A
    # published SQL/notebook query instead passes its own dashboard_key
    # (derived from the source artifact id) so it provisions a dedicated
    # dashboard rather than silently overwriting the project's main one —
    # both previously resolved to the identical `datapilot-project-{slug}`
    # slug and collided.
    slug = _dashboard_slug(dashboard_key or project_slug)
    title = _dashboard_title(project_name, dataset)
    dashboards = _list_results(client, token, internal_url, "/api/v1/dashboard/")
    existing = next((item for item in dashboards if item.get("slug") == slug), None)
    headers = {"Authorization": f"Bearer {token}", "X-CSRFToken": csrf_token}
    if existing:
        dashboard_id = int(existing["id"])
    else:
        created = client.post(
            f"{internal_url}/api/v1/dashboard/",
            headers=headers,
            json={
                "dashboard_title": title,
                "slug": slug,
                "published": True,
                "json_metadata": json.dumps(
                    {"timed_refresh_immune_slices": [], "refresh_frequency": 0}
                ),
            },
        )
        created.raise_for_status()
        dashboard_id = int(created.json()["id"])

    database_id = _postgres_database_id(client, token, internal_url)
    dataset_id = _ensure_dataset(client, token, csrf_token, internal_url, database_id, dataset)
    columns = list(dataset.get("columns") or [])
    chart_specs = _dashboard_chart_specs(columns)
    chart_ids: list[int] = []
    positioned_charts: list[dict[str, Any]] = []
    for spec in chart_specs:
        chart_id = _ensure_chart(
            client,
            token,
            csrf_token,
            internal_url,
            dataset_id,
            dashboard_id,
            project_slug,
            str(spec["suffix"]),
            str(spec["kind"]),
            columns,
            str(spec["groupby"]) if spec.get("groupby") else None,
        )
        chart_ids.append(chart_id)
        positioned_charts.append({"id": chart_id, "kind": str(spec["kind"])})
    updated = client.put(
        f"{internal_url}/api/v1/dashboard/{dashboard_id}",
        headers=headers,
        json={
            "dashboard_title": title,
            "slug": slug,
            "published": True,
            "position_json": json.dumps(_dashboard_positions(positioned_charts)),
            "json_metadata": json.dumps(
                {"timed_refresh_immune_slices": [], "refresh_frequency": 0}
            ),
        },
    )
    updated.raise_for_status()
    embedded = client.get(
        f"{internal_url}/api/v1/dashboard/{dashboard_id}/embedded",
        headers={"Authorization": f"Bearer {token}"},
    )
    if embedded.status_code == 404:
        embedded = client.post(
            f"{internal_url}/api/v1/dashboard/{dashboard_id}/embedded",
            headers=headers,
            json={"allowed_domains": _embed_allowed_domains()},
        )
        embedded.raise_for_status()
    else:
        embedded.raise_for_status()
        saved = client.put(
            f"{internal_url}/api/v1/dashboard/{dashboard_id}/embedded",
            headers=headers,
            json={"allowed_domains": _embed_allowed_domains()},
        )
        saved.raise_for_status()
    result = embedded.json().get("result") or {}
    embedded_id = result.get("uuid")
    if not embedded_id:
        raise RuntimeError("The project analytics dashboard is not enabled for embedding")
    rls_rules, access_mode, rls_column = _build_rls_rules(dataset, dataset_id)
    return {
        "dashboard_id": dashboard_id,
        "dashboard_slug": slug,
        "embedded_id": str(embedded_id),
        "dashboard_title": title,
        "dataset_relation": f"{dataset['schema_name']}.{dataset['table_name']}",
        "superset_dataset_id": dataset_id,
        "chart_ids": chart_ids,
        "chart_count": len(chart_ids),
        "access_mode": access_mode,
        "rls": rls_rules,
        "rls_column": rls_column,
    }


def get_embed_configuration(
    project_name: str,
    project_slug: str,
    dataset: dict[str, Any],
    dashboard_key: str | None = None,
) -> dict[str, Any]:
    internal_url, public_url, _, _ = _settings()
    client, token, csrf_token, _ = _admin_session()
    try:
        dashboard = _ensure_dashboard(
            client, token, csrf_token, internal_url, project_name, project_slug, dataset, dashboard_key
        )
        return {**dashboard, "superset_domain": public_url, "project_slug": project_slug}
    finally:
        client.close()


def create_guest_token(
    project_name: str,
    project_slug: str,
    dataset: dict[str, Any],
    user_id: str,
    _email: str,
    name: str,
    dashboard_key: str | None = None,
) -> dict[str, str]:
    internal_url, _, _, _ = _settings()
    client, token, csrf_token, _ = _admin_session()
    try:
        dashboard = _ensure_dashboard(
            client, token, csrf_token, internal_url, project_name, project_slug, dataset, dashboard_key
        )
        name_parts = name.strip().split(maxsplit=1)
        response = client.post(
            f"{internal_url}/api/v1/security/guest_token/",
            headers={
                "Authorization": f"Bearer {token}",
                "X-CSRFToken": csrf_token,
            },
            json={
                "resources": [{"type": "dashboard", "id": dashboard["embedded_id"]}],
                "rls": list(dashboard.get("rls") or []),
                "user": {
                    "username": f"datapilot-{project_slug}-{user_id}"[:120],
                    "first_name": name_parts[0] if name_parts else "DataPilot",
                    "last_name": name_parts[1] if len(name_parts) > 1 else "User",
                },
            },
        )
        response.raise_for_status()
        return {"token": response.json()["token"]}
    finally:
        client.close()


def create_editor_url(user_id: str, email: str, name: str, role: str) -> dict[str, Any]:
    if role != "admin":
        raise PermissionError("Superset editor access requires the admin role")

    public_url = os.getenv("SUPERSET_PUBLIC_URL", "http://localhost:8088").strip().rstrip("/")
    secret = os.getenv("SUPERSET_EDITOR_SSO_SECRET", "").strip()
    if not secret:
        raise RuntimeError("Superset editor single sign-on is not configured")

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=30)
    token = jwt.encode(
        {
            "iss": "datapilot",
            "aud": "superset-editor",
            "sub": user_id,
            "email": email,
            "name": name,
            "role": role,
            "iat": now,
            "exp": expires_at,
            "jti": str(uuid4()),
        },
        secret,
        algorithm="HS256",
    )
    return {
        "url": f"{public_url}/datapilot/editor-login?{urlencode({'token': token})}",
        "expires_in": 30,
    }
