#!/usr/bin/env bash

set -euo pipefail

usage() {
  cat <<'EOF'
Provision or reconcile the shared HTTPS-only preview Gateway and its public
Google-managed wildcard certificate.

Usage:
  scripts/bootstrap_shared_preview_edge.sh \
    --gcp-project-id <id> \
    --gke-cluster-name <name> \
    --gke-cluster-location <region-or-zone> \
    --dns-zone <cloud-dns-zone>

Options:
  --gateway-namespace <name>       Defaults to mbsrn
  --gateway-name <name>            Defaults to mbsrn-preview-gateway
  --static-ip-name <name>          Defaults to mbsrn-preview-edge-ip
  --dns-authorization-name <name>  Defaults to mbsrn-preview-dns-auth
  --certificate-name <name>        Defaults to mbsrn-preview-wildcard
  --certificate-map-name <name>    Defaults to mbsrn-preview-cert-map
  --certificate-map-entry <name>   Defaults to mbsrn-preview-wildcard-entry
  --help

The script changes only platform-level resources. It does not create a site
route or change any preview hostname A record.
EOF
}

GCP_PROJECT_ID=""
GKE_CLUSTER_NAME=""
GKE_CLUSTER_LOCATION=""
DNS_ZONE=""
GATEWAY_NAMESPACE="mbsrn"
GATEWAY_NAME="mbsrn-preview-gateway"
STATIC_IP_NAME="mbsrn-preview-edge-ip"
DNS_AUTHORIZATION_NAME="mbsrn-preview-dns-auth"
CERTIFICATE_NAME="mbsrn-preview-wildcard"
CERTIFICATE_MAP_NAME="mbsrn-preview-cert-map"
CERTIFICATE_MAP_ENTRY_NAME="mbsrn-preview-wildcard-entry"
PREVIEW_DOMAIN="site.mbsrn.com"
PREVIEW_WILDCARD_DOMAIN="*.site.mbsrn.com"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --gcp-project-id) GCP_PROJECT_ID="$2"; shift 2 ;;
    --gke-cluster-name) GKE_CLUSTER_NAME="$2"; shift 2 ;;
    --gke-cluster-location) GKE_CLUSTER_LOCATION="$2"; shift 2 ;;
    --dns-zone) DNS_ZONE="$2"; shift 2 ;;
    --gateway-namespace) GATEWAY_NAMESPACE="$2"; shift 2 ;;
    --gateway-name) GATEWAY_NAME="$2"; shift 2 ;;
    --static-ip-name) STATIC_IP_NAME="$2"; shift 2 ;;
    --dns-authorization-name) DNS_AUTHORIZATION_NAME="$2"; shift 2 ;;
    --certificate-name) CERTIFICATE_NAME="$2"; shift 2 ;;
    --certificate-map-name) CERTIFICATE_MAP_NAME="$2"; shift 2 ;;
    --certificate-map-entry) CERTIFICATE_MAP_ENTRY_NAME="$2"; shift 2 ;;
    --help|-h) usage; exit 0 ;;
    *) echo "ERROR: unknown argument: $1" >&2; usage >&2; exit 1 ;;
  esac
done

for required_value in GCP_PROJECT_ID GKE_CLUSTER_NAME GKE_CLUSTER_LOCATION DNS_ZONE; do
  if [[ -z "${!required_value//[[:space:]]/}" ]]; then
    echo "ERROR: ${required_value} is required." >&2
    usage >&2
    exit 1
  fi
done
for required_command in gcloud kubectl python; do
  if ! command -v "$required_command" >/dev/null 2>&1; then
    echo "ERROR: ${required_command} is required." >&2
    exit 1
  fi
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GATEWAY_MANIFEST="$(mktemp)"
trap 'rm -f "$GATEWAY_MANIFEST"' EXIT

gcloud services enable \
  certificatemanager.googleapis.com \
  compute.googleapis.com \
  container.googleapis.com \
  dns.googleapis.com \
  --project "$GCP_PROJECT_ID" >/dev/null

if ! gcloud compute addresses describe "$STATIC_IP_NAME" \
  --global --project "$GCP_PROJECT_ID" >/dev/null 2>&1; then
  gcloud compute addresses create "$STATIC_IP_NAME" \
    --global --network-tier PREMIUM --project "$GCP_PROJECT_ID" >/dev/null
  echo "Created shared global address: ${STATIC_IP_NAME}"
fi
STATIC_IP_ADDRESS="$(gcloud compute addresses describe "$STATIC_IP_NAME" \
  --global --project "$GCP_PROJECT_ID" --format='value(address)')"
if [[ -z "${STATIC_IP_ADDRESS//[[:space:]]/}" ]]; then
  echo "ERROR: shared global address has no allocated IP: ${STATIC_IP_NAME}" >&2
  exit 1
