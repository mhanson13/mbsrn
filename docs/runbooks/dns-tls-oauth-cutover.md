# DNS + TLS + OAuth Production Cutover Runbook

## Purpose

Use this runbook for final production cutover verification of:

- `app.mbsrn.com` (operator app)
- `www.mbsrn.com` (public website)

This is the final readiness path for DNS + TLS + Google OAuth branding/publication checks.

## Current Target Topology

- DNS zone: `mbsrn.com`
- Ingress resources:
  - `mbsrn-ingress` -> `app.mbsrn.com`
  - `mbsrn-www-ingress` -> `www.mbsrn.com`
- Managed certificates:
  - `mbsrn-app-managed-cert`
  - `mbsrn-www-managed-cert`
- App ingress HTTPS redirect:
  - enabled via `mbsrn-app-frontend-config`

## Preconditions

Before cutover checks:

1. Deployment workflows completed successfully:
   - app: `.github/workflows/deploy-prod.yml`
   - website: `.github/workflows/deploy-www-prod.yml`
2. Kubernetes context points to production cluster/namespace.
3. DNS changes are propagated in your DNS provider.
4. Google OAuth branding values are prepared (see section below).

## Production Verification Order (Execute In Sequence)

### 1) Confirm ingress and host wiring

Run:

```bash
kubectl get ingress -n mbsrn
```

Expected:

- `mbsrn-ingress` exists and includes host `app.mbsrn.com`
- `mbsrn-www-ingress` exists and includes host `www.mbsrn.com`
- each ingress has an external `ADDRESS`

### 2) Confirm managed certificate resources

Run:

```bash
kubectl get managedcertificate -n mbsrn
kubectl describe managedcertificate mbsrn-app-managed-cert -n mbsrn
kubectl describe managedcertificate mbsrn-www-managed-cert -n mbsrn
```

Expected:

- both resources exist
- status is `Active` (or equivalent ready state)
- domain status does not show ongoing failure

If status is still provisioning, wait and re-check. Managed cert issuance is not immediate.

### 3) Confirm DNS points to ingress addresses

Run:

```bash
nslookup app.mbsrn.com
nslookup www.mbsrn.com

dig +short app.mbsrn.com A
dig +short www.mbsrn.com A
```

Expected:

- both hostnames resolve
- resolved IPs match the intended ingress external addresses
- no stale/old load balancer IP remains authoritative

### 4) Confirm HTTPS reaches both hosts

Run:

```bash
curl -I https://app.mbsrn.com
curl -I https://www.mbsrn.com
```

Expected:

- TLS handshake succeeds without certificate errors
- response status is valid for entry behavior:
  - app host: `200` / auth redirect status (for example `302`/`307`) is acceptable
  - website host: `200` expected

### 5) Public website route smoke test

Run:

```bash
curl -I https://www.mbsrn.com/
curl -I https://www.mbsrn.com/features
curl -I https://www.mbsrn.com/privacy
curl -I https://www.mbsrn.com/terms
```

Expected:

- all routes return `200`
- no auth redirect on public routes

### 6) Browser-level checks (required)

Open both hosts in a browser and verify:

1. no browser certificate warning on either host
2. `https://www.mbsrn.com/` loads anonymously
3. privacy/terms pages are reachable and readable
4. CTA from website points to `https://app.mbsrn.com`
5. app login/callback flows remain HTTPS-valid

## Google OAuth Production Cutover Checklist

Use these exact branding fields:

- Homepage URL: `https://www.mbsrn.com/`
- Privacy policy URL: `https://www.mbsrn.com/privacy`
- Terms of service URL: `https://www.mbsrn.com/terms`

Required manual checks before changing OAuth publishing status:

1. Authorized domain includes `mbsrn.com`
2. OAuth redirect URIs for app remain exact HTTPS values (`https://app.mbsrn.com/...`)
3. public URLs above load without auth and without TLS warnings
4. no temporary placeholder policy/legal copy is still exposed
5. product name shown in reviewer-visible UI aligns with consent-screen app name:
   - `My Business Sucks Right Now`
6. if Google reviews the app sign-in surface (`https://app.mbsrn.com/`), confirm visible links to:
   - `https://www.mbsrn.com/privacy`
   - `https://www.mbsrn.com/terms`

## GO / NO-GO Criteria

### GO

Proceed only if all are true:

1. `app.mbsrn.com` and `www.mbsrn.com` resolve to intended ingress addresses
2. both managed certificates are `Active` (or equivalent ready)
3. HTTPS responses succeed on both hosts
4. browsers show no certificate warnings
5. public website URLs are reachable anonymously
6. app OAuth callback and sign-in flows remain HTTPS-valid

### NO-GO

Do not proceed (or pause rollout) if any are true:

1. certificate provisioning still pending/failing
2. hostname resolves to wrong IP
3. HTTP/HTTPS redirect loop is observed
4. app auth callback fails or redirect URI mismatch appears
5. public privacy/terms pages are unreachable or malformed

## Rollback / Triage Guidance

If cutover fails, use this order:

1. **Certificates not active**
   - re-check `kubectl describe managedcertificate ...`
   - verify DNS A records match ingress `ADDRESS`
   - wait for propagation before making additional changes
2. **Ingress IP drift**
   - run `kubectl get ingress -n mbsrn -o wide`
   - compare against DNS records
   - correct DNS if ingress addresses changed
3. **DNS mismatch**
   - verify authoritative DNS zone values for `app` and `www`
   - flush/confirm resolver caches with `dig +short`
4. **Redirect/auth failures**
   - validate app redirect URIs in Google OAuth config are exact HTTPS app-domain URIs
   - verify app ingress still maps app host only
5. **Public site not healthy**
   - confirm website deployment/pods/service/ingress health
   - pause OAuth publishing cutover until public URL checks pass

If any NO-GO condition remains unresolved, hold OAuth production publishing changes and continue with operational triage only.

## Top 5 Failure Modes To Watch

1. Managed certificate stuck in provisioning due to DNS/IP mismatch
2. Hostname resolving to an old ingress address after rollout
3. Redirect loop caused by conflicting host/redirect configuration
4. OAuth redirect URI mismatch after domain/TLS changes
5. Public policy URLs (`/privacy`, `/terms`) inaccessible at cutover time
