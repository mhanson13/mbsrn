# Reusable preview deployment and Workload Identity Federation

Last updated: 2026-08-28

## Purpose

The reusable preview deployment path keeps reviewed deployment logic in
`.github/workflows/deploy-site-preview.yml`. A site repository receives only a
small `workflow_dispatch` caller and bounded site/release inputs. It never
receives a Google service-account JSON key.

This path is opt-in until Platfire and a second unrelated site pass acceptance.
When the three settings below are absent, the compatibility renderer remains
active. Partial configuration is rejected.

## Bootstrap Google trust

Run with an administrator identity that can manage IAM, service accounts, and
Workload Identity Federation:

```bash
scripts/bootstrap_preview_deploy_wif.sh \
  --gcp-project-id mbsrn-prod \
  --github-owner mhanson13
```

The script is idempotent. It creates or updates:

- a dedicated deployment service account;
- a Workload Identity Pool and GitHub OIDC provider;
- `roles/container.developer` and read-only `roles/compute.viewer` access;
- `roles/iam.workloadIdentityUser` impersonation for the trusted principal set.

The provider condition requires both the configured GitHub owner and the exact
`job_workflow_ref` for `deploy-site-preview.yml@refs/heads/main`. A workflow in
another owner, another file, or another ref cannot exchange its token through
this provider.

## GitHub prerequisites

1. Merge and publish `.github/workflows/deploy-site-preview.yml` at the trusted
   ref.
2. If `mbsrn` is private, allow the intended caller repositories to use its
   Actions and reusable workflows in repository Actions settings.
3. Add the three values printed by the bootstrap script as GitHub repository
   variables on `mbsrn`:

   - `MIGRATION_REUSABLE_DEPLOY_WORKFLOW_REF`
   - `MIGRATION_DEPLOY_WORKLOAD_IDENTITY_PROVIDER`
   - `MIGRATION_DEPLOY_SERVICE_ACCOUNT`

These values identify resources; they are not credentials or private keys. Do
not create or copy `GCP_DEPLOY_KEY` into new site repositories.

## Activation behavior

The next MBSRN application deployment passes the variables to the API. When all
three are present, subsequent preview workflow provisioning replaces an
MBSRN-managed legacy workflow with a signed reusable caller. Existing custom,
non-MBSRN workflows remain protected by the repository-adoption rules.

The central workflow:

- checks out the caller repository;
- builds and publishes the caller's site image;
- authenticates through GitHub OIDC and Google WIF;
- refuses legacy `networking.gke.io/managed-certificates` ingress bindings;
- applies only the self-managed/pre-shared-certificate runtime manifests;
- verifies static IP, DNS, exact certificate fingerprint, hostname coverage,
  and the HTTPS response.

## Verification

For the Platfire pilot, verify that the generated caller:

- references `mhanson13/mbsrn/.github/workflows/deploy-site-preview.yml@main`;
- contains `platfire.site.mbsrn.com` and the release's frozen certificate name
  and fingerprint;
- does not contain `credentials_json` or `GCP_DEPLOY_KEY`;
- completes with the release deployment and verification gates at `ready`.

Repeat with an unrelated source domain, preview slug, and repository name.

## Rollback

Clear all three `MIGRATION_REUSABLE_DEPLOY_*` repository variables and redeploy
the API. This stops new reusable callers from being provisioned. It does not
delete the WIF provider, service account, existing site workflows, releases, or
certificates. Restore the variables to resume after correction.
