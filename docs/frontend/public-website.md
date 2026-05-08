# Public Website (`frontend/www`)

## Purpose

`frontend/www` is the standalone public website for `www.mbsrn.com`.

It exists to provide:

- public product overview content
- feature summary grounded in shipped platform behavior
- OAuth branding URLs (homepage, privacy policy, terms of service)

The operator app remains separate in `frontend/operator-ui` at `app.mbsrn.com`.

## Separation From Operator App

- **Code path**: separate Next.js app (`frontend/www` vs `frontend/operator-ui`)
- **Build path**: separate Docker image (`mbsrn-www`)
- **Deploy path**: separate workflow (`.github/workflows/deploy-www-prod.yml`)
- **Kubernetes resources**: separate website resources (`k8s/www-*`)

Website updates do not require operator app code changes.

## Local Development

```bash
cd frontend/www
npm ci
npm run dev
```

Pages:

- `/`
- `/features`
- `/privacy`
- `/terms`

No environment variables are required for the current static-first website.

## Next.js Standalone Image Optimization Requirement

`frontend/www` builds with Next.js `output: "standalone"` and uses `next/image`.
In production runtime, image optimization requires `sharp` to be present in the standalone bundle.

`sharp` is a production dependency of `frontend/www` and should be validated before deploy:

```bash
cd frontend/www
npm ci
npm run build
npm run validate:standalone-runtime
```

## Deployment

Production website deployment is handled by:

- `.github/workflows/deploy-www-prod.yml`

It applies:

- `k8s/www-serviceaccount.yaml`
- `k8s/www-deployment.yaml`
- `k8s/www-service.yaml`
- `k8s/www-frontend-config.yaml`
- `k8s/www-managed-certificate.yaml`
- `k8s/www-ingress.yaml`

Operator app deployment remains in `.github/workflows/deploy-prod.yml` with `k8s/ui-*` and `k8s/api-*`.

## GKE TLS Topology (ManagedCertificate + Ingress)

Production endpoints are split across two GKE Ingress resources:

- `app.mbsrn.com` -> `mbsrn-ingress` -> `mbsrn-app-managed-cert`
- `www.mbsrn.com` -> `mbsrn-www-ingress` -> `mbsrn-www-managed-cert`

Manifest sources:

- app ingress/cert:
  - `k8s/app-ingress.yaml`
  - `k8s/app-managed-certificate.yaml`
  - `k8s/app-frontend-config.yaml`
- website ingress/cert:
  - `k8s/www-ingress.yaml`
  - `k8s/www-managed-certificate.yaml`
  - `k8s/www-frontend-config.yaml`

Notes:
- TLS is managed by GKE ManagedCertificate resources via annotation `networking.gke.io/managed-certificates`.
- Website ingress keeps its current static-IP behavior; no static-IP annotation changes are made in this doc path.
- App ingress keeps explicit static-IP binding annotation (`mbsrn-prod-static-ip`) in `k8s/app-ingress.yaml`.

Required deployment config mirrors the existing production deploy model:

- GitHub variables:
  - `GCP_PROJECT_ID`
  - `GCP_REGION`
  - `GKE_CLUSTER`
  - `K8S_NAMESPACE`
  - `AR_REGION`
  - `AR_REPOSITORY`
  - optional website sizing/image vars:
    - `WWW_IMAGE_NAME`
    - `WWW_MEMORY_REQUEST`, `WWW_EPHEMERAL_STORAGE_REQUEST`
    - `WWW_MEMORY_LIMIT`, `WWW_EPHEMERAL_STORAGE_LIMIT`
  - website CPU is intentionally pinned in `.github/workflows/deploy-www-prod.yml`:
    - `requests.cpu=100m`
    - `limits.cpu=500m`
    - ultra-low recommender values (for example `4m`) are treated as advisory, not copied literally for production
    - these are declared/rendered targets; GKE Autopilot may admit different live requests after admission/defaulting
    - observed production state on May 4, 2026 for `mbsrn-www` admitted `requests.cpu=308m` with `requests.memory=2Gi`
