# Production cost optimization

This runbook records reversible cost controls for the low-traffic `mbsrn-prod` environment. Cost changes must preserve platform capabilities and must not delete networking resources without ownership, reference, and live-health verification.

## Current profile

- GKE Autopilot application requests: 750m CPU, 1.69 GiB memory, and 3.14 GiB ephemeral storage with Platfire running.
- Shared preview edge: `34.95.117.146`, Certificate Manager wildcard certificate, and HTTPS-only GKE Gateway.
- Cloud SQL: `db-custom-1-3840`; keep this tier until measured CPU and memory headroom support a smaller replacement.
- Artifact Registry: repository `mbsrn` in `us-central1`.
- GKE monitoring: `SYSTEM_COMPONENTS`; Managed Service for Prometheus remains enabled because Autopilot requires it.

## Artifact Registry cleanup

The authoritative policy is [`infra/artifact-registry/cleanup-policy.json`](../../infra/artifact-registry/cleanup-policy.json). It targets versions older than 30 days and retains the newest 20 versions of every package.

Apply or refresh the non-destructive dry run:

```bash
gcloud artifacts repositories set-cleanup-policies mbsrn \
  --project mbsrn-prod \
  --location us-central1 \
  --policy infra/artifact-registry/cleanup-policy.json \
  --dry-run
```

Wait at least 24 hours and inspect Artifact Registry Data Access audit logs before using `--no-dry-run`. Confirm that every deployed image digest and the required rollback set are retained.

## Monitoring controls

Thirty-day billing metrics on 2026-10-17 showed 567.9 million Prometheus samples, dominated by generic container network, memory, CPU, filesystem, and kubelet metrics. No application `PodMonitoring` resource existed.

The supported Autopilot reduction is:

```bash
gcloud container clusters update mbsrn-prod \
  --project mbsrn-prod \
  --location us-central1 \
  --monitoring=SYSTEM
```

Do not attempt to disable Managed Service for Prometheus on this Autopilot version; GKE rejects that operation. Dataplane V2 metric exposure does not incur Prometheus ingestion by itself on Autopilot. It requires a matching `ClusterPodMonitoring`, which this cluster does not have.

Recheck `monitoring.googleapis.com/billing/samples_ingested` after configuration propagation and compare a full 24-hour period with the previous baseline.

## Preview endpoint cleanup

Before deleting a dedicated preview endpoint:

1. Verify the shared certificate is active and the Gateway is programmed.
2. Verify the site's HTTPRoute is accepted and its Gateway backend is healthy.
3. Compare content from the shared and dedicated IPs.
4. Change only the site's exact-host DNS record.
5. Verify multiple public resolvers and publicly trusted HTTPS.
6. Remove legacy manifests from the generated repository contract so deployment cannot recreate them.
7. Delete the live Ingress and wait until its forwarding rules are gone.
8. Delete the dedicated address only when it reports no users.
9. Delete the unreferenced Compute certificate while retaining vaulted material for the bounded recovery window.
10. Reverify public HTTPS and forwarding-rule count.

## Future state

Add an operator-controlled sleep/wake state for draft sites. Sleeping must scale only the draft Deployment to zero; it must retain namespace, route, hostname, release, and repository identity so an operator can wake the preview without reprovisioning certificates or load balancers.
