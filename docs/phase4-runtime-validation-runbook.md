# Phase 4 Runtime Validation Runbook

## 1) Purpose And Scope
This runbook is the final Phase 4 runtime signoff procedure for Work Boots pilot deployments on GKE.

It validates deployed behavior for:
- CI/CD rollout and migration gates
- Redis-backed security controls
- ingress/CORS/security headers
- auth/session runtime flows
- operator UI runtime behavior

This runbook does not change architecture. It validates the existing monolith deployment and operational posture.

## 2) Preconditions
Before starting runtime validation, confirm all of the following:

- GCP project access for:
  - GKE cluster
  - Artifact Registry
  - Cloud Logging
- `kubectl` access to the target cluster/namespace.
- GitHub Actions Workload Identity Federation is configured:
  - `OIDC_WORKLOAD_IDENTITY_PROVIDER`
  - `DEPLOY_SERVICE_ACCOUNT`
- GitHub Actions deploy secrets are populated:
  - `CONTAINER_REGISTRY_REGION`
  - `CONTAINER_REGISTRY_REPOSITORY`
  - `KUBERNETES_CLUSTER_NAME`
  - `KUBERNETES_CLUSTER_LOCATION`
  - `KUBERNETES_CLUSTER_LOCATION_TYPE` (`region` or `zone`)
- Deploy workflow uses required GitHub variable `GCP_PROJECT_ID`.
- Target namespace exists:
  - dev: `work-boots-dev`
  - prod: `work-boots`
- Redis is provisioned and reachable from API pods (pilot/prod expectation).
- Database connectivity and migration permissions are valid for `alembic upgrade head`.
- Kubernetes `work-boots-secrets` is populated with required secret values.
- Frontend pipeline is green (`frontend-ci.yml`: `npm ci`, lint, typecheck, build).
- Backend pipeline is green (`backend-ci.yml`: lint/format/type checks + migration validation + tests + coverage).

Reference files:
- Deploy workflow: `.github/workflows/deploy-gke.yml`
- Base manifests: `infra/k8s/base/`
- Overlays: `infra/k8s/overlays/dev/`, `infra/k8s/overlays/prod/`
- Runtime config: `.env.example`, `app/core/config.py`

## 3) Validation Checklist Overview
Mark each item pass/fail:

- [ ] Deploy workflow completed successfully.
- [ ] Alembic migration job completed before deployment rollout.
- [ ] API and UI deployments rolled out healthy in target namespace.
- [ ] Correct API and UI image refs were deployed.
- [ ] Redis connectivity validated from API runtime.
- [ ] Redis-backed session/rate-limit backends active in pilot/prod.
- [ ] Fail-closed behavior validated (`RATE_LIMIT_FAIL_OPEN=false`, `SESSION_STATE_FAIL_OPEN=false`).
- [ ] CORS behavior validated for allowed and disallowed origins.
- [ ] Security headers validated end-to-end through ingress.
- [ ] TLS/HSTS behavior validated.
- [ ] Google exchange + `/api/auth/me` + refresh + logout flows validated.
- [ ] Unmapped/deactivated principal behavior validated.
- [ ] Operator UI runtime pages validated.
- [ ] Rollback procedure validated/documented.
- [ ] GitHub required checks enabled.

## 4) Deployment And Rollout Validation

### 4.1 Trigger deploy
Use `deploy-gke.yml` (`workflow_dispatch`) with target overlay:
- `dev` or `prod`

### 4.2 Verify overlay and namespace
Expected mapping:
- `dev` -> `work-boots-dev`
- `prod` -> `work-boots`

```bash
kubectl get ns work-boots-dev
kubectl get ns work-boots
```

