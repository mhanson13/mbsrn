# GKE Deployment And CI/CD

## Overview
Deployment targets Google Kubernetes Engine (containerd runtime) with OCI images stored in Artifact Registry.

CI/CD is implemented with GitHub Actions and Google Workload Identity Federation.
The target GKE cluster is currently managed manually outside deploy workflow execution.

Bootstrap/runbook:
- `docs/gcp-github-actions-bootstrap.md`
- `docs/deployment-configuration-contract.md` (canonical naming contract for deploy-time secrets/env/inputs)

## Kubernetes Assets

Kustomize manifests live under:
- `infra/k8s/base`
- `infra/k8s/overlays/dev`
- `infra/k8s/overlays/prod`

Base resources are namespace-neutral and include:
- API deployment + service
- Redis deployment + service (internal ClusterIP only)
- Operator UI deployment + service
- Ingress (same-host path routing: `/` -> UI, `/api` -> API)
- FrontendConfig (HTTP -> HTTPS redirect)
- ManagedCertificate (Google-managed TLS certificate)
- ConfigMap

Each overlay owns its namespace resource:
- `infra/k8s/overlays/dev/namespace.yaml` (`work-boots-dev`)
- `infra/k8s/overlays/prod/namespace.yaml` (`work-boots`)

A secret template is provided at:
- `infra/k8s/base/secrets.template.yaml`

## Build Strategy (No Docker Daemon)

Workflows use Google Cloud Buildpacks:
- `gcloud builds submit --pack image=...`
- deploy workflow passes explicit source staging dir:
  - `--gcs-source-staging-dir="${BUILD_SOURCE_DIR}"`

This produces OCI-compatible images suitable for containerd on GKE.

## GitHub Actions Workflows

- `backend-ci.yml`
  - Python dependency install
  - Alembic migration-chain validation (`alembic upgrade head`) against CI Postgres
  - CI uses ephemeral Postgres for migration validation via `postgres:16` in GitHub Actions.
  - pytest

- `frontend-ci.yml`
  - deterministic install (`npm ci`)
  - UI lint, typecheck, and production build
  - frontend test script execution only when a test script exists (none is currently defined)

- `deploy-gke.yml`
  - backend build gate:
    - install dependencies
    - pytest
    - build/push API image with Cloud Buildpacks
  - frontend build gate:
    - deterministic install (`npm ci`)
    - lint, typecheck, build
    - build/push UI image with Cloud Buildpacks
  - WIF auth to GCP
  - cluster credential retrieval
  - kustomize apply
  - Alembic migration gate (`alembic upgrade head`) before rollout
  - deployment image updates to exact image refs produced by build jobs
  - rollout verification

- `deploy-prod.yml`
  - push-to-main/workflow-dispatch production rollout path using `k8s/` manifests
  - includes explicit Redis apply for `mbsrn-redis` prior to API rollout

### Deployment Path Precedence
- Production-authoritative path:
  - `.github/workflows/deploy-prod.yml` + `k8s/*`
- Secondary/manual path:
  - `.github/workflows/deploy-gke.yml` + `infra/k8s/overlays/*`
- Session/Redis contract is standardized across both paths:
  - Redis workload/service name: `mbsrn-redis`
  - API Redis URL: `redis://mbsrn-redis:6379/0`

## Required GitHub Secrets/Variables

GitHub variable:

- `GCP_PROJECT_ID` (for example `work-boots`)

- `CONTAINER_REGISTRY_REGION`
- `CONTAINER_REGISTRY_REPOSITORY`
- `BUILD_SOURCE_DIR`
- `OIDC_WORKLOAD_IDENTITY_PROVIDER`
- `DEPLOY_SERVICE_ACCOUNT`
- `KUBERNETES_CLUSTER_NAME`
- `KUBERNETES_CLUSTER_LOCATION`
- `KUBERNETES_CLUSTER_LOCATION_TYPE` (`region` or `zone`)

Notes:
- `GCP_PROJECT_ID` in `deploy-gke.yml` is sourced from GitHub variable `GCP_PROJECT_ID` and is required.
- WIF auth uses `google-github-actions/auth@v3` with:
  - `workload_identity_provider: ${{ secrets.OIDC_WORKLOAD_IDENTITY_PROVIDER }}`
  - `service_account: ${{ secrets.DEPLOY_SERVICE_ACCOUNT }}`
