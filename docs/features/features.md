# MBSRN - Feature Overview

## Core Purpose

MBSRN is an AI-powered operator platform that helps small, local businesses understand their market, identify competitors, and take clear, actionable steps to grow.

It transforms a business's website and market context into structured insights and practical recommendations.

---

## 1. Market and Competitor Intelligence

### What it does
- Identifies real competitors in the same service area and geography
- Generates structured competitor profile candidates for operator review
- Filters out:
- directories (e.g., Yelp, Angi)
- duplicates
- irrelevant industries

### Key capability
- Works in both:
- search-backed mode (higher accuracy)
- non-search fallback mode (resilient execution)

### Operator value
> "Who am I actually competing with locally?"

---

## 2. Site and SEO Visibility Analysis

### What it does
- Crawls and analyzes the business website
- Extracts:
- service focus
- geographic targeting
- content coverage
- Identifies visibility gaps relative to competitors

### Key capability
- Converts raw site structure into actionable SEO insight

### Operator value
> "Why am I not showing up, and what's missing?"

---

## 3. AI-Driven Recommendations Engine

### What it does
- Generates prioritized, actionable recommendations based on:
- site audit results
- competitor landscape
- business context

### Examples
- "Create a dedicated 'Kitchen Remodeling in Loveland' page"
- "Add location-specific service pages"
- "Improve homepage service clarity"

### Key capability
- Recommendations are:
- contextual
- specific
- easy to understand (non-technical)

### Operator value
> "What should I do next to get more customers?"

---

## 4. Recommendation Execution Workflow

### What it does
- Allows operators to:
- generate recommendations
- apply them
- track outcomes

### Key capability
- Enforces prerequisites (e.g., audit required before recommendations)
- Tracks:
- what was applied
- when it was applied
- expected impact timing

### Operator value
> "What changed, and what will happen because of it?"

---

## 5. Prompt and AI Configuration Control (Admin)

### What it does
- Admin controls for:
- overriding AI prompts
- tuning competitor and recommendation behavior
- configuring crawl limits and inputs

### Key capability
- Prompt versioning with override support
- Real-time tuning without redeploy

### Operator value (internal)
> "We can evolve the product without changing code."

---

## 6. Observability and Debugging

### What it does
- Structured logging across:
- provider calls
- candidate generation
- filtering pipeline
- Admin UI for querying GCP logs

### Key capability
- Visibility into:
- why competitors were rejected
- failure types (timeout, malformed output, filtering)
- execution paths (fast, full, degraded)

### Operator value (internal/platform)
> "We can diagnose issues without guessing."

---

## 7. Resilient AI Execution Model

### What it does
- Multi-tier execution strategy:
- fast path (deterministic, low latency)
- full path (tool-enabled, higher quality)
- degraded fallback (safe completion)

### Key capability
- Prevents:
- total failures
- repeated timeouts
- broken user experience

### Operator value
> "The system works reliably, even when AI tools are limited."

---

## 8. Safe Data Handling and Validation

### What it does
- Validates AI output before use
- Filters:
- malformed candidates
- incomplete entries
- Prevents invalid data from surfacing

### Key capability
- Distinguishes between:
- malformed output
- valid empty results
- filtered candidates

### Operator value
> "The results are trustworthy, not hallucinated."

---

## 9. Context-Aware Intelligence

### What it uses
- Business context:
- industry
- services
- location (ZIP, region)
- Website data
- Competitor signals

### Key capability
- Tailors all outputs to local market reality

### Operator value
> "This is specific to my business, not generic advice."

---

## 10. End-to-End Operator Workflow

### Flow
1. Business onboarded
2. Website analyzed
3. Competitors identified
4. Visibility gaps surfaced
5. Recommendations generated
6. Actions applied
7. Outcomes tracked

---

## 11. Controlled Website Migration Workspace (Phase 1-4)

### What it does
- Provides a site-scoped migration workspace for replacing weak incumbent SMB websites
- Captures bounded source-site signals plus operator overrides and enriched replacement content
- Reuses existing audit/recommendation/competitor summaries as migration context
- Generates draft-only static-site artifacts for operator review
- Supports explicit operator approval, GitHub publish, and GKE deploy request flows
- Preserves publish/deploy history and readiness traceability

