# SEO.ai Phase 2 Implementation Checklist

Status: Draft  
Owner: Work Boots  
Scope: Phase 2 only (Competitor Intelligence)

---

## 1. Scope Lock

### In scope
- Business-scoped competitor sets
- Manual competitor domain registration
- Deterministic competitor snapshot capture
- Deterministic comparison findings
- AI summaries from stored deterministic comparison findings
- Tenant-safe APIs, logging, and tests

### Out of scope
- Automatic SERP discovery/scraping
- Rank tracking
- Backlink analysis
- Content generation
- Recommendation engine
- Background workers/queue infrastructure

---

## 2. Execution Slices

### PR1: Competitor set foundations
- [ ] Data model + migration for sets/domains
- [ ] Repository methods with business-scoped guards
- [ ] API CRUD for sets/domains
- [ ] Validation and normalization

### PR2: Competitor snapshot capture
- [ ] Snapshot run model/state wiring
- [ ] Snapshot page persistence
- [ ] Deterministic bounded capture (registered competitor domains only)
- [ ] Snapshot run APIs and diagnostics

### PR3: Deterministic comparison engine
- [ ] Comparison run model/state wiring
- [ ] Deterministic comparison dimensions
- [ ] Deterministic gap finding persistence
- [ ] Comparison findings APIs

### PR4: AI competitor gap summaries
- [ ] Summary model/versioning wiring
- [ ] AI provider boundary usage
- [ ] Manual-trigger summary endpoint
- [ ] Failure isolation and history

### PR5: Hardening/tests/docs
- [ ] Tenant isolation tests
- [ ] SSRF and crawl-bound tests for competitor snapshot logic
- [ ] Logging coverage for run lifecycle and failures
- [ ] Docs/readme alignment

---

## 3. Deterministic Comparison Baseline

- [ ] Service-page coverage comparison
- [ ] Core trust/process/FAQ/about/contact coverage comparison
- [ ] Local-intent coverage comparison
- [ ] Heading/metadata/content depth proxies
- [ ] Category/severity classification on comparison findings

---

## 4. API Boundary Checklist

- [ ] All endpoints stay under `/api/businesses/{business_id}/seo/...`
- [ ] TenantContext-enforced business scoping
- [ ] No API endpoints for SERP discovery/rank/backlinks/content generation
- [ ] Manual summary trigger only

---

## 5. Definition of Done (Phase 2)

- [ ] Competitor sets/domains are business-scoped and CRUD-capable
- [ ] Snapshot runs capture deterministic competitor page data with bounded behavior
- [ ] Comparison runs produce deterministic, persisted gap findings
- [ ] AI summary is grounded in stored deterministic comparison findings only
- [ ] Tenant isolation and SSRF protections are validated by tests
- [ ] Docs reflect shipped Phase 2 behavior without scope drift

