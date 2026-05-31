# Platform-Owned `www.mbsrn.com` Managed Site

## Purpose
This document defines the repository/domain boundary for the platform-owned public website target.

## Source-Of-Truth Boundary
- `mhanson13/mbsrn` remains the authenticated MBSRN app/control-plane source repository.
- `app.mbsrn.com` remains served from the control-plane deployment path tied to `mhanson13/mbsrn`.
- `mhanson13/mbsrn-www` is a managed target repository for public website artifacts only.
- `www.mbsrn.com` is the intended public marketing hostname for artifacts published to `mhanson13/mbsrn-www`.

What does **not** move to `mhanson13/mbsrn-www`:
- backend API/control-plane code
- operator/admin UI source
- migration orchestration/control-plane logic
- control-plane CI/CD ownership

## Managed Publish Target Contract
For the platform-owned public site, use the existing migration publish-target model (no special-case code path):
- GitHub owner/account: `mhanson13` (Admin-owned baseline)
- repository name: `mbsrn-www` (workspace/site-scoped target)
- default branch: `main`
- preview hostname: continue using managed preview host (`*.site.mbsrn.com`) until manual DNS cutover
- customer domain target: `www.mbsrn.com`

If an MBSRN site record already exists, reuse/update it. Do not create a duplicate site record for this platform-owned public site.

## Workflow And Roles
- Operator:
  - prepares/reviews migration requirements and artifacts
  - sets site-scoped repository name/branch override as allowed by workspace ownership
- Admin:
  - owns account/owner baseline and final publish/deploy controls
  - confirms platform-owned target and cutover readiness

Publish/deploy semantics are unchanged:
- publish is explicit and writes reviewed artifacts to target repo
- deploy is explicit and separate
- publish does not equal production cutover

## Media Artifact Requirement
For `mhanson13/mbsrn-www`, selected migration media must ship with the generated artifact package:
- generated HTML must use deployable static image paths (for example `assets/images/...`)
- selected usable images included in draft are materialized automatically into artifact files during generation
- internal media IDs/placeholders (such as `upl-...` or unresolved `@image(...)`) are not cutover-ready
- publish output must contain both page files and referenced image files
- operators should not manually upload/copy migration images into the GitHub target repository

Cutover/readiness remains blocked when media is unresolved or missing from artifact files, even if draft text generation otherwise succeeds.

## DNS Cutover
DNS changes are manual and out of scope for this pass.

Recommended sequence:
1. Generate + review artifact.
2. Publish to `mhanson13/mbsrn-www`.
3. Deploy and validate preview/runtime behavior.
4. Perform manual DNS cutover for `www.mbsrn.com` when approved.

## Rollback
- Repository rollback: redeploy previous known-good artifact/revision from `mhanson13/mbsrn-www`.
- DNS rollback: point `www.mbsrn.com` back to prior known-good endpoint if needed.
- Control plane (`app.mbsrn.com`) remains on `mhanson13/mbsrn` throughout.

## Security Boundary For Public Artifacts
Public site artifacts must not include:
- operator/admin routes
- control-plane API internals
- private diagnostics
- secrets/tokens/credentials

The migration review/publish controls remain in the authenticated control-plane app.
