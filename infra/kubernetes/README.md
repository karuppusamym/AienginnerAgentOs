# DataPilot Kubernetes baseline

This is a production deployment baseline, not a replacement for environment-specific platform controls. It assumes managed PostgreSQL, Redis, Qdrant, Temporal and an OTLP collector are supplied outside this overlay.

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

Before production cutover, validate backup/restore, TLS ingress, network egress, managed-service availability, secret rotation, OTLP delivery, and a worker failure/retry drill.
