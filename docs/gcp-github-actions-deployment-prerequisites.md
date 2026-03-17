# GCP + GitHub Actions Deployment Prerequisites (GKE)

## 1) Purpose And Scope
This guide is a prerequisite/setup runbook for deploying Work Boots to GKE from GitHub Actions.

What this guide does:
- shows exactly what to create in Google Cloud and GitHub
- maps every required value to the files/workflows in this repository
- gives copy/paste commands and explicit Google Cloud Console navigation

What this guide does not do:
- redesign architecture
- change auth/tenant model
- split services into microservices
- replace GitHub Actions as the deploy orchestrator

Current deployment model in this repo:
- GitHub Actions orchestrates CI + deploy (`.github/workflows/deploy-gke.yml`)
- GKE runs API/UI workloads (`infra/k8s/base/`, `infra/k8s/overlays/*`)
- Cloud Buildpacks are used only to build/push images from the workflow (`gcloud builds submit --pack ...`)

## 2) High-Level Deployment Flow
End-to-end flow used by this repo:

```text
GitHub push/workflow_dispatch
  -> GitHub Actions workflow (deploy-gke.yml)
  -> Workload Identity Federation auth to GCP
  -> Build/push API and UI images to Artifact Registry
  -> Get GKE credentials
  -> kubectl apply overlay (dev/prod)
  -> run Alembic migration Job gate
  -> update deployment images + verify rollout
```

## 3) Google Cloud Resource Setup (Step-By-Step)
Each required resource below uses the same pattern:
- Console path
- click-by-click setup
- exactly what to copy
- where this value is used in this repo

### 3.1 Create Or Select A GCP Project
**Console Path:**
Google Cloud Console -> top project selector -> `New Project`

**Steps:**
1. Click the project selector in the top header.
2. Click `New Project`.
3. Project name: `work-boots` (or your org standard).
4. Select billing account.
5. Click `Create`.
6. Re-open the project selector and switch to the new project.

**Copy This Value:**
- Project ID: `my-work-boots-prod` (example)
- Project Number: `123456789012` (example)

**Used In:**
- GitHub secret `GCP_PROJECT_ID` in `.github/workflows/deploy-gke.yml`
- Workload Identity Provider resource string (uses Project Number)
- Artifact Registry path (`<LOCATION>-docker.pkg.dev/<PROJECT_ID>/<REPO>`)

### 3.2 Enable Required APIs
**Console Path:**
Google Cloud Console -> APIs & Services -> Library

**Steps:**
1. Go to `APIs & Services` -> `Library`.
2. Search and open each required API from Section 4.
3. Click `Enable` for each API.
4. Confirm each API shows `Enabled` in `APIs & Services` -> `Enabled APIs & services`.

**Copy This Value:**
- No secret value to copy.
- Copy/paste checklist item: all required APIs show `Enabled`.

**Used In:**
- Required for workflow steps in `.github/workflows/deploy-gke.yml` to authenticate, build, push, and deploy.

### 3.3 Create Artifact Registry Repository
**Console Path:**
Google Cloud Console -> Artifact Registry -> Repositories -> `Create Repository`

**Steps:**
1. Click `Create Repository`.
2. Name: `work-boots` (or your chosen name).
3. Format: `Docker`.
4. Region: choose one region (example: `us-central1`).
5. Click `Create`.

**Copy This Value:**
- Region: `us-central1`
- Repository name: `work-boots`
- Full repository prefix:
  `us-central1-docker.pkg.dev/<PROJECT_ID>/work-boots`

**Used In:**
- GitHub secrets:
  - `GAR_LOCATION` = `us-central1`
  - `GAR_REPOSITORY` = `work-boots`
- Image URI construction in `.github/workflows/deploy-gke.yml`:
  - API: `${GAR_LOCATION}-docker.pkg.dev/${PROJECT_ID}/${GAR_REPOSITORY}/api:${GITHUB_SHA}`
  - UI: `${GAR_LOCATION}-docker.pkg.dev/${PROJECT_ID}/${GAR_REPOSITORY}/ui:${GITHUB_SHA}`

