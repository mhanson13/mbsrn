# Architecture

## System Overview
mbsrn is a multi-tenant platform with a FastAPI monolith and a standalone Next.js operator UI.

Primary runtime components:
- Backend API: `app/`
- Operator UI: `frontend/operator-ui/`
- Kubernetes manifests: `infra/k8s/`
- CI/CD workflows: `.github/workflows/`

## API-First Design
- The API is the system of record for business logic.
- The operator UI calls business-scoped API endpoints; it does not implement authorization logic.
- Provider credentials and token operations are backend-only.

## Service Layering
mbsrn follows a layered backend structure:

```text
routes (HTTP contracts, error mapping)
  -> services (business rules, policy, orchestration)
    -> repositories (scoped persistence)
      -> models / database

provider clients (Google/OAuth/GBP HTTP wrappers)
  <- called by services, never by routes directly
```

Examples:
- GBP routes: `app/api/routes/integrations.py`
- GBP connection service: `app/services/google_business_profile_connection.py`
- GBP read service: `app/services/google_business_profile_service.py`
- GBP verification guidance service: `app/services/verification_guidance_service.py`
- GBP API client: `app/integrations/google_business_profile.py`

## Multi-Tenant / Business Scoping Model
- Request scope is resolved server-side by `TenantContext` (`app/api/deps.py`).
- Authenticated context carries `business_id` + `principal_id`.
- Services and repositories use this scope for data access and mutation.
- Cross-business access is rejected.

Primary scoped entities:
- `principals`
- `principal_identities`
- `provider_connections`
- `provider_oauth_states`

## Security Boundaries
- Google OIDC login is identity proofing only.
- Internal principal/business checks are the authorization boundary.
- Google Business Profile authorization is a separate OAuth flow.
- Long-lived provider credentials remain server-side and encrypted at rest.
- GCP runtime ADC for admin Cloud Logging diagnostics/query uses GKE Workload Identity mapping (`KSA -> GSA`) and project-scoped IAM.

Workload Identity runbook:
- [GCP Workload Identity (ADC)](gcp-workload-identity.md)

## Normalization Boundary
- Provider-specific payload and transport details stay in provider clients.
- Service layer is the normalization boundary that maps provider data into stable application/domain contracts.
- Route handlers return service-normalized models; frontend code must not depend on raw provider response shapes.
- If raw or semi-raw provider fields must be exposed, that exposure must be explicit, controlled, and documented.

Why this matters:
- UI stability when provider payload shapes change.
- Deterministic service-layer tests for business behavior.
- Future provider portability without frontend rewrites.
- Prevention of accidental Google API shape leakage across app boundaries.

## Provider-Specific Logic Placement
Provider-specific behavior belongs in the GBP service/client path:
- HTTP transport and provider error parsing: `app/integrations/google_business_profile.py`
- token-use policy checks and reconnect/scope decisions: `app/services/google_business_profile_connection.py`
- canonical provider->domain verification mapping tables/helpers: `app/services/google_business_profile_verification_mapping.py`
- business-level mapping/normalization: `app/services/google_business_profile_service.py`
- deterministic operator guidance from normalized state: `app/services/verification_guidance_service.py`

Routes should only:
- call services
- map service exceptions to HTTP responses
- return schema-conformant payloads

Observability note:
- Unknown provider values (state/method/error) degrade to safe normalized defaults and are logged with structured warning events for follow-up mapping updates.
- GBP verification hardening also tracks lightweight in-process counters for unknown/fallback events in `app/services/google_business_profile_verification_observability.py`.

Frontend contract note:
- Operator UI is expected to render backend guidance contracts (`guidance` on success and normalized verification errors) rather than rebuilding guidance logic locally.
- Verification contract drift is guarded by a checked-in backend-generated schema artifact:
  - `docs/contracts/gbp-verification-contract.schema.json`
  - guard command: `python scripts/gbp_verification_contract_guard.py --check`

## Testing Philosophy
- Mock provider APIs in backend tests; do not depend on live Google services.
- Prefer service-layer tests for normalization, policy, and business behavior.
- Verify token usability and scope enforcement before provider-call paths.
- Keep tests deterministic (fixed fixtures, explicit error mapping expectations).

## Frontend Action Control Layer

The operator UI includes a frontend-only Action Control Layer for recommendation/automation decision surfaces.

