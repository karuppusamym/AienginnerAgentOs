from __future__ import annotations

import json
import os
import time
from http.cookiejar import CookieJar
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, Request, build_opener


BASE_URL = os.getenv("SUPERSET_URL", "http://superset:8088").rstrip("/")
USERNAME = os.getenv("SUPERSET_ADMIN_USERNAME", "admin")
PASSWORD = os.getenv("SUPERSET_ADMIN_PASSWORD", "ChangeMe123!")
DASHBOARD_SLUG = "datapilot-local-operations"
OPENER = build_opener(HTTPCookieProcessor(CookieJar()))
CSRF_TOKEN: str | None = None


def request(method: str, path: str, token: str | None = None, payload: dict | None = None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Accept": "application/json"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if payload is not None and token and CSRF_TOKEN:
        headers["X-CSRFToken"] = CSRF_TOKEN
    req = Request(f"{BASE_URL}{path}", data=data, headers=headers, method=method)
    with OPENER.open(req, timeout=30) as response:
        body = response.read().decode("utf-8")
        return json.loads(body) if body else {}


def login() -> str:
    global CSRF_TOKEN
    for attempt in range(40):
        try:
            result = request(
                "POST",
                "/api/v1/security/login",
                payload={"username": USERNAME, "password": PASSWORD, "provider": "db", "refresh": True},
            )
            token = result["access_token"]
            csrf = request("GET", "/api/v1/security/csrf_token/", token)
            CSRF_TOKEN = csrf["result"]
            return token
        except (HTTPError, URLError, TimeoutError):
            if attempt == 39:
                raise
            time.sleep(2)
    raise RuntimeError("Superset login did not become available")


def list_results(path: str, token: str) -> list[dict]:
    return request("GET", f"{path}?q=(page_size:200)", token).get("result", [])


def ensure_dataset(token: str, database_id: int) -> int:
    datasets = list_results("/api/v1/dataset/", token)
    existing = next(
        (item for item in datasets if item.get("table_name") == "accounts" and item.get("schema") == "core"),
        None,
    )
    if existing:
        return int(existing["id"])
    created = request(
        "POST",
        "/api/v1/dataset/",
        token,
        {"database": database_id, "schema": "core", "table_name": "accounts"},
    )
    return int(created["id"])


def ensure_dashboard(token: str) -> int:
    dashboards = list_results("/api/v1/dashboard/", token)
    existing = next((item for item in dashboards if item.get("slug") == DASHBOARD_SLUG), None)
    if existing:
        return int(existing["id"])
    created = request(
        "POST",
        "/api/v1/dashboard/",
        token,
        {
            "dashboard_title": "DataPilot Local Operations",
            "slug": DASHBOARD_SLUG,
            "published": True,
            "json_metadata": json.dumps({"timed_refresh_immune_slices": [], "refresh_frequency": 0}),
        },
    )
    return int(created["id"])


def chart_params(viz_type: str, dataset_id: int) -> dict:
    common = {
        "viz_type": viz_type,
        "datasource": f"{dataset_id}__table",
        "adhoc_filters": [],
        "time_range": "No filter",
    }
    if viz_type == "big_number_total":
        return {**common, "metric": "count", "y_axis_format": "SMART_NUMBER"}
    if viz_type == "pie":
        return {
            **common,
            "groupby": ["account_type"],
            "metric": "count",
            "row_limit": 100,
            "sort_by_metric": True,
            "donut": True,
            "show_legend": True,
            "label_type": "key_value",
            "number_format": "SMART_NUMBER",
        }
    return {
        **common,
        "all_columns": ["account_id", "customer_id", "account_type", "status", "opened_at"],
        "row_limit": 100,
        "order_by_cols": [json.dumps(["opened_at", False])],
        "include_search": True,
        "table_timestamp_format": "%Y-%m-%d %H:%M:%S",
    }


def chart_query_context(viz_type: str, dataset_id: int, dashboard_id: int, chart_id: int) -> dict:
    form_data = chart_params(viz_type, dataset_id)
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
    if viz_type == "big_number_total":
        query.update({"columns": [], "metrics": ["count"], "orderby": [["count", False]]})
    elif viz_type == "pie":
        query.update({"columns": ["account_type"], "metrics": ["count"], "orderby": [["count", False]]})
    else:
        query.update(
            {
                "columns": ["account_id", "customer_id", "account_type", "status", "opened_at"],
                "metrics": [],
                "orderby": [["opened_at", False]],
            }
        )
    return {
        "datasource": {"id": dataset_id, "type": "table"},
        "force": False,
        "queries": [query],
        "form_data": form_data,
        "result_format": "json",
        "result_type": "full",
    }


def ensure_chart(token: str, dataset_id: int, dashboard_id: int, name: str, viz_type: str) -> int:
    charts = list_results("/api/v1/chart/", token)
    existing = next((item for item in charts if item.get("slice_name") == name), None)
    payload = {
        "slice_name": name,
        "viz_type": viz_type,
        "datasource_id": dataset_id,
        "datasource_type": "table",
        "dashboards": [dashboard_id],
        "params": json.dumps(chart_params(viz_type, dataset_id)),
    }
    if existing:
        chart_id = int(existing["id"])
    else:
        created = request("POST", "/api/v1/chart/", token, payload)
        chart_id = int(created["id"])
    payload["query_context"] = json.dumps(
        chart_query_context(viz_type, dataset_id, dashboard_id, chart_id)
    )
    request("PUT", f"/api/v1/chart/{chart_id}", token, payload)
    return chart_id


def dashboard_positions(total_id: int, type_id: int, table_id: int) -> dict:
    root = "ROOT_ID"
    grid = "GRID_ID"
    row_one = "ROW-OVERVIEW"
    row_two = "ROW-DETAIL"
    positions = {
        "DASHBOARD_VERSION_KEY": "v2",
        root: {"id": root, "type": "ROOT", "children": [grid]},
        grid: {"id": grid, "type": "GRID", "children": [row_one, row_two], "parents": [root]},
        row_one: {
            "id": row_one,
            "type": "ROW",
            "children": [f"CHART-{total_id}", f"CHART-{type_id}"],
            "meta": {"background": "BACKGROUND_TRANSPARENT"},
            "parents": [root, grid],
        },
        row_two: {
            "id": row_two,
            "type": "ROW",
            "children": [f"CHART-{table_id}"],
            "meta": {"background": "BACKGROUND_TRANSPARENT"},
            "parents": [root, grid],
        },
    }
    for chart_id, width, height, row in (
        (total_id, 4, 20, row_one),
        (type_id, 8, 20, row_one),
        (table_id, 12, 30, row_two),
    ):
        positions[f"CHART-{chart_id}"] = {
            "id": f"CHART-{chart_id}",
            "type": "CHART",
            "children": [],
            "meta": {"chartId": chart_id, "height": height, "width": width},
            "parents": [root, grid, row],
        }
    return positions


def configure_dashboard(token: str, dashboard_id: int, chart_ids: tuple[int, int, int]) -> str:
    request(
        "PUT",
        f"/api/v1/dashboard/{dashboard_id}",
        token,
        {
            "dashboard_title": "DataPilot Local Operations",
            "slug": DASHBOARD_SLUG,
            "published": True,
            "position_json": json.dumps(dashboard_positions(*chart_ids)),
            "json_metadata": json.dumps({"timed_refresh_immune_slices": [], "refresh_frequency": 0}),
        },
    )
    try:
        embedded = request("GET", f"/api/v1/dashboard/{dashboard_id}/embedded", token)
        request(
            "PUT",
            f"/api/v1/dashboard/{dashboard_id}/embedded",
            token,
            {"allowed_domains": ["http://localhost:3001", "http://127.0.0.1:3001"]},
        )
    except HTTPError as error:
        if error.code != 404:
            raise
        embedded = request(
            "POST",
            f"/api/v1/dashboard/{dashboard_id}/embedded",
            token,
            {"allowed_domains": ["http://localhost:3001", "http://127.0.0.1:3001"]},
        )
    result = embedded.get("result", {})
    return str(result.get("uuid") or result.get("dashboard_id") or dashboard_id)


def main() -> None:
    token = login()
    databases = list_results("/api/v1/database/", token)
    database = next(item for item in databases if item.get("database_name") == "DataPilot PostgreSQL")
    dataset_id = ensure_dataset(token, int(database["id"]))
    dashboard_id = ensure_dashboard(token)
    total_id = ensure_chart(token, dataset_id, dashboard_id, "Total accounts", "big_number_total")
    type_id = ensure_chart(token, dataset_id, dashboard_id, "Accounts by type", "pie")
    table_id = ensure_chart(token, dataset_id, dashboard_id, "Recent accounts", "table")
    embedded_id = configure_dashboard(token, dashboard_id, (total_id, type_id, table_id))
    print(json.dumps({"dashboard_id": dashboard_id, "embedded_id": embedded_id, "dataset_id": dataset_id}))


if __name__ == "__main__":
    main()
