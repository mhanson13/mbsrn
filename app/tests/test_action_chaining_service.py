from __future__ import annotations

import socket
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.models.seo_action_execution_item import SEOActionExecutionItem
from app.models.seo_site import SEOSite
from app.repositories.business_repository import BusinessRepository
from app.repositories.seo_action_chain_draft_repository import SEOActionChainDraftRepository
from app.repositories.seo_action_execution_item_repository import SEOActionExecutionItemRepository
from app.repositories.seo_site_repository import SEOSiteRepository
from app.models.seo_recommendation import SEORecommendation
from app.schemas.action_chaining import ActionExecutionItem
from app.services.action_chain_activation_service import (
    ActionChainActivationService,
    SEOActionChainDraftNotFoundError,
)
from app.services.action_lineage_service import ActionLineageService
from app.services.action_chaining_service import generate_next_actions
from app.services.seo_recommendations import SEORecommendationService


def test_generate_next_actions_empty_for_unknown_type() -> None:
    action = ActionExecutionItem(
        action_id=str(uuid4()),
        action_type="unknown_action",
        state="accepted",
    )

    assert generate_next_actions(action) == []


def test_generate_next_actions_for_seo_fix() -> None:
    action = ActionExecutionItem(
        action_id=str(uuid4()),
        action_type="seo_fix",
        state="accepted",
    )

    drafts = generate_next_actions(action)

    assert len(drafts) == 1
    assert drafts[0].action_type == "verify_fix"
    assert drafts[0].source_action_id == action.action_id


def test_generate_next_actions_for_completed_action() -> None:
    action = ActionExecutionItem(
        action_id=str(uuid4()),
        action_type="publish_content",
        state="completed",
    )

    drafts = generate_next_actions(action)

    assert len(drafts) == 1
    assert drafts[0].action_type == "promote_content"
    assert drafts[0].priority == "medium"
    assert drafts[0].automation_ready is True
    assert drafts[0].automation_template_key == "content_promotion_followup"


def test_generate_next_actions_for_optimize_page_completed_sets_automation_metadata() -> None:
    action = ActionExecutionItem(
        action_id=str(uuid4()),
        action_type="optimize_page",
        state="completed",
    )

    drafts = generate_next_actions(action)

    assert len(drafts) == 1
    assert drafts[0].action_type == "measure_performance"
    assert drafts[0].automation_ready is True
    assert drafts[0].automation_template_key == "performance_check_followup"


def test_no_ai_calls(monkeypatch) -> None:
    def _raise_if_called(*args, **kwargs):
        raise AssertionError("Deterministic action chaining must not perform provider calls")

    monkeypatch.setattr(socket, "create_connection", _raise_if_called)
    action = ActionExecutionItem(
        action_id=str(uuid4()),
        action_type="seo_fix",
        state="accepted",
    )

    drafts = generate_next_actions(action)

    assert len(drafts) == 1


def test_state_transition_triggers_chaining() -> None:
    session = MagicMock()
    action_chain_repo = MagicMock()
    action_chain_repo.create_if_missing.return_value = (MagicMock(), True)
    service = SEORecommendationService(
        session=session,
        business_repository=MagicMock(),
        principal_repository=MagicMock(),
        seo_site_repository=MagicMock(),
        seo_audit_repository=MagicMock(),
        seo_competitor_repository=MagicMock(),
        seo_action_chain_draft_repository=action_chain_repo,
        seo_recommendation_repository=MagicMock(),
    )
    recommendation = SEORecommendation(
        id=str(uuid4()),
        business_id=str(uuid4()),
        site_id=str(uuid4()),
        recommendation_run_id=str(uuid4()),
        audit_run_id=None,
        comparison_run_id=None,
        rule_key="seo_fix",
        category="SEO",
        severity="INFO",
        title="Fix SEO metadata",
        rationale="Update metadata and canonical tags",
        priority_score=70,
        priority_band="medium",
        effort_bucket="LOW",
        status="accepted",
    )

    service._trigger_action_chaining_if_needed(
        recommendation=recommendation,
        previous_status="open",
        updated_by_principal_id="principal-1",
    )

    action_chain_repo.create_if_missing.assert_called_once()
    session.commit.assert_called_once()


