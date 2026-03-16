# Work Boots Platform And Security Architecture

## 1) System Overview
Work Boots is implemented as a FastAPI monolith with a standalone operator UI and Kubernetes-based deployment.

Current runtime components:
- API/backend: `app/` (FastAPI + repository/service pattern)
- Operator UI: `frontend/operator-ui` (Next.js + TypeScript)
- Kubernetes manifests: `infra/k8s` (kustomize base + `dev`/`prod` overlays)
- CI/CD: `.github/workflows` (`backend-ci.yml`, `frontend-ci.yml`, `deploy-gke.yml`)

High-level runtime flow:

```text
Operator Browser (Next.js UI)
  -> /api/auth/google/exchange (Google ID token exchange)
  -> App JWT access/refresh session
  -> Business-scoped API routes
  -> Services/Repositories (tenant-scoped)
  -> Postgres (Alembic-managed schema)
```

Deployment flow:
- GitHub Actions builds OCI images (Cloud Buildpacks).
- Images are pushed to Artifact Registry.
- `deploy-gke.yml` applies kustomize overlays to GKE and runs Alembic migration gate before rollout.

## 2) Core Architectural Invariants
These invariants are fixed and intentional:
- FastAPI monolith remains the system of record.
- Repository/service pattern with thin route handlers.
- Tenant isolation is business-scoped and enforced via `TenantContext` + scoped repository/service access.
- Internal principal/business membership and role checks are authoritative for authorization.
- Google identity is only identity proofing, not authorization.
- SEO/recommendation pipeline remains deterministic-first.
- AI is limited to summaries/narratives of persisted deterministic outputs.
- No microservice split and no distributed orchestration redesign.

## 3) Authentication And Authorization Flow

### Supported auth entry paths
Runtime bearer auth is resolved from:
1. App session JWT (human operator path)
2. DB-backed API credential (service/admin key path)

Key routes:
- `POST /api/auth/google/exchange`
- `POST /api/auth/refresh`
- `POST /api/auth/logout`
- `GET /api/auth/me`

### Google exchange path
1. UI/user obtains Google ID token.
2. API verifies token via JWKS (`app/integrations/google_auth.py`), including:
   - signature
   - issuer
   - audience
   - subject (`sub`)
   - email verification policy
3. API resolves internal mapping in `principal_identities` using:
   - `provider=google`
   - `provider_subject=<sub>`
4. API validates principal + identity active state.
5. API issues app JWT access/refresh tokens (`app/core/session_token.py`).
6. `TenantContext` is derived from internal claims and used for business scoping.

### Authorization boundary
- Google answers identity (`who is the user`).
- Work Boots answers authorization (`what can they do`) via principal/business/role checks.
- Authorization is never granted solely by Google email/domain.

### DB API credential path
- DB token hash lookup remains supported in `get_tenant_context`.
- Credential must be active and principal must be active.
- Resulting context is still internal and business-scoped.

## 4) Session And Security Controls

### JWT/session model
Implemented in `app/core/session_token.py`:
- access + refresh JWTs
- standard claims (`iss`, `aud`, `iat`, `nbf`, `exp`, `sub`, `jti`)
- rotation/replay handling for refresh tokens
- explicit revocation checks

### Session state + revocation
Implemented in `app/core/session_state.py`:
- session revocation/session-state backend abstraction
- Redis-backed distributed mode
- in-memory fallback mode for local/dev
- principal-level and identity-level revocation cutoffs

### Rate limiting
Implemented in `app/core/rate_limit.py`:
- auth route throttling (IP + user-agent bucket)
- stricter admin route throttling
- Redis-backed distributed mode with in-memory fallback path
- explicit fail-open/fail-closed behavior controls

Production/staging posture:
- Redis-backed security controls are expected (`RATE_LIMIT_BACKEND=redis`, `SESSION_STATE_BACKEND=redis`).
- Fail-open is not allowed for Redis-backed production/staging usage:
  - `RATE_LIMIT_FAIL_OPEN=false`
  - `SESSION_STATE_FAIL_OPEN=false`

