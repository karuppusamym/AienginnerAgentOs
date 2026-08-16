export type NavKey =
  | "workspace"
  | "conversations"
  | "datasets"
  | "files"
  | "sql"
  | "notebooks"
  | "pipelines"
  | "jobs"
  | "artifacts"
  | "quality"
  | "superset"
  | "approvals"
  | "tools"
  | "agents"
  | "semantic"
  | "evaluations"
  | "admin";

export type Overview = {
  counts: { data_assets: number; connectors: number; jobs: number; pending_approvals: number };
  system: { model: string; vector_store: string; workflow_engine: string; autonomy_level: number };
};

export type Recommendation = { question: string; basis: string; relation: string };

export type SecurityCategoryKey = "prompt_injection" | "pii_exposure" | "toxic_content";

export type SecurityOverview = {
  period: { key: string; label: string; started_at: string; ended_at: string };
  overview: {
    overall_security_score: number;
    posture: string;
    score_delta_pp: number;
    total_security_events: number;
    blocked_requests: number;
    critical_incidents: number;
  };
  event_series: {
    label: string;
    start_at: string;
    end_at: string;
    counts: Record<SecurityCategoryKey, number>;
  }[];
  top_security_risks: {
    key: SecurityCategoryKey;
    category: string;
    count: number;
    share_percent: number;
  }[];
  events_by_category: {
    key: SecurityCategoryKey;
    category: string;
    count: number;
  }[];
  incidents_by_severity: { severity: string; count: number }[];
  recent_incidents: {
    id: string;
    title: string;
    severity: string;
    status: string;
    category: string;
    created_at: string;
  }[];
};

export type Dataset = {
  id: string;
  source_name: string;
  schema_name: string;
  table_name: string;
  asset_type: string;
  category: string;
  row_count: number | null;
  columns: { name: string; type: string; nullable: boolean; business_name?: string; description?: string }[];
  tags: string[];
  description: string;
  owner?: string | null;
  sensitivity?: string;
  freshness_sla_hours?: number | null;
  metadata_status?: string;
  connector_id?: string | null;
  source?: { id?: string | null; name: string; database: string; connector_type: string; dialect: string; connection_mode?: "direct" | "mcp" };
};

export type Connector = {
  id: string;
  name: string;
  connector_type: string;
  connection_mode: "direct" | "mcp";
  description?: string | null;
  host: string | null;
  database: string | null;
  mcp_server_url?: string | null;
  secret_reference?: string | null;
  status: string;
  read_only: boolean;
  metadata_summary: Record<string, number>;
  last_scanned_at?: string;
};

export type ModelProvider = {
  id: string;
  name: string;
  provider_type: string;
  base_url?: string;
  default_model: string;
  embedding_model?: string;
  secret_reference?: string;
  enabled: boolean;
  is_default: boolean;
  status: string;
};

export type Project = {
  id: string;
  name: string;
  slug: string;
  description?: string;
  environment: string;
  active: boolean;
  default_model_provider_id?: string;
  membership_role?: string;
  is_current: boolean;
  model_provider?: { id: string; name: string; provider_type: string; default_model: string; status: string };
};

export type AgentVersion = { id: string; version: number; instructions: string; model_provider_id?: string; tool_names: string[]; query_tool_names: string[]; input_schema: Record<string, unknown>; config: Record<string, unknown>; status: string; evaluation_score?: number; created_at: string };
export type AgentDefinition = { id: string; name: string; purpose: string; autonomy_level: number; enabled: boolean; tool_names: string[]; query_tool_names: string[]; policy: Record<string, unknown>; current_version?: number; version_status?: string; model_provider_id?: string; evaluation_score?: number; versions?: AgentVersion[] };
export type ToolVersion = { id: string; version: number; implementation_type: string; handler_name: string; endpoint?: string; http_method: string; parameter_schema: { type?: string; required?: string[]; properties?: Record<string, { type?: string; description?: string }> }; result_schema: Record<string, unknown>; permissions: string[]; timeout_seconds: number; max_retries: number; retry_backoff_seconds: number; cost_class: string; environment: string; status: string; created_at: string };
export type ToolDefinition = { id: string; name: string; category: string; description: string; risk_level: string; enabled: boolean; requires_approval: boolean; current_version?: number; version_status?: string; implementation_type?: string; parameter_schema?: ToolVersion["parameter_schema"]; versions?: ToolVersion[] };
export type SemanticMetric = { id: string; project_id: string; asset_id?: string | null; name: string; description?: string; formula: string; grain: string; owner: string; dimensions: string[]; synonyms: string[]; status: string };
export type SemanticJoinPolicy = { id: string; project_id: string; left_asset_id: string; right_asset_id: string; left_column: string; right_column: string; join_type: "inner" | "left"; description?: string; status: string };
export type PipelineDefinition = { id: string; name: string; objective: string; status: string; current_version: number; generated_code: string; definition: { sources?: { asset_id: string; relation: string }[]; target?: { relation: string }; nodes?: { id: string; type: string; label: string }[]; edges?: { source: string; target: string }[]; checks?: string[] }; updated_at: string };
export type Incident = { id: string; job_id: string; title: string; severity: string; status: string; root_cause: string; evidence: Record<string, unknown>[]; remediation: string[]; retry_job_id?: string; created_at: string };

