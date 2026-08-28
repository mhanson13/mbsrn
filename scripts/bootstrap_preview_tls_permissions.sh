#!/usr/bin/env bash

set -euo pipefail

usage() {
  cat <<'EOF'
Ensure the narrow project role required by the MBSRN preview TLS service.

Usage:
  scripts/bootstrap_preview_tls_permissions.sh --gcp-project-id <id> [options]

Options:
  --runtime-service-account <email> Defaults to mbsrn-api@<project>.iam.gserviceaccount.com
  --role-id <id>                   Defaults to mbsrnPreviewTlsOperator
  --secret-prefix <prefix>         Defaults to mbsrn-tls; scopes certificate-secret read access
  --help
EOF
}

GCP_PROJECT_ID="${GCP_PROJECT_ID:-}"
RUNTIME_SERVICE_ACCOUNT="${RUNTIME_SERVICE_ACCOUNT:-}"
ROLE_ID="${ROLE_ID:-mbsrnPreviewTlsOperator}"
SECRET_PREFIX="${TLS_CERTIFICATE_SECRET_PREFIX:-mbsrn-tls}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --gcp-project-id)
      GCP_PROJECT_ID="$2"
      shift 2
      ;;
    --runtime-service-account)
      RUNTIME_SERVICE_ACCOUNT="$2"
      shift 2
      ;;
    --role-id)
      ROLE_ID="$2"
      shift 2
      ;;
    --secret-prefix)
      SECRET_PREFIX="$2"
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

if [[ -z "${GCP_PROJECT_ID//[[:space:]]/}" ]]; then
  echo "ERROR: --gcp-project-id is required." >&2
  exit 1
fi
if ! command -v gcloud >/dev/null 2>&1; then
  echo "ERROR: gcloud is required." >&2
  exit 1
fi
if [[ -z "${RUNTIME_SERVICE_ACCOUNT//[[:space:]]/}" ]]; then
  RUNTIME_SERVICE_ACCOUNT="mbsrn-api@${GCP_PROJECT_ID}.iam.gserviceaccount.com"
fi
if [[ ! "${SECRET_PREFIX}" =~ ^[A-Za-z0-9_-]{1,80}$ ]]; then
  echo "ERROR: --secret-prefix must contain 1-80 letters, numbers, underscores, or hyphens." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
ROLE_FILE="${REPOSITORY_ROOT}/infra/gcp/preview-tls-operator-role.yaml"
if [[ ! -f "${ROLE_FILE}" ]]; then
  echo "ERROR: role definition is missing: ${ROLE_FILE}" >&2
  exit 1
fi
if ! gcloud iam service-accounts describe "${RUNTIME_SERVICE_ACCOUNT}" \
  --project "${GCP_PROJECT_ID}" >/dev/null 2>&1; then
  echo "ERROR: runtime service account does not exist: ${RUNTIME_SERVICE_ACCOUNT}" >&2
  exit 1
fi

gcloud services enable compute.googleapis.com secretmanager.googleapis.com \
  --project "${GCP_PROJECT_ID}" >/dev/null

if gcloud iam roles describe "${ROLE_ID}" --project "${GCP_PROJECT_ID}" >/dev/null 2>&1; then
  gcloud iam roles update "${ROLE_ID}" \
    --project "${GCP_PROJECT_ID}" \
    --file "${ROLE_FILE}" >/dev/null
  echo "Updated custom role: projects/${GCP_PROJECT_ID}/roles/${ROLE_ID}"
else
  gcloud iam roles create "${ROLE_ID}" \
    --project "${GCP_PROJECT_ID}" \
    --file "${ROLE_FILE}" >/dev/null
  echo "Created custom role: projects/${GCP_PROJECT_ID}/roles/${ROLE_ID}"
fi

gcloud projects add-iam-policy-binding "${GCP_PROJECT_ID}" \
  --member "serviceAccount:${RUNTIME_SERVICE_ACCOUNT}" \
  --role "projects/${GCP_PROJECT_ID}/roles/${ROLE_ID}" \
  --condition=None \
  --quiet >/dev/null

GCP_PROJECT_NUMBER="$(gcloud projects describe "${GCP_PROJECT_ID}" --format='value(projectNumber)')"
if [[ -z "${GCP_PROJECT_NUMBER//[[:space:]]/}" ]]; then
  echo "ERROR: could not resolve project number for ${GCP_PROJECT_ID}." >&2
  exit 1
fi
TLS_SECRET_RESOURCE_PREFIX="projects/${GCP_PROJECT_NUMBER}/secrets/${SECRET_PREFIX}-"
TLS_SECRET_READ_CONDITION="expression=(resource.type == 'secretmanager.googleapis.com/Secret' || resource.type == 'secretmanager.googleapis.com/SecretVersion') && resource.name.startsWith('${TLS_SECRET_RESOURCE_PREFIX}'),title=mbsrnPreviewTLSSecretRead,description=Read only MBSRN preview TLS certificate secrets"

gcloud projects add-iam-policy-binding "${GCP_PROJECT_ID}" \
  --member "serviceAccount:${RUNTIME_SERVICE_ACCOUNT}" \
  --role "roles/secretmanager.secretAccessor" \
  --condition="${TLS_SECRET_READ_CONDITION}" \
  --quiet >/dev/null

echo "Preview TLS write/publish permissions are ready for ${RUNTIME_SERVICE_ACCOUNT}."
echo "Preview TLS secret read access is limited to ${TLS_SECRET_RESOURCE_PREFIX}*."
