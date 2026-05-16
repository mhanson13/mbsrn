"use client";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { PageContainer } from "../../../components/layout/PageContainer";
import { OperatorRouteSupportState } from "../../../components/layout/OperatorRouteSupportState";
import { OperatorPageSectionStack } from "../../../components/layout/OperatorPageSurface";
import { SectionStatusItem, SectionStatusStrip } from "../../../components/layout/SectionStatusStrip";
import { SectionCard } from "../../../components/layout/SectionCard";
import { SectionHeader } from "../../../components/layout/SectionHeader";
import { WorkspaceActionBar } from "../../../components/layout/WorkspaceActionBar";
import { WorkspaceMessageStack } from "../../../components/layout/WorkspaceMessageStack";
import { useOperatorContext } from "../../../components/useOperatorContext";
import {
  ApiRequestError,
  fetchRecommendation,
  updateRecommendationStatus,
} from "../../../lib/api/client";
import { normalizeError } from "../../../lib/errors";
import type { Recommendation } from "../../../lib/api/types";

const RECOMMENDATION_PAGE_SIZE_OPTIONS = [25, 50, 100] as const;

function formatDateTime(value: string | null): string {
  if (!value) {
    return "-";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleString();
}

function recommendationSourceType(item: Recommendation): string {
  if (item.audit_run_id && item.comparison_run_id) {
    return "mixed";
  }
  if (item.audit_run_id) {
    return "audit";
  }
  if (item.comparison_run_id) {
    return "comparison";
  }
  return "unknown";
}

function truncateEvidenceText(value: string, maxChars: number): string {
  const normalized = value.replace(/\s+/g, " ").trim();
  if (normalized.length <= maxChars) {
    return normalized;
  }
  return `${normalized.slice(0, Math.max(0, maxChars - 1)).trimEnd()}…`;
}

function deriveRecommendationEvidencePreview(item: Recommendation): string {
  const firstCompetitorEvidence = (item.competitor_evidence_links || [])
    .map((link) => (link.evidence_summary || "").trim())
    .find((value) => value.length > 0);
  const candidates = [
    item.recommendation_evidence_summary || "",
    item.recommendation_observed_gap_summary || "",
    item.recommendation_action_delta?.observed_site_gap || "",
    firstCompetitorEvidence || "",
    (item.recommendation_evidence_trace || [])[0] || "",
    item.rationale || "",
  ]
    .map((value) => value.trim())
    .filter((value) => value.length > 0);
  if (candidates.length === 0) {
    return "No supporting proof captured yet.";
  }
  return truncateEvidenceText(candidates[0], 128);
}

function deriveRecommendationEvidenceTrustCue(item: Recommendation): string {
  const tiers = (item.competitor_evidence_links || []).map((link) => link.trust_tier || link.evidence_trust_tier || null);
  if (tiers.includes("trusted_verified")) {
    return "Support cue: verified linkage evidence";
  }
  if (tiers.includes("informational_unverified") || tiers.includes("informational_candidate")) {
    return "Support cue: informational linkage evidence";
  }
  if ((item.recommendation_evidence_summary || "").trim().length > 0 || (item.recommendation_evidence_trace || []).length > 0) {
    return "Support cue: recommendation-context evidence";
  }
  return "Support cue: operator review required";
}

function safeRecommendationDetailErrorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) {
    if (error.status === 401) {
      return "Session expired. Sign in again.";
    }
    if (error.status === 403) {
      return "You are not authorized to view this recommendation.";
    }
    if (error.status === 404) {
      return "Recommendation was not found in your tenant scope.";
    }
  }
  return "Unable to load recommendation detail right now. Please try again.";
}

function safeRecommendationActionErrorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) {
    if (error.status === 401) {
      return "Session expired. Sign in again.";
    }
    if (error.status === 403) {
      return "You are not authorized to update this recommendation.";
    }
    if (error.status === 404) {
      return "Recommendation not found in your tenant scope.";
    }
    if (error.status === 422) {
      return "Recommendation update is not allowed in the current state.";
    }
  }
  return "Unable to update recommendation right now. Please try again.";
}

function buildComparisonRunHref(comparisonRunId: string, siteId: string): string {
  const params = new URLSearchParams();
  if (siteId) {
    params.set("site_id", siteId);
  }
  const query = params.toString();
  return query ? `/competitors/comparison-runs/${comparisonRunId}?${query}` : `/competitors/comparison-runs/${comparisonRunId}`;
}

