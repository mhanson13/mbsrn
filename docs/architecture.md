# Architecture

## System Overview
Work Boots is a multi-tenant platform with a FastAPI monolith and a standalone Next.js operator UI.

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
Work Boots follows a layered backend structure:

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

## Testing Philosophy
- Mock provider APIs in backend tests; do not depend on live Google services.
- Prefer service-layer tests for normalization, policy, and business behavior.
- Verify token usability and scope enforcement before provider-call paths.
- Keep tests deterministic (fixed fixtures, explicit error mapping expectations).
