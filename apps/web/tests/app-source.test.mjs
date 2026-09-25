import assert from "node:assert/strict";
import { access, readFile, readdir } from "node:fs/promises";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const root = new URL("../", import.meta.url);

/**
 * Every .tsx source under app/, recursively: app/page.tsx, app/components/*.tsx
 * (the files this test originally read) plus the App Router route segments in
 * app/(workspace)/** and app/lib/*.tsx that code moved into when the query-string
 * views became real routes. The set is a superset of the original one.
 */
async function appSources() {
  const entries = await readdir(fileURLToPath(new URL("app/", root)), { recursive: true, withFileTypes: true });
  const files = entries
    .filter((entry) => entry.isFile() && entry.name.endsWith(".tsx"))
    .map((entry) => join(entry.parentPath ?? entry.path, entry.name))
    .sort();
  return Promise.all(files.map((file) => readFile(file, "utf8")));
}

test("ships DataPilot product metadata", async () => {
  const layout = await readFile(new URL("app/layout.tsx", root), "utf8");
  assert.match(layout, /title:\s*"DataPilot Agent OS"/);
  assert.match(layout, /Local-first governed AI data engineering workspace/);
  assert.doesNotMatch(layout, /Starter Project|codex-preview/);
});

test("includes core governed product workflows", async () => {
  // Product views are intentionally split into domain components.  Inspect the
  // rendered application source as a whole instead of coupling this smoke test
  // to the former single-file page implementation.
  const page = [
    await readFile(new URL("app/page.tsx", root), "utf8"),
    ...await appSources(),
  ].join("\n");
  for (const workflow of [
    "Local file ingestion",
    "Grounded SQL workspace",
    "Approval inbox",
    "Agent registry",
    "PingFederate",
    "Artifact repository",
    "Run read-only preview",
    "Physical relation",
    "Schema mapping",
    "Confirm and stage",
    "Run quality check",
    "Execution log",
    "without another login",
    "Ingestion schedules",
    "Governed notebooks",
    "Evaluation and replay",
    "Review comments",
    "Change temporary password",
    "Switch or create project",
    "Active project model",
    "Projects and memberships",
    "Effective run policy",
    "Save metric",
    "tool marketplace",
    "Security Overview",
    "Overall Security Score",
    "Security Events Over Time",
    "Registered data sources",
    "Connection type",
    "SQL HISTORY",
    "Saved SQL artifacts",
    "All categories",
    "Generated pipelines",
    "Edit pipeline",
    "Save version",
    "Delete pipeline",
    "Edit data connector",
    "Save connector",
    "Parameter JSON Schema",
    "Diagnose",
    "Governed query gateway",
    "Versioned prompts",
    "Retention controls",
    "CONVERSATION CONTEXT",
    "Registered data source",
    "New query tool",
    "Draft next executable version",
    "EXECUTION HISTORY",
  ]) {
    assert.match(page, new RegExp(workflow));
  }
  assert.match(page, /\/search\?q=/);
  assert.match(page, /\/sql\/execute/);
  assert.match(page, /\/artifacts/);
  assert.match(page, /\/files\/\$\{selected\.id\}\/schema/);
  assert.match(page, /\/files\/\$\{selected\.id\}\/stage/);
  assert.match(page, /\/quality\/rules\/\$\{rule\.id\}\/run/);
  assert.match(page, /embedDashboard/);
  assert.match(page, /\/analytics\/config/);
  assert.match(page, /\/analytics\/guest-token/);
  assert.match(page, /\/analytics\/editor-session/);
  assert.match(page, /openEditor/);
  assert.doesNotMatch(page, /href="http:\/\/localhost:8088"/);
  assert.match(page, /autonomy_level:\s*2/);
  assert.match(page, /read-only/);
  assert.match(page, /Metadata scan completed:/);
  assert.match(page, /SQLSERVER_CREDENTIALS/);
  assert.match(page, /load_mode/);
  assert.match(page, /"Merge"/);
  assert.match(page, /\/schedules/);
  assert.match(page, /\/notebooks/);
  assert.match(page, /\/evaluations/);
  assert.match(page, /\/diff\?from_version=/);
  assert.match(page, /\/comments/);
  assert.match(page, /\/review/);
  assert.match(page, /\/auth\/change-password/);
  assert.match(page, /\/projects/);
  assert.match(page, /\/model-provider/);
  assert.match(page, /\/semantic\/metrics/);
  assert.match(page, /\/agents\/\$\{id\}/);
  assert.match(page, /\/policies\/effective/);
  assert.match(page, /\/jobs\/\$\{selected\.id\}\/cancel/);
  assert.match(page, /\/feedback/);
  assert.match(page, /\/pipelines\/generate/);
  assert.match(page, /\/pipelines\/\$\{editingPipeline\.id\}.*method:\s*"PUT"/s);
  assert.match(page, /\/pipelines\/\$\{pipeline\.id\}.*method:\s*"DELETE"/s);
  assert.match(page, /\/pipelines\/\$\{id\}\/deploy|\/pipelines\/\$\{pipeline\.id\}\/deploy/);
  assert.match(page, /\/connectors\/\$\{editing\.id\}.*method:\s*editing\s*\?\s*"PUT"/s);
  assert.match(page, /\/connectors\/\$\{connector\.id\}.*method:\s*"DELETE"/s);
  assert.match(page, /\/tools\/\$\{selectedTool\.id\}\/versions/);
  assert.match(page, /\/tools\/\$\{selectedTool\.id\}\/execute/);
  assert.match(page, /\/jobs\/\$\{selected\.id\}\/diagnose/);
  assert.match(page, /\/jobs\/\$\{selected\.id\}\/retry/);
  assert.match(page, /\/conversations/);
  assert.match(page, /\/query-tools/);
  assert.match(page, /\/external-clients/);
  assert.match(page, /\/prompts/);
  assert.match(page, /\/retention-policies/);
  assert.match(page, /\/schema-drift/);
  assert.match(page, /\/model-usage/);
  assert.match(page, /\/agents\/\$\{selected\.id\}.*method:\s*"PUT"/s);
  assert.match(page, /\/tools\/\$\{selectedTool\.id\}.*method:\s*"PUT"/s);
});