### Key capability
- Enforces explicit trust/approval gates:
- source import is advisory
- operator input can override weak source material
- generated outputs remain operator-controlled through approval, publish, and deploy gates (no auto actions)
- Adds admin-controlled GitHub publish baseline configuration (`owner`, `default_branch`, `base_path`, `enabled`) so migration publish has an explicit control-plane dependency.
- Hardens admin GitHub publish target trust with pre-save validation, normalized effective-target preview, clearer publish/deploy readiness ownership messaging, and lightweight structured config-change logging.
- Uses split ownership for migration publish target:
- Admin owns GitHub account/owner baseline and runtime credential boundary.
- Operator owns workspace repository name plus optional branch override.
- workspace shows merged effective target/readiness context (owner + repo + branch) without exposing credential material.
- Deploy routing trust boundary is now explicit:
- Admin owns raw deploy workflow control-plane fields (`repo_owner`, `repo_name`, `workflow_id`, `ref`, `inputs`).
- Operator workspace keeps those values read-only and only exposes bounded deploy availability toggling plus staged deploy diagnostics.
- Migration publish now provisions site-specific deploy workflows from an approved MBSRN-managed template mode and records the effective workflow path in publish history for deploy traceability.
- Admin controls deploy template/environment mapping metadata (`deploy_workflow_mode`, `target_environment_key`, `target_environment_source`); operators can view the effective values read-only in workspace diagnostics.
- Readiness explicitly distinguishes merged metadata readiness from runtime publisher capability (for example credential unavailable vs runtime integration unavailable) so publish blockers map to the correct actor.
- Deploy readiness now exposes explicit blocker classes (`published_artifact_missing`, deploy target config missing/invalid, deploy runtime/integration unavailable) so deploy blockers map to the correct actor without generic "runtime missing" ambiguity.
- Runtime publisher credentials remain environment-managed (`MIGRATION_GITHUB_TOKEN`) and are never exposed through Admin/workspace payloads.
- Local development uses the same `MIGRATION_GITHUB_TOKEN` env var name (with a local test token value when needed) to avoid test/runtime naming drift.
- Production deployment injects `MIGRATION_GITHUB_TOKEN` into `mbsrn-api` through existing `mbsrn-api-auth` secret wiring; the token is not stored/editable in application UI.
- approve/publish/deploy button enablement is driven by authoritative readiness prerequisites after mutation refresh, not local stale assumptions.
- analytics insertion rules remain workspace-level controls and now persist/reload reliably after save.
- publish now enforces workflow bootstrap verification on every non-dry-run publish for target/generated repos:
  - checks/verifies `.github/workflows/{workflow_id}` on target branch
  - provisions missing workflow file before publish is considered valid
  - fails publish if provisioning cannot be verified (`workflow_provisioning_failed`)
  - keeps duplicate artifact write protection while allowing workflow-repair publishes (`duplicate_publish_repair`) when content already exists but workflow is missing
