from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from app.integrations.shared_preview_edge import (  # noqa: E402
    SharedPreviewEdgeConfig,
    render_shared_preview_gateway_manifest,
)


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

    config = SharedPreviewEdgeConfig.from_mapping(
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
    sys.stdout.write(render_shared_preview_gateway_manifest(config))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
