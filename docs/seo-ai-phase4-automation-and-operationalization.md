# SEO.ai Phase 4: Automation and Operationalization

## Scope
Phase 4 operationalizes the existing SEO.ai pipeline inside the FastAPI monolith without changing the deterministic-first architecture.

Implemented in this phase:
- persisted site-level automation configuration
- persisted automation run history with step-level status tracking
- manual trigger API for site automation runs
- scheduler-ready due-config execution path
- strict business/site scoping and lineage validation
- duplicate active-run prevention per business/site

## Architecture Boundaries
Phase 4 keeps current boundaries intact:
- deterministic services remain the source of truth for audits, comparison runs, and recommendations
- AI remains downstream only for summaries/narratives of persisted outputs
- automation orchestrates existing services; it does not reimplement audit/comparison/recommendation logic
- no queues, workers, or distributed orchestration were introduced

## Pipeline Orchestration
Automation executes these steps in order:
1. `audit_run`
2. `audit_summary`
3. `competitor_snapshot_run`
4. `comparison_run`
5. `competitor_summary`
6. `recommendation_run`
7. `recommendation_narrative`

Per-step behavior:
- if a step is disabled by config, it is recorded as `skipped`
- if prerequisites are missing, dependent steps are recorded as `skipped`
- if a step fails, that failure is persisted on the step
- run status is derived from persisted step outcomes (`failed`, `completed`, or `skipped`)

## Scheduler-Ready Execution
Phase 4 adds a scheduler-ready due-run path:
- configs with `is_enabled=true` and `next_run_at <= now` are eligible
- due execution can be invoked through:
  - service layer (`SEOAutomationService.run_due_configs`)
  - job wrapper (`SEOAutomationJob.run_due`)
  - API job endpoint (`POST /api/jobs/seo-automation/run-due`)

No external scheduler is required for local operation. A cron/task runner can call the due-run endpoint or invoke the service/job path.

## Operational Safety
- one active automation run (`queued` or `running`) is allowed per business/site
- manual and scheduled triggers are tracked separately (`trigger_source`)
- config stores `last_run_at`, `next_run_at`, `last_status`, and `last_error_message`
- run-level `steps_json` captures per-step status, timestamps, linked output IDs, and errors

## Deferred Work
Still intentionally out of scope:
- autonomous remediation or publishing
- distributed orchestration infrastructure
- AI-driven workflow decisions
- changes to deterministic recommendation generation semantics
