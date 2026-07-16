# GKE Deployment And CI/CD

## Overview
Deployment targets Google Kubernetes Engine (containerd runtime) with OCI images stored in Artifact Registry.

CI/CD is implemented with GitHub Actions and Google Workload Identity Federation.
The target GKE cluster is currently managed manually outside deploy workflow execution.

Bootstrap/runbook:
- `docs/gcp-github-actions-bootstrap.md`
- `docs/deployment-configuration-contract.md` (canonical naming contract for deploy-time secrets/env/inputs)

## Kubernetes Assets

Kustomize manifests live under:
- `infra/k8s/base`
- `infra/k8s/overlays/dev`
- `infra/k8s/overlays/prod`

Base resources are namespace-neutral and include:
- API deployment + service
- Redis deployment + service (internal ClusterIP only)
- Operator UI deployment + service
- Ingress (same-host path routing: `/` -> UI, `/api` -> API)
- FrontendConfig (HTTP -> HTTPS redirect)
- ManagedCertificate (Google-managed TLS certificate)
- ConfigMap

### Production Ingress TLS Split (Authoritative `k8s/*` Path)

Production host routing is intentionally split:

- `app.mbsrn.com`:
  - Ingress: `mbsrn-ingress` (`k8s/app-ingress.yaml`)
  - Managed cert: `mbsrn-app-managed-cert` (`k8s/app-managed-certificate.yaml`)
  - FrontendConfig: `mbsrn-app-frontend-config` (`k8s/app-frontend-config.yaml`)
- `www.mbsrn.com`:
  - Ingress: `mbsrn-www-ingress` (`k8s/www-ingress.yaml`)
  - Managed cert: `mbsrn-www-managed-cert` (`k8s/www-managed-certificate.yaml`)
  - FrontendConfig: `mbsrn-www-frontend-config` (`k8s/www-frontend-config.yaml`)

Both ingresses use the GKE Ingress + ManagedCertificate model (not Gateway API).
Managed certificate binding is via ingress annotation:
`networking.gke.io/managed-certificates`.

Static IP behavior:
- app ingress (`k8s/app-ingress.yaml`) keeps explicit reserved IP annotation:
  - `kubernetes.io/ingress.global-static-ip-name: mbsrn-prod-static-ip`
- website ingress currently preserves its existing behavior and does not set a static-IP annotation in `k8s/www-ingress.yaml`.
  - If website IP pinning is required, add the known reserved IP resource name explicitly before recreating ingress resources.

Each overlay owns its namespace resource:
- `infra/k8s/overlays/dev/namespace.yaml` (`mbsrn-dev`)
- `infra/k8s/overlays/prod/namespace.yaml` (`mbsrn`)

A secret template is provided at:
- `infra/k8s/base/secrets.template.yaml`

## Build Strategy (No Docker Daemon)

Workflows use Google Cloud Buildpacks:
- `gcloud builds submit --pack image=...`
- deploy workflow passes explicit source staging dir:
  - `--gcs-source-staging-dir="${BUILD_SOURCE_DIR}"`
- API buildpack runtime is pinned via repository-root `.python-version`:
  - `3.13`
  - Google Cloud Buildpacks in this deployment path do not use `runtime.txt` for Python
    version selection; do not rely on `runtime.txt` as the API buildpack control file.
  - this avoids Buildpack auto-select drift (for example Python 3.14) that can break native
    dependencies such as `pydantic-core` / `PyO3` compatibility windows.

This produces OCI-compatible images suitable for containerd on GKE.

### Next.js Security Baseline (Self-Hosted)

MBSRN is self-hosted on GKE, so Vercel-hosted protections do not apply.

Middleware authorization bypass baseline:
- advisory: `GHSA-f82v-jwr5-mffw`
- affected pattern: authorization decisions that rely only on Next.js middleware and trust inbound
  `x-middleware-subrequest` traffic
- fixed in Next 15.x at `15.2.3+`
- baseline control: keep all self-hosted apps on patched Next 15.x and keep route/API authorization
  checks enforced server-side; middleware is defense-in-depth, not sole authorization.

For `GHSA-c4j6-fc7j-m34r` / `CVE-2026-44578` (Next.js WebSocket upgrade SSRF), treat
`>=13.4.13 <15.5.16` as affected in this deployment model.

Minimum patched baseline for MBSRN self-hosted Next.js apps:
- `next >= 15.5.16`

Pinned application versions:
- `frontend/operator-ui`
  - `next: 15.5.16`
  - `eslint-config-next: 15.5.16`
  - `react: 18.3.1`
  - `react-dom: 18.3.1`
- `frontend/www`
  - `next: 15.5.16`
  - `eslint-config-next: 15.5.16`
  - `react: 18.3.1`
  - `react-dom: 18.3.1`

Validation commands used during the upgrade:

```bash
cd frontend/operator-ui
npm install
npm ls next react react-dom eslint-config-next
npx tsc --noEmit --pretty false
npm run lint
npm test -- --runInBand middleware
npm test -- --runInBand app/admin
npm test -- --runInBand app/audits
npm test -- --runInBand app/automation
npm test -- --runInBand app/competitors
npm test -- --runInBand app/recommendations
npm test -- --runInBand
npm run build

cd ../www
npm install
npm ls next react react-dom eslint-config-next
npx tsc --noEmit --pretty false
npm run lint
npm run build
npm run validate:standalone-runtime
```

Defense-in-depth follow-up (not changed by this pass):
- if WebSocket upgrades are not required for UI/website traffic, block upgrade requests at
  the load-balancer/reverse-proxy layer
- keep egress controls conservative so pods cannot reach metadata/internal destinations
  unnecessarily (`169.254.169.254`, `metadata.google.internal`)

## GitHub Actions Workflows

- `backend-ci.yml`
  - Python dependency install
  - Alembic migration-chain validation (`alembic upgrade head`) against CI Postgres
  - CI uses ephemeral Postgres for migration validation via `postgres:16` in GitHub Actions.
  - pytest

- `frontend-ci.yml`
  - deterministic install (`npm ci`)
  - UI lint, typecheck, and production build
  - frontend test script execution only when a test script exists (none is currently defined)

- `deploy-gke.yml`
  - backend build gate:
    - install dependencies
    - pytest
    - build/push API image with Cloud Buildpacks
  - frontend build gate:
    - deterministic install (`npm ci`)
    - lint, typecheck, build
    - build/push UI image with Cloud Buildpacks
  - WIF auth to GCP
  - cluster credential retrieval
  - kustomize apply
  - Alembic migration gate (`alembic upgrade head`) before rollout
  - deployment image updates to exact image refs produced by build jobs
  - rollout verification
  - preflight `DATABASE_URL` validation via `scripts/validate_production_database_url.py`
    using `DB_CONNECTION_MODE` (default `direct`, configurable)

- `deploy-prod.yml`
  - push-to-main/workflow-dispatch production rollout path using `k8s/` manifests
  - includes explicit Redis apply for `mbsrn-redis` prior to API rollout
  - preflight `DATABASE_URL` validation via `scripts/validate_production_database_url.py`
    using `DB_CONNECTION_MODE=direct` (cloud-native Postgres production contract)

- `deploy-www-prod.yml`
  - push-to-main/workflow-dispatch production rollout path for public website only
  - builds/pushes `frontend/www` image
  - applies website-only `k8s/www-*` resources
  - keeps `app.mbsrn.com` operator deployment path isolated
  - `frontend/www` runs Next.js standalone mode; production image optimization requires `sharp` in runtime dependencies