Implementation points:
- types: `frontend/operator-ui/lib/api/types.ts`
- pure derivation: `frontend/operator-ui/lib/transforms/actionExecution.ts`
- presentation: `frontend/operator-ui/components/action-execution/ActionControls.tsx`

Core contract:
- controls are derived from existing read-model state (`actionStateCode`, automation lifecycle, linkage ids, trust tier)
- controls are deterministic and additive
- controls do not mutate backend workflow semantics

Separation of concerns:
- **Visibility**: what happened (status/outcome)
- **Execution readiness**: what can be done now (`review`, `run`, `view status`, `blocked`)
- **Completion**: what is already acted-on (`completed_acted`)

Trust boundary:
- weaker trust tiers remain review-first and do not imply automatic completion
- informational states still render explicit non-actionable/blocked guidance instead of empty UI

Local validation strategy:
- mock-driven transform tests (`actionExecution.test.ts`)
- route-level UI tests using mocked payloads only (no provider/runtime dependency)

## Action Chaining Layer

The backend includes a deterministic Action Chaining Layer that generates follow-on actions after qualifying workflow transitions.

Implementation points:
- chain rules: `app/services/action_chaining_service.py`
- chain schema: `app/schemas/action_chaining.py`
- persistence model: `app/models/seo_action_chain_draft.py`
- activation service: `app/services/action_chain_activation_service.py`
- persistence repository: `app/repositories/seo_action_chain_draft_repository.py`
- activated action repository: `app/repositories/seo_action_execution_item_repository.py`
- transition hook: `app/services/seo_recommendations.py`
- activation route: `POST /api/businesses/{business_id}/seo/sites/{site_id}/actions/{action_id}/next-actions/{draft_id}/activate`

Behavior:
- no AI/provider calls
- no asynchronous worker dependency
- deterministic `action_type + state` rules only
- additive persistence of `pending` chained drafts
- additive activation from draft -> first-class action execution item

Current transition mapping:
- recommendation transition to `accepted` -> chained evaluation state `accepted`
- recommendation transition to `resolved` -> chained evaluation state `completed`

Current rule examples:
- `seo_fix` + `accepted` -> `verify_fix`
- `publish_content` + `completed` -> `promote_content`
- `optimize_page` + `completed` -> `measure_performance`

Persistence and idempotency:
- chained outputs are stored in `seo_action_chain_drafts`
- deduped per `(business_id, site_id, source_action_id, action_type)`
- activated outputs are stored in `seo_action_execution_items`
- activation is idempotent per draft (`source_draft_id` uniqueness) and returns the existing action id on repeat activation

Chained draft lifecycle:
- `pending` -> generated but not promoted
- `activated` -> promoted to a first-class action execution item (`activated_action_id` persisted)

Deterministic automation linkage metadata:
- `automation_ready`: indicates whether a chained action type is suitable for later automation binding
- `automation_template_key`: internal hint key used for future automation bindings (metadata-only; non-executing)

Unified lineage read model:
- service: `app/services/action_lineage_service.py`
- endpoint: `GET /api/businesses/{business_id}/seo/sites/{site_id}/actions/{action_id}/lineage`
- canonical response includes source action, chained drafts, activated actions, and deterministic counts
- read-only hydration path for workspace/recommendation/automation UI consistency
- recommendation/workspace read payloads now attach additive `action_lineage` per recommendation so UI can consume next-step truth from the main operator read flow instead of multi-endpoint inference

Observability:
- structured service log event `action_chaining_generated` includes:
  - `source_action_id`
  - `generated_count`
  - `action_types`

## Automation Output Review + Decision Capture

The Action Control Layer now includes a thin Output Review + Decision Capture step to close the operator loop for output-ready items.

Implementation points:
- output review component: `frontend/operator-ui/components/action-execution/OutputReview.tsx`
- state/decision transforms: `frontend/operator-ui/lib/transforms/actionExecution.ts`
- additive UI types: `frontend/operator-ui/lib/api/types.ts`

Decision model (frontend-derived):
- `accepted`
- `rejected`
- `deferred`

Deterministic local state transitions:
- `accepted` -> `completed_acted`
- `rejected` -> `blocked_unavailable`
- `deferred` -> `recommendation_only_review`

