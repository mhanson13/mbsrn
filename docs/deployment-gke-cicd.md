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
- `REDIS_URL`
- `API_TOKEN_HASH_PEPPER`
- `APP_SESSION_SECRET`
- `GOOGLE_OIDC_CLIENT_ID`
- `GOOGLE_OIDC_CLIENT_SECRET`
- `GOOGLE_OAUTH_CLIENT_ID`
- `GOOGLE_OAUTH_CLIENT_SECRET`
- `GOOGLE_OAUTH_TOKEN_ENCRYPTION_KEYS_JSON`
- provider credentials (Twilio/SMTP) when enabled

`work-boots-secrets` is required by both API/UI Deployments and migration Job (`envFrom.secretRef`).

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
