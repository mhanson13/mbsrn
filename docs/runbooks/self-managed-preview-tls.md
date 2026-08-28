# Self-managed preview TLS

MBSRN uses self-signed, self-managed Google Compute SSL certificates only for `*.site.mbsrn.com` preview hosts. Customer production domains remain outside this workflow.

## Platform contract

1. Generate a certificate or import an existing certificate/key pair through the operator workspace. The API validates the self-signature, key match, validity period, and preview-host SAN.
2. The certificate and private key are stored together as a versioned Google Secret Manager secret. API responses and logs expose only certificate metadata and the SHA-256 fingerprint.
3. The public certificate and private key are uploaded to a global Compute Engine `SELF_MANAGED` SSL certificate resource through the explicit `selfManaged` request object.
4. The selected resource name is written to the site's GKE Ingress through `ingress.gcp.kubernetes.io/pre-shared-cert`. No Kubernetes `ManagedCertificate` is created or applied.
5. Deployment verifies the Compute resource type, Ingress annotation, static IP, DNS, served SAN, and exact served SHA-256 fingerprint. HTTPS probing uses explicit self-signed trust bypass only after the fingerprint check.

An existing Compute SSL certificate can also be adopted without its private key. This is recorded as external custody and cannot be vaulted unless the matching certificate/key PEM pair is imported.

## One-time Google Cloud prerequisites

- Enable the Secret Manager API in the certificate project.
- Grant the API workload identity a custom certificate-writer role containing only `secretmanager.secrets.create` and `secretmanager.versions.add`. `roles/secretmanager.admin` is not required.
- Grant `roles/secretmanager.secretAccessor` through an IAM Condition limited to Secret Manager `Secret` and `SecretVersion` resources whose names begin with the configured certificate prefix (default `mbsrn-tls-`). This permits retrying a certificate that was vaulted before Compute publication failed without exposing unrelated platform secrets.
- Grant the API workload identity a narrow role containing `compute.sslCertificates.create` and `compute.sslCertificates.get` for global Compute SSL certificate publication and adoption.
- Set `TLS_CERTIFICATE_GCP_PROJECT_ID` when it differs from `GCP_PROJECT_ID`.
- Run `alembic upgrade head` before exposing the new operator controls.

Provision or reconcile the narrow role idempotently:

```bash
scripts/bootstrap_preview_tls_permissions.sh --gcp-project-id mbsrn-prod
```

The role definition is versioned at `infra/gcp/preview-tls-operator-role.yaml`. It contains `secretmanager.secrets.create`, `secretmanager.versions.add`, `compute.sslCertificates.create`, `compute.sslCertificates.get`, and `compute.globalOperations.get`. The bootstrap script separately grants prefix-scoped `roles/secretmanager.secretAccessor`; it does not add payload-read permission to the project custom role.

Before generating certificate material, call `GET /api/businesses/{business_id}/tls/capabilities`. A ready response confirms the certificate project and workload credentials are configured. It lists the permissions that the real certificate operations require, with `verification_state=operation_required`; it does not claim that Google has authorized an operation that has not run. Secret Manager does not provide a project-level permission-test route, and Google documents `testIamPermissions` as a UI aid rather than an authorization check.

The real Secret Manager and Compute requests are authoritative. Failures distinguish unauthenticated credentials, permission denial, missing resource/API configuration, rate limiting, provider outage, timeout, and transport errors. Operator responses contain a short next action. Administrator diagnostics may include the service, operation, HTTP/provider status, retryability, and stable reason code, but never access tokens, provider response bodies, certificate PEM, or private keys.

Google Cloud request validation failures such as `INVALID_ARGUMENT` are non-retryable platform integration errors. The operator should collect diagnostics instead of repeatedly generating or publishing certificate material.

Failed release gates retain only bounded provider evidence: service, operation, HTTP/provider status, retryability, and missing permission names. The administrator bundle correlates that evidence with the release support ID and media reason counts; it never stores raw provider responses, certificate material, secret payloads, or media bytes.

Secret Manager may return a canonical version resource containing the numeric project number even when the request used the project ID. The vault loader accepts that Google-generated form, validates the secret and version path, and rebuilds the access request against the configured certificate project. A reference to another named project remains invalid.

Do not copy the certificate private key into GitHub. Existing GitHub deployment authentication remains unchanged.

References: [Google self-managed SSL certificates](https://docs.cloud.google.com/load-balancing/docs/ssl-certificates/self-managed-certs), [GKE pre-shared certificate annotation](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/secure-traffic-management), [Secret Manager least-privilege guidance](https://docs.cloud.google.com/secret-manager/docs/access-control), and [IAM resource conditions](https://docs.cloud.google.com/iam/docs/conditions-resource-attributes).

## Platfire rollout

1. Deploy the database migration and API/UI code.
2. Confirm Secret Manager API and workload identity permissions.
3. Open Platfire's operator workspace and choose **Ensure, Vault & Publish**, or import/adopt an existing self-managed certificate. Ensure reuses a valid published asset and resumes a vaulted asset after a partial Compute failure.
4. Publish the existing artifact again. Duplicate-artifact repair is allowed to reconcile the workflow and Ingress without republishing artifact content.
5. Request GKE deploy.
6. Use **Verify Served Certificate**. Success requires the endpoint fingerprint to match the selected asset.

Rollback is certificate selection, not key deletion: select the prior published asset and republish the site. Retain old Compute certificate resources and Secret Manager versions until the replacement has been verified.