- GitHub secrets:
  - `GCP_WORKLOAD_IDENTITY_PROVIDER`
  - `GCP_SERVICE_ACCOUNT_EMAIL`

## Production Rollout Checklist

Run this checklist in order for every `www.mbsrn.com` release.

For the final combined production cutover flow across both hosts (`app` + `www`), including GO/NO-GO and rollback criteria, use:
- `docs/runbooks/dns-tls-oauth-cutover.md`

1. Pre-deploy repository checks
- `cd frontend/www && npm run lint`
- `cd frontend/www && npm run typecheck`
- `cd frontend/www && npm run build`
- `cd frontend/www && npm run validate:standalone-runtime`
- Confirm public pages still compile:
  - `/`
  - `/features`
  - `/privacy`
  - `/terms`

2. Trigger website deployment
- Use `.github/workflows/deploy-www-prod.yml` (push to `main` with website file changes or manual dispatch).
- Confirm workflow succeeds through:
  - image build/push
  - rendered manifest apply
  - rollout status for `deployment/mbsrn-www`

3. Verify Kubernetes routing/cert resources
- `kubectl -n mbsrn get deploy mbsrn-www`
- `kubectl -n mbsrn rollout status deploy/mbsrn-www --timeout=5m`
- `kubectl -n mbsrn get svc mbsrn-www`
- `kubectl -n mbsrn get ingress mbsrn-www-ingress -o wide`
- `kubectl -n mbsrn describe managedcertificate mbsrn-www-managed-cert`

4. Verify DNS and public reachability
- Confirm `www.mbsrn.com` resolves to the ingress LB IP.
- Confirm TLS serves a valid cert for `www.mbsrn.com`.
- Confirm public pages are reachable without authentication.

5. Verify production content blockers before publish
- Confirm no unresolved legal/contact placeholder text remains in rendered pages.
- Confirm support contact email is correct (`support@mbsrn.com` by default in repo).
- Confirm legal counsel has reviewed Privacy/Terms copy for long-term production use.

6. Verify Google OAuth branding readiness
- Homepage URL: `https://www.mbsrn.com/`
- Privacy URL: `https://www.mbsrn.com/privacy`
- Terms URL: `https://www.mbsrn.com/terms`
- Authorized domain: `mbsrn.com`
- Confirm OAuth branding fields and links match exactly before publishing OAuth app branding changes.

## Post-Deploy Smoke Test

Use this manual smoke test after deployment completes.

### HTTP and route checks

Run:

```bash
curl -I https://www.mbsrn.com/
curl -I https://www.mbsrn.com/features
curl -I https://www.mbsrn.com/privacy
curl -I https://www.mbsrn.com/terms
```

Expected:
- each route returns `200 OK`
- no auth redirect on public pages

Operator app TLS quick check:

```bash
curl -I https://app.mbsrn.com
```

Expected:
- `200`, `302`, or `307` from app entry path is acceptable based on auth/session flow
- certificate served for `app.mbsrn.com` (no browser cert warning)

### Asset and metadata checks

Run:

```bash
curl -I https://www.mbsrn.com/favicon.svg
curl -s https://www.mbsrn.com/ | grep -E \"<title>|description|canonical|og:\"
```

Expected:
- favicon returns `200`
- homepage HTML contains title/description/canonical/open-graph metadata

### Browser checks (required)

Open `https://www.mbsrn.com/` and verify:
- header/footer nav links work
- CTA opens `https://app.mbsrn.com`
- logo/favicons render correctly
- no broken image icons or mixed-content warnings
- `/privacy` and `/terms` are readable and not malformed
- light/dark theme toggle does not break layout or contrast
- mobile-width pass (rough check at ~390px and ~768px)

### Troubleshooting quick mapping