### 3.4 Create GKE Autopilot Cluster
**Console Path:**
Google Cloud Console -> Kubernetes Engine -> Clusters -> `Create` -> `Switch to Autopilot`

**Steps:**
1. Click `Create`.
2. Select `Autopilot`.
3. Cluster name: `work-boots-cluster` (example).
4. Region: choose your deploy region (for example `us-central1`).
5. Networking: keep defaults unless your org requires custom VPC/subnet.
6. Click `Create`.
7. Wait until cluster status is `Running`.

**Copy This Value:**
- Cluster name: `work-boots-cluster`
- Cluster region: `us-central1`

**Used In:**
- GitHub secrets:
  - `GKE_CLUSTER` = cluster name
  - `GKE_LOCATION` = region
- Used by `gcloud container clusters get-credentials` in `.github/workflows/deploy-gke.yml`

### 3.5 Create Workload Identity Pool
Full detailed WIF setup is in Section 5; this subsection is the resource creation summary.

**Console Path:**
Google Cloud Console -> IAM & Admin -> Workload Identity Federation -> `Create Pool`

**Steps:**
1. Click `Create Pool`.
2. Pool ID: `github-pool` (example).
3. Display name: `GitHub Actions Pool`.
4. Click `Create`.

**Copy This Value:**
- Pool ID: `github-pool`

**Used In:**
- Part of provider resource string stored in GitHub secret `GCP_WIF_PROVIDER`.

### 3.6 Create Workload Identity Provider (GitHub OIDC)
Full detailed WIF setup is in Section 5; this subsection is the resource creation summary.

**Console Path:**
Google Cloud Console -> IAM & Admin -> Workload Identity Federation -> select pool -> `Add Provider`

**Steps:**
1. Provider type: `OpenID Connect (OIDC)`.
2. Provider ID: `github-provider` (example).
3. Issuer URL: `https://token.actions.githubusercontent.com`.
4. Configure attribute mapping/conditions (Section 5 has copy-ready values).
5. Save provider.

**Copy This Value:**
- Provider resource string:
  `projects/<PROJECT_NUMBER>/locations/global/workloadIdentityPools/<POOL_ID>/providers/<PROVIDER_ID>`

**Used In:**
- GitHub secret `GCP_WIF_PROVIDER`
- `google-github-actions/auth@v3` in `.github/workflows/deploy-gke.yml`

### 3.7 Create Service Account For GitHub Actions
**Console Path:**
Google Cloud Console -> IAM & Admin -> Service Accounts -> `Create Service Account`

**Steps:**
1. Click `Create Service Account`.
2. Name: `work-boots-github-deployer` (example).
3. Description: `Deploys Work Boots from GitHub Actions to GKE`.
4. Click `Create and Continue`.
5. Grant required roles (minimum set in Section 5.4).
6. Click `Done`.

**Copy This Value:**
- Service account email:
  `work-boots-github-deployer@<PROJECT_ID>.iam.gserviceaccount.com`

**Used In:**
- GitHub secret `GCP_WIF_SERVICE_ACCOUNT`
- `google-github-actions/auth@v3` in `.github/workflows/deploy-gke.yml`

### 3.8 Configure IAM Bindings (WIF + Deploy Permissions)
**Console Path:**
Google Cloud Console -> IAM & Admin -> IAM (for project roles)
Google Cloud Console -> IAM & Admin -> Service Accounts -> select deployer SA -> Permissions (for `roles/iam.workloadIdentityUser`)

**Steps:**
1. In `IAM`, grant project-level roles to the deployer service account (Section 5.4).
2. Open deployer service account -> `Permissions` -> `Grant Access`.
3. Add principal set from your WIF provider (Section 5.3) with role:
   - `Workload Identity User` (`roles/iam.workloadIdentityUser`)
