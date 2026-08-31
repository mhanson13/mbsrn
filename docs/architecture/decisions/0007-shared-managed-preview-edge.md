# ADR 0007: Shared managed preview edge

Status: Accepted; platform provisioned, site migration pending
Date: 2026-08-31

## Decision

Preview sites under `<preview_slug>.site.mbsrn.com` use one shared, HTTPS-only GKE Gateway backed by a global external Application Load Balancer. A Certificate Manager certificate map attached through `networking.gke.io/certmap` contains a pre-provisioned, Google-managed `*.site.mbsrn.com` certificate. DNS authorization for `site.mbsrn.com` proves domain control before any site is deployed.

The Gateway has one port 443 listener and no port 80 listener. Each site owns one exact-host `HTTPRoute` and a Gateway-only Service in its Kubernetes namespace. The route attaches to the platform Gateway and targets only that Service in the same namespace. During migration, the Gateway-only Service and the legacy Ingress Service select the same pods but remain distinct because GKE does not allow a Service to be referenced by both GKE Ingress and Gateway. Route attachment is limited to namespaces carrying an MBSRN-managed preview label; application namespaces cannot change the Gateway or certificate map.

Platform infrastructure owns the global address, DNS authorization, certificate, certificate map, Gateway, attachment policy, and shared monitoring. Site provisioning owns preview identity, exact-host DNS, namespace/runtime, and exact-host route. Release work owns the immutable artifact, GitHub commit, site revision, and end-to-end verification.

The certificate release gate remains visible, but it becomes a read-only platform readiness check. It verifies wildcard coverage, active certificate state, certificate-map/Gateway attachment, and normal public TLS identity. It does not generate, import, vault, publish, or rotate certificate material per site.

Exact-host DNS records continue during the initial migration and point to the shared Gateway address. Wildcard DNS is not approved by this decision and requires a separate review of hostname ownership, unknown-host behavior, and takeover controls.

Customer production domains such as `www.platfire.com` are excluded. They require a separate exact-host certificate and production cutover workflow.

## Consequences

Certificate issuance and load-balancer creation leave the per-site critical path. Google holds and renews the private key, so preview key material is not stored by MBSRN. Fixed edge cost is shared; cost reporting must allocate fixed cost separately from attributable traffic and runtime consumption.

The platform must migrate from GKE Ingress to Gateway API. Site deployment and diagnostics must understand `Gateway`, `HTTPRoute`, Gateway-only Service, and `HealthCheckPolicy` readiness instead of per-site Ingress, FrontendConfig, forwarding-rule, static-IP, and certificate state. Cross-namespace route attachment and ownership checks become security boundaries and require contract tests.

The existing self-signed Compute `SELF_MANAGED` path remains available only for bounded rollback until each migrated hostname passes public HTTPS verification and its rollback window closes. It is then removed with ownership revalidation; private keys and certificate versions are never deleted merely because a new route was applied.

## Alternatives rejected

- Per-site self-signed certificates fail normal public-browser trust and keep private-key custody in MBSRN.
- Per-site Google-managed GKE `ManagedCertificate` resources still wait for per-site load-balancer authorization and do not support wildcard certificates.
- Per-site Let's Encrypt certificates improve browser trust but retain per-site issuance, renewal, Secret custody, and failure handling that the shared wildcard removes.
- One load balancer per preview preserves isolation through duplication but adds provisioning latency, fixed cost, quotas, and operational surface for every site.

## Acceptance and rollback

Platfire is the first canary, Matty the Bookie is the second-site isolation proof, and a third unrelated site proves generic onboarding without a new certificate or load balancer. A cutover is accepted only when DNS targets the shared address, the route is attached, the correct backend is healthy, the served certificate is publicly trusted and covers the exact hostname, HTTPS content is usable, and HTTP is not served.

Rollback restores the exact-host DNS record to the retained prior endpoint. The former Ingress, static address, certificate binding, Compute certificate, and Secret Manager version remain unchanged during the rollback window. Cleanup begins only after the window closes and a fresh ownership/dependency check confirms that another site or endpoint does not reference the resource.

References: [Certificate Manager DNS authorization](https://docs.cloud.google.com/certificate-manager/docs/domain-authorization), [GKE Gateway Certificate Manager integration](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/secure-gateway), and [GKE external Gateway deployment](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/deploying-gateways).
