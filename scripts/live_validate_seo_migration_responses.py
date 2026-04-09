#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.integrations.seo_migration_artifact_provider import (
    OpenAISEOMigrationArtifactGenerationProvider,
    SEOMigrationArtifactProviderError,
)
from app.services.ai_response_contract_evaluator import evaluate_migration_artifact_response
from app.services.seo_migration_prompt import build_seo_migration_prompt


_EXPECTED_RESPONSES_CONTRACT: dict[str, Any] = {
    "top_level_keys": ["input", "model", "text"],
    "text_top_level_keys": ["format"],
    "text_format_keys": ["name", "schema", "strict", "type"],
    "input_mode": "string",
    "contains_messages_legacy": False,
    "contains_response_format_legacy": False,
    "contains_tools": False,
    "has_extra_request_options": False,
    "has_null_optional_fields": False,
    "schema_name": "seo_migration_artifact_response",
    "strict_enabled": True,
    "schema_object_nodes_non_false_additional_properties": 0,
    "schema_object_nodes_missing_required": 0,
}


def _load_env_value_from_dotenv(*, key: str) -> str | None:
    env_path = Path(".env")
    if not env_path.exists():
        return None
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if not line.startswith(f"{key}="):
            continue
        _, _, value = line.partition("=")
        stripped = value.strip().strip('"').strip("'")
        return stripped or None
    return None


def _ensure_runtime_env() -> None:
    os.environ.setdefault("APP_ENV", "local")
    os.environ["AI_MODEL_NAME"] = "gpt-5.1"
    api_key = os.getenv("AI_API_KEY")
    if not api_key:
        api_key = _load_env_value_from_dotenv(key="AI_API_KEY")
        if api_key:
            os.environ["AI_API_KEY"] = api_key
    if api_key and not os.getenv("AI_PROVIDER_API_KEY"):
        # Reuse existing app config/provider initialization wiring.
        os.environ["AI_PROVIDER_API_KEY"] = api_key


def _build_live_migration_context() -> dict[str, object]:
    return {
        "site_snapshot": {
            "business_id": "00000000-0000-0000-0000-000000000001",
            "site_id": "00000000-0000-0000-0000-000000000002",
            "display_name": "TNM Fire Protection",
            "base_url": "https://www.tnmfire.com/",
            "normalized_domain": "tnmfire.com",
            "industry": "fire protection",
            "primary_location": "Longmont, CO",
            "service_areas": ["Longmont", "Boulder County"],
            "location_context": {"text": "Longmont, CO", "strength": "high", "source": "live_validation"},
            "business_context": {
                "industry_context": "fire protection systems and compliance services",
                "industry_context_strength": "high",
                "service_focus_terms": ["inspection", "testing", "maintenance", "installation"],
                "target_customer_context": "local commercial and industrial businesses",
            },
        },
        "migration_workspace": {
            "workspace_id": "00000000-0000-0000-0000-000000000003",
            "source_url": "https://www.tnmfire.com/",
            "source_site_status": "ingested",
            "migration_status": "source_ingested",
        },
        "source_snapshot": {
            "title": "TNM Fire",
            "meta_description": "Fire protection systems, inspections, and local service.",
        },
        "operator_requirements": {
            "must_include_services": ["inspection", "testing", "repair"],
            "tone": "clear and trust-oriented",
            "contact_priority": "phone_and_form",
        },
        "enriched_content_notes": {
            "business_updates": [
                "Highlight local service coverage",
                "Clarify compliance-oriented service process",
            ],
        },
        "brand_business_facts_snapshot": {
            "business_name": "TNM Fire Protection",
            "phone": "(303) 000-0000",
            "email": "info@tnmfire.com",
        },
        "existing_context_summaries": {
            "site_summary": "Local fire protection service provider with inspection and testing focus.",
            "audit_summary": "Current site lacks conversion-oriented structure.",
            "recommendation_summary": "Improve service specificity and contact pathways.",
            "competitor_summary": "Competitors use stronger service detail and trust signals.",
        },
    }