4. Save.

**Copy This Value:**
- Principal set member string (example):
  `principalSet://iam.googleapis.com/projects/<PROJECT_NUMBER>/locations/global/workloadIdentityPools/<POOL_ID>/attribute.repository/mhanson13/work-boots`

**Used In:**
- Allows GitHub OIDC tokens to impersonate the deployer SA.

### 3.9 Provision Redis (Applicable For Pilot/Prod Security Controls)
This repo does not deploy Redis manifests in `infra/k8s`. You must provide Redis separately.

Recommended managed option: Memorystore for Redis.

**Console Path:**
Google Cloud Console -> Memorystore for Redis -> `Create Instance`

**Steps:**
1. Click `Create Instance`.
2. Choose Redis version supported by your org policy.
3. Name: `work-boots-redis` (example).
4. Region: same region as GKE cluster when possible.
5. Tier: choose pilot-appropriate tier.
6. Configure network connectivity so GKE workloads can reach Redis.
7. Click `Create`.

**Copy This Value:**
- Redis host/IP
- Redis port (usually `6379`)
- Redis URI:
  - `redis://<HOST>:6379/0`
  - or `rediss://<HOST>:6379/0` when TLS is enabled

**Used In:**
- Kubernetes Secret `work-boots-secrets` key `REDIS_URL` (`infra/k8s/base/secrets.template.yaml`)
- Runtime controls in `infra/k8s/base/configmap.yaml`:
  - `RATE_LIMIT_BACKEND=redis`
  - `SESSION_STATE_BACKEND=redis`

### 3.10 Provision Database (Applicable; Required For API Runtime)
This repo does not deploy PostgreSQL manifests in `infra/k8s`. You must provide PostgreSQL separately.

Recommended managed option: Cloud SQL for PostgreSQL.

**Console Path:**
Google Cloud Console -> SQL -> `Create Instance` -> `Choose PostgreSQL`

**Steps:**
1. Click `Create Instance`.
2. Choose `PostgreSQL`.
3. Instance ID: `work-boots-postgres` (example).
4. Set admin password.
5. Choose region (prefer same as GKE).
6. Configure connectivity according to your network model.
7. Create database (example: `work_boots_console`).
8. Create application user.
9. Click `Create`.

**Copy This Value:**
- Host/IP
- Port (`5432`)
- Database name
- Username/password
- Assembled `DATABASE_URL`:
  `postgresql+psycopg://<USER>:<PASSWORD>@<HOST>:5432/<DB_NAME>`

**Used In:**
- `DATABASE_URL` consumed by API runtime (`app/core/config.py`)
- Current base config default is in `infra/k8s/base/configmap.yaml`; you can override via Kubernetes Secret (Section 7)
- Migration job uses same env sources in `.github/workflows/deploy-gke.yml`

### 3.11 Configure TLS/Certificate For Ingress Hostnames
Ingress hosts are defined in overlays:
- dev: `dev.workboots.example.com` (`infra/k8s/overlays/dev/kustomization.yaml`)
- prod: `workboots.example.com` (`infra/k8s/overlays/prod/kustomization.yaml`)

The base ingress currently defines host routing but no TLS block (`infra/k8s/base/ingress.yaml`).
Configure TLS before production traffic.

**Console Path:**
Google Cloud Console -> Network Services -> Load balancing (certificate visibility)  
and optionally Certificate Manager (if using Google-managed certs outside Kubernetes manifests)

**Steps:**
1. Choose TLS option (Section 9: Option A or Option B).
2. Point DNS records for hostnames to ingress external IP.
3. Verify certificate status is `Active` and HTTPS works.

**Copy This Value:**
- Ingress external IP
- DNS records (`A`/`AAAA`)
- Certificate resource or TLS secret name

