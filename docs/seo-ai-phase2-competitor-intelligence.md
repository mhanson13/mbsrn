# SEO.ai Phase 2: Competitor Intelligence Engine

Status: Draft  
Owner: Work Boots  
Depends on: Phase 1 + Phase 1.5 SEO.ai on `main`  
Scope: Competitor sets, snapshotting, deterministic comparison, AI gap summary

---

## 1. Overview

Phase 2 extends SEO.ai from single-site auditing into competitor intelligence.  
The goal is to let each business compare its site against manually managed competitor domains, persist deterministic comparison data, and generate AI summaries grounded in stored comparison records.

This phase stays inside the current FastAPI monolith and business-scoped API pattern.

---

## 2. Scope Lock

### In scope
- Competitor domain registration (business-scoped)
- Optional manual competitor sets per tracked site
- Competitor page snapshot runs (bounded crawl/snapshot behavior)
- Deterministic comparison dimensions and gap finding records
- AI summarization of deterministic competitor gaps
- Business-scoped storage and APIs

### Out of scope
- Automatic SERP scraping/discovery
- Rank tracking
- Backlink analysis
- Content generation
- Publishing to external CMS
- New infrastructure (queues, workers, microservices)

---

## 3. Product Goals

### Primary goals
- Store and manage competitor sets for each business/site
- Capture repeatable competitor snapshots for comparison
- Produce deterministic gap findings against the client site
- Generate plain-English AI summaries from deterministic results

### Non-goals for this phase
- Building a full market intelligence platform
- Automating competitor discovery
- Any recommendation/content-authoring workflows (Phase 3+)

---

## 4. Core Workflows

### 4.1 Competitor setup
1. User selects a site.
2. User creates or selects a competitor set.
3. User adds competitor domains manually.

### 4.2 Snapshot run
1. User triggers a competitor snapshot run.
2. System snapshots homepage + bounded internal pages per competitor domain.
3. Snapshot data is persisted with run status and diagnostics.

### 4.3 Deterministic comparison run
1. User triggers a comparison run for a completed snapshot run.
2. System computes deterministic dimensions and stores findings.
3. Findings are retrievable via business-scoped APIs.

### 4.4 AI summary
1. User manually triggers summary generation for a completed comparison run.
2. AI summarizes deterministic findings only.
3. Versioned summaries are persisted; failures do not invalidate comparison data.

---

## 5. Deterministic Comparison Dimensions (Phase 2)

Minimum deterministic dimensions:
- Service-page coverage count
- Presence of core pages: `about`, `contact`, `faq`, `reviews/testimonials`, `process`
- Local-intent coverage (city/state/location mentions)
- Metadata coverage and duplication indicators
- Heading structure quality (H1/H2 presence)
- Visible content depth proxy (word-count thresholds)
- Internal-link density proxy

Comparison output should include:
- client metric value
- competitor metric value(s)
- gap direction (`client_trails`, `client_leads`, `parity`)
- deterministic evidence (URLs/metric counts)

---

## 6. AI Usage Boundary

AI is allowed only for summarization:
- executive competitor gap summary
- top opportunities
- concise next-step framing

AI must not:
- invent competitor pages not present in stored snapshots
- generate recommendations beyond deterministic evidence
- generate publish-ready content

---

## 7. Business Scoping and Security

- All records must include `business_id`.
- Route layer must continue using `TenantContext`.
- Service/repository methods must enforce business-scoped reads/writes.
- Cross-business access must return `404`/forbidden behavior consistent with current patterns.
- Snapshot fetching must preserve existing SSRF protections used by SEO crawlers.

---

## 8. Run Lifecycle States

### Snapshot runs
- `queued`, `running`, `completed`, `failed`

### Comparison runs
- `queued`, `running`, `completed`, `failed`

### Gap summary records
- `completed`, `failed` with version history

---

## 9. Observability Requirements

Log with identifiers:
- `business_id`
- `site_id`
- `competitor_set_id`
- `snapshot_run_id` / `comparison_run_id`
- lifecycle transitions
- failure reasons

Persist diagnostics:
- domains targeted
- pages attempted/captured/skipped
- fetch or parse error counts
- run duration

---

## 10. API Design Principles

- Keep route handlers thin.
- Keep deterministic logic in services.
- Keep provider-specific AI code in `integrations/`.
- Manual-trigger summary endpoint only for Phase 2.
- Reuse Phase 1 endpoint style and response patterns.

---

## 11. Delivery Slices (One PR Each)

1. Data foundations for competitor entities
2. Competitor set/domain management APIs
3. Snapshot engine + snapshot APIs
4. Deterministic comparison engine + comparison APIs
5. AI gap summary integration + tests/docs hardening