test("uses App Router segments with a shared authenticated layout", async () => {
  const routes = [
    "workspace", "analysis", "analysis/[conversationId]", "datasets", "files", "sql", "notebooks", "pipelines",
    "jobs", "artifacts", "quality", "superset", "approvals", "tools", "agents", "semantic", "evaluations", "admin", "learning",
  ];
  for (const route of routes) {
    await access(new URL(`app/(workspace)/${route}/page.tsx`, root));
  }
  const layout = await readFile(new URL("app/(workspace)/layout.tsx", root), "utf8");
  assert.match(layout, /QueryProvider/);
  assert.match(layout, /WorkspaceShell/);
  const analysisLayout = await readFile(new URL("app/(workspace)/analysis/layout.tsx", root), "utf8");
  assert.match(analysisLayout, /useParams/);
  assert.match(analysisLayout, /useSearchParams/);
  assert.match(analysisLayout, /ConversationsView/);
  // `/` redirects to the role landing route and old `?view=` links to their route.
  const home = await readFile(new URL("app/page.tsx", root), "utf8");
  assert.match(home, /legacyViewTarget/);
  assert.match(home, /roleLanding/);
  const routesSource = await readFile(new URL("app/lib/routes.ts", root), "utf8");
  assert.match(routesSource, /conversations: "\/analysis"/);
  assert.match(routesSource, /learning: "\/learning"/);
  const shell = await readFile(new URL("app/components/WorkspaceShell.tsx", root), "utf8");
  assert.match(shell, /from "next\/link"/);
  assert.match(shell, /usePathname/);
  assert.match(shell, /onUnauthorized/);
});