### 4.3 Verify rollout health
```bash
NAMESPACE=work-boots-dev   # or work-boots
kubectl -n "$NAMESPACE" get deploy work-boots-api work-boots-ui
kubectl -n "$NAMESPACE" rollout status deploy/work-boots-api --timeout=5m
kubectl -n "$NAMESPACE" rollout status deploy/work-boots-ui --timeout=5m
kubectl -n "$NAMESPACE" get pods -l app=work-boots-api
kubectl -n "$NAMESPACE" get pods -l app=work-boots-ui
```

### 4.4 Verify deployed image refs
```bash
kubectl -n "$NAMESPACE" get deploy work-boots-api -o jsonpath='{.spec.template.spec.containers[0].image}{"\n"}'
kubectl -n "$NAMESPACE" get deploy work-boots-ui -o jsonpath='{.spec.template.spec.containers[0].image}{"\n"}'
```

Compare these refs to the deploy workflow run outputs/build logs.

### 4.5 Verify migration gate
`deploy-gke.yml` creates a pre-rollout migration Job named:
`work-boots-migrate-<github_run_id>-<github_run_attempt>`.

Check recent jobs/events:
```bash
kubectl -n "$NAMESPACE" get jobs --sort-by=.metadata.creationTimestamp
kubectl -n "$NAMESPACE" get events --sort-by=.lastTimestamp | tail -n 50
```

Pass criteria:
- Migration Job reached `Complete` before rollout image update.
- No migration errors in workflow logs or cluster events.

## 5) Redis / Security-Control Runtime Validation

### 5.1 Confirm deployed config posture
```bash
kubectl -n "$NAMESPACE" get configmap work-boots-config -o yaml
```

Validate:
- `RATE_LIMIT_BACKEND: "redis"`
- `SESSION_STATE_BACKEND: "redis"`
- `RATE_LIMIT_FAIL_OPEN: "false"`
- `SESSION_STATE_FAIL_OPEN: "false"`

Confirm `REDIS_URL` exists in `work-boots-secrets` (do not expose secret value in shared logs/screenshots).

### 5.2 Confirm runtime backend selection
Inspect API logs for backend initialization events:
- `rate_limit_backend_init ... redis_configured=... fail_open=...`
- `session_state_backend_init ... redis_configured=... fail_open=...`
- `... initialized with Redis backend`

```bash
kubectl -n "$NAMESPACE" logs deploy/work-boots-api --tail=200
```

### 5.3 Validate fail-closed behavior (dev namespace exercise)
Perform this only in non-production:

1. Intentionally break Redis connectivity in `work-boots-dev` (for example invalid `REDIS_URL` in dev secret).
2. Restart API deployment.
3. Exercise auth path (`/api/auth/google/exchange` or `/api/auth/refresh`).

Expected outcome in pilot/prod posture:
- No silent in-memory fallback for Redis-backed controls.
- Security-control path fails closed (request denied/error), and logs clearly indicate Redis backend initialization/connection failure.

Restore valid Redis config immediately after test.

## 6) Ingress / CORS / Security Headers Validation

### 6.1 Confirm expected host routing
Ingress hosts from overlays:
- dev: `dev.workboots.example.com`
- prod: `workboots.example.com`

```bash
kubectl -n "$NAMESPACE" get ingress work-boots-ingress -o yaml
```

### 6.2 Validate CORS behavior
Use API endpoint (for example `/health`) with different `Origin` headers:

```bash
API_BASE=https://dev.workboots.example.com   # or https://workboots.example.com
curl -i -H "Origin: https://dev.workboots.example.com" "$API_BASE/health"
curl -i -H "Origin: https://not-allowed.example.com" "$API_BASE/health"
```

Pass criteria:
- Allowed origin: `Access-Control-Allow-Origin` matches configured allowlist.
- Disallowed origin: no permissive wildcard behavior.

### 6.3 Validate security headers end-to-end
```bash
curl -I "$API_BASE/health"
curl -I "$API_BASE/api/auth/me"
```