**Used In:**
- Ingress serving API/UI over HTTPS
- HSTS expectations from runtime docs and `SECURITY_HEADERS_HSTS_*` settings

### 3.12 Create Google OAuth Client (For Operator Login)
Google identity is used for identity proofing, then mapped to internal principals.

**Console Path:**
Google Cloud Console -> APIs & Services -> Credentials -> `Create Credentials` -> `OAuth client ID`

**Steps:**
1. If prompted, configure OAuth consent screen first.
2. Click `Create Credentials` -> `OAuth client ID`.
3. Application type: `Web application`.
4. Name: `work-boots-operator-ui` (example).
5. Add authorized JavaScript origins:
   - `https://dev.workboots.example.com`
   - `https://workboots.example.com`
6. Add authorized redirect URIs if your UI flow requires them.
7. Click `Create`.

**Copy This Value:**
- OAuth Client ID:
  `<CLIENT_ID>.apps.googleusercontent.com`
- OAuth Client Secret (if your deployment requires it)

**Used In:**
- Kubernetes Secret `work-boots-secrets`:
  - `GOOGLE_OIDC_CLIENT_ID`
  - `GOOGLE_OIDC_CLIENT_SECRET`
- API runtime Google token validation/auth flow

## 4) Required Google APIs (With UI Path)
**Console Path:**
Google Cloud Console -> APIs & Services -> Library

Enable these APIs in the same project used for deployment:

| API | Why it is needed in this repo |
|---|---|
| Kubernetes Engine API (`container.googleapis.com`) | Required for GKE cluster operations and `get-credentials` in deploy workflow |
| Artifact Registry API (`artifactregistry.googleapis.com`) | Required to store API/UI images built in workflow |
| Cloud Build API (`cloudbuild.googleapis.com`) | Required because deploy workflow runs `gcloud builds submit --pack ...` |
| IAM API (`iam.googleapis.com`) | Required for service account and IAM policy operations |
| IAM Service Account Credentials API (`iamcredentials.googleapis.com`) | Required for SA impersonation during WIF auth |
| Security Token Service API (`sts.googleapis.com`) | Required by Workload Identity Federation token exchange |
| Compute Engine API (`compute.googleapis.com`) | Required by GKE/ingress and load balancer dependencies |
| Service Usage API (`serviceusage.googleapis.com`) | Required to manage API enablement |
| Cloud Resource Manager API (`cloudresourcemanager.googleapis.com`) | Required by IAM/resource policy operations |
| Redis API (`redis.googleapis.com`) (if using Memorystore) | Required if provisioning managed Redis |
| Cloud SQL Admin API (`sqladmin.googleapis.com`) (if using Cloud SQL) | Required if provisioning managed PostgreSQL |

## 5) Workload Identity Federation (Critical)
### 5.1 What WIF Is And Why This Repo Uses It
Workload Identity Federation (WIF) lets GitHub Actions exchange its short-lived OIDC token for Google credentials without storing long-lived JSON keys in GitHub secrets.

Why this is safer:
- no static key file to leak/rotate
- short-lived credentials per workflow run
- explicit trust policy by repo/branch

How auth works in this repo:
1. GitHub job requests an OIDC token (`id-token: write` in workflow).
2. `google-github-actions/auth@v3` exchanges that token using your WIF provider.
3. Google grants short-lived access as your deployer service account.
4. Workflow runs `gcloud` + `kubectl` operations.

### 5.2 Create Workload Identity Pool
**Console Path:**
Google Cloud Console -> IAM & Admin -> Workload Identity Federation -> `Create Pool`

**Steps:**
1. Click `Create Pool`.
2. Pool ID: `github-pool`.
3. Display name: `GitHub Actions Pool`.
4. Description: `Trust boundary for GitHub Actions deployments`.
5. Click `Create`.

**Copy This Value:**
- Pool ID: `github-pool`

**Used In:**
- Provider resource string stored in GitHub secret `GCP_WIF_PROVIDER`.

