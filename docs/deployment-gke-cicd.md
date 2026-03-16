# GKE Deployment And CI/CD

## Overview
Deployment targets Google Kubernetes Engine (containerd runtime) with OCI images stored in Artifact Registry.

CI/CD is implemented with GitHub Actions and Google Workload Identity Federation.

## Kubernetes Assets

Kustomize manifests live under:
- `infra/k8s/base`
- `infra/k8s/overlays/dev`
- `infra/k8s/overlays/prod`

Base resources include:
- API deployment + service
- Operator UI deployment + service
- Ingress (API + UI paths)
- ConfigMap
- Namespace

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
  - build/push API image on `main`

- `frontend-ci.yml`
  - Node install
  - UI lint/build
  - build/push UI image on `main`

- `deploy-gke.yml`
  - WIF auth to GCP
  - cluster credential retrieval
  - kustomize apply
  - deployment image updates to current SHA
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
- Rollback is available using standard Kubernetes rollout history commands.
