# Operator Layout Primitives

Use these shared primitives first for page structure and layout consistency:

- `PageContainer`: top-level page rhythm/container
- `SectionCard`: section framing/card treatment
- `FormContainer`: consistent form width/spacing
- `OperatorPageHero`: standardized top-level route hero/title/subtitle composition
- `OperatorPageSummaryStrip`: standardized summary-strip wrapper for hero stats
- `OperatorPageSectionStack`: standardized post-hero section cadence

Prefer shared utility classes from `app/globals.css` for common layout patterns:

- `row-wrap`, `row-wrap-tight`, `row-space-between`
- `metrics-grid`, `grid-fit-180`, `grid-fit-120`
- `table-container`, `table-container-compact`
- `panel-compact`, `stack-*` spacing classes

Use shared button variants from `app/globals.css` instead of page-level button tweaks:

- `button button-primary` for main CTA
- `button button-secondary` for supporting actions
- `button button-danger` for destructive/admin-sensitive actions
- `button button-tertiary` for low-emphasis utility actions
- add `button-inline` for compact table/action-column buttons

Avoid one-off layout wrappers and inline styling (`style={{ ... }}`) in `app/` and `components/`.
The regression guardrail test in `lib/validation/layout-guardrails.test.ts` enforces this and allows only explicitly documented exceptions.
