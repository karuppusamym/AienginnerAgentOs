# DataPilot Kubernetes baseline

This is a production deployment baseline, not a replacement for environment-specific platform controls. It assumes managed PostgreSQL, Redis, Qdrant, Temporal and an OTLP collector are supplied outside this overlay.

**Runs on vanilla Kubernetes and OpenShift (OCP) unmodified.** Both `apps/api/Dockerfile` and `apps/web/Dockerfile` run as a fixed non-root UID with the app directory group-owned by group 0 (`chmod g=u`), and every Deployment sets `runAsNonRoot: true` / drops all capabilities / uses the `RuntimeDefault` seccomp profile. OCP's default `restricted-v2` SCC overrides the UID at admission but keeps group 0 — since the image never assumed a specific UID, that override doesn't break anything.

## Redis is required, not optional, if you want rate limiting

`REDIS_URL` is used by `apps/api/app/rate_limit.py` to throttle the external query-tool gateway (`/external/v1/*`, `/mcp`) per client (`EXTERNAL_QUERY_TOOL_RATE_LIMIT_PER_MINUTE`, default 60/min). The limiter **fails open** — if Redis is unreachable, requests are allowed through rather than blocked — so a Redis outage degrades gracefully to "no rate limiting" instead of an outage of its own. Point `REDIS_URL` at a real managed Redis before exposing the external gateway to untrusted clients in production.

## Connection pool sizing — read before scaling replicas

The API scales horizontally via Kubernetes replicas (HPA: 2–8 for `datapilot-api`, 2–10 for `datapilot-worker`), not via multiple processes per pod — every replica opens its own SQLAlchemy connection pool against the same Postgres instance. Defaults are `DB_POOL_SIZE=5` / `DB_POOL_MAX_OVERFLOW=3` (8 connections/process); at max HPA scale-out that's `(8 + 10) x 8 = 144` possible connections against a Postgres default `max_connections` of 100. **This is not yet reconciled** — before running at real production replica counts, either raise `max_connections` on your Postgres instance, front it with PgBouncer, or lower `DB_POOL_SIZE`/`DB_POOL_MAX_OVERFLOW` to match your actual `maxReplicas`.

## Exposing traffic externally

This baseline only creates `ClusterIP` Services — nothing routes external traffic to them yet. See `ingress.example.yaml` for a vanilla-Kubernetes `Ingress` template and a commented-out OpenShift `Route` alternative; copy whichever matches your platform into your overlay, fill in the hostname/TLS placeholders, and add it to `kustomization.yaml`.

## NetworkPolicy — lateral-movement restriction, not egress control

`network-policy.yaml` closes the "every pod can reach every other pod" gap for **ingress**: a default-deny-ingress policy applies to every pod in the namespace, with explicit allows for `datapilot-api` (from `datapilot-web`/`datapilot-worker` on 8000) and `datapilot-web` (from those two, plus your ingress controller on 3000). `datapilot-worker` has no Service and gets no inbound allow rule at all under this baseline — it only makes outbound calls.

**Before applying, edit the `namespaceSelector` placeholder in `network-policy.yaml`'s `datapilot-web-allow-ingress` rule** to match your actual ingress controller's namespace/labels (e.g. nginx-ingress is commonly `kubernetes.io/metadata.name: ingress-nginx`) — left as the placeholder, external traffic to the web UI will be silently blocked.

This intentionally does **not** restrict egress. `datapilot-api`/`datapilot-worker` need broad outbound reach by design — connectors, MCP servers, and model providers are registered against arbitrary external endpoints at runtime, so a safe egress allowlist has to live at the network/firewall layer (cloud provider egress controls) where the destination list is centrally managed, not hardcoded into a namespace-scoped NetworkPolicy that has no way to know your cluster's pod/service CIDR.

## Required secrets

Create a `datapilot-runtime` secret in the target namespace with at least:

- `DATABASE_URL`
- `JWT_SECRET`
- `POSTGRES_PASSWORD` when the optional in-cluster PostgreSQL profile is used
- provider/connector secret environment variables referenced by DataPilot records

Set container images in `kustomization.yaml` or through the delivery pipeline. Never put credentials in ConfigMaps or source control.

## Apply

```sh
kubectl apply -k infra/kubernetes
kubectl -n datapilot rollout status deployment/datapilot-api
kubectl -n datapilot rollout status deployment/datapilot-web
kubectl -n datapilot rollout status deployment/datapilot-worker
```

Before production cutover, validate backup/restore, TLS ingress, network egress, managed-service availability, secret rotation, OTLP delivery, connection-pool sizing against your real `max_connections`, and a worker failure/retry drill.

## Known gaps in this baseline (honest, not yet closed)

- `NetworkPolicy` now restricts ingress (see above) but not egress — a compromised pod can still reach arbitrary external hosts, and cross-namespace egress within the cluster is unrestricted. Deliberate scope limit, not an oversight; see the NetworkPolicy section above for why.
- The worker's liveness probe checks that the `app.worker` process exists (`pgrep`), which catches crashes but not a hung-but-alive event loop. A heartbeat file or small health-check sidecar would close that gap.
- No autoscaling signal beyond CPU utilization — a burst of Temporal activity (e.g. many scheduled ingestions at once) that's I/O-bound rather than CPU-bound won't trigger the worker HPA. Worth adding a custom metric (e.g. Temporal task-queue depth) if that pattern shows up in practice.