- `404/5xx on all routes`: check ingress/service binding and `mbsrn-www` pod readiness.
- cert stuck `Provisioning`/`Failed`: verify host DNS points to ingress LB IP and wait for managed cert issuance.
- TLS pending/invalid: check managed certificate status and DNS host mapping.
- Route works but missing styles/assets: verify `frontend/www/public/*` assets are present in image.
- repeated `sharp-missing-in-production` logs: verify `frontend/www/package.json` includes `sharp` in `dependencies`, rebuild image, and rerun `npm run validate:standalone-runtime`.
- OAuth branding rejected: verify exact URLs and authorized domain in Google Cloud console.

Managed certificate status commands:

```bash
kubectl get managedcertificate -n mbsrn
kubectl describe managedcertificate mbsrn-app-managed-cert -n mbsrn
kubectl describe managedcertificate mbsrn-www-managed-cert -n mbsrn
kubectl get ingress -n mbsrn
```

Provisioning delay expectation:
- managed certificate issuance commonly takes several minutes and may take longer depending on DNS propagation and GCLB state.

## Content Ownership

Update website content in:

- primary messaging constants: `frontend/www/lib/siteContent.ts`
- homepage layout/content wiring: `frontend/www/app/page.tsx`
- features page structure: `frontend/www/app/features/page.tsx`
- privacy policy content: `frontend/www/app/privacy/page.tsx`
- terms content: `frontend/www/app/terms/page.tsx`
- shell nav/footer: `frontend/www/components/SiteHeader.tsx`, `frontend/www/components/SiteFooter.tsx`

## Brand Narrative and Visual Strategy

The homepage now leads with a direct brand narrative:

- `My Business Sucks Right Now` -> `My Business Starts Right Now`
- operator frustration first, then clear operational direction
- action-focused positioning over generic analytics language

Homepage narrative order:

1. Hero with high-visibility brand and emotional hook
2. "This is you" section for overloaded operators
3. Transition moment (`Sucks -> Starts`)
4. Before/After operational clarity
5. Existing feature/outcome/how-it-works/trust sections

Imagery guidance for future updates:

- use real-world operator contexts (field work, service jobs, operations pressure)
- avoid sterile corporate stock visuals
- keep visual tone practical and high-stakes, not gimmicky
- pair emotional imagery with clear "what to do next" copy

Asset location for homepage narrative visuals:

- `frontend/www/public/images/`

Policy page note:
- Privacy/Terms are starter SaaS policy copy for launch readiness and OAuth branding fields.
- Keep legal review explicit until counsel sign-off is complete.
- Confirm support contact email before production publishing.

## Google OAuth Branding URLs

Use these URLs in Google OAuth branding fields:

- Homepage: `https://www.mbsrn.com/`
- Privacy policy: `https://www.mbsrn.com/privacy`
- Terms of service: `https://www.mbsrn.com/terms`

Authorized domain expectation:

- `mbsrn.com` should be verified/allowed in the Google Cloud OAuth configuration.

## Google Cloud / OAuth Manual Checks

Before changing OAuth publishing status, verify manually in Google Cloud Console:

1. OAuth branding URLs match:
- Homepage: `https://www.mbsrn.com/`
- Privacy: `https://www.mbsrn.com/privacy`
- Terms: `https://www.mbsrn.com/terms`

2. Authorized domain includes `mbsrn.com`.

3. The public pages are accessible anonymously and return production content (no draft placeholders).

4. Privacy/Terms copy has completed legal/business review for production use.
5. If Google reviewer lands on `https://app.mbsrn.com/`, confirm:
   - visible product name alignment with OAuth consent screen (`My Business Sucks Right Now`)
   - visible links to `https://www.mbsrn.com/privacy` and `https://www.mbsrn.com/terms`

## Apex Domain Note

This repo deploys the public site for `www.mbsrn.com`.

Recommended production state:

- keep `www.mbsrn.com` as the canonical public hostname
- configure apex `mbsrn.com` to issue a permanent redirect to `https://www.mbsrn.com`

Alternative (only if required by product/legal requirements):

- add an additional ingress/certificate host entry and route apex to `mbsrn-www`

Do not repoint `app.mbsrn.com`; it remains the operator workspace domain.