### Logout and replay visibility
Implemented in auth service flow:
- `POST /api/auth/logout` revokes active session token(s)
- refresh replay detection emits security audit events
- audit payloads are structured and secret-safe

### Current browser token posture
Current operator UI behavior:
- access token: `sessionStorage`
- refresh token: in-memory only (non-persistent)
- sign-out calls `/api/auth/logout`

### API edge posture (CORS + security headers)
Implemented baseline controls:
- explicit CORS allowlist via `API_CORS_ALLOWED_ORIGINS`
- local/dev default origins only for local operator UI workflows
- wildcard CORS origin rejected for production/staging config
- default API security response headers:
  - `X-Content-Type-Options: nosniff`
  - `X-Frame-Options: DENY`
  - `Referrer-Policy: strict-origin-when-cross-origin`
  - API-scoped `Content-Security-Policy`
- configurable HSTS (`SECURITY_HEADERS_HSTS_ENABLED`, `SECURITY_HEADERS_HSTS_MAX_AGE_SECONDS`)

Known risk posture (deferred to Phase 5):
- token handling can be further hardened with secure `httpOnly` cookie-based refresh model + CSRF controls.

## 5) Deployment Architecture

### Build and release path
- `backend-ci.yml`:
  - dependency install
  - scoped quality gates (`ruff`, `black --check`, `mypy`)
  - Alembic migration-chain validation
  - backend tests with coverage reporting (`--cov=app`, term + XML)
- `frontend-ci.yml`:
  - deterministic install (`npm ci`)
  - lint/typecheck/build
- `deploy-gke.yml`:
  - build + push backend/UI OCI images
  - authenticate with GCP using Workload Identity Federation
  - apply kustomize overlay to GKE
  - run Alembic migration gate before rollout
  - rollout exact built image refs

### Kubernetes model
- Base manifests: namespace-neutral in `infra/k8s/base`
- Overlays own namespaces:
  - `infra/k8s/overlays/dev` -> `work-boots-dev`
  - `infra/k8s/overlays/prod` -> `work-boots`
- API and UI deployments/services are both included.

### Schema discipline
- Alembic is authoritative for CI/staging/prod/GKE.
- Startup `create_all()` is guarded for local/dev/test convenience only (`DB_AUTO_CREATE_LOCAL` + local-like env).

### Production config expectations
- Secrets/config are externalized (Kubernetes Secret/ConfigMap and CI secrets).
- Production should enforce explicit fail-closed behavior for security controls unless intentionally overridden.

## 6) Phase Boundary View (Phase 4 -> Phase 5)

### What Phase 4 completes
Phase 4 operationalization delivers:
- deployable operator UI + API stack
- Google identity proofing integrated with internal principal mapping
- JWT session lifecycle with rotation/replay handling
- Redis-capable session-state and rate-limit controls
- deterministic CI/CD + GKE rollout path
- Alembic-first migration discipline

### What moves to Phase 5
Phase 5 is security-maturity and production-posture hardening:
- browser/session hardening (cookie + CSRF model)
- CSP/security header hardening
- stronger security observability and incident-response controls
- Redis production posture enforcement and validation
- adversarial validation/pen-testing loops

Roadmaps:
- Phase 4 operationalization roadmap: `docs/phase4-platform-operationalization-roadmap.md`
- Phase 5 security maturity roadmap: `docs/phase5-security-maturity-roadmap.md`

## 7) Known Gaps / Future Hardening
Planned hardening areas after current baseline:
- cookie-based refresh token model with CSRF-safe flow
- CSP and security-header enforcement verification across UI/API delivery path
- expanded security observability (auth anomaly visibility, SIEM-ready event pipeline)
- incident-response controls:
  - revoke all sessions for principal
  - revoke all sessions for business
- Redis production hardening:
  - network boundary restrictions
  - auth/TLS expectations
  - explicit fail-mode enforcement by environment
- penetration and abuse testing:
  - replay/token theft simulation
  - tenant-isolation negative-path validation
  - rate-limit bypass validation

## Out Of Scope
Out of scope for this architecture baseline:
- replacing monolith architecture
- replacing principal/business authorization model
- changing deterministic/AI boundaries in SEO.ai pipeline
- broad platform re-architecture or microservice migration
