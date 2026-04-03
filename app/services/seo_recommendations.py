from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
import logging
import re
import time
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.models.seo_audit_finding import SEOAuditFinding
from app.models.seo_competitor_comparison_finding import SEOCompetitorComparisonFinding
from app.models.seo_recommendation import SEORecommendation
from app.models.seo_recommendation_run import SEORecommendationRun
from app.repositories.business_repository import BusinessRepository
from app.repositories.principal_repository import PrincipalRepository
from app.repositories.seo_audit_repository import SEOAuditRepository
from app.repositories.seo_action_chain_draft_repository import SEOActionChainDraftRepository
from app.repositories.seo_competitor_repository import SEOCompetitorRepository
from app.repositories.seo_recommendation_repository import (
    SEORecommendationListPageResult,
    SEORecommendationRepository,
)
from app.repositories.seo_site_repository import SEOSiteRepository
from app.schemas.action_chaining import ActionExecutionItem, NextActionDraft
from app.schemas.seo_recommendation import (
    SEORecommendationCompetitorEvidenceTrustTier,
    SEORecommendationListQuery,
    SEORecommendationRunCreateRequest,
    SEORecommendationWorkflowUpdateRequest,
)
from app.services.action_chaining_service import generate_next_actions


SEVERITY_RANK: dict[str, int] = {"INFO": 1, "WARNING": 2, "CRITICAL": 3}
SEVERITY_BASE_PRIORITY: dict[str, int] = {"INFO": 30, "WARNING": 60, "CRITICAL": 85}
EFFORT_BUCKETS: set[str] = {"LOW", "MEDIUM", "HIGH"}
PRIORITY_BANDS: tuple[str, ...] = ("low", "medium", "high", "critical")
WORKFLOW_STATUSES: tuple[str, ...] = ("open", "in_progress", "accepted", "dismissed", "snoozed", "resolved")
WORKFLOW_DECISIONS: tuple[str, ...] = ("accept", "dismiss", "snooze", "resolve", "reopen", "start")
ACTIONABLE_STATUSES: tuple[str, ...] = ("open", "in_progress", "accepted")
STATUS_TO_DECISION: dict[str, str] = {
    "open": "reopen",
    "in_progress": "start",
    "accepted": "accept",
    "dismissed": "dismiss",
    "snoozed": "snooze",
    "resolved": "resolve",
}
DECISION_TO_STATUS: dict[str, str] = {value: key for key, value in STATUS_TO_DECISION.items()}
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "open": {"in_progress", "accepted", "dismissed", "snoozed", "resolved"},
    "in_progress": {"open", "accepted", "dismissed", "snoozed", "resolved"},
    "accepted": {"open", "in_progress", "snoozed", "resolved", "dismissed"},
    "dismissed": {"open"},
    "snoozed": {"open", "in_progress", "accepted", "resolved", "dismissed"},
    "resolved": {"open"},
}
CHAINABLE_ACCEPTED_STATUS = "accepted"
CHAINABLE_COMPLETED_STATUS = "resolved"
CHAINED_ACTION_SOURCE = "action_chaining"
CHAINABLE_ACTION_TYPES: set[str] = {"seo_fix", "publish_content", "optimize_page"}
logger = logging.getLogger(__name__)


def classify_competitor_evidence_link(
    *,
    review_status: str | None,
    verification_status: str | None,
) -> SEORecommendationCompetitorEvidenceTrustTier:
    """Classify recommendation competitor evidence trust from persisted state only."""
    normalized_review_status = str(review_status or "").strip().lower()
    normalized_verification_status = str(verification_status or "").strip().lower()
    if normalized_review_status == "accepted":
        if normalized_verification_status == "verified":
            return "trusted_verified"
        if normalized_verification_status == "unverified":
            return "informational_unverified"
    return "informational_candidate"

AUDIT_TEMPLATES: dict[str, tuple[str, str, str]] = {
    "missing_title": ("fix_missing_title_tags", "Fix missing title tags", "LOW"),
    "duplicate_title": ("resolve_duplicate_title_tags", "Resolve duplicate title tags", "LOW"),
    "title_too_short": ("expand_short_title_tags", "Expand short title tags", "LOW"),
    "title_too_long": ("tighten_long_title_tags", "Tighten long title tags", "LOW"),
    "missing_meta_description": ("add_missing_meta_descriptions", "Add missing meta descriptions", "LOW"),
    "duplicate_meta_description": ("resolve_duplicate_meta_descriptions", "Resolve duplicate meta descriptions", "LOW"),
    "meta_description_too_short": ("expand_short_meta_descriptions", "Expand short meta descriptions", "LOW"),
    "meta_description_too_long": ("tighten_long_meta_descriptions", "Tighten long meta descriptions", "LOW"),
    "missing_h1": ("add_missing_h1_headings", "Add missing H1 headings", "MEDIUM"),
    "multiple_h1": ("normalize_multiple_h1_headings", "Normalize multiple H1 headings", "MEDIUM"),
    "missing_h2": ("add_supporting_h2_headings", "Add supporting H2 headings", "MEDIUM"),
    "thin_content": ("expand_thin_content_pages", "Expand thin-content pages", "HIGH"),
    "extremely_thin_content": ("expand_extremely_thin_pages", "Expand extremely thin pages", "HIGH"),
    "missing_canonical": ("add_missing_canonical_tags", "Add missing canonical tags", "LOW"),
    "missing_internal_links": ("improve_internal_linking", "Improve internal linking", "MEDIUM"),
    "broken_internal_links": ("repair_broken_internal_links", "Repair broken internal links", "MEDIUM"),
}