export type Job = {
  id: string;
  title: string;
  job_type: string;
  status: string;
  progress: number;
  plan: { agent: string; action: string; status: string }[];
  evidence: { type: string; label: string }[];
  logs: { at: string; level: string; message: string }[];
  outputs: { type: string; agent?: string; tool?: string; title?: string; summary?: string; data?: unknown; at?: string }[];
  created_at: string;
};

export type Approval = {
  id: string;
  job_id: string;
  title: string;
  action_type: string;
  risk_level: string;
  status: string;
  evidence: { summary?: string; checks?: string[]; objective?: string; guardrails?: string[] };
  created_at: string;
};

export type IngestedFile = {
  id: string;
  filename: string;
  size_bytes: number;
  status: string;
  row_count?: number;
  profile: {
    kind: string;
    row_count?: number;
    column_count?: number;
    columns?: { name: string; inferred_type: string; null_count: number; distinct_count: number }[];
    sample_rows?: Record<string, unknown>[];
    preview?: string;
    staged_table?: { schema_name: string; table_name: string; relation: string; row_count: number; loaded_rows: number; replaced_rows: number; load_mode: LoadMode };
    confirmed_mapping?: {
      id: string;
      name: string;
      target_table: string;
      columns: MappingColumn[];
      load_mode?: LoadMode;
      key_columns?: string[];
    };
  };
  created_at: string;
};

export type MappingColumn = {
  source_name: string;
  target_name: string;
  target_type: "string" | "integer" | "number" | "boolean";
  nullable: boolean;
};

export type LoadMode = "versioned" | "replace" | "append" | "upsert";

export type IngestionMapping = {
  id: string;
  name: string;
  target_table: string;
  columns: MappingColumn[];
  latest_relation?: string;
  run_count: number;
  artifact_id: string;
};

export type QualityRun = {
  id: string;
  rule_id: string;
  rule_name: string;
  dataset: string;
  status: string;
  checked_rows: number;
  failed_rows: number;
  pass_rate: number;
  quarantine_relation?: string;
  error?: string;
  created_at: string;
};

export type QualityRule = {
  id: string;
  asset_id: string;
  name: string;
  rule_type: string;
  column_name: string;
  severity: string;
  dataset: string;
  latest_run?: QualityRun;
};

export type SQLResult = {
  sql: string;
  dialect: string;
  explanation: string;
  source?: { name?: string; database?: string; connector_type?: string };
  cache?: { hit: boolean; cache_key?: string; normalized_question?: string; hit_count?: number };
  grounding?: {
    catalog_matches?: { relation: string; match_type: string; score: number }[];
    semantic_matches?: { name: string; formula: string; grain: string }[];
    join_matches?: { left_relation: string; right_relation: string; join_type: string; left_column: string; right_column: string }[];
  };
  validation: {
    status: string;
    read_only: boolean;
    row_limit: number;
    risk_level: string;
    checks: string[];
  };
  sources: { asset?: string; columns?: string[]; term?: string; definition?: string }[];
  preview: Record<string, string | number>[];
  execution?: SQLExecutionResult | null;
  provider: { id: string; name: string; model: string; mode: string; latency_ms: number };
};

export type SQLExecutionResult = {
  columns: string[];
  rows: Record<string, string | number>[];
  row_count: number;
  truncated: boolean;
  limit: number;
  error?: string;
};

export type SearchResult = {
  source_id: string;
  source_type: string;
  title: string;
  text: string;
  score: number;
  relation?: string;
};

export type Artifact = {
  id: string;
  name: string;
  artifact_type: string;
  status: string;
  latest_version: number;
  metadata: Record<string, unknown>;
  updated_at: string;
};

export type ArtifactVersion = {
  id: string;
  artifact_id: string;
  version: number;
  content: string;
  artifact_metadata: Record<string, unknown>;
  created_at: string;
};

