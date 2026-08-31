# MBSRN Delivery Goals

Last updated: 2026-08-31

## Current objective

Deliver a generic, low-friction workflow that turns an authorized ingested site into an approved, media-complete, GitHub-published preview at `<preview_slug>.site.mbsrn.com`. Preview sites share an HTTPS-only Google Cloud Gateway/load balancer and a pre-provisioned Google-managed `*.site.mbsrn.com` certificate, so neither certificate issuance nor load-balancer creation is performed per site.

Platfire is the first acceptance exercise only. Success must prove the same configuration-driven path works for unrelated sites.

## Phase 0: Record decisions and establish guardrails

- [x] Document current failures and approved architecture in `CONTEXT.md`.
- [x] Create `GOALS.md` with phased acceptance criteria.
- [x] Add concise architecture decision records for preview identity, media storage, certificate custody, and reusable deployment execution.
- [x] Define compatibility windows for old APIs and generated workflows.

Acceptance:

- The repository contains one authoritative description of the target workflow and invariants.
- Implementation and review can identify whether a change violates site isolation, release immutability, or secret-handling rules.

## Phase 1: Make media durable

- [x] Add a storage interface independent of filesystem and GCS implementations.
- [x] Store production migration media in a private GCS bucket.
- [x] Record object generation and SHA-256 metadata.
- [x] Provision the bucket, public-access prevention, versioning, lifecycle, and bucket-scoped runtime IAM idempotently.
- [x] Keep local storage only for development and tests.
- [x] Surface per-asset integrity state with source re-import and identity-preserving upload replacement actions.
- [ ] Re-import Platfire media after the GCS path is active.
- [x] Publish referenced binary assets to GitHub with their pages.

Acceptance:

- An image ingested through one API pod can be previewed, materialized, and published through another pod.
- Platfire's approved release contains all referenced `assets/images/*` files in GitHub.
- Missing or changed source bytes produce one actionable gate failure.

## Phase 2: Establish canonical preview identity

- [x] Add operator-confirmed `preview_slug` to the site delivery configuration.
- [x] Validate uniqueness, DNS length, and reserved labels.
- [x] Lock the slug after the first infrastructure mutation.
- [x] Pass the resolved hostname explicitly to certificate, DNS, repository, workflow, and deployment integrations.
- [x] Backfill existing sites without silently creating infrastructure.
- [x] Expose existing-site preview identity confirmation in the migration workflow.
- [x] Block combined approval/release creation until the canonical preview identity is saved.
- [x] Validate the identity before approval so failed release prerequisites cannot partially approve a draft.

Acceptance:

- Source domain and repository name may differ without producing different preview hostnames.
- Resource names remain deterministic and collision-safe.
- No runtime path contains a Platfire-specific condition.

## Phase 3: Introduce preview releases and gates

- [x] Add immutable preview-release, operation, and gate records.
- [x] Implement `Approve & Create Preview` as an idempotent operation.
- [x] Run package, GitHub, certificate, DNS, deployment, and verification gates in dependency order.
- [x] Resume failed operations at the failed gate.
- [x] Return existing state for duplicate requests.
- [x] Stop deriving current status from unrelated latest-history records.
- [x] Reject incomplete media packages before approval and publish only frozen artifact contents.
- [x] Reconcile an already-published artifact's certificate manifest idempotently before advancing the release.
- [x] Reconcile generated deployment workflows before release dispatch and keep multiline credentials out of shell scripts.

Acceptance:

- One operator action can take an approved draft to a verified preview.
- Each external mutation is attempted only when absent, stale, invalid, or explicitly retried.
- A release always identifies its artifact, media manifest, Git commit, certificate, DNS expectation, deployment run, and verified URL.

## Phase 4: Replace per-site preview TLS with shared managed edge infrastructure