_CONTENT_TARGET_TYPE_LABELS: dict[str, str] = {
    "heading_h1": "Main heading",
    "heading_h2": "Supporting headings",
    "intro_paragraph": "Intro paragraph",
    "service_description": "Service description",
    "internal_links": "Internal links",
    "meta_title": "Meta title",
    "meta_description": "Meta description",
    "faq_block": "FAQ section",
    "image_alt_text": "Image alt text",
    "canonical_tag": "Canonical tag",
    "page_title_block": "Page title block",
    "call_to_action": "Call to action",
    "location_copy": "Location/service-area copy",
}

_AUDIT_FINDING_CONTENT_TARGETS: dict[str, tuple[str, ...]] = {
    "missing_title": ("meta_title",),
    "duplicate_title": ("meta_title",),
    "title_too_short": ("meta_title",),
    "title_too_long": ("meta_title",),
    "missing_meta_description": ("meta_description",),
    "duplicate_meta_description": ("meta_description",),
    "meta_description_too_short": ("meta_description",),
    "meta_description_too_long": ("meta_description",),
    "missing_h1": ("heading_h1", "page_title_block"),
    "multiple_h1": ("heading_h1", "heading_h2"),
    "missing_h2": ("heading_h2",),
    "thin_content": ("intro_paragraph", "service_description", "faq_block"),
    "extremely_thin_content": ("intro_paragraph", "service_description", "faq_block", "call_to_action"),
    "missing_canonical": ("canonical_tag",),
    "missing_internal_links": ("internal_links",),
    "broken_internal_links": ("internal_links",),
}

_COMPARISON_METRIC_CONTENT_TARGETS: dict[str, tuple[str, ...]] = {
    "missing_title_count": ("meta_title",),
    "title_coverage_percent": ("meta_title",),
    "missing_meta_description_count": ("meta_description",),
    "meta_description_coverage_percent": ("meta_description",),
    "missing_h1_count": ("heading_h1", "page_title_block"),
    "h1_coverage_percent": ("heading_h1", "page_title_block"),
    "thin_content_count": ("intro_paragraph", "service_description", "faq_block"),
    "missing_canonical_count": ("canonical_tag",),
    "canonical_coverage_percent": ("canonical_tag",),
    "missing_internal_links_count": ("internal_links",),
    "internal_links_coverage_percent": ("internal_links",),
    "page_count": ("service_description", "location_copy"),
}


class SEORecommendationNotFoundError(ValueError):
    pass


class SEORecommendationValidationError(ValueError):
    pass


@dataclass(frozen=True)
class SEORecommendationRunResult:
    run: SEORecommendationRun
    recommendations: list[SEORecommendation]


@dataclass(frozen=True)
class SEORecommendationReport:
    run: SEORecommendationRun
    recommendations: list[SEORecommendation]
    by_category: dict[str, int]
    by_severity: dict[str, int]
    by_effort_bucket: dict[str, int]


@dataclass(frozen=True)
class SEORecommendationBacklog:
    business_id: str
    site_id: str
    items: list[SEORecommendation]


@dataclass(frozen=True)
class SEORecommendationPrioritizedReport:
    business_id: str
    site_id: str
    generated_at: datetime
    total_recommendations: int
    backlog_items: list[SEORecommendation]
    by_status: dict[str, int]
    by_category: dict[str, int]
    by_severity: dict[str, int]
    by_effort_bucket: dict[str, int]
    by_priority_band: dict[str, int]


@dataclass
class _RecommendationDraft:
    rule_key: str
    category: str
    severity: str
    title: str
    rationale: str
    priority_score: int
    effort_bucket: str
    evidence: dict[str, object]


