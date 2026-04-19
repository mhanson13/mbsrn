from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.core.cloudsql_instance_preflight import classify_cloudsql_instance_inspection


def _read_optional_text(path_value: str | None) -> str | None:
    if not path_value:
        return None
    path = Path(path_value)
    if not path.exists():
        return None
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Classify Cloud SQL instance preflight outcomes from gcloud describe output.",
    )
    parser.add_argument("--exit-code", type=int, required=True)
    parser.add_argument("--state", default=None)
    parser.add_argument("--stderr-file", default=None)
    parser.add_argument(
        "--field",
        choices=("json", "reason_code", "message", "retryable", "detail", "stderr_summary"),
        default="json",
        help="Output a single field or full JSON payload.",
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    classification = classify_cloudsql_instance_inspection(
        describe_exit_code=args.exit_code,
        instance_state=args.state,
        stderr_text=_read_optional_text(args.stderr_file),
    )

    if args.field == "reason_code":
        print(classification.reason_code or "")
        return 0
    if args.field == "message":
        print(classification.message or "")
        return 0
    if args.field == "retryable":
        print("true" if classification.retryable else "false")
        return 0
    if args.field == "detail":
        print(classification.detail or "")
        return 0
    if args.field == "stderr_summary":
        print(classification.stderr_summary or "")
        return 0

    print(
        json.dumps(
            {
                "reason_code": classification.reason_code,
                "message": classification.message,
                "retryable": classification.retryable,
                "detail": classification.detail,
                "stderr_summary": classification.stderr_summary,
            },
            ensure_ascii=True,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
