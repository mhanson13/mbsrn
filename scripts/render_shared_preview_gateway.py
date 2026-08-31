from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SHARED_PREVIEW_EDGE_MODULE_PATH = REPOSITORY_ROOT / "app" / "integrations" / "shared_preview_edge.py"


def _load_shared_preview_edge_module():
    """Load the dependency-free renderer without importing the application package."""
    spec = importlib.util.spec_from_file_location(
        "mbsrn_shared_preview_edge_renderer",
        SHARED_PREVIEW_EDGE_MODULE_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load the shared preview edge renderer.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    parser = argparse.ArgumentParser(description="Render the MBSRN shared preview Gateway manifest.")
    parser.add_argument("--static-ip-name", required=True)
    parser.add_argument("--gateway-name", required=True)
    parser.add_argument("--gateway-namespace", required=True)
    parser.add_argument("--certificate-map-name", required=True)
    parser.add_argument("--certificate-map-entry-name", required=True)
    parser.add_argument("--certificate-name", required=True)
    parser.add_argument("--dns-authorization-name", required=True)
    args = parser.parse_args()

    shared_preview_edge = _load_shared_preview_edge_module()
    config = shared_preview_edge.SharedPreviewEdgeConfig.from_mapping(
        {
            "gateway_api_enabled": True,
            "shared_preview_static_ip_name": args.static_ip_name,
            "gateway_name": args.gateway_name,
            "gateway_namespace": args.gateway_namespace,
            "certificate_map_name": args.certificate_map_name,
            "certificate_map_entry_name": args.certificate_map_entry_name,
            "certificate_name": args.certificate_name,
            "dns_authorization_name": args.dns_authorization_name,
            "certificate_domain": "*.site.mbsrn.com",
        }
    )
    sys.stdout.write(shared_preview_edge.render_shared_preview_gateway_manifest(config))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
