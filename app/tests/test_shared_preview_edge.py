from __future__ import annotations

from pathlib import Path

import yaml

from app.integrations.shared_preview_edge import (
    GATEWAY_ROUTE_NAMESPACE_LABEL,
    GATEWAY_ROUTE_NAMESPACE_LABEL_VALUE,
    SharedPreviewEdgeConfig,
    evaluate_shared_preview_edge_readiness,
    render_shared_preview_gateway_manifest,
    render_site_gateway_manifests,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _config(**overrides: object) -> SharedPreviewEdgeConfig:
    payload: dict[str, object] = {
        "gateway_api_enabled": True,
        "shared_preview_static_ip_name": "mbsrn-preview-edge-ip",
        "gateway_name": "mbsrn-preview-gateway",
        "gateway_namespace": "mbsrn",
        "certificate_map_name": "mbsrn-preview-cert-map",
        "certificate_map_entry_name": "mbsrn-preview-wildcard-entry",
        "certificate_name": "mbsrn-preview-wildcard",
        "dns_authorization_name": "mbsrn-preview-dns-auth",
        "certificate_domain": "*.site.mbsrn.com",
    }
    payload.update(overrides)
    return SharedPreviewEdgeConfig.from_mapping(payload)


def test_shared_preview_edge_config_fails_closed_when_enabled_but_incomplete() -> None:
    config = SharedPreviewEdgeConfig.from_mapping({"gateway_api_enabled": True})

    assert config.ready_for_rendering is False
    assert config.missing_fields == (
        "shared_preview_static_ip_name",
        "gateway_name",
        "gateway_namespace",
        "certificate_map_name",
        "certificate_map_entry_name",
        "certificate_name",
        "dns_authorization_name",
    )


def test_render_shared_preview_gateway_is_https_only_and_selector_scoped() -> None:
    parsed = yaml.safe_load(render_shared_preview_gateway_manifest(_config()))

    assert parsed["kind"] == "Gateway"
    assert parsed["metadata"]["annotations"] == {
        "networking.gke.io/certmap": "mbsrn-preview-cert-map",
    }
    assert parsed["spec"]["gatewayClassName"] == "gke-l7-global-external-managed"
    assert parsed["spec"]["addresses"] == [{"type": "NamedAddress", "value": "mbsrn-preview-edge-ip"}]
    assert parsed["spec"]["listeners"] == [
        {
            "name": "https",
            "protocol": "HTTPS",
            "port": 443,
            "allowedRoutes": {
                "namespaces": {
                    "from": "Selector",
                    "selector": {
                        "matchLabels": {
                            GATEWAY_ROUTE_NAMESPACE_LABEL: GATEWAY_ROUTE_NAMESPACE_LABEL_VALUE,
                        }
                    },
                },
                "kinds": [{"group": "gateway.networking.k8s.io", "kind": "HTTPRoute"}],
            },
        }
    ]


def test_render_site_gateway_manifests_uses_separate_service_for_safe_ingress_coexistence() -> None:
    manifests = render_site_gateway_manifests(
        config=_config(),
        namespace="platfire",
        preview_hostname="platfire.site.mbsrn.com",
        labels_yaml="    app.kubernetes.io/managed-by: mbsrn\n    mbsrn.io/site-id: site-platfire\n",
    )

    service = yaml.safe_load(manifests["k8s/gateway-service.yaml"])
    route = yaml.safe_load(manifests["k8s/httproute.yaml"])
    health_check = yaml.safe_load(manifests["k8s/gateway-healthcheckpolicy.yaml"])

    assert service["metadata"]["name"] == "site-web-gateway"
    assert "annotations" not in service["metadata"]
    assert service["spec"]["selector"] == {"app.kubernetes.io/name": "site-web"}
    assert route["spec"]["hostnames"] == ["platfire.site.mbsrn.com"]
    assert route["spec"]["parentRefs"] == [
        {"name": "mbsrn-preview-gateway", "namespace": "mbsrn", "sectionName": "https"}
    ]
    assert route["spec"]["rules"][0]["backendRefs"] == [{"name": "site-web-gateway", "port": 80}]
    assert health_check["spec"]["targetRef"] == {
        "group": "",
        "kind": "Service",
        "name": "site-web-gateway",
    }


def test_evaluate_shared_preview_edge_readiness_requires_all_platform_evidence() -> None:
    config = _config()
    readiness = evaluate_shared_preview_edge_readiness(
        config=config,
        certificate={
            "managed": {
                "state": "ACTIVE",
                "domains": ["*.site.mbsrn.com"],
            }
        },
        certificate_map_entry={
            "hostname": "*.site.mbsrn.com",
            "certificates": [
                "projects/mbsrn-prod/locations/global/certificates/mbsrn-preview-wildcard",
            ],
        },
        gateway={
            "metadata": {"annotations": {"networking.gke.io/certmap": "mbsrn-preview-cert-map"}},
            "status": {
                "conditions": [{"type": "Programmed", "status": "True"}],
                "addresses": [{"type": "IPAddress", "value": "34.149.100.20"}],
            },
        },
        expected_static_ip_address="34.149.100.20",
    )

    assert readiness.status == "ready"
    assert readiness.reason_code == "shared_preview_gateway_ready"
    assert readiness.reasons == ()
    assert readiness.certificate_active is True
    assert readiness.certificate_map_attached is True
    assert readiness.gateway_programmed is True
    assert readiness.gateway_address_matches is True


def test_evaluate_shared_preview_edge_readiness_returns_bounded_pending_reasons() -> None:
    readiness = evaluate_shared_preview_edge_readiness(
        config=_config(),
        certificate={"managed": {"state": "PROVISIONING", "domains": ["*.site.mbsrn.com"]}},
        certificate_map_entry=None,
        gateway=None,
        expected_static_ip_address="34.149.100.20",
    )

    assert readiness.status == "pending"
    assert readiness.reason_code == "shared_preview_gateway_pending"
    assert len(readiness.reasons) == 4


def test_shared_preview_edge_bootstrap_is_platform_scoped_and_https_only() -> None:
    bootstrap = (REPOSITORY_ROOT / "scripts" / "bootstrap_shared_preview_edge.sh").read_text(encoding="utf-8")

    assert "certificatemanager.googleapis.com" in bootstrap
    assert "dns-authorizations create" in bootstrap
    assert 'PREVIEW_WILDCARD_DOMAIN="*.site.mbsrn.com"' in bootstrap
    assert "--gateway-api standard" in bootstrap
    assert 'kubectl apply -f "$GATEWAY_MANIFEST"' in bootstrap
    assert "record-sets create \"$DNS_AUTH_RECORD_NAME\"" in bootstrap
    assert "preview hostname A record" in bootstrap
    assert "--insecure" not in bootstrap
