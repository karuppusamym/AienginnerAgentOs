"""FastAPI application: lifespan, middleware and router registration.

Shared services live in app/services/ (re-exported by the core.py facade) and
schemas in schemas.py; every public and private name from core is re-exported
here so existing ``app.main`` imports keep working.
"""
from __future__ import annotations

from . import core as _core
from .core import *  # noqa: F401,F403

# ``import *`` skips underscore names; re-export them too (tests and older code use them).
globals().update({name: value for name, value in vars(_core).items() if not name.startswith("__") and name not in globals()})


def _reindex_catalog() -> None:
    """Refresh catalog vectors without blocking startup (it made N embedding calls inline)."""
    with SessionLocal() as db:
        for asset in db.scalars(select(DataAsset)).all():
            try:
                index_document(
                    asset.id,
                    f"{asset.schema_name}.{asset.table_name}",
                    f"{asset.description or ''} Columns: "
                    + ", ".join(column.get("name", "") for column in asset.columns),
                    {
                        "source_type": "dataset",
                        "schema_name": asset.schema_name,
                        "table_name": asset.table_name,
                        "tags": asset.tags,
                    },
                    db=db,
                )
            except Exception:
                pass


def startup() -> None:
    initialize_observability()
    initialize_governance()
    if migrations_on_startup():
        # alembic upgrade head (advisory-locked); the baseline revision creates
        # the whole schema on an empty database. See app/migrations.py.
        run_migrations(engine)
    # Safety net: a table added to models.py before its Alembic revision exists
    # is still created (checkfirst, so existing tables are untouched). Columns
    # and indexes on existing tables still need a revision.
    Base.metadata.create_all(bind=engine)
    if os.getenv("ENABLE_DEMO_DATA", "false").lower() in {"1", "true", "yes"}:
        ensure_demo_tables(engine)
    configure_read_only_access(engine)
    with SessionLocal() as db:
        seed_database(db)
        default_project = db.scalar(select(Project).order_by(Project.created_at))
        if default_project:
            backfill_project_columns(engine, default_project.id)
            db.expire_all()
    if os.getenv("QDRANT_URL", "").strip():
        threading.Thread(target=_reindex_catalog, name="catalog-reindex", daemon=True).start()


@asynccontextmanager
async def app_lifespan(_: FastAPI):
    startup()
    yield


app = FastAPI(
    title="DataPilot Agent OS API",
    version="0.1.0",
    description="Local-first governed AI data engineering workspace.",
    lifespan=app_lifespan,
)
app.add_middleware(
    CORSMiddleware,
    # Developers commonly get the next available Next.js port (3001/3002).
    # Keep the local defaults aligned with the Compose web service without
    # opening CORS to arbitrary origins.
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:3001,http://localhost:3002").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def observe_request(request: Request, call_next: Any) -> Any:
    supplied_request_id = request.headers.get("X-Request-ID", "")
    # Request IDs are echoed to clients and emitted in structured logs.  Accept a
    # portable trace identifier, but never let arbitrary header content become a
    # log value or a response header.
    correlation_id = (
        supplied_request_id
        if re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", supplied_request_id)
        else str(uuid4())
    )
    token = request_id.set(correlation_id)
    supplied_project = request.headers.get("X-Project-Id", "")
    project_token = active_project_id.set(supplied_project if re.fullmatch(r"[0-9a-fA-F-]{8,64}", supplied_project) else None)
    started = time.perf_counter()
    try:
        with span("http.request", method=request.method, path=request.url.path):
            response = await call_next(request)
        response.headers["X-Request-ID"] = correlation_id
        # These API-safe defaults protect browser consumers without changing CORS
        # behavior or the interactive OpenAPI documentation.
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        duration_ms = elapsed_ms(started)
        emit("http.request", method=request.method, path=request.url.path, status=response.status_code, duration_ms=duration_ms)
        record_governance_event(
            "http_request",
            f"{request.method} {request.url.path}",
            "succeeded" if response.status_code < 400 else "rejected" if response.status_code < 500 else "failed",
            session_id=correlation_id,
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        return response
    except Exception as exc:
        duration_ms = elapsed_ms(started)
        emit("http.request.failed", method=request.method, path=request.url.path, duration_ms=duration_ms)
        record_governance_event(
            "http_request",
            f"{request.method} {request.url.path}",
            "failed",
            session_id=correlation_id,
            method=request.method,
            path=request.url.path,
            duration_ms=duration_ms,
            error_type=type(exc).__name__,
        )
        raise
    finally:
        active_project_id.reset(project_token)
        request_id.reset(token)


# --- Domain routers (see apps/api/app/routers/) ---
from .routers import (
    admin,
    agents,
    analytics,
    approvals,
    artifacts,
    auth,
    connectors,
    conversations,
    datapackage,
    decisions,
    evaluations,
    files,
    governance,
    jobs,
    model_providers,
    notebooks,
    pipelines,
    projects,
    prompts,
    quality,
    query_tools,
    retention_policies,
    semantic,
    sql,
    system,
    tools,
    workspace,
)

for _router_module in (
    admin,
    agents,
    analytics,
    approvals,
    artifacts,
    auth,
    connectors,
    conversations,
    datapackage,
    decisions,
    evaluations,
    files,
    governance,
    jobs,
    model_providers,
    notebooks,
    pipelines,
    projects,
    prompts,
    quality,
    query_tools,
    retention_policies,
    semantic,
    sql,
    system,
    tools,
    workspace,
):
    app.include_router(_router_module.router)