- Deploy validates cluster target and fails fast before `get-credentials` if the cluster is missing.
- Deploy never creates foundational infrastructure (cluster/repository/WIF).
- Docker Hub secrets are not required for backend CI Postgres pulls in this repo.
- If your org later introduces Docker Hub auth for other workflows, use Docker Hub username + PAT (`DOCKERHUB_TOKEN`), not account password.

## Runtime Configuration

Kubernetes ConfigMap handles non-secret environment values.

Env rendering rule:
- every Kubernetes `env` entry must render from exactly one source (`value` or `valueFrom`, never both)
- optional blank literals must be omitted rather than rendered as an empty `value` alongside `valueFrom`

Schema management policy:
- Application startup does not manage production schema evolution.
- `DB_AUTO_CREATE_LOCAL` is a local/dev/test convenience guard only.
- CI and GKE deploy pipeline run Alembic migrations (`alembic upgrade head`) before rollout.

Kubernetes Secret handles sensitive values including:
- `DATABASE_URL` (recommended for production instead of ConfigMap default)
- `API_TOKEN_HASH_PEPPER`
- `APP_SESSION_SECRET`
- `GOOGLE_OIDC_CLIENT_ID`
- `GOOGLE_OIDC_CLIENT_SECRET`
- `GOOGLE_OAUTH_CLIENT_ID`
- `GOOGLE_OAUTH_CLIENT_SECRET`
- `GOOGLE_OAUTH_TOKEN_ENCRYPTION_KEYS_JSON`
- `GOOGLE_PLACES_API_KEY` (optional but recommended for Google Places seed discovery)
- provider credentials (Twilio/SMTP) when enabled

`work-boots-secrets` is required by both API/UI Deployments and migration Job (`envFrom.secretRef`).

Database URL safety contract:
- Non-local runtime (`APP_ENV`/`ENVIRONMENT` not local/dev/test) requires `DATABASE_URL`.
- In non-local runtime, localhost targets are rejected at startup:
  - `localhost`
  - `127.0.0.1`
  - `::1`
- API startup performs a fail-fast connectivity check (single `SELECT 1`) and exits on failure so Kubernetes can restart.
- Startup logs emit sanitized DB target only (no credentials):
  - `Database target resolved: host=<host>, port=<port>`

Production-authoritative path (`deploy-prod.yml` + `k8s/*`) injects `GOOGLE_PLACES_API_KEY` into
Kubernetes Secret `mbsrn-api-auth`, and API runtime consumes it via
`valueFrom.secretKeyRef` as `GOOGLE_PLACES_API_KEY`.

Session backend behavior:
- Supported backends: `SESSION_STATE_BACKEND=auto|redis|inmemory`.
- Redis-backed session state is required for correctness in multi-replica production.
- Redis is deployed in-cluster by manifests:
  - `infra/k8s/base/redis-deployment.yaml`
  - `infra/k8s/base/redis-service.yaml`
  - API runtime uses `REDIS_URL=redis://mbsrn-redis:6379/0`
- In-memory session state is process-local and non-shared across replicas; it is acceptable for local/dev/test only.
- `SESSION_STATE_ALLOW_INMEMORY_FALLBACK` controls whether in-memory fallback is allowed when Redis is unavailable/misconfigured.
- Production/staging fallback to in-memory emits degraded runtime logs:
  - `event=session_state_backend_selection ... selected_backend=inmemory ... degraded_mode=True`
- Operators should verify production pods are selecting `selected_backend=redis`.

Session production readiness checklist:
- `SESSION_STATE_BACKEND=redis`
- API pods resolve in-cluster Redis service (`mbsrn-redis:6379`)
- `SESSION_STATE_FAIL_OPEN=false`
- `SESSION_STATE_ALLOW_INMEMORY_FALLBACK=false`
- `mbsrn-redis` Deployment/Service are present in target namespace
- Startup/steady-state logs include:
  - `event=session_state_backend_selection ... selected_backend=redis`
- No production/staging logs with:
  - `event=session_state_backend_selection ... selected_backend=inmemory ... degraded_mode=True`

