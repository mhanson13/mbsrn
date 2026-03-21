"use client";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { useOperatorContext } from "../../../../../components/useOperatorContext";
import {
  ApiRequestError,
  fetchRecommendationRunNarratives,
  fetchRecommendationRunReport,
} from "../../../../../lib/api/client";
import type {
  Recommendation,
  RecommendationNarrative,
  RecommendationRun,
  RecommendationRunReport,
} from "../../../../../lib/api/types";

const RECOMMENDATION_PREVIEW_LIMIT = 25;
const RECOMMENDATION_RATIONALE_PREVIEW_LIMIT = 140;
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

function truncateText(value: string, limit: number): string {
  const normalized = value.trim();
  if (normalized.length <= limit) {
    return normalized;
  }
  return `${normalized.slice(0, limit - 1)}…`;
}

function isNotFoundError(error: unknown): boolean {
  return error instanceof ApiRequestError && error.status === 404;
}

function safeNarrativeHistoryErrorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) {
    if (error.status === 401) {
      return "Session expired. Sign in again.";
    }
    if (error.status === 403) {
      return "You are not authorized to view recommendation narratives for this run.";
    }
    if (error.status === 404) {
      return "Recommendation run narrative history was not found in your tenant scope.";
    }
  }
  return "Unable to load recommendation narrative history right now. Please try again.";
}