export type IngestionSchedule = {
  id: string;
  name: string;
  mapping_id: string;
  mapping_name: string;
  filename: string;
  target_table?: string;
  cron: string;
  load_mode: string;
  watermark_column?: string;
  last_watermark?: string;
  enabled: boolean;
  next_run_at?: string;
  last_run_at?: string;
};

export type MappingOption = IngestionMapping & { filename: string };

export type ArtifactComment = { id: string; body: string; version?: number; author: string; created_at: string };

export type EvaluationSet = {
  id: string;
  name: string;
  description?: string;
  cases: { name: string; question: string; case_type?: "sql_generation" | "agent_run"; dialect: string; expected_tables: string[]; required_sql_tokens: string[]; expected_agents?: string[]; expected_tools?: string[]; expects_approval?: boolean | null }[];
  latest_run?: { id: string; status: string; score: number; created_at: string };
};

export type NotebookCellData = { id: string; type: "markdown" | "sql" | "python"; source: string };
export type Notebook = { id: string; name: string; status: string; version: number; cells: NotebookCellData[]; outputs: { cell_id: string; status: string; output?: unknown; error?: string }[]; job_id?: string | null };

export type Conversation = { id: string; title: string; summary?: string; message_count: number; last_message?: string; created_by: string; created_at: string; updated_at: string };
export type ConversationMessage = {
  id: string;
  conversation_id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
  structured: {
    sql?: string;
    dialect?: string;
    provider?: { name: string; model: string };
    cache?: { hit: boolean; cache_key?: string; normalized_question?: string; hit_count?: number };
    grounding?: {
      catalog_matches?: { relation: string; match_type: string; score: number }[];
      semantic_matches?: { name: string; formula: string; grain: string }[];
      join_matches?: { left_relation: string; right_relation: string; join_type: string; left_column: string; right_column: string }[];
    };
    validation?: { status: string; checks: string[] };
    sources?: { asset?: string; term?: string }[];
    execution?: SQLExecutionResult;
    chart?: { type: "bar" | "line" | "table"; title: string; x?: string; y?: string; data: Record<string, string | number>[] };
    source?: { id?: string | null; name: string; database: string; connector_type: string; dialect: string };
    memory?: { prior_messages_used: number; persisted: boolean; summary?: string | null };
  };
};
export type ExternalClient = { id: string; name: string; client_id: string; active: boolean; scopes: string[]; created_at: string; token?: string };
export type QueryTool = { id: string; name: string; description: string; purpose: string; data_source: string; line_of_business: string; owner: string; tags: string[]; connector_id?: string; upstream_tool_name?: string | null; sql_template: string; parameter_schema: Record<string, unknown>; result_schema: Record<string, unknown>; allowed_relations: string[]; row_limit: number; timeout_seconds: number; requires_approval: boolean; status: string; version: number; updated_at: string };
export type QueryToolDraft = Omit<QueryTool, "id" | "status" | "version" | "updated_at">;
export type RelationOption = { asset_id: string; relation: string; source_name: string; connector_id?: string | null; connector_name: string; columns: Dataset["columns"]; tags: string[] };
export type QueryToolUsage = { invocation_count: number; success_count: number; failure_count: number; success_rate: number | null; median_latency_ms: number | null; rows_returned: number; last_invoked_at: string | null };
export type QueryToolRegistrySummary = { total: number; published: number; draft: number; never_invoked: number; tools: (QueryTool & QueryToolUsage)[] };
export type PromptArtifact = { id: string; name: string; status: string; version: number; content: { system_prompt?: string; template?: string; variables?: string[] }; metadata: Record<string, unknown>; updated_at: string };
export type RetentionPolicy = { id: string; resource_type: string; retention_days: number; enabled: boolean; updated_at: string };
export type SchemaDrift = { id: string; connector_id: string; relation: string; changes: { kind: string; column: string; from?: string; to?: string; type?: string }[]; status: string; detected_at: string };
export type ModelUsage = { pricing_configured: boolean; totals: { calls: number; input_tokens: number; output_tokens: number; estimated_cost_usd: number }; items: { provider_id: string; provider_name: string; model: string; calls: number; input_tokens: number; output_tokens: number; estimated_cost_usd: number; average_latency_ms: number }[] };
export type LearningSuggestion = { id: string; feedback_id: string; category: string; status: "open" | "accepted" | "dismissed"; title: string; rationale: string; proposed_change: { review_target?: string; context_id?: string; action?: string; recent_signals?: { feedback_id: string; context_id?: string; comment?: string }[]; occurrence_count?: number }; reviewed_by: string | null; review_note: string | null; occurrence_count: number; severity: "normal" | "elevated" | "high"; created_at: string; reviewed_at: string | null };
