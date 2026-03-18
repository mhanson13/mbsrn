#!/usr/bin/env bash

set -euo pipefail

usage() {
  cat <<'EOF'
Bootstrap Google Cloud for Work Boots GitHub Actions deploys (WIF + GAR + IAM).

Usage:
  scripts/bootstrap_gcp_github_actions.sh --project-id <PROJECT_ID> --gar-location <REGION> --gar-repository <NAME> [options]

Options:
  --project-id <id>            GCP project ID (required; no default)
  --repo <owner/name>          GitHub repo allowed to impersonate via WIF (default: mhanson13/work-boots)
  --pool-id <id>               Workload Identity Pool ID (default: github-pool)
  --provider-id <id>           Workload Identity Provider ID (default: github-provider)
  --service-account-id <id>    Deployer service account ID (default: work-boots-github-deployer)
  --gar-location <region>      Artifact Registry region (required)
  --gar-repository <name>      Artifact Registry repository name (required)
  --build-source-bucket <gs://...>  Cloud Build source staging dir (default: gs://<PROJECT_ID>-build-source/source)
  --gke-cluster <name>         Optional: cluster name for output/validation notes
  --gke-location <region>      Optional: cluster region for output/validation notes
  --help                       Show help

Environment variables are also supported:
  PROJECT_ID, REPO, POOL_ID, PROVIDER_ID, SERVICE_ACCOUNT_ID,
  GAR_LOCATION, GAR_REPOSITORY, BUILD_SOURCE_BUCKET, GKE_CLUSTER, GKE_LOCATION

Example:
  PROJECT_ID=work-boots GAR_LOCATION=us-central1 GAR_REPOSITORY=work-boots \
  scripts/bootstrap_gcp_github_actions.sh
EOF
}

require_cmd() {
  local cmd="$1"
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    echo "ERROR: required command not found: ${cmd}" >&2
    exit 1
  fi
}

trimmed_nonempty() {
  local value="${1:-}"
  [[ -n "${value//[[:space:]]/}" ]]
}

PROJECT_ID="${PROJECT_ID:-}"
REPO="${REPO:-mhanson13/work-boots}"
POOL_ID="${POOL_ID:-github-pool}"
PROVIDER_ID="${PROVIDER_ID:-github-provider}"
SERVICE_ACCOUNT_ID="${SERVICE_ACCOUNT_ID:-work-boots-github-deployer}"
GAR_LOCATION="${GAR_LOCATION:-}"
GAR_REPOSITORY="${GAR_REPOSITORY:-}"
BUILD_SOURCE_BUCKET="${BUILD_SOURCE_BUCKET:-}"
GKE_CLUSTER="${GKE_CLUSTER:-}"
GKE_LOCATION="${GKE_LOCATION:-}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-id)
      PROJECT_ID="$2"
      shift 2
      ;;
    --repo)
      REPO="$2"
      shift 2
      ;;
    --pool-id)
      POOL_ID="$2"
      shift 2
      ;;
    --provider-id)
      PROVIDER_ID="$2"
      shift 2
      ;;
    --service-account-id)
      SERVICE_ACCOUNT_ID="$2"
      shift 2
      ;;
    --gar-location)
      GAR_LOCATION="$2"
      shift 2
      ;;
    --gar-repository)
      GAR_REPOSITORY="$2"
      shift 2
      ;;
    --build-source-bucket)
      BUILD_SOURCE_BUCKET="$2"
      shift 2
      ;;
    --gke-cluster)
      GKE_CLUSTER="$2"
      shift 2
      ;;
    --gke-location)
      GKE_LOCATION="$2"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if ! trimmed_nonempty "${PROJECT_ID}"; then
  echo "ERROR: PROJECT_ID is required." >&2
  exit 1
fi
if ! trimmed_nonempty "${GAR_LOCATION}"; then
  echo "ERROR: GAR_LOCATION is required." >&2
  exit 1
fi
if ! trimmed_nonempty "${GAR_REPOSITORY}"; then
  echo "ERROR: GAR_REPOSITORY is required." >&2
  exit 1
fi
if [[ ! "${REPO}" =~ ^[^/]+/[^/]+$ ]]; then
  echo "ERROR: REPO must be in owner/name format. Got: ${REPO}" >&2
  exit 1
fi
if ! trimmed_nonempty "${BUILD_SOURCE_BUCKET}"; then
  BUILD_SOURCE_BUCKET="gs://${PROJECT_ID}-build-source/source"