### 5.3 Create Workload Identity Provider
**Console Path:**
Google Cloud Console -> IAM & Admin -> Workload Identity Federation -> select `github-pool` -> `Add Provider`

**Steps:**
1. Provider type: `OpenID Connect (OIDC)`.
2. Provider ID: `github-provider`.
3. Issuer (URL): `https://token.actions.githubusercontent.com`.
4. Allowed audiences:
   - `https://github.com/mhanson13/work-boots`
5. Attribute mappings (add exactly):
   - `google.subject=assertion.sub`
   - `attribute.actor=assertion.actor`
   - `attribute.repository=assertion.repository`
   - `attribute.repository_owner=assertion.repository_owner`
   - `attribute.ref=assertion.ref`
6. Attribute condition (recommended baseline):
   - `assertion.repository=='mhanson13/work-boots'`
   - optionally restrict branch:
     `assertion.repository=='mhanson13/work-boots' && assertion.ref=='refs/heads/main'`
7. Click `Create`.

**Copy This Value:**
- Provider resource string:
  `projects/<PROJECT_NUMBER>/locations/global/workloadIdentityPools/github-pool/providers/github-provider`

**Used In:**
- GitHub secret `GCP_WIF_PROVIDER`
- `workload_identity_provider:` in `.github/workflows/deploy-gke.yml`

### 5.4 Create/Configure Deployer Service Account
**Console Path:**
Google Cloud Console -> IAM & Admin -> Service Accounts -> `Create Service Account`

**Steps:**
1. Create service account:
   - Name: `work-boots-github-deployer`
2. Grant project roles (pilot baseline; tighten later):
   - `Artifact Registry Writer` (`roles/artifactregistry.writer`)
   - `Kubernetes Engine Developer` (`roles/container.developer`)
   - `Cloud Build Builds Editor` (`roles/cloudbuild.builds.editor`)
   - `Service Account Token Creator` is not required for the GitHub runner SA itself in this flow.
3. Save.

**Copy This Value:**
- Service account email:
  `work-boots-github-deployer@<PROJECT_ID>.iam.gserviceaccount.com`

**Used In:**
- GitHub secret `GCP_WIF_SERVICE_ACCOUNT`
- `service_account:` in `.github/workflows/deploy-gke.yml`

### 5.5 Bind WIF Principal To Service Account
**Console Path:**
Google Cloud Console -> IAM & Admin -> Service Accounts -> select deployer SA -> `Permissions` -> `Grant Access`

**Steps:**
1. Click `Grant Access`.
2. New principals:
   `principalSet://iam.googleapis.com/projects/<PROJECT_NUMBER>/locations/global/workloadIdentityPools/github-pool/attribute.repository/mhanson13/work-boots`
3. Role:
   `Workload Identity User` (`roles/iam.workloadIdentityUser`)
4. Click `Save`.

**Copy This Value:**
- Principal set string used above.

**Used In:**
- Allows only your repository's GitHub OIDC identities to impersonate the deployer SA.

### 5.6 Copy Required Values + GitHub Secret Mapping
Required value formats:
- Provider resource string:
  `projects/<PROJECT_NUMBER>/locations/global/workloadIdentityPools/<POOL_ID>/providers/<PROVIDER_ID>`
- Service account email:
  `<SA_NAME>@<PROJECT_ID>.iam.gserviceaccount.com`

Mapping to repository secrets:
- `GCP_WIF_PROVIDER` <- provider resource string
- `GCP_WIF_SERVICE_ACCOUNT` <- service account email

If your org uses different generic names:
- `GCP_WORKLOAD_IDENTITY_PROVIDER` maps to this repo's `GCP_WIF_PROVIDER`
- `GCP_SERVICE_ACCOUNT_EMAIL` maps to this repo's `GCP_WIF_SERVICE_ACCOUNT`

