#!/usr/bin/env bash

set -euo pipefail

usage() {
  cat <<'EOF'
Bootstrap Google Cloud for Work Boots GitHub Actions deploys (WIF + GAR + IAM).

Usage:
  scripts/bootstrap_gcp_github_actions.sh --gcp-project-id <GCP_PROJECT_ID> --container-registry-region <REGION> --container-registry-repository <NAME> [options]

Options:
  --gcp-project-id <id>            GCP project ID (required; no default)
  --repo <owner/name>          GitHub repo allowed to impersonate via WIF (default: mhanson13/work-boots)
  --pool-id <id>               Workload Identity Pool ID (default: github-pool)
  --provider-id <id>           Workload Identity Provider ID (default: github-provider)
  --service-account-id <id>    Deployer service account ID (default: work-boots-github-deployer)
  --container-registry-region <region>      Artifact Registry region (required)
  --container-registry-repository <name>      Artifact Registry repository name (required)
  --build-source-dir <gs://...>  Cloud Build source staging dir (default: gs://<GCP_PROJECT_ID>-build-source/source)
  --kubernetes-cluster-name <name>         Optional: cluster name for create/reuse
  --kubernetes-cluster-location <location> Optional: cluster location (region or zone) for create/reuse
  --kubernetes-cluster-location-type <type> Optional: cluster location type (region|zone, default: region)
  --kubernetes-cluster-mode <mode>          Optional: cluster provisioning mode (autopilot|standard, default: autopilot)
  --help                       Show help

Environment variables are also supported:
  GCP_PROJECT_ID, REPO, POOL_ID, PROVIDER_ID, SERVICE_ACCOUNT_ID,
  CONTAINER_REGISTRY_REGION, CONTAINER_REGISTRY_REPOSITORY, BUILD_SOURCE_DIR,
  KUBERNETES_CLUSTER_NAME, KUBERNETES_CLUSTER_LOCATION, KUBERNETES_CLUSTER_LOCATION_TYPE, KUBERNETES_CLUSTER_MODE

Deprecated aliases (still accepted for transition):
  PROJECT_ID, GAR_LOCATION, GAR_REPOSITORY, BUILD_SOURCE_BUCKET, GKE_CLUSTER, GKE_LOCATION, KUBERNETES_CLUSTER_REGION

Example:
  GCP_PROJECT_ID=work-boots CONTAINER_REGISTRY_REGION=us-central1 CONTAINER_REGISTRY_REPOSITORY=work-boots \
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

GCP_PROJECT_ID="${GCP_PROJECT_ID:-${PROJECT_ID:-}}"
REPO="${REPO:-mhanson13/work-boots}"
POOL_ID="${POOL_ID:-github-pool}"
PROVIDER_ID="${PROVIDER_ID:-github-provider}"
SERVICE_ACCOUNT_ID="${SERVICE_ACCOUNT_ID:-work-boots-github-deployer}"
CONTAINER_REGISTRY_REGION="${CONTAINER_REGISTRY_REGION:-${GAR_LOCATION:-}}"
CONTAINER_REGISTRY_REPOSITORY="${CONTAINER_REGISTRY_REPOSITORY:-${GAR_REPOSITORY:-}}"
BUILD_SOURCE_DIR="${BUILD_SOURCE_DIR:-${BUILD_SOURCE_BUCKET:-}}"
KUBERNETES_CLUSTER_NAME="${KUBERNETES_CLUSTER_NAME:-${GKE_CLUSTER:-}}"
KUBERNETES_CLUSTER_LOCATION="${KUBERNETES_CLUSTER_LOCATION:-${KUBERNETES_CLUSTER_REGION:-${GKE_LOCATION:-}}}"
KUBERNETES_CLUSTER_LOCATION_TYPE="${KUBERNETES_CLUSTER_LOCATION_TYPE:-region}"
KUBERNETES_CLUSTER_MODE="${KUBERNETES_CLUSTER_MODE:-autopilot}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-id)
      GCP_PROJECT_ID="$2"
      shift 2
      ;;
    --gcp-project-id)
      GCP_PROJECT_ID="$2"
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
      CONTAINER_REGISTRY_REGION="$2"
      shift 2
      ;;
    --container-registry-region)
      CONTAINER_REGISTRY_REGION="$2"
      shift 2
      ;;
    --gar-repository)
      CONTAINER_REGISTRY_REPOSITORY="$2"
      shift 2
      ;;
    --container-registry-repository)
      CONTAINER_REGISTRY_REPOSITORY="$2"
      shift 2
      ;;
    --build-source-bucket)
      BUILD_SOURCE_DIR="$2"
      shift 2
      ;;
    --build-source-dir)
      BUILD_SOURCE_DIR="$2"
      shift 2
      ;;
    --gke-cluster)
      KUBERNETES_CLUSTER_NAME="$2"
      shift 2
      ;;
    --kubernetes-cluster-name)
      KUBERNETES_CLUSTER_NAME="$2"
      shift 2
      ;;
    --gke-location)
      KUBERNETES_CLUSTER_LOCATION="$2"
      KUBERNETES_CLUSTER_LOCATION_TYPE="region"
      shift 2
      ;;
    --kubernetes-cluster-region)
      KUBERNETES_CLUSTER_LOCATION="$2"
      KUBERNETES_CLUSTER_LOCATION_TYPE="region"
      shift 2
      ;;
    --kubernetes-cluster-location)
      KUBERNETES_CLUSTER_LOCATION="$2"
      shift 2
      ;;
    --kubernetes-cluster-location-type)
      KUBERNETES_CLUSTER_LOCATION_TYPE="$2"
      shift 2
      ;;
    --kubernetes-cluster-mode)
      KUBERNETES_CLUSTER_MODE="$2"
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

