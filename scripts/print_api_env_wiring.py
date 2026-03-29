#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print("Usage: print_api_env_wiring.py <deployment_json_path>", file=sys.stderr)
        return 2

    deployment_path = Path(args[0])
    with deployment_path.open(encoding="utf-8") as handle:
        payload = json.load(handle)

    containers = payload.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
    container = next((item for item in containers if item.get("name") == "mbsrn-api"), None)
    if container is None:
        print("mbsrn-api container not found in deployment template.")
        return 0

    env_entries = container.get("env", [])
    print("mbsrn-api env sources:")
    for entry in env_entries:
        name = entry.get("name", "<unnamed>")
        if "valueFrom" in entry:
            value_from = entry["valueFrom"]
            if "secretKeyRef" in value_from:
                ref = value_from["secretKeyRef"]
                print(f"- {name}: secretKeyRef name={ref.get('name')} key={ref.get('key')}")
            elif "configMapKeyRef" in value_from:
                ref = value_from["configMapKeyRef"]
                print(f"- {name}: configMapKeyRef name={ref.get('name')} key={ref.get('key')}")
            else:
                print(f"- {name}: valueFrom(other)")
        elif "value" in entry:
            print(f"- {name}: literal value")
        else:
            print(f"- {name}: source not set")

    database_url_entry = next((item for item in env_entries if item.get("name") == "DATABASE_URL"), None)
    if database_url_entry is None:
        print("DATABASE_URL env entry: missing")
    elif "valueFrom" in database_url_entry and "secretKeyRef" in database_url_entry["valueFrom"]:
        ref = database_url_entry["valueFrom"]["secretKeyRef"]
        print(
            "DATABASE_URL env entry: secretKeyRef "
            f"name={ref.get('name')} key={ref.get('key')}"
        )
    elif "value" in database_url_entry:
        print("DATABASE_URL env entry: literal value")
    else:
        print("DATABASE_URL env entry: unresolved source")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
