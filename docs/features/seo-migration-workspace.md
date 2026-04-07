# SEO Migration Workspace (Phase 1-4)

## Intent
The migration workspace is a controlled operator workflow for replacing weak incumbent SMB websites with reviewable, structured, AI-assisted static artifacts.

The incumbent site is a signal source, not a canonical source of truth. The migration workspace becomes canonical by combining:
- imported source-site facts/signals
- operator requirements and requested changes
- enriched replacement content notes
- existing MBSRN audit/recommendation/competitor summaries

## Trust Boundary and Lifecycle
Authoritative boundary:

`AI generation -> draft artifacts -> operator approval -> explicit publish -> explicit deploy`

Lifecycle states are tracked independently:
- Draft generated (`migration_status=draft_generated`)
- Draft approved (`migration_status=draft_approved`)
- Published to GitHub (`migration_status=published_to_github`)
- Deploy requested (`migration_status=deploy_requested`)

No auto-publish or auto-deploy behavior exists in this feature.

State/order invariants:
- publish is blocked until the selected artifact version is approved and publish target readiness is valid
- deploy is blocked until the selected artifact version has a successful publish and deploy target readiness is valid
- failed publish attempts do not mark deploy-ready state
- failed deploy attempts do not mutate last successful publish metadata (artifact id/commit/timestamp)
- UI readiness indicators are derived from persisted workspace/artifact state returned by backend summary/readiness payloads

## Operator Workflow
Primary workflow in site workspace `Migration` tab:
1. Create/manage workspace and set `source_url`.
2. Run bounded source ingest.
3. Capture requirements and enriched replacement content.
4. Generate and review draft artifacts.
5. Approve an artifact version.
6. Configure publish target and run publish dry-run.
7. Publish approved artifact to target repository.
8. Configure deploy target and run deploy dry-run.
9. Submit explicit deploy request to GKE deployment workflow.

Important operator cue:
- GitHub publish is not production deployment.

## Source Ingest Limits and Safety
Homepage ingest remains intentionally bounded:
- HTTP(S) only
- timeout/redirect/size limits
- HTML/XHTML content-type validation
- shallow extraction only (not a broad crawler)

Normalized extraction includes:
- title/meta/canonical
- headings
- phone/email/address/contact signals
- bounded same-origin links
- service-like blocks
- static asset reference metadata
- cleaned text blocks for context assembly

## Draft Artifact Contract
Draft generation uses existing provider patterns (`mock`, `openai`, misconfigured-safe fallback) and requires structured JSON.

Guardrails:
- bounded file count and payload size
- strict static-file path/extension boundaries
- rejection of backend/runtime/infra files
- analytics snippet normalization to placeholders
- partial salvage only for valid fragments

## Publish Workflow (GitHub)
Publish target is site-scoped configuration:
- `repo_owner`
- `repo_name`
- `branch`
- `artifact_root`
- `enabled`

Publish behavior:
- explicit operator-triggered action only
- approved artifact required
- bounded file/path validation before publish
- no writes outside configured artifact root
- dry-run supported
- history captured with status/result metadata
- duplicate non-dry-run publish attempts for the same artifact+target are rejected with operator-readable validation errors
- retry after a failed publish is supported and recorded as a new history event
- dry-run publish records history but does not overwrite prior successful publish commit metadata

Security constraints:
- no GitHub token storage in migration rows
- no token values returned by API
- no token values logged

## Required Runtime Configuration
Migration publish/deploy runtime configuration is environment-driven:
- `MIGRATION_GITHUB_TOKEN`
- `MIGRATION_GITHUB_API_BASE_URL`
- `MIGRATION_GITHUB_TIMEOUT_SECONDS`
- `MIGRATION_PUBLISH_COMMIT_MESSAGE_PREFIX`
- `MIGRATION_PUBLISH_COMMITTER_NAME`
- `MIGRATION_PUBLISH_COMMITTER_EMAIL`
- `MIGRATION_DEPLOY_DEFAULT_WORKFLOW_ID`
- `MIGRATION_DEPLOY_DEFAULT_REF`

Notes:
- token is only read from runtime environment, never persisted in workspace rows
- per-site publish/deploy target details are stored in workspace config JSON fields
- runtime config is validated at action/readiness time for migration publish/deploy (feature-scoped validation); unrelated app features continue running when migration config is missing

## Deploy Workflow (GKE Path)
Deploy target is site-scoped configuration:
- optional repo override (`repo_owner`, `repo_name`)
- workflow id/ref (`workflow_id`, `ref`)
- bounded workflow `inputs`
- `enabled`

