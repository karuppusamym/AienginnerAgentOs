# DataPilot UX consolidation

**Question:** there are many screens and features. What can be merged, hidden or removed so people can actually find and use them?

**Short answer:** almost nothing is dead. The problem is **presentation**: 19 flat destinations, labels named after internal components ("Tool registry", "Superset", "Workspace"), and the same concept in 2–4 places. The fix, in order:

1. **Group the sidebar by user job** (5 areas) and show each role a short default list, with everything else behind a persisted **Show advanced** toggle. *Done in this change; no route or feature removed.*
2. **Merge the real duplicates.** There are four: Agents/Tools, the learning split across Learning and Admin → Governance, "saved query" spread over four stores, and two "ask" entry points. *Agents & tools, Learning and the Home → Analysis hand-off are done (§8). The Save menu is owned by the SQL/Notebooks work.*
3. **Remove nothing yet.** Unused API endpoints are machine interfaces (MCP, external REST, health) or backend features with no UI yet. They are not dead code (§5).

---

## 1. Inventory (before this change)

The sidebar had 19 items in 5 groups. "Governance & agents" and "Administration" started collapsed, and in the collapsed desktop rail (the default state) their items could not be reached at all, because the rail hides group headers.

| Route | Nav label (before) | Purpose (from the view) | Route gate (`canView`) | API permission needed to do anything |
|---|---|---|---|---|
| `/workspace` | Workspace | Health, recent jobs, recommendations, "What do you want to build or understand?" launches a governed agent objective (`/overview`, `/recommendations`, `/security-overview`, `/agents/runs`) | all | read for all; launching needs `jobs:write` |
| `/analysis[/<id>]` | Analysis | 3-panel chat: threads, answer with charts, inspector (route, Jev, learning); publish to Superset; save to notebook | all | `conversation:write` (analyst+) |
| `/datasets` | Datasets | Catalog explorer, profiling, relationship explorer, Data Package import/export, AI metadata | all | `catalog:read` / `catalog:write` |
| `/files` | Files | Profile, map and stage local files | all | `catalog:write` (engineer+) |
| `/sql` | SQL | Grounded SQL generate/explain/execute. Saves to **artifact**, **verified query**, **notebook**, or **published query** | all | `query:write` for generate (viewer blocked) |
| `/notebooks` | Notebooks | Versioned SQL + notes cells, run, publish to Superset | all | `query:write` |
| `/pipelines` | Pipelines | Generate/deploy transformations, lineage, **schedules** | all | `pipeline:write` (engineer+) |
| `/jobs` | Jobs | Run trace for agent runs, scans and schedules; retry, cancel, diagnose | all | `jobs:write` for actions |
| `/artifacts` | Artifacts | Versioned SQL, workflows, quality rules, prompts, runbooks, DDL suggestions; diff, review, comments | all | read for all |
| `/quality` | Quality | Rules, runs, failed rows, AI rule suggestions | all | `quality:write` (engineer+) |
| `/superset` | Superset | Embedded dashboards: project dashboard, published queries, datasets | all | read; editor session admin-only |
| `/approvals` | Approvals | Inbox for controlled writes, schedules, external actions; auto-review | all | decisions need `jobs:write` (engineer+; separation of duties optional) |
| `/tools` | Tool registry | Tabs: *Internal integrations* (**renders `AgentsView registryOnly`**), *External data tools* (`GatewayAdmin`), *Invocation history* (admin) | admin, engineer | `registry:write` |
| `/agents` | Agents | "Agent registry and tool marketplace": agents, versions, scorecards **and the same internal tool list** | all | `registry:write` for edits |
| `/semantic` | Semantic layer | Approved metrics and join policies | all | `semantic:write` (engineer+) |
| `/evaluations` | Evaluations | SQL grounding / agent-run evaluation sets, run, score | all | engineer+ in practice |
| `/learning` | Learning | Tabs: verified queries, prompt optimisation (GEPA), performance & DDL suggestions, **router (tool choice)** | admin, engineer | engineer+ |
| `/admin` | Admin | Connectors, models, projects, users, audit, auth, **Governance: prompts, retention, learning-loop suggestions, router (route) evaluation** | admin | admin |
| `/architecture` | Architecture | Static "how it fits together" explainer | all | none |

## 2. Overlaps found (evidence from the code)

