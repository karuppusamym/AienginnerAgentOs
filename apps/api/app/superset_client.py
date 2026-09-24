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
    # Published-query dashboards pass "query-<artifact uuid>": keep names unique but readable.
    if project_slug.startswith("query-"):
        return f"DataPilot query {project_slug[6:14]} - {suffix}"[:240]
    if project_slug.startswith("asset-"):
        return f"DataPilot dataset {project_slug[6:14]} - {suffix}"[:240]
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
        # Ids, measures and time columns make poor pie slices / categories.
        if lowered_name.endswith("_id") or lowered_type in {"numeric", "timestamp"} or re.search(r"(date|time|_at$|_on$|month|year|day)", lowered_name):
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


def _choose_measure(columns: list[dict[str, Any]]) -> str | None:
    for column in columns:
        name = _column_name(column)
        lowered_type = _column_type(column)
        numeric = lowered_type == "numeric" or any(t in lowered_type for t in ("int", "numeric", "number", "decimal", "float", "double", "real", "money"))
        if name and not name.lower().endswith("_id") and numeric:
            return name
    return None


def _choose_temporal(columns: list[dict[str, Any]]) -> str | None:
    for column in columns:
        lowered_type = _column_type(column)
        if lowered_type == "timestamp" or any(t in lowered_type for t in ("date", "time")):
            return _column_name(column)
    return None


def _metric(measure: str | None) -> Any:
    if not measure:
        return "count"
    return {"expressionType": "SIMPLE", "column": {"column_name": measure}, "aggregate": "SUM", "label": f"SUM({measure})"}


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
    measure = _choose_measure(columns)
    if chart_kind == "big_number_total":
        return {**common, "metric": _metric(measure), "y_axis_format": "SMART_NUMBER"}
    if chart_kind == "echarts_timeseries_bar":
        return {**common, "x_axis": groupby_column, "metrics": [_metric(measure)], "groupby": [], "row_limit": 100,
                "orientation": "vertical", "show_legend": False, "y_axis_format": "SMART_NUMBER"}
    if chart_kind == "echarts_timeseries_line":
        return {**common, "x_axis": groupby_column, "time_grain_sqla": "P1M", "metrics": [_metric(measure)], "groupby": [],
                "row_limit": 10000, "show_legend": False, "y_axis_format": "SMART_NUMBER", "markerEnabled": True}
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
    dashboard_key: str | None = None,
) -> int:
    # Chart names are the lookup key, so they must be unique per *dashboard*: a
    # published query dashboard reusing the project dashboard's names used to
    # take over (and re-point) the project's charts, leaving empty panels.
    name = _chart_name(dashboard_key or project_slug, suffix)
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


def _detach_foreign_charts(client: httpx.Client, token: str, csrf_token: str, internal_url: str, dashboard_id: int, keep: set[int]) -> None:
    """Remove charts from this dashboard that it does not own (left over from the old name collision)."""
    headers = {"Authorization": f"Bearer {token}", "X-CSRFToken": csrf_token}
    attached = client.get(f"{internal_url}/api/v1/dashboard/{dashboard_id}/charts", headers={"Authorization": f"Bearer {token}"})
    if attached.status_code != 200:
        return
    for chart in attached.json().get("result", []):
        chart_id = int(chart["id"])
        if chart_id in keep:
            continue
        detail = client.get(f"{internal_url}/api/v1/chart/{chart_id}", headers={"Authorization": f"Bearer {token}"})
        if detail.status_code != 200:
            continue
        owners = [int(item["id"]) for item in detail.json().get("result", {}).get("dashboards", []) if int(item["id"]) != dashboard_id]
        client.put(f"{internal_url}/api/v1/chart/{chart_id}", headers=headers, json={"dashboards": owners})


