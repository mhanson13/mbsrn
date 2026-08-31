from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping


PREVIEW_DOMAIN = "site.mbsrn.com"
PREVIEW_WILDCARD_DOMAIN = f"*.{PREVIEW_DOMAIN}"
GATEWAY_CLASS_NAME = "gke-l7-global-external-managed"
GATEWAY_LISTENER_NAME = "https"
GATEWAY_ROUTE_NAMESPACE_LABEL = "mbsrn.io/preview-route-access"
GATEWAY_ROUTE_NAMESPACE_LABEL_VALUE = "true"
GATEWAY_SERVICE_NAME = "site-web-gateway"
GATEWAY_HEALTH_CHECK_POLICY_NAME = "site-web-gateway-health"
GATEWAY_ROUTE_NAME = "site-web"

_DNS_LABEL_PATTERN = re.compile(r"^[a-z](?:[-a-z0-9]{0,61}[a-z0-9])?$")
_DNS_NAMESPACE_PATTERN = re.compile(r"^[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?$")
_PREVIEW_HOSTNAME_PATTERN = re.compile(rf"^[a-z0-9](?:[-a-z0-9]{{0,61}}[a-z0-9])?\.{re.escape(PREVIEW_DOMAIN)}$")


def _text(value: object) -> str | None:
    normalized = str(value or "").strip().lower()
    return normalized or None


