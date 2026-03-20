"use client";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { useOperatorContext } from "../../../../components/useOperatorContext";
import {
  ApiRequestError,
  fetchCompetitorComparisonReport,
  fetchLatestRecommendationRunNarrative,
  fetchRecommendationRunReport,
} from "../../../../lib/api/client";
import type {
  CompetitorComparisonReport,
  Recommendation,
  RecommendationNarrative,
  RecommendationRun,
  RecommendationRunReport,
} from "../../../../lib/api/types";

const RECOMMENDATION_PREVIEW_LIMIT = 150;
const RECOMMENDATION_RATIONALE_PREVIEW_LIMIT = 160;

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

function safeRecommendationRunDetailErrorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) {
    if (error.status === 401) {
      return "Session expired. Sign in again.";
    }
    if (error.status === 403) {
      return "You are not authorized to view this recommendation run.";
    }
    if (error.status === 404) {
      return "Recommendation run was not found in your tenant scope.";
    }
  }
  return "Unable to load recommendation run details right now. Please try again.";
}

function safeRecommendationRunRelatedErrorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) {
    if (error.status === 401) {
      return "Session expired. Sign in again.";
    }
    if (error.status === 403) {
      return "You are not authorized to view one or more related resources.";
    }
    if (error.status === 404) {
      return "Some related resources were not found in your tenant scope.";
    }
  }
  return "Some related recommendation-run context could not be loaded. The available data is still shown.";
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

