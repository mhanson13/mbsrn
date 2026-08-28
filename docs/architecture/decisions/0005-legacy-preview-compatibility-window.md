# ADR 0005: Legacy preview compatibility window

Status: Accepted  
Date: 2026-08-28

## Decision

Legacy migration publish/deploy routes remain as adapters until the preview-release API has completed Platfire acceptance, one unrelated-site dry run, two production releases, and 30 consecutive days with no observed legacy-only call. Removal requires route telemetry review and a documented rollback point.

Per-site generated workflows and preview Kubernetes `ManagedCertificate` behavior remain only until the reusable workflow and self-managed certificate path pass the same two-site acceptance. No new site is intentionally enrolled in a legacy path during the window.

## Consequences

Compatibility code has explicit removal gates instead of becoming permanent. Historical action JSON remains readable but cannot be the source of truth for new release state.