- [x] Validate the certificate project and workload credentials without unsupported provider permission probes.
- [x] Use real Secret Manager and Compute operations as authoritative permission checks with actionable, sanitized failures.
- [x] Make `ensure` reuse published certificates and resume vaulted certificates after partial Compute failure.
- [x] Accept Google Secret Manager's numeric canonical project references while keeping vault reads scoped to the configured certificate project.
- [x] Publish Compute certificates with the explicit `selfManaged` API contract and classify invalid requests as non-retryable platform errors.
- [x] Record the shared preview-edge design and rollback procedure in an ADR and operator runbook.
- [x] Add fail-closed shared-edge admin configuration, pure readiness evaluation, and HTTPS-only Gateway/site-route manifest renderers.
- [x] Add an idempotent platform bootstrap for the global address, DNS authorization CNAME, wildcard certificate, certificate map, Gateway API channel, and Gateway manifest.
- [x] Preserve the legacy Ingress during canary attachment by routing Gateway through a distinct Service selecting the same site pods.
- [ ] Enable and validate GKE Gateway API support without changing live preview traffic.
- [ ] Create one DNS authorization for `site.mbsrn.com` and one Google-managed `*.site.mbsrn.com` Certificate Manager certificate.
- [ ] Create an HTTPS-only shared Gateway/load balancer with a stable global IP and no public HTTP listener.
- [ ] Define the cross-namespace route-attachment policy so an MBSRN-managed site route can reach only its own namespace Service.
- [ ] Replace the per-site certificate mutation with an idempotent check that the shared certificate is active, attached, and covers the preview hostname.
- [ ] Migrate Platfire as a canary, then Matty the Bookie, while preserving the old endpoint for a bounded rollback window.
- [ ] Remove migrated sites' per-site Ingress, forwarding rules, certificates, and certificate Secret Manager versions only after HTTPS verification and ownership revalidation.
- [ ] Prove a third unrelated preview can attach without creating a certificate or load balancer.
- [ ] Define and document per-site cost allocation for shared fixed charges and attributable traffic/runtime usage.

Acceptance:

- A new preview does not generate, vault, publish, or rotate a private key.
- A new preview creates or reconciles only its route/runtime resources; it does not create a load balancer or certificate.
- Firefox and other public-trust browsers accept `platfire.site.mbsrn.com` without a warning or locally installed trust root.
- Platfire and Matty the Bookie resolve through the same shared Gateway while remaining isolated by hostname, namespace, Service, and site ownership metadata.
- The certificate gate reports shared platform readiness in concise terms and sends provider detail only to administrator diagnostics.
- The cost report separates shared preview-edge cost from traffic and runtime costs attributable to a site.

## Phase 5: Make GitHub publication atomic and deployment reusable

- [x] Publish complete releases through one Git tree/commit/ref update.
- [x] Verify all expected paths after publication.
- [ ] Replace per-site generated workflow bodies with a reusable workflow contract.
- [ ] Replace long-lived target-repository GCP keys with Workload Identity Federation.
- [ ] Restrict federation by trusted owner and reusable workflow identity.
- [x] Implement an opt-in reusable caller, centralized deployment workflow, and WIF bootstrap.
- [x] Reject partial reusable-deployment configuration and retain a reversible compatibility fallback.
- [ ] Keep repository adoption and ownership markers as one-time gates.

Acceptance:

- GitHub never receives a page commit without its required image files.
- Every site uses the same reviewed deployment implementation.
- Site repositories contain configuration/release content, not generated site-specific infrastructure code.

## Phase 6: Simplify the operator workspace

- [x] Present one primary action appropriate to the current state.
- [x] Show the eight high-level release gates with short next actions.
- [x] Move dry-run, replacement, raw provider, and Kubernetes controls out of the standard path.
- [x] Add administrator-only `Collect Debug Output`.
- [x] Ensure authenticated artifact/media previews work without unauthenticated image requests.
- [x] Render preview-release and diagnostic action results beside the initiating controls.
- [x] Keep diagnostic bundles collectable when TLS or preview-identity prerequisites are incomplete.
- [x] Include sanitized provider failure evidence and artifact-media blocker counts in administrator bundles.
- [x] Treat the visible **Continue: DNS & deployment** release gate as explicit authorization for that release, without changing the site's manual-deploy setting.
- [x] Prevent late requests from a previously viewed site from overwriting the active migration workspace.
- [x] Disable approval and preview creation when the selected latest draft package is known to be media-incomplete.
- [ ] Split the migration workspace into focused components.