fi

if ! gcloud certificate-manager dns-authorizations describe "$DNS_AUTHORIZATION_NAME" \
  --location global --project "$GCP_PROJECT_ID" >/dev/null 2>&1; then
  gcloud certificate-manager dns-authorizations create "$DNS_AUTHORIZATION_NAME" \
    --location global --domain "$PREVIEW_DOMAIN" --project "$GCP_PROJECT_ID" >/dev/null
  echo "Created DNS authorization: ${DNS_AUTHORIZATION_NAME}"
fi
AUTH_DOMAIN="$(gcloud certificate-manager dns-authorizations describe "$DNS_AUTHORIZATION_NAME" \
  --location global --project "$GCP_PROJECT_ID" --format='value(domain)')"
if [[ "$AUTH_DOMAIN" != "$PREVIEW_DOMAIN" ]]; then
  echo "ERROR: existing DNS authorization covers ${AUTH_DOMAIN}, expected ${PREVIEW_DOMAIN}." >&2
  exit 1
fi
DNS_AUTH_RECORD_NAME="$(gcloud certificate-manager dns-authorizations describe "$DNS_AUTHORIZATION_NAME" \
  --location global --project "$GCP_PROJECT_ID" --format='value(dnsResourceRecord.name)')"
DNS_AUTH_RECORD_TYPE="$(gcloud certificate-manager dns-authorizations describe "$DNS_AUTHORIZATION_NAME" \
  --location global --project "$GCP_PROJECT_ID" --format='value(dnsResourceRecord.type)')"
DNS_AUTH_RECORD_DATA="$(gcloud certificate-manager dns-authorizations describe "$DNS_AUTHORIZATION_NAME" \
  --location global --project "$GCP_PROJECT_ID" --format='value(dnsResourceRecord.data)')"
if [[ -z "$DNS_AUTH_RECORD_NAME" || "$DNS_AUTH_RECORD_TYPE" != "CNAME" || -z "$DNS_AUTH_RECORD_DATA" ]]; then
  echo "ERROR: DNS authorization did not return a complete CNAME record." >&2
  exit 1
fi

EXISTING_DNS_AUTH_DATA="$(gcloud dns record-sets describe "$DNS_AUTH_RECORD_NAME" \
  --type CNAME --zone "$DNS_ZONE" --project "$GCP_PROJECT_ID" \
  --format='value(rrdatas[0])' 2>/dev/null || true)"
if [[ -n "$EXISTING_DNS_AUTH_DATA" && "$EXISTING_DNS_AUTH_DATA" != "$DNS_AUTH_RECORD_DATA" ]]; then
  echo "ERROR: ${DNS_AUTH_RECORD_NAME} already exists with different CNAME data." >&2
  exit 1
fi
if [[ -z "$EXISTING_DNS_AUTH_DATA" ]]; then
  gcloud dns record-sets create "$DNS_AUTH_RECORD_NAME" \
    --type CNAME --ttl 300 --rrdatas "$DNS_AUTH_RECORD_DATA" \
    --zone "$DNS_ZONE" --project "$GCP_PROJECT_ID" >/dev/null
  echo "Created Certificate Manager DNS authorization record: ${DNS_AUTH_RECORD_NAME}"
fi

if ! gcloud certificate-manager certificates describe "$CERTIFICATE_NAME" \
  --location global --project "$GCP_PROJECT_ID" >/dev/null 2>&1; then
  gcloud certificate-manager certificates create "$CERTIFICATE_NAME" \
    --location global \
    --domains "$PREVIEW_WILDCARD_DOMAIN" \
    --dns-authorizations "$DNS_AUTHORIZATION_NAME" \
    --project "$GCP_PROJECT_ID" >/dev/null
  echo "Created Google-managed wildcard certificate: ${CERTIFICATE_NAME}"
fi
CERTIFICATE_DOMAINS="$(gcloud certificate-manager certificates describe "$CERTIFICATE_NAME" \
  --location global --project "$GCP_PROJECT_ID" --format='csv[no-heading](managed.domains)')"
if [[ "$CERTIFICATE_DOMAINS" != *"$PREVIEW_WILDCARD_DOMAIN"* ]]; then
  echo "ERROR: existing certificate does not cover ${PREVIEW_WILDCARD_DOMAIN}." >&2
  exit 1
fi

if ! gcloud certificate-manager maps describe "$CERTIFICATE_MAP_NAME" \
  --location global --project "$GCP_PROJECT_ID" >/dev/null 2>&1; then
  gcloud certificate-manager maps create "$CERTIFICATE_MAP_NAME" \
    --location global --project "$GCP_PROJECT_ID" >/dev/null
  echo "Created certificate map: ${CERTIFICATE_MAP_NAME}"
