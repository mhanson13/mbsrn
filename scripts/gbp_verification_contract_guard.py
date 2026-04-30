from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if not os.environ.get("APP_ENV"):
    os.environ["APP_ENV"] = "test"

DEFAULT_CONTRACT_ARTIFACT_PATH = PROJECT_ROOT / "docs" / "contracts" / "gbp-verification-contract.schema.json"
DEFAULT_FRONTEND_TYPES_PATH = PROJECT_ROOT / "frontend" / "operator-ui" / "lib" / "api" / "types.ts"


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate/check the GBP verification contract artifact and drift guard."
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write the canonical contract artifact to disk.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail with non-zero exit code when drift is detected.",
    )
    parser.add_argument(
        "--artifact-path",
        type=Path,
        default=DEFAULT_CONTRACT_ARTIFACT_PATH,
        help=f"Path to contract artifact JSON (default: {DEFAULT_CONTRACT_ARTIFACT_PATH}).",
    )
    parser.add_argument(
        "--frontend-types-path",
        type=Path,
        default=DEFAULT_FRONTEND_TYPES_PATH,
        help=f"Path to frontend TypeScript contract file (default: {DEFAULT_FRONTEND_TYPES_PATH}).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    from app.services.google_business_profile_verification_contract_guard import (
        run_verification_contract_guard,
        write_verification_contract_artifact,
    )

    args = _parse_args(sys.argv[1:] if argv is None else argv)
    should_write = args.write or not args.check

    if should_write:
        write_verification_contract_artifact(path=args.artifact_path)
        print(f"Wrote GBP verification contract artifact: {args.artifact_path}")

    errors = run_verification_contract_guard(
        artifact_path=args.artifact_path,
        frontend_types_path=args.frontend_types_path,
        check_artifact=args.check,
    )
    if errors:
        for error in errors:
            print(f"[contract-guard] {error}", file=sys.stderr)
        return 1

    print("GBP verification contract guard passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