- `deploy-datadog.yml`
  - workflow-dispatch only path for Datadog observability resources
  - authenticates with existing GCP Workload Identity and fetches GKE credentials
  - ensures namespace `datadog`
  - creates/updates Kubernetes secret `datadog-secret` in `datadog` namespace from GitHub secret `DATADOG_API_KEY`
    - secret key name: `api-key`
  - applies `k8s/datadog/datadog-agent.yaml`

### Datadog Observability Baseline

Datadog secret flow:

`GitHub secret DATADOG_API_KEY` -> `deploy-datadog.yml` -> Kubernetes secret `datadog-secret` (`api-key`) -> DatadogAgent `datadog` in namespace `datadog`.

DatadogAgent settings (authoritative manifest: `k8s/datadog/datadog-agent.yaml`):
- cluster name: `mbsrn-prod`
- Datadog site: `us3.datadoghq.com`
- secret reference only (`datadog-secret` / `api-key`)
- registry: `gcr.io/datadoghq`
- tag: `env:prod`
- features enabled:
  - cluster checks
  - orchestrator explorer
  - log collection (`containerCollectAll: true`)

Application surface boundary:
- Datadog remains an infrastructure-only implementation detail.
- Operator/admin/product UI should use neutral diagnostics labels (for example `runtime diagnostics`, `deployment telemetry`, `platform logs`) and should not expose Datadog-specific branding or status blocks.

Rotation procedure:
1. Update GitHub secret `DATADOG_API_KEY`.
2. Re-run workflow `deploy-datadog`.
3. Confirm `datadog-secret` and DatadogAgent reconcile in namespace `datadog`.

Secret handling policy:
- never commit Datadog API key values
- never print Datadog API key values in workflow logs
- never commit generated Kubernetes Secret manifests with real values

### Deployment Path Precedence
- Production-authoritative path:
  - `.github/workflows/deploy-prod.yml` + `k8s/*`
- Public-website production path:
  - `.github/workflows/deploy-www-prod.yml` + `k8s/www-*`
- Secondary/manual path:
  - `.github/workflows/deploy-gke.yml` + `infra/k8s/overlays/*`
- Session/Redis contract is standardized across both paths:
  - Redis workload/service name: `mbsrn-redis`
  - API Redis URL: `redis://mbsrn-redis:6379/0`

### GKE Resource Request Tuning (FinOps)

This section distinguishes declared (repo/workflow) resource values from admitted (live cluster) values in GKE Autopilot.

Declared/rendered source of truth for production CPU:
- `.github/workflows/deploy-prod.yml`:
  - `UI_CPU_REQUEST=100m`
  - `UI_CPU_LIMIT=500m`
  - `API_CPU_REQUEST=300m` (conservative FinOps right-size)
  - `API_CPU_LIMIT=750m` (conservative FinOps right-size)
- `.github/workflows/deploy-www-prod.yml`:
  - `WWW_CPU_REQUEST=100m`
  - `WWW_CPU_LIMIT=500m`
- Templates are rendered into:
  - `k8s/ui-deployment.yaml` (`__UI_CPU_REQUEST__`, `__UI_CPU_LIMIT__`)
  - `k8s/www-deployment.yaml` (`__WWW_CPU_REQUEST__`, `__WWW_CPU_LIMIT__`)

API FinOps note (May 30, 2026):
- Prior production API CPU request baseline was `1000m`.
- Google FinOps recommendation suggested `7m` request/limit for `mbsrn-api`.
- The raw `7m` value is intentionally not applied for production API runtime safety.
- Production deploy now uses a conservative right-size target of `300m` request / `750m` limit for `mbsrn-api`.

Observed production evidence (May 4, 2026):
- Workloads: `mbsrn-ui`, `mbsrn-www`
- Declared CPU request target: `100m`
- Live admitted CPU request: `308m`
- Live CPU limit: `500m`
- Live memory request/limit: `2Gi`
- Live ephemeral-storage request/limit: `4Gi`
- Rollout outcome at verification time: both deployments successful, healthy pods, `0` restarts observed

Interpretation:
- Google Cloud Billing/Recommender values (including very low values such as `4m`) are advisory and are not copied literally for production.
- In GKE Autopilot, admitted Pod resources can differ from declared values after admission/defaulting.
- With current memory sizing (`2Gi`), Autopilot admitted CPU request at `308m` for both UI/WWW in observed production state.
- Do not assume declared `100m` always equals live admitted `100m`.

Post-deploy verification commands (declared vs admitted):

```bash
kubectl -n mbsrn get deployment mbsrn-ui -o jsonpath='{.spec.template.spec.containers[0].resources}{"\n"}'
kubectl -n mbsrn get deployment mbsrn-www -o jsonpath='{.spec.template.spec.containers[0].resources}{"\n"}'
kubectl -n mbsrn get deployment mbsrn-api -o jsonpath='{.spec.template.spec.containers[0].resources}{"\n"}'
kubectl -n mbsrn rollout status deployment/mbsrn-ui
kubectl -n mbsrn rollout status deployment/mbsrn-www
kubectl -n mbsrn rollout status deployment/mbsrn-api
kubectl -n mbsrn get pods -l app=mbsrn-ui
kubectl -n mbsrn get pods -l app=mbsrn-www
kubectl -n mbsrn get pods -l app=mbsrn-api
kubectl -n mbsrn get events --sort-by=.lastTimestamp | grep -i -E "autopilot|resource|cpu|memory|mbsrn-ui|mbsrn-www|mbsrn-api" | tail -50
```

Future tuning note:
- Do not reduce memory blindly.
- Review Cloud Monitoring memory working set and CPU throttling over 24-72 hours before changing memory.
- If memory usage remains comfortably below `2Gi`, consider a separate conservative change to reduce memory request/limit (for example toward `1Gi`), then re-check admitted CPU after rollout.
- After API CPU right-size deployment, monitor: API latency, 5xx rate, pod restarts, CPU throttling, and migration/admin workflow response times.

### SEO Migration Managed Target Repo Contract

For migration-driven site repos, MBSRN acts as a control-plane orchestrator:

- one site targets one repo/workflow tuple in the destination repository.
- non-dry-run migration publish ensures the site workflow file exists at:
  - `.github/workflows/<workflow_id>`
- the workflow file is generated from an approved MBSRN-managed template mode (`deploy_workflow_mode`), currently `site_repo_template_v1`.
- admin-owned environment mapping metadata (`target_environment_key`, `target_environment_source`) is injected as template metadata; operators cannot edit these deploy routing controls from workspace UI.
- deploy execution remains in the target repo via GitHub Actions dispatch; MBSRN does not directly execute GKE deployment steps.

Deploy auth mode is generic and configuration-driven:
- `deploy_auth_mode=target_repo_actions_secret`
  - site-repo workflow requires `GCP_DEPLOY_KEY`.
  - deploy readiness blocks before dispatch when missing (`target_repo_deploy_secret_missing`).
  - workflow run failures with the same root cause are classified as `generated_workflow_requires_missing_gcp_deploy_key`.
- `deploy_auth_mode=control_plane_managed` or `deploy_auth_mode=github_oidc_workload_identity`
  - target-repo `GCP_DEPLOY_KEY` is not required by the workflow contract.
- deploy diagnostics/readiness expose:
  - `deploy_auth_mode`
  - `target_repo_deploy_secret_required`
  - `target_repo_deploy_secret_name`
  - `target_repo_deploy_secret_present`