fi
if ! gcloud certificate-manager maps entries describe "$CERTIFICATE_MAP_ENTRY_NAME" \
  --map "$CERTIFICATE_MAP_NAME" --location global --project "$GCP_PROJECT_ID" >/dev/null 2>&1; then
  gcloud certificate-manager maps entries create "$CERTIFICATE_MAP_ENTRY_NAME" \
    --map "$CERTIFICATE_MAP_NAME" \
    --certificates "$CERTIFICATE_NAME" \
    --hostname "$PREVIEW_WILDCARD_DOMAIN" \
    --location global --project "$GCP_PROJECT_ID" >/dev/null
  echo "Created wildcard certificate map entry: ${CERTIFICATE_MAP_ENTRY_NAME}"
fi
MAP_ENTRY_HOSTNAME="$(gcloud certificate-manager maps entries describe "$CERTIFICATE_MAP_ENTRY_NAME" \
  --map "$CERTIFICATE_MAP_NAME" --location global --project "$GCP_PROJECT_ID" --format='value(hostname)')"
MAP_ENTRY_CERTIFICATES="$(gcloud certificate-manager maps entries describe "$CERTIFICATE_MAP_ENTRY_NAME" \
  --map "$CERTIFICATE_MAP_NAME" --location global --project "$GCP_PROJECT_ID" --format='value(certificates)')"
if [[ "$MAP_ENTRY_HOSTNAME" != "$PREVIEW_WILDCARD_DOMAIN" || "$MAP_ENTRY_CERTIFICATES" != *"/${CERTIFICATE_NAME}"* ]]; then
  echo "ERROR: existing certificate map entry does not match the approved wildcard certificate." >&2
  exit 1
fi

GATEWAY_CHANNEL="$(gcloud container clusters describe "$GKE_CLUSTER_NAME" \
  --location "$GKE_CLUSTER_LOCATION" --project "$GCP_PROJECT_ID" \
  --format='value(networkConfig.gatewayApiConfig.channel)')"
if [[ "$GATEWAY_CHANNEL" != "CHANNEL_STANDARD" ]]; then
  gcloud container clusters update "$GKE_CLUSTER_NAME" \
    --location "$GKE_CLUSTER_LOCATION" --project "$GCP_PROJECT_ID" \
    --gateway-api standard >/dev/null
  echo "Enabled the Gateway API standard channel. GKE reconciliation can take up to 45 minutes."
fi
gcloud container clusters get-credentials "$GKE_CLUSTER_NAME" \
  --location "$GKE_CLUSTER_LOCATION" --project "$GCP_PROJECT_ID" >/dev/null
if ! kubectl get namespace "$GATEWAY_NAMESPACE" >/dev/null 2>&1; then
  echo "ERROR: Gateway namespace does not exist: ${GATEWAY_NAMESPACE}" >&2
  exit 1
fi

python "${SCRIPT_DIR}/render_shared_preview_gateway.py" \
  --static-ip-name "$STATIC_IP_NAME" \
  --gateway-name "$GATEWAY_NAME" \
  --gateway-namespace "$GATEWAY_NAMESPACE" \
  --certificate-map-name "$CERTIFICATE_MAP_NAME" \
  --certificate-map-entry-name "$CERTIFICATE_MAP_ENTRY_NAME" \
  --certificate-name "$CERTIFICATE_NAME" \
  --dns-authorization-name "$DNS_AUTHORIZATION_NAME" > "$GATEWAY_MANIFEST"
kubectl apply -f "$GATEWAY_MANIFEST"

CERTIFICATE_STATE="$(gcloud certificate-manager certificates describe "$CERTIFICATE_NAME" \
  --location global --project "$GCP_PROJECT_ID" --format='value(managed.state)')"
echo "Shared preview edge reconciliation submitted."
echo "certificate_state=${CERTIFICATE_STATE:-UNKNOWN}"
echo "shared_static_ip_address=${STATIC_IP_ADDRESS}"
echo "gateway=${GATEWAY_NAMESPACE}/${GATEWAY_NAME}"
echo
echo "Configure managed_preview_endpoint only after the certificate is ACTIVE and the Gateway is Programmed:"
echo "mode=preview_shared_gateway"
echo "shared_preview_static_ip_name=${STATIC_IP_NAME}"
echo "gateway_api_enabled=true"
echo "gateway_name=${GATEWAY_NAME}"
echo "gateway_namespace=${GATEWAY_NAMESPACE}"
echo "certificate_map_name=${CERTIFICATE_MAP_NAME}"
echo "certificate_map_entry_name=${CERTIFICATE_MAP_ENTRY_NAME}"
echo "certificate_name=${CERTIFICATE_NAME}"
echo "dns_authorization_name=${DNS_AUTHORIZATION_NAME}"
echo "certificate_domain=${PREVIEW_WILDCARD_DOMAIN}"
