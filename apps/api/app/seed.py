from __future__ import annotations

import os

from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import hash_password
from .models import (
    AgentDefinition,
    AgentVersion,
    Approval,
    AuthProvider,
    Connector,
    DataAsset,
    Job,
    ModelProvider,
    Project,
    ProjectMembership,
    SemanticMetric,
    ToolDefinition,
    ToolVersion,
    User,
)


def _secret_available(reference: str | None) -> bool:
    return bool(reference and reference.startswith("env:") and os.getenv(reference[4:]))


def _preferred_workspace_provider(db: Session) -> ModelProvider | None:
    gemini = db.scalar(
        select(ModelProvider).where(
            ModelProvider.provider_type == "gemini",
            ModelProvider.default_model == "gemini-3.6-flash",
            ModelProvider.enabled.is_(True),
        )
    )
    if gemini and _secret_available(gemini.secret_reference):
        return gemini
    return db.scalar(
        select(ModelProvider).where(ModelProvider.is_default.is_(True), ModelProvider.enabled.is_(True))
    ) or db.scalar(select(ModelProvider).where(ModelProvider.enabled.is_(True)).limit(1))


def ensure_control_plane(db: Session) -> None:
    admin = db.scalar(select(User).where(User.role == "admin").order_by(User.created_at))
    if admin is None:
        return
    if os.getenv("GEMINI_API_KEY"):
        for name, model in [("Gemini 3.6 Flash", "gemini-3.6-flash"), ("Gemini 3.5 Flash", "gemini-3.5-flash")]:
            if not db.scalar(select(ModelProvider).where(ModelProvider.provider_type == "gemini", ModelProvider.default_model == model)):
                db.add(ModelProvider(name=name, provider_type="gemini", base_url="https://generativelanguage.googleapis.com/v1beta", default_model=model, embedding_model="gemini-embedding-001", secret_reference="env:GEMINI_API_KEY", enabled=True, is_default=False, status="not_tested"))
        db.flush()
    provider = _preferred_workspace_provider(db)
    project = db.scalar(select(Project).where(Project.slug == "retail-banking"))
    if project is None:
        project = Project(
            name="Retail Banking",
            slug="retail-banking",
            description="Seeded local banking data engineering workspace.",
            environment="local",
            default_model_provider_id=provider.id if provider else None,
            created_by=admin.id,
        )
        db.add(project)
        db.flush()
    elif project.default_model_provider_id is None:
        project.default_model_provider_id = provider.id if provider else None
    if not db.scalar(
        select(Connector).where(
            Connector.project_id == project.id,
            Connector.connector_type == "local_files",
        )
    ):
        db.add(
            Connector(
                project_id=project.id,
                name="DataPilot local workspace",
                connector_type="local_files",
                status="healthy",
                read_only=True,
                metadata_summary={"files": 0, "tables": 0},
            )
        )
        db.flush()
    if os.getenv("ENABLE_DEMO_DATA", "false").lower() in {"1", "true", "yes"} and not db.scalar(
        select(DataAsset).where(DataAsset.project_id == project.id, DataAsset.schema_name == "core", DataAsset.table_name == "accounts")
    ):
        db.add(DataAsset(
            project_id=project.id,
            source_name="DataPilot PostgreSQL",
            schema_name="core",
            table_name="accounts",
            asset_type="table",
            row_count=8,
            columns=[
                {"name": "account_id", "type": "integer", "nullable": False},
                {"name": "customer_id", "type": "integer", "nullable": False},
                {"name": "account_type", "type": "varchar", "nullable": False},
                {"name": "status", "type": "varchar", "nullable": False},
                {"name": "opened_at", "type": "timestamp", "nullable": False},
            ],
            tags=["demo", "certified"],
            description="Local demo accounts table used by notebooks and embedded analytics.",
        ))
        db.flush()
    for user in db.scalars(select(User)).all():
        membership = db.scalar(
            select(ProjectMembership).where(
                ProjectMembership.project_id == project.id,
                ProjectMembership.user_id == user.id,
            )
        )
        if membership is None:
            db.add(
                ProjectMembership(
                    project_id=project.id,
                    user_id=user.id,
                    role="owner" if user.id == admin.id else "member",
                    is_current=True,
                )
            )

    if not db.scalar(select(SemanticMetric).limit(1)):
        db.add_all(
            [
                SemanticMetric(project_id=project.id, name="New deposit accounts", description="New checking and savings accounts opened during a period.", formula="COUNT(DISTINCT account_id)", grain="opening month", owner="Retail Analytics", dimensions=["account_type", "status"], synonyms=["deposit growth"], status="approved", created_by=admin.id),
                SemanticMetric(project_id=project.id, name="Active customer rate", description="Share of customers currently active.", formula="active_customers / all_customers", grain="calendar day", owner="Customer Insights", dimensions=["segment"], synonyms=["active customer percentage"], status="approved", created_by=admin.id),
                SemanticMetric(project_id=project.id, name="Net transaction amount", description="Signed transaction value for the selected period.", formula="SUM(amount)", grain="account, posting day", owner="Finance Data", dimensions=["transaction_type", "channel"], synonyms=["net flow"], status="approved", created_by=admin.id),
            ]
        )

    tools = [
        ("catalog.search", "metadata", "Search governed catalog and vector context.", "low", False),
        ("dataset.profile", "metadata", "Read the persisted profile and schema for a catalog dataset.", "low", False),
        ("sql.generate", "analysis", "Generate dialect-aware read-only SQL.", "low", False),
        ("sql.preview", "execution", "Execute a bounded read-only PostgreSQL preview.", "medium", False),
        ("file.profile", "ingestion", "Profile a local structured file.", "low", False),
        ("pipeline.stage", "execution", "Write a governed local staging relation.", "high", True),
        ("quality.run", "quality", "Execute a persisted data-quality rule.", "medium", False),
        ("schedule.run", "automation", "Execute an approved ingestion schedule.", "high", True),
        ("job.inspect", "operations", "Inspect a durable job trace, evidence, and logs.", "low", False),
        ("lineage.query", "metadata", "Find upstream and downstream lineage for a relation.", "low", False),
    ]
    for name, category, description, risk_level, requires_approval in tools:
        if not db.scalar(select(ToolDefinition).where(ToolDefinition.name == name)):
            db.add(ToolDefinition(name=name, category=category, description=description, risk_level=risk_level, requires_approval=requires_approval))
    db.flush()

    tool_contracts = {
        "catalog.search": (
            "catalog.search",
            {"type": "object", "additionalProperties": False, "required": ["query"], "properties": {"query": {"type": "string", "maxLength": 300}, "limit": {"type": "integer", "minimum": 1, "maximum": 25}}},
            ["catalog:read"],
        ),
        "sql.preview": (
            "sql.preview",
            {"type": "object", "additionalProperties": False, "required": ["sql"], "properties": {"sql": {"type": "string", "maxLength": 100000}, "limit": {"type": "integer", "minimum": 1, "maximum": 1000}}},
            ["query:read"],
        ),
        "dataset.profile": (
            "dataset.profile",
            {"type": "object", "additionalProperties": False, "required": ["asset_id"], "properties": {"asset_id": {"type": "string", "maxLength": 36}}},
            ["catalog:read"],
        ),
        "job.inspect": (
            "job.inspect",
            {"type": "object", "additionalProperties": False, "required": ["job_id"], "properties": {"job_id": {"type": "string", "maxLength": 36}}},
            ["jobs:read"],
        ),
        "lineage.query": (
            "lineage.query",
            {"type": "object", "additionalProperties": False, "required": ["relation"], "properties": {"relation": {"type": "string", "maxLength": 320}}},
            ["catalog:read"],
        ),
        "sql.generate": (
            "sql.generate",
            {"type": "object", "additionalProperties": False, "required": ["query"], "properties": {"query": {"type": "string", "maxLength": 500}, "dialect": {"type": "string", "maxLength": 20}}},
            ["catalog:read", "query:draft"],
        ),
        "file.profile": (
            "file.profile",
            {"type": "object", "additionalProperties": False, "required": ["file_id"], "properties": {"file_id": {"type": "string", "maxLength": 36}}},
            ["files:read"],
        ),
        "quality.run": (
            "quality.run",
            {"type": "object", "additionalProperties": False, "required": ["rule_id"], "properties": {"rule_id": {"type": "string", "maxLength": 36}}},
            ["quality:execute"],
        ),
        "pipeline.stage": (
            "pipeline.stage",
            {"type": "object", "additionalProperties": False, "required": ["file_id", "mapping_id"], "properties": {"file_id": {"type": "string", "maxLength": 36}, "mapping_id": {"type": "string", "maxLength": 36}, "load_mode": {"type": "string", "maxLength": 20}, "key_columns": {"type": "array"}}},
            ["staging:write"],
        ),
        "schedule.run": (
            "schedule.run",
            {"type": "object", "additionalProperties": False, "required": ["schedule_id"], "properties": {"schedule_id": {"type": "string", "maxLength": 36}}},
            ["ingestion:execute"],
        ),
    }
    for tool_name, (handler, parameter_schema, permissions) in tool_contracts.items():
        tool = db.scalar(select(ToolDefinition).where(ToolDefinition.name == tool_name))
        if tool and not db.scalar(select(ToolVersion).where(ToolVersion.tool_id == tool.id)):
            db.add(ToolVersion(tool_id=tool.id, version=1, implementation_type="builtin", handler_name=handler, parameter_schema=parameter_schema, result_schema={"type": "object"}, permissions=permissions, timeout_seconds=30, max_retries=0, status="published", created_by=admin.id))

    agents = [
        ("Planner", "Decomposes requests, selects specialists, and enforces run limits.", ["catalog.search"], 2, {"role": "planner"}),
        ("Metadata", "Scans catalogs, profiles assets, and retrieves grounded context.", ["catalog.search", "dataset.profile", "file.profile", "lineage.query"], 2, {"role": "metadata"}),
        ("SQL Analyst", "Generates and validates dialect-aware read-only SQL.", ["catalog.search", "sql.generate", "sql.preview"], 2, {"role": "sql_analyst"}),
        ("Pipeline", "Drafts and executes approval-gated local ingestion workflows.", ["file.profile", "pipeline.stage", "schedule.run"], 3, {"role": "pipeline"}),
        ("Quality", "Profiles data and proposes measurable quality controls.", ["catalog.search", "quality.run"], 2, {"role": "quality"}),
        ("Troubleshooter", "Explains failed jobs and recommends bounded remediation.", ["catalog.search", "job.inspect", "lineage.query"], 1, {"role": "troubleshooter"}),
        ("Policy", "Explains policy decisions while deterministic controls remain authoritative.", ["catalog.search", "job.inspect"], 2, {"role": "policy", "deterministic_authority": True, "writes_require_approval": True}),
        ("Analytics", "Builds grounded metric and dashboard analyses from approved catalog context.", ["catalog.search", "dataset.profile", "sql.generate", "sql.preview", "lineage.query"], 2, {"role": "analytics", "writes_require_approval": True}),
    ]
    for name, purpose, tool_names, level, policy in agents:
        if not db.scalar(select(AgentDefinition).where(AgentDefinition.name == name)):
            db.add(AgentDefinition(name=name, purpose=purpose, autonomy_level=level, tool_names=tool_names, policy={"max_iterations": 4, "max_tool_calls": 12, "timeout_seconds": 300, **policy}))
    db.flush()
    for name, purpose, tool_names, level, _policy in agents:
        agent = db.scalar(select(AgentDefinition).where(AgentDefinition.name == name))
        if agent and not db.scalar(select(AgentVersion).where(AgentVersion.agent_id == agent.id)):
            db.add(AgentVersion(agent_id=agent.id, version=1, instructions=f"You are the {name} specialist in DataPilot. {purpose} Ground decisions in project metadata, emit evidence, respect tool schemas, and stop when approval is required.", model_provider_id=project.default_model_provider_id, tool_names=tool_names, input_schema={"type": "object", "required": ["objective"], "properties": {"objective": {"type": "string"}}}, config={"max_iterations": 4, "max_tool_calls": 12, "timeout_seconds": 300, "autonomy_level": level}, status="published", created_by=admin.id))
    db.commit()


