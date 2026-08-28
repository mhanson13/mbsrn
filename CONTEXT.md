# MBSRN Engineering Context

Last updated: 2026-08-28

## Purpose

MBSRN ingests an authorized existing website, combines the captured source with audit, SEO, competitor, recommendation, business, and operator context, generates versioned draft site artifacts, and publishes approved preview releases. Customer production-domain cutover is a separate future workflow.

Platfire (`platfire.com`) is the first acceptance site. It is not a runtime special case. All delivery behavior must be parameterized by business, site, release, preview identity, and repository configuration.

## Current architecture

- Backend: Python, FastAPI, SQLAlchemy, Alembic.
- Operator UI: Next.js/React.
- Primary runtime: GKE in `us-central1`.
- Database: PostgreSQL/Cloud SQL in production.
- Session state: Redis in production.
- Site source and generated artifact metadata: database records.
- GitHub: approved static artifacts and deployment workflow dispatch.
- Google Cloud: GKE, Cloud DNS, Compute SSL certificates, Secret Manager, Cloud Logging.

## Confirmed production problems

1. Migration media is written to pod-local `var/migration_media`, but production runs multiple API replicas. A later request can reach a different pod and lose access to otherwise valid image metadata. Platfire exhibited seven selected images and zero materialized images for this reason.
2. The original TLS readiness probe called an unsupported project-level Secret Manager `testIamPermissions` route. Its generic error handling mislabeled the resulting provider failure as an IAM problem even though production already had the required custom role and enabled APIs.
3. Certificate and deployment hostnames are derived through different paths. A source domain and repository name that do not normalize to the same label can select different preview identities.
4. The operator workflow exposes separate approval, publication, certificate, deployment, refresh, and raw diagnostic controls without a single release operation tying them together.
5. Diagnostic summaries mix selected artifact, latest artifact, and latest action history. This produces contradictory guidance.
6. The migration service, GitHub publisher, and operator workspace are oversized and contain overlapping managed- and self-managed-certificate behavior.
7. On 2026-08-28, preview release creation for an existing site returned `preview_slug_required` after the artifact had already been approved. Administrator diagnostic collection then failed with HTTP 500 because certificate status treated the same missing prerequisite as fatal. Both failures were shown only in the page-level message area, far from the controls that initiated them.

## Implementation status

As of 2026-08-28, the durable media storage boundary is implemented and tested. The production bucket `mbsrn-prod-migration-media-1068908288067` is private, uses uniform bucket-level access, has public-access prevention and versioning enabled, and expires noncurrent generations after 90 days. The runtime service account has bucket-scoped object create/read roles. Deployment wiring is pending the next application rollout; Platfire media must be re-imported after that rollout.

Canonical preview identity is implemented across the site model/API, TLS, GitHub workflow rendering, static IP, DNS, and deployment boundaries. `preview_slug` is globally unique, rejects reserved/invalid labels, remains nullable for safe existing-site backfill, and becomes immutable when preview infrastructure is first mutated. The explicit hostname remains authoritative even when source domain and repository names differ.

The dedicated migration route now exposes preview identity as an explicit release prerequisite for every site. A valid repository name can seed the editable suggestion, but only a saved site `preview_slug` satisfies the gate. **Approve & Create Preview** remains disabled until that value is persisted. The API validates identity before approval, so a failed prerequisite cannot partially approve the artifact. Preview and diagnostic action results render beside their initiating controls. Diagnostic collection records unavailable certificate status and its bounded reason code instead of failing when preview infrastructure prerequisites are incomplete.

Preview releases persist one artifact, frozen media manifest, canonical preview identity, Git commit, selected certificate identity, deployment run identifier, operation, and eight ordered gates. The combined approval/release endpoint is idempotent even when retried with a different request key; standalone approval retains its existing duplicate-rejection contract. `POST .../preview-releases/{release_id}/advance` performs exactly one external gate and can resume a failed gate without repeating successful gates. Reconciliation will not substitute a newly activated certificate into an existing release.