Deploy behavior:
- explicit operator-triggered action only
- approved + published artifact required
- readiness/state tracked separately from publish state
- deployment history captured with status/result metadata
- duplicate non-dry-run deploy requests for the same artifact+target+inputs are rejected with operator-readable validation errors
- retry after a failed deploy is supported and recorded as a new history event
- deploy dry-run records history but does not overwrite prior successful deploy request markers

Current deployment model is reused via workflow dispatch conventions; platform deployment architecture is not redesigned by this feature.

## Analytics Insertion Rules
Analytics is controlled by platform logic, not model snippets.

Fields:
- `analytics_config_json.enabled`
- `analytics_config_json.ga_measurement_id`
- `analytics_config_json.insertion_mode` (`publish_only` or `publish_and_deploy`)

Rules:
- model-emitted analytics scripts are normalized to placeholders
- measurement id insertion precedence:
1. publish request override id (publish only)
2. workspace analytics config id
3. site GA4 measurement id
- `publish_only` mode omits GA measurement input from deploy dispatch
- placeholder normalization is deterministic (duplicate placeholders collapse to a single insertion point)
- repeated publish/deploy actions do not duplicate analytics insertion in generated output payloads
- insertion is restricted to allowed static artifact files and controlled modes only

## Failure Categories and Operator Next Steps
Migration publish/deploy paths normalize failures into stable categories:
- `config_missing`
  - Missing/invalid migration runtime config (most commonly GitHub publisher configuration).
  - Operator action: verify runtime env wiring (`MIGRATION_*`) and redeploy API if needed.
- `target_invalid`
  - Publish/deploy target repo/branch/root/workflow/ref/inputs failed validation.
  - Operator action: fix site workspace target config and retry.
- `approval_required`
  - Attempted publish/deploy before required approval/publish prerequisites were satisfied.
  - Operator action: approve artifact first; deploy only after successful publish.
- `duplicate_request`
  - Duplicate publish/deploy request for same artifact + equivalent target context.
  - Operator action: verify prior request outcome before resubmitting.
- `artifact_invalid`
  - Selected artifact files were not publishable under bounded static-file rules.
  - Operator action: regenerate/re-approve a valid artifact version.
- `provider_error`
  - Publish execution failed in provider call path.
  - Operator action: inspect publish history + external provider status and retry.
- `deploy_error`
  - Deploy dispatch failed in provider call path.
  - Operator action: inspect deploy history + workflow execution status and retry.
- `unknown_error`
  - Fallback category when no more specific category is available.

These categories are exposed through migration readiness/history payload fields for operator diagnostics.

## History Record Contract
Publish/deploy history entries are append-only, bounded lists and include:
- `action` (`publish` or `deploy`)
- `status` (`dry_run`, `published`, `deploy_requested`, `failed`)
- `timestamp`
- artifact identifiers (`artifact_version_id`, `artifact_version`)
- target metadata relevant to the action (repo/branch/root or repo/workflow/ref/inputs)
- analytics metadata (`analytics_measurement_id`, `analytics_insertion_mode`, plus `analytics_applied` when available)
- result identifiers when available (`latest_commit_sha`, `commit_shas`, `published_at`, `dispatched_at`)
- normalized failure category (`failure_category`) on error paths
- sanitized failure summary (`error_summary`) on error paths

## Structured Logging
Migration control-plane actions emit structured logs (`event=seo_migration_control_plane_action`) for:
- approval requested/completed/failed
- publish requested/completed/failed
- deploy requested/completed/failed

Logged fields are safe metadata only:
- `business_id`, `site_id`, `workspace_id`
- `artifact_version_id`, `artifact_version`
- `action`, `status`, `dry_run`, `duration_ms`
- sanitized target summary (repo/branch/root or workflow/ref)
- `failure_category` and sanitized `failure_reason` on failures

Not logged:
- tokens/secrets
- full generated artifact contents
- raw provider stack traces in operator-facing surfaces

## API Surface (Phase 1-4)
Core workspace:
- `PUT /api/businesses/{business_id}/seo/sites/{site_id}/migration/workspace`
- `GET /api/businesses/{business_id}/seo/sites/{site_id}/migration/workspace`
- `GET /api/businesses/{business_id}/seo/sites/{site_id}/migration/summary`
- `GET /api/businesses/{business_id}/seo/sites/{site_id}/migration/prompt-preview`