- deploy now prefers authoritative workflow identity captured at publish time (`deploy_workflow_id` / `deploy_workflow_path`) before falling back to workspace/default workflow ids, preventing stale workspace workflow drift from blocking dispatch.
- deploy now records requested-vs-used workflow identifiers (`workflow_identifier_requested`, `workflow_identifier_used`) plus identifier type/resolution source fields so dispatch by workflow id vs file-derived identifier is explicit in control-plane diagnostics.
- deploy target lookup failures are now classified with non-secret reason codes (`repo_not_found`, `workflow_not_found`, `branch_not_found_or_ref_invalid`, `workflow_not_dispatchable`, `workflow_dispatch_not_supported`, `token_not_authorized`) for clearer control-plane troubleshooting.
- deploy now emits an explicit managed-target readiness preflight (`seo_migration_target_readiness_check`) for the authoritative tuple (repo owner/name, ref, workflow id/path) so dispatch never relies on implicit repo/ref/workflow assumptions.
- deploy diagnostics now model a distinct dispatch-service availability stage (`dispatch_service_availability`, `dispatch_service_reason_code`) so operators can distinguish workflow identity/trigger support from downstream service/function readiness before dispatch.
- deploy readiness now adds deterministic workflow conformance checks (`workflow_conformance_status`, `workflow_conformance_reasons`) so placeholder/non-conformant workflow content is distinguished from deploy-capable managed workflows before or alongside dispatch attempts.
- deploy diagnostics now explicitly separate control-plane dispatch readiness from downstream target-repo workflow/runtime readiness, so a dispatchable workflow target is not over-interpreted as guaranteed GKE rollout success.
- migration workspace deploy traceability now emphasizes a copy-friendly `deploy_trace_id` plus stage-aligned status hints (`dispatch_result_stage`, no-run-yet eventual consistency guidance) to speed production log correlation during real deploy checks.
- deploy diagnostics now expose dispatch payload and post-dispatch evidence fields (`dispatch_ref_sent`, `workflow_inputs_configured_keys`, `workflow_inputs_sent_keys`, `workflow_run_lookup_attempted`, `workflow_run_found`, `workflow_job_failure_detected`, `post_dispatch_state`) so operators can distinguish accepted-no-run, run-failed, and run-in-progress outcomes without raw log inspection.
- deploy diagnostics now expose target-repo deploy evidence contract fields (`expected_workflow_outputs`, `deploy_evidence_contract_status`, `deploy_evidence_contract_reasons`, `workflow_contract_advisory`) so workflow success without explicit live evidence is distinguished from confirmed deployment.
- deploy dispatch classification now preserves preflight context so post-preflight dispatch failures are treated as workflow dispatchability problems when appropriate, instead of being mislabeled as branch/ref missing.
- workspace now surfaces effective migration destinations with explicit URL states (expected published URL vs resolved live URL), deterministic URL source labeling, and clear draft/expected/live distinction for pre-execution trust.
- deploy now performs a best-effort post-dispatch workflow-run result capture; when explicit workflow completion metadata includes a live URL signal, it is stored as `resolved_live_url` with `url_source=workflow_output`.
- migration workspace includes a manual `Refresh Deploy Status` action so operators/admins can re-check workflow-run completion metadata later without re-dispatching deploy.
- refresh updates run status/conclusion and only promotes confirmed live URL when new explicit workflow output evidence is available.
- operators can open a sandboxed draft preview of selected migration artifact content before publish/deploy; preview is explicitly read-only and non-live, supports multi-page draft navigation when artifact HTML pages are available, and keeps file preview hide/show controls in the review pane.
- migration analytics insertion controls now hydrate from authoritative workspace/site GA state and persist across save/reload without introducing a second source of truth.

### Operator value
> "I can replace a low-quality incumbent site with a structured draft package before any publication step."

---

## 12. Consistent Operator Dashboard Surfaces (UI Pattern Reuse)

### What it does
- Reuses shared operator-facing presentational primitives across high-traffic non-workspace pages:
- Dashboard
- Competitor Intelligence (`/competitors`)
- Audit Runs (`/audits`)
- Automation Run History (`/automation`)
- Recommendations Workflow (`/recommendations`)

### Key capability
- Applies the same summary/status/action/message/table rhythm used in the site workspace to adjacent operator surfaces.
- Uses shared MBSRN-native primitives (`WorkspaceActionBar`, `WorkspaceMessageStack`, `WorkspaceEmptyStateCard`, `WorkspaceTableShell`, `WorkspaceMetadataGrid`) instead of repeated page-local layout markup.
- Standardizes route-level page composition on high-traffic top-level pages using reusable page-surface wrappers:
  - `OperatorPageHero`
  - `OperatorPageSummaryStrip`
  - `OperatorPageSectionStack`
  - currently applied on `Dashboard`, `Audit Runs`, `Competitor Intelligence`, `SEO Sites`, `Automation`, and `Recommendations`.
- TailAdmin was used as visual inspiration only; implementation remains MBSRN-native with existing CSS/components.

### Operator value
> "Core operator pages now scan and behave like one coherent dashboard product."

---

## 13. Site Operator Journey and Recommendation Detail Consistency

### What it does
- Restructures the site operator route into clearer domain surfaces:
  - `Operator Focus`
  - `Recommendations`
  - `Migration`
  - `Activity`
