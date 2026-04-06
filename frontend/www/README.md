# MBSRN Public Website (`frontend/www`)

Standalone Next.js public website for `www.mbsrn.com`.

## Purpose

- Public marketing/legal surface for OAuth branding and customer-facing product explanation
- Isolated from operator workspace runtime (`frontend/operator-ui`)
- Static-first content with no backend API dependency

## Local run

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

## Build

```bash
npm run lint
npm run typecheck
npm run build
```

## Deployment

- Kubernetes resources are under `k8s/www-*`.
- Production deployment workflow is `.github/workflows/deploy-www-prod.yml`.
- This deploy path is separate from operator app deployment.
