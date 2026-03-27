# MBSRN - Feature Overview

## Core Purpose

MBSRN is an AI-powered operator platform that helps small, local businesses understand their market, identify competitors, and take clear, actionable steps to grow.

It transforms a business's website and market context into structured insights and practical recommendations.

---

## 1. Market and Competitor Intelligence

### What it does
- Identifies real competitors in the same service area and geography
- Generates structured competitor profile candidates for operator review
- Filters out:
- directories (e.g., Yelp, Angi)
- duplicates
- irrelevant industries

### Key capability
- Works in both:
- search-backed mode (higher accuracy)
- non-search fallback mode (resilient execution)

### Operator value
> "Who am I actually competing with locally?"

---

## 2. Site and SEO Visibility Analysis

### What it does
- Crawls and analyzes the business website
- Extracts:
- service focus
- geographic targeting
- content coverage
- Identifies visibility gaps relative to competitors

### Key capability
- Converts raw site structure into actionable SEO insight

### Operator value
> "Why am I not showing up, and what's missing?"

---

## 3. AI-Driven Recommendations Engine

### What it does
- Generates prioritized, actionable recommendations based on:
- site audit results
- competitor landscape
- business context

### Examples
- "Create a dedicated 'Kitchen Remodeling in Loveland' page"
- "Add location-specific service pages"
- "Improve homepage service clarity"

### Key capability
- Recommendations are:
- contextual
- specific
- easy to understand (non-technical)

### Operator value
> "What should I do next to get more customers?"

---

## 4. Recommendation Execution Workflow

### What it does
- Allows operators to:
- generate recommendations
- apply them
- track outcomes

### Key capability
- Enforces prerequisites (e.g., audit required before recommendations)
- Tracks:
- what was applied
- when it was applied
- expected impact timing

### Operator value
> "What changed, and what will happen because of it?"

---

## 5. Prompt and AI Configuration Control (Admin)

### What it does
- Admin controls for:
- overriding AI prompts
- tuning competitor and recommendation behavior
- configuring crawl limits and inputs

### Key capability
- Prompt versioning with override support
- Real-time tuning without redeploy

### Operator value (internal)
> "We can evolve the product without changing code."

---

## 6. Observability and Debugging

### What it does
- Structured logging across:
- provider calls
- candidate generation
- filtering pipeline
- Admin UI for querying GCP logs

### Key capability
- Visibility into:
- why competitors were rejected
- failure types (timeout, malformed output, filtering)
- execution paths (fast, full, degraded)

### Operator value (internal/platform)
> "We can diagnose issues without guessing."

---

## 7. Resilient AI Execution Model

### What it does
- Multi-tier execution strategy:
- fast path (deterministic, low latency)
- full path (tool-enabled, higher quality)
- degraded fallback (safe completion)

### Key capability
- Prevents:
- total failures
- repeated timeouts
- broken user experience

### Operator value
> "The system works reliably, even when AI tools are limited."

---

## 8. Safe Data Handling and Validation

### What it does
- Validates AI output before use
- Filters:
- malformed candidates
- incomplete entries
- Prevents invalid data from surfacing

### Key capability
- Distinguishes between:
- malformed output
- valid empty results
- filtered candidates

### Operator value
> "The results are trustworthy, not hallucinated."

---

## 9. Context-Aware Intelligence

### What it uses
- Business context:
- industry
- services
- location (ZIP, region)
- Website data
- Competitor signals

### Key capability
- Tailors all outputs to local market reality

### Operator value
> "This is specific to my business, not generic advice."

---

## 10. End-to-End Operator Workflow

### Flow
1. Business onboarded
2. Website analyzed
3. Competitors identified
4. Visibility gaps surfaced
5. Recommendations generated
6. Actions applied
7. Outcomes tracked

---

## Summary

MBSRN transforms a small business from:

> "I don't know why my business isn't growing"

into:

> "I know exactly what to fix next - and why."

---

## One-Line Positioning

**MBSRN is an AI-powered growth console that converts a business's website and market into clear competitors, actionable recommendations, and measurable next steps.**