Validate presence/expected behavior for:
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Content-Security-Policy` (API responses)
- `Strict-Transport-Security` where enabled

### 6.4 Validate TLS/HSTS at ingress
Pass criteria:
- TLS certificate is valid for host.
- HTTPS redirects/termination behavior is correct.
- HSTS appears where configured for pilot/prod.

If ingress layer overwrites headers, document ingress policy and keep app/ingress header policy aligned.

## 7) Auth/Session Runtime Validation
Validate with a mapped active principal identity and with negative-path users.

### 7.1 Positive path
- Sign in via Google in operator UI.
- Exchange succeeds (`POST /api/auth/google/exchange`).
- Call `/api/auth/me` with app access token and confirm principal/business context.
- Allow access token to approach expiry and validate refresh flow (`POST /api/auth/refresh`).
- Validate logout (`POST /api/auth/logout`) clears active access.

### 7.2 Negative path checks
- Unmapped Google identity: exchange is rejected.
- Deactivated principal identity: exchange/refresh is rejected.
- Deactivated principal: access is rejected for protected routes.

### 7.3 Revocation/replay checks
- After logout, old token usage should fail.
- Refresh replay/reuse should be rejected and logged/audited.

## 8) Frontend Runtime Validation
In deployed operator UI:

- [ ] Login succeeds for valid mapped principal.
- [ ] `/dashboard`, `/sites`, `/audits`, `/competitors`, `/recommendations`, `/automation` load correctly.
- [ ] Expired access token triggers refresh path correctly.
- [ ] Logout clears local session and redirects as expected.
- [ ] Unauthorized responses force session clear + login flow.

Known current posture:
- Frontend CI enforces install/lint/typecheck/build.
- No frontend automated test script is currently defined.

## 9) Failure / Rollback Guidance
If rollout fails, triage in this order:

1. Migration failure:
- Check deploy workflow migration step logs.
- Check migration Job logs/events in target namespace.

2. API/UI rollout failure:
- `kubectl describe deploy` and pod logs for `work-boots-api`/`work-boots-ui`.
- Validate image refs and pull permissions.

3. Redis-related auth/session failure:
- Confirm `REDIS_URL`, backend mode, fail-open flags.
- Check API logs for Redis backend initialization/connection errors.

4. Ingress/CORS/header issues:
- Inspect ingress resource and host rules.
- Validate live headers with `curl -I`.

Rollback baseline:
```bash
kubectl -n "$NAMESPACE" rollout history deploy/work-boots-api
kubectl -n "$NAMESPACE" rollout undo deploy/work-boots-api
kubectl -n "$NAMESPACE" rollout undo deploy/work-boots-ui
```

## 10) GitHub / Merge Protection Operational Note
Repository code cannot enforce branch protection by itself.
Enable required status checks in GitHub settings for protected branches:

- backend CI workflow/checks (`backend-ci.yml`, job `backend-tests`)
- frontend CI workflow/checks (`frontend-ci.yml`, job `frontend-validate`)
- deploy workflow/check(s) as required by team policy (`deploy-gke.yml`)

Also require pull request review and disallow direct pushes to protected branches for pilot safety.

## 11) Phase 4 Runtime Signoff Criteria
Phase 4 runtime signoff is complete only when all are true:

- [ ] Deploy workflow succeeds for target overlay.
- [ ] Alembic migration gate succeeds before rollout.
- [ ] API and UI rollouts are healthy.
- [ ] Redis-backed controls are active in pilot/prod.
- [ ] Fail-closed behavior validated for Redis security controls.
- [ ] Ingress/CORS/security headers/TLS are validated end-to-end.
- [ ] Google exchange + internal principal mapping + auth session lifecycle validated.
- [ ] Operator UI runtime flows validated.
- [ ] Required GitHub checks are enabled via branch protection.
- [ ] Critical dependency advisories that could block pilot are reviewed and dispositioned.

---

Use this runbook together with:
- `docs/phase4-platform-operationalization-roadmap.md`
- `docs/security-architecture.md`
- `docs/deployment-gke-cicd.md`