| Overlap | Evidence | Verdict |
|---|---|---|
| **Agents vs Tool registry** | `ToolsView.tsx` "Internal integrations" tab is `<AgentsView registryOnly />`. `/agents` renders the same `AgentsView` with agents plus the tool marketplace. Both call `/tools`, `/tools/{id}/versions`, `/tools/{id}/execute`. | Real duplicate. Merge (§4.1). |
| **Learning vs Admin → Governance** | Route evaluation (`POST /router/evaluate`) is in `admin.tsx`. Tool-choice evaluation (`POST /router/evaluate-tools`) is on the Learning → Router tab. Learning-loop suggestions (`/learning-suggestions`) are in Admin → Governance. Verified queries and GEPA are in Learning. | One concept split across two screens. Merge (§4.2). |
| **Evaluations vs Learning** | Learning's prompt optimisation reads evaluation sets (`useEvaluationSets`). Agent scorecards and the publish gate also depend on evaluations. | Related, but Evaluations is a set-up step for Learning. Merge as a tab later (§4.2). Keep the route. |
| **Saved SQL in four places** | From `SQLView.tsx`: `POST /artifacts` (saved SQL artifact), `POST /verified-queries` (Learning memory), `POST /notebooks`, `POST /analytics/publish-sql` (Superset published query). | Four stores, and each one exists for a reason (review, reuse by the model, iteration, dashboards). Users mainly need a single **Save** menu with clear outcomes (§4.3), not fewer stores. |
| **Two "ask" entry points** | Home's objective box posts `/agents/runs`. Analysis also posts `/agents/runs` for agent actions and `/conversations/*` for chat. | Same user intent. Home should hand off to Analysis (§4.4). |
| **Jobs vs Approvals vs Pipelines schedules** | Pipelines creates `/schedules` and runs them; runs show in Jobs; gated steps show in Approvals. | Different jobs (design, operate, decide). Keep all three, but link across them. The approvals badge already exists. |
| **Semantic vs Datasets vs Files** | Datasets owns the relationship explorer (`/semantic/explorer`). Semantic owns metrics and joins. Files feeds Datasets. | Adjacent steps of one pipeline. Group them under **Data**; no merge. |
| **Superset vs published queries** | Published queries are created in SQL, Notebooks and Analysis, and are viewed in Superset (`/analytics/dashboards`). | Not a duplicate: publish happens in context, viewing happens in Dashboards. Relabel only. |
| **Home vs Analysis** | Home is an operator dashboard (health, jobs, security). Analysts land on Analysis. | Keep Home for admin/engineer. Hide it from analyst/viewer by default. |

## 3. Target information architecture

Five areas by user job. Analytics (Superset) sits in **Analyze** rather than on its own because an analyst's job is "ask, then look at the dashboard". A one-item section would add a header without adding meaning.

| Area | Items (new label → route) | Who it is for |
|---|---|---|
| **Analyze** | Home → `/workspace`, Analysis → `/analysis`, Dashboards → `/superset` | everyone |
| **Data** | Datasets, Files, Semantic layer, Quality | engineer (write), analyst/viewer (read) |
| **Build** | SQL, Notebooks, Pipelines, Artifacts | analyst (SQL/Notebooks), engineer |
| **Automate** | Agents & tools (was Agents + Tool registry), Jobs | engineer, admin |
| **Govern** | Approvals, Learning (now includes Evaluations), Admin, Architecture | reviewer, engineer, admin |

### Per-role landing and default sidebar

`canView` (the route gate) is unchanged. The default sidebar is a presentation choice layered on top of it (`roleNav` / `isPrimaryNav` in `lib/constants.tsx`).

| Role | Lands on | Default sidebar | Behind "Show advanced" (still reachable by URL) |
|---|---|---|---|
| admin | Home | all 19 | none (no toggle shown) |
| engineer | Pipelines | 17: everything except Admin (gated) and Architecture | Architecture |
| analyst | Analysis | 7: Analysis, Dashboards, Datasets, Semantic layer, SQL, Notebooks, Artifacts | Home, Files, Quality, Pipelines, Agents, Jobs, Approvals, Evaluations, Architecture |
| viewer | Datasets | 4: Datasets, Semantic layer, Dashboards, Artifacts | Home, Analysis, Files, Quality, SQL, Notebooks, Pipelines, Agents, Jobs, Approvals, Evaluations, Architecture |

