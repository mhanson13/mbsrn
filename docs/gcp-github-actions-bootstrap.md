# GCP Bootstrap For GitHub Actions Deploy

This runbook sets up a fresh or existing Google Cloud project so this repository can deploy with:
- GitHub Actions
- Workload Identity Federation (OIDC, no JSON keys)
- Artifact Registry
- Cloud Build
- GKE

Script:
- `scripts/bootstrap_gcp_github_actions.sh`
- Naming contract: `docs/deployment-configuration-contract.md`

Responsibility split:
- Bootstrap creates or reuses foundational cloud infrastructure.
- Deploy workflow validates required infrastructure and fails fast if missing.

## Inputs

Required:
- `GCP_PROJECT_ID`
- `CONTAINER_REGISTRY_REGION`
- `CONTAINER_REGISTRY_REPOSITORY`

Optional (with defaults):
- `REPO` (default: `mhanson13/work-boots`)
- `POOL_ID` (default: `github-pool`)
- `PROVIDER_ID` (default: `github-provider`)
- `SERVICE_ACCOUNT_ID` (default: `work-boots-github-deployer`)
- `BUILD_SOURCE_DIR` (default: `gs://<GCP_PROJECT_ID>-build-source/source`)
- `KUBERNETES_CLUSTER_NAME` (optional create/reuse target)
- `KUBERNETES_CLUSTER_LOCATION` (optional create/reuse target; region or zone)
- `KUBERNETES_CLUSTER_LOCATION_TYPE` (default: `region`; allowed: `region`, `zone`)
- `KUBERNETES_CLUSTER_MODE` (default: `autopilot`; allowed: `autopilot`, `standard`)

## Run

Example:

```bash
GCP_PROJECT_ID=work-boots \
CONTAINER_REGISTRY_REGION=us-central1 \
CONTAINER_REGISTRY_REPOSITORY=work-boots \
REPO=mhanson13/work-boots \
scripts/bootstrap_gcp_github_actions.sh
```

Flag-based equivalent:

```bash
scripts/bootstrap_gcp_github_actions.sh \
  --gcp-project-id work-boots \
  --container-registry-region us-central1 \
  --container-registry-repository work-boots \
  --kubernetes-cluster-name work-boots-cluster \
  --kubernetes-cluster-location us-central1 \
  --kubernetes-cluster-location-type region \
  --kubernetes-cluster-mode autopilot \
  --repo mhanson13/work-boots
```

Legacy flag aliases (`--project-id`, `--gar-location`, `--gar-repository`, `--build-source-bucket`, `--gke-cluster`, `--gke-location`, `--kubernetes-cluster-region`) are still accepted for transition, but canonical names are preferred.

## What The Script Configures

1. Enables required APIs:
   - `artifactregistry.googleapis.com`
   - `cloudbuild.googleapis.com`
   - `container.googleapis.com`
   - `iam.googleapis.com`
   - `iamcredentials.googleapis.com`
   - `sts.googleapis.com`
   - `serviceusage.googleapis.com`
   - `cloudresourcemanager.googleapis.com`
2. Creates or reuses:
   - Workload Identity Pool
   - GitHub OIDC provider
   - deploy service account
   - Artifact Registry Docker repository
3. Grants IAM roles to deploy service account:
   - `roles/serviceusage.serviceUsageConsumer`
   - `roles/cloudbuild.builds.editor`
   - `roles/artifactregistry.writer`
   - `roles/container.developer`
4. Creates or reuses Cloud Build source staging bucket from `BUILD_SOURCE_DIR`
   and grants bucket IAM:
   - deploy SA: `roles/storage.objectAdmin`
   - Cloud Build SA: `roles/storage.objectViewer`
5. Binds GitHub repo principal set to deploy service account:
   - `roles/iam.workloadIdentityUser`
6. Grants Artifact Registry writer on the target repository to:
   - `<PROJECT_NUMBER>@cloudbuild.gserviceaccount.com`
7. Optionally creates or reuses a Kubernetes cluster when both
   `KUBERNETES_CLUSTER_NAME` and `KUBERNETES_CLUSTER_LOCATION` are set:
   - `KUBERNETES_CLUSTER_MODE=autopilot` -> `gcloud container clusters create-auto`
   - `KUBERNETES_CLUSTER_MODE=standard` -> `gcloud container clusters create`
   - `KUBERNETES_CLUSTER_LOCATION_TYPE=zone` is supported for standard mode only