test("uses a project-scoped TanStack Query data layer", async () => {
  const pkg = JSON.parse(await readFile(new URL("package.json", root), "utf8"));
  assert.match(pkg.dependencies["@tanstack/react-query"], /^\d+\.\d+\.\d+$/, "pinned exact version");
  const queries = await readFile(new URL("app/lib/queries.tsx", root), "utf8");
  assert.match(queries, /QueryClientProvider/);
  assert.match(queries, /\["project", projectId/);
  assert.match(queries, /signal/);
  assert.match(queries, /useInfiniteQuery/);
  assert.match(queries, /refetchInterval/);
  for (const endpoint of ["/conversations", "/connectors", "/model-providers", "/model-routing", "/jobs", "/approvals", "/datasets", "/verified-queries", "/prompt-optimizations", "/sql/index-recommendations", "/router/decisions"]) {
    assert.ok(queries.includes(endpoint), `query for ${endpoint}`);
  }
});

test("ships the learning and quality workflows", async () => {
  const page = (await appSources()).join("\n");
  for (const text of ["Verified queries", "Prompt optimization", "Index recommendations", "Recent decisions", "Router evaluation", "Pareto", "Instructions vs baseline", "Per-case scores", "is not available from this API yet"]) {
    assert.match(page, new RegExp(text));
  }
  assert.match(page, /\/verified-queries\/\$\{id\}.*method:\s*"PUT"/s);
  assert.match(page, /\/verified-queries\/\$\{id\}.*method:\s*"DELETE"/s);
  assert.match(page, /\/prompt-optimizations\/\$\{id\}\/apply/);
  assert.match(page, /\/sql\/index-recommendations\/apply/);
  // Chat inspector and approval rendering for the learning loop.
  assert.match(page, /verified_examples/);
  assert.match(page, /reused_verified_query/);
  assert.match(page, /<h4>Ensemble<\/h4>/);
  assert.match(page, /escalated_by/);
  assert.match(page, /"prompt_activation"/);
  assert.match(page, /"create_index"/);
});

test("renders data-driven result charts with a chart-type switcher", async () => {
  const charts = await readFile(new URL("app/components/charts.tsx", root), "utf8");
  for (const type of ["kpi", "line", "bar", "grouped_bar", "stacked_bar", "pie", "scatter", "table"]) {
    assert.match(charts, new RegExp(`"${type}"`), `chart type ${type}`);
  }
  for (const component of ["KpiTiles", "LineChart", "BarChart", "GroupedBarChart", "PieChart", "ScatterChart", "ChartTypeSwitcher", "chartAlternatives"]) {
    assert.match(charts, new RegExp(`function ${component}\\b`), component);
  }
  // Accessible SVG: title/desc, keyboard stepping and a live region; palette tokens only.
  assert.match(charts, /<title id=/);
  assert.match(charts, /<desc id=/);
  assert.match(charts, /ArrowRight/);
  assert.match(charts, /aria-live="polite"/);
  assert.match(charts, /var\(--chart-/);
  // Older answers without alternatives still get bar / line / table.
  assert.match(charts, /\["bar" as const, "line" as const\]/);
  const css = await readFile(new URL("app/globals.css", root), "utf8");
  for (let slot = 1; slot <= 8; slot += 1) assert.equal(css.match(new RegExp(`--chart-${slot}:`, "g"))?.length, 3, `--chart-${slot} in light + both dark scopes`);
  const chat = await readFile(new URL("app/components/ConversationsView.tsx", root), "utf8");
  assert.match(chat, /<ChartTypeSwitcher/);
  assert.match(chat, /chartTypes\[inspected\.id\]/, "chart choice remembered per message");
  assert.match(chat, /Jev decision/);
  assert.match(chat, /No majority/);
  const pkg = JSON.parse(await readFile(new URL("package.json", root), "utf8"));
  // Result charts are inline SVG. d3 layout/interaction modules (force layout, drag, zoom, selection)
  // are allowed for the semantic relationship graph; chart-rendering libraries are not.
  const graphLayout = new Set(["d3-force", "d3-drag", "d3-zoom", "d3-selection"]);
  assert.ok(!Object.keys(pkg.dependencies).some((name) => !graphLayout.has(name) && /chart|d3|plotly|vega|nivo/i.test(name)), "charts are inline SVG, no chart library");
});

test("surfaces decision models and DDL suggestions", async () => {
  const page = (await appSources()).join("\n");
  const constants = await readFile(new URL("app/lib/constants.tsx", root), "utf8");
  assert.match(constants, /value: "jev"/);
  assert.match(constants, /https:\/\/openrouter\.ai\/api\/alpha\/decisions/);
  assert.match(constants, /typesafe\/jev-1\.13/);
  assert.match(constants, /Decision model: returns typed choices with probabilities, not text/);
  assert.match(page, /decision model/);
  assert.match(page, /Escalated by Jev/);
  assert.match(page, /jev:consequential/);
  assert.match(page, /Model usage/);
  // Router evaluation: fallback only for "local (…)", all backends on by default.
  assert.match(page, /startsWith\("local \("\)/);
  assert.match(page, /jev: true/);
  // Index advice is a DDL suggestion for DBAs, never executed automatically.
  for (const text of ["Performance &(amp;)? DDL suggestions", "never run automatically", "Saved DDL suggestions", "Include fast queries", "Save suggestion", "Copy DDL", "No queries slower than"]) {
    assert.match(page, new RegExp(text));
  }
  const queries = await readFile(new URL("app/lib/queries.tsx", root), "utf8");
  assert.match(queries, /\/sql\/ddl-suggestions/);
  assert.match(queries, /min_ms=/);
});

test("groups the sidebar by user job with role defaults and an advanced toggle", async () => {
  const constants = await readFile(new URL("app/lib/constants.tsx", root), "utf8");
  const routesSource = await readFile(new URL("app/lib/routes.ts", root), "utf8");
  const shell = await readFile(new URL("app/components/WorkspaceShell.tsx", root), "utf8");
  // Five areas; every routed nav key sits in exactly one of them, so no route drops out of the sidebar.
  // Keys merged into another page (NAV_REDIRECTS) are in no area, and their redirect target's key is.
  const groupsBlock = constants.match(/export const navGroups[\s\S]*?\n\];/)[0];
  const groupLabels = [...groupsBlock.matchAll(/label: "([^"]+)"/g)].map((match) => match[1]);
  assert.deepEqual(groupLabels, ["Analyze", "Data", "Build", "Automate", "Govern"]);
  const grouped = [...groupsBlock.matchAll(/items: \[([^\]]*)\]/g)].flatMap((match) => [...match[1].matchAll(/"([a-z]+)"/g)].map((item) => item[1]));
  const pathsBlock = routesSource.match(/NAV_PATHS[^=]*= \{([\s\S]*?)\};/)[1];
  const navKeys = [...pathsBlock.matchAll(/^\s*([a-z]+):/gm)].map((match) => match[1]);
  const redirectsBlock = routesSource.match(/NAV_REDIRECTS[^=]*= \{([\s\S]*?)\};/)[1];
  const redirects = Object.fromEntries([...redirectsBlock.matchAll(/^\s*([a-z]+): "([^"]+)"/gm)].map((match) => [match[1], match[2]]));
  assert.deepEqual(Object.keys(redirects).sort(), ["evaluations", "tools"]);
  assert.equal(new Set(grouped).size, grouped.length, "no nav key listed twice");
  assert.deepEqual([...grouped].sort(), navKeys.filter((key) => !redirects[key]).sort(), "each non-redirect nav key in exactly one section");
  for (const [key, target] of Object.entries(redirects)) {
    assert.ok(!grouped.includes(key), `${key} is merged, not listed`);
    const targetKey = navKeys.find((navKey) => pathsBlock.includes(`${navKey}: "${target.split("?")[0]}"`));
    assert.ok(targetKey && grouped.includes(targetKey), `${key} redirects into a listed page`);
  }
  // Role defaults include each role's landing route; admin sees everything.
  const roleNavBlock = constants.match(/export const roleNav[\s\S]*?\n\};/)[0];
  assert.match(roleNavBlock, /admin: "all"/);
  for (const [role, landing] of [["engineer", "pipelines"], ["analyst", "conversations"], ["viewer", "datasets"]]) {
    const items = roleNavBlock.match(new RegExp(`${role}: \\[([\\s\\S]*?)\\]`))[1];
    assert.match(items, new RegExp(`"${landing}"`), `${role} default nav includes its landing route`);
  }
  // Presentation only: canView stays the route gate, deep links keep working, the toggle persists.
  assert.match(routesSource, /export function canView/);
  assert.match(shell, /isPrimaryNav\(item\.key, user\.role\)/);
  assert.match(shell, /item\.key === active/);
  assert.match(shell, /NAV_ADVANCED_STORAGE_KEY/);
  assert.match(constants, /NAV_ADVANCED_STORAGE_KEY = "datapilot\.nav\.showAdvanced"/);
  assert.match(shell, /Show advanced/);
  assert.match(shell, /railMode/);
});

