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

### Production Ingress TLS Split (Authoritative `k8s/*` Path)

Production host routing is intentionally split:

- `app.mbsrn.com`:
  - Ingress: `mbsrn-ingress` (`k8s/app-ingress.yaml`)
  - Managed cert: `mbsrn-app-managed-cert` (`k8s/app-managed-certificate.yaml`)
  - FrontendConfig: `mbsrn-app-frontend-config` (`k8s/app-frontend-config.yaml`)
- `www.mbsrn.com`:
  - Ingress: `mbsrn-www-ingress` (`k8s/www-ingress.yaml`)
  - Managed cert: `mbsrn-www-managed-cert` (`k8s/www-managed-certificate.yaml`)
  - FrontendConfig: `mbsrn-www-frontend-config` (`k8s/www-frontend-config.yaml`)

Both ingresses use the GKE Ingress + ManagedCertificate model (not Gateway API).
Managed certificate binding is via ingress annotation:
`networking.gke.io/managed-certificates`.

Static IP behavior:
- app ingress (`k8s/app-ingress.yaml`) keeps explicit reserved IP annotation:
  - `kubernetes.io/ingress.global-static-ip-name: mbsrn-prod-static-ip`
- website ingress currently preserves its existing behavior and does not set a static-IP annotation in `k8s/www-ingress.yaml`.
  - If website IP pinning is required, add the known reserved IP resource name explicitly before recreating ingress resources.

Each overlay owns its namespace resource:
- `infra/k8s/overlays/dev/namespace.yaml` (`mbsrn-dev`)
- `infra/k8s/overlays/prod/namespace.yaml` (`mbsrn`)

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
  - preflight `DATABASE_URL` validation via `scripts/validate_production_database_url.py`
    using `DB_CONNECTION_MODE` (default `direct`, configurable)

- `deploy-prod.yml`
  - push-to-main/workflow-dispatch production rollout path using `k8s/` manifests
  - includes explicit Redis apply for `mbsrn-redis` prior to API rollout
  - preflight `DATABASE_URL` validation via `scripts/validate_production_database_url.py`
    using `DB_CONNECTION_MODE=direct` (cloud-native Postgres production contract)

- `deploy-www-prod.yml`
  - push-to-main/workflow-dispatch production rollout path for public website only
  - builds/pushes `frontend/www` image
  - applies website-only `k8s/www-*` resources
  - keeps `app.mbsrn.com` operator deployment path isolated

### Deployment Path Precedence
- Production-authoritative path:
  - `.github/workflows/deploy-prod.yml` + `k8s/*`
- Public-website production path:
  - `.github/workflows/deploy-www-prod.yml` + `k8s/www-*`
- Secondary/manual path:
  - `.github/workflows/deploy-gke.yml` + `infra/k8s/overlays/*`
- Session/Redis contract is standardized across both paths:
  - Redis workload/service name: `mbsrn-redis`
  - API Redis URL: `redis://mbsrn-redis:6379/0`

### GKE Resource Request Tuning (FinOps)

This section distinguishes declared (repo/workflow) resource values from admitted (live cluster) values in GKE Autopilot.

Declared/rendered source of truth for production UI/WWW CPU:
- `.github/workflows/deploy-prod.yml`:
  - `UI_CPU_REQUEST=100m`
  - `UI_CPU_LIMIT=500m`
- `.github/workflows/deploy-www-prod.yml`:
  - `WWW_CPU_REQUEST=100m`
  - `WWW_CPU_LIMIT=500m`
- Templates are rendered into:
  - `k8s/ui-deployment.yaml` (`__UI_CPU_REQUEST__`, `__UI_CPU_LIMIT__`)
  - `k8s/www-deployment.yaml` (`__WWW_CPU_REQUEST__`, `__WWW_CPU_LIMIT__`)

Observed production evidence (May 4, 2026):
- Workloads: `mbsrn-ui`, `mbsrn-www`
- Declared CPU request target: `100m`
- Live admitted CPU request: `308m`
- Live CPU limit: `500m`
- Live memory request/limit: `2Gi`
- Live ephemeral-storage request/limit: `4Gi`
- Rollout outcome at verification time: both deployments successful, healthy pods, `0` restarts observed

