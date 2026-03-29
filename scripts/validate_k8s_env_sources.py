#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_ENV_KEY_RE = re.compile(r"^(?P<indent>\s*)env:\s*$")
_ENV_ITEM_RE = re.compile(r"^(?P<indent>\s*)-\s+name:\s*(?P<name>.+?)\s*$")


def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _is_comment_or_empty(line: str) -> bool:
    stripped = line.strip()
    return not stripped or stripped.startswith("#")


def _finalize_item(
    *,
    path: Path,
    line_number: int,
    env_index: int,
    name: str | None,
    has_value: bool,
    has_value_from: bool,
    violations: list[str],
) -> None:
    if name and has_value and has_value_from:
        violations.append(
            (
                f"{path}:{line_number}: env[{env_index}] '{name}' defines both value and valueFrom "
                "(use exactly one source and omit empty literal value branches)."
            )
        )


def _scan_file(path: Path) -> list[str]:
    violations: list[str] = []
    lines = path.read_text(encoding="utf-8").splitlines()

    in_env_block = False
    env_indent = -1
    current_name: str | None = None
    current_line = 0
    current_item_indent = -1
    current_env_index = -1
    next_env_index = 0
    has_value = False
    has_value_from = False

    for index, line in enumerate(lines, start=1):
        if _is_comment_or_empty(line):
            continue

        indent = _indent_of(line)
        stripped = line.strip()

        if not in_env_block:
            env_match = _ENV_KEY_RE.match(line)
            if env_match:
                in_env_block = True
                env_indent = len(env_match.group("indent"))
                current_name = None
                current_line = 0
                current_item_indent = -1
                current_env_index = -1
                next_env_index = 0
                has_value = False
                has_value_from = False
            continue

        if indent <= env_indent:
            _finalize_item(
                path=path,
                line_number=current_line,
                env_index=current_env_index,
                name=current_name,
                has_value=has_value,
                has_value_from=has_value_from,
                violations=violations,
            )
            in_env_block = False
            env_indent = -1
            current_name = None
            current_line = 0
            current_item_indent = -1
            current_env_index = -1
            next_env_index = 0
            has_value = False
            has_value_from = False

            env_match = _ENV_KEY_RE.match(line)
            if env_match:
                in_env_block = True
                env_indent = len(env_match.group("indent"))
                next_env_index = 0
            continue

        item_match = _ENV_ITEM_RE.match(line)
        if item_match and len(item_match.group("indent")) > env_indent:
            _finalize_item(
                path=path,
                line_number=current_line,
                env_index=current_env_index,
                name=current_name,
                has_value=has_value,
                has_value_from=has_value_from,
                violations=violations,
            )
            current_name = item_match.group("name").strip().strip("\"'")
            current_line = index
            current_item_indent = len(item_match.group("indent"))
            current_env_index = next_env_index
            next_env_index += 1
            has_value = False
            has_value_from = False
            continue

        if current_name is None:
            continue
        if indent <= current_item_indent:
            continue
        if stripped.startswith("valueFrom:"):
            has_value_from = True
            continue
        if stripped.startswith("value:"):
            has_value = True

    if in_env_block:
        _finalize_item(
            path=path,
            line_number=current_line,
            env_index=current_env_index,
            name=current_name,
            has_value=has_value,
            has_value_from=has_value_from,
            violations=violations,
        )

    return violations


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail when a Kubernetes env item defines both value and valueFrom.")
    parser.add_argument("paths", nargs="+", help="Manifest files to scan.")
    args = parser.parse_args()

    all_violations: list[str] = []
    for raw_path in args.paths:
        path = Path(raw_path)
        if not path.exists():
            print(f"[FAIL] missing manifest file: {path}", file=sys.stderr)
            return 1
        all_violations.extend(_scan_file(path))

    if all_violations:
        print("[FAIL] found env items with both value and valueFrom:", file=sys.stderr)
        for violation in all_violations:
            print(f" - {violation}", file=sys.stderr)
        return 1

    print(f"[OK] validated {len(args.paths)} manifest file(s): env items use a single source.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