## 6) GitHub Secrets And Variables
Add secrets in GitHub:

**Console Path:**
GitHub -> `mhanson13/work-boots` -> `Settings` -> `Secrets and variables` -> `Actions` -> `New repository secret`

Create these repository secrets (exact names from `.github/workflows/deploy-gke.yml`):

| Name | Type | Example | Where to get it | Used in |
|---|---|---|---|---|
| `GCP_PROJECT_ID` | Secret | `my-work-boots-prod` | GCP project details page | `deploy-gke.yml` (`PROJECT_ID`) |
| `GAR_LOCATION` | Secret | `us-central1` | Artifact Registry repository region | image URI build/push paths |
| `GAR_REPOSITORY` | Secret | `work-boots` | Artifact Registry repository name | image URI build/push paths |
| `GCP_WIF_PROVIDER` | Secret | `projects/123456789012/locations/global/workloadIdentityPools/github-pool/providers/github-provider` | WIF provider details | `google-github-actions/auth@v3` |
| `GCP_WIF_SERVICE_ACCOUNT` | Secret | `work-boots-github-deployer@my-work-boots-prod.iam.gserviceaccount.com` | IAM Service Accounts | `google-github-actions/auth@v3` |
| `GKE_CLUSTER` | Secret | `work-boots-cluster` | GKE cluster details | `gcloud container clusters get-credentials` |
| `GKE_LOCATION` | Secret | `us-central1` | GKE cluster region | `gcloud container clusters get-credentials --region` |

Notes:
- Deploy workflow runs on `push` to `main` and `workflow_dispatch`.
- Secrets are not available to workflows triggered from untrusted forks.
- Keep `permissions.id-token: write` in deploy jobs; WIF fails without it.

## 7) Application Runtime Configuration
### 7.1 How Config Is Injected
Both API and UI Deployments use:
- ConfigMap: `work-boots-config` (non-secret settings)
- Secret: `work-boots-secrets` (sensitive values)

Repository files:
- ConfigMap template: `infra/k8s/base/configmap.yaml`
- Secret template: `infra/k8s/base/secrets.template.yaml`
- Deployment env wiring: `infra/k8s/base/api-deployment.yaml`, `infra/k8s/base/ui-deployment.yaml`

### 7.2 Create Kubernetes Secret (Preferred via YAML)
**Console Path (for verification):**
Google Cloud Console -> Kubernetes Engine -> Workloads -> your cluster -> Config & Storage -> Secrets

**Steps:**
1. Copy template file:
   ```bash
   cp infra/k8s/base/secrets.template.yaml infra/k8s/base/secrets.yaml
   ```
2. Edit `infra/k8s/base/secrets.yaml` and set real values.
3. Include at minimum:
   - `REDIS_URL`
   - `API_TOKEN_HASH_PEPPER`
   - `APP_SESSION_SECRET`
   - `GOOGLE_OIDC_CLIENT_ID`
   - `GOOGLE_OIDC_CLIENT_SECRET` (if your Google flow requires it)
   - `DATABASE_URL` (recommended to add here to avoid DB credentials in ConfigMap)
4. Apply to dev namespace:
   ```bash
   kubectl -n work-boots-dev apply -f infra/k8s/base/secrets.yaml
   ```
5. Apply to prod namespace:
   ```bash
   kubectl -n work-boots apply -f infra/k8s/base/secrets.yaml
   ```
6. Verify secret exists:
   ```bash
   kubectl -n work-boots-dev get secret work-boots-secrets
   kubectl -n work-boots get secret work-boots-secrets
   ```

**Copy This Value:**
- Secret name: `work-boots-secrets`
- Confirmed key names present (do not copy values to shared docs/screenshots)

**Used In:**
- API/UI runtime env via `envFrom.secretRef`
- Migration Job env via inline Job manifest in `.github/workflows/deploy-gke.yml`