Operational implication:
- a repo can contain published artifact files but is not considered deploy-ready until workflow provisioning/verification succeeds on the target ref.

### Platform-Owned Public Website Target (`www.mbsrn.com`)

Repository/domain boundary:
- control plane source repo comes from `MBSRN_CONTROL_PLANE_REPOSITORY` (`owner/repo`)
- authenticated control plane host remains `app.mbsrn.com`
- platform-owned public artifacts target repo remains a separate managed target repo from the control-plane source repo
- public marketing host target is `www.mbsrn.com`

Managed-site implications:
- use existing migration per-site publish-target configuration (owner/account from Admin baseline, repo name from workspace target)
- for the platform-owned public site target, use a dedicated artifacts repo rather than the configured control-plane source repo
- preview validation continues on managed preview hostname (`*.site.mbsrn.com`) before DNS cutover
- DNS cutover for `www.mbsrn.com` is manual and out of scope for migration publish/deploy actions

Safety reminder:
- publishing artifacts to a public-site target repo does not move control-plane source/ownership out of the configured control-plane source repo
- public artifact output must not contain control-plane routes, internal diagnostics, or secret-bearing content
- media deploy blockers are evaluated from deployable generated-package references (`assets/images/*`, unresolved `@image(...)`, unresolved `upl-...`, private/non-deployable URLs), not from selected-image productivity state alone
- when generated output includes private app/control-plane preview URLs or signed storage URLs, readiness blocks publish/deploy and diagnostics stay redacted to safe blocker categories/remediation text

### Managed Site HTTPS Readiness Diagnostics

Managed site deploy readiness requires successful HTTPS reachability, not just control-plane alignment.

Important state:
- DNS/static IP/ingress/certificate checks can all be valid while `deploy_https_ready=false`.
- In this state, deploy diagnostics should preserve bounded probe evidence in `https_probe_error_summary`.
- `deploy_https_ready=false` with blank `https_probe_error_summary` is a diagnostics regression and should trigger workflow/template verification.
- managed deploy workflow failures should always emit a final safe reason summary (`deploy_runtime_reason_code`, `deploy_runtime_reason_message`, `deploy_runtime_failure_stage`) plus bounded runtime-state evidence fields before exit.
- if GitHub shows only `Process completed with exit code 1` and run logs have no `deploy_runtime_reason_code`, treat the run as diagnostics-incomplete:
  - `runtime_readiness_unknown_failure` when managed template markers are present
  - `managed_deploy_workflow_template_stale` when managed template markers are missing
  - operator action: reprovision workflow/template files from publish, then retry deploy or inspect Advanced Diagnostics.
- selected workflow attempt outcome and current runtime outcome are distinct:
  - selected workflow failure remains historical evidence
  - current runtime state is derived from latest bounded HTTPS probe evidence when available
  - current runtime evidence precedence: `current_live_probe` -> `workflow_output` -> selected attempt -> summary fallback -> historical failure
  - refresh is scoped to the active route/workspace site id and may fall back to the latest deploy record for that site when selected artifact history is missing
- if selected workflow evidence collection failed but current live HTTPS probe succeeds, operator UI should report current runtime as healthy while preserving the failed selected attempt in history/diagnostics.
- preview endpoint-mode reconciliation rules:
  - `preview_shared_gateway`: deploy readiness validates shared preview gateway config and expected shared static-IP name for `*.site.mbsrn.com`; per-site static-IP ensure is not required.
  - `dedicated_static_ip`: static-IP ensure/describe uses bounded re-describe + list fallback before classifying `static_ip_address_missing_after_retry`; newly created per-site addresses are labeled at create time with GCP-safe ownership labels (`mbsrn-managed-by`, `mbsrn-site-id`, `mbsrn-preview-hostname`, `mbsrn-repo`).
  - list fallback succeeds only when exactly one address entry matches the expected name and includes a non-empty `address` value.
  - stale selected-attempt static-IP-missing failures remain historical context and must not override healthy current live HTTPS evidence.
- Expected reason-code families include:
  - `certificate_provisioning_pending` (static IP + ingress can be healthy while TLS still converges)
    - legacy workflow-log/history aliases remain read-compatible: `managed_certificate_provisioning`, `tls_certificate_provisioning`, `managed_certificate_pending`, `runtime_ready_tls_pending`
  - `https_probe_failed_after_control_plane_ready`
  - `https_probe_timeout`
  - `https_probe_empty_reply`
  - `https_probe_not_attempted`
  - `ingress_backend_502` (kept distinct when backend returns 502)

Typical causes:
- backend service endpoints are not ready
- BackendConfig health checks do not match runtime behavior
- site runtime is not yet serving `/` successfully
- external load balancer convergence lag

`certificate_provisioning_pending` interpretation:
- static IP can be `IN_USE` and ingress IP can already match the reserved address while certificate remains `PROVISIONING`.
- in this state, HTTPS probe failures are usually a downstream symptom of TLS convergence and should not be classified as backend 502 or app runtime failure.
- control plane probes the deterministic ManagedCertificate name for the site before workflow dispatch (`expected_managed_certificate_name`), and reconcile/apply remains idempotent for that same name across retries.
- `observed_pre_shared_cert_annotation` is controller metadata only and not the source-of-truth binding decision for managed deployments.
- runtime and TLS are tracked separately in readiness:
  - `certificate_readiness_state=certificate_provisioning_pending`
  - `runtime_ready_tls_pending=true` when LB/runtime evidence is present but HTTPS is still pending
  - `https_ready=false` until certificate converges and HTTPS probe succeeds
- when endpoint mode requires HTTPS-ready certificate before dispatch (for example dedicated/static-IP mode), deploy readiness blocks with a certificate gate and does not dispatch another run until cert is `ACTIVE`.
- HTTPS-required gate copy: `Certificate exists but is still provisioning. Deploy is held until the certificate is ACTIVE.`
- when endpoint mode is preview-tolerant (`preview_shared_gateway`), runtime can remain deployable while TLS is pending; UI shows this as a wait-state, not as runtime-replace failure.
- preview-tolerant copy: `Runtime can deploy while HTTPS certificate provisioning continues.`
- missing ManagedCertificate objects, FAILED_NOT_VISIBLE states, certificate/domain mismatch, and DNS mismatch remain distinct blocker states and are not normalized into provisioning.
- next action: wait for ManagedCertificate to reach `ACTIVE`, then refresh/rerun deploy.

`ingress_backend_502` interpretation:
- deploy success still requires preview HTTPS to return non-5xx; backend health alone is not sufficient.
- runtime diagnostics include bounded 502 context fields:
  - `gce_backend_health_status` (`HEALTHY|UNHEALTHY|UNKNOWN`)
  - `k8s_endpoint_ready` (`true|false`)
  - `preview_https_status` + probe attempt/elapsed wait
  - `service_probe_status` + `in_cluster_service_status_code`
  - `endpoint_probe_status` + `endpoint_probe_status_code`
  - `runtime_probe_status` (`ingress_or_edge_convergence|app_runtime_response_502|pod_runtime_failure|service_probe_failed|unknown`)
- split guidance:
  - service/endpoint probes `ok` + preview HTTPS `502` + backend `HEALTHY` => ingress/LB edge convergence or stale backend path.
  - service/endpoint probes `http_502` => app runtime also returning 502.
  - pod restart/crash evidence => pod runtime instability.