def seed_database(db: Session) -> None:
    if db.scalar(select(User).limit(1)):
        ensure_control_plane(db)
        return

    admin = User(
        email=os.getenv("SEED_ADMIN_EMAIL", "admin@datapilot.local"),
        name="Local Administrator",
        password_hash=hash_password(os.getenv("SEED_ADMIN_PASSWORD", "ChangeMe123!")),
        role="admin",
        must_change_password=True,
    )
    analyst = User(
        email="analyst@datapilot.local",
        name="Maya Chen",
        password_hash=hash_password("ChangeMe123!"),
        role="analyst",
        must_change_password=True,
    )
    db.add_all([admin, analyst])
    db.flush()

    if os.getenv("ENABLE_DEMO_DATA", "false").lower() not in {"1", "true", "yes"}:
        db.add_all(
            [
                ModelProvider(name="Company model gateway", provider_type="company_gateway", base_url="https://model-gateway.company.example/v1", default_model="company-reasoning", embedding_model="company-embedding", secret_reference="env:COMPANY_MODEL_API_KEY", enabled=False, is_default=False, status="configuration_required"),
                ModelProvider(name="Local deterministic model", provider_type="local_mock", default_model="datapilot-mock-v1", embedding_model="local-hash-embedding", enabled=True, is_default=True, status="healthy"),
                Connector(name="Local file workspace", connector_type="local_files", status="healthy", read_only=True, metadata_summary={"files": 0, "tables": 0}),
                AuthProvider(),
            ]
        )
        db.commit()
        ensure_control_plane(db)
        return

    company_model = ModelProvider(
        name="Company model gateway",
        provider_type="company_gateway",
        base_url="https://model-gateway.company.example/v1",
        default_model="company-reasoning",
        embedding_model="company-embedding",
        secret_reference="env:COMPANY_MODEL_API_KEY",
        enabled=False,
        is_default=False,
        status="configuration_required",
    )
    mock_model = ModelProvider(
        name="Local deterministic model",
        provider_type="local_mock",
        base_url=None,
        default_model="datapilot-mock-v1",
        embedding_model="local-hash-embedding",
        enabled=True,
        is_default=True,
        status="healthy",
    )
    mock_connector = Connector(
        name="Banking demo warehouse",
        connector_type="sql_server",
        host="mock-sqlserver",
        database="RetailBanking",
        status="healthy",
        read_only=True,
        metadata_summary={"schemas": 2, "tables": 7, "columns": 54},
    )
    db.add_all(
        [
            company_model,
            mock_model,
            mock_connector,
            AuthProvider(),
        ]
    )
    db.flush()

    assets = [
        DataAsset(
            connector_id=mock_connector.id,
            source_name=mock_connector.name,
            schema_name="core",
            table_name="customers",
            row_count=124_820,
            columns=[
                {"name": "customer_id", "type": "bigint", "nullable": False},
                {"name": "segment", "type": "varchar", "nullable": True},
                {"name": "created_at", "type": "datetime2", "nullable": False},
                {"name": "risk_rating", "type": "varchar", "nullable": True},
            ],
            tags=["PII", "certified"],
            description="Master customer record with approved customer grain.",
        ),
        DataAsset(
            connector_id=mock_connector.id,
            source_name=mock_connector.name,
            schema_name="core",
            table_name="accounts",
            row_count=203_118,
            columns=[
                {"name": "account_id", "type": "bigint", "nullable": False},
                {"name": "customer_id", "type": "bigint", "nullable": False},
                {"name": "account_type", "type": "varchar", "nullable": False},
                {"name": "status", "type": "varchar", "nullable": True},
                {"name": "opened_at", "type": "datetime2", "nullable": False},
            ],
            tags=["certified"],
            description="Deposit and lending accounts. Join to customers on customer_id.",
        ),
        DataAsset(
            connector_id=mock_connector.id,
            source_name=mock_connector.name,
            schema_name="activity",
            table_name="transactions",
            row_count=8_942_401,
            columns=[
                {"name": "transaction_id", "type": "bigint", "nullable": False},
                {"name": "account_id", "type": "bigint", "nullable": False},
                {"name": "amount", "type": "decimal(18,2)", "nullable": False},
                {"name": "transaction_type", "type": "varchar", "nullable": False},
                {"name": "posted_at", "type": "datetime2", "nullable": False},
            ],
            tags=["high-volume"],
            description="Posted account activity. Amount is signed in account currency.",
        ),
    ]
    db.add_all(assets)
    db.flush()

    job = Job(
        title="Daily customer quality baseline",
        job_type="quality_workflow",
        status="WAITING_FOR_APPROVAL",
        progress=65,
        created_by=analyst.id,
        plan=[
            {"agent": "Planner", "action": "Resolve customer grain", "status": "complete"},
            {"agent": "Quality", "action": "Draft duplicate and null checks", "status": "complete"},
            {"agent": "Policy", "action": "Require approval before scheduling", "status": "complete"},
            {"agent": "Runner", "action": "Create local daily schedule", "status": "waiting"},
        ],
        evidence=[
            {"type": "dataset", "label": "core.customers"},
            {"type": "profile", "label": "124,820 rows profiled"},
        ],
    )
    db.add(job)
    db.flush()
    db.add(
        Approval(
            job_id=job.id,
            title="Schedule daily customer quality checks",
            action_type="schedule_workflow",
            risk_level="medium",
            requested_by=analyst.id,
            evidence={
                "summary": "Creates a local 06:00 schedule. No source data is modified.",
                "checks": ["duplicate customer_id", "missing risk_rating", "invalid segment"],
            },
        )
    )
    db.commit()
    ensure_control_plane(db)