Interpretation:
- Google Cloud Billing/Recommender values (including very low values such as `4m`) are advisory and are not copied literally for production.
- In GKE Autopilot, admitted Pod resources can differ from declared values after admission/defaulting.
- With current memory sizing (`2Gi`), Autopilot admitted CPU request at `308m` for both UI/WWW in observed production state.
- Do not assume declared `100m` always equals live admitted `100m`.

Post-deploy verification commands (declared vs admitted):

```bash
kubectl -n mbsrn get deployment mbsrn-ui -o jsonpath='{.spec.template.spec.containers[0].resources}{"\n"}'
kubectl -n mbsrn get deployment mbsrn-www -o jsonpath='{.spec.template.spec.containers[0].resources}{"\n"}'
kubectl -n mbsrn rollout status deployment/mbsrn-ui
kubectl -n mbsrn rollout status deployment/mbsrn-www
kubectl -n mbsrn get pods -l app=mbsrn-ui
kubectl -n mbsrn get pods -l app=mbsrn-www
kubectl -n mbsrn get events --sort-by=.lastTimestamp | grep -i -E "autopilot|resource|cpu|memory|mbsrn-ui|mbsrn-www|mbsrn-api" | tail -50
```

Future tuning note:
- Do not reduce memory blindly.
- Review Cloud Monitoring memory working set and CPU throttling over 24-72 hours before changing memory.
- If memory usage remains comfortably below `2Gi`, consider a separate conservative change to reduce memory request/limit (for example toward `1Gi`), then re-check admitted CPU after rollout.
- `mbsrn-api` `FailedScheduling`/HPA warnings should be tracked as a separate follow-up review and are out of scope for this UI/WWW tuning pass.

### SEO Migration Managed Target Repo Contract

For migration-driven site repos, MBSRN acts as a control-plane orchestrator:

- one site targets one repo/workflow tuple in the destination repository.
- non-dry-run migration publish ensures the site workflow file exists at:
  - `.github/workflows/<workflow_id>`
- the workflow file is generated from an approved MBSRN-managed template mode (`deploy_workflow_mode`), currently `site_repo_template_v1`.
- admin-owned environment mapping metadata (`target_environment_key`, `target_environment_source`) is injected as template metadata; operators cannot edit these deploy routing controls from workspace UI.
- deploy execution remains in the target repo via GitHub Actions dispatch; MBSRN does not directly execute GKE deployment steps.

Operational implication:
- a repo can contain published artifact files but is not considered deploy-ready until workflow provisioning/verification succeeds on the target ref.

### Managed Site HTTPS Readiness Diagnostics

Managed site deploy readiness requires successful HTTPS reachability, not just control-plane alignment.

Important state:
- DNS/static IP/ingress/certificate checks can all be valid while `deploy_https_ready=false`.
- In this state, deploy diagnostics should preserve bounded probe evidence in `https_probe_error_summary`.
- `deploy_https_ready=false` with blank `https_probe_error_summary` is a diagnostics regression and should trigger workflow/template verification.
- selected workflow attempt outcome and current runtime outcome are distinct:
  - selected workflow failure remains historical evidence
  - current runtime state is derived from latest bounded HTTPS probe evidence when available
  - current runtime evidence precedence: `current_live_probe` -> `workflow_output` -> selected attempt -> summary fallback -> historical failure
  - refresh is scoped to the active route/workspace site id and may fall back to the latest deploy record for that site when selected artifact history is missing
- if selected workflow evidence collection failed but current live HTTPS probe succeeds, operator UI should report current runtime as healthy while preserving the failed selected attempt in history/diagnostics.
- static-IP reconciliation rules:
  - static IP ensure/describe uses bounded re-describe before classifying `managed_site_static_ip_address_missing`
  - stale selected-attempt static-IP-missing failures remain historical context and must not override healthy current live HTTPS evidence
- Expected reason-code families include:
  - `https_probe_failed_after_control_plane_ready`
  - `https_probe_timeout`
  - `https_probe_empty_reply`
  - `https_probe_not_attempted`
  - `ingress_backend_502` (kept distinct when backend returns 502)