fi
if [[ ! "${BUILD_SOURCE_BUCKET}" =~ ^gs://[^/]+(/.*)?$ ]]; then
  echo "ERROR: BUILD_SOURCE_BUCKET must be a gs:// URI. Got: ${BUILD_SOURCE_BUCKET}" >&2
  exit 1
fi

require_cmd gcloud

ACTIVE_ACCOUNT="$(gcloud auth list --filter=status:ACTIVE --format='value(account)' | head -n1 || true)"
if ! trimmed_nonempty "${ACTIVE_ACCOUNT}"; then
  echo "ERROR: no active gcloud account found. Run: gcloud auth login" >&2
  exit 1
fi

if ! gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)' >/dev/null 2>&1; then
  echo "ERROR: project not found or not accessible: ${PROJECT_ID}" >&2
  exit 1
fi

PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')"
if ! trimmed_nonempty "${PROJECT_NUMBER}"; then
  echo "ERROR: unable to resolve project number for ${PROJECT_ID}" >&2
  exit 1
fi

SERVICE_ACCOUNT_EMAIL="${SERVICE_ACCOUNT_ID}@${PROJECT_ID}.iam.gserviceaccount.com"
WIF_PROVIDER_RESOURCE="projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_ID}/providers/${PROVIDER_ID}"
REPO_PRINCIPAL_SET="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_ID}/attribute.repository/${REPO}"
CLOUDBUILD_SERVICE_ACCOUNT="${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com"
SOURCE_BUCKET_NAME="${BUILD_SOURCE_BUCKET#gs://}"
SOURCE_BUCKET_NAME="${SOURCE_BUCKET_NAME%%/*}"
SOURCE_BUCKET_URI="gs://${SOURCE_BUCKET_NAME}"

echo "==> Bootstrap configuration"
echo "PROJECT_ID=${PROJECT_ID}"
echo "PROJECT_NUMBER=${PROJECT_NUMBER}"
echo "REPO=${REPO}"
echo "POOL_ID=${POOL_ID}"
echo "PROVIDER_ID=${PROVIDER_ID}"
echo "SERVICE_ACCOUNT_EMAIL=${SERVICE_ACCOUNT_EMAIL}"
echo "GAR_LOCATION=${GAR_LOCATION}"
echo "GAR_REPOSITORY=${GAR_REPOSITORY}"
echo "BUILD_SOURCE_BUCKET=${BUILD_SOURCE_BUCKET}"
if trimmed_nonempty "${GKE_CLUSTER}"; then
  echo "GKE_CLUSTER=${GKE_CLUSTER}"
fi
if trimmed_nonempty "${GKE_LOCATION}"; then
  echo "GKE_LOCATION=${GKE_LOCATION}"
fi

echo "==> Enabling required APIs"
gcloud services enable \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  container.googleapis.com \
  iam.googleapis.com \
  iamcredentials.googleapis.com \
  storage.googleapis.com \
  sts.googleapis.com \
  serviceusage.googleapis.com \
  cloudresourcemanager.googleapis.com \
  --project "${PROJECT_ID}" >/dev/null

echo "==> Ensuring Artifact Registry repository exists"
if ! gcloud artifacts repositories describe "${GAR_REPOSITORY}" \
  --location "${GAR_LOCATION}" \
  --project "${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud artifacts repositories create "${GAR_REPOSITORY}" \
    --repository-format docker \
    --location "${GAR_LOCATION}" \
    --description "Work Boots API/UI container images" \
    --project "${PROJECT_ID}" >/dev/null
  echo "Created Artifact Registry repository: ${GAR_REPOSITORY}"
else
  echo "Artifact Registry repository already exists: ${GAR_REPOSITORY}"
fi

echo "==> Ensuring Cloud Build source staging bucket exists"
if ! gcloud storage buckets describe "${SOURCE_BUCKET_URI}" --project "${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud storage buckets create "${SOURCE_BUCKET_URI}" \
    --location "${GAR_LOCATION}" \
    --uniform-bucket-level-access \
    --project "${PROJECT_ID}" >/dev/null
  echo "Created GCS bucket: ${SOURCE_BUCKET_URI}"
else
  echo "GCS bucket already exists: ${SOURCE_BUCKET_URI}"
fi

echo "==> Ensuring Workload Identity Pool exists"
if ! gcloud iam workload-identity-pools describe "${POOL_ID}" \
  --location "global" \
  --project "${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud iam workload-identity-pools create "${POOL_ID}" \
    --location "global" \
    --display-name "GitHub Actions Pool" \
    --description "WIF trust boundary for GitHub Actions deploys" \
    --project "${PROJECT_ID}" >/dev/null
  echo "Created WIF pool: ${POOL_ID}"
else
  echo "WIF pool already exists: ${POOL_ID}"
fi

echo "==> Ensuring Workload Identity Provider exists"
if ! gcloud iam workload-identity-pools providers describe "${PROVIDER_ID}" \
  --workload-identity-pool "${POOL_ID}" \
  --location "global" \
  --project "${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud iam workload-identity-pools providers create-oidc "${PROVIDER_ID}" \
    --workload-identity-pool "${POOL_ID}" \
    --location "global" \
    --issuer-uri "https://token.actions.githubusercontent.com" \
    --allowed-audiences "https://github.com/${REPO}" \
    --attribute-mapping "google.subject=assertion.sub,attribute.actor=assertion.actor,attribute.repository=assertion.repository,attribute.repository_owner=assertion.repository_owner,attribute.ref=assertion.ref" \
    --attribute-condition "assertion.repository=='${REPO}' && assertion.ref=='refs/heads/main'" \
    --display-name "GitHub OIDC Provider" \
    --project "${PROJECT_ID}" >/dev/null
  echo "Created WIF provider: ${PROVIDER_ID}"
else
  echo "WIF provider already exists: ${PROVIDER_ID} (left unchanged)"
fi

echo "==> Ensuring deploy service account exists"
if ! gcloud iam service-accounts describe "${SERVICE_ACCOUNT_EMAIL}" --project "${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud iam service-accounts create "${SERVICE_ACCOUNT_ID}" \
    --display-name "Work Boots GitHub Deployer" \
    --description "Deploys Work Boots from GitHub Actions via WIF" \
    --project "${PROJECT_ID}" >/dev/null
  echo "Created service account: ${SERVICE_ACCOUNT_EMAIL}"
else
  echo "Service account already exists: ${SERVICE_ACCOUNT_EMAIL}"
fi

echo "==> Granting project IAM roles to deploy service account"
for role in \
  roles/serviceusage.serviceUsageConsumer \
  roles/cloudbuild.builds.editor \
  roles/artifactregistry.writer \
  roles/container.developer; do
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member "serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
    --role "${role}" \
    --quiet >/dev/null
  echo "Granted ${role}"
done

echo "==> Granting GCS source staging bucket access"
gcloud storage buckets add-iam-policy-binding "${SOURCE_BUCKET_URI}" \
  --member "serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
  --role "roles/storage.objectAdmin" \
  --project "${PROJECT_ID}" >/dev/null
echo "Granted roles/storage.objectAdmin to ${SERVICE_ACCOUNT_EMAIL} on ${SOURCE_BUCKET_URI}"

gcloud storage buckets add-iam-policy-binding "${SOURCE_BUCKET_URI}" \
  --member "serviceAccount:${CLOUDBUILD_SERVICE_ACCOUNT}" \
  --role "roles/storage.objectViewer" \
  --project "${PROJECT_ID}" >/dev/null
echo "Granted roles/storage.objectViewer to ${CLOUDBUILD_SERVICE_ACCOUNT} on ${SOURCE_BUCKET_URI}"

echo "==> Granting repository-level Artifact Registry write to Cloud Build service account"
gcloud artifacts repositories add-iam-policy-binding "${GAR_REPOSITORY}" \
  --location "${GAR_LOCATION}" \
  --member "serviceAccount:${CLOUDBUILD_SERVICE_ACCOUNT}" \
  --role "roles/artifactregistry.writer" \
  --project "${PROJECT_ID}" \
  --quiet >/dev/null
echo "Granted roles/artifactregistry.writer to ${CLOUDBUILD_SERVICE_ACCOUNT} on ${GAR_REPOSITORY}"

echo "==> Binding GitHub repo principal set to deploy service account (roles/iam.workloadIdentityUser)"
gcloud iam service-accounts add-iam-policy-binding "${SERVICE_ACCOUNT_EMAIL}" \
  --role "roles/iam.workloadIdentityUser" \
  --member "${REPO_PRINCIPAL_SET}" \
  --project "${PROJECT_ID}" \
  --quiet >/dev/null

echo
echo "Bootstrap complete."
echo
echo "Add/update these GitHub repository secrets:"
echo "  GCP_WORKLOAD_IDENTITY_PROVIDER=${WIF_PROVIDER_RESOURCE}"
echo "  GCP_SERVICE_ACCOUNT_EMAIL=${SERVICE_ACCOUNT_EMAIL}"
echo "  GAR_LOCATION=${GAR_LOCATION}"
echo "  GAR_REPOSITORY=${GAR_REPOSITORY}"
echo "  BUILD_SOURCE_BUCKET=${BUILD_SOURCE_BUCKET}"
if trimmed_nonempty "${GKE_CLUSTER}"; then
  echo "  GKE_CLUSTER=${GKE_CLUSTER}"
fi
if trimmed_nonempty "${GKE_LOCATION}"; then
  echo "  GKE_LOCATION=${GKE_LOCATION}"
fi

echo
echo "Post-bootstrap validation commands:"
echo "  gcloud iam workload-identity-pools providers describe ${PROVIDER_ID} --workload-identity-pool ${POOL_ID} --location global --project ${PROJECT_ID}"
echo "  gcloud iam service-accounts get-iam-policy ${SERVICE_ACCOUNT_EMAIL} --project ${PROJECT_ID}"
echo "  gcloud artifacts repositories describe ${GAR_REPOSITORY} --location ${GAR_LOCATION} --project ${PROJECT_ID}"
echo "  gcloud storage buckets describe ${SOURCE_BUCKET_URI} --project ${PROJECT_ID}"
echo
echo "Manual steps not automated by this script:"
echo "  - Ensure GKE cluster exists and set GKE_CLUSTER/GKE_LOCATION GitHub secrets."
echo "  - Ensure Kubernetes RBAC in cluster permits this service account identity to apply manifests and update deployments."