test("result charts drill down / up, toggle series, zoom and expand", async () => {
  const charts = await readFile(new URL("app/components/charts.tsx", root), "utf8");
  // Drill: optional onDrill prop emitting a natural-language follow-up, client-side grain drill.
  assert.match(charts, /onDrill\?: \(request: ChartDrillRequest\) => void/);
  assert.match(charts, /Break down \$\{/);
  for (const grain of ["year", "quarter", "month", "day"]) assert.match(charts, new RegExp(`"${grain}"`), `grain ${grain}`);
  assert.match(charts, /function deriveView\b/);
  assert.match(charts, /function drillMode\b/);
  assert.match(charts, /aria-label="Drill path"/, "breadcrumb");
  assert.match(charts, /Drill up one level/);
  assert.match(charts, /event\.key === "Backspace"/, "keyboard drill up");
  assert.match(charts, /event\.key === "Enter" \|\| event\.key === " "/, "keyboard drill down");
  // Legend toggling, brush zoom with reset, full-screen expand.
  assert.match(charts, /aria-pressed=\{!off\}/);
  assert.match(charts, /function useBrush\b/);
  assert.match(charts, /Reset zoom/);
  assert.match(charts, /createPortal\(/);
  assert.match(charts, /aria-modal="true"/);
  const types = await readFile(new URL("app/types.ts", root), "utf8");
  assert.match(types, /export type ChartDrillRequest = \{ column: string; value: string; question: string/);
});

test("relationship graph is pannable, zoomable, draggable and drills source > table > column", async () => {
  const canvas = await readFile(new URL("app/components/GraphCanvas.tsx", root), "utf8");
  // Pan / zoom (wheel + buttons + fit), drag-to-pin with release, layouts, search, keyboard, reduced motion.
  assert.match(canvas, /addEventListener\("wheel"/);
  for (const label of ["Zoom in", "Zoom out", "Fit to screen", "Find a node in this graph"]) assert.match(canvas, new RegExp(label));
  assert.match(canvas, /sim\.fx = point\.x/, "dragged nodes are pinned");
  assert.match(canvas, /function release\b/, "double-click releases a pinned node");
  assert.match(canvas, /"force" \| "hierarchical"/);
  assert.match(canvas, /function hierarchicalPositions\b/);
  assert.match(canvas, /prefers-reduced-motion: reduce/);
  assert.match(canvas, /tabIndex=\{node\.id === tabStop \? 0 : -1\}/, "roving tab stop");
  assert.match(canvas, /ArrowRight/);
  assert.match(canvas, /showAllLabels/, "labels hidden at low zoom on big graphs");
  assert.doesNotMatch(canvas, /from "d3|from "vis-|from "cytoscape/, "no graph library");
  const explorer = await readFile(new URL("app/components/RelationshipExplorer.tsx", root), "utf8");
  assert.match(explorer, /<GraphCanvas/);
  assert.match(explorer, /function buildCanvas\b/);
  assert.match(explorer, /Drill level: source, table, column/);
  assert.match(explorer, /Drill up/);
  assert.match(explorer, /Drill down/);
  assert.match(explorer, /Neighbours \+1 hop/);
  assert.match(explorer, /\/semantic\/explorer\?\$\{params\}/, "neighbour expansion refetches depth 1 around a node");
  const semantic = await readFile(new URL("app/components/SemanticView.tsx", root), "utf8");
  assert.match(semantic, /<RelationshipExplorer/);
});

test("merges Agents & tools and the learning loops; old routes redirect; safety actions are wired", async () => {
  const read = (path) => readFile(new URL(path, root), "utf8");
  // §4.1 One Agents & tools page; /tools redirects to its tools tab, no duplicate rendering.
  const agents = await read("app/components/AgentsView.tsx");
  assert.match(agents, /Agents &amp; tools/);
  assert.match(agents, /<GatewayAdmin/);
  assert.match(agents, /<InvocationHistory/);
  assert.match(agents, /if \(role === "admin"\) tabs\.push\("history"\)/);
  assert.doesNotMatch(agents, /registryOnly/);
  await assert.rejects(access(new URL("app/components/ToolsView.tsx", root)), "ToolsView was merged into AgentsView");
  assert.match(await read("app/(workspace)/tools/page.tsx"), /RouteRedirect/);
  assert.match(await read("app/lib/routes.ts"), /tools: "\/agents\?tab=tools"/);
  // §4.2 Learning owns suggestions, router evaluation and evaluations; Admin → Governance no longer does.
  const learning = await read("app/components/LearningView.tsx");
  for (const text of ["function RouterEvaluationPanel", "function LearningSuggestionsPanel", "<EvaluationsView notify=\{notify\} embedded", "/learning-suggestions", "Router & tool choice"]) {
    assert.match(learning, new RegExp(text));
  }
  const admin = await read("app/components/admin.tsx");
  assert.doesNotMatch(admin, /learning-suggestions|router\/evaluate|function RouterEvaluationPanel/);
  assert.match(await read("app/(workspace)/evaluations/page.tsx"), /RouteRedirect/);
  assert.match(await read("app/lib/routes.ts"), /evaluations: "\/learning\?tab=evaluations"/);
  // §4.4 Home hands the question to Analysis; agent runs stay an explicit, permission-aware option.
  const home = await read("app/(workspace)/workspace/page.tsx");
  assert.match(home, /setAnalysisSeed\(/);
  assert.match(home, /navigate\("conversations", \{ fresh: true \}\)/);
  assert.match(await read("app/components/WorkspaceView.tsx"), /Run as agent/);
  // §5 Safety/ops actions with confirmations.
  const pipelines = await read("app/components/PipelinesView.tsx");
  assert.match(pipelines, /\/schedules\/\$\{schedule\.id\}\/disable/);
  assert.match(pipelines, /\/schedules\/\$\{schedule\.id\}\/enable/);
  assert.match(await read("app/components/QualityView.tsx"), /\/quality\/runs\/\$\{run\.id\}\/remediate/);
  assert.match(admin, /\/query-tools\/\$\{tool\.id\}\/retire/);
  assert.match(admin, /\/query-tools\/\$\{tool\.id\}\/analytics/);
  assert.match(await read("app/components/JobsView.tsx"), /\/incidents\/\$\{incident\.id\}\/resolve/);
  assert.match(await read("app/components/EvaluationsView.tsx"), /\/evaluations\/\$\{item\.id\}\/baseline/);
});
