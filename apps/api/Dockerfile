FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# procps provides pgrep, used by infra/kubernetes/worker.yaml's liveness
# probe (this same image runs both the API and the Temporal worker — see
# compose.yaml/worker.yaml — and python:3.12-slim doesn't ship it).
RUN apt-get update \
    && apt-get install -y --no-install-recommends procps \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
RUN mkdir -p /data/uploads

# Run as a fixed non-root UID, group 0 ("root group"). This is deliberately
# compatible with two different deployment models:
#   - plain Docker / vanilla Kubernetes: runs as UID 1001 as declared here.
#   - OpenShift (OCP): the default "restricted" SCC ignores this USER line
#     and instead injects an arbitrary high UID at pod start, but always
#     keeps that UID in group 0. Because /app and /data/uploads are
#     group-owned by 0 with group-write permission (`chmod -R g=u`), the
#     arbitrary OCP UID can still write uploads and any runtime files
#     regardless of which numeric UID the platform assigns.
RUN chown -R 1001:0 /app /data/uploads \
    && chmod -R g=u /app /data/uploads
USER 1001:0

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
