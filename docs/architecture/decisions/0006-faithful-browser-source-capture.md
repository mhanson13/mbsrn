# ADR 0006: Isolated faithful browser source capture

Status: Accepted and implemented; production rollout pending  
Date: 2026-08-28

## Decision

Faithful source capture is an optional, asynchronous ingestion mode. The API records a durable capture run and a dedicated worker renders the authorized public site with headless Chromium. The API does not run a browser in its request-serving Pods.

The worker runs as a non-root user in GKE Sandbox (`runtimeClassName: gvisor`) and explicitly enables Chromium's sandbox. It accepts only public HTTP(S) source URLs without credentials, pins the authorized host's public DNS addresses for the browser process, and permits navigation only between the exact source host and its `www` equivalent on bounded ports. External requests are blocked and reported.

Captured rendered pages and first-party assets are written to the private, versioned migration-media bucket. Every retry uses a new attempt prefix. The manifest is written last and freezes each object's source URL, final URL, content type, byte length, SHA-256 digest, storage generation, and provenance. A completed capture updates the workspace only when it is still the site's latest requested capture.

Operators must acknowledge authorization before `faithful_snapshot` can be queued. Forms, authentication, commerce, uploads, embedded applications, streaming media, WebSockets, and other server behavior are limitations to report, not behavior to clone. `analyze_rebuild` remains the default mode.

## Consequences

- Browser crashes and long crawls are isolated from API availability and can be retried from database state.
- Source baselines are immutable inputs. AI-generated drafts can quote bounded rendered context, but cannot overwrite captured objects or their manifest.
- Cross-domain runtime dependencies are deliberately excluded; the operator sees concise limitation codes and can collect separate administrator diagnostics when needed.
- Production deployment requires the capture worker image, migration `0064_faithful_source_captures`, GKE Sandbox support, database access, and the existing bucket-scoped Workload Identity permissions.

References: [Playwright Docker guidance](https://playwright.dev/python/docs/docker) and [GKE Sandbox](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/sandbox-pods).