Typical causes:
- backend service endpoints are not ready
- BackendConfig health checks do not match runtime behavior
- site runtime is not yet serving `/` successfully
- external load balancer convergence lag

Safe verification commands:

```bash
kubectl -n <namespace> get ingress
kubectl -n <namespace> get service site-web -o wide
kubectl -n <namespace> get endpoints site-web
kubectl -n <namespace> get pods -l app=site-web
kubectl -n <namespace> describe ingress site-web
kubectl -n <namespace> describe backendconfig site-web-backend-config-<site>
curl -Iv https://<preview-host>/
```

## Required GitHub Secrets/Variables

GitHub variable:

- `GCP_PROJECT_ID` (for example `mbsrn`)

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

`mbsrn-secrets` is required by both API/UI Deployments and migration Job (`envFrom.secretRef`).

Environment DB mode matrix:
- local/dev/test/ci (`APP_ENV` local-like):
  - local Postgres is allowed
  - localhost `DATABASE_URL` fallback is allowed
- production via `.github/workflows/deploy-prod.yml`:
  - `DB_CONNECTION_MODE=direct` is required
  - cloud-native Postgres target is required (non-loopback)
  - Cloud SQL preflight is not part of this branch
- optional proxy-backed deployments (non-default):
  - `DB_CONNECTION_MODE=cloudsql_proxy`
  - Cloud SQL-specific preflight/diagnostics can apply

Database URL safety contract:
- `APP_ENV` is the sole authority for localhost database safety checks.
- Localhost (`localhost`, `127.0.0.1`, `::1`) is allowed only when `APP_ENV` is one of:
  - `local`
  - `development`
  - `dev`
  - `test`
  - `ci`
- `APP_ENV=production` requires `DATABASE_URL` and rejects localhost targets at startup:
  - `localhost`
  - `127.0.0.1`
  - `::1`
- Production localhost exception is narrow and explicit:
  - localhost/loopback `DATABASE_URL` is allowed only when `DB_CONNECTION_MODE=cloudsql_proxy`
  - this is intended only for optional proxy-backed paths, not `deploy-prod.yml`
- Unknown or unset `APP_ENV` values reject localhost targets and require an explicit non-localhost `DATABASE_URL`.
- API startup performs a bounded connectivity check:
  - default mode: single `SELECT 1` attempt, then fail fast
  - `APP_ENV=production` + `DB_CONNECTION_MODE=cloudsql_proxy` + localhost target:
    bounded retry window (15 attempts, 1s delay) before failing
  - this retry path is for optional proxy-backed runtime only
- Startup logs emit sanitized DB target only (no credentials):
  - `Database target resolved: host=<host>, port=<port>`
- Schema readiness expectation is resolved from Alembic head at runtime (current repo head: `0039_competitor_domain_verification_status`).
- Production startup verification logs:
  - `Startup schema readiness expectation ... expected_revision=0039_competitor_domain_verification_status ...`
  - `Startup database connectivity check using cloudsql proxy retry budget ...` (only for proxy-backed localhost mode)
  - `Startup database connectivity check succeeded ... proxy_retry_path_entered=<bool> recovered_after_retry=<bool>`
  - `Schema readiness passed expected=... current=...`

### Production DATABASE_URL Source Of Truth (`deploy-prod.yml` path)
- Production-authoritative deploy path (`.github/workflows/deploy-prod.yml` + `k8s/*`) sources
  `DATABASE_URL` from GitHub secret `DATABASE_URL`.
- `deploy-prod.yml` enforces `DB_CONNECTION_MODE=direct` and treats any other mode as invalid.
- GitHub Actions config requirement for production:
  - repo variable `DB_CONNECTION_MODE` must be unset (workflow default remains `direct`) or explicitly `direct`
  - `cloudsql_proxy` in `deploy-prod.yml` is an invalid configuration and will fail fast with `production_db_mode_invalid`