Inputs/ingest:
- `POST /api/businesses/{business_id}/seo/sites/{site_id}/migration/source-ingest`
- `PUT /api/businesses/{business_id}/seo/sites/{site_id}/migration/operator-requirements`
- `PUT /api/businesses/{business_id}/seo/sites/{site_id}/migration/enriched-content`

Draft artifacts:
- `POST /api/businesses/{business_id}/seo/sites/{site_id}/migration/generate-draft-artifacts`
- `GET /api/businesses/{business_id}/seo/sites/{site_id}/migration/artifact-versions`
- `GET /api/businesses/{business_id}/seo/sites/{site_id}/migration/artifact-versions/{artifact_version_id}`
- `GET /api/businesses/{business_id}/seo/sites/{site_id}/migration/artifact-versions/{artifact_version_id}/file-preview?path=...`

Publish/deploy controls:
- `PUT /api/businesses/{business_id}/seo/sites/{site_id}/migration/publish-config`
- `PUT /api/businesses/{business_id}/seo/sites/{site_id}/migration/deploy-config`
- `PUT /api/businesses/{business_id}/seo/sites/{site_id}/migration/analytics-config`
- `POST /api/businesses/{business_id}/seo/sites/{site_id}/migration/artifact-versions/{artifact_version_id}/approve`
- `POST /api/businesses/{business_id}/seo/sites/{site_id}/migration/publish`
- `POST /api/businesses/{business_id}/seo/sites/{site_id}/migration/deploy`
- `GET /api/businesses/{business_id}/seo/sites/{site_id}/migration/publish-history`
- `GET /api/businesses/{business_id}/seo/sites/{site_id}/migration/deploy-history`

## Operator Runbook
1. Confirm source ingest is complete and reviewed.
2. Confirm enriched content/requirements override weak incumbent content where needed.
3. Generate draft artifacts and review files.
4. Approve the chosen artifact version.
5. Save publish target config and run publish dry-run.
6. Run publish (non-dry-run) after dry-run checks pass.
7. Save deploy target config and run deploy dry-run.
8. Submit deploy request.
9. Validate deployment externally and coordinate DNS cutover separately.

## Controlled Production Exercise Checklist
Use this checklist for a bounded real-world migration exercise:
1. Confirm migration runtime config is present (`MIGRATION_GITHUB_TOKEN` and related `MIGRATION_*` values).
2. Confirm publish target repo/branch/artifact-root is intentional for this site workspace.
3. Confirm the selected artifact version is explicitly approved.
4. Confirm analytics insertion mode (`publish_only` vs `publish_and_deploy`) and measurement id are intentional.
5. Run publish, then verify summary/readiness state and latest publish history entry (`status`, target, commit identifiers).
6. Run deploy, then verify summary/readiness state and latest deploy history entry (`status`, workflow/ref, dispatch timestamp).
7. Confirm diagnostics fields report expected values after each action (`last_publish_status`, `last_publish_failure_category/message`, `last_deploy_status`, `last_deploy_failure_category/message`).
8. Confirm traceability fields are present across logs/history (`business_id`, `site_id`, `workspace_id`, `artifact_version_id`, action/status, target summary, failure category, timestamp).
9. Confirm DNS/A-record cutover remains manual and outside the app.
10. Confirm rollback path: select prior stable artifact, re-approve, then explicitly re-publish and re-deploy.

## Troubleshooting and Rollback
Publish failures:
- verify target repo/branch/root config
- verify artifact approval status and readiness reasons
- check path-boundary rejections in publish warnings/history
- if duplicate publish is reported, either select a different approved artifact or change target config intentionally

Deploy failures:
- verify publish completed for selected artifact
- verify deploy target enabled/workflow/ref values
- inspect deploy history inputs and workflow execution status
- if duplicate deploy is reported, verify whether the prior deploy request already covers the same artifact+target+inputs

Verification checklist:
- publish success:
  - migration summary shows publish status/readiness aligned with latest action
  - publish history latest entry includes `status=published`, target metadata, and commit identifiers when available
- deploy success:
  - migration summary shows deploy status/readiness aligned with latest action
  - deploy history latest entry includes `status=deploy_requested`, workflow/ref, and dispatch timestamp

Rollback pattern:
- select and re-approve an older stable artifact version
- re-publish and re-deploy explicitly
- no automatic rollback orchestration is performed in this phase
- DNS/A-record cutover remains an external operator task and is not automated by this feature

## Known Limitations
- bounded ingest scope (homepage-first, shallow extraction)
- no background worker pipeline introduced
- no external asset proxying
- no infrastructure/runtime file generation by model
- deploy request tracks intent/history; production validation remains an operator responsibility
