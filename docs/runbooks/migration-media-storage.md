# Migration media storage

Production migration media is stored in a private, versioned Google Cloud Storage bucket. API responses expose authenticated preview URLs but never expose the bucket, object key, generation, or checksum.

## Provision or reconcile

Run the idempotent platform bootstrap with an identity allowed to create/update buckets and bucket IAM:

```bash
scripts/bootstrap_migration_media_storage.sh --gcp-project-id mbsrn-prod --location us-central1
```

The default bucket name is `<project>-migration-media-<project-number>`. The script enforces uniform bucket-level access, public-access prevention, versioning, and the lifecycle policy in `infra/gcp/migration-media-lifecycle.json`. Active objects have no automatic deletion rule; noncurrent generations expire after 90 days.

The API runtime service account receives bucket-scoped object create and read access. It does not receive bucket administration or object deletion access.

Configure the API deployment with:

```text
MIGRATION_MEDIA_STORAGE_BACKEND=gcs
MIGRATION_MEDIA_GCS_BUCKET=<bucket-name>
MIGRATION_MEDIA_GCS_PROJECT_ID=<project-id>
```

Local development and tests default to `MIGRATION_MEDIA_STORAGE_BACKEND=local` and may override `MIGRATION_MEDIA_STORAGE_ROOT`.

## Verify

```bash
gcloud storage buckets describe gs://<bucket-name> --project <project-id>
gcloud storage buckets get-iam-policy gs://<bucket-name> --project <project-id>
```

Then import an image, generate a draft from a separate API request, and confirm the selected image is materialized under `assets/images/` in the generated artifact. A generation or SHA-256 mismatch must fail materialization with `media_storage_integrity_failed`.

## Recovery

Do not make the bucket public. If a generation is removed unexpectedly, re-import the source image and generate a new immutable draft. Do not alter an approved artifact to point at a different object generation.