The script is idempotent where practical (create-if-missing, safe re-apply for IAM bindings).

## GitHub Secrets/Variables Required By Current Workflows

From `.github/workflows/deploy-gke.yml`:

GitHub variable:
- `GCP_PROJECT_ID` (for example `work-boots`)

- `OIDC_WORKLOAD_IDENTITY_PROVIDER`
- `DEPLOY_SERVICE_ACCOUNT`
- `CONTAINER_REGISTRY_REGION`
- `CONTAINER_REGISTRY_REPOSITORY`
- `BUILD_SOURCE_DIR`
- `KUBERNETES_CLUSTER_NAME`
- `KUBERNETES_CLUSTER_LOCATION`
- `KUBERNETES_CLUSTER_LOCATION_TYPE` (`region` or `zone`)

Notes:
- `GCP_PROJECT_ID` is read from required GitHub variable `GCP_PROJECT_ID` in workflow.
- Script prints exact values for:
  - `GCP_PROJECT_ID`
  - `OIDC_WORKLOAD_IDENTITY_PROVIDER`
  - `DEPLOY_SERVICE_ACCOUNT`
  - `CONTAINER_REGISTRY_REGION`
  - `CONTAINER_REGISTRY_REPOSITORY`
  - `BUILD_SOURCE_DIR`

## What Is Still Manual

- If you do not provide `KUBERNETES_CLUSTER_NAME` and `KUBERNETES_CLUSTER_LOCATION`, ensure the GKE cluster exists and set:
  - `KUBERNETES_CLUSTER_NAME`
  - `KUBERNETES_CLUSTER_LOCATION`
  - `KUBERNETES_CLUSTER_LOCATION_TYPE` when using a zonal cluster
- Ensure Kubernetes RBAC in the cluster allows deploy identity operations used by workflow:
  - `kubectl apply -k ...`
  - migration Job create/wait/log/delete
  - deployment image updates + rollout checks
- Reserve global static IPs and update ingress overlay placeholders before production traffic:
  - `infra/k8s/overlays/dev/kustomization.yaml`:
    - ingress host (example: `dev.workboots.example.com`)
    - annotation `kubernetes.io/ingress.global-static-ip-name` (example: `work-boots-dev-static-ip`)
    - managed certificate domain patch
  - `infra/k8s/overlays/prod/kustomization.yaml`:
    - ingress host (example: `workboots.example.com`)
    - annotation `kubernetes.io/ingress.global-static-ip-name` (example: `work-boots-prod-static-ip`)
    - managed certificate domain patch
- Point DNS records to the ingress external IP after apply.

## Public Access Model

- UI is public via GKE Ingress on `/`.
- API remains internal as a `ClusterIP` service and is exposed on the same hostname behind ingress path `/api`.
- No NodePort and no direct node exposure are used.

## Validate Readiness

After bootstrap:

```bash
gcloud iam workload-identity-pools providers describe <PROVIDER_ID> \
  --workload-identity-pool <POOL_ID> \
  --location global \
  --project <GCP_PROJECT_ID>

gcloud iam service-accounts get-iam-policy <SERVICE_ACCOUNT_EMAIL> \
  --project <GCP_PROJECT_ID>

gcloud artifacts repositories describe <CONTAINER_REGISTRY_REPOSITORY> \
  --location <CONTAINER_REGISTRY_REGION> \
  --project <GCP_PROJECT_ID>

# Regional cluster example:
gcloud container clusters describe <KUBERNETES_CLUSTER_NAME> \
  --region <KUBERNETES_CLUSTER_LOCATION> \
  --project <GCP_PROJECT_ID>

# Zonal cluster example:
gcloud container clusters describe <KUBERNETES_CLUSTER_NAME> \
  --zone <KUBERNETES_CLUSTER_LOCATION> \
  --project <GCP_PROJECT_ID>
```

Then run deploy pipeline from GitHub Actions:
- workflow: `deploy-gke`
- trusted events: `push` to `main` or `workflow_dispatch`