Deterministic operator-facing outcome mapping:
- accepted outcome: "Automation output accepted."
- rejected outcome: "Automation output rejected."
- deferred outcome: "Automation output review deferred."

Readiness vs completion boundary:
- Output review is explicit before completion for `automation_output_ready`.
- Informational/lower-trust items remain review-first and are not auto-promoted to done.
- If no action is available, UI still renders blocked/muted guidance instead of empty controls.

Persistence boundary:
- Frontend updates local decision state immediately.
- Existing safe mutation path is reused only where already available (`updateRecommendationStatus` for accepted/rejected recommendation decisions).
- No automation engine or orchestration changes are introduced.

Local test strategy:
- mocked transform tests for decision transitions and presentation defaults
- mocked page tests for recommendation/workspace/automation run surfaces
- no provider/runtime dependency required for decision-capture validation

## Recommendation Bulk Mutation Resilience

Bulk recommendation status mutations now use bounded frontend concurrency instead of unbounded parallel fan-out.

Implementation boundary:
- UI queue processing: `frontend/operator-ui/app/recommendations/page.tsx`
- shared bounded queue helper: `frontend/operator-ui/lib/bulkActionQueue.ts`
- per-item mutation endpoint remains unchanged: `PATCH /api/.../sites/{site_id}/recommendations/{recommendation_id}`

Operational behavior:
- fixed in-flight concurrency cap (`4`) for bulk accept/dismiss workflows
- optimistic row-level status updates during processing
- single controlled post-batch refresh instead of per-item refresh storms
- partial failures are reported explicitly and retained for follow-up selection

Pool-pressure observability:
- API now emits structured route-context logging for SQLAlchemy pool timeout exceptions and returns a transient `503` response instead of an opaque unhandled `500`.

## AI Provider Execution Modes
Competitor profile generation now routes provider calls by explicit execution mode and call capability, not by hardcoded endpoint selection in service logic.

- `fast_path`
  - provider call type: `non_tool`
  - web search: disabled
  - context mode: reduced (`reduced_context_mode=true`)
  - attempt number: `0`
  - intent: low-latency first pass
- `full`
  - provider call type: `tool_enabled`
  - web search: enabled
  - context mode: full
  - attempt number: `1`
  - intent: highest-quality search-backed discovery
- `degraded`
  - provider call type: `non_tool`
  - web search: disabled (hard guard)
  - context mode: reduced (`reduced_context_mode=true`)
  - attempt number: `2`
  - intent: timeout recovery path after full-attempt timeout

Runtime guardrails:
- Fast and degraded modes must use `non_tool` provider calls.
- Full mode is the only mode allowed to use `tool_enabled`.
- Structured provider telemetry includes:
  - `execution_mode`
  - `provider_call_type`
  - `web_search_enabled`
  - `attempt_number`
  - `duration_ms`

Latency tradeoff:
- Non-tool calls are generally faster and more deterministic.
- Tool-enabled calls are higher-latency but improve real-time competitor discovery quality.

## Competitor Search Escalation
Competitor generation now applies both timeout-based and quality-based escalation.

- Timeout-based escalation remains unchanged:
  - fast_path (`attempt_number=0`) failure falls through to full (`attempt_number=1`)
  - full timeout falls through to degraded (`attempt_number=2`)
- Quality-based escalation (conservative guardrail):
  - if fast_path completes successfully but returns zero valid candidates, the run escalates to full search-backed execution before finalizing
  - escalation reason is recorded as `zero_valid_competitors` in provider attempt debug metadata
- Re-escalation guardrails:
  - full attempts do not trigger another full/search escalation
  - degraded remains timeout-recovery only and still uses non-tool calls with web search disabled

## Prompt Resolution Model
Competitor prompt execution and preview use the same resolved prompt assembly pipeline.

- Resolved prompt composition:
  - `system_prompt`
  - normalized business admin override instruction body when present, otherwise default template instruction body
  - platform constraints
  - structured context injection
- Admin override precedence:
  - non-empty business admin override text wins over deployment/default template text
  - override text is normalized and placeholder-rendered before final prompt assembly
- Version/source metadata:
  - prompt source comes from resolved settings (`admin_config`, `env`, `default`)
  - prompt version is extracted from the resolved user prompt marker (`PROMPT_VERSION: ...`) when present
  - if no marker exists, prompt version falls back to the configured template/provider version
