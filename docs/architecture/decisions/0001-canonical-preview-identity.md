# ADR 0001: Canonical preview identity

Status: Accepted, implementation pending  
Date: 2026-08-28

## Decision

Every site has an explicit, tenant-scoped `preview_slug`. The resolved preview hostname is `<preview_slug>.site.mbsrn.com`. The slug is operator-editable until the first preview infrastructure mutation and locked afterward.

Repository, DNS, TLS, Kubernetes, and verification integrations receive this resolved identity explicitly. They do not derive independent hostnames from the source domain or repository name. Repository name remains separately configurable and defaults to the slug.

## Consequences

Existing sites require a non-mutating backfill/confirmation step. A later rename is an infrastructure migration, not an ordinary site edit. Platfire uses `platfire` only as the first acceptance value; no runtime Platfire branch is permitted.