### 7.3 Configure Runtime Env Keys (What Matters Most)
Required key guidance for pilot/prod:

- `REDIS_URL`
  - Source: managed Redis endpoint
  - Used by distributed rate limit and session state
- `DATABASE_URL`
  - Source: PostgreSQL endpoint/user/pass/db
  - Used by app and Alembic migration job
- `APP_SESSION_SECRET`
  - Source: long random secret
  - Used for app JWT signing/session flow
- `GOOGLE_OIDC_CLIENT_ID`
  - Source: Google OAuth client (Section 3.12)
  - Used for Google token audience validation

## 8) GKE Concepts (Beginner Mapping)
Plain-English terms:
- Cluster: the managed Kubernetes control plane + worker capacity.
- Namespace: logical isolation boundary inside a cluster.
- Deployment: manages pod replicas of an app.
- Service: stable internal network endpoint for pods.
- Ingress: external HTTP(S) routing into services.

How this repo maps:
- Base manifests: `infra/k8s/base/`
  - `api-deployment.yaml`, `ui-deployment.yaml`
  - `api-service.yaml`, `ui-service.yaml`
  - `ingress.yaml`
  - `configmap.yaml`
- Overlays:
  - dev namespace `work-boots-dev` -> `infra/k8s/overlays/dev/`
  - prod namespace `work-boots` -> `infra/k8s/overlays/prod/`
- Deploy workflow applies overlay:
  - `kubectl apply -k "infra/k8s/overlays/${TARGET_OVERLAY}"`

## 9) TLS / Certificates
If you expose this ingress publicly, configure TLS before production.

### Option A: Google-Managed Certificate (Recommended)
**Console Path:**
Google Cloud Console -> Network Services -> Load balancing  
and DNS path: Google Cloud Console -> Network Services -> Cloud DNS

**Steps:**
1. Reserve static external IP for ingress (recommended for stable DNS target).
2. Create DNS `A` records:
   - `workboots.example.com`
   - `dev.workboots.example.com`
   pointing to ingress IP.
3. Configure managed certificate strategy for your ingress path.
4. Wait for certificate provisioning.
5. Verify HTTPS endpoint and certificate status.

**Copy This Value:**
- Ingress external IP
- DNS record targets
- Managed certificate resource name

**Used In:**
- HTTPS for hosts defined in overlays
- Required for reliable HSTS behavior

### Option B: Manual TLS Secret
**Console Path:**
Google Cloud Console -> Kubernetes Engine -> Workloads -> your cluster -> Config & Storage -> Secrets

**Steps:**
1. Obtain TLS cert + private key from your CA.
2. Create secret in target namespace:
   ```bash
   kubectl -n work-boots create secret tls work-boots-tls \
     --cert=fullchain.pem \
     --key=privkey.pem
   ```
3. Add/patch ingress TLS section to reference `work-boots-tls`.
4. Apply overlay and verify HTTPS.

**Copy This Value:**
- TLS secret name (`work-boots-tls`)

**Used In:**
- Ingress TLS termination when using manually managed certs

## 10) Redis + Security Controls (Critical)
Why Redis matters in this repo:
- Session/revocation and rate-limiting controls are expected to be distributed for multi-pod runtime.
- Pilot/prod posture is fail-closed for Redis-backed controls.

Required settings (set for pilot/prod):

```env
RATE_LIMIT_BACKEND=redis
SESSION_STATE_BACKEND=redis
RATE_LIMIT_FAIL_OPEN=false
SESSION_STATE_FAIL_OPEN=false
```

Where to set:
- Base defaults exist in `infra/k8s/base/configmap.yaml`
- Secret provides `REDIS_URL` in `work-boots-secrets`
- `.env.example` documents the same production posture

Consequences if misconfigured:
- Missing/invalid `REDIS_URL` with fail-closed settings -> auth/security flows can fail (intended safer behavior).
- `*_FAIL_OPEN=true` in prod -> requests may succeed during Redis outages, reducing security guarantees.
- `*_BACKEND=inmemory` in multi-pod prod -> inconsistent enforcement across pods.

