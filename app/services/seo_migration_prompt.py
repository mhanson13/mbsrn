from __future__ import annotations

from dataclasses import dataclass
import json


SEO_MIGRATION_PROMPT_VERSION = "seo-migration-v1"


@dataclass(frozen=True)
class SEOMigrationPrompt:
    system_prompt: str
    user_prompt: str
    prompt_version: str
    context_json_chars: int
    total_prompt_chars: int


def build_seo_migration_prompt(
    *,
    migration_context: dict[str, object],
    prompt_version: str = SEO_MIGRATION_PROMPT_VERSION,
    prompt_text_recommendations: str = "",
) -> SEOMigrationPrompt:
    context_json = json.dumps(migration_context, ensure_ascii=True, sort_keys=True)

    operator_overlay = (prompt_text_recommendations or "").strip()
    overlay_block = f"\n\nOPERATOR_PROMPT_OVERLAY:\n{operator_overlay}" if operator_overlay else ""

    system_prompt = (
        "You generate bounded static-website migration draft artifacts for SMB operators. "
        "Output must be strict JSON matching the provided schema. "
        "Never emit backend, infrastructure, CI, deployment, secret, auth, runtime, or package-manager files. "
        "Only emit static website artifacts under allowed relative paths. "
        "Do not claim publish/deploy execution. All outputs are draft-only."
    )

    user_prompt = (
        f"PROMPT_VERSION: {prompt_version}\n"
        "TASK: Produce a reviewable migration draft package.\n"
        "GOALS:\n"
        "- Treat imported source data as potentially weak/incomplete.\n"
        "- Prefer operator requirements and enriched content when conflicts exist.\n"
        "- Include explicit draft-only safeguards and publish/deploy placeholders.\n"
        "- Keep artifact set small and operator-reviewable.\n"
        f"{overlay_block}\n\n"
        "MIGRATION_CONTEXT_JSON:\n"
        f"{context_json}"
    )

    return SEOMigrationPrompt(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        prompt_version=prompt_version,
        context_json_chars=len(context_json),
        total_prompt_chars=len(system_prompt) + len(user_prompt),
    )