function toSortedCountEntries(countMap: Record<string, number> | undefined): Array<[string, number]> {
  if (!countMap) {
    return [];
  }
  return Object.entries(countMap).sort((left, right) => left[0].localeCompare(right[0]));
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

export default function RecommendationRunDetailPage() {
  const params = useParams<{ run_id: string }>();
  const searchParams = useSearchParams();
  const recommendationRunId = (params?.run_id || "").trim();
  const requestedSiteId = (searchParams.get("site_id") || "").trim();
  const context = useOperatorContext();

  const queueContextParams = useMemo(
    () => parseQueueContextSearchParams(searchParams),
    [searchParams],
  );

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
  const [latestNarrative, setLatestNarrative] = useState<RecommendationNarrative | null>(null);
  const [comparisonReport, setComparisonReport] = useState<CompetitorComparisonReport | null>(null);
  const [resolvedSiteId, setResolvedSiteId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [relatedError, setRelatedError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);

  const run: RecommendationRun | null = report?.recommendation_run || null;

  const selectedSiteDisplayName = useMemo(() => {
    if (!run) {
      return null;
    }
    const match = context.sites.find((site) => site.id === run.site_id);
    return match?.display_name || null;
  }, [context.sites, run]);

  const recommendations = useMemo(() => {
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

  const recommendationsByStatus = useMemo(
    () => toSortedCountEntries(report?.recommendations.by_status),
    [report?.recommendations.by_status],
  );
  const recommendationsByCategory = useMemo(
    () => toSortedCountEntries(report?.rollups.by_category),
    [report?.rollups.by_category],
  );
  const recommendationsBySeverity = useMemo(
    () => toSortedCountEntries(report?.rollups.by_severity),
    [report?.rollups.by_severity],
  );
  const recommendationsByEffort = useMemo(
    () => toSortedCountEntries(report?.rollups.by_effort_bucket),
    [report?.rollups.by_effort_bucket],
  );

  const runStatus = (run?.status || "").trim().toLowerCase();
  const runCompleted = runStatus === "completed";
  const runFailed = runStatus === "failed";

  const comparisonRun = comparisonReport?.run || null;

  const comparisonRunHref = useMemo(() => {
    if (!run?.comparison_run_id) {
      return null;
    }
    const query = new URLSearchParams();
    const siteId = run.site_id;
    if (siteId) {
      query.set("site_id", siteId);
    }
    if (comparisonRun?.competitor_set_id) {
      query.set("set_id", comparisonRun.competitor_set_id);
    }
    const queryText = query.toString();
    return queryText
      ? `/competitors/comparison-runs/${run.comparison_run_id}?${queryText}`
      : `/competitors/comparison-runs/${run.comparison_run_id}`;
  }, [comparisonRun?.competitor_set_id, run?.comparison_run_id, run?.site_id]);

  const competitorSetHref = useMemo(() => {
    if (!comparisonRun) {
      return null;
    }
    const query = new URLSearchParams();
    query.set("site_id", comparisonRun.site_id);
    return `/competitors/${comparisonRun.competitor_set_id}?${query.toString()}`;
  }, [comparisonRun]);

  const snapshotRunHref = useMemo(() => {
    if (!comparisonRun) {
      return null;
    }
    const query = new URLSearchParams();
    query.set("site_id", comparisonRun.site_id);
    query.set("set_id", comparisonRun.competitor_set_id);
    return `/competitors/snapshot-runs/${comparisonRun.snapshot_run_id}?${query.toString()}`;
  }, [comparisonRun]);

  useEffect(() => {
    if (context.loading || context.error || !recommendationRunId) {
      setReport(null);
      setLatestNarrative(null);
      setComparisonReport(null);
      setResolvedSiteId(null);
      setLoading(false);
      setError(null);
      setRelatedError(null);
      setNotFound(false);
      return;
    }

    if (candidateSiteIds.length === 0) {
      setReport(null);
      setLatestNarrative(null);
      setComparisonReport(null);
      setResolvedSiteId(null);
      setLoading(false);
      setError("No site context is available to resolve this recommendation run.");
      setRelatedError(null);
      setNotFound(false);
      return;
    }

    let cancelled = false;

    async function loadDetail() {
      setLoading(true);
      setError(null);
      setRelatedError(null);
      setNotFound(false);
      setReport(null);
      setLatestNarrative(null);
      setComparisonReport(null);
      setResolvedSiteId(null);

      try {
        let resolvedReport: RecommendationRunReport | null = null;
        let resolvedSite: string | null = null;

        for (const siteId of candidateSiteIds) {
          try {
            const result = await fetchRecommendationRunReport(
              context.token,
              context.businessId,
              siteId,
              recommendationRunId,
            );
            resolvedReport = result;
            resolvedSite = siteId;
            break;
          } catch (innerError) {
            if (isNotFoundError(innerError)) {
              continue;
            }
            throw innerError;
          }
        }

        if (!resolvedReport || !resolvedSite) {
          if (!cancelled) {
            setNotFound(true);
          }
          return;
        }

        if (cancelled) {
          return;
        }

        setReport(resolvedReport);
        setResolvedSiteId(resolvedSite);

        const relatedErrors: unknown[] = [];

        const [narrativeResult, comparisonResult] = await Promise.allSettled([
          fetchLatestRecommendationRunNarrative(
            context.token,
            context.businessId,
            resolvedSite,
            recommendationRunId,
          ),
          resolvedReport.recommendation_run.comparison_run_id
            ? fetchCompetitorComparisonReport(
                context.token,
                context.businessId,
                resolvedReport.recommendation_run.comparison_run_id,
              )
            : Promise.resolve(null),
        ]);

        if (cancelled) {
          return;
        }

        if (narrativeResult.status === "fulfilled") {
          setLatestNarrative(narrativeResult.value);
        } else if (!isNotFoundError(narrativeResult.reason)) {
          relatedErrors.push(narrativeResult.reason);
        }

        if (comparisonResult.status === "fulfilled") {
          if (comparisonResult.value) {
            setComparisonReport(comparisonResult.value);
          }
        } else if (!isNotFoundError(comparisonResult.reason)) {
          relatedErrors.push(comparisonResult.reason);
        }

        if (relatedErrors.length > 0) {
          setRelatedError(safeRecommendationRunRelatedErrorMessage(relatedErrors[0]));
        }
      } catch (loadError) {
        if (cancelled) {
          return;
        }
        if (isNotFoundError(loadError)) {
          setNotFound(true);
          return;
        }
        setError(safeRecommendationRunDetailErrorMessage(loadError));
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
    return <section className="panel">Loading recommendation run detail...</section>;
  }
  if (context.error) {
    return <section className="panel">Unable to load tenant context. Refresh and sign in again.</section>;
  }
  if (!recommendationRunId) {
    return (
      <section className="panel stack">
        <h1>Recommendation Run Detail</h1>
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
          <Link href={backToRecommendationsHref}>Back to Recommendations</Link>
        </p>
        <h1>Recommendation Run Detail</h1>
        <p>
          Recommendation Run ID: <code>{recommendationRunId}</code>
        </p>
        {resolvedSiteId ? (
          <p>
            Resolved Site ID: <code>{resolvedSiteId}</code>
          </p>
        ) : null}

        {loading ? <p className="hint muted">Loading recommendation run detail...</p> : null}
        {!loading && notFound ? (
          <p className="hint warning">Recommendation run not found or not accessible in your tenant scope.</p>
        ) : null}
        {!loading && error ? <p className="hint error">{error}</p> : null}
      </div>

      {!loading && !notFound && !error && run ? (
        <>
          {relatedError ? (
            <div className="panel stack">
              <p className="hint warning">{relatedError}</p>
            </div>
          ) : null}

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
            <p>Created By: {run.created_by_principal_id || "-"}</p>
            <p>Created: {formatDateTime(run.created_at)}</p>
            <p>Started: {formatDateTime(run.started_at)}</p>
            <p>Completed: {formatDateTime(run.completed_at)}</p>
            <p>Updated: {formatDateTime(run.updated_at)}</p>
            <p>Duration (ms): {run.duration_ms ?? "-"}</p>
            <p>Error Summary: {run.error_summary || "-"}</p>
          </div>

          <div className="panel stack">
            <h2>Run Outcome</h2>
            {runCompleted ? (
              <p className="hint">
                Recommendation run completed. Report counts and produced recommendations are stable.
              </p>
            ) : runFailed ? (
              <p className="hint warning">
                Recommendation run failed before completion. Partial recommendation data may be present.
              </p>
            ) : (
              <p className="hint warning">
                Recommendation run is still {run.status}. Recommendations and rollups may still change.
              </p>
            )}
            <div style={{ display: "flex", flexWrap: "wrap", gap: "0.75rem" }}>
              <Link href={backToRecommendationsHref}>Recommendation Queue</Link>
              <Link href="/audits">Audit Runs</Link>
              <Link href="/competitors">Competitor Sets</Link>
              {run.audit_run_id ? <Link href={`/audits/${run.audit_run_id}`}>Linked Audit Run</Link> : null}
              {comparisonRunHref ? <Link href={comparisonRunHref}>Linked Comparison Run</Link> : null}
            </div>
          </div>

          <div className="panel stack">
            <h2>Recommendation Metrics</h2>
            <table className="table">
              <tbody>
                <tr>
                  <th>Total Recommendations</th>
                  <td>{run.total_recommendations}</td>
                </tr>
                <tr>
                  <th>Critical Recommendations</th>
                  <td>{run.critical_recommendations}</td>
                </tr>
                <tr>
                  <th>Warning Recommendations</th>
                  <td>{run.warning_recommendations}</td>
                </tr>
                <tr>
                  <th>Info Recommendations</th>
                  <td>{run.info_recommendations}</td>
                </tr>
              </tbody>
            </table>
            <div
              className="stack"
              style={{ gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))", alignItems: "start" }}
            >
              <div className="panel stack" style={{ padding: "0.75rem" }}>
                <h3>By Category</h3>
                {recommendationsByCategory.length === 0 ? (
                  <p className="hint muted">No category rollups are available.</p>
                ) : (
                  <table className="table">
                    <tbody>
                      {recommendationsByCategory.map(([key, value]) => (
                        <tr key={`cat-${key}`}>
                          <th>{key}</th>
                          <td>{value}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
              <div className="panel stack" style={{ padding: "0.75rem" }}>
                <h3>By Severity</h3>
                {recommendationsBySeverity.length === 0 ? (
                  <p className="hint muted">No severity rollups are available.</p>
                ) : (
                  <table className="table">
                    <tbody>
                      {recommendationsBySeverity.map(([key, value]) => (
                        <tr key={`sev-${key}`}>
                          <th>{key}</th>
                          <td>{value}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
              <div className="panel stack" style={{ padding: "0.75rem" }}>
                <h3>By Effort</h3>
                {recommendationsByEffort.length === 0 ? (
                  <p className="hint muted">No effort rollups are available.</p>
                ) : (
                  <table className="table">
                    <tbody>
                      {recommendationsByEffort.map(([key, value]) => (
                        <tr key={`effort-${key}`}>
                          <th>{key}</th>
                          <td>{value}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
              <div className="panel stack" style={{ padding: "0.75rem" }}>
                <h3>By Workflow Status</h3>
                {recommendationsByStatus.length === 0 ? (
                  <p className="hint muted">No status breakdown is available.</p>
                ) : (
                  <table className="table">
                    <tbody>
                      {recommendationsByStatus.map(([key, value]) => (
                        <tr key={`status-${key}`}>
                          <th>{key}</th>
                          <td>{value}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            </div>
          </div>

          <div className="panel stack">
            <h2>Lineage</h2>
            <p>
              Audit Run ID:{" "}
              {run.audit_run_id ? (
                <Link href={`/audits/${run.audit_run_id}`}>
                  <code>{run.audit_run_id}</code>
                </Link>
              ) : (
                <code>-</code>
              )}
            </p>
            <p>
              Comparison Run ID:{" "}
              {run.comparison_run_id && comparisonRunHref ? (
                <Link href={comparisonRunHref}>
                  <code>{run.comparison_run_id}</code>
                </Link>
              ) : run.comparison_run_id ? (
                <code>{run.comparison_run_id}</code>
              ) : (
                <code>-</code>
              )}
            </p>
            {comparisonRun && competitorSetHref ? (
              <p>
                Competitor Set: <Link href={competitorSetHref}><code>{comparisonRun.competitor_set_id}</code></Link>
              </p>
            ) : null}
            {comparisonRun && snapshotRunHref ? (
              <p>
                Snapshot Run: <Link href={snapshotRunHref}><code>{comparisonRun.snapshot_run_id}</code></Link>
              </p>
            ) : null}
          </div>

          <div className="panel stack">
            <h2>Latest Narrative</h2>
            {!latestNarrative ? (
              <p className="hint muted">No generated narrative is currently available for this recommendation run.</p>
            ) : (
              <>
                <p>
                  Narrative ID: <code>{latestNarrative.id}</code>
                </p>
                <p>
                  Version: {latestNarrative.version} ({latestNarrative.status})
                </p>
                <p>
                  Provider: {latestNarrative.provider_name} / {latestNarrative.model_name}
                </p>
                <p>Prompt Version: {latestNarrative.prompt_version}</p>
                <p>Created: {formatDateTime(latestNarrative.created_at)}</p>
                <p>Updated: {formatDateTime(latestNarrative.updated_at)}</p>
                <p>Error: {latestNarrative.error_message || "-"}</p>
                <p>
                  Top Themes:{" "}
                  {latestNarrative.top_themes_json.length > 0
                    ? latestNarrative.top_themes_json.join(", ")
                    : "-"}
                </p>
                <p>
                  Sections Exposed: {latestNarrative.sections_json ? Object.keys(latestNarrative.sections_json).length : 0}
                </p>
                <div className="panel stack" style={{ padding: "0.75rem" }}>
                  <h3>Narrative Text</h3>
                  <p style={{ whiteSpace: "pre-wrap" }}>{latestNarrative.narrative_text || "No narrative text returned."}</p>
                </div>
              </>
            )}
          </div>

          <div className="panel stack">
            <h2>Produced Recommendations ({report?.recommendations.total || 0})</h2>
            {recommendations.length === 0 ? (
              <p className="hint muted">No recommendations were returned for this recommendation run.</p>
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
                      <th>Created</th>
                    </tr>
                  </thead>
                  <tbody>
                    {recommendations.map((item) => (
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
                        <td>{formatDateTime(item.created_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {(report?.recommendations.total || 0) > recommendations.length ? (
                  <p className="hint muted">
                    Showing the top {recommendations.length} recommendations by priority out of {report?.recommendations.total || 0}.
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
