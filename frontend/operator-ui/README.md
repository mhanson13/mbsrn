# mbsrn Operator UI

Standalone Next.js operator surface for mbsrn.

## Local development

```bash
npm ci
npm run dev
```

Set environment values in `.env.local`:

- `NEXT_PUBLIC_API_BASE_URL`
- `NEXT_PUBLIC_GOOGLE_CLIENT_ID`

## Production standalone build note

This app uses Next.js `output: "standalone"`.

- `sharp` must remain installed in `dependencies` (not `devDependencies`) for image optimization in standalone runtime mode.
- The standalone build output (`.next/standalone`) includes traced runtime `node_modules` used by `server.js`; runtime images should copy that output directly.
- Branding and other static assets live under `frontend/operator-ui/public/` and are referenced by root-relative URLs (for example `/images/mbsrn-logo.jpg`).
- Standalone runtime images must copy both `.next/static` and `public/`; otherwise static image URLs can return HTML fallback responses instead of `image/*`.

Authentication flow:

1. UI collects Google ID token (Google Identity Services button or manual token input).
2. UI exchanges token with backend `POST /api/auth/google/exchange`.
3. Backend returns app access/refresh tokens bound to internal principal/business.
4. UI stores:
   - access token in `sessionStorage`
   - refresh token in memory only for the active browser session
5. UI uses bearer access token for business-scoped API calls.
6. Sign out calls `POST /api/auth/logout` and clears local session state.

## Admin GitHub publish target configuration

Admin route (`/admin`) includes a `GitHub Publish Configuration` form used by migration publish readiness/execution:

- `GitHub account/owner`
- `Default Branch`
- `Base Path`
- `Enabled`
- Effective target preview (normalized owner/branch/base path)

Validation expectations:
- when enabled, owner must use GitHub account/org shape
- when enabled, default branch is required and must use safe branch characters
- base path is normalized to `/` or `/subpath` and validated before save

API surface:
- `GET /api/admin/github-publish-config`
- `PUT /api/admin/github-publish-config`

This stores publish target metadata only. GitHub credentials remain environment-managed and are not exposed in UI.

Migration workspace boundary:
- Admin owns GitHub account/owner and runtime credential boundary.
- migration workflow runs on the dedicated route `/sites/[site_id]/migration`; the main site workspace provides status + launch only.
- migration workflow does not provide editable Admin-owned owner/base-path controls.
- operators configure workspace repository name plus optional branch override.
- migration route surfaces a merged effective target/readiness summary (admin owner + workspace repo/branch) without exposing credential material.
- deploy routing controls are Admin-owned:
  - `repo_owner`, `repo_name`, `workflow_id`, `ref`, `inputs`
- site workspace shows those deploy routing values as read-only diagnostics and only allows bounded deploy availability toggling.
- readiness UI distinguishes metadata readiness from runtime publisher capability:
  - `Runtime publisher: Ready`
  - `Runtime publisher: Credential unavailable`
  - `Runtime publisher: Invalid runtime configuration`
  - `Runtime publisher: Integration unavailable`
- deploy readiness surfaces explicit blocker guidance from backend `blocker_codes`:
  - `published_artifact_missing` -> published artifact required before deploy
  - `deploy_configuration_missing` / `deploy_configuration_invalid` -> admin deploy-target configuration action required
  - `deploy_runtime_unavailable` / `deploy_integration_unavailable` -> platform/runtime deploy wiring action required
- analytics insertion mode + GA measurement fields are workspace-level settings and persist after save/reload.
- approve/publish/deploy control enablement follows backend readiness prerequisites from refreshed summary state.
- publish readiness requires both merged target metadata and runtime publisher capability (`MIGRATION_GITHUB_TOKEN` and valid runtime publisher wiring).
- migration workspace now shows an explicit effective destination summary:
  - draft preview availability
  - expected publish destination (owner/repo/branch/path and derived repository URL when determinable)
  - expected published site URL (deterministic target config)
  - resolved live URL (deploy metadata/result when available)
  - URL source labeling (`deterministic_target_config`, `deploy_result`, `workflow_output`, `unknown`)
  - deterministic target URLs remain expected guidance; only deploy-result/workflow-output URLs are treated as confirmed live URLs
- migration deploy section includes a manual `Refresh Deploy Status` action:
  - re-checks stored workflow-run metadata without re-dispatching deploy
  - updates workflow run status/conclusion when execution progresses
  - promotes confirmed live URL only when explicit workflow completion output evidence is found
  - surfaces safe no-change states when run metadata/target metadata is not yet available
- migration draft preview is rendered from selected artifact content in a sandboxed iframe and is always labeled as draft-only (not published, not deployed).
- draft preview supports whole-site navigation through generated HTML pages when the artifact includes multiple pages.
- artifact file preview supports explicit hide/show controls so operators can collapse preview output without losing selected file context.
- eligible unpublished draft artifacts can be deleted from the migration route; artifacts referenced by publish/deploy history or already published remain protected.
- migration analytics rules hydrate from authoritative workspace/site GA values and persist after save/reload.

Google Profile naming and placement:
- top-level navigation and page labels use `Google Profile`.
- `/google-profile` is the primary route; `/business-profile` remains compatibility path.
- GA4 property setup is owned by Google Profile and removed from the site workspace surface.

## Shared workspace/page composition primitives

Operator-facing routes should prefer shared presentational primitives over page-local framing:

- `OperatorPageHero`
- `OperatorPageSectionStack`
- `RouteActionCluster`
- `SectionStatusStrip`
- `WorkspaceActionBar`
- `OperatorRouteSupportState`

Usage guidance:
- use `OperatorPageHero` for route-level control surfaces (title, summary strip, key actions, next-step visibility)
- use `OperatorPageSectionStack` to enforce consistent section rhythm after hero surfaces
- use `RouteActionCluster` for hero-adjacent action hierarchy (primary, secondary, and contextual shortcuts) before dropping to page-local action rows
- use `SectionStatusStrip` for section-level high-signal status/count context when sections are operationally dense
- use `WorkspaceActionBar` to separate primary vs secondary action groups
- use `OperatorRouteSupportState` for loading/error/missing-id support states on detail/workspace routes
- keep high-traffic operator routes (including `/automation`) in a control-surface cadence: hero -> primary actions -> section stack (operations, outcomes, history)
- on `/recommendations`, keep a decision-first cadence: hero -> queue controls -> quick scan -> execution/history -> secondary outcome snapshot
- keep shared shell + dashboard cadence aligned with upgraded route surfaces:
  - shell route-context rail (current area + quick guidance)
  - dashboard priority lane (what matters now)
  - launchpad lane (direct workflow entry)
  - secondary lane (activity/context signals)

Role-aware boundary:
- these primitives are shared presentation scaffolding for Operator/Admin/User-adapted pages.
- keep business/workflow semantics in route/domain logic; primitives remain presentational.
- avoid embedding Operator-only assumptions into shared shell/layout framing; role intent belongs in route/domain composition.
