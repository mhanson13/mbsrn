# GCP Bootstrap For GitHub Actions Deploy

This runbook sets up a fresh or existing Google Cloud project so this repository can deploy with:
- GitHub Actions
- Workload Identity Federation (OIDC, no JSON keys)
- Artifact Registry
- Cloud Build
- GKE

Script:
- `scripts/bootstrap_gcp_github_actions.sh`

## Inputs

Required:
- `PROJECT_ID`
- `GAR_LOCATION`
- `GAR_REPOSITORY`

Optional (with defaults):
- `REPO` (default: `mhanson13/work-boots`)
- `POOL_ID` (default: `github-pool`)
- `PROVIDER_ID` (default: `github-provider`)
- `SERVICE_ACCOUNT_ID` (default: `work-boots-github-deployer`)
- `BUILD_SOURCE_BUCKET` (default: `gs://<PROJECT_ID>-build-source/source`)
- `GKE_CLUSTER` (for output/manual checklist only)
- `GKE_LOCATION` (for output/manual checklist only)

## Run

Example:

```bash
PROJECT_ID=work-boots \
GAR_LOCATION=us-central1 \
GAR_REPOSITORY=work-boots \
REPO=mhanson13/work-boots \
scripts/bootstrap_gcp_github_actions.sh
```

Flag-based equivalent:

```bash
scripts/bootstrap_gcp_github_actions.sh \
  --project-id work-boots \
  --gar-location us-central1 \
  --gar-repository work-boots \
  --repo mhanson13/work-boots
```

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
4. Creates or reuses Cloud Build source staging bucket from `BUILD_SOURCE_BUCKET`
   and grants bucket IAM:
   - deploy SA: `roles/storage.objectAdmin`
   - Cloud Build SA: `roles/storage.objectViewer`
5. Binds GitHub repo principal set to deploy service account:
   - `roles/iam.workloadIdentityUser`
6. Grants Artifact Registry writer on the target repository to:
   - `<PROJECT_NUMBER>@cloudbuild.gserviceaccount.com`

The script is idempotent where practical (create-if-missing, safe re-apply for IAM bindings).

## GitHub Secrets Required By Current Workflows

From `.github/workflows/deploy-gke.yml`:

- `GCP_WORKLOAD_IDENTITY_PROVIDER`
- `GCP_SERVICE_ACCOUNT_EMAIL`
- `GAR_LOCATION`
- `GAR_REPOSITORY`
- `BUILD_SOURCE_BUCKET`
- `GKE_CLUSTER`
- `GKE_LOCATION`

Notes:
- `PROJECT_ID` is deterministic in workflow (`work-boots`) and not secret-backed.
- Script prints exact values for:
  - `GCP_WORKLOAD_IDENTITY_PROVIDER`
  - `GCP_SERVICE_ACCOUNT_EMAIL`
  - `GAR_LOCATION`
  - `GAR_REPOSITORY`
  - `BUILD_SOURCE_BUCKET`

## What Is Still Manual

- Ensure the GKE cluster exists and set:
  - `GKE_CLUSTER`
  - `GKE_LOCATION`
- Ensure Kubernetes RBAC in the cluster allows deploy identity operations used by workflow:
  - `kubectl apply -k ...`
  - migration Job create/wait/log/delete
  - deployment image updates + rollout checks

## Validate Readiness

After bootstrap:

```bash
gcloud iam workload-identity-pools providers describe <PROVIDER_ID> \
  --workload-identity-pool <POOL_ID> \
  --location global \
  --project <PROJECT_ID>

gcloud iam service-accounts get-iam-policy <SERVICE_ACCOUNT_EMAIL> \
  --project <PROJECT_ID>

gcloud artifacts repositories describe <GAR_REPOSITORY> \
  --location <GAR_LOCATION> \
  --project <PROJECT_ID>
```

Then run deploy pipeline from GitHub Actions:
- workflow: `deploy-gke`
- trusted events: `push` to `main` or `workflow_dispatch`