Common managed-site deploy blocker codes:
- `repo_adoption_required` / `github_repo_adoption_required`
- `workflow_provisioning_failed`
- `workflow_file_missing`
- `workflow_disabled`
- `workflow_dispatch_missing`
- `workflow_dispatch_rejected`
- `target_repo_deploy_secret_missing`
- `generated_workflow_requires_missing_gcp_deploy_key`
- `shared_preview_gateway_missing`
- `shared_preview_gateway_hostname_missing`
- `static_ip_address_missing_after_retry`
- `address_not_found_after_retry`
- `address_ambiguous_after_retry`
- `address_value_missing_after_retry`
- `ingress_static_ip_conflict`
- `workflow_run_failed_without_live_url_evidence`

Dispatch/run-evidence classification notes:
- `dispatch_accepted_no_run` / `dispatch_unverified_no_run` means GitHub accepted dispatch transport but workflow run evidence is still pending.
- explicit dispatch rejection reason codes (`workflow_dispatch_rejected`, `workflow_dispatch_not_supported`, `workflow_disabled`, `workflow_dispatch_missing`) are classified as dispatch-blocked target failures, not no-run uncertainty.

Endpoint mode/template guidance:
- changing `managed_preview_endpoint` admin defaults requires rerunning publish/workflow provisioning and then rerunning deploy so target-repo workflow env/manifests are regenerated with the updated endpoint mode.
- target repository deploy workflows must also be reprovisioned after managed deploy workflow template changes so new failure-summary logic and diagnostics markers are present.
- `mbsrn_managed_deploy_template_version` is a diagnostics marker only; it does not gate publish/deploy execution by itself.

Scoped fresh redeploy (`replace_existing_runtime`) guidance:
- deploy UI exposes an explicit per-attempt option: `Replace existing managed-site runtime before deploy`.
- when enabled, managed workflow runs namespace/site-scoped cleanup before `kubectl apply` and then recreates runtime resources from current managed manifests.
- after apply (and before ingress/TLS wait loops), workflow now verifies required runtime resources exist:
  - required always: `deployment/site-web`, `service/site-web`
  - required when rendered/referenced by manifests: `ingress/site-web`, `ManagedCertificate`, `FrontendConfig`, `BackendConfig`
  - if `service/site-web` exists but has no ready endpoint addresses after apply/rollout, workflow fails before ingress readiness with an explicit endpoint-missing reason.
- scoped cleanup targets managed runtime resources only:
  - `ingress/site-web`
  - preview `managedcertificate`
  - preview `frontendconfig`
  - preview `backendconfig`
  - `service/site-web`
  - `deployment/site-web`
  - site-scoped `networkpolicy` (selector: `app.kubernetes.io/managed-by=mbsrn,mbsrn.io/site-id=<site-id>`)
- this option does **not** delete:
  - GitHub repositories or published artifact commits
  - migration artifacts/media/business/site records
  - global static IP resources (manual/admin cleanup remains separate)
- diagnostics/reason codes:
  - `legacy_runtime_replacement_required`
  - `managed_site_runtime_replace_requested`
  - `managed_site_runtime_replace_completed`
  - `managed_site_runtime_replace_failed`
  - `runtime_deployment_missing_after_apply`
  - `runtime_service_missing_after_apply`
  - `runtime_ingress_missing_after_apply`
  - `runtime_managed_certificate_missing_after_apply`
  - `runtime_frontend_config_missing_after_apply`
  - `runtime_backend_config_missing_after_apply`
  - `runtime_service_endpoints_missing_after_apply`
- classification distinction:
  - missing ManagedCertificate object after apply is a manifest/apply failure
  - ManagedCertificate `PROVISIONING` is TLS convergence pending (not missing-resource failure)
  - missing ManagedCertificate object before dispatch is a certificate-resource blocker (`managed_certificate_failed_not_visible` / `certificate_resource_missing`) and is distinct from provisioning wait-state
  - missing `service/site-web` after apply is a runtime apply failure (not TLS pending)

### Admin Permanent Site Delete

Admin Site Registry permanent delete is now a separate guarded control-plane workflow and is distinct from deploy-time `replace_existing_runtime`.

- Deactivate/archive vs permanent delete:
  - deactivation keeps site, migration, audit, recommendation, and deploy metadata intact
  - permanent delete hard-deletes the site row and site-owned control-plane records
- Permanent delete flow is always multi-stage:
  1. prepare delete plan
  2. admin review
  3. exact confirmation phrase entry
  4. explicit execution request
  5. per-resource result summary
- External cleanup options default off:
  - generated GitHub repo delete
  - verified managed GKE/runtime resource delete
  - verified managed DNS/static-IP/certificate delete
- Ownership checks before external delete:
  - GitHub repo must match the configured owner/name, must not match the protected control-plane repo from `MBSRN_CONTROL_PLANE_REPOSITORY`, and must have a valid MBSRN management/adoption marker for the selected business/site
  - runtime resources must be in the derived namespace and carry site labels such as `app.kubernetes.io/managed-by=mbsrn`, `mbsrn.io/site-id`, `mbsrn.io/repo`, and `mbsrn.io/preview-hostname`
  - DNS delete requires exact expected hostname/type/value match
  - static-IP delete requires exact expected project/name plus verified site ownership before delete is attempted
  - preferred static-IP ownership proof is exact MBSRN/site label match when present on the address:
    - legacy/compatibility keys: `app.kubernetes.io/managed-by`, `mbsrn.io/site-id`, `mbsrn.io/repo`, `mbsrn.io/preview-hostname`
    - new GCP-safe address-label keys for create-time dedicated IP ownership: `mbsrn-managed-by`, `mbsrn-site-id`, `mbsrn-preview-hostname`, `mbsrn-repo`
  - legacy/unlabeled static IPs fall back only when the exact derived static-IP name, exact preview-hostname DNS A record, and exact observed IP all agree and no other site configuration references the same IP or preview hostname
  - shared preview gateway IPs, in-use IPs, conflicting references, and unverified ownership states are skipped rather than deleted during per-site cleanup
  - admin delete-plan and execution results surface safe static-IP diagnostics for operator review:
    - `static_ip_ownership_status`: `verified`, `unverified`, `shared`, `in_use`, `conflicting_reference`, `not_found`, `unknown`
    - `static_ip_ownership_method`: `labels`, `dns_fallback`, `none`, `not_applicable`
    - `static_ip_delete_selected`, `static_ip_delete_attempted`, `static_ip_delete_reason_code`, `static_ip_delete_safe_summary`
  - admin UI copy is intentionally concise:
    - `Verified by labels.` is the preferred ownership proof path
    - `Verified by DNS/name fallback.` is legacy compatibility evidence only
    - `Skipped: ownership unverified.`, `Skipped: shared preview gateway.`, `Skipped: IP is in use.`, and `Skipped: referenced by another site/config.` explain why delete was not attempted
    - `Not found.` and `Delete failed.` are surfaced separately in per-resource execution results
  - existing static IPs are not backfilled or mutated in this pass; deploy-time static-IP ensure/readiness behavior is otherwise unchanged
  - ManagedCertificate delete requires exact namespace/name plus site ownership labels
- Protected repo guard config:
  - `MBSRN_CONTROL_PLANE_REPOSITORY` must be set to `owner/repo`
  - if unset, runtime uses the current compatibility fallback so the existing protected control-plane repo remains blocked
  - malformed values fail closed during runtime configuration validation
- The admin permanent-delete workflow does **not** automatically delete:
  - the configured protected control-plane repo
  - arbitrary customer/unmanaged repos
  - unrelated cluster-wide resources
  - shared preview gateway static IPs
  - source-site URLs or the original customer website
