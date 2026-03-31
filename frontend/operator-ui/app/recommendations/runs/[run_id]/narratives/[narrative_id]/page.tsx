"use client";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { PageContainer } from "../../../../../../components/layout/PageContainer";
import { DetailFocusPanel } from "../../../../../../components/layout/DetailFocusPanel";
import { SectionCard } from "../../../../../../components/layout/SectionCard";
import { SectionHeader } from "../../../../../../components/layout/SectionHeader";
import { SummaryStatCard } from "../../../../../../components/layout/SummaryStatCard";
import { WorkflowContextPanel } from "../../../../../../components/layout/WorkflowContextPanel";
import { useOperatorContext } from "../../../../../../components/useOperatorContext";
import {
  ApiRequestError,
  fetchRecommendationNarrative,
  fetchRecommendationRunReport,
} from "../../../../../../lib/api/client";
import type {
  Recommendation,
  RecommendationNarrative,
  RecommendationRun,
  RecommendationRunReport,
} from "../../../../../../lib/api/types";

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

function formatStructuredValue(value: unknown): string {
  if (typeof value === "string") {
    return value;
  }
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function isNotFoundError(error: unknown): boolean {
  return error instanceof ApiRequestError && error.status === 404;
}

function safeNarrativeDetailErrorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) {
    if (error.status === 401) {
      return "Session expired. Sign in again.";
    }
    if (error.status === 403) {
      return "You are not authorized to view this recommendation narrative.";
    }
    if (error.status === 404) {
      return "Recommendation narrative was not found in your tenant scope.";
    }
  }
  return "Unable to load recommendation narrative detail right now. Please try again.";
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

function buildNarrativeHistoryHref(
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
    ? `/recommendations/runs/${recommendationRunId}/narratives?${query}`
    : `/recommendations/runs/${recommendationRunId}/narratives`;
}

function buildComparisonRunHref(comparisonRunId: string, siteId: string): string {
  const params = new URLSearchParams();
  if (siteId) {
    params.set("site_id", siteId);
  }
  const query = params.toString();
  return query ? `/competitors/comparison-runs/${comparisonRunId}?${query}` : `/competitors/comparison-runs/${comparisonRunId}`;
}

