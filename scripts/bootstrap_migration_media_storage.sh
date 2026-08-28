#!/usr/bin/env bash

set -euo pipefail

usage() {
  cat <<'EOF'
Ensure the private, versioned GCS bucket used for migration source media.

Usage:
  scripts/bootstrap_migration_media_storage.sh --gcp-project-id <id> [options]

Options:
  --bucket <name>                   Defaults to <project>-migration-media-<project-number>
  --location <region>              Defaults to us-central1
  --runtime-service-account <email> Defaults to mbsrn-api@<project>.iam.gserviceaccount.com
  --help
EOF
}

GCP_PROJECT_ID="${GCP_PROJECT_ID:-}"
MIGRATION_MEDIA_BUCKET="${MIGRATION_MEDIA_BUCKET:-}"
MIGRATION_MEDIA_LOCATION="${MIGRATION_MEDIA_LOCATION:-us-central1}"
RUNTIME_SERVICE_ACCOUNT="${RUNTIME_SERVICE_ACCOUNT:-}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --gcp-project-id)
      GCP_PROJECT_ID="$2"
      shift 2
      ;;
    --bucket)
      MIGRATION_MEDIA_BUCKET="$2"
      shift 2
      ;;
    --location)
      MIGRATION_MEDIA_LOCATION="$2"
      shift 2
      ;;
    --runtime-service-account)
      RUNTIME_SERVICE_ACCOUNT="$2"
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

PROJECT_NUMBER="$(gcloud projects describe "${GCP_PROJECT_ID}" --format='value(projectNumber)')"
if [[ -z "${PROJECT_NUMBER//[[:space:]]/}" ]]; then
  echo "ERROR: unable to resolve project number for ${GCP_PROJECT_ID}." >&2
  exit 1
fi
if [[ -z "${MIGRATION_MEDIA_BUCKET//[[:space:]]/}" ]]; then
  MIGRATION_MEDIA_BUCKET="${GCP_PROJECT_ID}-migration-media-${PROJECT_NUMBER}"
fi
if [[ -z "${RUNTIME_SERVICE_ACCOUNT//[[:space:]]/}" ]]; then
  RUNTIME_SERVICE_ACCOUNT="mbsrn-api@${GCP_PROJECT_ID}.iam.gserviceaccount.com"
fi

BUCKET_URI="gs://${MIGRATION_MEDIA_BUCKET}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
LIFECYCLE_FILE="${REPOSITORY_ROOT}/infra/gcp/migration-media-lifecycle.json"

if [[ ! -f "${LIFECYCLE_FILE}" ]]; then
  echo "ERROR: lifecycle policy is missing: ${LIFECYCLE_FILE}" >&2
  exit 1
fi
if ! gcloud iam service-accounts describe "${RUNTIME_SERVICE_ACCOUNT}" \
  --project "${GCP_PROJECT_ID}" >/dev/null 2>&1; then
  echo "ERROR: runtime service account does not exist: ${RUNTIME_SERVICE_ACCOUNT}" >&2
  exit 1
fi

gcloud services enable storage.googleapis.com --project "${GCP_PROJECT_ID}" >/dev/null

if gcloud storage buckets describe "${BUCKET_URI}" --project "${GCP_PROJECT_ID}" >/dev/null 2>&1; then
  EXISTING_PROJECT_NUMBER="$(
    gcloud storage buckets describe "${BUCKET_URI}" \
      --project "${GCP_PROJECT_ID}" \
      --format='value(projectNumber)'
  )"
  if [[ "${EXISTING_PROJECT_NUMBER}" != "${PROJECT_NUMBER}" ]]; then
    echo "ERROR: existing bucket is not owned by project ${GCP_PROJECT_ID}: ${BUCKET_URI}" >&2
    exit 1
  fi
  echo "Migration media bucket already exists: ${BUCKET_URI}"
else
  gcloud storage buckets create "${BUCKET_URI}" \
    --project "${GCP_PROJECT_ID}" \
    --location "${MIGRATION_MEDIA_LOCATION}" \
    --uniform-bucket-level-access \
    --public-access-prevention >/dev/null
  echo "Created migration media bucket: ${BUCKET_URI}"
fi

gcloud storage buckets update "${BUCKET_URI}" \
  --project "${GCP_PROJECT_ID}" \
  --uniform-bucket-level-access \
  --public-access-prevention \
  --versioning \
  --lifecycle-file "${LIFECYCLE_FILE}" >/dev/null

for role in roles/storage.objectCreator roles/storage.objectViewer; do
  gcloud storage buckets add-iam-policy-binding "${BUCKET_URI}" \
    --project "${GCP_PROJECT_ID}" \
    --member "serviceAccount:${RUNTIME_SERVICE_ACCOUNT}" \
    --role "${role}" >/dev/null
done

echo "Migration media storage is ready."
echo "MIGRATION_MEDIA_STORAGE_BACKEND=gcs"
echo "MIGRATION_MEDIA_GCS_BUCKET=${MIGRATION_MEDIA_BUCKET}"