GitHub artifact publication creates all text and binary blobs, derives a tree, verifies every expected path/blob from GitHub, creates one commit, and then performs one non-forced branch-reference update. A failed blob/tree/verification/commit request cannot expose a partial package, and the result contains one exact commit SHA. Existing repository ownership-marker and baseline checks still run before the artifact transaction.

Reusable preview deployment is implemented behind an all-or-none platform configuration gate. The site-repository workflow becomes a small signed caller with bounded inputs; `.github/workflows/deploy-site-preview.yml` centrally owns build, GKE apply, and endpoint verification. The called job authenticates through GitHub OIDC and Google Workload Identity Federation and rejects legacy ManagedCertificate ingress annotations. The compatibility renderer remains inactive only after the workflow ref, WIF provider, and deployment service account are all configured and two-site acceptance is complete.

Preview TLS readiness checks now validate the configured project and workload credentials without calling unsupported or non-authoritative permission-test routes. The actual Secret Manager and Compute operations verify authorization and return sanitized, operation-specific failures. Production has a narrow `mbsrnPreviewTlsOperator` custom role bound to the API workload identity. On 2026-08-28, production also received Secret Accessor through a resource-name condition limited to `projects/1068908288067/secrets/mbsrn-tls-*`; the versioned bootstrap preserves that boundary. This lets `ensure` resume a vaulted certificate after partial Compute failure without granting access to unrelated secrets. Generate/import and `ensure` operations remain API-side so private keys do not transit GitHub.

The advanced workspace certificate action now calls `ensure` rather than unconditional `generate`. It reuses a valid published asset and can load and resume a matching vaulted asset instead of creating another certificate after a retryable Compute publication failure. Certificate diagnostics include stable safe reason codes and bounded failure messages; provider bodies and private material remain excluded.

The operator workspace now presents one preview-release card with the eight concise gates and a single context-appropriate action. Legacy manual publish, certificate, deploy, dry-run, and replacement controls are retained under a collapsed advanced disclosure during the compatibility window. Administrators can explicitly collect a seven-day sanitized diagnostic bundle; operators do not see that control, and bundles exclude credentials, private keys, raw provider bodies, media, and captured site content.

Artifact and migration-media previews now use authenticated API requests with the operator bearer token. The UI converts returned blobs to local data URLs before assigning image or sandboxed iframe content, so protected API URLs are never emitted as unauthenticated browser resource requests.

Workspace media reads now expose a bounded integrity state instead of sending operators to preview URLs that are known to fail. Missing source-site objects can be re-imported through the existing SSRF-protected import path. Missing operator-uploaded objects can be replaced while preserving the logical asset ID, selection, and descriptive metadata. Both operations create new storage generations and require a new draft; neither mutates an existing artifact.

Artifact media is now finalized only during draft generation. Approval rejects missing selected files or unresolved references with `draft_package_incomplete`, preview-release creation defensively rejects incomplete legacy approved packages, and GitHub publication consumes only the frozen artifact. The former publish-time artifact repair path has been removed.

The migration route remounts its workspace at the business/site boundary and every workspace refresh carries a generation-and-scope guard. Late summary, TLS, media, history, release, or capture responses from a previously viewed site are discarded. When the latest selected draft is known to have missing media or unresolved references, both standalone approval and **Approve & Create Preview** are disabled with one repair-and-regenerate instruction beside the action.

Optional asynchronous source capture is implemented for all sites. `analyze_rebuild` remains the default; `faithful_snapshot` requires recorded authorization and runs Chromium in a dedicated non-root, gVisor-isolated worker rather than API Pods. Capture rows are tenant/site scoped, idempotent, retryable, and immutable by source version. Every browser attempt writes first-party pages/assets and a last-written manifest under a unique GCS attempt prefix with size, SHA-256, generation, and provenance. Exact-host/`www` navigation, public DNS pinning, redirect checks, external-request blocking, and bounded time/page/asset/byte limits are enforced. Unsupported dynamic behavior is reported as a limitation. The latest successfully completed requested run becomes the workspace baseline and supplies only bounded rendered context to AI draft generation. Production rollout and Platfire acceptance remain pending.

