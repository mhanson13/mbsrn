# ADR 0003: Preview certificate custody

Status: Superseded by ADR 0007; compatibility path only
Date: 2026-08-28

This decision describes the currently deployed rollback path. It is no longer the target for preview sites. See [ADR 0007](0007-shared-managed-preview-edge.md).

## Decision

MBSRN uses self-signed, global Compute `SELF_MANAGED` certificates only for preview hosts under `*.site.mbsrn.com`. The API certificate service generates or imports the key pair, validates it, writes it to Secret Manager, publishes the Compute resource, and records sanitized metadata.

Certificate private keys do not transit GitHub, API responses, diagnostics, or logs. Existing exact-host or wildcard self-managed resources may be adopted after type and hostname validation. Customer production-domain managed certificates remain a separate future workflow.

## Consequences

The API workload identity needs narrow Secret Manager create/version and Compute SSL certificate create/get capabilities. Replacement resources are retained until endpoint fingerprint verification succeeds.