Acceptance:

- An operator can identify the next required action without opening diagnostics.
- No normal workflow card displays raw Kubernetes/GitHub provider fields.
- An administrator can produce a sanitized diagnostic bundle using one action and support ID.

## Phase 7: Add optional faithful site capture

- [x] Add explicit `analyze_rebuild` and `faithful_snapshot` ingestion modes.
- [x] Require authorization acknowledgment for faithful snapshots.
- [x] Capture bounded first-party rendered pages and assets into immutable GCS source versions.
- [x] Report dynamic or unsupported features.
- [x] Generate AI-enhanced drafts from, but never over, the captured baseline.
- [x] Execute long-running captures asynchronously in an isolated worker.

Acceptance:

- Operators can choose the mode per site.
- The capture manifest provides source URL, final URL, digest, size, and provenance for every stored item.
- SSRF, redirect, content-size, page-count, and domain-boundary controls remain enforced.

Implementation is complete in code and tests. Production rollout and the Platfire end-to-end acceptance item below remain open.

## Phase 8: Remove bloat and legacy coupling

- [ ] Split migration orchestration, release state, media, GitHub, deployment, and diagnostics into focused modules.
- [ ] Remove production pod-local media behavior.
- [ ] Remove preview self-signed generation, import/adopt, Secret Manager vault, Compute `SELF_MANAGED`, and per-site certificate-selection code after migration.
- [ ] Remove per-site GKE Ingress, FrontendConfig, static-IP, and load-balancer provisioning after Gateway acceptance.
- [ ] Remove preview Kubernetes `ManagedCertificate` compatibility code.
- [ ] Remove per-site workflow renderers and resolver fallbacks.
- [ ] Remove site-specific UI placeholders and hard-coded account/image fallbacks.
- [ ] Replace chronological feature documentation with concise contracts and runbooks.
- [ ] Remove compatibility APIs after observed usage reaches zero.

Acceptance:

- Core modules have a single responsibility and bounded public interfaces.
- Deleted behavior has replacement tests and migration notes.
- No approved feature is removed solely to reduce line count.

## Required testing throughout

- Unit tests for domain transitions, identity resolution, storage adapters, certificate validation, and gate decisions.
- API tests for tenant isolation, authorization, idempotency, error contracts, and diagnostic redaction.
- Integration tests for GCS object generations, atomic Git publication, and external capability preflights.
- Contract tests for shared Gateway listeners, namespace/hostname route isolation, wildcard certificate coverage, and idempotent route reconciliation.
- Frontend tests for primary actions, gate states, artifact selection, and admin-only diagnostics.
- Multi-replica media test proving requests do not depend on pod affinity.
- Regression tests using multiple unrelated domains and repositories.
- Platfire end-to-end acceptance followed by at least one unrelated site dry run.

## Platfire acceptance checklist

- [ ] `preview_slug` is `platfire` and no Platfire-specific runtime path is used.
- [ ] Source ingestion completes in the selected mode.
- [ ] Selected images exist in GCS with digests and generations.
- [ ] A new draft materializes and previews those images.
- [ ] `Approve & Create Preview` creates one resumable release.
- [ ] GitHub `mhanson13/platfire` contains the complete release.
- [ ] The shared Certificate Manager certificate is active, attached to the preview Gateway, and covers `*.site.mbsrn.com`.
- [ ] Platfire has one owned HTTPRoute attached to the shared Gateway and targeting only its namespace Service.
- [ ] DNS resolves `platfire.site.mbsrn.com` to the shared preview endpoint.
- [ ] Endpoint verification observes a publicly trusted chain, the expected hostname, and a usable HTTPS response.
- [ ] No HTTP listener serves the preview endpoint.
- [ ] Platfire provisioning creates no per-site certificate, forwarding rule, or load balancer.
- [ ] All release gates report `ready`.
- [ ] Administrator diagnostic collection produces a sanitized bundle.

## Deferred goals

- Exact-host managed certificates and hosting cutover for customer production domains.
- Customer DNS cutover such as `www.platfire.com`.
- Migration of non-certificate GitHub secrets.
- General-purpose hosting of dynamic third-party application backends.
