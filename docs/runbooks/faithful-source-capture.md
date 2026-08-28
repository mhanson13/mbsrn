# Faithful source capture

This runbook covers the optional browser-rendered baseline used before migration draft generation. Platfire is the first acceptance site, not a runtime special case.

## Deploy

1. Apply database migration `0064_faithful_source_captures` before the worker and API become available.
2. Confirm the production migration-media bucket is private, versioned, and configured through `MIGRATION_MEDIA_GCS_BUCKET`.
3. Confirm the `mbsrn-api` Kubernetes service account can create and read objects in that bucket through Workload Identity Federation for GKE.
4. Confirm the cluster supports the `gvisor` RuntimeClass. Autopilot requires GKE `1.27.4-gke.800` or later; Standard clusters require GKE Sandbox-enabled nodes.
5. Set the optional `CAPTURE_WORKER_IMAGE_NAME` GitHub repository variable when the default `mbsrn-source-capture-worker` is unsuitable.
6. Run the production deployment. It builds a version-matched Playwright worker image, applies the worker manifest, waits for rollout, and verifies image/SHA provenance.

The worker fails startup when Chromium or its sandbox cannot launch. Do not remove gVisor, change the worker to root, or disable Chromium's sandbox to make rollout pass.

## Operate

1. In the site's migration workspace, enter the public source URL.
2. Choose **Analyze and rebuild** for bounded source analysis, or **Faithful static snapshot** for browser-rendered pages and first-party assets.
3. For a faithful snapshot, confirm that the customer controls or has permission to reproduce the source.
4. Start capture. The UI shows `queued`, `running`, `completed`, or `failed` plus concise counts, limitations, and a safe failure reason.
5. Generate drafts only after the selected capture completes. A newer capture supersedes an older completion as workspace input.

Default faithful bounds are 10 pages, 200 assets, 50 MB total, 5 MB per resource, 20 seconds per navigation, and 180 seconds per run. API request limits cap pages at 25, assets at 300, and total bytes at 100 MB.

## Diagnose

Check rollout and sandbox assignment:

```bash
kubectl -n mbsrn rollout status deployment/mbsrn-source-capture-worker
kubectl -n mbsrn get pods -l app=mbsrn-source-capture-worker \
  -o jsonpath='{range .items[*]}{.metadata.name}{" runtime="}{.spec.runtimeClassName}{"\n"}{end}'
```

Read bounded worker logs:

```bash
kubectl -n mbsrn logs deployment/mbsrn-source-capture-worker --tail=200
```

Common outcomes:

- `browser_runtime_unavailable`: verify the worker image tag matches the Python Playwright package and that gVisor can start sandboxed Chromium.
- `unsafe_source_url` or `unsafe_redirect`: use a credential-free public HTTP(S) URL; private, loopback, link-local, and cross-site targets are rejected.
- `navigation_timeout`: verify the public source is reachable and, if justified, adjust the bounded navigation timeout.
- `capture_too_large`, `page_too_large`, or limit warnings: lower the requested scope or review the source manually; do not remove platform caps.
- `external_resources_blocked`: expected when the site depends on CDNs or third-party scripts. The baseline intentionally contains only exact-host/`www` resources.
- replacement-required feature codes: rebuild the dynamic behavior as an explicit MBSRN feature; do not treat the snapshot as a functioning backend.

Stale `running` rows are re-queued after 600 seconds and fail after three attempts. Each attempt has a distinct storage prefix, so an interrupted run cannot overwrite an earlier object generation.

## Roll back

Scale the worker to zero to stop starting new captures; queued rows remain durable. Rolling back the API must also hide the new UI control or retain schema compatibility. Do not delete capture objects or migration `0064` while a workspace references a capture. Revert a site's active input by completing or selecting a new authorized capture, not by editing a frozen manifest.