### Redis-Backed Session Verification (Production-Authoritative Path)
Use the namespace configured for `deploy-prod.yml` (`K8S_NAMESPACE`; currently `mbsrn`).

1. Verify Redis workload and service are present/running:

```bash
kubectl -n <namespace> get deploy mbsrn-redis
kubectl -n <namespace> rollout status deploy/mbsrn-redis --timeout=120s
kubectl -n <namespace> get svc mbsrn-redis
kubectl -n <namespace> get pods -l app=mbsrn-redis -o wide
```

2. Verify API deployment and live pod env wiring:

```bash
kubectl -n <namespace> get deploy mbsrn-api -o jsonpath="{range .spec.template.spec.containers[?(@.name=='mbsrn-api')].env[*]}{.name}={.value}{'\n'}{end}" | grep -E '^(REDIS_URL|SESSION_STATE_BACKEND|SESSION_STATE_ALLOW_INMEMORY_FALLBACK)='

kubectl -n <namespace> describe deploy mbsrn-api | grep -A5 -E 'SESSION_STATE_BACKEND|SESSION_STATE_ALLOW_INMEMORY_FALLBACK|REDIS_URL'

API_POD=$(kubectl -n <namespace> get pods -l app=mbsrn-api -o jsonpath='{.items[0].metadata.name}')
kubectl -n <namespace> exec "$API_POD" -- sh -c 'printenv | grep -E "^(REDIS_URL|SESSION_STATE_BACKEND|SESSION_STATE_ALLOW_INMEMORY_FALLBACK)="'
```

3. Verify backend selection logs from API:

```bash
kubectl -n <namespace> logs deploy/mbsrn-api --tail=500 | grep "session_state_backend_selection"
```

Expected healthy runtime:
- `REDIS_URL=redis://mbsrn-redis:6379/0`
- `SESSION_STATE_BACKEND=redis`
- `SESSION_STATE_ALLOW_INMEMORY_FALLBACK=false`
- log line contains:
  - `event=session_state_backend_selection`
  - `selected_backend=redis`
  - `degraded_mode=False`

Degraded fallback signal (production/staging; investigate immediately):
- `event=session_state_backend_selection`
- `selected_backend=inmemory`
- `degraded_mode=True`
- inspect `reason=...` for classification (`redis_not_configured_auto_fallback`, `redis_unavailable_fail_open:*`, etc.)

### Cloud Logging Queries (Session Backend)
Use Logs Explorer with these exact filters (adjust namespace if needed):

Healthy Redis selection:
```text
resource.type="k8s_container"
resource.labels.namespace_name="mbsrn"
resource.labels.container_name="mbsrn-api"
textPayload:"session_state_backend_selection"
textPayload:"selected_backend=redis"
textPayload:"degraded_mode=False"
```

Degraded in-memory fallback detection:
```text
resource.type="k8s_container"
resource.labels.namespace_name="mbsrn"
resource.labels.container_name="mbsrn-api"
textPayload:"session_state_backend_selection"
textPayload:"selected_backend=inmemory"
textPayload:"degraded_mode=True"
```

Session backend selection errors:
```text
resource.type="k8s_container"
resource.labels.namespace_name="mbsrn"
resource.labels.container_name="mbsrn-api"
severity>=ERROR
textPayload:"session_state_backend_selection"
(textPayload:"selected_backend=none" OR textPayload:"selected_backend=inmemory")
```

Prompt configuration note:
- production prompt overrides are managed in persisted business admin settings.
- deprecated legacy env prompt `AI_PROMPT_TEXT_RECOMMENDATION` is not required for API deployment wiring.

## Operational Notes

- API health endpoint: `/health`
- Deployments include readiness/liveness probes.
- Deploy runs are gated on successful backend and frontend image builds.
- Migrations must succeed before workload rollout proceeds.
- Rollback is available using standard Kubernetes rollout history commands.
- Public internet access is through GKE Ingress + external HTTP(S) load balancer.
- Ingress path routing uses one hostname:
  - `/` -> `work-boots-ui` service
  - `/api` -> `work-boots-api` service
- API and UI services remain internal `ClusterIP`; production NodePort exposure is not used.
