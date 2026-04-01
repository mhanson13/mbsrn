# Recommendation Bulk Actions Runbook

## Purpose

Prevent and diagnose API/database pool pressure caused by large recommendation bulk actions (for example, accepting 50+ recommendations at once).

## Current Processing Model

- Bulk recommendation updates are queued client-side with a fixed concurrency cap of `4`.
- Queue execution uses shared helper `frontend/operator-ui/lib/bulkActionQueue.ts` so other mass-action flows can reuse the same bounded pattern.
- The queue surfaces live progress:
  - total selected
  - processed
  - succeeded
  - failed
- Rows are updated optimistically while processing.
- A full recommendations refresh runs once after batch completion when at least one update succeeds.

## Why This Guardrail Exists

Without queueing, a large bulk action can send one authenticated mutation request per item in parallel. Each request still runs normal tenant/principal DB dependencies, which can exhaust SQLAlchemy QueuePool capacity under burst load.

## Operator-Visible Behavior

- Bulk action button remains enabled only when no batch is already running.
- In-flight progress appears in the queue controls area.
- Completion summary is explicit (for example, `Bulk accepted complete: 47/63 succeeded, 16 failed.`).
- Failed updates are re-selected to support retry/follow-up.

## Production Verification Checklist

1. Trigger a controlled large bulk action in a safe tenant (for example, 40-70 recommendations).
2. Confirm UI progress increments while processing (not a single frozen request burst).
3. Confirm a single completion summary appears with succeeded/failed counts.
4. Confirm failed rows remain selected.
5. Confirm list refresh happens once at batch completion (not after every row).

## Pool Timeout Observability

When pool pressure occurs, backend logs emit:

- `database_pool_timeout`
- `method`
- `path`
- `app_env`
- `db_connection_mode`
- `host`
- `port`

The API returns:

- HTTP `503`
- `detail=Database temporarily unavailable due to pool pressure. Please retry.`

## Troubleshooting

If bulk updates still fail at high rates:

1. Verify the frontend build contains the bounded queue logic (concurrency cap `4`).
2. Check whether multiple browser tabs are executing separate bulk actions concurrently.
3. Inspect API logs for repeated `database_pool_timeout` entries on recommendation patch routes.
4. Confirm no client-side retry loop is reissuing failed mutations aggressively.
5. If needed, retry only failed rows instead of rerunning the full original selection.