def _boolean(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class SharedPreviewEdgeConfig:
    enabled: bool
    static_ip_name: str | None
    gateway_name: str | None
    gateway_namespace: str | None
    certificate_map_name: str | None
    certificate_name: str | None
    dns_authorization_name: str | None
    certificate_domain: str = PREVIEW_WILDCARD_DOMAIN

    @classmethod
    def from_mapping(cls, value: Mapping[str, object] | None) -> SharedPreviewEdgeConfig:
        payload = value or {}
        return cls(
            enabled=_boolean(payload.get("gateway_api_enabled", False)),
            static_ip_name=_text(payload.get("shared_preview_static_ip_name")),
            gateway_name=_text(payload.get("gateway_name")),
            gateway_namespace=_text(payload.get("gateway_namespace")),
            certificate_map_name=_text(payload.get("certificate_map_name")),
            certificate_name=_text(payload.get("certificate_name")),
            dns_authorization_name=_text(payload.get("dns_authorization_name")),
            certificate_domain=_text(payload.get("certificate_domain")) or PREVIEW_WILDCARD_DOMAIN,
        )

    @property
    def missing_fields(self) -> tuple[str, ...]:
        if not self.enabled:
            return ()
        required = {
            "shared_preview_static_ip_name": self.static_ip_name,
            "gateway_name": self.gateway_name,
            "gateway_namespace": self.gateway_namespace,
            "certificate_map_name": self.certificate_map_name,
            "certificate_name": self.certificate_name,
            "dns_authorization_name": self.dns_authorization_name,
        }
        return tuple(name for name, value in required.items() if not value)

    @property
    def ready_for_rendering(self) -> bool:
        return self.enabled and not self.missing_fields and self.certificate_domain == PREVIEW_WILDCARD_DOMAIN

    def validate(self) -> None:
        if not self.enabled:
            return
        if self.missing_fields:
            raise ValueError("Shared preview Gateway configuration is incomplete: " + ", ".join(self.missing_fields))
        assert self.static_ip_name is not None
        assert self.gateway_name is not None
        assert self.gateway_namespace is not None
        assert self.certificate_map_name is not None
        assert self.certificate_name is not None
        assert self.dns_authorization_name is not None
        for field_name, candidate in (
            ("shared_preview_static_ip_name", self.static_ip_name),
            ("gateway_name", self.gateway_name),
            ("certificate_map_name", self.certificate_map_name),
            ("certificate_name", self.certificate_name),
            ("dns_authorization_name", self.dns_authorization_name),
        ):
            if not _DNS_LABEL_PATTERN.fullmatch(candidate):
                raise ValueError(f"{field_name} must be a lowercase Google/Kubernetes resource name.")
        if not _DNS_NAMESPACE_PATTERN.fullmatch(self.gateway_namespace):
            raise ValueError("gateway_namespace must be a lowercase Kubernetes namespace name.")
        if self.certificate_domain != PREVIEW_WILDCARD_DOMAIN:
            raise ValueError(f"certificate_domain must be {PREVIEW_WILDCARD_DOMAIN} for preview traffic.")


@dataclass(frozen=True)
class SharedPreviewEdgeReadiness:
    status: str
    reason_code: str
    reasons: tuple[str, ...]
    certificate_active: bool
    certificate_map_attached: bool
    gateway_programmed: bool
    gateway_address_matches: bool


def evaluate_shared_preview_edge_readiness(
    *,
    config: SharedPreviewEdgeConfig,
    certificate: Mapping[str, object] | None,
    certificate_map_entry: Mapping[str, object] | None,
    gateway: Mapping[str, object] | None,
    expected_static_ip_address: str | None,
) -> SharedPreviewEdgeReadiness:
    if not config.enabled:
        return SharedPreviewEdgeReadiness(
            status="disabled",
            reason_code="shared_preview_gateway_disabled",
            reasons=("Shared preview Gateway API is disabled.",),
            certificate_active=False,
            certificate_map_attached=False,
            gateway_programmed=False,
            gateway_address_matches=False,
        )
    if config.missing_fields:
        return SharedPreviewEdgeReadiness(
            status="action_required",
            reason_code="shared_preview_gateway_config_incomplete",
            reasons=tuple(f"Missing {field}." for field in config.missing_fields),
            certificate_active=False,
            certificate_map_attached=False,
            gateway_programmed=False,
            gateway_address_matches=False,
        )
    config.validate()

    certificate_payload = certificate or {}
    managed_payload = certificate_payload.get("managed")
    managed = managed_payload if isinstance(managed_payload, Mapping) else {}
    domains_payload = managed.get("domains")
    domains = tuple(str(item).strip().lower() for item in domains_payload) if isinstance(domains_payload, list) else ()
    certificate_active = str(managed.get("state") or "").strip().upper() == "ACTIVE" and (
        config.certificate_domain in domains
    )

    map_entry_payload = certificate_map_entry or {}
    map_hostname = str(map_entry_payload.get("hostname") or "").strip().lower()
    certificates_payload = map_entry_payload.get("certificates")
    mapped_certificates = (
        tuple(str(item).strip().rsplit("/", 1)[-1].lower() for item in certificates_payload)
        if isinstance(certificates_payload, list)
        else ()
    )
    certificate_map_attached = (
        map_hostname == config.certificate_domain and str(config.certificate_name).lower() in mapped_certificates
    )

    gateway_payload = gateway or {}
    metadata_payload = gateway_payload.get("metadata")
    metadata = metadata_payload if isinstance(metadata_payload, Mapping) else {}
    annotations_payload = metadata.get("annotations")
    annotations = annotations_payload if isinstance(annotations_payload, Mapping) else {}
    status_payload = gateway_payload.get("status")
    gateway_status = status_payload if isinstance(status_payload, Mapping) else {}
    conditions_payload = gateway_status.get("conditions")
    conditions = conditions_payload if isinstance(conditions_payload, list) else []
    programmed_condition = next(
        (
            item
            for item in conditions
            if isinstance(item, Mapping) and str(item.get("type") or "").strip().lower() == "programmed"
        ),
        None,
    )
    gateway_programmed = bool(
        programmed_condition
        and str(programmed_condition.get("status") or "").strip().lower() == "true"
        and str(annotations.get("networking.gke.io/certmap") or "").strip().lower()
        == str(config.certificate_map_name).lower()
    )

    addresses_payload = gateway_status.get("addresses")
    addresses = addresses_payload if isinstance(addresses_payload, list) else []
    observed_addresses = {
        str(item.get("value") or "").strip()
        for item in addresses
        if isinstance(item, Mapping) and str(item.get("value") or "").strip()
    }
    normalized_expected_address = str(expected_static_ip_address or "").strip()
    gateway_address_matches = bool(
        normalized_expected_address and normalized_expected_address in observed_addresses
    )

    reasons: list[str] = []
    if not certificate_active:
        reasons.append("The wildcard certificate is not active or does not cover the preview domain.")
    if not certificate_map_attached:
        reasons.append("The wildcard certificate is not selected by the expected certificate-map entry.")
    if not gateway_programmed:
        reasons.append("The shared Gateway is not programmed with the expected certificate map.")
    if not gateway_address_matches:
        reasons.append("The shared Gateway address does not match the reserved static address.")
    ready = not reasons
    return SharedPreviewEdgeReadiness(
        status="ready" if ready else "pending",
        reason_code="shared_preview_gateway_ready" if ready else "shared_preview_gateway_pending",
        reasons=tuple(reasons),
        certificate_active=certificate_active,
        certificate_map_attached=certificate_map_attached,
        gateway_programmed=gateway_programmed,
        gateway_address_matches=gateway_address_matches,
    )


def render_shared_preview_gateway_manifest(config: SharedPreviewEdgeConfig) -> str:
    config.validate()
    assert config.static_ip_name is not None
    assert config.gateway_name is not None
    assert config.gateway_namespace is not None
    assert config.certificate_map_name is not None
    return (
        "apiVersion: gateway.networking.k8s.io/v1\n"
        "kind: Gateway\n"
        "metadata:\n"
        f"  name: {config.gateway_name}\n"
        f"  namespace: {config.gateway_namespace}\n"
        "  labels:\n"
        "    app.kubernetes.io/managed-by: mbsrn\n"
        "    mbsrn.io/scope: shared-preview-edge\n"
        "  annotations:\n"
        f"    networking.gke.io/certmap: {config.certificate_map_name}\n"
        "spec:\n"
        f"  gatewayClassName: {GATEWAY_CLASS_NAME}\n"
        "  addresses:\n"
        "    - type: NamedAddress\n"
        f"      value: {config.static_ip_name}\n"
        "  listeners:\n"
        f"    - name: {GATEWAY_LISTENER_NAME}\n"
        "      protocol: HTTPS\n"
        "      port: 443\n"
        "      allowedRoutes:\n"
        "        namespaces:\n"
        "          from: Selector\n"
        "          selector:\n"
        "            matchLabels:\n"
        f"              {GATEWAY_ROUTE_NAMESPACE_LABEL}: \"{GATEWAY_ROUTE_NAMESPACE_LABEL_VALUE}\"\n"
        "        kinds:\n"
        "          - group: gateway.networking.k8s.io\n"
        "            kind: HTTPRoute\n"
    )


def render_site_gateway_manifests(
    *,
    config: SharedPreviewEdgeConfig,
    namespace: str,
    preview_hostname: str,
    labels_yaml: str,
    managed_manifest_marker: str | None = None,
) -> dict[str, str]:
    config.validate()
    normalized_namespace = _text(namespace)
    normalized_hostname = _text(preview_hostname)
    if not normalized_namespace or not _DNS_NAMESPACE_PATTERN.fullmatch(normalized_namespace):
        raise ValueError("A valid site namespace is required for shared Gateway routing.")
    if not normalized_hostname or not _PREVIEW_HOSTNAME_PATTERN.fullmatch(normalized_hostname):
        raise ValueError(f"Preview hostname must be a direct child of {PREVIEW_DOMAIN}.")
    assert config.gateway_name is not None
    assert config.gateway_namespace is not None
    marker = f"# {managed_manifest_marker}\n" if managed_manifest_marker else ""

    service = (
        f"{marker}"
        "apiVersion: v1\n"
        "kind: Service\n"
        "metadata:\n"
        f"  name: {GATEWAY_SERVICE_NAME}\n"
        f"  namespace: {normalized_namespace}\n"
        "  labels:\n"
        f"{labels_yaml}"
        "spec:\n"
        "  selector:\n"
        "    app.kubernetes.io/name: site-web\n"
        "  ports:\n"
        "    - name: http\n"
        "      port: 80\n"
        "      targetPort: 8080\n"
        "  type: ClusterIP\n"
    )
    route = (
        f"{marker}"
        "apiVersion: gateway.networking.k8s.io/v1\n"
        "kind: HTTPRoute\n"
        "metadata:\n"
        f"  name: {GATEWAY_ROUTE_NAME}\n"
        f"  namespace: {normalized_namespace}\n"
        "  labels:\n"
        f"{labels_yaml}"
        "spec:\n"
        "  parentRefs:\n"
        f"    - name: {config.gateway_name}\n"
        f"      namespace: {config.gateway_namespace}\n"
        f"      sectionName: {GATEWAY_LISTENER_NAME}\n"
        "  hostnames:\n"
        f"    - {normalized_hostname}\n"
        "  rules:\n"
        "    - matches:\n"
        "        - path:\n"
        "            type: PathPrefix\n"
        "            value: /\n"
        "      backendRefs:\n"
        f"        - name: {GATEWAY_SERVICE_NAME}\n"
        "          port: 80\n"
    )
    health_check = (
        f"{marker}"
        "apiVersion: networking.gke.io/v1\n"
        "kind: HealthCheckPolicy\n"
        "metadata:\n"
        f"  name: {GATEWAY_HEALTH_CHECK_POLICY_NAME}\n"
        f"  namespace: {normalized_namespace}\n"
        "  labels:\n"
        f"{labels_yaml}"
        "spec:\n"
        "  default:\n"
        "    checkIntervalSec: 10\n"
        "    timeoutSec: 5\n"
        "    healthyThreshold: 1\n"
        "    unhealthyThreshold: 3\n"
        "    config:\n"
        "      type: HTTP\n"
        "      httpHealthCheck:\n"
        "        portSpecification: USE_SERVING_PORT\n"
        "        requestPath: /\n"
        "  targetRef:\n"
        "    group: \"\"\n"
        "    kind: Service\n"
        f"    name: {GATEWAY_SERVICE_NAME}\n"
    )
    return {
        "k8s/gateway-service.yaml": service,
        "k8s/httproute.yaml": route,
        "k8s/gateway-healthcheckpolicy.yaml": health_check,
    }