- Cloud SQL instance inspection is not part of the `deploy-prod.yml` path.
- Deploy creates/updates Kubernetes secret `mbsrn-api-auth` with key `DATABASE_URL`.
- API runtime consumes `DATABASE_URL` only via:
  - `k8s/api-deployment.yaml` -> `env.valueFrom.secretKeyRef(name=mbsrn-api-auth,key=DATABASE_URL)`
- Production runtime wiring in manifests is explicit:
  - `APP_ENV=production`
  - `DB_CONNECTION_MODE=direct`
  - `DATABASE_URL` from `mbsrn-api-auth.DATABASE_URL`
- Migration and retention jobs consume the same secret/key wiring:
  - `k8s/api-migration-job.yaml`
  - `k8s/api-migration-baseline-job.yaml`
  - `k8s/api-seo-competitor-profile-retention-cronjob.yaml`
- `deploy-prod.yml` fails fast when:
  - `DB_CONNECTION_MODE` is not `direct` (`production_db_mode_invalid`)
  - rendered API manifest does not wire `DATABASE_URL` via `secretKeyRef`
  - rendered API manifest contains a literal `DATABASE_URL` value
- Accepted production `DATABASE_URL` forms for `deploy-prod.yml` direct mode include non-loopback host targets such as:
  - in-cluster service DNS:
    - `postgresql+psycopg://<user>:<password>@<postgres-service>.<namespace>.svc.cluster.local:5432/<database>`
  - managed/external Postgres endpoint:
    - `postgresql://<user>:<password>@<managed-postgres-hostname>:5432/<database>`
- Rejected in `deploy-prod.yml` direct mode:
  - localhost/loopback targets (`localhost`, `127.0.0.1`, `::1`)
  - Cloud SQL proxy localhost assumptions
- `deploy-prod.yml` validates the effective connection target host/socket path and rejects loopback.

### Shared DATABASE_URL Validation Policy (Both Deploy Workflows)
- Both `.github/workflows/deploy-prod.yml` and `.github/workflows/deploy-gke.yml`
  call the shared validator:
  - `python scripts/validate_production_database_url.py --env-var DATABASE_URL --db-connection-mode-env-var DB_CONNECTION_MODE`
- Effective policy is mode-aware and matches runtime safety intent:
  - loopback rejected unless `DB_CONNECTION_MODE=cloudsql_proxy`
  - remote host allowed
  - socket-style cloud-native URL forms allowed
  - unknown `DB_CONNECTION_MODE` rejected
- `deploy-prod.yml` enforces `DB_CONNECTION_MODE=direct` to keep production on cloud-native Postgres.
- Recommended `deploy-gke.yml` default is `DB_CONNECTION_MODE=direct`; set `cloudsql_proxy`
  only when that deployment path is intentionally proxy-backed.

### Rollout Diagnostics For DATABASE_URL Wiring
On `mbsrn-api` rollout failure, `deploy-prod.yml` now emits safe diagnostics (no secret values):
- `mbsrn-api` env var names and source type (literal / `secretKeyRef` / `configMapKeyRef`)
- explicit `DATABASE_URL` env source classification
- secret/key presence check for `mbsrn-api-auth.DATABASE_URL`
- deployment describe + pod listing + recent API logs for context
- env-source rendering is produced by `scripts/print_api_env_wiring.py` (no inline heredoc parsing)
- Preflight database diagnostics include:
  - parsed scheme
  - effective target source classification (`url:hostname`, `query:host`, `query:unix_sock`, etc.)
  - query parameter presence/keys
  - socket-style detection
  - loopback detection result
  - final accept/reject result

### Quick Triage: Production DB Mode Mismatch
If API startup fails with:

- `Startup database connectivity check failed`
- `connection to server at "127.0.0.1", port 5432 failed: Connection refused`

validate the production DB path in this order:

1. `deploy-prod.yml` must run with:
   - `APP_ENV=production`
   - `DB_CONNECTION_MODE=direct`
2. `DATABASE_URL` must resolve to a non-loopback target for direct mode.
   - If validation reports `target_kind=loopback_host`, update the production `DATABASE_URL` value to a non-loopback service/hostname.