export default function RecommendationDetailPage() {
  const params = useParams<{ id: string }>();
  const searchParams = useSearchParams();
  const recommendationId = (params?.id || "").trim();
  const requestedSiteId = (searchParams.get("site_id") || "").trim();
  const context = useOperatorContext();

  const backToRecommendationsHref = useMemo(() => {
    const nextParams = new URLSearchParams();
    const status = (searchParams.get("status") || "").trim().toLowerCase();
    if (["open", "in_progress", "accepted", "dismissed", "snoozed", "resolved"].includes(status)) {
      nextParams.set("status", status);
    }
    const priority = (searchParams.get("priority") || searchParams.get("priority_band") || "").trim().toLowerCase();
    if (["low", "medium", "high", "critical"].includes(priority)) {
      nextParams.set("priority", priority);
    }
    const category = (searchParams.get("category") || "").trim().toUpperCase();
    if (["SEO", "CONTENT", "STRUCTURE", "TECHNICAL"].includes(category)) {
      nextParams.set("category", category);
    }
    const sort = (searchParams.get("sort") || "").trim().toLowerCase();
    if (["priority_asc", "priority_desc", "newest", "oldest"].includes(sort)) {
      if (sort !== "priority_desc") {
        nextParams.set("sort", sort);
      }
    } else {
      const sortBy = (searchParams.get("sort_by") || "").trim().toLowerCase();
      const sortOrder = (searchParams.get("sort_order") || "").trim().toLowerCase();
      if (sortBy === "created_at" && sortOrder === "asc") {
        nextParams.set("sort", "oldest");
      } else if (sortBy === "created_at" && sortOrder === "desc") {
        nextParams.set("sort", "newest");
      } else if (sortBy === "priority_score" && sortOrder === "asc") {
        nextParams.set("sort", "priority_asc");
      }
    }
    const page = Number.parseInt((searchParams.get("page") || "").trim(), 10);
    if (Number.isFinite(page) && page > 1) {
      nextParams.set("page", String(page));
    }
    const pageSize = Number.parseInt((searchParams.get("page_size") || "").trim(), 10);
    if (
      Number.isFinite(pageSize) &&
      RECOMMENDATION_PAGE_SIZE_OPTIONS.includes(pageSize as (typeof RECOMMENDATION_PAGE_SIZE_OPTIONS)[number])
    ) {
      nextParams.set("page_size", String(pageSize));
    }
    const query = nextParams.toString();
    return query ? `/recommendations?${query}` : "/recommendations";
  }, [searchParams]);

  const candidateSiteIds = useMemo(() => {
    const candidates = [
      requestedSiteId,
      context.selectedSiteId || "",
      ...context.sites.map((site) => site.id),
    ].filter((value) => value.trim().length > 0);
    return [...new Set(candidates)];
  }, [context.selectedSiteId, context.sites, requestedSiteId]);

  const [recommendation, setRecommendation] = useState<Recommendation | null>(null);
  const [resolvedSiteId, setResolvedSiteId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [actionLoading, setActionLoading] = useState(false);
  const [actionTarget, setActionTarget] = useState<"accepted" | "dismissed" | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionSuccess, setActionSuccess] = useState<string | null>(null);
  const [noteDraft, setNoteDraft] = useState("");

  useEffect(() => {
    if (context.loading || context.error || !recommendationId) {
      setRecommendation(null);
      setResolvedSiteId(null);
      setLoading(false);
      setError(null);
      setNotFound(false);
      setActionLoading(false);
      setActionTarget(null);
      setActionError(null);
      setActionSuccess(null);
      setNoteDraft("");
      return;
    }

    if (candidateSiteIds.length === 0) {
      setRecommendation(null);
      setResolvedSiteId(null);
      setLoading(false);
      setError("No site context is available to resolve this recommendation.");
      setNotFound(false);
      setActionLoading(false);
      setActionTarget(null);
      setActionError(null);
      setActionSuccess(null);
      setNoteDraft("");
      return;
    }

    let cancelled = false;

    async function loadDetail() {
      setLoading(true);
      setError(null);
      setNotFound(false);
      setRecommendation(null);
      setResolvedSiteId(null);
      setActionLoading(false);
      setActionTarget(null);
      setActionError(null);
      setActionSuccess(null);
      setNoteDraft("");

      try {
        for (const siteId of candidateSiteIds) {
          try {
            const result = await fetchRecommendation(
              context.token,
              context.businessId,
              siteId,
              recommendationId,
            );
            if (cancelled) {
              return;
            }
            setRecommendation(result);
            setResolvedSiteId(siteId);
            setNoteDraft(result.decision_reason || "");
            return;
          } catch (err) {
            if (err instanceof ApiRequestError && err.status === 404) {
              continue;
            }
            throw normalizeError(err, "Failed to load recommendation details.");
          }
        }

        if (!cancelled) {
          setNotFound(true);
        }
      } catch (err) {
        if (cancelled) {
          return;
        }
        if (err instanceof ApiRequestError && err.status === 404) {
          setNotFound(true);
          return;
        }
        setError(safeRecommendationDetailErrorMessage(err));
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void loadDetail();
    return () => {
      cancelled = true;
    };
  }, [candidateSiteIds, context.businessId, context.error, context.loading, context.token, recommendationId]);

  async function handleUpdateStatus(status: "accepted" | "dismissed") {
    if (!recommendation || actionLoading) {
      return;
    }
    const previousRecommendation = recommendation;
    const optimisticNote = noteDraft.trim() || null;
    setActionLoading(true);
    setActionTarget(status);
    setActionError(null);
    setActionSuccess(null);
    setRecommendation({
      ...recommendation,
      status,
      decision_reason: optimisticNote,
    });
    try {
      const updated = await updateRecommendationStatus(
        context.token,
        context.businessId,
        previousRecommendation.site_id,
        previousRecommendation.id,
        {
          status,
          note: optimisticNote,
        },
      );
      setRecommendation(updated);
      setResolvedSiteId(updated.site_id);
      setActionSuccess(`Recommendation marked as ${updated.status}.`);
      setNoteDraft(updated.decision_reason || "");
    } catch (err) {
      setRecommendation(previousRecommendation);
      setActionError(safeRecommendationActionErrorMessage(err));
    } finally {
      setActionLoading(false);
      setActionTarget(null);
    }
  }

  async function handleSaveNote() {
    if (!recommendation || actionLoading) {
      return;
    }
    const normalizedNote = noteDraft.trim() || null;
    if ((recommendation.decision_reason || null) === normalizedNote) {
      setActionSuccess("Note is already up to date.");
      setActionError(null);
      return;
    }

    setActionLoading(true);
    setActionTarget(null);
    setActionError(null);
    setActionSuccess(null);
    try {
      const updated = await updateRecommendationStatus(
        context.token,
        context.businessId,
        recommendation.site_id,
        recommendation.id,
        {
          note: normalizedNote,
        },
      );
      setRecommendation(updated);
      setResolvedSiteId(updated.site_id);
      setNoteDraft(updated.decision_reason || "");
      setActionSuccess("Recommendation note saved.");
    } catch (err) {
      setActionError(safeRecommendationActionErrorMessage(err));
    } finally {
      setActionLoading(false);
    }
  }

  const recommendationRunHref = useMemo(() => {
    if (!recommendation?.recommendation_run_id) {
      return null;
    }
    return `/recommendations/runs/${recommendation.recommendation_run_id}?site_id=${encodeURIComponent(recommendation.site_id)}`;
  }, [recommendation]);

  const decisionSummaryFacts = useMemo(() => {
    if (!recommendation) {
      return [];
    }
    const pending = recommendation.status === "open" || recommendation.status === "in_progress";
    const blockedBy = recommendation.blocking_reason
      || (recommendation.status === "accepted"
        ? "Already accepted; monitor after refresh."
        : recommendation.status === "dismissed" || recommendation.status === "resolved" || recommendation.status === "snoozed"
          ? "Decision closed unless context changes."
          : "No blocker detected.");
    const measurementAvailability = recommendation.recommendation_measurement_context
      ? (() => {
        const status = (recommendation.recommendation_measurement_context.measurement_status || "").trim().toLowerCase();
        if (status === "available") {
          return "Measurement context available.";
        }
        if (status === "not_configured") {
          return "Measurement not configured.";
        }
        if (status === "unavailable") {
          return "Measurement temporarily unavailable.";
        }
        if (status === "no_match") {
          return "No page-level measurement match.";
        }
        return "Measurement availability unknown.";
      })()
      : "Measurement context not provided.";

    const firstStep = (() => {
      const planStep = recommendation.action_plan?.action_steps?.[0];
      if (planStep && typeof planStep.instruction === "string" && planStep.instruction.trim().length > 0) {
        return planStep.instruction.trim();
      }
      const nextAction = (recommendation.next_action || "").trim();
      if (nextAction.length > 0) {
        return nextAction;
      }
      return "Open this recommendation and review evidence before making a decision.";
    })();
    const successSignal = (() => {
      const expected = (recommendation.recommendation_expected_outcome || "").trim();
      if (expected.length > 0) {
        return expected;
      }
      const ga4Hint = (recommendation.ga4_outcome_snapshot?.operator_hint || "").trim();
      if (ga4Hint.length > 0) {
        return ga4Hint;
      }
      return "Use the next audit and directional GA4/GBP trends to verify movement. Do not infer causality from one signal.";
    })();
    const evidenceUsed = (() => {
      const sources = Array.isArray(recommendation.source_basis) ? recommendation.source_basis : [];
      const sourceLabels = sources.map((source) => {
        if (source === "audit_findings") {
          return "audit findings";
        }
        if (source === "comparison_findings") {
          return "comparison findings";
        }
        if (source === "accepted_competitors") {
          return "accepted/useful competitors";
        }
        if (source === "ga4_insights") {
          return "GA4 signals";
        }
        if (source === "search_console_insights") {
          return "search signals";
        }
        if (source === "gbp_insights") {
          return "GBP signals";
        }
        return source;
      });
      if (sourceLabels.length > 0) {
        return `Source basis: ${sourceLabels.join(", ")}.`;
      }
      return "Source basis is not explicitly captured for this recommendation.";
    })();

    return [
      {
        label: "What to do",
        value: recommendation.next_action || (pending ? "Review and decide: accept or dismiss." : "Return to queue and continue."),
      },
      { label: "Why it matters", value: recommendation.why_now || recommendation.priority_rationale || recommendation.rationale },
      { label: "First step", value: firstStep },
      { label: "Success signal", value: successSignal },
      { label: "Blocked by", value: blockedBy },
      { label: "Evidence used", value: `${evidenceUsed} ${measurementAvailability}`.trim() },
    ];
  }, [recommendation]);

  if (context.loading) {
    return (
      <OperatorRouteSupportState
        title="Recommendation Detail"
        subtitle="Loading recommendation detail for the selected business context."
      />
    );
  }
  if (context.error) {
    return (
      <OperatorRouteSupportState
        title="Recommendation Detail"
        subtitle="Unable to load tenant context. Refresh and sign in again."
      />
    );
  }
  if (!recommendationId) {
    return (
      <OperatorRouteSupportState
        title="Recommendation Detail"
        subtitle="Recommendation identifier is missing."
        backHref={backToRecommendationsHref}
        backLabel="Back to Recommendations"
      />
    );
  }

  return (
    <PageContainer>
      <WorkspaceMessageStack data-testid="recommendation-detail-message-stack">
        {resolvedSiteId ? (
          <p className="hint muted">Resolved site: <code>{resolvedSiteId}</code></p>
        ) : null}
        {loading ? <p className="hint muted">Loading recommendation detail...</p> : null}
        {!loading && notFound ? (
          <p className="hint warning">Recommendation not found or not accessible in your tenant scope.</p>
        ) : null}
        {!loading && error ? <p className="hint error">{error}</p> : null}
      </WorkspaceMessageStack>

      {!loading && !notFound && !error && recommendation ? (
        <OperatorPageSectionStack>
          <SectionCard variant="summary" className="role-surface-support" data-testid="recommendation-detail-header">
            <SectionHeader
              title="Recommendation Detail"
              subtitle={recommendation.title}
              headingLevel={1}
              variant="support"
            />
            <WorkspaceActionBar
              variant="secondary"
              className="row-wrap-tight"
              data-testid="recommendation-detail-header-actions"
            >
              <Link href={backToRecommendationsHref} className="button button-secondary">
                Back to Recommendations
              </Link>
              {recommendationRunHref ? (
                <Link href={recommendationRunHref} className="button button-tertiary">
                  Parent Recommendation Run
                </Link>
              ) : null}
              {recommendation.audit_run_id ? (
                <Link href={`/audits/${recommendation.audit_run_id}`} className="button button-tertiary">
                  Linked Audit Run
                </Link>
              ) : null}
            </WorkspaceActionBar>
            <SectionStatusStrip compact={true} data-testid="recommendation-detail-status-strip">
              <SectionStatusItem
                label="Status"
                value={recommendation.status}
                tone={
                  recommendation.status === "accepted"
                    ? "success"
                    : recommendation.status === "dismissed"
                      ? "danger"
                      : "warning"
                }
              />
              <SectionStatusItem
                label="Priority"
                value={recommendation.priority_score}
                detail={recommendation.priority_band}
                tone="neutral"
              />
              <SectionStatusItem
                label="Category"
                value={recommendation.category}
                tone="neutral"
              />
              <SectionStatusItem
                label="Source"
                value={recommendationSourceType(recommendation)}
                tone="neutral"
              />
            </SectionStatusStrip>
            {(recommendation.duplicate_count ?? 0) > 1 ? (
              <p className="hint muted" data-testid="recommendation-detail-duplicate-notice">
                Similar findings exist from previous runs. This recommendation is the current representative
                (latest of {recommendation.duplicate_count} repeated findings).
              </p>
            ) : null}
          </SectionCard>

          <SectionCard variant="summary" className="role-surface-support" data-testid="recommendation-detail-decision-summary">
            <SectionHeader
              title="Decision Summary"
              subtitle="Operator-first context for what this recommendation is and what to do next."
              headingLevel={2}
              compact
              variant="support"
            />
            <dl className="detail-focus-facts">
              {decisionSummaryFacts.map((fact) => (
                <div key={fact.label} className="detail-focus-fact detail-focus-fact-neutral">
                  <dt>{fact.label}</dt>
                  <dd>{fact.value}</dd>
                </div>
              ))}
            </dl>
          </SectionCard>

          <SectionCard
            variant="emphasis"
            className="role-surface-support"
            id="recommendation-actions"
            data-testid="recommendation-detail-actions"
          >
            <SectionHeader
              title="Actions"
              subtitle="Capture the operator decision and save a note."
              headingLevel={2}
              compact
              variant="support"
            />
            <WorkspaceActionBar variant="primary" className="row-wrap-tight">
              <button
                className="primary"
                type="button"
                disabled={actionLoading || recommendation.status === "accepted"}
                onClick={() => {
                  void handleUpdateStatus("accepted");
                }}
              >
                {actionLoading && actionTarget === "accepted" ? "Saving..." : "Accept"}
              </button>
              <button
                type="button"
                disabled={actionLoading || recommendation.status === "dismissed"}
                onClick={() => {
                  void handleUpdateStatus("dismissed");
                }}
              >
                {actionLoading && actionTarget === "dismissed" ? "Saving..." : "Dismiss"}
              </button>
            </WorkspaceActionBar>
            <label htmlFor="recommendation-note">Operator Note</label>
            <textarea
              id="recommendation-note"
              value={noteDraft}
              onChange={(event) => setNoteDraft(event.target.value)}
              rows={4}
              placeholder="Add an operator note for this recommendation..."
              maxLength={2000}
              disabled={actionLoading}
            />
            <WorkspaceActionBar variant="secondary" className="row-space-between">
              <small className="hint muted">{noteDraft.length}/2000 characters</small>
              <button
                type="button"
                disabled={actionLoading}
                onClick={() => {
                  void handleSaveNote();
                }}
              >
                {actionLoading && actionTarget === null ? "Saving..." : "Save Note"}
              </button>
            </WorkspaceActionBar>
            {actionSuccess ? <p className="hint">{actionSuccess}</p> : null}
            {actionError ? <p className="hint error">{actionError}</p> : null}
            <p className="hint muted" data-testid="recommendation-detail-saved-note">
              Saved note: {recommendation.decision_reason || "No operator note saved yet."}
            </p>
          </SectionCard>

          <SectionCard variant="support" className="role-surface-support" data-testid="recommendation-detail-supporting-details">
            <SectionHeader
              title="Supporting Details"
              subtitle="Directional signals used for this recommendation."
              headingLevel={2}
              compact
              variant="support"
            />
            <p className="hint muted">
              <span className="text-strong">Audit signal:</span>{" "}
              {recommendation.audit_run_id ? "Audit finding context available." : "No audit-linked context attached."}
            </p>
            {recommendation.competitor_context_summary ? (
              <p className="hint muted" data-testid="recommendation-detail-competitor-signal">
                <span className="text-strong">Competitor signal:</span> {recommendation.competitor_context_summary}
              </p>
            ) : null}
            {recommendation.ga4_priority_hint ? (
              <p className="hint muted" data-testid="recommendation-detail-ga4-signal">
                <span className="text-strong">GA4 signal:</span> {recommendation.ga4_priority_hint}
              </p>
            ) : null}
            {recommendation.gbp_context_summary ? (
              <p className="hint muted" data-testid="recommendation-detail-gbp-signal">
                <span className="text-strong">GBP signal:</span> {recommendation.gbp_context_summary}
              </p>
            ) : null}
            <details className="stack-tight" data-testid="recommendation-detail-supporting-disclosure">
              <summary className="hint muted">View evidence/details</summary>
              <p className="hint muted">
                <span className="text-strong">Summary:</span> {recommendation.rationale}
              </p>
              {recommendation.priority_rationale ? (
                <p className="hint muted">
                  <span className="text-strong">Why now:</span> {recommendation.priority_rationale}
                </p>
              ) : null}
              <p className="hint muted">
                <span className="text-strong">Evidence preview:</span> {deriveRecommendationEvidencePreview(recommendation)}
              </p>
              <p className="hint muted">
                <span className="text-strong">Evidence confidence:</span> {deriveRecommendationEvidenceTrustCue(recommendation)}
              </p>
              {recommendation.next_action ? (
                <p className="hint muted">
                  <span className="text-strong">Implementation context:</span> {recommendation.next_action}
                </p>
              ) : null}
              {recommendation.ga4_priority_hint ? (
                <p className="hint muted">
                  <span className="text-strong">GA4 context:</span> {recommendation.ga4_priority_hint}
                </p>
              ) : null}
              {recommendation.ga4_outcome_snapshot?.operator_hint ? (
                <p className="hint muted">
                  <span className="text-strong">Observed result:</span> {recommendation.ga4_outcome_snapshot.operator_hint}
                </p>
              ) : null}
            </details>
          </SectionCard>

          <SectionCard variant="support" className="role-surface-support" data-testid="recommendation-detail-lineage-scope">
            <SectionHeader
              title="Advanced Diagnostics"
              subtitle="Run lineage and tenant scope metadata."
              headingLevel={2}
              compact
              variant="support"
            />
            <details className="stack-tight" data-testid="recommendation-detail-lineage-disclosure">
              <summary className="hint muted">View run lineage and tenant scope</summary>
              <p>
                Audit Run:{" "}
                {recommendation.audit_run_id ? (
                  <Link href={`/audits/${recommendation.audit_run_id}`}>
                    <code>{recommendation.audit_run_id}</code>
                  </Link>
                ) : (
                  <code>-</code>
                )}
              </p>
              <p>
                Comparison Run:{" "}
                {recommendation.comparison_run_id ? (
                  <Link href={buildComparisonRunHref(recommendation.comparison_run_id, recommendation.site_id)}>
                    <code>{recommendation.comparison_run_id}</code>
                  </Link>
                ) : (
                  <code>-</code>
                )}
              </p>
              <p>
                Recommendation Run:{" "}
                {recommendationRunHref ? (
                  <Link href={recommendationRunHref}>
                    <code>{recommendation.recommendation_run_id}</code>
                  </Link>
                ) : (
                  <code>-</code>
                )}
              </p>
              <p>Business ID: <code>{recommendation.business_id}</code></p>
              <p>Site ID: <code>{recommendation.site_id}</code></p>
              <p>Created: {formatDateTime(recommendation.created_at)}</p>
              <p>Updated: {formatDateTime(recommendation.updated_at)}</p>
            </details>
          </SectionCard>
        </OperatorPageSectionStack>
      ) : null}
    </PageContainer>
  );
}
