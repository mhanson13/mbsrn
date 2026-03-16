# GKE Deployment And CI/CD

## Overview
Deployment targets Google Kubernetes Engine (containerd runtime) with OCI images stored in Artifact Registry.

CI/CD is implemented with GitHub Actions and Google Workload Identity Federation.

## Kubernetes Assets

Kustomize manifests live under:
- `infra/k8s/base`
- `infra/k8s/overlays/dev`
- `infra/k8s/overlays/prod`

Base resources are namespace-neutral and include:
- API deployment + service
- Operator UI deployment + service
- Ingress (API + UI paths)
- ConfigMap

Each overlay owns its namespace resource:
- `infra/k8s/overlays/dev/namespace.yaml` (`work-boots-dev`)
- `infra/k8s/overlays/prod/namespace.yaml` (`work-boots`)

A secret template is provided at:
- `infra/k8s/base/secrets.template.yaml`

## Build Strategy (No Docker Daemon)

Workflows use Google Cloud Buildpacks:
- `gcloud builds submit --pack image=...`

This produces OCI-compatible images suitable for containerd on GKE.

## GitHub Actions Workflows

- `backend-ci.yml`
  - Python dependency install
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

## Required GitHub Secrets

- `GCP_PROJECT_ID`
- `GAR_LOCATION`
- `GAR_REPOSITORY`
- `GCP_WIF_PROVIDER`
- `GCP_WIF_SERVICE_ACCOUNT`
- `GKE_CLUSTER`
- `GKE_LOCATION`

## Runtime Configuration

Kubernetes ConfigMap handles non-secret environment values.

Kubernetes Secret handles sensitive values including:
- `API_TOKEN_HASH_PEPPER`
- `APP_SESSION_SECRET`
- `GOOGLE_OIDC_CLIENT_ID`
- `GOOGLE_OIDC_CLIENT_SECRET`
- provider credentials (Twilio/SMTP) when enabled

## Operational Notes

- API health endpoint: `/health`
- Deployments include readiness/liveness probes.
- Deploy runs are gated on successful backend and frontend image builds.
- Migrations must succeed before workload rollout proceeds.
- Rollback is available using standard Kubernetes rollout history commands.
