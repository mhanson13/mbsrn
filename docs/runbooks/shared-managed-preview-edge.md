# Shared managed preview edge

This runbook governs the staged migration of `*.site.mbsrn.com` previews to the shared edge defined in [ADR 0007](../architecture/decisions/0007-shared-managed-preview-edge.md). Resource identifiers and observed preflight state must be reviewed before production execution.

The versioned bootstrap now implements the platform ensure operation:

```bash
scripts/bootstrap_shared_preview_edge.sh \
  --gcp-project-id mbsrn-prod \
  --gke-cluster-name mbsrn-prod \
  --gke-cluster-location us-central1 \
  --dns-zone sites
```

It creates or verifies only shared platform resources and the Certificate Manager authorization CNAME. It does not create or change any site's preview-host A record. Review its reported resource names and states before enabling Gateway API routing in admin configuration.

## Safety rules

- Provision the shared edge alongside existing per-site endpoints.
- Do not change a site's DNS until the shared certificate, map, Gateway, route, and backend are ready.
- Use a separate Gateway-only Service during coexistence; GKE does not permit the same Service to be referenced by both Ingress and Gateway.
- Change only the selected site's exact-host DNS record during a canary cutover.
- Do not delete an old endpoint during cutover.
- Do not use `--insecure`, a local trust root, or fingerprint-only validation as success evidence.
- Revalidate MBSRN ownership and external references immediately before cleanup.

## Platform prerequisites

1. Confirm the cluster version supports Certificate Manager on GKE Gateway and the Gateway API is enabled.
2. Reserve a stable global address for the shared preview edge.
3. Create one Certificate Manager DNS authorization for `site.mbsrn.com` and publish its CNAME through the platform Cloud DNS integration.
4. Create one public Google-managed certificate covering `*.site.mbsrn.com`.
5. Create a certificate map and wildcard map entry, then wait for the certificate to become active.
6. Create a `gke-l7-global-external-managed` Gateway with `networking.gke.io/certmap`, one HTTPS listener on port 443, and no HTTP listener.
7. Restrict `allowedRoutes` to MBSRN-managed preview namespaces.
8. Configure monitoring for certificate state, Gateway/route readiness, backend health, request count, bytes, latency, and error rate.
9. Record shared fixed cost independently from per-site traffic and runtime usage.

The platform readiness check must be idempotent and read-only during a site release. Missing or unhealthy shared infrastructure is an administrator action, not a request for the operator to generate another certificate.

## Site attachment

For a site with preview hostname `<preview_slug>.site.mbsrn.com`:

1. Reconcile its namespace, MBSRN ownership labels, and Deployment.
2. Reconcile a `site-web-gateway` ClusterIP Service without Ingress NEG or BackendConfig annotations. It selects the same site pods as the legacy Service but is owned only by Gateway API.
3. Reconcile a Gateway `HealthCheckPolicy` targeting `site-web-gateway`.
4. Reconcile one exact-host `HTTPRoute` in that namespace.
5. Attach the route to the shared Gateway and reference only `site-web-gateway` in the same namespace.
6. Confirm the Gateway accepts the route and the backend reports healthy.
7. Reconcile the site's exact-host Cloud DNS A record to the shared global address.
8. Verify public DNS, normal TLS trust, SAN/hostname coverage, expected site identity/content, and lack of an HTTP listener.
9. Mark the certificate, DNS, deployment, and verification release gates ready from observed state.

A retry reads current state and changes only absent or drifted resources owned by the same site. It never creates another Gateway or certificate.

## Canary sequence

1. Deploy and verify the platform edge using a disposable, explicitly owned validation hostname.
2. Attach Platfire without changing `platfire.site.mbsrn.com` DNS.
3. When the Platfire route and backend are ready, change only its exact-host DNS record to the shared address.
4. Verify Platfire from public resolvers and a normal Firefox-compatible trust path.
5. Observe the agreed rollback window; restore the prior exact-host DNS value if routing, content, or TLS verification fails.
6. Repeat for Matty the Bookie and verify both hostnames route only to their own Services.
7. Attach a third unrelated site and confirm no certificate, certificate map, Gateway, global address, forwarding rule, or load balancer is created.
8. Make the shared edge the default only after all acceptance evidence is recorded.

## Cleanup

After a site's rollback window closes:

1. Reconfirm its DNS still targets the shared address and its shared route is healthy.
2. Enumerate the old Ingress, FrontendConfig, static address, forwarding rules, Compute certificate, and Secret Manager version from persisted ownership metadata.
3. Confirm no other site, target proxy, route, configuration, or DNS record references each candidate.
4. Produce a bounded cleanup plan for administrator review.
5. Delete only verified, site-owned legacy resources and record each result.

Shared Gateway, address, DNS authorization, certificate, certificate map, and map entry are platform resources and must never appear in a site cleanup plan.

## Operator diagnostics

The standard workspace shows only these outcomes:

- Certificate: shared preview certificate ready, pending, or administrator action required.
- DNS: exact hostname points to the shared preview endpoint, pending, or action required.
- Deployment: route attached and backend healthy, pending, or action required.
- Verification: public HTTPS serves the expected site, pending, or failed.

Administrator bundles may add sanitized provider resource names, conditions, reason codes, timestamps, and cost/traffic observations. They must exclude credentials, certificate private material, provider response bodies, and captured site content.
