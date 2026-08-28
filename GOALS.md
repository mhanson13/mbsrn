# MBSRN Delivery Goals

Last updated: 2026-08-28

## Current objective

Deliver a generic, low-friction workflow that turns an authorized ingested site into an approved, media-complete, GitHub-published, self-managed-TLS preview at `<preview_slug>.site.mbsrn.com`.

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

Acceptance:

- One operator action can take an approved draft to a verified preview.
- Each external mutation is attempted only when absent, stale, invalid, or explicitly retried.
- A release always identifies its artifact, media manifest, Git commit, certificate, DNS expectation, deployment run, and verified URL.

## Phase 4: Correct and consolidate preview TLS

- [x] Add startup/admin capability checks for required Secret Manager and Compute permissions.
- [x] Surface missing permissions before certificate generation.
- [ ] Implement idempotent generate, import, adopt, reuse, bind, rotate, and verify operations.
- [ ] Use only Compute self-managed certificates and the GKE pre-shared certificate annotation for preview hosts.
- [ ] Remove preview dependencies on Kubernetes `ManagedCertificate` resources after compatibility validation.
- [ ] Preserve old certificates and secret versions until replacements are verified.

Acceptance:

- A missing certificate is generated, vaulted, published, bound, and verified without exposing the key.
- An existing exact-host or wildcard self-managed certificate can be selected safely.
- Platfire serves the selected fingerprint at `platfire.site.mbsrn.com`.

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
- [ ] Split the migration workspace into focused components.

Acceptance:

- An operator can identify the next required action without opening diagnostics.
- No normal workflow card displays raw Kubernetes/GitHub provider fields.
- An administrator can produce a sanitized diagnostic bundle using one action and support ID.

## Phase 7: Add optional faithful site capture

- [ ] Add explicit `analyze_rebuild` and `faithful_snapshot` ingestion modes.
- [ ] Require authorization acknowledgment for faithful snapshots.
- [ ] Capture bounded first-party rendered pages and assets into immutable GCS source versions.
- [ ] Report dynamic or unsupported features.
- [ ] Generate AI-enhanced drafts from, but never over, the captured baseline.
- [ ] Execute long-running captures asynchronously.

Acceptance:

- Operators can choose the mode per site.
- The capture manifest provides source URL, final URL, digest, size, and provenance for every stored item.
- SSRF, redirect, content-size, page-count, and domain-boundary controls remain enforced.

## Phase 8: Remove bloat and legacy coupling

- [ ] Split migration orchestration, release state, media, GitHub, deployment, and diagnostics into focused modules.
- [ ] Remove production pod-local media behavior.
- [ ] Remove preview managed-certificate code.
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
- [ ] The certificate is vaulted and exists as a global Compute `SELF_MANAGED` resource.
- [ ] Ingress selects the expected pre-shared certificate.
- [ ] DNS resolves `platfire.site.mbsrn.com` to the expected endpoint.
- [ ] Endpoint verification observes the expected certificate fingerprint and usable HTTP response.
- [ ] All release gates report `ready`.
- [ ] Administrator diagnostic collection produces a sanitized bundle.

## Deferred goals

- Production-worthy managed certificates for customer domains.
- Customer DNS cutover such as `www.platfire.com`.
- Migration of non-certificate GitHub secrets.
- General-purpose hosting of dynamic third-party application backends.
