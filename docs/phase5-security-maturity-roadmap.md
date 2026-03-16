# Phase 5 Security Maturity Roadmap

## Purpose And Scope
Phase 5 is the next security maturity phase after Phase 4 pilot operationalization.  
It focuses on strengthening production security posture without changing the core architecture or auth model.

Why separate from Phase 4:
- Phase 4 established deployability and operational controls.
- Phase 5 focuses on deeper browser/session hardening, production security controls, and validation rigor.

Architecture constraints that remain unchanged:
- FastAPI monolith
- repository/service pattern with thin routes
- business-scoped APIs and `TenantContext` tenant isolation
- internal authorization via principal/business membership and role checks
- Google used for identity proofing only
- deterministic-first SEO/recommendation pipeline
- AI limited to summarization/narrative over persisted deterministic outputs

## Current Security Baseline (Inherited From Phase 4)
Current implemented baseline:
- app-issued JWT access/refresh token model
- refresh rotation with replay detection
- explicit logout and revocation support (`POST /api/auth/logout`)
- Redis-capable revocation/session-state backend with local/dev in-memory fallback
- Redis-capable distributed rate limiting with configurable fail-open/fail-closed behavior
- JWKS-based Google ID token verification (issuer/audience/subject validation)
- internal principal/business authorization remains authoritative
- persisted auth/admin audit events (including refresh replay detection and logout events)
- API CORS allowlist + baseline security response headers (with configurable HSTS)
- CI baseline includes backend quality gates + coverage visibility and frontend lint/typecheck/build gates

## Phase 5 Workstreams

### 1) Browser Session Hardening
Target:
- move toward secure `httpOnly` refresh-token cookie flow
- keep access token handling explicit and bounded

Work items:
- design cookie-based refresh path that preserves current principal/business auth model
- define CSRF controls for cookie-based refresh/logout endpoints
- validate token lifetime and rotation policy for browser sessions
- keep phased migration path from current UI token handling

### 2) XSS Mitigation And CSP
Target:
- reduce script injection risk in operator UI and edge delivery path

Work items:
- define and enforce CSP policy for operator UI and API ingress where applicable
- verify security headers (`Content-Security-Policy`, `X-Content-Type-Options`, `Referrer-Policy`, etc.)
- minimize third-party script/dependency surface in UI auth flows
- validate UI rendering/input handling against common XSS vectors

### 3) Security Observability And Auth Event Maturity
Target:
- improve operator/security-team visibility for auth/session incidents

Work items:
- standardize auth security event taxonomy (replay, lockout-like behavior, revoke actions)
- define alertable event thresholds for replay/rate-limit anomalies
- align logs/events for Cloud Logging and SIEM ingestion
- ensure event payloads remain secret-safe

### 4) Incident Response Controls
Target:
- provide explicit, auditable response controls for account/session compromise events

Work items:
- principal-level global session revocation control
- business-level session revocation control with admin safeguards
- operator/admin runbook for security response actions
- verify revocation propagation behavior across distributed runtime

### 5) Redis Production Security Posture
Target:
- harden Redis-backed security controls for production operation

Work items:
- enforce network-level restrictions (private networking, ACL boundary expectations)
- enforce Redis auth/TLS where deployment platform supports it
- validate fail-open/fail-closed defaults by environment
- document operational requirements and failure-mode expectations

### 6) Validation And Penetration Testing
Target:
- verify security controls with repeatable adversarial tests before production expansion

Work items:
- refresh replay and token reuse test scenarios
- token theft/session hijack simulation exercises
- tenant-isolation negative-path testing across auth/session boundaries
- rate-limit bypass and distributed abuse simulation tests
- formal pen-test execution and remediation tracking

## Recommended Sequencing

### First (Pre-Production Priority)
1. Redis production security posture + fail-closed enforcement
2. CSP/security-header rollout and verification
3. incident-response session revocation controls
4. security observability baseline and alerting thresholds

### Next (Post-Pilot Feedback, Still Phase 5)
1. browser refresh-token cookie migration plan and implementation
2. expanded penetration testing and regression suite hardening
3. iterative observability refinement from pilot incident patterns

## Completion Criteria (Phase 5 Complete)
Phase 5 is complete when:
- browser/session strategy is hardened with documented CSRF-safe approach
- CSP/security headers are enforced and validated in deployed environments
- auth security events are actionable, structured, and integrated for operations
- principal/business session kill-switch controls are implemented and documented
- Redis production security requirements are enforced and verified
- pen-test and adversarial validation pass criteria are met with tracked remediation closure

## Out Of Scope
Out of scope for Phase 5:
- replacing monolith architecture
- replacing principal/business authorization model
- changing SEO.ai deterministic/AI boundaries
- broad platform re-architecture or migration to new orchestration stacks
- full IAM platform redesign