3. Confirm `mbsrn-api-auth` has `DATABASE_URL` and rendered manifests wire it by `secretKeyRef`.
4. If `production_db_mode_invalid` appears, correct the repo variable `DB_CONNECTION_MODE` to `direct`.
   - deploy logs now include a warning line with the received mode and source classification (`repo_variable` vs `workflow_default_direct`).
5. Confirm API startup diagnostics show sanitized DB target and mode:
   - `app_env`, `db_connection_mode`, host/port classification.

The API startup check retry path for proxy-backed localhost mode applies only to optional `DB_CONNECTION_MODE=cloudsql_proxy` deployments (for example, a consciously configured `deploy-gke.yml` path). It is not the standard `deploy-prod.yml` production contract.

### Where To Update Production `DATABASE_URL`
- Source of truth for `deploy-prod.yml`: GitHub Actions **repo secret** `DATABASE_URL`.
- Flow:
  1. update GitHub repo secret `DATABASE_URL` to the intended non-loopback production endpoint value
  2. run `deploy-prod.yml`
  3. workflow writes secret value into Kubernetes secret `mbsrn-api-auth` key `DATABASE_URL`
  4. API + migration jobs consume `mbsrn-api-auth.DATABASE_URL` via `secretKeyRef`

### Legacy Optional Cloud SQL Proxy Diagnostic Path
Use this sequence only when a deployment is intentionally configured for `DB_CONNECTION_MODE=cloudsql_proxy` and API startup still fails after retry budget exhaustion.

1. Inspect sidecar logs directly:

```bash
kubectl logs -n mbsrn deployment/mbsrn-api -c cloud-sql-proxy --tail=200
```

2. Verify pod/container health and restart behavior:

```bash
kubectl get pods -n mbsrn -o wide
kubectl describe pod <pod_name> -n mbsrn
```

3. Verify deployed proxy args and expected port wiring:

```bash
kubectl -n mbsrn get deploy mbsrn-api -o yaml | sed -n '/name: cloud-sql-proxy/,$p'
```

Expected key args:
- `--port=5432`
- `<instance-connection-name>` (resolved from `CLOUD_SQL_INSTANCE_CONNECTION_NAME`)

4. Verify in-pod listener state:

```bash
kubectl exec -it <pod_name> -n mbsrn -- sh -c "netstat -tlnp || ss -tlnp"
```

Expected:
- listener on `127.0.0.1:5432` (or `0.0.0.0:5432` in equivalent proxy mode)

5. Verify Cloud SQL env injection in the running pod:

```bash
kubectl exec -it <pod_name> -n mbsrn -- env | grep CLOUD_SQL
```

Expected:
- `CLOUD_SQL_INSTANCE_CONNECTION_NAME` present and non-empty

6. Verify runtime identity has Cloud SQL client permission:

```bash
gcloud projects get-iam-policy mbsrn-prod \
  --flatten="bindings[].members" \
  --format="table(bindings.role, bindings.members)" \
  | grep mbsrn-api
```

Expected:
- runtime GSA used by `mbsrn-api` has `roles/cloudsql.client`

#### Error → Likely Cause Mapping
- `cloud-sql-proxy` container CrashLoopBackOff + logs show credential/permission errors:
  - Workload Identity mapping missing on KSA, or runtime GSA missing `roles/cloudsql.client`
- logs show invalid/unknown instance connection name:
  - bad `CLOUD_SQL_INSTANCE_CONNECTION_NAME` secret value or wrong project/region/instance tuple
- sidecar running but no `:5432` listener:
  - proxy args/flags malformed or startup fatal before bind
- sidecar running with listener but app still gets refusal:
  - wrong target host/port in effective `DATABASE_URL`, or app container not sharing expected pod net namespace (rare; validate manifest/runtime)

Keep diagnostics sanitized:
- do not print DB credentials
- log host/port and mode only

### Distinguish Proxy-Health Failures From Rollout/Capacity Churn
Recent production evidence confirmed an important split:

- Proxy-health path can be fully healthy (`cloud-sql-proxy` auth/listen/accepted connections),
  while rollout still shows transient readiness failures due to scheduling pressure and
  replacement timing.

Treat these as separate failure classes:

