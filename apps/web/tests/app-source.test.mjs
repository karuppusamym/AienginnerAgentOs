import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const root = new URL("../", import.meta.url);

test("ships DataPilot product metadata", async () => {
  const layout = await readFile(new URL("app/layout.tsx", root), "utf8");
  assert.match(layout, /title:\s*"DataPilot Agent OS"/);
  assert.match(layout, /Local-first governed AI data engineering workspace/);
  assert.doesNotMatch(layout, /Starter Project|codex-preview/);
});

test("includes core governed product workflows", async () => {
  const page = await readFile(new URL("app/page.tsx", root), "utf8");
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
