"use client";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

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

  if (context.loading) {
    return <section className="panel">Loading recommendation detail...</section>;
  }
  if (context.error) {
    return <section className="panel">Unable to load tenant context. Refresh and sign in again.</section>;
  }
  if (!recommendationId) {
    return (
      <section className="panel stack">
        <h1>Recommendation Detail</h1>
        <p className="hint warning">Recommendation identifier is missing.</p>
        <p>
          <Link href={backToRecommendationsHref}>Back to Recommendations</Link>
        </p>
      </section>
    );
  }

  return (
    <section className="stack">
      <div className="panel stack">
        <p>
          <Link href={backToRecommendationsHref}>Back to Recommendations</Link>
        </p>
        <h1>Recommendation Detail</h1>
        <p>
          Recommendation ID: <code>{recommendationId}</code>
        </p>
        {resolvedSiteId ? (
          <p>
            Resolved Site ID: <code>{resolvedSiteId}</code>
          </p>
        ) : null}

        {loading ? <p className="hint muted">Loading recommendation detail...</p> : null}
        {!loading && notFound ? (
          <p className="hint warning">Recommendation not found or not accessible in your tenant scope.</p>
        ) : null}
        {!loading && error ? <p className="hint error">{error}</p> : null}
      </div>

      {!loading && !notFound && !error && recommendation ? (
        <>
          <div className="panel stack">
            <h2>Recommendation Context</h2>
            <p>{recommendation.title}</p>
            <p>{recommendation.rationale}</p>
          </div>

          <div className="panel stack">
            <h2>Priority and Status</h2>
            <p>
              Priority: {recommendation.priority_score} ({recommendation.priority_band})
            </p>
            <p>Status: {recommendation.status}</p>
            <p>Category: {recommendation.category}</p>
            <p>Source Type: {recommendationSourceType(recommendation)}</p>
          </div>

          <div className="panel stack">
            <h2>Actions</h2>
            <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
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
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "0.75rem" }}>
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
          </div>

          <div className="panel stack">
            <h2>Saved Note</h2>
            <p>{recommendation.decision_reason || "No operator note saved yet."}</p>
          </div>

          <div className="panel stack">
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
          </div>

          <div className="panel stack">
            <h2>Tenant Scope</h2>
            <p>
              Business ID: <code>{recommendation.business_id}</code>
            </p>
            <p>
              Site ID: <code>{recommendation.site_id}</code>
            </p>
            <p>Created: {formatDateTime(recommendation.created_at)}</p>
            <p>Updated: {formatDateTime(recommendation.updated_at)}</p>
          </div>
        </>
      ) : null}
    </section>
  );
}
