# Embedded analytics: dashboards, datasets and scope

This page covers how the **Governed analytics** page (Superset embedded without another login)
decides what to show, and why the choices are scoped the way they are.

## 1. What you can open

The page has a picker on the left and the embedded dashboard on the right. Every entry belongs
to the **current project**.

| Group | What it is | How it is created | Approval |
|---|---|---|---|
| **Project dashboard** | The project's default view, built on its primary dataset: the latest mapped or staged file, otherwise the best local dataset | Automatically, the first time the page opens | No (catalogued local data) |
| **Published queries** | One dashboard per saved SQL or notebook query, e.g. "Accounts by type" | *Publish to Superset* from SQL or Notebooks, then approval | **Yes**, a `publish_superset_query` approval |
| **Datasets, grouped by source** (Local files, DataPilot PostgreSQL, …) | Any catalogued dataset that is physically in the analytics database, e.g. `core.accounts` | On demand, the first time it is selected | No (same trust as the project dashboard) |

Each dashboard gets the same data-driven chart set:
- a headline total
- the measure by category (bar)
- the share by category (pie)
- a monthly trend, when a real date column exists
- a table

The last selection is remembered per project in the browser, so returning users land where they
left off. The filter box searches entry titles, columns and sources.

## 2. Why the scope is the project (and grouped by source)

- **Project is the security boundary.** Membership, roles, RLS and audit are all per project.
  Every guest token is minted for *one* dashboard of *this* project, and switching projects
  switches the list. A cross-project picker would need cross-project permissions that don't
  exist.
- **Source is how users think about data.** Within a project, datasets are grouped by source so
  "the file I uploaded" and "the warehouse table" are easy to tell apart.
- **Published queries are listed separately.** They are *curated* views that went through
  approval, while datasets are *raw* catalog tables.
- **Connector sources are not listed.** SQL Server, Oracle, BigQuery and MCP tools aren't
  registered in this Superset instance, which only reads the local analytics database. To chart
  connector data, stage it (Files → schedule) or save a local SQL query and publish it.

## 3. Governance on dataset dashboards

`POST /analytics/datasets/{asset_id}/guest-token` checks, in order:

1. The dataset belongs to the current project.
2. It is local and physically exists.
3. It is not a DataPilot metadata table (users, providers, audit, …).
4. **Restricted** datasets are admin-only; they are shown with a lock for others.
5. **PII-named columns** (email, phone, national IDs, …) are left out of the charts and the
   preview table.
6. Superset is reachable; otherwise the API returns 503 with the start command.
7. Every open is audited as `analytics.dataset_dashboard_opened`.

The dashboard slug is keyed per dataset (`asset-<id>`) and chart names are keyed per dashboard,
so dataset, query and project dashboards never take each other's charts.

## 4. API

| Endpoint | Purpose |
|---|---|
| `GET /analytics/dashboards` | The picker's list: `primary`, `published[]`, `datasets[]` (source, rows, columns, sensitivity, default flag, restricted flag) and Superset availability |
| `GET /analytics/config` + `POST /analytics/guest-token` | Project dashboard |
| `POST /analytics/queries/{artifact_id}/guest-token` | Published query dashboard |
| `POST /analytics/datasets/{asset_id}/guest-token` | Dataset dashboard (created on demand) |
| `GET /analytics/status` | Is Superset reachable, and why not |

## 5. Usability options considered

| Option | Verdict |
|---|---|
| **Picker with the project dashboard, published queries and datasets** | **Built.** One place to find every chartable thing in the project, with no Superset knowledge needed. |
| Several dashboards on one page (tiles or tabs) | Not built. Each embedded dashboard is a full iframe with its own guest token, so two or more at once are heavy and hard to read. The picker plus a remembered selection covers the common "switch between views" case. |
| Choosing a dataset directly | **Built** (the "Datasets" groups). Useful for exploring before a query is worth publishing. |
| Building one dashboard across several datasets | Do it in the Superset editor (admins: *Open editor*). DataPilot keeps its generated dashboards simple and regenerable. |
| A project default set by the owner | Next step: a server-side "pin as project default" (today the default is the latest mapped dataset, marked with a star). |
| Sharing a link to a specific dashboard | Next step: put the selection in the URL (`/superset?view=dataset:<id>`) as well as in the browser. |
