# Self-managed preview TLS

MBSRN uses self-signed, self-managed Google Compute SSL certificates only for `*.site.mbsrn.com` preview hosts. Customer production domains remain outside this workflow.

## Platform contract

1. Generate a certificate or import an existing certificate/key pair through the operator workspace. The API validates the self-signature, key match, validity period, and preview-host SAN.
2. The certificate and private key are stored together as a versioned Google Secret Manager secret. API responses and logs expose only certificate metadata and the SHA-256 fingerprint.
3. The public certificate and private key are uploaded to a global Compute Engine `SELF_MANAGED` SSL certificate resource.
4. The selected resource name is written to the site's GKE Ingress through `ingress.gcp.kubernetes.io/pre-shared-cert`. No Kubernetes `ManagedCertificate` is created or applied.
5. Deployment verifies the Compute resource type, Ingress annotation, static IP, DNS, served SAN, and exact served SHA-256 fingerprint. HTTPS probing uses explicit self-signed trust bypass only after the fingerprint check.

An existing Compute SSL certificate can also be adopted without its private key. This is recorded as external custody and cannot be vaulted unless the matching certificate/key PEM pair is imported.

## One-time Google Cloud prerequisites

- Enable the Secret Manager API in the certificate project.
- Grant the API workload identity a custom certificate-writer role containing only `secretmanager.secrets.create` and `secretmanager.versions.add`. `roles/secretmanager.admin` also works but is substantially broader. Do not grant secret payload read access unless a later recovery workflow actually needs it.
- Grant the API workload identity a narrow role containing `compute.sslCertificates.create` and `compute.sslCertificates.get` for global Compute SSL certificate publication and adoption.
- Set `TLS_CERTIFICATE_GCP_PROJECT_ID` when it differs from `GCP_PROJECT_ID`.
- Run `alembic upgrade head` before exposing the new operator controls.

Provision or reconcile the narrow role idempotently:

```bash
scripts/bootstrap_preview_tls_permissions.sh --gcp-project-id mbsrn-prod
```

The role definition is versioned at `infra/gcp/preview-tls-operator-role.yaml`. It contains `secretmanager.secrets.create`, `secretmanager.versions.add`, `compute.sslCertificates.create`, `compute.sslCertificates.get`, and `compute.globalOperations.get`.

Before generating certificate material, call `GET /api/businesses/{business_id}/tls/capabilities`. A ready response confirms both permission groups. A failure lists missing permissions and a short next action; private keys and provider response bodies are never included.

Do not copy the certificate private key into GitHub. Existing GitHub deployment authentication remains unchanged.

References: [Google self-managed SSL certificates](https://docs.cloud.google.com/load-balancing/docs/ssl-certificates/self-managed-certs), [GKE pre-shared certificate annotation](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/secure-traffic-management), and [Secret Manager least-privilege guidance](https://docs.cloud.google.com/secret-manager/docs/access-control).

## Platfire rollout

1. Deploy the database migration and API/UI code.
2. Confirm Secret Manager API and workload identity permissions.
3. Open Platfire's operator workspace and choose **Generate, Vault & Publish**, or import/adopt an existing self-managed certificate.
4. Publish the existing artifact again. Duplicate-artifact repair is allowed to reconcile the workflow and Ingress without republishing artifact content.
5. Request GKE deploy.
6. Use **Verify Served Certificate**. Success requires the endpoint fingerprint to match the selected asset.

Rollback is certificate selection, not key deletion: select the prior published asset and republish the site. Retain old Compute certificate resources and Secret Manager versions until the replacement has been verified.