def _build_payload_diff(*, fingerprint: dict[str, Any]) -> list[dict[str, Any]]:
    diffs: list[dict[str, Any]] = []
    for key, expected in _EXPECTED_RESPONSES_CONTRACT.items():
        actual = fingerprint.get(key)
        if actual != expected:
            diffs.append({"field": key, "expected": expected, "actual": actual})
    if isinstance(fingerprint.get("input_length_chars"), int):
        if int(fingerprint["input_length_chars"]) <= 0:
            diffs.append({"field": "input_length_chars", "expected": ">0", "actual": fingerprint["input_length_chars"]})
    else:
        diffs.append({"field": "input_length_chars", "expected": ">0", "actual": fingerprint.get("input_length_chars")})
    return diffs


def _artifact_status_from_evaluation_status(status: str) -> str:
    if status == "salvaged":
        return "partial"
    if status in {"accepted", "accepted_with_warnings"}:
        return "completed"
    return "failed"


def _artifact_result_from_status(status: str) -> str:
    if status == "completed":
        return "succeeded"
    if status == "partial":
        return "partial"
    return "failed"


def _safe_snapshot_overview(snapshot: dict[str, Any], fingerprint: dict[str, Any]) -> dict[str, Any]:
    text_payload = snapshot.get("text")
    text_format_payload: dict[str, Any] | None = None
    if isinstance(text_payload, dict):
        text_format = text_payload.get("format")
        if isinstance(text_format, dict):
            text_format_payload = text_format

    schema_payload = text_format_payload.get("schema") if isinstance(text_format_payload, dict) else None
    schema_keys = sorted(str(key) for key in schema_payload.keys()) if isinstance(schema_payload, dict) else []
    return {
        "top_level_keys": fingerprint.get("top_level_keys") or [],
        "text_top_level_keys": fingerprint.get("text_top_level_keys") or [],
        "text_format_keys": fingerprint.get("text_format_keys") or [],
        "schema_top_level_keys": schema_keys,
        "input_mode": fingerprint.get("input_mode"),
        "input_length_chars": fingerprint.get("input_length_chars"),
    }


