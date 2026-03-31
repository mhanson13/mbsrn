"use client";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { PageContainer } from "../../../components/layout/PageContainer";
import { DetailFocusPanel, type DetailFocusFact } from "../../../components/layout/DetailFocusPanel";
import { SectionCard } from "../../../components/layout/SectionCard";
import { SectionHeader } from "../../../components/layout/SectionHeader";
import { SummaryStatCard } from "../../../components/layout/SummaryStatCard";
import { WorkflowContextPanel } from "../../../components/layout/WorkflowContextPanel";
import { useOperatorContext } from "../../../components/useOperatorContext";
import {
  ApiRequestError,
  fetchRecommendation,
  updateRecommendationStatus,
} from "../../../lib/api/client";
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
            throw err;
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

  const workflowContextLinks = useMemo(() => {
    const links: Array<{ href: string; label: string }> = [
      { href: backToRecommendationsHref, label: "Recommendation Queue" },
    ];
    if (recommendation?.recommendation_run_id) {
      links.push({
        href: `/recommendations/runs/${recommendation.recommendation_run_id}?site_id=${encodeURIComponent(recommendation.site_id)}`,
        label: "Parent Recommendation Run",
      });
    }
    if (recommendation?.audit_run_id) {
      links.push({ href: `/audits/${recommendation.audit_run_id}`, label: "Linked Audit Run" });
    }
    if (recommendation?.comparison_run_id) {
      links.push({
        href: buildComparisonRunHref(recommendation.comparison_run_id, recommendation.site_id),
        label: "Linked Comparison Run",
      });
    }
    return links;
  }, [backToRecommendationsHref, recommendation]);

  const workflowNextStep = useMemo(() => {
    if (!recommendation) {
      return null;
    }
    if (recommendation.status === "open" || recommendation.status === "in_progress") {
      return {
        href: `/recommendations/runs/${recommendation.recommendation_run_id}?site_id=${encodeURIComponent(recommendation.site_id)}`,
        label: "Review parent run context",
        note: "Confirm lineage context before accepting or dismissing this recommendation.",
      };
    }
    return {
      href: backToRecommendationsHref,
      label: "Return to recommendation queue",
      note: "Continue processing remaining recommendation actions.",
    };
  }, [backToRecommendationsHref, recommendation]);

  const detailFocusTakeaway = useMemo(() => {
    if (!recommendation) {
      return "Recommendation context is still loading.";
    }
    if (recommendation.status === "open" || recommendation.status === "in_progress") {
      return `This recommendation is still actionable and currently in "${recommendation.status}" state.`;
    }
    if (recommendation.status === "accepted") {
      return "This recommendation has been accepted; confirm downstream visibility on the next analysis refresh.";
    }
    if (recommendation.status === "dismissed") {
      return "This recommendation is dismissed; keep lineage available for auditability and future review.";
    }
    return `This recommendation is in "${recommendation.status}" state.`;
  }, [recommendation]);

  const detailFocusNextStep = useMemo(() => {
    if (!recommendation) {
      return null;
    }
    if (recommendation.status === "open" || recommendation.status === "in_progress") {
      return {
        href: "#recommendation-actions",
        label: "Review rationale, then accept or dismiss",
        note: "Use the action controls below once decision context is clear.",
      };
    }
    return {
      href: backToRecommendationsHref,
      label: "Return to recommendation queue",
      note: "Continue with remaining recommendation actions.",
    };
  }, [backToRecommendationsHref, recommendation]);
  const detailFocusFacts = useMemo<DetailFocusFact[]>(() => {
    if (!recommendation) {
      return [];
    }

    const applied = recommendation.status === "accepted";
    const pending = recommendation.status === "open" || recommendation.status === "in_progress";
    const dismissed = recommendation.status === "dismissed";

    const currentStatusLabel = applied
      ? "Applied / completed"
      : pending
        ? "Needs review / pending"
        : dismissed
          ? "Dismissed"
          : recommendation.status;

    const whatChangedLabel = applied
      ? "Recommendation is marked accepted for this site."
      : dismissed
        ? "Recommendation is marked dismissed in the queue."
        : "No apply change has been recorded yet.";

    const manualFollowUpLabel = applied
      ? "Yes. Confirm this change in the next analysis refresh."
      : pending
        ? "Yes. Review the recommendation and choose accept or dismiss."
        : "Optional. Re-open only if context changes.";

    const expectedVisibilityLabel = applied
      ? "Visible after the next refresh; external channels may take additional time to reflect."
      : pending
        ? "No downstream visibility change until an apply action is recorded."
        : "Dismissal is reflected in the queue immediately.";

    return [
      {
        label: "Current status",
        value: currentStatusLabel,
        tone: applied ? "success" : pending ? "warning" : "neutral",
      },
      {
        label: "What changed",
        value: whatChangedLabel,
        tone: applied ? "success" : "neutral",
      },
      {
        label: "Manual follow-up",
        value: manualFollowUpLabel,
        tone: pending || applied ? "warning" : "neutral",
      },
      {
        label: "Expected visibility",
        value: expectedVisibilityLabel,
        tone: applied ? "warning" : "neutral",
      },
      {
        label: "Source context",
        value: `${recommendationSourceType(recommendation)} lineage`,
        tone: "neutral",
      },
    ];
  }, [recommendation]);

  if (context.loading) {
    return (
      <PageContainer>
        <SectionCard as="div" variant="support" className="role-surface-support">
          <SectionHeader
            title="Recommendation Detail"
            subtitle="Loading recommendation detail for the selected business context."
            headingLevel={1}
            variant="support"
          />
        </SectionCard>
      </PageContainer>
    );
  }
  if (context.error) {
    return (
      <PageContainer>
        <SectionCard as="div" variant="support" className="role-surface-support">
          <SectionHeader
            title="Recommendation Detail"
            subtitle="Unable to load tenant context. Refresh and sign in again."
            headingLevel={1}
            variant="support"
          />
        </SectionCard>
      </PageContainer>
    );
  }
  if (!recommendationId) {
    return (
      <PageContainer>
        <SectionCard variant="support" className="role-surface-support">
          <SectionHeader
            title="Recommendation Detail"
            subtitle="Recommendation identifier is missing."
            headingLevel={1}
            variant="support"
          />
          <p><Link href={backToRecommendationsHref}>Back to Recommendations</Link></p>
        </SectionCard>
      </PageContainer>
    );
  }

  return (
    <PageContainer>
      <div className="role-dashboard-landing">
        <SectionCard variant="primary" className="role-dashboard-hero">
          <SectionHeader
            title="Recommendation Detail"
            subtitle="Review recommendation context, update decision status, and track linked lineage."
            headingLevel={1}
            variant="hero"
            meta={(
              <span className="hint muted">Recommendation: <code>{recommendationId}</code></span>
            )}
            actions={<Link href={backToRecommendationsHref}>Back to Recommendations</Link>}
          />
          <div className="workspace-summary-strip role-summary-strip">
            <SummaryStatCard
              label="Status"
              value={recommendation?.status || "Loading"}
              detail="Current workflow decision state"
              tone={recommendation?.status === "accepted" ? "success" : recommendation?.status === "dismissed" ? "danger" : "warning"}
              variant="elevated"
            />
            <SummaryStatCard
              label="Priority"
              value={recommendation ? `${recommendation.priority_score}` : "-"}
              detail={recommendation ? recommendation.priority_band : "Priority band pending"}
              tone="neutral"
              variant="elevated"
            />
            <SummaryStatCard
              label="Category"
              value={recommendation?.category || "-"}
              detail={recommendation ? recommendationSourceType(recommendation) : "Recommendation lineage pending"}
              tone="neutral"
              variant="elevated"
            />
          </div>
          {resolvedSiteId ? (
            <p className="hint muted">Resolved site: <code>{resolvedSiteId}</code></p>
          ) : null}
          {loading ? <p className="hint muted">Loading recommendation detail...</p> : null}
          {!loading && notFound ? (
            <p className="hint warning">Recommendation not found or not accessible in your tenant scope.</p>
          ) : null}
          {!loading && error ? <p className="hint error">{error}</p> : null}
        </SectionCard>
      </div>

      {!loading && !notFound && !error && recommendation ? (
        <WorkflowContextPanel
          data-testid="recommendation-detail-workflow-context"
          lineage="Recommendations → Recommendation detail → Decision update"
          links={workflowContextLinks}
          nextStep={workflowNextStep}
        />
      ) : null}

      {!loading && !notFound && !error && recommendation ? (
        <DetailFocusPanel
          data-testid="recommendation-detail-focus"
          title="Recommendation outcome snapshot"
          takeaway={detailFocusTakeaway}
          nextStep={detailFocusNextStep}
          facts={detailFocusFacts}
          detailHint="Recommendation context, decision controls, lineage, and tenant scope are grouped in the sections below."
        />
      ) : null}

      {!loading && !notFound && !error && recommendation ? (
        <>
          <SectionCard variant="summary" className="role-surface-support">
            <h2>Recommendation Context</h2>
            <p>{recommendation.title}</p>
            <p>{recommendation.rationale}</p>
          </SectionCard>

          <SectionCard variant="summary" className="role-surface-support">
            <h2>Priority and Status</h2>
            <p>
              Priority: {recommendation.priority_score} ({recommendation.priority_band})
            </p>
            <p>Status: {recommendation.status}</p>
            <p>Category: {recommendation.category}</p>
            <p>Source Type: {recommendationSourceType(recommendation)}</p>
          </SectionCard>

          <SectionCard variant="emphasis" className="role-surface-support" id="recommendation-actions">
            <h2>Actions</h2>
            <div className="row-wrap-tight">
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
            </div>
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
            <div className="row-space-between">
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
            </div>
            {actionSuccess ? <p className="hint">{actionSuccess}</p> : null}
            {actionError ? <p className="hint error">{actionError}</p> : null}
          </SectionCard>

          <SectionCard variant="support" className="role-surface-support">
            <h2>Saved Note</h2>
            <p>{recommendation.decision_reason || "No operator note saved yet."}</p>
          </SectionCard>

          <SectionCard variant="support" className="role-surface-support">
            <h2>Lineage</h2>
            <p>
              Audit Run ID:{" "}
              {recommendation.audit_run_id ? (
                <Link href={`/audits/${recommendation.audit_run_id}`}>
                  <code>{recommendation.audit_run_id}</code>
                </Link>
              ) : (
                <code>-</code>
              )}
            </p>
            <p>
              Comparison Run ID:{" "}
              {recommendation.comparison_run_id ? (
                <Link href={buildComparisonRunHref(recommendation.comparison_run_id, recommendation.site_id)}>
                  <code>{recommendation.comparison_run_id}</code>
                </Link>
              ) : (
                <code>-</code>
              )}
            </p>
            <p>
              Recommendation Run ID:{" "}
              <Link href={`/recommendations/runs/${recommendation.recommendation_run_id}?site_id=${encodeURIComponent(recommendation.site_id)}`}>
                <code>{recommendation.recommendation_run_id}</code>
              </Link>
            </p>
          </SectionCard>

          <SectionCard variant="support" className="role-surface-support">
            <h2>Tenant Scope</h2>
            <p>
              Business ID: <code>{recommendation.business_id}</code>
            </p>
            <p>
              Site ID: <code>{recommendation.site_id}</code>
            </p>
            <p>Created: {formatDateTime(recommendation.created_at)}</p>
            <p>Updated: {formatDateTime(recommendation.updated_at)}</p>
          </SectionCard>
        </>
      ) : null}
    </PageContainer>
  );
}
