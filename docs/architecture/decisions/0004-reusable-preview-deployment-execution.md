# ADR 0004: Reusable preview deployment execution

Status: Accepted, implemented behind an opt-in compatibility gate  
Date: 2026-08-28

## Decision

Site repositories call one reviewed reusable deployment workflow. Google access uses short-lived GitHub OIDC Workload Identity Federation credentials restricted by trusted repository owner and reusable workflow identity.

Site repositories contain release content and bounded configuration, not generated copies of infrastructure workflow logic. New preview deployment paths do not receive long-lived Google service-account JSON keys.

## Consequences

Deployment behavior can be reviewed and upgraded centrally. The reusable workflow, bounded caller renderer, and WIF bootstrap are implemented. The current per-site workflow renderer and `GCP_DEPLOY_KEY` propagation remain compatibility-only until Platfire and an unrelated site pass replacement acceptance criteria.