function deriveRecommendationSourceType(item: Recommendation): string {
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

function buildRecommendationDetailHref(item: Recommendation): string {
  const params = new URLSearchParams();
  params.set("site_id", item.site_id);
  return `/recommendations/${item.id}?${params.toString()}`;
}

function parseQueueContextSearchParams(searchParams: URLSearchParams): URLSearchParams {
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
  return nextParams;
}

function buildParentRunHref(
  recommendationRunId: string,
  siteId: string,
  queueContextParams: URLSearchParams,
): string {
  const params = new URLSearchParams(queueContextParams);
  if (siteId) {
    params.set("site_id", siteId);
  }
  const query = params.toString();
  return query
    ? `/recommendations/runs/${recommendationRunId}?${query}`
    : `/recommendations/runs/${recommendationRunId}`;
}

function buildNarrativeDetailHref(
  recommendationRunId: string,
  narrativeId: string,
  siteId: string,
  queueContextParams: URLSearchParams,
): string {
  const params = new URLSearchParams(queueContextParams);
  if (siteId) {
    params.set("site_id", siteId);
  }
  const query = params.toString();
  return query
    ? `/recommendations/runs/${recommendationRunId}/narratives/${narrativeId}?${query}`
    : `/recommendations/runs/${recommendationRunId}/narratives/${narrativeId}`;
}

function buildComparisonRunHref(comparisonRunId: string, siteId: string): string {
  const params = new URLSearchParams();
  if (siteId) {
    params.set("site_id", siteId);
  }
  const query = params.toString();
  return query ? `/competitors/comparison-runs/${comparisonRunId}?${query}` : `/competitors/comparison-runs/${comparisonRunId}`;
}

export default function RecommendationRunNarrativeHistoryPage() {
  const params = useParams<{ run_id: string }>();
  const searchParams = useSearchParams();
  const recommendationRunId = (params?.run_id || "").trim();
  const requestedSiteId = (searchParams.get("site_id") || "").trim();
  const context = useOperatorContext();

  const queueContextParams = useMemo(() => parseQueueContextSearchParams(searchParams), [searchParams]);

  const backToRecommendationsHref = useMemo(() => {
    const query = queueContextParams.toString();
    return query ? `/recommendations?${query}` : "/recommendations";
  }, [queueContextParams]);

  const candidateSiteIds = useMemo(() => {
    const candidates = [
      requestedSiteId,
      context.selectedSiteId || "",
      ...context.sites.map((site) => site.id),
    ].filter((value) => value.trim().length > 0);
    return [...new Set(candidates)];
  }, [context.selectedSiteId, context.sites, requestedSiteId]);

  const [report, setReport] = useState<RecommendationRunReport | null>(null);
  const [narratives, setNarratives] = useState<RecommendationNarrative[]>([]);
  const [resolvedSiteId, setResolvedSiteId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);

  const run: RecommendationRun | null = report?.recommendation_run || null;

  const parentRunHref = useMemo(() => {
    if (!recommendationRunId) {
      return "/recommendations";
    }
    const siteId = run?.site_id || resolvedSiteId || requestedSiteId;
    return buildParentRunHref(recommendationRunId, siteId || "", queueContextParams);
  }, [queueContextParams, recommendationRunId, requestedSiteId, resolvedSiteId, run?.site_id]);

  const sortedNarratives = useMemo(() => {
    return [...narratives].sort((left, right) => {
      if (right.version !== left.version) {
        return right.version - left.version;
      }
      return right.created_at.localeCompare(left.created_at);
    });
  }, [narratives]);

  const latestNarrative = sortedNarratives[0] || null;

  const selectedSiteDisplayName = useMemo(() => {
    if (!run) {
      return null;
    }
    const match = context.sites.find((site) => site.id === run.site_id);
    return match?.display_name || null;
  }, [context.sites, run]);

  const producedRecommendations = useMemo(() => {
    const items = report?.recommendations.items || [];
    return [...items]
      .sort((left, right) => {
        if (right.priority_score !== left.priority_score) {
          return right.priority_score - left.priority_score;
        }
        return right.created_at.localeCompare(left.created_at);
      })
      .slice(0, RECOMMENDATION_PREVIEW_LIMIT);
  }, [report?.recommendations.items]);

  useEffect(() => {
    if (context.loading || context.error || !recommendationRunId) {
      setReport(null);
      setNarratives([]);
      setResolvedSiteId(null);
      setLoading(false);
      setError(null);
      setNotFound(false);
      return;
    }

    if (candidateSiteIds.length === 0) {
      setReport(null);
      setNarratives([]);
      setResolvedSiteId(null);
      setLoading(false);
      setError("No site context is available to resolve this recommendation run.");
      setNotFound(false);
      return;
    }

    let cancelled = false;

    async function loadDetail() {
      setLoading(true);
      setError(null);
      setNotFound(false);
      setReport(null);
      setNarratives([]);
      setResolvedSiteId(null);

      try {
        for (const siteId of candidateSiteIds) {
          let reportResult: RecommendationRunReport;
          try {
            reportResult = await fetchRecommendationRunReport(
              context.token,
              context.businessId,
              siteId,
              recommendationRunId,
            );
          } catch (innerError) {
            if (isNotFoundError(innerError)) {
              continue;
            }
            throw innerError;
          }

          let narrativesResult: RecommendationNarrative[];
          try {
            const response = await fetchRecommendationRunNarratives(
              context.token,
              context.businessId,
              siteId,
              recommendationRunId,
            );
            narrativesResult = response.items;
          } catch (innerError) {
            if (isNotFoundError(innerError)) {
              continue;
            }
            throw innerError;
          }

          if (cancelled) {
            return;
          }

          setReport(reportResult);
          setNarratives(narrativesResult);
          setResolvedSiteId(siteId);
          return;
        }

        if (!cancelled) {
          setNotFound(true);
        }
      } catch (loadError) {
        if (!cancelled) {
          setError(safeNarrativeHistoryErrorMessage(loadError));
        }
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
  }, [
    candidateSiteIds,
    context.businessId,
    context.error,
    context.loading,
    context.token,
    recommendationRunId,
  ]);

  if (context.loading) {
    return <section className="panel">Loading recommendation narrative history...</section>;
  }
  if (context.error) {
    return <section className="panel">Unable to load tenant context. Refresh and sign in again.</section>;
  }
  if (!recommendationRunId) {
    return (
      <section className="panel stack">
        <h1>Recommendation Narrative History</h1>
        <p className="hint warning">Recommendation run identifier is missing.</p>
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
          <Link href={parentRunHref}>Back to Recommendation Run</Link>
        </p>
        <p>
          <Link href={backToRecommendationsHref}>Back to Recommendations</Link>
        </p>
        <h1>Recommendation Narrative History</h1>
        <p>
          Recommendation Run ID: <code>{recommendationRunId}</code>
        </p>
        {resolvedSiteId ? (
          <p>
            Resolved Site ID: <code>{resolvedSiteId}</code>
          </p>
        ) : null}
        {loading ? <p className="hint muted">Loading recommendation narrative history...</p> : null}
        {!loading && notFound ? (
          <p className="hint warning">Recommendation run narrative history not found or not accessible in your tenant scope.</p>
        ) : null}
        {!loading && error ? <p className="hint error">{error}</p> : null}
      </div>

      {!loading && !notFound && !error && run ? (
        <>
          <div className="panel stack">
            <h2>Run Context</h2>
            <p>
              Business ID: <code>{run.business_id}</code>
            </p>
            <p>
              Site ID: <code>{run.site_id}</code>
              {selectedSiteDisplayName ? <> ({selectedSiteDisplayName})</> : null}
            </p>
            <p>Status: {run.status}</p>
            <p>Created: {formatDateTime(run.created_at)}</p>
            <p>Started: {formatDateTime(run.started_at)}</p>
            <p>Completed: {formatDateTime(run.completed_at)}</p>
            <p>Updated: {formatDateTime(run.updated_at)}</p>
            <p>Error Summary: {run.error_summary || "-"}</p>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "0.75rem" }}>
              <Link href={parentRunHref}>Parent Recommendation Run</Link>
              <Link href={backToRecommendationsHref}>Recommendation Queue</Link>
              {run.audit_run_id ? <Link href={`/audits/${run.audit_run_id}`}>Linked Audit Run</Link> : null}
              {run.comparison_run_id ? (
                <Link href={buildComparisonRunHref(run.comparison_run_id, run.site_id)}>Linked Comparison Run</Link>
              ) : null}
            </div>
          </div>

          <div className="panel stack">
            <h2>Narrative Summary</h2>
            <p>Total Narrative Versions: {sortedNarratives.length}</p>
            {!latestNarrative ? (
              <p className="hint muted">No narrative history records are available for this run yet.</p>
            ) : (
              <>
                <p>
                  Latest Version: {latestNarrative.version} ({latestNarrative.status})
                </p>
                <p>
                  Latest Provider/Model: {latestNarrative.provider_name} / {latestNarrative.model_name}
                </p>
                <p>Latest Created: {formatDateTime(latestNarrative.created_at)}</p>
                <p>
                  Latest Themes:{" "}
                  {latestNarrative.top_themes_json.length > 0
                    ? latestNarrative.top_themes_json.slice(0, 5).join(", ")
                    : "-"}
                </p>
                <p>
                  <Link
                    href={buildNarrativeDetailHref(
                      recommendationRunId,
                      latestNarrative.id,
                      run.site_id,
                      queueContextParams,
                    )}
                  >
                    Open Latest Narrative Detail
                  </Link>
                </p>
              </>
            )}
          </div>

          <div className="panel stack">
            <h2>Narrative Versions</h2>
            {sortedNarratives.length === 0 ? (
              <p className="hint muted">
                No recommendation narrative versions have been generated for this run yet.
              </p>
            ) : (
              <table className="table">
                <thead>
                  <tr>
                    <th>Version</th>
                    <th>Status</th>
                    <th>Created</th>
                    <th>Provider / Model</th>
                    <th>Themes</th>
                    <th>Sections</th>
                    <th>Error</th>
                    <th>Open</th>
                  </tr>
                </thead>
                <tbody>
                  {sortedNarratives.map((item) => (
                    <tr key={item.id}>
                      <td>{item.version}</td>
                      <td>{item.status}</td>
                      <td>{formatDateTime(item.created_at)}</td>
                      <td>{item.provider_name} / {item.model_name}</td>
                      <td>{item.top_themes_json.length > 0 ? item.top_themes_json.slice(0, 3).join(", ") : "-"}</td>
                      <td>{item.sections_json ? Object.keys(item.sections_json).length : 0}</td>
                      <td>{item.error_message || "-"}</td>
                      <td>
                        <Link
                          href={buildNarrativeDetailHref(
                            recommendationRunId,
                            item.id,
                            run.site_id,
                            queueContextParams,
                          )}
                        >
                          View
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          <div className="panel stack">
            <h2>Produced Recommendations ({report?.recommendations.total || 0})</h2>
            {producedRecommendations.length === 0 ? (
              <p className="hint muted">No produced recommendations are available for this run.</p>
            ) : (
              <>
                <table className="table">
                  <thead>
                    <tr>
                      <th>Title</th>
                      <th>Priority</th>
                      <th>Status</th>
                      <th>Category</th>
                      <th>Source</th>
                      <th>Rationale</th>
                    </tr>
                  </thead>
                  <tbody>
                    {producedRecommendations.map((item) => (
                      <tr key={item.id}>
                        <td>
                          <Link href={buildRecommendationDetailHref(item)}>{item.title}</Link>
                          <br />
                          <span className="hint muted"><code>{item.id}</code></span>
                        </td>
                        <td>
                          {item.priority_score} ({item.priority_band})
                        </td>
                        <td>{item.status}</td>
                        <td>{item.category}</td>
                        <td>{deriveRecommendationSourceType(item)}</td>
                        <td>{truncateText(item.rationale, RECOMMENDATION_RATIONALE_PREVIEW_LIMIT)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {(report?.recommendations.total || 0) > producedRecommendations.length ? (
                  <p className="hint muted">
                    Showing the top {producedRecommendations.length} recommendations by priority out of{" "}
                    {report?.recommendations.total || 0}.
                  </p>
                ) : null}
              </>
            )}
          </div>
        </>
      ) : null}
    </section>
  );
}
