from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Sequence

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.integrations.seo_summary_provider import MockSEOCompetitorProfileGenerationProvider
from app.jobs.seo_competitor_profile_generation_retention import SEOCompetitorProfileGenerationRetentionJob
from app.repositories.business_repository import BusinessRepository
from app.repositories.seo_competitor_profile_generation_repository import (
    SEOCompetitorProfileGenerationRepository,
)
from app.repositories.seo_competitor_repository import SEOCompetitorRepository
from app.repositories.seo_site_repository import SEOSiteRepository
from app.services.seo_competitor_profile_generation import (
    SEOCompetitorProfileGenerationService,
    SEOCompetitorProfileRetentionPolicy,
)
from app.services.seo_competitor_profile_prompt import SEO_COMPETITOR_PROFILE_PROMPT_VERSION


logger = logging.getLogger(__name__)


def run_seo_competitor_profile_generation_retention_cleanup(
    *,
    business_id: str | None,
    site_id: str | None,
) -> dict[str, object]:
    normalized_business_id = (business_id or "").strip() or None
    normalized_site_id = (site_id or "").strip() or None
    if normalized_site_id and not normalized_business_id:
        raise ValueError("--site-id requires --business-id")

    settings = get_settings()
    retention_policy = SEOCompetitorProfileRetentionPolicy(
        raw_output_retention_days=settings.seo_competitor_profile_raw_output_retention_days,
        run_retention_days=settings.seo_competitor_profile_run_retention_days,
        rejected_draft_retention_days=settings.seo_competitor_profile_rejected_draft_retention_days,
    )

    with SessionLocal() as session:
        business_repository = BusinessRepository(session)
        generation_service = SEOCompetitorProfileGenerationService(
            session=session,
            business_repository=business_repository,
            seo_site_repository=SEOSiteRepository(session),
            seo_competitor_repository=SEOCompetitorRepository(session),
            seo_competitor_profile_generation_repository=SEOCompetitorProfileGenerationRepository(session),
            provider=MockSEOCompetitorProfileGenerationProvider(
                provider_name="maintenance",
                model_name="maintenance-cleanup",
                prompt_version=SEO_COMPETITOR_PROFILE_PROMPT_VERSION,
            ),
            retention_policy=retention_policy,
        )
        cleanup_job = SEOCompetitorProfileGenerationRetentionJob(generation_service=generation_service)

        if normalized_business_id:
            business_ids = [normalized_business_id]
            scope = "business"
        else:
            business_ids = [item.id for item in business_repository.list()]
            scope = "global"

        logger.info(
            ("SEO competitor profile retention cleanup sweep started scope=%s " "site_id=%s business_count=%s"),
            scope,
            normalized_site_id or "all",
            len(business_ids),
        )

        totals = {
            "stale_runs_reconciled": 0,
            "raw_output_pruned_runs": 0,
            "rejected_drafts_pruned": 0,
            "runs_pruned": 0,
        }
        business_summaries: list[dict[str, int | str]] = []
        failures: list[dict[str, str]] = []

        for target_business_id in business_ids:
            try:
                summary = cleanup_job.run_cleanup(
                    business_id=target_business_id,
                    site_id=normalized_site_id,
                )
            except Exception as exc:  # noqa: BLE001
                session.rollback()
                failures.append(
                    {
                        "business_id": target_business_id,
                        "error": str(exc),
                    }
                )
                logger.exception(
                    "SEO competitor profile retention cleanup sweep failed for business_id=%s site_id=%s",
                    target_business_id,
                    normalized_site_id or "all",
                )
                continue

            totals["stale_runs_reconciled"] += summary.stale_runs_reconciled
            totals["raw_output_pruned_runs"] += summary.raw_output_pruned_runs
            totals["rejected_drafts_pruned"] += summary.rejected_drafts_pruned
            totals["runs_pruned"] += summary.runs_pruned
            business_summaries.append(
                {
                    "business_id": target_business_id,
                    "stale_runs_reconciled": summary.stale_runs_reconciled,
                    "raw_output_pruned_runs": summary.raw_output_pruned_runs,
                    "rejected_drafts_pruned": summary.rejected_drafts_pruned,
                    "runs_pruned": summary.runs_pruned,
                }
            )

        payload: dict[str, object] = {
            "scope": scope,
            "site_id": normalized_site_id,
            "businesses_scanned": len(business_ids),
            "businesses_succeeded": len(business_summaries),
            "businesses_failed": len(failures),
            "totals": totals,
            "business_summaries": business_summaries,
            "failures": failures,
        }
        if normalized_business_id:
            payload["business_id"] = normalized_business_id

        logger.info(
            (
                "SEO competitor profile retention cleanup sweep completed scope=%s site_id=%s "
                "businesses_scanned=%s businesses_failed=%s stale_runs_reconciled=%s "
                "raw_output_pruned_runs=%s rejected_drafts_pruned=%s runs_pruned=%s"
            ),
            scope,
            normalized_site_id or "all",
            payload["businesses_scanned"],
            payload["businesses_failed"],
            totals["stale_runs_reconciled"],
            totals["raw_output_pruned_runs"],
            totals["rejected_drafts_pruned"],
            totals["runs_pruned"],
        )
        return payload


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        summary = run_seo_competitor_profile_generation_retention_cleanup(
            business_id=args.business_id,
            site_id=args.site_id,
        )
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}, indent=2))
        return 2

    print(json.dumps(summary, indent=2))
    return 1 if int(summary.get("businesses_failed", 0)) > 0 else 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli.seo_competitor_profile_generation_retention_cleanup",
        description="Run SEO competitor profile generation retention cleanup across all businesses or one scope.",
    )
    parser.add_argument("--business-id", help="Limit cleanup to one business UUID.")
    parser.add_argument("--site-id", help="Limit cleanup to one site UUID (requires --business-id).")
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