export default function RecommendationNarrativeDetailPage() {
  const params = useParams<{ run_id: string; narrative_id: string }>();
  const searchParams = useSearchParams();
  const recommendationRunId = (params?.run_id || "").trim();
  const narrativeId = (params?.narrative_id || "").trim();
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
  const [narrative, setNarrative] = useState<RecommendationNarrative | null>(null);
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

  const narrativeHistoryHref = useMemo(() => {
    if (!recommendationRunId) {
      return "/recommendations";
    }
    const siteId = run?.site_id || resolvedSiteId || requestedSiteId;
    return buildNarrativeHistoryHref(recommendationRunId, siteId || "", queueContextParams);
  }, [queueContextParams, recommendationRunId, requestedSiteId, resolvedSiteId, run?.site_id]);

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

  const narrativeSections = useMemo(() => {
    if (!narrative?.sections_json) {
      return [] as Array<[string, unknown]>;
    }
    return Object.entries(narrative.sections_json);
  }, [narrative?.sections_json]);

  const workflowContextLinks = useMemo(() => {
    const links: Array<{ href: string; label: string }> = [
      { href: backToRecommendationsHref, label: "Recommendation Queue" },
      { href: parentRunHref, label: "Parent Recommendation Run" },
      { href: narrativeHistoryHref, label: "Narrative History" },
    ];
    if (run?.audit_run_id) {
      links.push({ href: `/audits/${run.audit_run_id}`, label: "Linked Audit Run" });
    }
    if (run?.comparison_run_id) {
      links.push({
        href: buildComparisonRunHref(run.comparison_run_id, run.site_id),
        label: "Linked Comparison Run",
      });
    }
    return links;
  }, [backToRecommendationsHref, narrativeHistoryHref, parentRunHref, run]);

  const workflowNextStep = useMemo(() => {
    if ((report?.recommendations.total || 0) > 0) {
      return {
        href: parentRunHref,
        label: "Review produced recommendations",
        note: "Use this narrative context to validate recommendation action readiness.",
      };
    }
    return {
      href: narrativeHistoryHref,
      label: "Return to narrative history",
      note: "Compare versions to validate reasoning progression across this run.",
    };
  }, [narrativeHistoryHref, parentRunHref, report?.recommendations.total]);

  const detailFocusTakeaway = useMemo(() => {
    if (!narrative || !run) {
      return "Narrative detail is still loading.";
    }
    const producedCount = report?.recommendations.total || 0;
    if (narrative.status === "completed") {
      return `Narrative version ${narrative.version} is completed with ${producedCount} linked recommendation${producedCount === 1 ? "" : "s"}.`;
    }
    return `Narrative version ${narrative.version} is in "${narrative.status}" state; verify run context before acting.`;
  }, [narrative, report?.recommendations.total, run]);

  const detailFocusNextStep = useMemo(() => {
    if ((report?.recommendations.total || 0) > 0) {
      return {
        href: parentRunHref,
        label: "Review produced recommendations",
        note: "Use this narrative as decision context, not as a standalone output.",
      };
    }
    return {
      href: narrativeHistoryHref,
      label: "Return to narrative history",
      note: "Compare versions and then return to the parent run.",
    };
  }, [narrativeHistoryHref, parentRunHref, report?.recommendations.total]);

  useEffect(() => {
    if (context.loading || context.error || !recommendationRunId || !narrativeId) {
      setReport(null);
      setNarrative(null);
      setResolvedSiteId(null);
      setLoading(false);
      setError(null);
      setNotFound(false);
      return;
    }

    if (candidateSiteIds.length === 0) {
      setReport(null);
      setNarrative(null);
      setResolvedSiteId(null);
      setLoading(false);
      setError("No site context is available to resolve this recommendation narrative.");
      setNotFound(false);
      return;
    }

    let cancelled = false;

    async function loadDetail() {
      setLoading(true);
      setError(null);
      setNotFound(false);
      setReport(null);
      setNarrative(null);
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

          let narrativeResult: RecommendationNarrative;
          try {
            narrativeResult = await fetchRecommendationNarrative(
              context.token,
              context.businessId,
              siteId,
              narrativeId,
            );
          } catch (innerError) {
            if (isNotFoundError(innerError)) {
              continue;
            }
            throw innerError;
          }

          if (narrativeResult.recommendation_run_id !== recommendationRunId) {
            continue;
          }

          if (cancelled) {
            return;
          }

          setReport(reportResult);
          setNarrative(narrativeResult);
          setResolvedSiteId(siteId);
          return;
        }

        if (!cancelled) {
          setNotFound(true);
        }
      } catch (loadError) {
        if (!cancelled) {
          setError(safeNarrativeDetailErrorMessage(loadError));
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
    narrativeId,
    recommendationRunId,
  ]);

  if (context.loading) {
    return (
      <PageContainer>
        <SectionCard as="div" variant="support" className="role-surface-support">
          <SectionHeader
            title="Recommendation Narrative Detail"
            subtitle="Loading recommendation narrative detail for the selected run."
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
            title="Recommendation Narrative Detail"
            subtitle="Unable to load tenant context. Refresh and sign in again."
            headingLevel={1}
            variant="support"
          />
        </SectionCard>
      </PageContainer>
    );
  }
  if (!recommendationRunId || !narrativeId) {
    return (
      <PageContainer>
        <SectionCard variant="support" className="role-surface-support">
          <SectionHeader
            title="Recommendation Narrative Detail"
            subtitle="Recommendation run or narrative identifier is missing."
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
        <SectionCard
          variant="primary"
          className="role-dashboard-hero"
          data-testid="recommendation-narrative-detail-hero"
        >
          <SectionHeader
            title="Recommendation Narrative Detail"
            subtitle="Inspect this narrative version’s context, themes, structured sections, and recommendation linkage."
            headingLevel={1}
            variant="hero"
            meta={(
              <span className="hint muted">
                Narrative: <code>{narrativeId}</code>
              </span>
            )}
            actions={(
              <div className="row-wrap-tight">
                <Link href={narrativeHistoryHref}>Back to Narrative History</Link>
                <Link href={parentRunHref}>Back to Recommendation Run</Link>
                <Link href={backToRecommendationsHref}>Back to Recommendations</Link>
              </div>
            )}
          />
          <div
            className="workspace-summary-strip role-summary-strip"
            data-testid="recommendation-narrative-detail-summary-strip"
          >
            <SummaryStatCard
              label="Narrative status"
              value={narrative?.status || "Loading"}
              detail={narrative ? `Version ${narrative.version}` : "Narrative context pending"}
              tone={narrative?.status === "completed" ? "success" : "warning"}
              variant="elevated"
            />
            <SummaryStatCard
              label="Prompt lineage"
              value={narrative?.prompt_version || "-"}
              detail={narrative ? `${narrative.provider_name} / ${narrative.model_name}` : "Provider/model pending"}
              tone="neutral"
              variant="elevated"
            />
            <SummaryStatCard
              label="Themes"
              value={narrative?.top_themes_json.length ?? 0}
              detail="Themes extracted for this narrative version"
              tone={(narrative?.top_themes_json.length ?? 0) > 0 ? "neutral" : "warning"}
              variant="elevated"
            />
            <SummaryStatCard
              label="Produced recommendations"
              value={report?.recommendations.total ?? 0}
              detail="Run-level recommendation output context"
              tone={(report?.recommendations.total ?? 0) > 0 ? "neutral" : "warning"}
              variant="elevated"
            />
          </div>
          {resolvedSiteId ? (
            <p className="hint muted">
              Recommendation run: <code>{recommendationRunId}</code> • Resolved site: <code>{resolvedSiteId}</code>
            </p>
          ) : null}
          {loading ? <p className="hint muted">Loading recommendation narrative detail...</p> : null}
          {!loading && notFound ? (
            <p className="hint warning">Recommendation narrative not found or not accessible in your tenant scope.</p>
          ) : null}
          {!loading && error ? <p className="hint error">{error}</p> : null}
        </SectionCard>
      </div>

      {!loading && !notFound && !error && run && narrative ? (
        <WorkflowContextPanel
          data-testid="recommendation-narrative-detail-workflow-context"
          lineage="Recommendations → Recommendation Run → Narrative history → Narrative detail"
          links={workflowContextLinks}
          nextStep={workflowNextStep}
        />
      ) : null}

      {!loading && !notFound && !error && run && narrative ? (
        <DetailFocusPanel
          data-testid="recommendation-narrative-detail-focus"
          takeaway={detailFocusTakeaway}
          nextStep={detailFocusNextStep}
          detailHint="Narrative metadata, structured sections, full text, and produced recommendations are organized below."
        />
      ) : null}

      {!loading && !notFound && !error && run && narrative ? (
        <>
          <SectionCard variant="summary" className="role-surface-support">
            <h2>Narrative Metadata</h2>
            <p>Version: {narrative.version}</p>
            <p>Status: {narrative.status}</p>
            <p>
              Provider/Model: {narrative.provider_name} / {narrative.model_name}
            </p>
            <p>Prompt Version: {narrative.prompt_version}</p>
            <p>Created By: {narrative.created_by_principal_id || "-"}</p>
            <p>Created: {formatDateTime(narrative.created_at)}</p>
            <p>Updated: {formatDateTime(narrative.updated_at)}</p>
            <p>Error: {narrative.error_message || "-"}</p>
          </SectionCard>

          <SectionCard variant="summary" className="role-surface-support">
            <h2>Run Lineage Context</h2>
            <p>
              Business ID: <code>{run.business_id}</code>
            </p>
            <p>
              Site ID: <code>{run.site_id}</code>
              {selectedSiteDisplayName ? <> ({selectedSiteDisplayName})</> : null}
            </p>
            <p>Run Status: {run.status}</p>
            <p>Created: {formatDateTime(run.created_at)}</p>
            <p>Started: {formatDateTime(run.started_at)}</p>
            <p>Completed: {formatDateTime(run.completed_at)}</p>
            <p className="hint muted">
              Workflow context links above keep this narrative tied to the parent run and adjacent lineage steps.
            </p>
          </SectionCard>

          <SectionCard variant="support" className="role-surface-support">
            <h2>Themes</h2>
            {narrative.top_themes_json.length === 0 ? (
              <p className="hint muted">No top themes were recorded for this narrative version.</p>
            ) : (
              <ul>
                {narrative.top_themes_json.map((theme) => (
                  <li key={theme}>{theme}</li>
                ))}
              </ul>
            )}
          </SectionCard>

          <SectionCard variant="support" className="role-surface-support">
            <h2>Sections</h2>
            {narrativeSections.length === 0 ? (
              <p className="hint muted">No structured sections were returned for this narrative version.</p>
            ) : (
              <div className="stack">
                {narrativeSections.map(([sectionName, sectionValue]) => (
                  <div key={sectionName} className="panel stack panel-compact">
                    <h3>{sectionName}</h3>
                    <pre className="pre-scroll">
                      {formatStructuredValue(sectionValue)}
                    </pre>
                  </div>
                ))}
              </div>
            )}
          </SectionCard>

          <SectionCard variant="support" className="role-surface-support">
            <h2>Narrative Text</h2>
            <p className="pre-wrap">{narrative.narrative_text || "No narrative text returned."}</p>
          </SectionCard>

          <SectionCard variant="support" className="role-surface-support">
            <h2>Produced Recommendations ({report?.recommendations.total || 0})</h2>
            {producedRecommendations.length === 0 ? (
              <p className="hint muted">No produced recommendations are available for this run.</p>
            ) : (
              <>
                <div className="table-container">
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
                </div>
                {(report?.recommendations.total || 0) > producedRecommendations.length ? (
                  <p className="hint muted">
                    Showing the top {producedRecommendations.length} recommendations by priority out of{" "}
                    {report?.recommendations.total || 0}.
                  </p>
                ) : null}
              </>
            )}
          </SectionCard>
        </>
      ) : null}
    </PageContainer>
  );
}