## Approved target workflow

The normal operator path is:

1. Configure a site and confirm its preview identity.
2. Choose an ingestion mode.
3. Ingest the authorized source.
4. Select media and provide requirements.
5. Generate and iteratively improve immutable draft versions.
6. Review a selected draft.
7. Run **Approve & Create Preview**.
8. Observe a concise sequence of release gates.
9. Open the verified preview URL.

The release gates are:

1. `source`
2. `draft_package`
3. `approval`
4. `github`
5. `certificate`
6. `dns`
7. `deployment`
8. `verification`

Allowed operator-facing gate states are `waiting`, `running`, `ready`, `action_required`, and `failed`. Detailed provider evidence belongs in an administrator-collected diagnostic bundle, not the normal workflow.

## Core invariants

### Tenant and site isolation

- Every record and external-resource operation is scoped by `business_id` and `site_id`.
- Frontend async responses may update state only while their captured business/site scope and request generation remain current.
- Repository ownership markers must match the expected business and site before MBSRN modifies an existing repository.
- Storage object names use immutable IDs rather than display names.
- No site name, customer domain, repository, or workflow path may be hard-coded into runtime behavior.

### Preview identity

- Each site has an explicit `preview_slug`.
- The operator can edit the slug until the first preview infrastructure resource is created.
- The slug is locked after infrastructure creation. Renaming requires a separate migration workflow.
- The preview hostname is `<preview_slug>.site.mbsrn.com`.
- The GitHub repository defaults to the slug but remains separately configurable.
- Kubernetes and Compute resource names include the slug and a stable site-derived suffix where collision protection is required.
- Integrations receive explicit resolved identity values. They must not independently infer a different hostname.

### Artifacts and releases

- Draft artifact versions are immutable review units.
- A preview release references one exact artifact version and one exact media manifest.
- A release never silently substitutes the latest artifact or latest selected media.
- Release creation is idempotent. A repeated request returns or resumes the same operation.
- Failed gates are resumable without repeating successful one-time work.
- Expected duplicate requests are not logged as application errors.

### Media

- Production media source bytes live in a private Google Cloud Storage bucket.
- Local filesystem storage is permitted only for local development and isolated tests.
- Media records retain bucket, object name, object generation, content type, byte length, and SHA-256 digest.
- Generated and approved pages reference artifact-relative paths such as `assets/images/example.webp`.
- GitHub receives the referenced binary assets in the same release commit as HTML, CSS, JavaScript, and metadata.
- An artifact cannot pass the GitHub gate when referenced bytes are missing or checksums differ.
- Missing workspace bytes produce one explicit re-import or replacement action without exposing bucket or object metadata.
- Active media is retained while referenced. Superseded object versions are retained for 90 days unless legal or operational requirements override that policy.

### Preview TLS

- Self-signed, global Compute `SELF_MANAGED` certificates are used only for `*.site.mbsrn.com` previews.
- Customer production domains and Google-managed certificates are outside the preview release workflow.
- Private keys are never committed to GitHub, returned by APIs, or written to logs.
- Generated/imported private keys are vaulted in Secret Manager.
- Compute self-managed certificate publication uses the explicit `selfManaged` request object; provider request-validation failures are platform errors and are not operator-retryable.
- Secret Manager version references may contain Google's numeric canonical project number; reads normalize them to the configured certificate project and reject references to another named project.
- Existing Compute self-managed certificates can be adopted after type and hostname validation.
- Existing exact-host or wildcard certificates can be reused when they cover the resolved preview hostname.
- Ingress selects the resource through `ingress.gcp.kubernetes.io/pre-shared-cert`.
- Verification compares the exact served certificate fingerprint with the selected asset.
- Certificate ensure checks current state before creating or rotating resources.