if ! trimmed_nonempty "${GCP_PROJECT_ID}"; then
  echo "ERROR: GCP_PROJECT_ID is required." >&2
  exit 1
fi
if ! trimmed_nonempty "${CONTAINER_REGISTRY_REGION}"; then
  echo "ERROR: CONTAINER_REGISTRY_REGION is required." >&2
  exit 1
fi
if ! trimmed_nonempty "${CONTAINER_REGISTRY_REPOSITORY}"; then
  echo "ERROR: CONTAINER_REGISTRY_REPOSITORY is required." >&2
  exit 1
fi
if [[ ! "${REPO}" =~ ^[^/]+/[^/]+$ ]]; then
  echo "ERROR: REPO must be in owner/name format. Got: ${REPO}" >&2
  exit 1
fi
if ! trimmed_nonempty "${BUILD_SOURCE_DIR}"; then
  BUILD_SOURCE_DIR="gs://${GCP_PROJECT_ID}-build-source/source"
fi
if [[ ! "${BUILD_SOURCE_DIR}" =~ ^gs://[^/]+(/.*)?$ ]]; then
  echo "ERROR: BUILD_SOURCE_DIR must be a gs:// URI. Got: ${BUILD_SOURCE_DIR}" >&2
  exit 1
fi
KUBERNETES_CLUSTER_MODE="$(echo "${KUBERNETES_CLUSTER_MODE}" | tr '[:upper:]' '[:lower:]')"
if [[ "${KUBERNETES_CLUSTER_MODE}" != "autopilot" && "${KUBERNETES_CLUSTER_MODE}" != "standard" ]]; then
  echo "ERROR: KUBERNETES_CLUSTER_MODE must be one of: autopilot, standard. Got: ${KUBERNETES_CLUSTER_MODE}" >&2
  exit 1
fi
KUBERNETES_CLUSTER_LOCATION_TYPE="$(echo "${KUBERNETES_CLUSTER_LOCATION_TYPE}" | tr '[:upper:]' '[:lower:]')"
if [[ "${KUBERNETES_CLUSTER_LOCATION_TYPE}" != "region" && "${KUBERNETES_CLUSTER_LOCATION_TYPE}" != "zone" ]]; then
  echo "ERROR: KUBERNETES_CLUSTER_LOCATION_TYPE must be one of: region, zone. Got: ${KUBERNETES_CLUSTER_LOCATION_TYPE}" >&2
  exit 1
fi
if trimmed_nonempty "${KUBERNETES_CLUSTER_NAME}" && ! trimmed_nonempty "${KUBERNETES_CLUSTER_LOCATION}"; then
  echo "ERROR: KUBERNETES_CLUSTER_LOCATION is required when KUBERNETES_CLUSTER_NAME is set." >&2
  exit 1
fi
if ! trimmed_nonempty "${KUBERNETES_CLUSTER_NAME}" && trimmed_nonempty "${KUBERNETES_CLUSTER_LOCATION}"; then
  echo "ERROR: KUBERNETES_CLUSTER_NAME is required when KUBERNETES_CLUSTER_LOCATION is set." >&2
  exit 1
fi
if [[ "${KUBERNETES_CLUSTER_MODE}" == "autopilot" && "${KUBERNETES_CLUSTER_LOCATION_TYPE}" != "region" ]]; then
  echo "ERROR: KUBERNETES_CLUSTER_MODE=autopilot requires KUBERNETES_CLUSTER_LOCATION_TYPE=region." >&2
  exit 1
fi

require_cmd gcloud

ACTIVE_ACCOUNT="$(gcloud auth list --filter=status:ACTIVE --format='value(account)' | head -n1 || true)"
if ! trimmed_nonempty "${ACTIVE_ACCOUNT}"; then
  echo "ERROR: no active gcloud account found. Run: gcloud auth login" >&2
  exit 1
fi

if ! gcloud projects describe "${GCP_PROJECT_ID}" --format='value(projectNumber)' >/dev/null 2>&1; then
  echo "ERROR: project not found or not accessible: ${GCP_PROJECT_ID}" >&2
  exit 1
fi

PROJECT_NUMBER="$(gcloud projects describe "${GCP_PROJECT_ID}" --format='value(projectNumber)')"
if ! trimmed_nonempty "${PROJECT_NUMBER}"; then
  echo "ERROR: unable to resolve project number for ${GCP_PROJECT_ID}" >&2
  exit 1
fi

SERVICE_ACCOUNT_EMAIL="${SERVICE_ACCOUNT_ID}@${GCP_PROJECT_ID}.iam.gserviceaccount.com"
WIF_PROVIDER_RESOURCE="projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_ID}/providers/${PROVIDER_ID}"
REPO_PRINCIPAL_SET="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_ID}/attribute.repository/${REPO}"
CLOUDBUILD_SERVICE_ACCOUNT="${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com"
SOURCE_BUCKET_NAME="${BUILD_SOURCE_DIR#gs://}"
SOURCE_BUCKET_NAME="${SOURCE_BUCKET_NAME%%/*}"
SOURCE_BUCKET_URI="gs://${SOURCE_BUCKET_NAME}"

echo "==> Bootstrap configuration"
echo "GCP_PROJECT_ID=${GCP_PROJECT_ID}"
echo "PROJECT_NUMBER=${PROJECT_NUMBER}"
echo "REPO=${REPO}"
echo "POOL_ID=${POOL_ID}"
echo "PROVIDER_ID=${PROVIDER_ID}"
echo "SERVICE_ACCOUNT_EMAIL=${SERVICE_ACCOUNT_EMAIL}"
echo "CONTAINER_REGISTRY_REGION=${CONTAINER_REGISTRY_REGION}"
echo "CONTAINER_REGISTRY_REPOSITORY=${CONTAINER_REGISTRY_REPOSITORY}"
echo "BUILD_SOURCE_DIR=${BUILD_SOURCE_DIR}"
if trimmed_nonempty "${KUBERNETES_CLUSTER_NAME}"; then
  echo "KUBERNETES_CLUSTER_NAME=${KUBERNETES_CLUSTER_NAME}"
fi
if trimmed_nonempty "${KUBERNETES_CLUSTER_LOCATION}"; then
  echo "KUBERNETES_CLUSTER_LOCATION=${KUBERNETES_CLUSTER_LOCATION}"
fi
echo "KUBERNETES_CLUSTER_LOCATION_TYPE=${KUBERNETES_CLUSTER_LOCATION_TYPE}"
echo "KUBERNETES_CLUSTER_MODE=${KUBERNETES_CLUSTER_MODE}"

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
  --project "${GCP_PROJECT_ID}" >/dev/null

if trimmed_nonempty "${KUBERNETES_CLUSTER_NAME}" && trimmed_nonempty "${KUBERNETES_CLUSTER_LOCATION}"; then
  echo "==> Ensuring Kubernetes cluster exists"
  CLUSTER_EXISTS=false
  if [[ "${KUBERNETES_CLUSTER_LOCATION_TYPE}" == "zone" ]]; then
    if gcloud container clusters describe "${KUBERNETES_CLUSTER_NAME}" \
      --zone "${KUBERNETES_CLUSTER_LOCATION}" \
      --project "${GCP_PROJECT_ID}" >/dev/null 2>&1; then
      CLUSTER_EXISTS=true
    fi
  else
    if gcloud container clusters describe "${KUBERNETES_CLUSTER_NAME}" \
      --region "${KUBERNETES_CLUSTER_LOCATION}" \
      --project "${GCP_PROJECT_ID}" >/dev/null 2>&1; then
      CLUSTER_EXISTS=true
    fi
  fi

  if [[ "${CLUSTER_EXISTS}" == "true" ]]; then
    echo "Kubernetes cluster already exists: ${KUBERNETES_CLUSTER_NAME}"
  else
    if [[ "${KUBERNETES_CLUSTER_MODE}" == "autopilot" ]]; then
      gcloud container clusters create-auto "${KUBERNETES_CLUSTER_NAME}" \
        --region "${KUBERNETES_CLUSTER_LOCATION}" \
        --project "${GCP_PROJECT_ID}" \
        --quiet >/dev/null
    else
      if [[ "${KUBERNETES_CLUSTER_LOCATION_TYPE}" == "zone" ]]; then
        gcloud container clusters create "${KUBERNETES_CLUSTER_NAME}" \
          --zone "${KUBERNETES_CLUSTER_LOCATION}" \
          --project "${GCP_PROJECT_ID}" \
          --quiet >/dev/null
      else
        gcloud container clusters create "${KUBERNETES_CLUSTER_NAME}" \
          --region "${KUBERNETES_CLUSTER_LOCATION}" \
          --project "${GCP_PROJECT_ID}" \
          --quiet >/dev/null
      fi
    fi
    echo "Created Kubernetes cluster: ${KUBERNETES_CLUSTER_NAME} (${KUBERNETES_CLUSTER_MODE}, ${KUBERNETES_CLUSTER_LOCATION_TYPE}:${KUBERNETES_CLUSTER_LOCATION})"
  fi
fi

echo "==> Ensuring Artifact Registry repository exists"
if ! gcloud artifacts repositories describe "${CONTAINER_REGISTRY_REPOSITORY}" \
  --location "${CONTAINER_REGISTRY_REGION}" \
  --project "${GCP_PROJECT_ID}" >/dev/null 2>&1; then
  gcloud artifacts repositories create "${CONTAINER_REGISTRY_REPOSITORY}" \
    --repository-format docker \
    --location "${CONTAINER_REGISTRY_REGION}" \
    --description "Work Boots API/UI container images" \
    --project "${GCP_PROJECT_ID}" >/dev/null
  echo "Created Artifact Registry repository: ${CONTAINER_REGISTRY_REPOSITORY}"
else
  echo "Artifact Registry repository already exists: ${CONTAINER_REGISTRY_REPOSITORY}"
fi

echo "==> Ensuring Cloud Build source staging bucket exists"
if ! gcloud storage buckets describe "${SOURCE_BUCKET_URI}" --project "${GCP_PROJECT_ID}" >/dev/null 2>&1; then
  gcloud storage buckets create "${SOURCE_BUCKET_URI}" \
    --location "${CONTAINER_REGISTRY_REGION}" \
    --uniform-bucket-level-access \
    --project "${GCP_PROJECT_ID}" >/dev/null
  echo "Created GCS bucket: ${SOURCE_BUCKET_URI}"
else
  echo "GCS bucket already exists: ${SOURCE_BUCKET_URI}"
fi

echo "==> Ensuring Workload Identity Pool exists"
if ! gcloud iam workload-identity-pools describe "${POOL_ID}" \
  --location "global" \
  --project "${GCP_PROJECT_ID}" >/dev/null 2>&1; then
  gcloud iam workload-identity-pools create "${POOL_ID}" \
    --location "global" \
    --display-name "GitHub Actions Pool" \
    --description "WIF trust boundary for GitHub Actions deploys" \
    --project "${GCP_PROJECT_ID}" >/dev/null
  echo "Created WIF pool: ${POOL_ID}"
else
  echo "WIF pool already exists: ${POOL_ID}"
fi

echo "==> Ensuring Workload Identity Provider exists"
if ! gcloud iam workload-identity-pools providers describe "${PROVIDER_ID}" \
  --workload-identity-pool "${POOL_ID}" \
  --location "global" \
  --project "${GCP_PROJECT_ID}" >/dev/null 2>&1; then
  gcloud iam workload-identity-pools providers create-oidc "${PROVIDER_ID}" \
    --workload-identity-pool "${POOL_ID}" \
    --location "global" \
    --issuer-uri "https://token.actions.githubusercontent.com" \
    --allowed-audiences "https://github.com/${REPO}" \
    --attribute-mapping "google.subject=assertion.sub,attribute.actor=assertion.actor,attribute.repository=assertion.repository,attribute.repository_owner=assertion.repository_owner,attribute.ref=assertion.ref" \
    --attribute-condition "assertion.repository=='${REPO}' && assertion.ref=='refs/heads/main'" \
    --display-name "GitHub OIDC Provider" \
    --project "${GCP_PROJECT_ID}" >/dev/null
  echo "Created WIF provider: ${PROVIDER_ID}"
else
  echo "WIF provider already exists: ${PROVIDER_ID} (left unchanged)"
fi

echo "==> Ensuring deploy service account exists"
if ! gcloud iam service-accounts describe "${SERVICE_ACCOUNT_EMAIL}" --project "${GCP_PROJECT_ID}" >/dev/null 2>&1; then
  gcloud iam service-accounts create "${SERVICE_ACCOUNT_ID}" \
    --display-name "Work Boots GitHub Deployer" \
    --description "Deploys Work Boots from GitHub Actions via WIF" \
    --project "${GCP_PROJECT_ID}" >/dev/null
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
  gcloud projects add-iam-policy-binding "${GCP_PROJECT_ID}" \
    --member "serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
    --role "${role}" \
    --quiet >/dev/null
  echo "Granted ${role}"
done

echo "==> Granting GCS source staging bucket access"
gcloud storage buckets add-iam-policy-binding "${SOURCE_BUCKET_URI}" \
  --member "serviceAccount:${SERVICE_ACCOUNT_EMAIL}" \
  --role "roles/storage.objectAdmin" \
  --project "${GCP_PROJECT_ID}" >/dev/null
echo "Granted roles/storage.objectAdmin to ${SERVICE_ACCOUNT_EMAIL} on ${SOURCE_BUCKET_URI}"

gcloud storage buckets add-iam-policy-binding "${SOURCE_BUCKET_URI}" \
  --member "serviceAccount:${CLOUDBUILD_SERVICE_ACCOUNT}" \
  --role "roles/storage.objectViewer" \
  --project "${GCP_PROJECT_ID}" >/dev/null
echo "Granted roles/storage.objectViewer to ${CLOUDBUILD_SERVICE_ACCOUNT} on ${SOURCE_BUCKET_URI}"

echo "==> Granting repository-level Artifact Registry write to Cloud Build service account"
gcloud artifacts repositories add-iam-policy-binding "${CONTAINER_REGISTRY_REPOSITORY}" \
  --location "${CONTAINER_REGISTRY_REGION}" \
  --member "serviceAccount:${CLOUDBUILD_SERVICE_ACCOUNT}" \
  --role "roles/artifactregistry.writer" \
  --project "${GCP_PROJECT_ID}" \
  --quiet >/dev/null
echo "Granted roles/artifactregistry.writer to ${CLOUDBUILD_SERVICE_ACCOUNT} on ${CONTAINER_REGISTRY_REPOSITORY}"

echo "==> Binding GitHub repo principal set to deploy service account (roles/iam.workloadIdentityUser)"
gcloud iam service-accounts add-iam-policy-binding "${SERVICE_ACCOUNT_EMAIL}" \
  --role "roles/iam.workloadIdentityUser" \
  --member "${REPO_PRINCIPAL_SET}" \
  --project "${GCP_PROJECT_ID}" \
  --quiet >/dev/null

echo
echo "Bootstrap complete."
echo
echo "Add/update these GitHub repository variables/secrets:"
echo "  GCP_PROJECT_ID=${GCP_PROJECT_ID}"
echo "  OIDC_WORKLOAD_IDENTITY_PROVIDER=${WIF_PROVIDER_RESOURCE}"
echo "  DEPLOY_SERVICE_ACCOUNT=${SERVICE_ACCOUNT_EMAIL}"
echo "  CONTAINER_REGISTRY_REGION=${CONTAINER_REGISTRY_REGION}"
echo "  CONTAINER_REGISTRY_REPOSITORY=${CONTAINER_REGISTRY_REPOSITORY}"
echo "  BUILD_SOURCE_DIR=${BUILD_SOURCE_DIR}"
if trimmed_nonempty "${KUBERNETES_CLUSTER_NAME}"; then
  echo "  KUBERNETES_CLUSTER_NAME=${KUBERNETES_CLUSTER_NAME}"
fi
if trimmed_nonempty "${KUBERNETES_CLUSTER_LOCATION}"; then
  echo "  KUBERNETES_CLUSTER_LOCATION=${KUBERNETES_CLUSTER_LOCATION}"
fi
echo "  KUBERNETES_CLUSTER_LOCATION_TYPE=${KUBERNETES_CLUSTER_LOCATION_TYPE}"

echo
echo "Post-bootstrap validation commands:"
echo "  gcloud iam workload-identity-pools providers describe ${PROVIDER_ID} --workload-identity-pool ${POOL_ID} --location global --project ${GCP_PROJECT_ID}"
echo "  gcloud iam service-accounts get-iam-policy ${SERVICE_ACCOUNT_EMAIL} --project ${GCP_PROJECT_ID}"
echo "  gcloud artifacts repositories describe ${CONTAINER_REGISTRY_REPOSITORY} --location ${CONTAINER_REGISTRY_REGION} --project ${GCP_PROJECT_ID}"
echo "  gcloud storage buckets describe ${SOURCE_BUCKET_URI} --project ${GCP_PROJECT_ID}"
if trimmed_nonempty "${KUBERNETES_CLUSTER_NAME}" && trimmed_nonempty "${KUBERNETES_CLUSTER_LOCATION}"; then
  if [[ "${KUBERNETES_CLUSTER_LOCATION_TYPE}" == "zone" ]]; then
    echo "  gcloud container clusters describe ${KUBERNETES_CLUSTER_NAME} --zone ${KUBERNETES_CLUSTER_LOCATION} --project ${GCP_PROJECT_ID}"
  else
    echo "  gcloud container clusters describe ${KUBERNETES_CLUSTER_NAME} --region ${KUBERNETES_CLUSTER_LOCATION} --project ${GCP_PROJECT_ID}"
  fi
fi
echo
echo "Manual steps not automated by this script:"
if ! trimmed_nonempty "${KUBERNETES_CLUSTER_NAME}" || ! trimmed_nonempty "${KUBERNETES_CLUSTER_LOCATION}"; then
  echo "  - Ensure GKE cluster exists and set KUBERNETES_CLUSTER_NAME/KUBERNETES_CLUSTER_LOCATION GitHub secrets."
fi
echo "  - Ensure Kubernetes RBAC in cluster permits this service account identity to apply manifests and update deployments."
