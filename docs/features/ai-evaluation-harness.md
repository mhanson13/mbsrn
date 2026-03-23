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

### Evaluation modes
- `mock` mode:
  - deterministic and CI-safe
  - uses internal mock providers only
  - default mode
- `real` mode:
  - calls configured external provider
  - requires explicit opt-in guard
  - blocked in production-like environments

Run both pipelines:
```bash
python -m app.cli.seo_ai_quality_eval --pipeline all
```

Run explicit mock mode:
```bash
python -m app.cli.seo_ai_quality_eval --mode mock --pipeline all
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

Real-provider (non-prod only, explicit opt-in):
```bash
AI_EVAL_ALLOW_REAL_PROVIDER=true \
python -m app.cli.seo_ai_quality_eval --mode real --pipeline all --json
```

Optional output file:
```bash
python -m app.cli.seo_ai_quality_eval --mode mock --pipeline all --json --output-file ./tmp/ai-eval.json
```

## Real-Mode Guardrails
- Real mode requires both:
  - `--mode real`
  - `AI_EVAL_ALLOW_REAL_PROVIDER=true`
- Real mode fails closed if:
  - provider is `mock`
  - provider config is misconfigured
  - environment is production-like (`production` / `prod`)
- The CLI never silently falls back from real mode to mock mode.

## Real-Provider Preflight Checklist
Use this checklist before running non-prod real-provider evaluation.

1. Required env vars
   - `AI_PROVIDER_NAME=openai`
   - `AI_PROVIDER_API_KEY=<provider-secret>`
   - `AI_EVAL_ALLOW_REAL_PROVIDER=true`
2. Recommended non-secret vars
   - `AI_MODEL_NAME` (default: `gpt-4o-mini`)
   - `AI_TIMEOUT_VALUE` (default: `30`)
   - `OPENAI_API_BASE_URL` (default: `https://api.openai.com/v1`)
3. Environment safety guard
   - Ensure `APP_ENV` and `ENVIRONMENT` are not `production`/`prod`.
4. Provider guard
   - Ensure `AI_PROVIDER_NAME` is not `mock` when using `--mode real`.
5. Competitor eval command
   - `python -m app.cli.seo_ai_quality_eval --mode real --pipeline competitor --json`
6. Recommendation eval command
   - `python -m app.cli.seo_ai_quality_eval --mode real --pipeline recommendations --json`
7. Optional combined run + output file
   - `python -m app.cli.seo_ai_quality_eval --mode real --pipeline all --json --output-file ./tmp/ai-eval-real.json`

Common fail-closed errors:
- `Real-provider eval is disabled...`:
  `AI_EVAL_ALLOW_REAL_PROVIDER` is unset/false.
- `requires a non-mock AI_PROVIDER_NAME`:
  provider is configured as `mock`.
- `blocked in production-like environments`:
  `APP_ENV`/`ENVIRONMENT` is production-like.
- `provider is misconfigured for 'openai'`:
  usually missing/invalid `AI_PROVIDER_API_KEY`.

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
- mode
- provider name
- model name
- total/passed/failed
- aggregate score
- per-case pass/fail, score, short reasons

Optional JSON output is available for local diffing and comparison and includes:
- `eval_mode`
- `provider_name`
- `model_name`
- aggregate and per-case results

## Safety / Privacy
- Raw supplemental prompt text is not printed by this harness.
- Raw prompt text is not logged in eval output.
- This harness is intended for synthetic/local fixture contexts.
- It does not replace human review of AI quality.

## Limitations
- Heuristic scoring is directional, not absolute truth.
- Open-ended generation can vary across providers/models.
- Use this as a regression signal plus manual review, not as a hard quality guarantee.
- Context contract changes (for example site/locality/service context normalization) should be evaluated with before/after harness runs to confirm directional quality impact.