### External execution and credentials

- The API coordinates desired state and uses narrowly scoped workload identities.
- Certificate material is generated/imported and vaulted without transiting GitHub.
- GitHub deployments use a reusable workflow and short-lived Google Workload Identity Federation credentials.
- New workflows must not depend on a long-lived `GCP_DEPLOY_KEY` JSON key.
- Workload Identity Federation conditions restrict the trusted GitHub owner and reusable workflow identity.
- External changes use supported GitHub and Google APIs; CLI usage inside a controlled workflow is an API client, not a source of site-specific behavior.

### Diagnostics and security

- Normal UI diagnostics show gate, status, short reason, next action, and operation/support ID.
- Administrators can explicitly collect a bounded site diagnostic bundle.
- Diagnostic bundles expire after seven days by default.
- Bundles may contain sanitized configuration provenance, external resource metadata, IAM capability results, bounded workflow/log evidence, and endpoint observations.
- Failed release gates retain a bounded provider service/operation/status summary, and bundles include artifact-media blocker reason counts without media content.
- Bundles must exclude tokens, credentials, private keys, secret payloads, raw media, and complete captured website contents.

## Ingestion modes

### Analyze and rebuild

The existing default mode captures bounded source signals and combines them with MBSRN analysis to generate a new site.

### Faithful static snapshot

This is an optional new feature. It requires an operator authorization acknowledgment and captures deployable first-party pages and assets into an immutable source version before AI changes. Dynamic server behavior such as authentication, commerce, protected APIs, and server-side form processing is reported as unsupported or replacement-required rather than silently copied.

Long-running ingestion is modeled as an asynchronous site operation.

The capture API queues durable database work. A separately deployed Chromium worker claims it atomically, retries interrupted work at most three times, and cannot let an older completion replace a newer requested baseline. Browser execution uses GKE Sandbox and Chromium's sandbox; weakening those controls is not an accepted availability workaround.

## Infrastructure lifecycle

### Platform-level ensure

- Private migration-media bucket and lifecycle policy.
- Bucket-scoped runtime IAM.
- GitHub deployment Workload Identity Federation.
- Reusable deployment workflow.
- Shared preview networking configuration.

### Site-level ensure

- Preview identity.
- GitHub repository creation/adoption.
- DNS record.
- Kubernetes namespace and managed labels.
- Self-managed certificate, vault entry, and binding.

### Release-level work

- Freeze artifact/media manifest.
- Publish an atomic GitHub commit.
- Build and deploy the site revision.
- Verify runtime, DNS, and exact certificate identity.

## Compatibility and removal strategy

- Existing routes remain temporarily available behind compatibility adapters while the preview-release API is adopted.
- Preview-specific Kubernetes `ManagedCertificate` provisioning is retired after Platfire succeeds through the self-managed path.
- Per-site generated workflow bodies are replaced by a generic reusable workflow.
- Production local-media fallback, hard-coded account fallbacks, and UI site-name placeholders are removed after replacement coverage exists.
- Historical JSON action records remain readable during migration but no longer drive current release state.

## Documentation responsibilities

- `CONTEXT.md` records current architecture, constraints, invariants, and decisions.
- `GOALS.md` records phased outcomes and acceptance criteria.
- Feature documents describe contracts, not chronological implementation history.
- Runbooks contain actionable operations and rollback procedures.
- Any change to release gates, resource ownership, credentials, or retention updates these files in the same change.

## Explicit non-goals

- Production hosting cutover for customer domains such as `www.platfire.com`.
- Google-managed production certificate automation.
- Migrating unrelated GitHub secrets to Secret Manager.
- Reproducing unauthorized content.
- Emulating arbitrary third-party server-side applications in faithful snapshot mode.