- Active-site guardrail:
  - active sites require deactivation first or an explicit `force_delete_active` confirmation during execution
- Failure behavior:
  - external cleanup is not transactional with database delete
  - if external cleanup partially succeeds and DB delete later fails, result code `site_delete_db_failed_after_external_cleanup` is returned and manual remediation is required
  - runbook for `site_delete_db_failed_after_external_cleanup`:
    - review the response `external_resources`, `blockers`, and `warnings` first; they describe what changed before the DB failure
    - verify each reported GitHub/GKE/DNS/static-IP/certificate state in the provider before retrying any cleanup step
    - clear the remaining DB-side blocker, then rerun delete only for unfinished safe targets or reconcile the site manually
  - per-resource results distinguish `deleted`, `skipped`, `blocked`, `failed`, `not_found`, and `not_checked`

`SITE_WEB_IMAGE_TAG` diagnostics:
- empty `SITE_WEB_IMAGE_TAG` is allowed for managed workflows and falls back to `${GITHUB_SHA}`.
- workflow outputs now include `site_runtime_image_tag_source` (`github_sha_fallback`, `configured_sha`, `configured_latest`, `configured_invalid_fallback_latest`) so rollout evidence shows the effective tag source.

Safe verification commands:

```bash
kubectl -n <namespace> get ingress
kubectl -n <namespace> get service site-web -o wide
kubectl -n <namespace> get endpoints site-web
kubectl -n <namespace> get endpointslice -l kubernetes.io/service-name=site-web -o wide
kubectl -n <namespace> get pods -l app.kubernetes.io/name=site-web -o wide
kubectl -n <namespace> describe pods -l app.kubernetes.io/name=site-web
kubectl -n <namespace> logs -l app.kubernetes.io/name=site-web --tail=200 --all-containers=true
kubectl -n <namespace> logs -l app.kubernetes.io/name=site-web --previous --tail=100 --all-containers=true
kubectl -n <namespace> get deploy site-web -o yaml
kubectl -n <namespace> get rs -l app.kubernetes.io/name=site-web -o wide
kubectl -n <namespace> get events --sort-by=.lastTimestamp
kubectl -n <namespace> describe ingress site-web
kubectl -n <namespace> describe backendconfig site-web-backend-config-<site>
kubectl -n mbsrn-www describe managedcertificate site-web-preview-cert-mbsrn-www
kubectl -n mbsrn-www describe ingress site-web
gcloud compute addresses describe site-web-preview-ip-mbsrn-www --global
curl -Iv https://<preview-host>/
```

### Runtime Error Noise Classification

Treat the following production log patterns as expected noise unless correlated with user-visible failures:

- API (`mbsrn-api`) lifespan shutdown cancellation:
  - stack traces rooted at `uvicorn/lifespan/on.py` with `asyncio.exceptions.CancelledError`
  - expected during pod termination/restart while ASGI lifespan receives cancellation
  - should not be treated as an application startup failure by itself
  - non-cancellation lifespan failures and other startup/shutdown exceptions remain error-visible
  - startup marker for filter install:
    - `api_lifespan_cancelled_error_filter_installed target_loggers=uvicorn.error,uvicorn`
  - suppression targets Uvicorn logging records for lifespan `CancelledError`, including traceback-text shaped records
  - suppression scope is logging-record based; if a runtime emits direct stderr tracebacks outside logging, those lines can still appear and should be interpreted as shutdown-noise unless correlated with readiness/startup failure.
- Next.js (`mbsrn-ui`, `mbsrn-www`) malformed multipart parse:
  - `Error: Unexpected end of form`
  - commonly caused by aborted/malformed multipart requests (for example, bot traffic or client disconnects)
  - classify as request-noise unless tied to a specific failing route and reproducible user flow

Operator UI/runtime diagnostics hardening:

- Route/global error boundaries log bounded fields only:
  - pathname when available
  - digest when available (or `unavailable`)
  - short message classification
- Next middleware blocks stale non-API `next-action` mutating requests with `409` and bounded classification:
  - classification: `stale_server_action_build_mismatch`
  - operator recovery: refresh/reload the tab after deployment to pick up the current build
  - `/api` and `/api/*` requests are not remapped by this guard
- Public WWW middleware blocks unsupported non-API mutating traffic before Next Server Action resolution:
  - multipart (`POST|PUT|PATCH`) -> `415` with event `blocked_unsupported_multipart_request`
  - non-multipart `POST` -> `405` with event `blocked_unsupported_public_post_request`
  - `/api` and `/api/*` remain pass-through for runtime handlers
- Controlled middleware rejections are expected to emit single-line structured stdout logs with stable fields (`component`, `event`, `method`, `pathname`, `classification`, and `app_version`; stale-action rejects include `refresh_required=true`).
  - `stale_server_action_build_mismatch` is expected deploy/client skew and should be INFO (or WARN only with explicit rate context), not ERROR.
  - `blocked_unsupported_multipart_request` on `mbsrn-www` is usually scanner/bot invalid traffic.
- Native Next.js server-action lookup failures remain actionable until early blockers absorb the traffic:
  - `Failed to find Server Action "...". This request might be from an older or newer deployment.`
- Cloud Logging triage:
  - controlled rejects should not page.
  - native Next Server Action failures should be investigated.
- Never log request/form bodies, auth headers, cookies, tokens, or provider payloads.

## Required GitHub Secrets/Variables

GitHub variable:

- `GCP_PROJECT_ID` (for example `mbsrn`)

- `CONTAINER_REGISTRY_REGION`
- `CONTAINER_REGISTRY_REPOSITORY`
- `BUILD_SOURCE_DIR`
- `OIDC_WORKLOAD_IDENTITY_PROVIDER`
- `DEPLOY_SERVICE_ACCOUNT`
- `KUBERNETES_CLUSTER_NAME`
- `KUBERNETES_CLUSTER_LOCATION`
- `KUBERNETES_CLUSTER_LOCATION_TYPE` (`region` or `zone`)

Notes:
- `GCP_PROJECT_ID` in `deploy-gke.yml` is sourced from GitHub variable `GCP_PROJECT_ID` and is required.
- WIF auth uses `google-github-actions/auth@v3` with:
  - `workload_identity_provider: ${{ secrets.OIDC_WORKLOAD_IDENTITY_PROVIDER }}`
  - `service_account: ${{ secrets.DEPLOY_SERVICE_ACCOUNT }}`
- Deploy validates cluster target and fails fast before `get-credentials` if the cluster is missing.
- Deploy never creates foundational infrastructure (cluster/repository/WIF).
- Docker Hub secrets are not required for backend CI Postgres pulls in this repo.
- If your org later introduces Docker Hub auth for other workflows, use Docker Hub username + PAT (`DOCKERHUB_TOKEN`), not account password.

## Runtime Configuration

Kubernetes ConfigMap handles non-secret environment values.

Env rendering rule:
- every Kubernetes `env` entry must render from exactly one source (`value` or `valueFrom`, never both)
- optional blank literals must be omitted rather than rendered as an empty `value` alongside `valueFrom`

Schema management policy:
- Application startup does not manage production schema evolution.
- `DB_AUTO_CREATE_LOCAL` is a local/dev/test convenience guard only.
- CI and GKE deploy pipeline run Alembic migrations (`alembic upgrade head`) before rollout.