def _dashboard_chart_specs(columns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """KPI, the measure by category (bar), share by category (pie), a monthly trend, and a table.

    A numeric measure is summed, never used as pie slices; pies only count rows,
    so negative values cannot distort them.
    """
    measure = _choose_measure(columns)
    label = measure.replace("_", " ") if measure else None
    headline = (label if label.startswith("total") else f"total {label}") if label else "total rows"
    specs: list[dict[str, Any]] = [{"suffix": headline, "kind": "big_number_total"}]
    dimensions = _choose_dimensions(columns)
    if dimensions and measure:
        specs.append({"suffix": f"{label} by {dimensions[0].replace('_', ' ')}", "kind": "echarts_timeseries_bar", "groupby": dimensions[0]})
    for dimension in dimensions[: (1 if measure else 2)]:
        specs.append({"suffix": f"share by {dimension.replace('_', ' ')}", "kind": "pie", "groupby": dimension})
    temporal = _choose_temporal(columns)
    if temporal:
        specs.append({"suffix": f"{label or 'rows'} per month", "kind": "echarts_timeseries_line", "groupby": temporal})
    specs.append({"suffix": "preview", "kind": "table"})
    return specs


def _row_widths(row: list[dict[str, Any]]) -> list[int]:
    if len(row) == 1:
        return [12]
    first_kind = str(row[0]["kind"])
    second_kind = str(row[1]["kind"])
    if first_kind == "big_number_total" or second_kind == "table":
        return [4, 8]
    return [6, 6]


def _dashboard_positions(charts: list[dict[str, Any]]) -> dict[str, Any]:
    root = "ROOT_ID"
    grid = "GRID_ID"
    # Two charts per row (the table gets its own row) so no chart is dropped from the layout.
    rows: list[list[dict[str, Any]]] = []
    for chart in charts:
        if chart["kind"] == "table" or not rows or len(rows[-1]) == 2 or rows[-1][0]["kind"] == "table":
            rows.append([chart])
        else:
            rows[-1].append(chart)
    row_ids = [f"ROW-{index}" for index in range(len(rows))]
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
    # Time-series charts need a real datetime column in Superset (staged text dates cannot take a time grain).
    detail = client.get(f"{internal_url}/api/v1/dataset/{dataset_id}", headers={"Authorization": f"Bearer {token}"})
    datetime_columns = {str(item.get("column_name")) for item in (detail.json().get("result", {}).get("columns", []) if detail.status_code == 200 else []) if item.get("is_dttm")}
    chart_specs = [spec for spec in chart_specs if spec["kind"] != "echarts_timeseries_line" or spec.get("groupby") in datetime_columns]
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
            dashboard_key,
        )
        chart_ids.append(chart_id)
        positioned_charts.append({"id": chart_id, "kind": str(spec["kind"])})
    _detach_foreign_charts(client, token, csrf_token, internal_url, dashboard_id, set(chart_ids))
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


_availability_cache: dict[str, Any] = {"at": 0.0, "value": None}


def superset_availability(max_age_seconds: float = 10.0) -> dict[str, Any]:
    """Cheap reachability check (DNS + /health) so callers can fail early with guidance.

    In Compose, Superset runs only with ``--profile analytics``; without it the
    ``superset`` hostname does not resolve and every call fails with a DNS error.
    """
    import socket
    import time
    from urllib.parse import urlparse

    now = time.monotonic()
    if _availability_cache["value"] is not None and now - _availability_cache["at"] < max_age_seconds:
        return _availability_cache["value"]
    internal_url = os.getenv("SUPERSET_INTERNAL_URL", "").strip().rstrip("/")
    public_url = os.getenv("SUPERSET_PUBLIC_URL", "http://localhost:8088").strip().rstrip("/")
    result: dict[str, Any] = {"available": False, "internal_url": internal_url or None, "public_url": public_url, "reason": ""}
    if not internal_url or not os.getenv("SUPERSET_ADMIN_PASSWORD", ""):
        result["reason"] = "Embedded analytics is not configured (SUPERSET_INTERNAL_URL / SUPERSET_ADMIN_PASSWORD)."
    else:
        parsed = urlparse(internal_url)
        try:
            socket.getaddrinfo(parsed.hostname or "", parsed.port or 80)
            response = httpx.get(f"{internal_url}/health", timeout=3.0)
            result["available"] = response.status_code == 200
            result["reason"] = "" if result["available"] else f"Superset health check returned HTTP {response.status_code}; it may still be starting."
        except socket.gaierror:
            result["reason"] = (
                f"Superset host '{parsed.hostname}' does not resolve: the analytics service is not running. "
                "Start it with `docker compose --profile analytics up -d` and wait until it is healthy."
            )
        except httpx.HTTPError as exc:
            result["reason"] = f"Superset at {internal_url} is not reachable ({type(exc).__name__}); it may still be starting."
    _availability_cache.update(at=now, value=result)
    return result


def describe_superset_error(exc: Exception) -> str:
    """Actionable message for connection-level failures; the raw error otherwise."""
    import socket

    root = exc
    while root.__cause__ is not None or root.__context__ is not None:
        root = root.__cause__ or root.__context__
        if isinstance(root, socket.gaierror):
            break
    if isinstance(root, socket.gaierror) or isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
        _availability_cache.update(at=0.0, value=None)
        return superset_availability()["reason"] or f"Superset is not reachable: {exc}"
    return str(exc)