The analyst and viewer lists follow `roles.py`. An analyst has `catalog:read`, `query:read`, `semantic:read`, `conversation:write` and `feedback:write`, with no pipeline, quality, registry or jobs writes. A viewer is read-only and cannot write to conversations, so Analysis would only produce errors for them by default.

### Before / after

| Before (group → label) | After (area → label) | Change |
|---|---|---|
| Overview → Workspace | Analyze → **Home** | relabel; hidden by default for analyst/viewer |
| Overview → Analysis | Analyze → Analysis | none |
| Governance & agents → Superset | Analyze → **Dashboards** | relabel and move next to Analysis |
| Data workspace → Datasets / Files | Data → Datasets / Files | Files hidden by default for analyst/viewer |
| Governance & agents → Semantic layer | Data → Semantic layer | move: it is data modelling, not governance |
| Build & operate → Quality | Data → Quality | move next to the data it checks |
| Data workspace → SQL / Notebooks | Build → SQL / Notebooks | move |
| Build & operate → Pipelines / Artifacts | Build → Pipelines / Artifacts | move |
| Governance & agents → Agents / Tool registry | Automate → Agents / Tool registry | now adjacent (merge candidate, §4.1) |
| Build & operate → Jobs | Automate → Jobs | move next to what produces runs |
| Build & operate → Approvals | Govern → Approvals | move; pending-count badge kept |
| Governance & agents → Evaluations / Learning | Govern → Evaluations / Learning | now adjacent (merge candidate, §4.2) |
| Administration → Admin / Architecture | Govern → Admin / Architecture | Architecture is "advanced" for engineers |
| 2 groups collapsed; unreachable in collapsed rail | all sections open; the rail lists every visible item with hairline separators | usability fix |

## 4. Recommended merges (with devil's advocate)

> Status: §4.1, §4.2 and §4.4 are **done** (see §8). §4.3 belongs to the SQL/Notebooks owners.

### 4.1 Merge "Agents" and "Tool registry" into one **Agents & tools** area (done)
- **Proposal:** `/agents` gets tabs *Agents · Internal tools · External data tools · Invocation history*. `/tools` redirects to `/agents?tab=tools`, and deep links keep working through a redirect.
- **Why:** the internal tool list is rendered twice from the same component, and users can't tell which page is the source of truth.
- **Devil's advocate:** the external gateway (grants, client tokens, quotas) is a security surface for admins, and mixing it with agent authoring could invite accidental grants. *Answer:* keep the External and History tabs admin/engineer-gated as they are today. Merging the pages does not merge the permissions.
- **Cost:** `AgentsView.tsx`, `ToolsView.tsx`, `routes.ts` redirect, tests. Medium.

### 4.2 One **Learning** area that owns every feedback loop (done)
- **Proposal:** move Admin → Governance → *Learning loop* (suggestions) and *Router evaluation* into Learning, next to the existing tool-choice Router tab. Add Evaluations as a Learning tab. Keep `/evaluations` as a redirect to `/learning?tab=evaluations`. Prompts and Retention stay in Admin.
- **Why:** route evaluation and tool-choice evaluation sit on different screens today, and a reviewer approving a learning suggestion never sees the verified queries it affects.
- **Devil's advocate:** Admin → Governance is admin-only, while Learning is admin+engineer. Moving suggestion review lets engineers approve prompt changes. *Answer:* gate the tab by role inside Learning (admin-only), or keep approval admin-only on the API, which is already the enforcement point.
- **Cost:** `LearningView.tsx`, `admin.tsx` (both owned by other agents right now). Medium.

### 4.3 One **Save** menu for SQL results
- **Proposal:** in SQL, Notebooks and Analysis, replace the separate buttons with one *Save as…* menu: *Artifact (for review)* · *Verified query (teach the assistant)* · *Notebook (keep iterating)* · *Publish to Dashboards*. Each option gets one line explaining the outcome.
- **Devil's advocate:** collapsing the stores into one would lose the review/verify distinction the learning loop depends on. *Answer:* that is why this merges the **entry point** only, not the stores.
- **Cost:** `SQLView.tsx`, `NotebooksView.tsx`, `ConversationsView.tsx`. Low–medium.

