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

## Competitor Candidate Validation
- Candidate parsing applies an early required-field filter before service-layer draft construction:
  - candidates missing `name` are dropped
  - candidates missing `domain` are dropped
  - domains are normalized to hostname form (for example, `https://example.com/` becomes `example.com`)
- Empty candidate arrays are valid provider outcomes and do not automatically fail a run.
- `malformed_output` is reserved for true structured-output failures (for example, unparseable or invalid top-level JSON shape), not for "zero valid candidates after filtering".

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