Kubernetes Secret handles sensitive values including:
- `DATABASE_URL` (recommended for production instead of ConfigMap default)
- `API_TOKEN_HASH_PEPPER`
- `APP_SESSION_SECRET`
- `GOOGLE_OIDC_CLIENT_ID`
- `GOOGLE_OIDC_CLIENT_SECRET`
- `GOOGLE_OAUTH_CLIENT_ID`
- `GOOGLE_OAUTH_CLIENT_SECRET`
- `GOOGLE_OAUTH_TOKEN_ENCRYPTION_KEYS_JSON`
- `GOOGLE_PLACES_API_KEY` (optional but recommended for Google Places seed discovery)
- provider credentials (Twilio/SMTP) when enabled

`mbsrn-secrets` is required by both API/UI Deployments and migration Job (`envFrom.secretRef`).

Environment DB mode matrix:
- local/dev/test/ci (`APP_ENV` local-like):
  - local Postgres is allowed
  - localhost `DATABASE_URL` fallback is allowed
- production via `.github/workflows/deploy-prod.yml`:
  - `DB_CONNECTION_MODE=direct` is required
  - cloud-native Postgres target is required (non-loopback)
  - Cloud SQL preflight is not part of this branch
- optional proxy-backed deployments (non-default):
  - `DB_CONNECTION_MODE=cloudsql_proxy`
  - Cloud SQL-specific preflight/diagnostics can apply

Database URL safety contract:
- `APP_ENV` is the sole authority for localhost database safety checks.
- Localhost (`localhost`, `127.0.0.1`, `::1`) is allowed only when `APP_ENV` is one of:
  - `local`
  - `development`
  - `dev`
  - `test`
  - `ci`
- `APP_ENV=production` requires `DATABASE_URL` and rejects localhost targets at startup:
  - `localhost`
  - `127.0.0.1`
  - `::1`
- Production localhost exception is narrow and explicit:
  - localhost/loopback `DATABASE_URL` is allowed only when `DB_CONNECTION_MODE=cloudsql_proxy`
  - this is intended only for optional proxy-backed paths, not `deploy-prod.yml`
- Unknown or unset `APP_ENV` values reject localhost targets and require an explicit non-localhost `DATABASE_URL`.
- API startup performs a bounded connectivity check:
  - default mode: single `SELECT 1` attempt, then fail fast
  - `APP_ENV=production` + `DB_CONNECTION_MODE=cloudsql_proxy` + localhost target:
    bounded retry window (15 attempts, 1s delay) before failing
  - this retry path is for optional proxy-backed runtime only
- Startup logs emit sanitized DB target only (no credentials):
  - `Database target resolved: host=<host>, port=<port>`
- Schema readiness expectation is resolved from Alembic head at runtime (current repo head: `0039_competitor_domain_verification_status`).
- Production startup verification logs:
  - `Startup schema readiness expectation ... expected_revision=0039_competitor_domain_verification_status ...`
  - `Startup database connectivity check using cloudsql proxy retry budget ...` (only for proxy-backed localhost mode)
  - `Startup database connectivity check succeeded ... proxy_retry_path_entered=<bool> recovered_after_retry=<bool>`
  - `Schema readiness passed expected=... current=...`
- Direct Cloud SQL transient restart/update behavior:
  - during Cloud SQL UPDATE/maintenance windows (especially ZONAL instances), short connection closures can occur while the instance restarts
  - `/healthz` readiness still returns `503` while schema query is unavailable, but readiness classification includes bounded reason `db_readiness_connection_closed` when the connection is closed unexpectedly
  - readiness performs one bounded re-check after a transient connection-closed failure and disposes the SQLAlchemy pool before retry
  - this does not change direct-mode semantics (`DB_CONNECTION_MODE=direct` remains cloud-native/private-IP without Cloud SQL Proxy dependency)

### Production DATABASE_URL Source Of Truth (`deploy-prod.yml` path)
- Production-authoritative deploy path (`.github/workflows/deploy-prod.yml` + `k8s/*`) sources
  `DATABASE_URL` from GitHub secret `DATABASE_URL`.
- `deploy-prod.yml` enforces `DB_CONNECTION_MODE=direct` and treats any other mode as invalid.
- GitHub Actions config requirement for production:
  - repo variable `DB_CONNECTION_MODE` must be unset (workflow default remains `direct`) or explicitly `direct`
  - `cloudsql_proxy` in `deploy-prod.yml` is an invalid configuration and will fail fast with `production_db_mode_invalid`
- Cloud SQL instance inspection is not part of the `deploy-prod.yml` path.
- Deploy creates/updates Kubernetes secret `mbsrn-api-auth` with key `DATABASE_URL`.
- API runtime consumes `DATABASE_URL` only via:
  - `k8s/api-deployment.yaml` -> `env.valueFrom.secretKeyRef(name=mbsrn-api-auth,key=DATABASE_URL)`
- Production runtime wiring in manifests is explicit:
  - `APP_ENV=production`
  - `DB_CONNECTION_MODE=direct`
  - `DATABASE_URL` from `mbsrn-api-auth.DATABASE_URL`
- Migration and retention jobs consume the same secret/key wiring:
  - `k8s/api-migration-job.yaml`
  - `k8s/api-migration-baseline-job.yaml`
  - `k8s/api-seo-competitor-profile-retention-cronjob.yaml`
- `deploy-prod.yml` fails fast when:
  - `DB_CONNECTION_MODE` is not `direct` (`production_db_mode_invalid`)
  - rendered API manifest does not wire `DATABASE_URL` via `secretKeyRef`
  - rendered API manifest contains a literal `DATABASE_URL` value
- Accepted production `DATABASE_URL` forms for `deploy-prod.yml` direct mode include non-loopback host targets such as:
  - in-cluster service DNS:
    - `postgresql+psycopg://<user>:<password>@<postgres-service>.<namespace>.svc.cluster.local:5432/<database>`
  - managed/external Postgres endpoint:
    - `postgresql://<user>:<password>@<managed-postgres-hostname>:5432/<database>`
- Rejected in `deploy-prod.yml` direct mode:
  - localhost/loopback targets (`localhost`, `127.0.0.1`, `::1`)
  - Cloud SQL proxy localhost assumptions
- `deploy-prod.yml` validates the effective connection target host/socket path and rejects loopback.

### Shared DATABASE_URL Validation Policy (Both Deploy Workflows)
- Both `.github/workflows/deploy-prod.yml` and `.github/workflows/deploy-gke.yml`
  call the shared validator:
  - `python scripts/validate_production_database_url.py --env-var DATABASE_URL --db-connection-mode-env-var DB_CONNECTION_MODE`
- Effective policy is mode-aware and matches runtime safety intent:
  - loopback rejected unless `DB_CONNECTION_MODE=cloudsql_proxy`
  - remote host allowed
  - socket-style cloud-native URL forms allowed
  - unknown `DB_CONNECTION_MODE` rejected
- `deploy-prod.yml` enforces `DB_CONNECTION_MODE=direct` to keep production on cloud-native Postgres.
- Recommended `deploy-gke.yml` default is `DB_CONNECTION_MODE=direct`; set `cloudsql_proxy`
  only when that deployment path is intentionally proxy-backed.

