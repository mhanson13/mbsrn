from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.core.cloudsql_proxy_failure import classify_cloudsql_proxy_failure


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
        description="Classify Cloud SQL proxy migration startup failures from log snippets.",
    )
    parser.add_argument("--proxy-log-file", default=None)
    parser.add_argument("--app-log-file", default=None)
    parser.add_argument(
        "--field",
        choices=("json", "reason_code", "message", "retryable"),
        default="json",
        help="Output a single field or full JSON payload.",
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    proxy_log_text = _read_optional_text(args.proxy_log_file)
    app_log_text = _read_optional_text(args.app_log_file)
    classification = classify_cloudsql_proxy_failure(
        proxy_log_text=proxy_log_text,
        app_log_text=app_log_text,
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

    print(
        json.dumps(
            {
                "reason_code": classification.reason_code,
                "message": classification.message,
                "retryable": classification.retryable,
            },
            ensure_ascii=True,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