def test_activate_chained_action_draft_creates_one_execution_item_and_is_idempotent(
    db_session,
    seeded_business,
) -> None:
    site = SEOSite(
        id=str(uuid4()),
        business_id=seeded_business.id,
        display_name="Action Chain Site",
        base_url="https://actions.example/",
        normalized_domain="actions.example",
        is_active=True,
        is_primary=False,
    )
    db_session.add(site)
    db_session.commit()

    draft_repository = SEOActionChainDraftRepository(db_session)
    execution_repository = SEOActionExecutionItemRepository(db_session)
    activation_service = ActionChainActivationService(
        session=db_session,
        business_repository=BusinessRepository(db_session),
        seo_site_repository=SEOSiteRepository(db_session),
        seo_action_chain_draft_repository=draft_repository,
        seo_action_execution_item_repository=execution_repository,
    )

    source_action_id = str(uuid4())
    draft_record, created = draft_repository.create_if_missing(
        business_id=seeded_business.id,
        site_id=site.id,
        source_action_id=source_action_id,
        draft=generate_next_actions(
            ActionExecutionItem(
                action_id=source_action_id,
                action_type="publish_content",
                state="completed",
            )
        )[0],
    )
    assert created is True
    db_session.commit()

    first = activation_service.activate_chained_action_draft(
        business_id=seeded_business.id,
        site_id=site.id,
        source_action_id=source_action_id,
        draft_id=draft_record.id,
        actor_principal_id="principal-1",
    )
    assert first.draft.activation_state == "activated"
    assert first.draft.activated_action_id is not None
    assert first.draft.automation_ready is True
    assert first.draft.automation_template_key == "content_promotion_followup"

    second = activation_service.activate_chained_action_draft(
        business_id=seeded_business.id,
        site_id=site.id,
        source_action_id=source_action_id,
        draft_id=draft_record.id,
        actor_principal_id="principal-2",
    )
    assert second.draft.activation_state == "activated"
    assert second.draft.activated_action_id == first.draft.activated_action_id

    execution_items = (
        db_session.query(SEOActionExecutionItem)
        .filter(SEOActionExecutionItem.business_id == seeded_business.id)
        .filter(SEOActionExecutionItem.site_id == site.id)
        .filter(SEOActionExecutionItem.source_draft_id == draft_record.id)
        .all()
    )
    assert len(execution_items) == 1
    assert execution_items[0].id == first.draft.activated_action_id
    assert execution_items[0].automation_ready is True
    assert execution_items[0].automation_template_key == "content_promotion_followup"


def test_activate_chained_action_draft_missing_draft_raises_not_found(db_session, seeded_business) -> None:
    site = SEOSite(
        id=str(uuid4()),
        business_id=seeded_business.id,
        display_name="Action Chain Site",
        base_url="https://actions.example/",
        normalized_domain="actions.example",
        is_active=True,
        is_primary=False,
    )
    db_session.add(site)
    db_session.commit()

    activation_service = ActionChainActivationService(
        session=db_session,
        business_repository=BusinessRepository(db_session),
        seo_site_repository=SEOSiteRepository(db_session),
        seo_action_chain_draft_repository=SEOActionChainDraftRepository(db_session),
        seo_action_execution_item_repository=SEOActionExecutionItemRepository(db_session),
    )

    with pytest.raises(SEOActionChainDraftNotFoundError):
        activation_service.activate_chained_action_draft(
            business_id=seeded_business.id,
            site_id=site.id,
            source_action_id=str(uuid4()),
            draft_id=str(uuid4()),
            actor_principal_id="principal-1",
        )