### Rollout Diagnostics For DATABASE_URL Wiring
On `mbsrn-api` rollout failure, `deploy-prod.yml` now emits safe diagnostics (no secret values):
- `mbsrn-api` env var names and source type (literal / `secretKeyRef` / `configMapKeyRef`)
- explicit `DATABASE_URL` env source classification
- secret/key presence check for `mbsrn-api-auth.DATABASE_URL`
- deployment describe + pod listing + recent API logs for context
- env-source rendering is produced by `scripts/print_api_env_wiring.py` (no inline heredoc parsing)
- Preflight database diagnostics include:
  - parsed scheme
  - effective target source classification (`url:hostname`, `query:host`, `query:unix_sock`, etc.)
  - query parameter presence/keys
  - socket-style detection
  - loopback detection result
  - final accept/reject result

### Quick Triage: Production DB Mode Mismatch
If API startup fails with:

- `Startup database connectivity check failed`
- `connection to server at "127.0.0.1", port 5432 failed: Connection refused`

validate the production DB path in this order:

1. `deploy-prod.yml` must run with:
   - `APP_ENV=production`
   - `DB_CONNECTION_MODE=direct`
2. `DATABASE_URL` must resolve to a non-loopback target for direct mode.
   - If validation reports `target_kind=loopback_host`, update the production `DATABASE_URL` value to a non-loopback service/hostname.
3. Confirm `mbsrn-api-auth` has `DATABASE_URL` and rendered manifests wire it by `secretKeyRef`.
4. If `production_db_mode_invalid` appears, correct the repo variable `DB_CONNECTION_MODE` to `direct`.
   - deploy logs now include a warning line with the received mode and source classification (`repo_variable` vs `workflow_default_direct`).
5. Confirm API startup diagnostics show sanitized DB target and mode:
   - `app_env`, `db_connection_mode`, host/port classification.

The API startup check retry path for proxy-backed localhost mode applies only to optional `DB_CONNECTION_MODE=cloudsql_proxy` deployments (for example, a consciously configured `deploy-gke.yml` path). It is not the standard `deploy-prod.yml` production contract.

### Where To Update Production `DATABASE_URL`
- Source of truth for `deploy-prod.yml`: GitHub Actions **repo secret** `DATABASE_URL`.
- Flow:
  1. update GitHub repo secret `DATABASE_URL` to the intended non-loopback production endpoint value
  2. run `deploy-prod.yml`
  3. workflow writes secret value into Kubernetes secret `mbsrn-api-auth` key `DATABASE_URL`
  4. API + migration jobs consume `mbsrn-api-auth.DATABASE_URL` via `secretKeyRef`

### Legacy Optional Cloud SQL Proxy Diagnostic Path
Use this sequence only when a deployment is intentionally configured for `DB_CONNECTION_MODE=cloudsql_proxy` and API startup still fails after retry budget exhaustion.

1. Inspect sidecar logs directly:

```bash
kubectl logs -n mbsrn deployment/mbsrn-api -c cloud-sql-proxy --tail=200
```

2. Verify pod/container health and restart behavior:

```bash
kubectl get pods -n mbsrn -o wide
kubectl describe pod <pod_name> -n mbsrn
```

3. Verify deployed proxy args and expected port wiring:

```bash
kubectl -n mbsrn get deploy mbsrn-api -o yaml | sed -n '/name: cloud-sql-proxy/,$p'
```

Expected key args:
- `--port=5432`
- `<instance-connection-name>` (resolved from `CLOUD_SQL_INSTANCE_CONNECTION_NAME`)

4. Verify in-pod listener state:

```bash
kubectl exec -it <pod_name> -n mbsrn -- sh -c "netstat -tlnp || ss -tlnp"
```

Expected:
- listener on `127.0.0.1:5432` (or `0.0.0.0:5432` in equivalent proxy mode)

5. Verify Cloud SQL env injection in the running pod:

```bash
kubectl exec -it <pod_name> -n mbsrn -- env | grep CLOUD_SQL
```

Expected:
- `CLOUD_SQL_INSTANCE_CONNECTION_NAME` present and non-empty

6. Verify runtime identity has Cloud SQL client permission:

```bash
gcloud projects get-iam-policy mbsrn-prod \
  --flatten="bindings[].members" \
  --format="table(bindings.role, bindings.members)" \
  | grep mbsrn-api
```

Expected:
- runtime GSA used by `mbsrn-api` has `roles/cloudsql.client`

#### Error → Likely Cause Mapping
- `cloud-sql-proxy` container CrashLoopBackOff + logs show credential/permission errors:
  - Workload Identity mapping missing on KSA, or runtime GSA missing `roles/cloudsql.client`
- logs show invalid/unknown instance connection name:
  - bad `CLOUD_SQL_INSTANCE_CONNECTION_NAME` secret value or wrong project/region/instance tuple
- sidecar running but no `:5432` listener:
  - proxy args/flags malformed or startup fatal before bind
- sidecar running with listener but app still gets refusal:
  - wrong target host/port in effective `DATABASE_URL`, or app container not sharing expected pod net namespace (rare; validate manifest/runtime)

Keep diagnostics sanitized:
- do not print DB credentials
- log host/port and mode only

### Distinguish Proxy-Health Failures From Rollout/Capacity Churn
Recent production evidence confirmed an important split:

- Proxy-health path can be fully healthy (`cloud-sql-proxy` auth/listen/accepted connections),
  while rollout still shows transient readiness failures due to scheduling pressure and
  replacement timing.

Treat these as separate failure classes:

1. Proxy-health failure:
   - proxy container cannot authenticate/start/listen/connect
2. Rollout/resource-pressure churn:
   - events show `FailedScheduling` (`Insufficient cpu/memory`) and transient readiness probe
     connection-refused on newly replaced API pods

When diagnosing rollout churn, capture pod-specific previous logs (not deployment aggregate logs):

```bash
kubectl get pods -n mbsrn -l app=mbsrn-api -o wide
kubectl describe pod <failing-api-pod> -n mbsrn
kubectl logs -n mbsrn pod/<failing-api-pod> -c mbsrn-api --previous --tail=300
kubectl logs -n mbsrn pod/<failing-api-pod> -c cloud-sql-proxy --previous --tail=300
kubectl get events -n mbsrn --sort-by=.metadata.creationTimestamp | tail -n 150
```

Correlation guidance:
- If proxy previous logs still show healthy auth/listen and accepted local connections,
  but events show scheduling pressure/readiness churn, prioritize rollout/capacity tuning
  over DB/proxy changes.
- If proxy previous logs show auth/instance/bind errors, follow the proxy-health path above.

Important separation:
- `mbsrn-seo-competitor-profile-retention` `StartError` triage is a separate operational issue
  and should not be used as evidence for API rollout DB/proxy regressions.
- CronJob `StartError` with `exec: "python"`/`exec: "python3": executable file not found in $PATH`
  indicates command/runtime mismatch for the buildpack API image (not DB/proxy failure).
  - production path uses Cloud Buildpacks + Procfile process shims; retention CronJob should run
    `/cnb/process/seo-competitor-profile-retention`, not bare interpreter binaries.

Production-authoritative path (`deploy-prod.yml` + `k8s/*`) injects `GOOGLE_PLACES_API_KEY` into
Kubernetes Secret `mbsrn-api-auth`, and API runtime consumes it via
`valueFrom.secretKeyRef` as `GOOGLE_PLACES_API_KEY`.

Search Console runtime wiring in the same production-authoritative path:

- `SEARCH_CONSOLE_CREDENTIALS_JSON` is injected into `mbsrn-api-auth` (from GitHub secret scope).
- `k8s/api-deployment.yaml` consumes `SEARCH_CONSOLE_CREDENTIALS_JSON` via `valueFrom.secretKeyRef`.
- `SEARCH_CONSOLE_CREDENTIALS_JSON` is optional; when omitted, runtime ADC fallback is used.
- Search Console property URL enablement is configured per-site in application data (`seo_sites.search_console_property_url` + `search_console_enabled`), not as app-global env.