### 4.4 Home's objective box hands off to Analysis (done)
- **Proposal:** the "What do you want to build or understand?" box seeds Analysis (`setAnalysisSeed` plus `navigate("conversations", { fresh: true })`, which Datasets already does) instead of starting a detached agent run.
- **Devil's advocate:** engineers use it to launch multi-step engineering objectives, not questions. *Answer:* Analysis already routes to agents (the Jev decision), so the run is still created and the conversation keeps its context. Keep a "Run as agent objective" option for engineers.
- **Cost:** `WorkspaceView.tsx`. Low.

### 4.5 Considered and rejected
- **Merge Jobs + Approvals + Pipelines:** rejected. They are three different jobs (operate, decide, design), and the approver is often not the engineer.
- **Merge Semantic into Datasets:** rejected. Metrics and join policies span datasets, and the relationship explorer already links the two.
- **Remove Architecture:** rejected, but hidden by default for non-admins. It is useful in demos and costs nothing.
- **Separate "Analytics" top-level area for Superset:** rejected for now (see §3). Revisit if more BI surfaces arrive.

## 5. Remove? Unused-endpoint audit

39 of 223 API routes have no caller in `apps/web`. The count comes from a script that matched every `@router.<verb>("…")` path against the string and template literals in `apps/web/app`. None of them should be deleted on that basis alone:

| Group | Endpoints | Why it has no web caller |
|---|---|---|
| Machine interfaces | `/mcp`, `/.well-known/mcp.json`, `/external/v1/*` (openapi, list, get, invoke), `/health`, `/health/live`, `/health/ready`, `/observability/status` | Called by external agents, probes and monitoring, never by the browser. **Keep.** |
| Backend features with no UI yet | `/glossary` (GET/POST/DELETE), `/lineage`, `/lineage/graph`, `/semantic/graph`, `/sql/history`, `/jobs/{id}/events`, `/files/{id}/mappings`, `/pipelines/{id}/packages/*` (5), `/external-extractions` (3), `/router/decide`, `/router/policy` | Real capabilities (spec §5.1 package delivery, lineage). **UI gaps, not dead code.** Surface them later: packages and lineage in Pipelines, glossary in Semantic layer, SQL history in SQL. |
| Missing actions on existing screens | `/schedules/{id}/disable`, `/quality/runs/{id}/remediate`, `/query-tools/{id}/retire`, `/query-tools/{id}/analytics`, `/incidents/{id}/resolve`, `/evaluations/{id}/baseline`, `/approvals/auto-approval` (GET), `/datapackage/validate`, `/datasets/{id}/datapackage` (GET/POST) | One button each on an existing view. **Done** for the first six (§8); the auto-approval GET (Approvals) and the Data Package endpoints (Datasets) are still open. |

**No web screen is dead.** Every route is linked from the sidebar and backed by live endpoints.

## 6. What this change implemented (low risk)

- `lib/constants.tsx`: new `navGroups` (Analyze · Data · Build · Automate · Govern), clearer labels (Home, Dashboards), `roleNav`, `isPrimaryNav` and `NAV_ADVANCED_STORAGE_KEY`. Nav keys, `NAV_PATHS`, `canView`, `roleLanding` and `legacyViewTarget` are unchanged, so every route, deep link and `/?view=…` link still resolves.
- `components/WorkspaceShell.tsx`:
  - The sidebar shows the role's default items.
  - A **Show advanced (N)** toggle, persisted in `localStorage` (`datapilot.nav.showAdvanced`), reveals the rest.
  - The route currently open is always listed, even when it is advanced.
  - All sections start open.
  - The collapsed desktop rail now lists every visible item. Before, items in collapsed groups were unreachable.
  - The product tour only visits the role's default items.
- `globals.css` (one block appended at the end): toggle style, rail section separators, and the mobile drawer now shows labels and section headers even when the desktop rail is collapsed.
- `tests/app-source.test.mjs`: a nav test checks that there are exactly five areas, that every nav key sits in exactly one area, that each role's landing route is in its defaults, and that the toggle and `canView` gate are present.

## 7. Next steps (suggested order)
1. ~~§4.1 Agents & tools merge, with a `/tools` redirect.~~ Done.
2. ~~§4.2 Learning owns every feedback loop, with an `/evaluations` redirect.~~ Done.
3. §4.3 Single *Save as…* menu (SQL/Notebooks owners).
4. ~~§5 missing safety actions: schedule disable, query-tool retire.~~ Done. Still open: auto-approval status on Approvals, Data Package validate/apply on Datasets.
5. ~~§4.4 Home → Analysis hand-off.~~ Done.
6. §5 UI for package delivery, lineage and glossary.