class SEORecommendationService:
    def __init__(
        self,
        *,
        session: Session,
        business_repository: BusinessRepository,
        principal_repository: PrincipalRepository,
        seo_site_repository: SEOSiteRepository,
        seo_audit_repository: SEOAuditRepository,
        seo_competitor_repository: SEOCompetitorRepository,
        seo_action_chain_draft_repository: SEOActionChainDraftRepository,
        seo_recommendation_repository: SEORecommendationRepository,
    ) -> None:
        self.session = session
        self.business_repository = business_repository
        self.principal_repository = principal_repository
        self.seo_site_repository = seo_site_repository
        self.seo_audit_repository = seo_audit_repository
        self.seo_competitor_repository = seo_competitor_repository
        self.seo_action_chain_draft_repository = seo_action_chain_draft_repository
        self.seo_recommendation_repository = seo_recommendation_repository

    def run_recommendations(
        self,
        *,
        business_id: str,
        site_id: str,
        payload: SEORecommendationRunCreateRequest,
        created_by_principal_id: str | None,
    ) -> SEORecommendationRunResult:
        self._require_business(business_id)
        self._require_site(business_id=business_id, site_id=site_id)

        audit_run = self._resolve_audit_run(
            business_id=business_id,
            site_id=site_id,
            audit_run_id=payload.audit_run_id,
        )
        comparison_run = self._resolve_comparison_run(
            business_id=business_id,
            site_id=site_id,
            comparison_run_id=payload.comparison_run_id,
        )

        run = SEORecommendationRun(
            id=str(uuid4()),
            business_id=business_id,
            site_id=site_id,
            audit_run_id=audit_run.id if audit_run is not None else None,
            comparison_run_id=comparison_run.id if comparison_run is not None else None,
            status="queued",
            total_recommendations=0,
            critical_recommendations=0,
            warning_recommendations=0,
            info_recommendations=0,
            category_counts_json={},
            effort_bucket_counts_json={},
            created_by_principal_id=created_by_principal_id,
        )
        try:
            self.seo_recommendation_repository.create_run(run)
            self.session.commit()
        except ValueError as exc:
            self.session.rollback()
            raise SEORecommendationValidationError(str(exc)) from exc

        started = time.monotonic()
        run.status = "running"
        run.started_at = utc_now()
        self.seo_recommendation_repository.save_run(run)
        self.session.commit()

        try:
            audit_findings = (
                self.seo_audit_repository.list_findings_for_business_run(business_id, audit_run.id)
                if audit_run is not None
                else []
            )
            comparison_findings = (
                self.seo_competitor_repository.list_comparison_findings_for_business_run(business_id, comparison_run.id)
                if comparison_run is not None
                else []
            )

            drafts = self._build_recommendation_drafts(
                audit_findings=audit_findings,
                comparison_findings=comparison_findings,
            )
            recommendations = self._persist_recommendations(
                run=run,
                drafts=drafts,
            )

            by_category, by_severity, by_effort = self._summarize_recommendations(recommendations)
            run.total_recommendations = len(recommendations)
            run.critical_recommendations = by_severity.get("CRITICAL", 0)
            run.warning_recommendations = by_severity.get("WARNING", 0)
            run.info_recommendations = by_severity.get("INFO", 0)
            run.category_counts_json = by_category
            run.effort_bucket_counts_json = by_effort
            run.status = "completed"
            run.completed_at = utc_now()
            run.duration_ms = int((time.monotonic() - started) * 1000)
            run.error_summary = None
            self.seo_recommendation_repository.save_run(run)
            self.session.commit()
            self.session.refresh(run)
            return SEORecommendationRunResult(run=run, recommendations=recommendations)
        except Exception as exc:  # noqa: BLE001
            self.session.rollback()
            run.status = "failed"
            run.completed_at = utc_now()
            run.duration_ms = int((time.monotonic() - started) * 1000)
            run.error_summary = str(exc)[:1000]
            self.seo_recommendation_repository.save_run(run)
            self.session.commit()
            raise SEORecommendationValidationError("Deterministic recommendation run failed") from exc

    def list_runs(self, *, business_id: str, site_id: str) -> list[SEORecommendationRun]:
        self._require_business(business_id)
        self._require_site(business_id=business_id, site_id=site_id)
        return self.seo_recommendation_repository.list_runs_for_business_site(business_id, site_id)

    def get_run(self, *, business_id: str, recommendation_run_id: str) -> SEORecommendationRun:
        self._require_business(business_id)
        run = self.seo_recommendation_repository.get_run_for_business(business_id, recommendation_run_id)
        if run is None:
            raise SEORecommendationNotFoundError("SEO recommendation run not found")
        return run

    def list_recommendations(
        self,
        *,
        business_id: str,
        recommendation_run_id: str,
    ) -> list[SEORecommendation]:
        self.get_run(business_id=business_id, recommendation_run_id=recommendation_run_id)
        return self.seo_recommendation_repository.list_recommendations_for_business_run(
            business_id,
            recommendation_run_id,
        )

    def get_recommendation(self, *, business_id: str, recommendation_id: str) -> SEORecommendation:
        self._require_business(business_id)
        recommendation = self.seo_recommendation_repository.get_recommendation_for_business(
            business_id,
            recommendation_id,
        )
        if recommendation is None:
            raise SEORecommendationNotFoundError("SEO recommendation not found")
        return recommendation

    def list_site_recommendations(
        self,
        *,
        business_id: str,
        site_id: str,
        query: SEORecommendationListQuery,
    ) -> SEORecommendationListPageResult:
        self._require_business(business_id)
        self._require_site(business_id=business_id, site_id=site_id)
        return self.seo_recommendation_repository.list_recommendations_page_for_business_site(
            business_id=business_id,
            site_id=site_id,
            page=query.page,
            page_size=query.page_size,
            status=query.status,
            category=query.category,
            severity=query.severity,
            effort_bucket=query.effort_bucket,
            priority_band=query.priority_band,
            assigned_principal_id=query.assigned_principal_id,
            source_type=query.source_type,
            recommendation_run_id=query.recommendation_run_id,
            sort_by=query.sort_by,
            sort_order=query.sort_order,
        )

    def update_recommendation_workflow(
        self,
        *,
        business_id: str,
        site_id: str,
        recommendation_id: str,
        payload: SEORecommendationWorkflowUpdateRequest,
        updated_by_principal_id: str | None,
    ) -> SEORecommendation:
        self._require_business(business_id)
        self._require_site(business_id=business_id, site_id=site_id)
        recommendation = self.get_recommendation(business_id=business_id, recommendation_id=recommendation_id)
        if recommendation.site_id != site_id:
            raise SEORecommendationNotFoundError("SEO recommendation not found")

        updates = payload.model_dump(exclude_unset=True)
        if not updates:
            return recommendation

        if "note" in updates:
            note_value = updates.get("note")
            if "decision_reason" in updates and updates.get("decision_reason") != note_value:
                raise SEORecommendationValidationError("note and decision_reason must match")
            updates["decision_reason"] = note_value

        now = utc_now()
        previous_status_normalized = self._normalize_status(recommendation.status)
        status, decision = self._resolve_status_and_decision(
            current_status=recommendation.status,
            current_decision=recommendation.decision,
            status_update=updates.get("status"),
            decision_update=updates.get("decision"),
        )

        if "assigned_principal_id" in updates:
            self._validate_assigned_principal(
                business_id=business_id,
                principal_id=updates.get("assigned_principal_id"),
            )
            recommendation.assigned_principal_id = updates.get("assigned_principal_id")

        if "decision_reason" in updates:
            recommendation.decision_reason = updates.get("decision_reason")

        if "due_at" in updates:
            recommendation.due_at = updates.get("due_at")

        snoozed_until_update = updates.get("snoozed_until") if "snoozed_until" in updates else None
        self._apply_status_rules(
            recommendation=recommendation,
            previous_status=recommendation.status,
            next_status=status,
            decision=decision,
            now=now,
            snoozed_until_update=snoozed_until_update,
            snoozed_until_provided="snoozed_until" in updates,
        )

        recommendation.updated_by_principal_id = updated_by_principal_id
        recommendation.updated_at = now
        self.seo_recommendation_repository.save_recommendation(recommendation)
        self.session.commit()
        self.session.refresh(recommendation)

        self._trigger_action_chaining_if_needed(
            recommendation=recommendation,
            previous_status=previous_status_normalized,
            updated_by_principal_id=updated_by_principal_id,
        )
        return recommendation

    def get_backlog(
        self,
        *,
        business_id: str,
        site_id: str,
    ) -> SEORecommendationBacklog:
        self._require_business(business_id)
        self._require_site(business_id=business_id, site_id=site_id)
        items = self.seo_recommendation_repository.list_actionable_recommendations_for_business_site(
            business_id=business_id,
            site_id=site_id,
            now=utc_now(),
        )
        return SEORecommendationBacklog(
            business_id=business_id,
            site_id=site_id,
            items=items,
        )

    def list_chained_action_drafts(
        self,
        *,
        business_id: str,
        site_id: str,
        source_action_id: str,
    ) -> list[NextActionDraft]:
        self._require_business(business_id)
        self._require_site(business_id=business_id, site_id=site_id)
        records = self.seo_action_chain_draft_repository.list_for_business_site_source_action(
            business_id=business_id,
            site_id=site_id,
            source_action_id=source_action_id,
        )
        return [
            NextActionDraft(
                id=record.id,
                action_type=record.action_type,
                title=record.title,
                description=record.description,
                source_action_id=record.source_action_id,
                priority=record.priority,
                activation_state=record.activation_state,
                activated_action_id=record.activated_action_id,
                automation_template_key=record.automation_template_key,
                automation_ready=bool(record.automation_ready),
                metadata=record.metadata_json or {},
            )
            for record in records
        ]

    def _trigger_action_chaining_if_needed(
        self,
        *,
        recommendation: SEORecommendation,
        previous_status: str,
        updated_by_principal_id: str | None,
    ) -> None:
        chained_state = self._derive_chained_state_for_transition(
            previous_status=previous_status,
            next_status=self._normalize_status(recommendation.status),
        )
        if chained_state is None:
            return

        action_type = self._derive_chainable_action_type(recommendation)
        if action_type is None:
            return

        source_action = ActionExecutionItem(
            action_id=recommendation.id,
            action_type=action_type,
            state=chained_state,
            title=recommendation.title,
            metadata={
                "business_id": recommendation.business_id,
                "site_id": recommendation.site_id,
                "recommendation_run_id": recommendation.recommendation_run_id,
                "source_rule_key": recommendation.rule_key,
                "source_status": recommendation.status,
            },
        )
        next_action_drafts = generate_next_actions(source_action)
        if not next_action_drafts:
            return

        generated_action_types: list[str] = []
        try:
            for draft in next_action_drafts:
                normalized_metadata = dict(draft.metadata or {})
                normalized_metadata.update(
                    {
                        "source": CHAINED_ACTION_SOURCE,
                        "source_rule_key": recommendation.rule_key,
                        "source_status": recommendation.status,
                        "updated_by_principal_id": updated_by_principal_id,
                    }
                )
                draft_for_persistence: NextActionDraft = draft.model_copy(
                    update={
                        "source_action_id": recommendation.id,
                        "metadata": normalized_metadata,
                    }
                )
                _, created = self.seo_action_chain_draft_repository.create_if_missing(
                    business_id=recommendation.business_id,
                    site_id=recommendation.site_id,
                    source_action_id=recommendation.id,
                    draft=draft_for_persistence,
                )
                if created:
                    generated_action_types.append(draft_for_persistence.action_type)
            if not generated_action_types:
                return
            self.session.commit()
        except Exception:  # noqa: BLE001
            self.session.rollback()
            logger.exception(
                "event=action_chaining_generate_failed source_action_id=%s action_type=%s",
                recommendation.id,
                action_type,
            )
            return

        logger.info(
            "event=action_chaining_generated source_action_id=%s generated_count=%s action_types=%s",
            recommendation.id,
            len(generated_action_types),
            generated_action_types,
        )

    def _derive_chained_state_for_transition(self, *, previous_status: str, next_status: str) -> str | None:
        if next_status == CHAINABLE_ACCEPTED_STATUS and previous_status != CHAINABLE_ACCEPTED_STATUS:
            return "accepted"
        if next_status == CHAINABLE_COMPLETED_STATUS and previous_status != CHAINABLE_COMPLETED_STATUS:
            return "completed"
        return None

    def _derive_chainable_action_type(self, recommendation: SEORecommendation) -> str | None:
        candidate = (recommendation.rule_key or "").strip().lower()
        if candidate in CHAINABLE_ACTION_TYPES:
            return candidate
        return None

    def get_prioritized_report(
        self,
        *,
        business_id: str,
        site_id: str,
    ) -> SEORecommendationPrioritizedReport:
        self._require_business(business_id)
        self._require_site(business_id=business_id, site_id=site_id)
        all_items = self.seo_recommendation_repository.list_recommendations_for_business_site(
            business_id=business_id,
            site_id=site_id,
            sort_by="priority_score",
            sort_order="desc",
        )
        backlog = self.get_backlog(business_id=business_id, site_id=site_id)
        by_status, by_category, by_severity, by_effort_bucket, by_priority_band = self._summarize_workflow(all_items)

        return SEORecommendationPrioritizedReport(
            business_id=business_id,
            site_id=site_id,
            generated_at=utc_now(),
            total_recommendations=len(all_items),
            backlog_items=backlog.items,
            by_status=by_status,
            by_category=by_category,
            by_severity=by_severity,
            by_effort_bucket=by_effort_bucket,
            by_priority_band=by_priority_band,
        )

    def get_report(
        self,
        *,
        business_id: str,
        recommendation_run_id: str,
    ) -> SEORecommendationReport:
        run = self.get_run(business_id=business_id, recommendation_run_id=recommendation_run_id)
        recommendations = self.list_recommendations(
            business_id=business_id,
            recommendation_run_id=recommendation_run_id,
        )

        by_category = self._normalize_int_map(run.category_counts_json)
        by_effort = self._normalize_int_map(run.effort_bucket_counts_json)
        by_severity = {
            "CRITICAL": run.critical_recommendations,
            "WARNING": run.warning_recommendations,
            "INFO": run.info_recommendations,
        }

        if not by_category or not by_effort:
            by_category, by_severity, by_effort = self._summarize_recommendations(recommendations)

        return SEORecommendationReport(
            run=run,
            recommendations=recommendations,
            by_category=by_category,
            by_severity=by_severity,
            by_effort_bucket=by_effort,
        )

    def _build_recommendation_drafts(
        self,
        *,
        audit_findings: list[SEOAuditFinding],
        comparison_findings: list[SEOCompetitorComparisonFinding],
    ) -> list[_RecommendationDraft]:
        drafts: dict[str, _RecommendationDraft] = {}

        audit_groups = self._group_audit_findings(audit_findings)
        for finding_type, grouped in audit_groups.items():
            template = AUDIT_TEMPLATES.get(finding_type)
            if template is None:
                continue
            rule_key, title, effort_bucket = template
            severity = grouped["severity"]
            count = grouped["count"]
            category = grouped["category"]
            priority = self._priority_score(
                severity=severity,
                count=count,
                source="audit",
            )
            content_targets = self._derive_audit_content_targets(finding_type)
            target_content_summary = self._format_target_content_summary(content_targets)
            rationale = self._build_audit_recommendation_rationale(
                finding_type=finding_type,
                finding_count=count,
                target_content_summary=target_content_summary,
            )
            self._upsert_draft(
                drafts=drafts,
                draft=_RecommendationDraft(
                    rule_key=rule_key,
                    category=category,
                    severity=severity,
                    title=title,
                    rationale=rationale,
                    priority_score=priority,
                    effort_bucket=effort_bucket,
                    evidence={
                        "sources": ["audit"],
                        "finding_types": [finding_type],
                        "counts": {finding_type: count},
                        "target_content_types": content_targets,
                        "target_content_summary": target_content_summary,
                    },
                ),
            )

        comparison_groups = self._group_comparison_findings(comparison_findings)
        for finding_type, grouped in comparison_groups.items():
            if finding_type in {"missing_client_baseline", "empty_competitor_snapshot"}:
                rule_key = f"comparison_{finding_type}"
                title = "Address deterministic comparison prerequisites"
                effort_bucket = "LOW"
            else:
                metric_key = re.sub(r"_gap$", "", finding_type)
                rule_key = f"close_competitor_gap_{metric_key}"
                title = f"Close competitor gap: {grouped['title']}"
                effort_bucket = self._comparison_effort_bucket(metric_key)

            severity = grouped["severity"]
            count = grouped["count"]
            category = grouped["category"]
            trails_count = grouped["client_trails_count"]
            if trails_count == 0 and finding_type not in {"missing_client_baseline", "empty_competitor_snapshot"}:
                continue

            priority = self._priority_score(
                severity=severity,
                count=max(count, trails_count),
                source="comparison",
            )
            metric_key = re.sub(r"_gap$", "", finding_type)
            content_targets = self._derive_comparison_content_targets(finding_type=finding_type, metric_key=metric_key)
            target_content_summary = self._format_target_content_summary(content_targets)
            rationale = self._build_comparison_recommendation_rationale(
                finding_type=finding_type,
                fallback_rationale=str(grouped["rationale"]),
                target_content_summary=target_content_summary,
            )
            self._upsert_draft(
                drafts=drafts,
                draft=_RecommendationDraft(
                    rule_key=rule_key,
                    category=category,
                    severity=severity,
                    title=title,
                    rationale=rationale,
                    priority_score=priority,
                    effort_bucket=effort_bucket,
                    evidence={
                        "sources": ["comparison"],
                        "finding_types": [finding_type],
                        "counts": {finding_type: count},
                        "client_trails_count": trails_count,
                        "target_content_types": content_targets,
                        "target_content_summary": target_content_summary,
                    },
                ),
            )

        return sorted(
            drafts.values(),
            key=lambda item: (-item.priority_score, item.rule_key),
        )

    def _persist_recommendations(
        self,
        *,
        run: SEORecommendationRun,
        drafts: list[_RecommendationDraft],
    ) -> list[SEORecommendation]:
        recommendations: list[SEORecommendation] = []
        for draft in drafts:
            recommendation = SEORecommendation(
                id=str(uuid4()),
                business_id=run.business_id,
                site_id=run.site_id,
                recommendation_run_id=run.id,
                audit_run_id=run.audit_run_id,
                comparison_run_id=run.comparison_run_id,
                rule_key=draft.rule_key,
                category=draft.category,
                severity=draft.severity,
                title=draft.title,
                rationale=draft.rationale,
                priority_score=draft.priority_score,
                priority_band=self._priority_band_for_score(draft.priority_score),
                effort_bucket=draft.effort_bucket,
                status="open",
                evidence_json=draft.evidence,
            )
            self.seo_recommendation_repository.add_recommendation(recommendation)
            recommendations.append(recommendation)
        return recommendations

    def _group_audit_findings(self, findings: list[SEOAuditFinding]) -> dict[str, dict[str, object]]:
        grouped: dict[str, dict[str, object]] = {}
        for finding in findings:
            key = finding.finding_type.strip().lower()
            entry = grouped.setdefault(
                key,
                {
                    "count": 0,
                    "severity": "INFO",
                    "category": finding.category.strip().upper() or "TECHNICAL",
                },
            )
            entry["count"] = int(entry["count"]) + 1
            entry["severity"] = self._max_severity(str(entry["severity"]), finding.severity)
            entry["category"] = str(entry["category"]).strip().upper() or "TECHNICAL"
        return grouped

    def _group_comparison_findings(
        self,
        findings: list[SEOCompetitorComparisonFinding],
    ) -> dict[str, dict[str, object]]:
        grouped: dict[str, dict[str, object]] = {}
        for finding in findings:
            key = finding.finding_type.strip().lower()
            entry = grouped.setdefault(
                key,
                {
                    "count": 0,
                    "client_trails_count": 0,
                    "severity": "INFO",
                    "category": finding.category.strip().upper() or "TECHNICAL",
                    "title": finding.title,
                    "rationale": "",
                },
            )
            entry["count"] = int(entry["count"]) + 1
            if (finding.gap_direction or "").strip().lower() == "client_trails":
                entry["client_trails_count"] = int(entry["client_trails_count"]) + 1
            entry["severity"] = self._max_severity(str(entry["severity"]), finding.severity)
            entry["category"] = str(entry["category"]).strip().upper() or "TECHNICAL"
            entry["title"] = finding.title
            entry["rationale"] = (
                f"{int(entry['count'])} persisted comparison finding(s) for '{finding.finding_type}' "
                f"with {int(entry['client_trails_count'])} trailing the competitor baseline."
            )
        return grouped

    def _upsert_draft(self, *, drafts: dict[str, _RecommendationDraft], draft: _RecommendationDraft) -> None:
        existing = drafts.get(draft.rule_key)
        if existing is None:
            drafts[draft.rule_key] = draft
            return

        merged_sources = sorted(
            set(self._to_str_list(existing.evidence.get("sources")) + self._to_str_list(draft.evidence.get("sources")))
        )
        merged_types = sorted(
            set(
                self._to_str_list(existing.evidence.get("finding_types"))
                + self._to_str_list(draft.evidence.get("finding_types"))
            )
        )
        merged_counts = self._merge_count_maps(
            existing.evidence.get("counts"),
            draft.evidence.get("counts"),
        )
        merged_target_content_types = self._merge_target_content_types(
            existing.evidence.get("target_content_types"),
            draft.evidence.get("target_content_types"),
        )
        merged_target_content_summary = self._format_target_content_summary(merged_target_content_types)

        drafts[draft.rule_key] = _RecommendationDraft(
            rule_key=draft.rule_key,
            category=existing.category,
            severity=self._max_severity(existing.severity, draft.severity),
            title=existing.title,
            rationale=f"{existing.rationale} {draft.rationale}".strip(),
            priority_score=max(existing.priority_score, draft.priority_score),
            effort_bucket=self._max_effort(existing.effort_bucket, draft.effort_bucket),
            evidence={
                "sources": merged_sources,
                "finding_types": merged_types,
                "counts": merged_counts,
                "target_content_types": merged_target_content_types,
                "target_content_summary": merged_target_content_summary,
            },
        )

    def _derive_audit_content_targets(self, finding_type: str) -> list[dict[str, str]]:
        type_keys = _AUDIT_FINDING_CONTENT_TARGETS.get(finding_type, ())
        return self._build_target_content_entries(
            type_keys=type_keys,
            source_type="audit_signal",
            targeting_strength="high",
        )

    def _derive_comparison_content_targets(
        self,
        *,
        finding_type: str,
        metric_key: str,
    ) -> list[dict[str, str]]:
        type_keys = _COMPARISON_METRIC_CONTENT_TARGETS.get(metric_key, ())
        if not type_keys and finding_type in {"missing_client_baseline", "empty_competitor_snapshot"}:
            return []
        return self._build_target_content_entries(
            type_keys=type_keys,
            source_type="evidence_mapping",
            targeting_strength="medium",
        )

    def _build_target_content_entries(
        self,
        *,
        type_keys: tuple[str, ...],
        source_type: str,
        targeting_strength: str,
    ) -> list[dict[str, str]]:
        entries: list[dict[str, str]] = []
        seen: set[str] = set()
        for type_key in type_keys:
            normalized_type_key = str(type_key or "").strip().lower()
            if not normalized_type_key or normalized_type_key in seen:
                continue
            label = _CONTENT_TARGET_TYPE_LABELS.get(normalized_type_key)
            if label is None:
                continue
            seen.add(normalized_type_key)
            entries.append(
                {
                    "type_key": normalized_type_key,
                    "label": label,
                    "source_type": source_type,
                    "targeting_strength": targeting_strength,
                }
            )
            if len(entries) >= 4:
                break
        return entries

    def _merge_target_content_types(self, left_raw: object, right_raw: object) -> list[dict[str, str]]:
        merged: list[dict[str, str]] = []
        seen: set[str] = set()
        source_priority = {"audit_signal": 3, "evidence_mapping": 2, "deterministic_rule": 1}
        entries_by_type_key: dict[str, dict[str, str]] = {}
        for raw_item in self._to_dict_list(left_raw) + self._to_dict_list(right_raw):
            type_key = str(raw_item.get("type_key") or "").strip().lower()
            if not type_key:
                continue
            label = _CONTENT_TARGET_TYPE_LABELS.get(type_key) or str(raw_item.get("label") or "").strip()
            if not label:
                continue
            source_type = str(raw_item.get("source_type") or "").strip().lower() or "deterministic_rule"
            if source_type not in source_priority:
                source_type = "deterministic_rule"
            targeting_strength = str(raw_item.get("targeting_strength") or "").strip().lower()
            if targeting_strength not in {"high", "medium", "low"}:
                targeting_strength = "medium"
            current = entries_by_type_key.get(type_key)
            candidate = {
                "type_key": type_key,
                "label": label,
                "source_type": source_type,
                "targeting_strength": targeting_strength,
            }
            if current is None:
                entries_by_type_key[type_key] = candidate
                continue
            current_priority = source_priority.get(current["source_type"], 1)
            candidate_priority = source_priority.get(candidate["source_type"], 1)
            if candidate_priority > current_priority:
                entries_by_type_key[type_key] = candidate

        for raw_item in self._to_dict_list(left_raw) + self._to_dict_list(right_raw):
            type_key = str(raw_item.get("type_key") or "").strip().lower()
            if not type_key or type_key in seen:
                continue
            selected = entries_by_type_key.get(type_key)
            if selected is None:
                continue
            seen.add(type_key)
            merged.append(selected)
            if len(merged) >= 4:
                break
        return merged

    def _format_target_content_summary(self, target_content_types: list[dict[str, str]]) -> str | None:
        labels: list[str] = []
        seen: set[str] = set()
        for raw in target_content_types:
            label = str(raw.get("label") or "").strip()
            if not label:
                continue
            normalized = label.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            labels.append(label)
            if len(labels) >= 4:
                break
        if not labels:
            return None
        if len(labels) == 1:
            return labels[0]
        if len(labels) == 2:
            return f"{labels[0]} and {labels[1]}"
        return f"{', '.join(labels[:-1])}, and {labels[-1]}"

    def _build_audit_recommendation_rationale(
        self,
        *,
        finding_type: str,
        finding_count: int,
        target_content_summary: str | None,
    ) -> str:
        normalized_finding_label = finding_type.replace("_", " ").strip()
        count_text = f"{max(1, finding_count)} page finding{'s' if finding_count != 1 else ''}"
        if target_content_summary:
            return (
                f"{count_text} indicate a {normalized_finding_label} issue. "
                f"Update {target_content_summary.lower()} on the affected pages."
            )
        return f"{count_text} indicate a {normalized_finding_label} issue in the latest site analysis."

    def _build_comparison_recommendation_rationale(
        self,
        *,
        finding_type: str,
        fallback_rationale: str,
        target_content_summary: str | None,
    ) -> str:
        if target_content_summary:
            normalized_finding_label = finding_type.replace("_", " ").strip()
            return (
                f"Comparison signals indicate a {normalized_finding_label} gap. "
                f"Update {target_content_summary.lower()} to close the gap."
            )
        return fallback_rationale

    def _priority_score(self, *, severity: str, count: int, source: str) -> int:
        normalized = self._normalize_severity(severity)
        base = SEVERITY_BASE_PRIORITY.get(normalized, 30)
        count_boost = min(15, max(0, count) * 2)
        source_boost = 10 if source == "comparison" else 0
        return min(100, base + count_boost + source_boost)

    def _comparison_effort_bucket(self, metric_key: str) -> str:
        high_effort_metrics = {"page_count", "thin_content_count"}
        low_effort_metrics = {
            "missing_title_count",
            "missing_meta_description_count",
            "title_coverage_percent",
            "meta_description_coverage_percent",
        }
        if metric_key in high_effort_metrics:
            return "HIGH"
        if metric_key in low_effort_metrics:
            return "LOW"
        return "MEDIUM"

    def _resolve_audit_run(self, *, business_id: str, site_id: str, audit_run_id: str | None):
        if audit_run_id is None:
            return None
        run = self.seo_audit_repository.get_run_for_business(business_id, audit_run_id)
        if run is None:
            raise SEORecommendationNotFoundError("Audit run not found")
        if run.site_id != site_id:
            raise SEORecommendationValidationError("Audit run does not match site")
        if run.status != "completed":
            raise SEORecommendationValidationError("Audit run must be completed")
        return run

    def _resolve_comparison_run(
        self,
        *,
        business_id: str,
        site_id: str,
        comparison_run_id: str | None,
    ):
        if comparison_run_id is None:
            return None
        run = self.seo_competitor_repository.get_comparison_run_for_business(business_id, comparison_run_id)
        if run is None:
            raise SEORecommendationNotFoundError("Comparison run not found")
        if run.site_id != site_id:
            raise SEORecommendationValidationError("Comparison run does not match site")
        if run.status != "completed":
            raise SEORecommendationValidationError("Comparison run must be completed")
        return run

    def _summarize_recommendations(
        self,
        recommendations: list[SEORecommendation],
    ) -> tuple[dict[str, int], dict[str, int], dict[str, int]]:
        by_category = Counter()
        by_severity = Counter()
        by_effort = Counter()
        for item in recommendations:
            by_category[item.category.strip().upper()] += 1
            by_severity[self._normalize_severity(item.severity)] += 1
            by_effort[self._normalize_effort(item.effort_bucket)] += 1
        return dict(sorted(by_category.items())), dict(sorted(by_severity.items())), dict(sorted(by_effort.items()))

    def _summarize_workflow(
        self,
        recommendations: list[SEORecommendation],
    ) -> tuple[dict[str, int], dict[str, int], dict[str, int], dict[str, int], dict[str, int]]:
        by_status = Counter()
        by_category = Counter()
        by_severity = Counter()
        by_effort = Counter()
        by_priority_band = Counter()
        for item in recommendations:
            by_status[self._normalize_status(item.status)] += 1
            by_category[item.category.strip().upper()] += 1
            by_severity[self._normalize_severity(item.severity)] += 1
            by_effort[self._normalize_effort(item.effort_bucket)] += 1
            by_priority_band[self._normalize_priority_band(item.priority_band)] += 1
        return (
            dict(sorted(by_status.items())),
            dict(sorted(by_category.items())),
            dict(sorted(by_severity.items())),
            dict(sorted(by_effort.items())),
            dict(sorted(by_priority_band.items())),
        )

    def _resolve_status_and_decision(
        self,
        *,
        current_status: str,
        current_decision: str | None,
        status_update: str | None,
        decision_update: str | None,
    ) -> tuple[str, str | None]:
        status = self._normalize_status(status_update) if status_update is not None else None
        decision = self._normalize_decision(decision_update) if decision_update is not None else None

        if decision is not None and status is None:
            status = DECISION_TO_STATUS[decision]

        if decision is not None and status is not None:
            expected_status = DECISION_TO_STATUS[decision]
            if expected_status != status:
                raise SEORecommendationValidationError("status and decision do not match")

        if status is None:
            if decision is None:
                return current_status, current_decision
            return current_status, decision

        current = self._normalize_status(current_status)
        if status != current and status not in ALLOWED_TRANSITIONS.get(current, set()):
            raise SEORecommendationValidationError(f"Invalid status transition: {current} -> {status}")

        if decision is None:
            if status != current:
                decision = STATUS_TO_DECISION.get(status)
            else:
                decision = current_decision
        return status, decision

    def _apply_status_rules(
        self,
        *,
        recommendation: SEORecommendation,
        previous_status: str,
        next_status: str,
        decision: str | None,
        now: datetime,
        snoozed_until_update: datetime | None,
        snoozed_until_provided: bool,
    ) -> None:
        recommendation.status = next_status
        recommendation.decision = decision

        if next_status == "snoozed":
            effective_snoozed_until = snoozed_until_update if snoozed_until_provided else recommendation.snoozed_until
            if effective_snoozed_until is None:
                raise SEORecommendationValidationError("snoozed_until is required when status is snoozed")
            if effective_snoozed_until <= now:
                raise SEORecommendationValidationError("snoozed_until must be in the future")
            recommendation.snoozed_until = effective_snoozed_until
            recommendation.resolved_at = None
        else:
            if snoozed_until_provided and snoozed_until_update is not None:
                raise SEORecommendationValidationError("snoozed_until is only valid for snoozed status")
            recommendation.snoozed_until = None

        if next_status == "resolved":
            if self._normalize_status(previous_status) != "resolved" or recommendation.resolved_at is None:
                recommendation.resolved_at = now
        elif next_status != "snoozed":
            recommendation.resolved_at = None

    def _validate_assigned_principal(self, *, business_id: str, principal_id: str | None) -> None:
        if principal_id is None:
            return
        principal = self.principal_repository.get_for_business(business_id, principal_id)
        if principal is None:
            raise SEORecommendationValidationError("Assigned principal not found for business")
        if not principal.is_active:
            raise SEORecommendationValidationError("Assigned principal is inactive")

    def _normalize_int_map(self, raw: dict[str, object] | None) -> dict[str, int]:
        if not raw:
            return {}
        normalized: dict[str, int] = {}
        for key, value in raw.items():
            if not isinstance(key, str):
                continue
            try:
                normalized[key] = int(value)
            except (TypeError, ValueError):
                continue
        return normalized

    def _require_business(self, business_id: str) -> None:
        business = self.business_repository.get(business_id)
        if business is None:
            raise SEORecommendationNotFoundError("Business not found")

    def _require_site(self, *, business_id: str, site_id: str) -> None:
        site = self.seo_site_repository.get_for_business(business_id, site_id)
        if site is None:
            raise SEORecommendationNotFoundError("SEO site not found")

    def _max_severity(self, left: str, right: str) -> str:
        normalized_left = self._normalize_severity(left)
        normalized_right = self._normalize_severity(right)
        if SEVERITY_RANK[normalized_right] > SEVERITY_RANK[normalized_left]:
            return normalized_right
        return normalized_left

    def _normalize_severity(self, value: str) -> str:
        normalized = (value or "").strip().upper()
        if normalized not in SEVERITY_RANK:
            return "INFO"
        return normalized

    def _normalize_effort(self, value: str) -> str:
        normalized = (value or "").strip().upper()
        if normalized not in EFFORT_BUCKETS:
            return "MEDIUM"
        return normalized

    def _normalize_status(self, value: str | None) -> str:
        normalized = (value or "").strip().lower()
        if normalized not in WORKFLOW_STATUSES:
            return "open"
        return normalized

    def _normalize_decision(self, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if normalized not in WORKFLOW_DECISIONS:
            raise SEORecommendationValidationError("Invalid workflow decision")
        return normalized

    def _priority_band_for_score(self, priority_score: int) -> str:
        if priority_score >= 90:
            return "critical"
        if priority_score >= 75:
            return "high"
        if priority_score >= 50:
            return "medium"
        return "low"

    def _normalize_priority_band(self, value: str | None) -> str:
        normalized = (value or "").strip().lower()
        if normalized not in PRIORITY_BANDS:
            return "medium"
        return normalized

    def _max_effort(self, left: str, right: str) -> str:
        rank = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}
        left_norm = self._normalize_effort(left)
        right_norm = self._normalize_effort(right)
        return right_norm if rank[right_norm] > rank[left_norm] else left_norm

    def _to_str_list(self, raw: object) -> list[str]:
        if not isinstance(raw, list):
            return []
        return [str(item) for item in raw]

    def _to_dict_list(self, raw: object) -> list[dict[str, object]]:
        if not isinstance(raw, list):
            return []
        return [item for item in raw if isinstance(item, dict)]

    def _merge_count_maps(self, left: object, right: object) -> dict[str, int]:
        merged: Counter[str] = Counter()
        for raw in (left, right):
            if not isinstance(raw, dict):
                continue
            for key, value in raw.items():
                if not isinstance(key, str):
                    continue
                try:
                    merged[key] += int(value)
                except (TypeError, ValueError):
                    continue
        return dict(sorted(merged.items()))