1. Proxy-health failure:
   - proxy container cannot authenticate/start/listen/connect
2. Rollout/resource-pressure churn:
   - events show `FailedScheduling` (`Insufficient cpu/memory`) and transient readiness probe
     connection-refused on newly replaced API pods

When diagnosing rollout churn, capture pod-specific previous logs (not deployment aggregate logs):

```bash
kubectl get pods -n mbsrn -l app=mbsrn-api -o wide
kubectl describe pod <failing-api-pod> -n mbsrn
kubectl logs -n mbsrn pod/<failing-api-pod> -c mbsrn-api --previous --tail=300
kubectl logs -n mbsrn pod/<failing-api-pod> -c cloud-sql-proxy --previous --tail=300
kubectl get events -n mbsrn --sort-by=.metadata.creationTimestamp | tail -n 150
```

Correlation guidance:
- If proxy previous logs still show healthy auth/listen and accepted local connections,
  but events show scheduling pressure/readiness churn, prioritize rollout/capacity tuning
  over DB/proxy changes.
- If proxy previous logs show auth/instance/bind errors, follow the proxy-health path above.

Important separation:
- `mbsrn-seo-competitor-profile-retention` `StartError` triage is a separate operational issue
  and should not be used as evidence for API rollout DB/proxy regressions.

Production-authoritative path (`deploy-prod.yml` + `k8s/*`) injects `GOOGLE_PLACES_API_KEY` into
Kubernetes Secret `mbsrn-api-auth`, and API runtime consumes it via
`valueFrom.secretKeyRef` as `GOOGLE_PLACES_API_KEY`.

Search Console runtime wiring in the same production-authoritative path:

- `SEARCH_CONSOLE_CREDENTIALS_JSON` is injected into `mbsrn-api-auth` (from GitHub secret scope).
- `k8s/api-deployment.yaml` consumes `SEARCH_CONSOLE_CREDENTIALS_JSON` via `valueFrom.secretKeyRef`.
- `SEARCH_CONSOLE_CREDENTIALS_JSON` is optional; when omitted, runtime ADC fallback is used.
- Search Console property URL enablement is configured per-site in application data (`seo_sites.search_console_property_url` + `search_console_enabled`), not as app-global env.

GA4 runtime wiring in the same production-authoritative path:

- `GA4_CREDENTIALS_JSON` is injected into `mbsrn-api-auth` (from GitHub secret scope).
- `k8s/api-deployment.yaml` consumes `GA4_CREDENTIALS_JSON` via `valueFrom.secretKeyRef`.
- `GA4_CREDENTIALS_JSON` is optional; when omitted, runtime ADC fallback is used.
- `GA4_PROPERTY_ID` remains optional in discovery-first onboarding mode:
  - account discovery can run without it
  - site-level traffic summary requires a configured property id
- GA4 onboarding state is persisted per-site in application data (`seo_sites.ga4_*` fields), not as app-global property binding.

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
  - `/` -> `mbsrn-ui` service
  - `/api` -> `mbsrn-api` service
- API and UI services remain internal `ClusterIP`; production NodePort exposure is not used.

### TLS Verification Commands (Post-Deploy)

For full production cutover order (DNS + TLS + OAuth GO/NO-GO), use:
- `docs/runbooks/dns-tls-oauth-cutover.md`

```bash
kubectl get managedcertificate -n mbsrn
kubectl describe managedcertificate mbsrn-app-managed-cert -n mbsrn
kubectl describe managedcertificate mbsrn-www-managed-cert -n mbsrn
kubectl get ingress -n mbsrn

curl -I https://app.mbsrn.com
curl -I https://www.mbsrn.com
```

Expected:
- both managed certificates progress to `Active`
- both ingresses retain their intended host mapping
- HTTPS is reachable for both domains without certificate warnings

Caveat:
- Managed certificate provisioning is not instant; allow for propagation/issuance delay before treating initial non-Active states as failure.
- App ingress currently enables HTTP->HTTPS redirect via `mbsrn-app-frontend-config`; keep OAuth redirect URIs configured as HTTPS (`https://app.mbsrn.com/...`) before enforcing production OAuth publishing changes.