## 8. What the follow-up change implemented

**Agents & tools (§4.1).** `/agents` is one page with tabs *Agents · Internal tools · External gateway / query tools · Invocation history* (`?tab=agents|tools|gateway|history`; the old Tool registry tab names `internal`, `external` and `invocations` are accepted as aliases). The gateway tab is admin/engineer and history is admin-only, as before (`agentsTabsFor` in `AgentsView.tsx`). `ToolsView.tsx` is deleted, so the internal tool list is rendered once. Agent scorecards stay in the agent detail page. The sidebar item is **Agents & tools**.

**Learning (§4.2).** Learning tabs: *Verified queries · Prompt optimization · Performance & DDL · Router & tool choice · Suggestions · Evaluations*.
- Router evaluation (`RouterEvaluationPanel`) and learning-loop suggestion review moved from `admin.tsx` into `LearningView.tsx` (moved, not copied). Admin → Governance keeps Prompts and Retention and links to the new tabs.
- Suggestions is admin-only, as the API enforces. The curation tabs are admin/engineer.
- Evaluations (`EvaluationsView`, rendered `embedded`) is open to every role, as `/evaluations` was. `canView("learning")` is therefore open to all roles, and `learningTabsFor` limits analysts and viewers to Evaluations. Learning stays in their "Show advanced" list, as Evaluations was.

**Redirects.** `NAV_REDIRECTS` in `lib/routes.ts` maps `tools → /agents?tab=tools` and `evaluations → /learning?tab=evaluations`.
- `app/(workspace)/tools/page.tsx` and `evaluations/page.tsx` redirect on the client (`components/RouteRedirect.tsx`, which keeps extra query parameters).
- `legacyViewTarget` sends `/?view=tools` and `/?view=evaluations` to the same targets.
- The `tools` and `evaluations` NavKeys and `NAV_PATHS` entries remain, so `navigate("tools")` and old links still resolve. They are no longer in `navItems`, `navGroups` or `roleNav`.
- The nav test now checks that every non-redirect key sits in exactly one area, and that each redirect key is unlisted and points to a listed page.

**Home (§4.4).** Submitting the objective box seeds a fresh Analysis conversation (`setAnalysisSeed` plus `navigate("conversations", { fresh: true })`, the same hand-off Datasets uses). The question is pre-filled, not sent. **Run as agent** is a secondary button that still posts `/agents/runs` and shows the plan. It is disabled, with an explanation, for roles without `jobs:write`.

**Safety and ops actions (§5).** Each has a confirmation dialog (`useConfirm`) and is disabled, with a tooltip, for roles the API would refuse. The API remains the enforcement point.

| Screen | Action | Endpoint | Enabled for |
|---|---|---|---|
| Pipelines → Ingestion schedules | Disable schedule | `POST /schedules/{id}/disable` | admin, engineer (`catalog:write`) |
| Pipelines → Ingestion schedules | Request re-enable (goes through Approvals) | `POST /schedules/{id}/enable` (**new**, 202; 409 if already enabled or a request is pending) | admin, engineer |
| Quality → Recent evaluations | Re-check failed rows / purge quarantine (both go through Approvals) | `POST /quality/runs/{id}/remediate` | admin, engineer (`quality:write`) |
| Agents & tools → External gateway | Retire query tool (row and dialog); publishing a retired tool again un-retires it | `POST /query-tools/{id}/retire` | admin |
| Agents & tools → External gateway | Usage analytics in the tool dialog | `GET /query-tools/{id}/analytics` | admin |
| Jobs → run trace incidents | Mark resolved | `POST /incidents/{id}/resolve` | admin, engineer |
| Learning → Evaluations | Promote the latest replay as the golden baseline (confirms again before overwriting) | `POST /evaluations/{id}/baseline` | every role except viewer |

There was no endpoint to re-enable a schedule, so `POST /schedules/{id}/enable` was added in `routers/files.py`. It creates the same `enable_ingestion_schedule` approval that schedule creation uses, and it is covered in `test_approved_incremental_schedule_uses_watermark`. A schedule shows *disabled* when it is off and has run before, and *awaiting approval* otherwise.
