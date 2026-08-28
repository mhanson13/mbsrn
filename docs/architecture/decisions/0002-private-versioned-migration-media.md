# ADR 0002: Private, versioned migration media

Status: Accepted and implemented at the storage boundary  
Date: 2026-08-28

## Decision

Production migration source bytes are stored in a private, versioned GCS bucket through an injected storage contract. Media metadata records the provider, bucket, object key, generation, byte length, and SHA-256 digest. Reads are generation-pinned and byte length/digest are verified before artifact materialization.

API responses expose authenticated preview endpoints and omit storage coordinates and checksums. Local filesystem storage remains available only for development and isolated tests.

Media is materialized while a new draft artifact is generated. Approval rejects incomplete packages. Publication reads only the frozen artifact files and manifest; it never re-reads current workspace media or repairs an approved artifact in place.

## Consequences

Requests no longer require pod affinity. A missing generation or integrity mismatch blocks materialization rather than silently publishing incomplete assets. Operators repair or replace workspace media and generate a new draft. Active objects have no automatic deletion policy; noncurrent generations expire after 90 days.