def test_action_lineage_service_returns_empty_when_no_chained_records(db_session, seeded_business) -> None:
    site = SEOSite(
        id=str(uuid4()),
        business_id=seeded_business.id,
        display_name="Lineage Site",
        base_url="https://lineage-empty.example/",
        normalized_domain="lineage-empty.example",
        is_active=True,
        is_primary=False,
    )
    db_session.add(site)
    db_session.commit()

    lineage_service = ActionLineageService(
        seo_action_chain_draft_repository=SEOActionChainDraftRepository(db_session),
        seo_action_execution_item_repository=SEOActionExecutionItemRepository(db_session),
    )
    source_action_id = str(uuid4())

    lineage = lineage_service.get_action_lineage(
        business_id=seeded_business.id,
        site_id=site.id,
        source_action_id=source_action_id,
    )

    assert lineage.source_action_id == source_action_id
    assert lineage.chained_drafts == []
    assert lineage.activated_actions == []
    assert lineage.counts.chained_draft_count == 0
    assert lineage.counts.activated_action_count == 0
    assert lineage.counts.automation_ready_count == 0


def test_action_lineage_service_returns_drafts_only_when_not_activated(db_session, seeded_business) -> None:
    site = SEOSite(
        id=str(uuid4()),
        business_id=seeded_business.id,
        display_name="Lineage Site",
        base_url="https://lineage-drafts.example/",
        normalized_domain="lineage-drafts.example",
        is_active=True,
        is_primary=False,
    )
    db_session.add(site)
    db_session.commit()

    source_action_id = str(uuid4())
    draft_repository = SEOActionChainDraftRepository(db_session)
    draft_repository.create_if_missing(
        business_id=seeded_business.id,
        site_id=site.id,
        source_action_id=source_action_id,
        draft=generate_next_actions(
            ActionExecutionItem(
                action_id=source_action_id,
                action_type="publish_content",
                state="completed",
            )
        )[0],
    )
    db_session.commit()

    lineage_service = ActionLineageService(
        seo_action_chain_draft_repository=draft_repository,
        seo_action_execution_item_repository=SEOActionExecutionItemRepository(db_session),
    )
    lineage = lineage_service.get_action_lineage(
        business_id=seeded_business.id,
        site_id=site.id,
        source_action_id=source_action_id,
    )

    assert lineage.counts.chained_draft_count == 1
    assert lineage.counts.activated_action_count == 0
    assert lineage.counts.automation_ready_count == 1
    assert lineage.chained_drafts[0].action_type == "promote_content"
    assert lineage.chained_drafts[0].activation_state == "pending"
    assert lineage.activated_actions == []


def test_action_lineage_service_returns_drafts_and_activated_actions(db_session, seeded_business) -> None:
    site = SEOSite(
        id=str(uuid4()),
        business_id=seeded_business.id,
        display_name="Lineage Site",
        base_url="https://lineage-activated.example/",
        normalized_domain="lineage-activated.example",
        is_active=True,
        is_primary=False,
    )
    db_session.add(site)
    db_session.commit()

    source_action_id = str(uuid4())
    draft_repository = SEOActionChainDraftRepository(db_session)
    execution_repository = SEOActionExecutionItemRepository(db_session)
    draft_record, _ = draft_repository.create_if_missing(
        business_id=seeded_business.id,
        site_id=site.id,
        source_action_id=source_action_id,
        draft=generate_next_actions(
            ActionExecutionItem(
                action_id=source_action_id,
                action_type="publish_content",
                state="completed",
            )
        )[0],
    )
    db_session.commit()

    activation_service = ActionChainActivationService(
        session=db_session,
        business_repository=BusinessRepository(db_session),
        seo_site_repository=SEOSiteRepository(db_session),
        seo_action_chain_draft_repository=draft_repository,
        seo_action_execution_item_repository=execution_repository,
    )
    activation_service.activate_chained_action_draft(
        business_id=seeded_business.id,
        site_id=site.id,
        source_action_id=source_action_id,
        draft_id=draft_record.id,
        actor_principal_id="principal-1",
    )

    lineage_service = ActionLineageService(
        seo_action_chain_draft_repository=draft_repository,
        seo_action_execution_item_repository=execution_repository,
    )
    lineage = lineage_service.get_action_lineage(
        business_id=seeded_business.id,
        site_id=site.id,
        source_action_id=source_action_id,
    )

    assert lineage.counts.chained_draft_count == 1
    assert lineage.counts.activated_action_count == 1
    assert lineage.counts.automation_ready_count == 1
    assert lineage.chained_drafts[0].activation_state == "activated"
    assert lineage.chained_drafts[0].activated_action_id == lineage.activated_actions[0].id
    assert lineage.activated_actions[0].source_draft_id == draft_record.id

    lineage_again = lineage_service.get_action_lineage(
        business_id=seeded_business.id,
        site_id=site.id,
        source_action_id=source_action_id,
    )
    assert lineage_again.model_dump() == lineage.model_dump()