def main() -> int:
    _ensure_runtime_env()
    api_key_present = bool(os.getenv("AI_API_KEY") or os.getenv("AI_PROVIDER_API_KEY"))
    if not api_key_present:
        print(
            json.dumps(
                {
                    "status": "skipped",
                    "reason": "AI_API_KEY not found in environment or .env",
                },
                ensure_ascii=True,
                sort_keys=True,
            )
        )
        return 0

    settings = get_settings()
    live_timeout_seconds = max(120, int(settings.ai_timeout_value))
    provider = OpenAISEOMigrationArtifactGenerationProvider(
        api_key=(settings.ai_provider_api_key or os.getenv("AI_API_KEY") or "").strip(),
        model_name="gpt-5.1",
        timeout_seconds=live_timeout_seconds,
        api_base_url=settings.openai_api_base_url,
        prompt_text_recommendations=settings.ai_prompt_text_recommendations,
    )
    context = _build_live_migration_context()
    request_context = provider._build_request_context(context)  # noqa: SLF001
    prompt = build_seo_migration_prompt(
        migration_context=context,
        prompt_version=provider.prompt_version,
        prompt_text_recommendations=provider.prompt_text_recommendations,
    )
    payload = provider._build_request_payload(  # noqa: SLF001
        system_prompt=prompt.system_prompt,
        user_prompt=prompt.user_prompt,
        request_profile=request_context,
    )
    fingerprint = provider._build_request_fingerprint(payload=payload, request_context=request_context)  # noqa: SLF001
    redacted_snapshot = provider.build_redacted_request_snapshot(payload=payload)
    redacted_snapshot_serialized = provider.serialize_redacted_request_snapshot(payload=payload)
    compatibility = provider.evaluate_compatibility()
    compatibility_decision = "allowed" if compatibility.supported else "blocked_local_preflight"
    payload_diff = _build_payload_diff(fingerprint=fingerprint)

    safe_result: dict[str, Any] = {
        "status": "pending",
        "execution": {
            "model_used": "gpt-5.1",
            "endpoint_path": compatibility.endpoint_path,
            "request_body_mode": compatibility.request_body_mode,
            "compatibility_decision": compatibility_decision,
            "request_contract_status": ("blocked" if not compatibility.supported else None),
            "provider_execution_status": ("not_called" if not compatibility.supported else None),
            "artifact_status": ("failed" if not compatibility.supported else None),
            "artifact_result": ("failed" if not compatibility.supported else None),
            "duration_ms": 0,
        },
        "request_fingerprint": {
            "input_mode": fingerprint.get("input_mode"),
            "has_extra_request_options": fingerprint.get("has_extra_request_options"),
            "has_null_optional_fields": fingerprint.get("has_null_optional_fields"),
            "schema_object_nodes_missing_required": fingerprint.get("schema_object_nodes_missing_required"),
            "schema_object_nodes_non_false_additional_properties": fingerprint.get(
                "schema_object_nodes_non_false_additional_properties"
            ),
            "top_level_keys": fingerprint.get("top_level_keys"),
            "text_top_level_keys": fingerprint.get("text_top_level_keys"),
            "text_format_keys": fingerprint.get("text_format_keys"),
            "input_length_chars": fingerprint.get("input_length_chars"),
            "schema_name": fingerprint.get("schema_name"),
            "strict_enabled": fingerprint.get("strict_enabled"),
        },
        "redacted_request_snapshot_overview": _safe_snapshot_overview(
            snapshot=redacted_snapshot if isinstance(redacted_snapshot, dict) else {},
            fingerprint=fingerprint,
        ),
        "redacted_snapshot_serialized_length": len(redacted_snapshot_serialized),
        "known_good_contract_diff": payload_diff,
    }

    if not compatibility.supported:
        safe_result["status"] = "blocked_local_preflight"
        print(json.dumps(safe_result, ensure_ascii=True, sort_keys=True))
        return 1

    started_at = time.perf_counter()
    try:
        provider_output = provider.generate_artifacts(migration_context=context)
    except SEOMigrationArtifactProviderError as exc:
        duration_ms = max(0, int((time.perf_counter() - started_at) * 1000))
        safe_result["status"] = "failed"
        safe_result["execution"] = {
            **safe_result["execution"],
            "model_used": "gpt-5.1",
            "request_contract_status": "rejected",
            "provider_execution_status": "rejected",
            "artifact_status": "failed",
            "artifact_result": "failed",
            "duration_ms": duration_ms,
            "failure_reason": exc.reason,
            "failure_code": exc.code,
            "failure_source": "remote_provider",
            "retryable": exc.retryable,
            "correlation_id_present": bool(exc.correlation_id),
        }
        print(json.dumps(safe_result, ensure_ascii=True, sort_keys=True))
        return 1

    duration_ms = max(0, int((time.perf_counter() - started_at) * 1000))
    generated_files = [
        {"path": item.path, "content": item.content, "media_type": item.media_type}
        for item in provider_output.generated_files
    ]
    evaluation = evaluate_migration_artifact_response(
        strategy_summary=provider_output.strategy_summary,
        generated_files=generated_files,
        raw_generated_file_count=len(provider_output.generated_files),
        page_map_count=len(provider_output.page_map),
    )
    artifact_status = _artifact_status_from_evaluation_status(evaluation.status)
    artifact_result = _artifact_result_from_status(artifact_status)
    safe_result["status"] = "succeeded"
    safe_result["execution"] = {
        **safe_result["execution"],
        "model_used": provider_output.model_name,
        "request_contract_status": evaluation.status,
        "provider_execution_status": "accepted",
        "artifact_status": artifact_status,
        "artifact_result": artifact_result,
        "duration_ms": duration_ms,
    }
    print(json.dumps(safe_result, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
