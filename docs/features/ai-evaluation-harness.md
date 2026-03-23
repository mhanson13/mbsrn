# AI Evaluation Harness

## Overview
This is an internal, fixture-based evaluation harness for AI output quality in two pipelines:
- competitor discovery
- recommendation narrative quality

It is designed for regression/comparison after prompt/model/config changes. It is not a product feature.

## Scope
- No API endpoints
- No database writes
- No UI
- No schema changes
- No runtime behavior changes

## Fixture Location
- `app/tests/fixtures/ai_eval/competitor_cases.json`
- `app/tests/fixtures/ai_eval/recommendation_cases.json`

Each file contains a `cases` array with:
- `case_id`
- `description`
- `input` context
- `expected` quality annotations used by deterministic scorers

## How To Run

Run both pipelines:
```bash
python -m app.cli.seo_ai_quality_eval --pipeline all
```

Competitor only:
```bash
python -m app.cli.seo_ai_quality_eval --pipeline competitor
```

Recommendations only:
```bash
python -m app.cli.seo_ai_quality_eval --pipeline recommendations
```

JSON output:
```bash
python -m app.cli.seo_ai_quality_eval --pipeline all --json
```

## Scoring Model

### Competitor scoring
Heuristic checks emphasize precision and false-positive control:
- forbidden domains/substrings
- existing/site domain leakage
- forbidden competitor types
- missing location/service signals
- candidate-count bounds
- optional known-good domain bonus

### Recommendation scoring
Heuristic checks emphasize specificity and grounding:
- generic phrase penalties
- missing required topics
- missing recommendation reference signals
- duplicate themes/actions
- narrative length and action-count sanity

## Output
Plain-text summary by default:
- pipeline
- total/passed/failed
- aggregate score
- per-case pass/fail, score, short reasons

Optional JSON output is available for local diffing and comparison.

## Safety / Privacy
- Raw supplemental prompt text is not printed by this harness.
- This harness is intended for synthetic/local fixture contexts.
- It does not replace human review of AI quality.

## Limitations
- Heuristic scoring is directional, not absolute truth.
- Open-ended generation can vary across providers/models.
- Use this as a regression signal plus manual review, not as a hard quality guarantee.
- Context contract changes (for example site/locality/service context normalization) should be evaluated with before/after harness runs to confirm directional quality impact.