def test_action_lineage_service_hydrates_multiple_drafts_deterministically(db_session, seeded_business) -> None:
    site = SEOSite(
        id=str(uuid4()),
        business_id=seeded_business.id,
        display_name="Lineage Site",
        base_url="https://lineage-multiple.example/",
        normalized_domain="lineage-multiple.example",
        is_active=True,
        is_primary=False,
    )
    db_session.add(site)
    db_session.commit()

    source_action_id = str(uuid4())
    draft_repository = SEOActionChainDraftRepository(db_session)
    draft_repository.create_if_missing(
        business_id=seeded_business.id,
        site_id=site.id,
        source_action_id=source_action_id,
        draft=generate_next_actions(
            ActionExecutionItem(
                action_id=source_action_id,
                action_type="publish_content",
                state="completed",
            )
        )[0],
    )
    draft_repository.create_if_missing(
        business_id=seeded_business.id,
        site_id=site.id,
        source_action_id=source_action_id,
        draft=generate_next_actions(
            ActionExecutionItem(
                action_id=source_action_id,
                action_type="optimize_page",
                state="completed",
            )
        )[0],
    )
    db_session.commit()

    lineage_service = ActionLineageService(
        seo_action_chain_draft_repository=draft_repository,
        seo_action_execution_item_repository=SEOActionExecutionItemRepository(db_session),
    )
    lineage = lineage_service.get_action_lineage(
        business_id=seeded_business.id,
        site_id=site.id,
        source_action_id=source_action_id,
    )

    assert lineage.counts.chained_draft_count == 2
    assert lineage.counts.activated_action_count == 0
    assert lineage.counts.automation_ready_count == 2
    assert [draft.action_type for draft in lineage.chained_drafts] == [
        "promote_content",
        "measure_performance",
    ]


def test_action_lineage_service_lists_lineage_for_multiple_source_actions(db_session, seeded_business) -> None:
    site = SEOSite(
        id=str(uuid4()),
        business_id=seeded_business.id,
        display_name="Lineage Site",
        base_url="https://lineage-map.example/",
        normalized_domain="lineage-map.example",
        is_active=True,
        is_primary=False,
    )
    db_session.add(site)
    db_session.commit()

    source_action_a = str(uuid4())
    source_action_b = str(uuid4())
    draft_repository = SEOActionChainDraftRepository(db_session)

    draft_repository.create_if_missing(
        business_id=seeded_business.id,
        site_id=site.id,
        source_action_id=source_action_a,
        draft=generate_next_actions(
            ActionExecutionItem(
                action_id=source_action_a,
                action_type="publish_content",
                state="completed",
            )
        )[0],
    )
    db_session.commit()

    lineage_service = ActionLineageService(
        seo_action_chain_draft_repository=draft_repository,
        seo_action_execution_item_repository=SEOActionExecutionItemRepository(db_session),
    )
    lineage_map = lineage_service.list_action_lineage_for_source_actions(
        business_id=seeded_business.id,
        site_id=site.id,
        source_action_ids=[source_action_a, source_action_b],
    )

    assert set(lineage_map.keys()) == {source_action_a, source_action_b}
    assert lineage_map[source_action_a].counts.chained_draft_count == 1
    assert lineage_map[source_action_b].counts.chained_draft_count == 0
