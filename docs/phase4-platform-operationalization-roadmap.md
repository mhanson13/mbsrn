# Phase 4 Platform Operationalization Roadmap

## Purpose And Scope
Phase 4 operationalizes the existing Work Boots CRM + SEO.ai platform for pilot use. This roadmap captures:
- what is already implemented
- what still needs hardening before pilot
- what is explicitly out of scope for this phase

Phase 4 scope is operationalization of the current monolith, not product-surface expansion.

## Fixed Architecture Constraints
The following architecture constraints remain fixed:
- FastAPI monolith
- repository/service pattern with thin routes
- business-scoped APIs with `TenantContext` tenant isolation
- internal authorization via principal/business membership and role checks
- Google identity used only for identity proofing
- deterministic-first SEO/recommendation pipeline
- AI used only for summaries/narratives over persisted deterministic outputs

## Current Completed Phase 4 Areas

### 1) Standalone Operator UI
Completed:
- Next.js + React + TypeScript operator UI in `frontend/operator-ui`
- typed API client usage against existing backend APIs
- operator surface for sites, audits, competitors, recommendations, and automation history

### 2) Google Identity + Internal Authorization Mapping
Completed:
- Google OIDC exchange endpoint (`POST /api/auth/google/exchange`)
- JWKS-based Google token verification (issuer, audience, subject, email verification policy)
- mapping to persisted `principal_identities` (`provider=google`, `provider_subject=sub`)
- internal principal/business/role authorization remains authoritative

### 3) Auth/Session Hardening
Completed:
- JWT access + refresh session tokens with rotation/replay handling
- Redis-capable session state backend with in-memory fallback path for local/dev
- Redis-capable distributed rate limiting with in-memory fallback path for local/dev
- replay/logout auth audit event coverage
- production/staging guardrails for Redis-backed security controls:
  - `RATE_LIMIT_FAIL_OPEN=false`
  - `SESSION_STATE_FAIL_OPEN=false`

### 4) API Edge Posture (CORS + Security Headers)
Completed:
- restrictive, config-driven API CORS policy (`API_CORS_ALLOWED_ORIGINS`)
- local/dev default origins for operator UI local workflows only
- wildcard CORS origin rejected for production/staging configuration
- baseline API security response headers:
  - `X-Content-Type-Options`
  - `X-Frame-Options`
  - `Referrer-Policy`
  - API-scoped `Content-Security-Policy`
- configurable HSTS with production/pilot defaults enabled
### 5) CI/CD + GKE Deployment Path
Completed:
- GitHub Actions CI and deploy workflows
- Workload Identity Federation-based Google auth in CI/CD
- Artifact Registry image build/push flow
- GKE deploy path with rollout gating
- OCI-compatible image build path for containerd runtime

### 6) Backend CI Quality + Coverage Visibility
Completed:
- scoped backend quality gates in CI:
  - `ruff`
  - `black --check`
  - scoped `mypy`
- backend coverage reporting in CI (`pytest --cov=app`) with XML artifact output

### 7) Alembic-First Migration Discipline
Completed:
- startup schema auto-create guarded to local/dev/test behavior only
- CI and deploy flows treat Alembic migrations as authoritative
- migration checks executed before rollout

## Remaining Phase 4 Work Before Pilot

### A) Redis Runtime Validation In Real Deployment Environments
Remaining:
- confirm Redis connectivity and behavior in deployed dev/staging environment (not only local/test)
- verify explicit behavior for:
  - `RATE_LIMIT_BACKEND=redis`
  - `SESSION_STATE_BACKEND=redis`
  - `RATE_LIMIT_FAIL_OPEN`
  - `SESSION_STATE_FAIL_OPEN`
- confirm logs/alerts clearly show backend selection and fallback behavior during failure simulation

### B) Frontend Validation/Build Verification
Remaining:
- verify operator UI lint/typecheck/build in the target CI environment with production-like config
- verify runtime session behavior (token exchange, refresh, logout) in deployed environment
- confirm documented behavior matches actual operator usage and browser lifecycle

### C) CSP/Security Header Implementation Or Verification
Remaining:
- validate effective header behavior end-to-end through ingress and UI hosting (not only app responses)
- confirm ingress/proxy layers preserve or intentionally override app-level security headers

### D) Production Config Verification For Fail-Closed Security Defaults
Remaining:
- validate deployed environment wiring for:
  - `RATE_LIMIT_BACKEND=redis`
  - `SESSION_STATE_BACKEND=redis`
  - `RATE_LIMIT_FAIL_OPEN=false`
  - `SESSION_STATE_FAIL_OPEN=false`
- validate deployment manifests/secrets/config include required auth/session/pepper settings

### E) Image Existence And Deploy Verification Checks
Remaining:
- confirm release/deploy pipeline behavior in target environments always rolls out exact built image references
- confirm deploy failures are operator-visible when expected image references are missing
- confirm post-rollout verification surfaces image digest/tag used per workload

### F) Pilot Operational Checklist
Remaining:
- finalize pilot runbook for:
  - auth/identity onboarding and principal mapping checks
  - migration rollout order and rollback procedure
  - operator UI login/session troubleshooting
  - automation run monitoring and failure handling
  - incident response contacts and escalation path

## Suggested Work Breakdown

### Phase 4A (Completed): Core Operationalization
Completed:
- operator UI baseline
- Google identity exchange + internal authorization mapping
- core auth/session hardening
- CI/CD and GKE deployment plumbing
- Alembic-first migration discipline

### Phase 4B (Remaining): Security And Runtime Hardening
Remaining:
- deployed-environment Redis failure-mode validation
- production fail-closed configuration enforcement
- CSP/security header verification and remediation
- deploy/image verification hardening confirmation

### Phase 4C (Remaining): Pilot Runbook And Readiness Verification
Remaining:
- pilot operational checklist completion
- environment validation sign-off (auth/session/deploy/automation)
- explicit go/no-go readiness review

## Completion Criteria (Phase 4 Pilot-Ready)
Phase 4 is complete for pilot when all of the following are true:
- operator UI, auth exchange, and internal authorization flows are validated in deployed environment
- Redis-backed rate limit and session-state behavior is validated with explicit fail-mode outcomes
- security header posture is verified and documented
- deploy pipeline uses deterministic built image refs with clear verification
- Alembic migration discipline is enforced in CI and pre-rollout flow
- pilot runbook and operational checklist are complete and reviewed

## Out Of Scope
Out of scope for this roadmap:
- browser cookie auth redesign
- full IAM redesign beyond current principal/business model
- broader production security-platform redesign (SIEM/SOAR/full compliance framework)
- major observability platform rebuild
- microservice or distributed workflow-engine migration