## 11) Common Failure Modes (Cause + Fix)
### 11.1 Google Auth Failure In Workflow
Cause:
- Wrong `GCP_WIF_PROVIDER` or `GCP_WIF_SERVICE_ACCOUNT`
- Workflow expecting WIF but configured with wrong/unused `credentials_json` mode
- missing `id-token: write` permission
- WIF provider attribute condition excludes current branch/repo

Fix:
1. Re-check provider resource string and SA email in GitHub secrets.
2. Confirm deploy job has:
   - `permissions: id-token: write`
3. In GCP, verify provider condition matches:
   - repository `mhanson13/work-boots`
   - branch rule if configured.

### 11.2 Secrets Missing In Pull Request Runs
Cause:
- GitHub does not expose repository secrets to untrusted fork workflows by default.

Fix:
1. Run deploy workflow from trusted branches in base repo.
2. Do not rely on fork PR workflows for deployment jobs.

### 11.3 Wrong Cluster Name Or Region
Cause:
- `GKE_CLUSTER`/`GKE_LOCATION` secret mismatch.

Fix:
1. Open GKE cluster details.
2. Copy exact cluster name and region.
3. Update GitHub secrets.

### 11.4 Redis Not Reachable
Cause:
- `REDIS_URL` missing/incorrect
- network path from GKE pods to Redis blocked

Fix:
1. Verify `REDIS_URL` in `work-boots-secrets`.
2. Verify service/network/firewall connectivity from cluster.
3. Check API logs for redis backend initialization errors.

### 11.5 Migration Job Fails
Cause:
- bad `DATABASE_URL`
- DB user lacks migration permissions
- schema conflict

Fix:
1. Inspect migration job logs/events.
2. Validate DB connectivity and credentials.
3. Run `alembic upgrade head` manually against target DB before redeploy.

### 11.6 TLS Certificate Not Provisioning
Cause:
- DNS not pointing to ingress IP
- certificate domain mismatch
- ingress TLS config incomplete

Fix:
1. Verify DNS records for `dev.workboots.example.com` and `workboots.example.com`.
2. Verify ingress external IP and host mapping.
3. Verify certificate resource/secret is correctly attached.

## 12) Step-By-Step Setup Sequence (Copy/Paste Checklist)
1. Create/select GCP project and enable billing.
2. Enable required APIs (Section 4).
3. Create Artifact Registry Docker repository.
4. Create GKE Autopilot cluster.
5. Create Workload Identity Pool and Provider.
6. Create deployer service account and grant required roles.
7. Grant `roles/iam.workloadIdentityUser` binding from WIF principal set to deployer SA.
8. Add required GitHub repository secrets (Section 6).
9. Create/update Kubernetes secret `work-boots-secrets` in `work-boots-dev` and `work-boots`.
10. Confirm overlays/namespaces:
    - dev -> `work-boots-dev`
    - prod -> `work-boots`
11. Configure DNS + TLS for ingress hostnames.
12. Trigger deploy:
    - GitHub -> Actions -> `deploy-gke` -> `Run workflow` -> choose `dev` first.
13. Validate rollout:
    - deployments healthy
    - migration job completed
    - `/health` reachable via ingress
14. Promote to `prod` only after dev validation succeeds.

## 13) Cross References
- Deployment pipeline reference: `docs/deployment-gke-cicd.md`
- Phase 4 roadmap: `docs/phase4-platform-operationalization-roadmap.md`
- Security architecture: `docs/security-architecture.md`
- Runtime validation runbook: `docs/phase4-runtime-validation-runbook.md`
- Workflow sources:
  - `.github/workflows/deploy-gke.yml`
  - `.github/workflows/backend-ci.yml`
  - `.github/workflows/frontend-ci.yml`