- UI/debug behavior:
  - workspace prompt preview and run metadata should display resolved prompt source + resolved prompt version
  - template metadata is secondary and must not override resolved prompt identity

## Competitor Candidate Validation
- Candidate parsing applies an early required-field filter before service-layer draft construction:
  - candidates missing `name` are dropped
  - domains are normalized to hostname form (for example, `https://example.com/` becomes `example.com`)
- Empty candidate arrays are valid provider outcomes and do not automatically fail a run.
- `malformed_output` is reserved for true structured-output failures (for example, unparseable or invalid top-level JSON shape), not for "zero valid candidates after filtering".

## Final Output Guarantee
- Final-stage guarantee prevents avoidable zero-draft completions when upstream candidates were discovered.
- If strict filtering produces zero drafts but upstream parsed candidates exist, the service selects a bounded forced fallback set (up to 3-5, depending on requested count).
- Forced fallback only relaxes final draft emission requirements:
  - allows weak/missing domain
  - allows classification mismatch
  - allows low confidence values in-range
  - still rejects clearly invalid entries (for example missing name)
- Forced drafts are tagged for review transparency:
  - `forced_inclusion=true`
- `forced_reason=no_valid_drafts_after_filtering`
- If provider candidates are truly empty, the run still completes with an empty draft list (valid zero-result outcome).

## Competitor Discovery Hints
- `SITE_CONTEXT_JSON` now includes optional `competitor_search_hints` values generated deterministically from:
  - primary ZIP (when present)
  - derivable normalized city/state context
  - `service_focus_terms`
- These hints are guidance-only strings to improve competitor discovery reliability for low-context sites.
- Hints are not authoritative data and never treated as confirmed competitors.
- No external lookups are used to generate hints; they are derived from existing site/business context only.

## Relaxed Competitor Eligibility
- Unsupported competitor type labels are treated as a soft classification mismatch signal instead of an automatic hard reject.
- Candidates with weak/missing domains can still pass when local/industry overlap evidence is strong; confidence is capped for weak-domain candidates.
- `no_live_site` outcomes can be relaxed for strong local evidence instead of always hard-failing the candidate.
- Over-filter safety fallback applies when all candidates would otherwise be rejected only for relaxable reasons (`no_live_site` / unsupported-type context):
  - allow up to top 3 candidates by confidence/detail
  - mark `relaxed_filtering_applied=true`
- Service telemetry emits `competitor_filtering_relaxation` with:
  - `unsupported_type_allowed`
  - `no_domain_allowed`
  - `relaxed_filtering_applied`

## Competitor Candidate Pipeline Observability
- Post-provider pipeline stages are tracked as:
  - raw provider candidates
  - valid parsed candidates
  - eligibility filtering
  - tuning/pruning
  - existing-domain removal and deduplication
  - final candidate-limit trimming
- Service telemetry emits `competitor_candidate_rejection_summary` with:
  - `raw_count`
  - `valid_count`
  - `rejected_by_eligibility`
  - `removed_by_existing_domain_match`
  - `removed_by_deduplication`
  - `removed_by_final_limit`
  - `final_count`
  - reason histogram
- `competitor_candidate_rejected` events provide capped per-candidate rejection visibility for diagnosis.
- Failure semantics:
  - malformed provider output: parsing/shape failure only
  - zero provider candidates: valid empty outcome
  - later-stage filtering to zero drafts: non-provider pipeline rejection outcome

## Admin Site Maintenance
- Admin-only site maintenance endpoints are exposed under business-scoped SEO routes:
  - `PATCH /api/businesses/{business_id}/seo/admin/sites/{site_id}`
  - `DELETE /api/businesses/{business_id}/seo/admin/sites/{site_id}`
- Site maintenance is service-driven (`SEOSiteService`) and destructive deletion is centralized in `delete_site_permanently(...)`.
- Permanent delete removes the site row and all site-owned SEO records in one transaction, including:
  - audit runs/pages/findings/summaries
  - competitor sets/domains/snapshot runs/snapshot pages/comparison runs/comparison findings/comparison summaries
  - recommendation runs/recommendations/narratives
  - automation configs/runs
  - competitor profile generation runs/drafts
  - tuning preview events
  - competitor profile cleanup execution records scoped to the site
- Delete is hard-delete behavior (no soft delete) and is intended to be irreversible once confirmed in admin UI.
