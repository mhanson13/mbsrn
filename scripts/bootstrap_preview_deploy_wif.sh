#!/usr/bin/env bash

set -euo pipefail

usage() {
  cat <<'EOF'
Create or update the GitHub Actions Workload Identity Federation path used by
the reusable MBSRN preview deployment workflow.

Usage:
  scripts/bootstrap_preview_deploy_wif.sh --gcp-project-id <id> --github-owner <owner> [options]

Options:
  --workflow-repository <name>   Defaults to mbsrn
  --workflow-ref <git-ref>       Defaults to refs/heads/main
  --pool-id <id>                 Defaults to mbsrn-preview-deploy
  --provider-id <id>             Defaults to github
  --service-account <email>      Defaults to mbsrn-preview-deployer@<project>.iam.gserviceaccount.com
  --help

The provider accepts repositories owned by --github-owner only when the OIDC
job was defined by that owner's exact reusable workflow and ref. The script
prints the three non-secret application settings required to opt in.
EOF
}

GCP_PROJECT_ID=""
GITHUB_OWNER=""
WORKFLOW_REPOSITORY="mbsrn"
WORKFLOW_REF="refs/heads/main"
POOL_ID="mbsrn-preview-deploy"
PROVIDER_ID="github"
DEPLOY_SERVICE_ACCOUNT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --gcp-project-id)
      GCP_PROJECT_ID="$2"
      shift 2
      ;;
    --github-owner)
      GITHUB_OWNER="$2"
      shift 2
      ;;
    --workflow-repository)
      WORKFLOW_REPOSITORY="$2"
      shift 2
      ;;
    --workflow-ref)
      WORKFLOW_REF="$2"
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
    --service-account)
      DEPLOY_SERVICE_ACCOUNT="$2"
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

if [[ -z "$GCP_PROJECT_ID" || -z "$GITHUB_OWNER" ]]; then
  echo "ERROR: --gcp-project-id and --github-owner are required." >&2
  usage >&2
  exit 1
fi
if ! command -v gcloud >/dev/null 2>&1; then
  echo "ERROR: gcloud is required." >&2
  exit 1
fi
if [[ -z "$DEPLOY_SERVICE_ACCOUNT" ]]; then
  DEPLOY_SERVICE_ACCOUNT="mbsrn-preview-deployer@${GCP_PROJECT_ID}.iam.gserviceaccount.com"
fi

gcloud services enable \
  iam.googleapis.com \
  iamcredentials.googleapis.com \
  sts.googleapis.com \
  container.googleapis.com \
  compute.googleapis.com \
  --project "$GCP_PROJECT_ID" >/dev/null

PROJECT_NUMBER="$(gcloud projects describe "$GCP_PROJECT_ID" --format='value(projectNumber)')"
if [[ -z "$PROJECT_NUMBER" ]]; then
  echo "ERROR: could not resolve project number for ${GCP_PROJECT_ID}." >&2
  exit 1
fi

if ! gcloud iam service-accounts describe "$DEPLOY_SERVICE_ACCOUNT" \
  --project "$GCP_PROJECT_ID" >/dev/null 2>&1; then
  service_account_id="${DEPLOY_SERVICE_ACCOUNT%%@*}"
  gcloud iam service-accounts create "$service_account_id" \
    --project "$GCP_PROJECT_ID" \
    --display-name "MBSRN preview deployment" >/dev/null
  echo "Created service account: ${DEPLOY_SERVICE_ACCOUNT}"
fi

for role in roles/container.developer roles/compute.viewer; do
  gcloud projects add-iam-policy-binding "$GCP_PROJECT_ID" \
    --member "serviceAccount:${DEPLOY_SERVICE_ACCOUNT}" \
    --role "$role" \
    --condition=None \
    --quiet >/dev/null
done

if ! gcloud iam workload-identity-pools describe "$POOL_ID" \
  --project "$GCP_PROJECT_ID" \
  --location global >/dev/null 2>&1; then
  gcloud iam workload-identity-pools create "$POOL_ID" \
    --project "$GCP_PROJECT_ID" \
    --location global \
    --display-name "MBSRN preview deployment" >/dev/null
  echo "Created workload identity pool: ${POOL_ID}"
fi

ATTRIBUTE_MAPPING="google.subject=assertion.sub,attribute.repository_owner=assertion.repository_owner,attribute.repository=assertion.repository,attribute.job_workflow_ref=assertion.job_workflow_ref"
EXPECTED_JOB_WORKFLOW_REF="${GITHUB_OWNER}/${WORKFLOW_REPOSITORY}/.github/workflows/deploy-site-preview.yml@${WORKFLOW_REF}"
ATTRIBUTE_CONDITION="assertion.repository_owner == '${GITHUB_OWNER}' && assertion.job_workflow_ref == '${EXPECTED_JOB_WORKFLOW_REF}'"

if gcloud iam workload-identity-pools providers describe "$PROVIDER_ID" \
  --project "$GCP_PROJECT_ID" \
  --location global \
  --workload-identity-pool "$POOL_ID" >/dev/null 2>&1; then
  gcloud iam workload-identity-pools providers update-oidc "$PROVIDER_ID" \
    --project "$GCP_PROJECT_ID" \
    --location global \
    --workload-identity-pool "$POOL_ID" \
    --issuer-uri "https://token.actions.githubusercontent.com/" \
    --attribute-mapping "$ATTRIBUTE_MAPPING" \
    --attribute-condition "$ATTRIBUTE_CONDITION" >/dev/null
  echo "Updated workload identity provider: ${PROVIDER_ID}"
else
  gcloud iam workload-identity-pools providers create-oidc "$PROVIDER_ID" \
    --project "$GCP_PROJECT_ID" \
    --location global \
    --workload-identity-pool "$POOL_ID" \
    --display-name "GitHub reusable preview deployment" \
    --issuer-uri "https://token.actions.githubusercontent.com/" \
    --attribute-mapping "$ATTRIBUTE_MAPPING" \
    --attribute-condition "$ATTRIBUTE_CONDITION" >/dev/null
  echo "Created workload identity provider: ${PROVIDER_ID}"
fi

WIF_MEMBER="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_ID}/attribute.repository_owner/${GITHUB_OWNER}"
gcloud iam service-accounts add-iam-policy-binding "$DEPLOY_SERVICE_ACCOUNT" \
  --project "$GCP_PROJECT_ID" \
  --member "$WIF_MEMBER" \
  --role roles/iam.workloadIdentityUser \
  --condition=None \
  --quiet >/dev/null

echo
echo "Set these GitHub repository variables only after deploy-site-preview.yml is available at the trusted ref:"
echo "MIGRATION_REUSABLE_DEPLOY_WORKFLOW_REF=${GITHUB_OWNER}/${WORKFLOW_REPOSITORY}/.github/workflows/deploy-site-preview.yml@${WORKFLOW_REF#refs/heads/}"
echo "MIGRATION_DEPLOY_WORKLOAD_IDENTITY_PROVIDER=projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_ID}/providers/${PROVIDER_ID}"
echo "MIGRATION_DEPLOY_SERVICE_ACCOUNT=${DEPLOY_SERVICE_ACCOUNT}"