- Promotes migration as a first-class operator workflow area on the site route.
- Aligns recommendation detail/run/narrative pages to the same page-composition rhythm used on top-level operator routes.

### Key capability
- Operators get a more predictable decision-first path from site-level triage to recommendation detail execution context.
- Shared page/workspace primitives now cover both list and detail recommendation flows.
- TailAdmin inspiration is visual only; implementation remains MBSRN-native.

### Operator value
> "I can move from site-level decisions to recommendation detail review without relearning the page structure on every route."

---

## 14. Site Operator Workspace Modernization (Decision-First Control Surface)

### What it does
- Upgrades `/sites/[site_id]` with a stronger workspace control surface using existing MBSRN-native primitives.
- Promotes migration and recommendation execution as first-class workflow lanes near the top of the route.
- Clarifies page scan order as:
  - top control surface (status + next action)
  - operational snapshot + operator focus
  - workflow tabs
  - domain execution/detail sections

### Key capability
- Reuses shared primitives (`OperatorPageHero`, `OperatorPageSectionStack`, `WorkspaceActionBar`, `OperatorRouteSupportState`) instead of page-local framing patterns.
- Improves action prominence, containment, and scanability without changing workflow semantics.
- TailAdmin remains inspiration-only; implementation stays within internal MBSRN CSS/components.

### Operator value
> "I can immediately see what matters now, what to do next, and where migration and recommendations stand."

---

## 15. Shared Shell + Dashboard Modernization

### What it does
- Modernizes shared operator chrome so upgraded routes feel coherent inside the same workspace system.
- Strengthens top-nav context with:
- current route area framing
- concise next-step guidance
- consistent session/role presentation
- Upgrades `/dashboard` into a stronger control surface with:
- explicit "what matters now" emphasis
- launchpad-style workflow lanes
- clearer separation between primary action and supporting signals

### Key capability
- Reuses existing MBSRN-native layout/workspace primitives and cadence (`OperatorPageHero`, `OperatorPageSectionStack`, `WorkspaceActionBar`, metadata/message shells) rather than page-local one-off framing.
- Keeps shared shell composition role-aware so Operator/Admin/User variants can evolve without rewriting base presentation patterns.
- TailAdmin remains visual inspiration only; implementation is internal and dependency-free.

### Operator value
> "The shell and dashboard now feel like a deliberate control console, not older chrome around newer pages."

---

## 16. Reusable Route-Level Action Cluster

### What it does
- Introduces a shared route-level action cluster primitive used near hero/control-surface areas to standardize:
- one clear primary CTA
- secondary action grouping
- contextual shortcut actions
- optional short guidance note
- Applies this action framing across modernized workspace routes (dashboard, site workspace, automation, recommendations list, and recommendation detail family) to reduce hero/action composition drift.

### Key capability
- Keeps action hierarchy predictable across routes without changing route semantics.
- Uses MBSRN-native primitives/components only; no external UI imports.
- Stays role-aware by keeping labels/semantics in route/domain code while the cluster remains presentational.

### Operator value
> "Primary and secondary actions now appear in a more consistent place and hierarchy across the workspace."

---

## 17. Reusable Section-Level Summary/Status Strip

### What it does
- Introduces a shared section-level summary/status strip primitive for dense operational sections.
- Standardizes quick-scan section cues such as:
- current status
- counts/backlog
- latest outcome/freshness
- readiness/error presence
- Applies this strip selectively in modernized routes (dashboard, automation, recommendations, and recommendation detail surfaces) where operators previously had to parse long text blocks before seeing section state.

### Key capability
- Keeps section scanability consistent after hero-level control surfaces.
- Uses a small MBSRN-native primitive (`SectionStatusStrip` + `SectionStatusItem`) rather than one-off badge/metric markup in each route.
- Remains presentational and role-aware; route/domain semantics stay in route code.

### Operator value
> "I can understand each section’s state in seconds before diving into details."

---

## Summary

MBSRN transforms a small business from:

> "I don't know why my business isn't growing"

into:

> "I know exactly what to fix next - and why."

---

## One-Line Positioning

**MBSRN is an AI-powered growth console that converts a business's website and market into clear competitors, actionable recommendations, and measurable next steps.**
