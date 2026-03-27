# GCP Logging Runbook

## Time Filtering Behavior

The admin `GCP Logs Query` tool always sends an explicit time constraint to Cloud Logging:

- If `Start Time` / `End Time` are both blank, the backend applies a visible default window of the last 24 hours.
- If `Start Time` is provided, the query includes `timestamp >= "<start_time>"`.
- If `End Time` is provided, the query includes `timestamp <= "<end_time>"`.
- If both are provided, both constraints are applied.

The backend response includes `effective_filter`, and the UI displays it so operators can confirm the exact filter sent to `entries.list`.
When either `Start Time` or `End Time` is supplied, `default_time_range_applied` is `false` and the default 24-hour window is not used.

## Override The Default Window

To search outside the default 24-hour window:

1. Set `Start Time (UTC, optional)` and/or `End Time (UTC, optional)` in ISO-8601 format.
2. Run the query.
3. Confirm the rendered `Effective Filter` line includes your timestamp bounds.

Example UTC values:

- `2026-03-20T00:00:00Z`
- `2026-03-27T12:30:00Z`

## Debug Missing Logs

If expected logs are missing:

1. Check the UI `Effective Filter` value first.
2. Verify whether the default 24-hour window was applied.
3. Expand the time range explicitly (for example, set `Start Time` to 7 days ago).
4. Re-run and confirm updated timestamp clauses are reflected in `effective_filter`.

## Guardrail

Time constraints must be operator-visible. Hidden timestamp filtering should never be added.