GA4 runtime wiring in the same production-authoritative path:

- `GA4_CREDENTIALS_JSON` is injected into `mbsrn-api-auth` (from GitHub secret scope).
- `k8s/api-deployment.yaml` consumes `GA4_CREDENTIALS_JSON` via `valueFrom.secretKeyRef`.
- `GA4_CREDENTIALS_JSON` is optional; when omitted, runtime ADC fallback is used.
- `GA4_PROPERTY_ID` remains optional in discovery-first onboarding mode:
  - account discovery can run without it
  - site-level traffic summary requires a configured property id
- GA4 onboarding state is persisted per-site in application data (`seo_sites.ga4_*` fields), not as app-global property binding.

Session backend behavior:
- Supported backends: `SESSION_STATE_BACKEND=auto|redis|inmemory`.
- Redis-backed session state is required for correctness in multi-replica production.
- Redis is deployed in-cluster by manifests:
  - `infra/k8s/base/redis-deployment.yaml`
  - `infra/k8s/base/redis-service.yaml`
  - API runtime uses `REDIS_URL=redis://mbsrn-redis:6379/0`
- In-memory session state is process-local and non-shared across replicas; it is acceptable for local/dev/test only.
- `SESSION_STATE_ALLOW_INMEMORY_FALLBACK` controls whether in-memory fallback is allowed when Redis is unavailable/misconfigured.
- Production/staging fallback to in-memory emits degraded runtime logs:
  - `event=session_state_backend_selection ... selected_backend=inmemory ... degraded_mode=True`
- Operators should verify production pods are selecting `selected_backend=redis`.

Session production readiness checklist:
- `SESSION_STATE_BACKEND=redis`
- API pods resolve in-cluster Redis service (`mbsrn-redis:6379`)
- `SESSION_STATE_FAIL_OPEN=false`
- `SESSION_STATE_ALLOW_INMEMORY_FALLBACK=false`
- `mbsrn-redis` Deployment/Service are present in target namespace
- Startup/steady-state logs include:
  - `event=session_state_backend_selection ... selected_backend=redis`
- No production/staging logs with:
  - `event=session_state_backend_selection ... selected_backend=inmemory ... degraded_mode=True`

### Redis-Backed Session Verification (Production-Authoritative Path)
Use the namespace configured for `deploy-prod.yml` (`K8S_NAMESPACE`; currently `mbsrn`).

1. Verify Redis workload and service are present/running:

```bash
kubectl -n <namespace> get deploy mbsrn-redis
kubectl -n <namespace> rollout status deploy/mbsrn-redis --timeout=120s
kubectl -n <namespace> get svc mbsrn-redis
kubectl -n <namespace> get pods -l app=mbsrn-redis -o wide
```

2. Verify API deployment and live pod env wiring:

```bash
kubectl -n <namespace> get deploy mbsrn-api -o jsonpath="{range .spec.template.spec.containers[?(@.name=='mbsrn-api')].env[*]}{.name}={.value}{'\n'}{end}" | grep -E '^(REDIS_URL|SESSION_STATE_BACKEND|SESSION_STATE_ALLOW_INMEMORY_FALLBACK)='

kubectl -n <namespace> describe deploy mbsrn-api | grep -A5 -E 'SESSION_STATE_BACKEND|SESSION_STATE_ALLOW_INMEMORY_FALLBACK|REDIS_URL'

API_POD=$(kubectl -n <namespace> get pods -l app=mbsrn-api -o jsonpath='{.items[0].metadata.name}')
kubectl -n <namespace> exec "$API_POD" -- sh -c 'printenv | grep -E "^(REDIS_URL|SESSION_STATE_BACKEND|SESSION_STATE_ALLOW_INMEMORY_FALLBACK)="'
```

3. Verify backend selection logs from API:

```bash
kubectl -n <namespace> logs deploy/mbsrn-api --tail=500 | grep "session_state_backend_selection"
```

Expected healthy runtime:
- `REDIS_URL=redis://mbsrn-redis:6379/0`
- `SESSION_STATE_BACKEND=redis`
- `SESSION_STATE_ALLOW_INMEMORY_FALLBACK=false`
- log line contains:
  - `event=session_state_backend_selection`
  - `selected_backend=redis`
  - `degraded_mode=False`

Degraded fallback signal (production/staging; investigate immediately):
- `event=session_state_backend_selection`
- `selected_backend=inmemory`
- `degraded_mode=True`
- inspect `reason=...` for classification (`redis_not_configured_auto_fallback`, `redis_unavailable_fail_open:*`, etc.)

### Cloud Logging Queries (Session Backend)
Use Logs Explorer with these exact filters (adjust namespace if needed):

Healthy Redis selection:
```text
resource.type="k8s_container"
resource.labels.namespace_name="mbsrn"
resource.labels.container_name="mbsrn-api"
textPayload:"session_state_backend_selection"
textPayload:"selected_backend=redis"
textPayload:"degraded_mode=False"
```

Degraded in-memory fallback detection:
```text
resource.type="k8s_container"
resource.labels.namespace_name="mbsrn"
resource.labels.container_name="mbsrn-api"
textPayload:"session_state_backend_selection"
textPayload:"selected_backend=inmemory"
textPayload:"degraded_mode=True"
```

Session backend selection errors:
```text
resource.type="k8s_container"
resource.labels.namespace_name="mbsrn"
resource.labels.container_name="mbsrn-api"
severity>=ERROR
textPayload:"session_state_backend_selection"
(textPayload:"selected_backend=none" OR textPayload:"selected_backend=inmemory")
```

Prompt configuration note:
- production prompt overrides are managed in persisted business admin settings.
- deprecated legacy env prompt `AI_PROMPT_TEXT_RECOMMENDATION` is not required for API deployment wiring.

## Operational Notes

- API health endpoint: `/health`
- Deployments include readiness/liveness probes.
- Deploy runs are gated on successful backend and frontend image builds.
- Migrations must succeed before workload rollout proceeds.
- Rollback is available using standard Kubernetes rollout history commands.
- Public internet access is through GKE Ingress + external HTTP(S) load balancer.
- Ingress path routing uses one hostname:
  - `/` -> `mbsrn-ui` service
  - `/api` -> `mbsrn-api` service
- API and UI services remain internal `ClusterIP`; production NodePort exposure is not used.

### TLS Verification Commands (Post-Deploy)

For full production cutover order (DNS + TLS + OAuth GO/NO-GO), use:
- `docs/runbooks/dns-tls-oauth-cutover.md`

```bash
kubectl get managedcertificate -n mbsrn
kubectl describe managedcertificate mbsrn-app-managed-cert -n mbsrn
kubectl describe managedcertificate mbsrn-www-managed-cert -n mbsrn
kubectl get ingress -n mbsrn

curl -I https://app.mbsrn.com
curl -I https://www.mbsrn.com
```

Expected:
- both managed certificates progress to `Active`
- both ingresses retain their intended host mapping
- HTTPS is reachable for both domains without certificate warnings

Caveat:
- Managed certificate provisioning is not instant; allow for propagation/issuance delay before treating initial non-Active states as failure.
- App ingress currently enables HTTP->HTTPS redirect via `mbsrn-app-frontend-config`; keep OAuth redirect URIs configured as HTTPS (`https://app.mbsrn.com/...`) before enforcing production OAuth publishing changes.
