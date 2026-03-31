"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { PageContainer } from "../../../components/layout/PageContainer";
import { SectionCard } from "../../../components/layout/SectionCard";
import { SectionHeader } from "../../../components/layout/SectionHeader";
import { SummaryStatCard } from "../../../components/layout/SummaryStatCard";
import { WorkflowContextPanel } from "../../../components/layout/WorkflowContextPanel";
import { useOperatorContext } from "../../../components/useOperatorContext";
import {
  ApiRequestError,
  fetchAuditRun,
  fetchAuditRunFindings,
  fetchAuditRunSummary,
  fetchCompetitorComparisonReport,
  fetchRecommendationRuns,
  fetchRecommendationsForRun,
} from "../../../lib/api/client";
import type {
  CompetitorComparisonRun,
  Recommendation,
  RecommendationRun,
  SEOAuditFinding,
  SEOAuditRun,
  SEOAuditRunSummary,
} from "../../../lib/api/types";

const FINDING_PREVIEW_LIMIT = 20;
const SEVERITY_RANK: Record<string, number> = {
  CRITICAL: 3,
  WARNING: 2,
  INFO: 1,
};

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

function recommendationSource(item: Recommendation): string {
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

function isNotFoundError(error: unknown): boolean {
  return error instanceof ApiRequestError && error.status === 404;
}

function safeAuditDetailErrorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) {
    if (error.status === 401) {
      return "Session expired. Sign in again.";
    }
    if (error.status === 403) {
      return "You are not authorized to view this audit run.";
    }
    if (error.status === 404) {
      return "Audit run was not found in your tenant scope.";
    }
  }
  return "Unable to load audit run details right now. Please try again.";
}

function safeAuditRelatedErrorMessage(error: unknown): string {
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
  return "Some related audit context could not be loaded. The available data is still shown.";
}

function toSortedCountEntries(countMap: Record<string, number>): Array<[string, number]> {
  return Object.entries(countMap).sort((left, right) => left[0].localeCompare(right[0]));
}

function buildRecommendationDetailHref(item: Recommendation): string {
  const params = new URLSearchParams();
  params.set("site_id", item.site_id);
  return `/recommendations/${item.id}?${params.toString()}`;
}

function buildRecommendationRunHref(recommendationRunId: string, siteId: string): string {
  const params = new URLSearchParams();
  params.set("site_id", siteId);
  return `/recommendations/runs/${recommendationRunId}?${params.toString()}`;
}

function buildComparisonRunHref(comparisonRunId: string, siteId: string, competitorSetId?: string): string {
  const params = new URLSearchParams();
  if (siteId) {
    params.set("site_id", siteId);
  }
  if (competitorSetId) {
    params.set("set_id", competitorSetId);
  }
  const query = params.toString();
  return query
    ? `/competitors/comparison-runs/${comparisonRunId}?${query}`
    : `/competitors/comparison-runs/${comparisonRunId}`;
}

function buildSnapshotRunHref(snapshotRunId: string, siteId: string, competitorSetId: string): string {
  const params = new URLSearchParams();
  if (siteId) {
    params.set("site_id", siteId);
  }
  if (competitorSetId) {
    params.set("set_id", competitorSetId);
  }
  const query = params.toString();
  return query ? `/competitors/snapshot-runs/${snapshotRunId}?${query}` : `/competitors/snapshot-runs/${snapshotRunId}`;
}

function buildCompetitorSetHref(competitorSetId: string, siteId: string): string {
  const params = new URLSearchParams();
  if (siteId) {
    params.set("site_id", siteId);
  }
  const query = params.toString();
  return query ? `/competitors/${competitorSetId}?${query}` : `/competitors/${competitorSetId}`;
}

export default function AuditRunDetailPage() {
  const params = useParams<{ run_id: string }>();
  const runId = (params?.run_id || "").trim();
  const context = useOperatorContext();

  const [run, setRun] = useState<SEOAuditRun | null>(null);
  const [summary, setSummary] = useState<SEOAuditRunSummary | null>(null);
  const [findings, setFindings] = useState<SEOAuditFinding[]>([]);
  const [findingsByCategory, setFindingsByCategory] = useState<Record<string, number>>({});
  const [findingsBySeverity, setFindingsBySeverity] = useState<Record<string, number>>({});
  const [relatedRecommendationRuns, setRelatedRecommendationRuns] = useState<RecommendationRun[]>([]);
  const [relatedRecommendations, setRelatedRecommendations] = useState<Recommendation[]>([]);
  const [relatedComparisons, setRelatedComparisons] = useState<CompetitorComparisonRun[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [relatedError, setRelatedError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);

  const selectedSiteDisplayName = useMemo(() => {
    if (!run) {
      return null;
    }
    const match = context.sites.find((site) => site.id === run.site_id);
    return match?.display_name || null;
  }, [context.sites, run]);

  const effectiveFindingsByCategory = useMemo(() => {
    if (Object.keys(findingsByCategory).length > 0) {
      return findingsByCategory;
    }
    return summary?.by_category || {};
  }, [findingsByCategory, summary]);

  const effectiveFindingsBySeverity = useMemo(() => {
    if (Object.keys(findingsBySeverity).length > 0) {
      return findingsBySeverity;
    }
    return summary?.by_severity || {};
  }, [findingsBySeverity, summary]);

  const findingCategoryEntries = useMemo(
    () => toSortedCountEntries(effectiveFindingsByCategory),
    [effectiveFindingsByCategory],
  );
  const findingSeverityEntries = useMemo(
    () => toSortedCountEntries(effectiveFindingsBySeverity),
    [effectiveFindingsBySeverity],
  );

  const sortedFindings = useMemo(() => {
    return [...findings].sort((left, right) => {
      const leftSeverity = SEVERITY_RANK[(left.severity || "").toUpperCase()] || 0;
      const rightSeverity = SEVERITY_RANK[(right.severity || "").toUpperCase()] || 0;
      if (rightSeverity !== leftSeverity) {
        return rightSeverity - leftSeverity;
      }
      return right.created_at.localeCompare(left.created_at);
    });
  }, [findings]);

  const findingPreview = useMemo(
    () => sortedFindings.slice(0, FINDING_PREVIEW_LIMIT),
    [sortedFindings],
  );

  const recommendationTotalsFromRuns = useMemo(() => {
    return relatedRecommendationRuns.reduce(
      (accumulator, item) => {
        accumulator.total += item.total_recommendations;
        accumulator.critical += item.critical_recommendations;
        accumulator.warning += item.warning_recommendations;
        accumulator.info += item.info_recommendations;
        return accumulator;
      },
      { total: 0, critical: 0, warning: 0, info: 0 },
    );
  }, [relatedRecommendationRuns]);

  const relatedRecommendationStatusEntries = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const item of relatedRecommendations) {
      counts[item.status] = (counts[item.status] || 0) + 1;
    }
    return Object.entries(counts).sort((left, right) => left[0].localeCompare(right[0]));
  }, [relatedRecommendations]);

  const runStatus = (run?.status || "").trim().toLowerCase();
  const runCompleted = runStatus === "completed";
  const runFailed = runStatus === "failed";

  const workflowContextLinks = useMemo(() => {
    const links: Array<{ href: string; label: string }> = [
      { href: "/audits", label: "Audit Runs" },
      { href: "/recommendations", label: "Recommendation Queue" },
      { href: run ? `/competitors?site_id=${encodeURIComponent(run.site_id)}` : "/competitors", label: "Competitor Sets" },
    ];
    if (relatedRecommendationRuns.length > 0) {
      const topRun = relatedRecommendationRuns[0];
      links.push({ href: buildRecommendationRunHref(topRun.id, topRun.site_id), label: "Top linked recommendation run" });
    }
    if (relatedComparisons.length > 0) {
      const topComparison = relatedComparisons[0];
      links.push({
        href: buildComparisonRunHref(topComparison.id, topComparison.site_id, topComparison.competitor_set_id),
        label: "Top linked comparison run",
      });
    }
    return links;
  }, [relatedComparisons, relatedRecommendationRuns, run]);

  const workflowNextStep = useMemo(() => {
    if (relatedRecommendationRuns.length > 0) {
      const topRun = relatedRecommendationRuns[0];
      return {
        href: buildRecommendationRunHref(topRun.id, topRun.site_id),
        label: "Review linked recommendation run",
        note: "Validate recommended actions produced from this audit context.",
      };
    }
    if (relatedComparisons.length > 0) {
      const topComparison = relatedComparisons[0];
      return {
        href: buildComparisonRunHref(topComparison.id, topComparison.site_id, topComparison.competitor_set_id),
        label: "Review linked competitor comparison",
        note: "Inspect comparative findings that may influence recommendation priorities.",
      };
    }
    return {
      href: "/recommendations",
      label: "Open recommendation queue",
      note: "Generated recommendations appear after linked runs are completed.",
    };
  }, [relatedComparisons, relatedRecommendationRuns]);

  useEffect(() => {
    if (context.loading || context.error || !runId) {
      setRun(null);
      setSummary(null);
      setFindings([]);
      setFindingsByCategory({});
      setFindingsBySeverity({});
      setRelatedRecommendationRuns([]);
      setRelatedRecommendations([]);
      setRelatedComparisons([]);
      setLoading(false);
      setError(null);
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
      setRun(null);
      setSummary(null);
      setFindings([]);
      setFindingsByCategory({});
      setFindingsBySeverity({});
      setRelatedRecommendationRuns([]);
      setRelatedRecommendations([]);
      setRelatedComparisons([]);

      try {
        const runData = await fetchAuditRun(context.token, context.businessId, runId);
        if (cancelled) {
          return;
        }
        setRun(runData);

        const relatedErrors: unknown[] = [];

        const [summaryResult, findingsResult, recommendationRunsResult] = await Promise.allSettled([
          fetchAuditRunSummary(context.token, context.businessId, runData.id),
          fetchAuditRunFindings(context.token, context.businessId, runData.id),
          fetchRecommendationRuns(context.token, context.businessId, runData.site_id),
        ]);
        if (cancelled) {
          return;
        }

        if (summaryResult.status === "fulfilled") {
          setSummary(summaryResult.value);
        } else if (!isNotFoundError(summaryResult.reason)) {
          relatedErrors.push(summaryResult.reason);
        }

        if (findingsResult.status === "fulfilled") {
          setFindings(findingsResult.value.items);
          setFindingsByCategory(findingsResult.value.by_category || {});
          setFindingsBySeverity(findingsResult.value.by_severity || {});
        } else if (!isNotFoundError(findingsResult.reason)) {
          relatedErrors.push(findingsResult.reason);
        }

        let matchingRecommendationRuns: RecommendationRun[] = [];
        if (recommendationRunsResult.status === "fulfilled") {
          matchingRecommendationRuns = recommendationRunsResult.value.items
            .filter((item) => item.audit_run_id === runData.id)
            .sort((left, right) => right.created_at.localeCompare(left.created_at));
          setRelatedRecommendationRuns(matchingRecommendationRuns);
        } else if (!isNotFoundError(recommendationRunsResult.reason)) {
          relatedErrors.push(recommendationRunsResult.reason);
        }

        if (matchingRecommendationRuns.length > 0) {
          const recommendationResponses = await Promise.allSettled(
            matchingRecommendationRuns.map((item) =>
              fetchRecommendationsForRun(context.token, context.businessId, runData.site_id, item.id),
            ),
          );
          if (cancelled) {
            return;
          }

          const recommendationById = new Map<string, Recommendation>();
          for (const result of recommendationResponses) {
            if (result.status === "fulfilled") {
              for (const item of result.value.items) {
                recommendationById.set(item.id, item);
              }
            } else if (!isNotFoundError(result.reason)) {
              relatedErrors.push(result.reason);
            }
          }

          const nextRelatedRecommendations = [...recommendationById.values()].sort((left, right) => {
            if (right.priority_score !== left.priority_score) {
              return right.priority_score - left.priority_score;
            }
            return right.created_at.localeCompare(left.created_at);
          });
          setRelatedRecommendations(nextRelatedRecommendations);

          const comparisonRunIds = [...new Set(
            matchingRecommendationRuns
              .map((item) => item.comparison_run_id)
              .filter((value): value is string => Boolean(value)),
          )];

          if (comparisonRunIds.length > 0) {
            const comparisonResponses = await Promise.allSettled(
              comparisonRunIds.map((comparisonRunId) =>
                fetchCompetitorComparisonReport(context.token, context.businessId, comparisonRunId),
              ),
            );
            if (cancelled) {
              return;
            }

            const nextRelatedComparisons: CompetitorComparisonRun[] = [];
            for (const result of comparisonResponses) {
              if (result.status === "fulfilled") {
                nextRelatedComparisons.push(result.value.run);
              } else if (!isNotFoundError(result.reason)) {
                relatedErrors.push(result.reason);
              }
            }
            nextRelatedComparisons.sort((left, right) => right.created_at.localeCompare(left.created_at));
            setRelatedComparisons(nextRelatedComparisons);
          }
        }

        if (relatedErrors.length > 0) {
          setRelatedError(safeAuditRelatedErrorMessage(relatedErrors[0]));
        }
      } catch (err) {
        if (cancelled) {
          return;
        }
        if (err instanceof ApiRequestError && err.status === 404) {
          setNotFound(true);
          return;
        }
        setError(safeAuditDetailErrorMessage(err));
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
  }, [context.businessId, context.error, context.loading, context.token, runId]);

  if (context.loading) {
    return (
      <PageContainer>
        <SectionCard as="div" variant="support" className="role-surface-support">
          <SectionHeader
            title="Audit Run Detail"
            subtitle="Loading audit run detail for the selected business context."
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
            title="Audit Run Detail"
            subtitle="Unable to load tenant context. Refresh and sign in again."
            headingLevel={1}
            variant="support"
          />
        </SectionCard>
      </PageContainer>
    );
  }
  if (!runId) {
    return (
      <PageContainer>
        <SectionCard variant="support" className="role-surface-support">
          <SectionHeader
            title="Audit Run Detail"
            subtitle="Audit run identifier is missing."
            headingLevel={1}
            variant="support"
          />
          <p><Link href="/audits">Back to Audit Runs</Link></p>
        </SectionCard>
      </PageContainer>
    );
  }

  return (
    <PageContainer>
      <div className="role-dashboard-landing">
        <SectionCard variant="primary" className="role-dashboard-hero">
          <SectionHeader
            title="Audit Run Detail"
            subtitle="Inspect crawl outcomes, findings, and downstream recommendation lineage for this audit run."
            headingLevel={1}
            variant="hero"
            meta={<span className="hint muted">Audit run: <code>{runId}</code></span>}
            actions={<Link href="/audits">Back to Audit Runs</Link>}
          />
          <div className="workspace-summary-strip role-summary-strip">
            <SummaryStatCard
              label="Run status"
              value={run?.status || "Loading"}
              detail={runCompleted ? "Completed and stable" : runFailed ? "Run failed" : "Pending completion"}
              tone={runCompleted ? "success" : runFailed ? "danger" : "warning"}
              variant="elevated"
            />
            <SummaryStatCard
              label="Findings loaded"
              value={findings.length}
              detail={summary ? `Summary total: ${summary.total_findings}` : "Summary pending"}
              tone={findings.length > 0 ? "neutral" : "warning"}
              variant="elevated"
            />
            <SummaryStatCard
              label="Related recommendation runs"
              value={relatedRecommendationRuns.length}
              detail="Lineage to recommendation outputs"
              tone={relatedRecommendationRuns.length > 0 ? "success" : "warning"}
              variant="elevated"
            />
            <SummaryStatCard
              label="Related competitor analysis"
              value={relatedComparisons.length}
              detail="Comparison lineage linked to this run"
              tone={relatedComparisons.length > 0 ? "neutral" : "warning"}
              variant="elevated"
            />
          </div>
          {loading ? <p className="hint muted">Loading audit run detail...</p> : null}
          {!loading && notFound ? (
            <p className="hint warning">Audit run not found or not accessible in your tenant scope.</p>
          ) : null}
          {!loading && error ? <p className="hint error">{error}</p> : null}
        </SectionCard>
      </div>

      {!loading && !notFound && !error && run ? (
        <WorkflowContextPanel
          data-testid="audit-run-workflow-context"
          lineage="Audits → Audit run detail → Linked recommendation/comparison flows"
          links={workflowContextLinks}
          nextStep={workflowNextStep}
        />
      ) : null}

      {!loading && !notFound && !error && run ? (
        <>
          {relatedError ? (
            <SectionCard variant="support" className="role-surface-support">
              <p className="hint warning">{relatedError}</p>
            </SectionCard>
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
            <p>
              Crawl Duration (ms): <strong>{run.crawl_duration_ms ?? "-"}</strong>
            </p>
          </div>

          <div className="panel stack">
            <h2>Run Outcome</h2>
            {runCompleted ? (
              <p className="hint">Audit run completed. Findings and downstream recommendations are stable.</p>
            ) : runFailed ? (
              <p className="hint warning">
                Audit run failed before completion. Partial metrics or downstream lineage may be incomplete.
              </p>
            ) : (
              <p className="hint warning">
                Audit run is still {run.status}. Findings, summaries, and linked recommendations may still change.
              </p>
            )}
            <p>Error Summary: {run.error_summary || "-"}</p>
            <p className="hint muted">
              Use workflow context links above to move between this audit, linked recommendation runs, and competitor lineage.
            </p>
          </div>

          <div className="panel stack">
            <h2>Run Metrics</h2>
            <table className="table">
              <tbody>
                <tr>
                  <th>Configured Max Pages</th>
                  <td>{run.max_pages}</td>
                </tr>
                <tr>
                  <th>Configured Max Depth</th>
                  <td>{run.max_depth}</td>
                </tr>
                <tr>
                  <th>Pages Discovered</th>
                  <td>{run.pages_discovered}</td>
                </tr>
                <tr>
                  <th>Pages Crawled</th>
                  <td>{run.pages_crawled}</td>
                </tr>
                <tr>
                  <th>Pages Skipped</th>
                  <td>{run.pages_skipped}</td>
                </tr>
                <tr>
                  <th>Duplicate URLs Skipped</th>
                  <td>{run.duplicate_urls_skipped}</td>
                </tr>
                <tr>
                  <th>Errors Encountered</th>
                  <td>{run.errors_encountered}</td>
                </tr>
                <tr>
                  <th>Crawl Duration (ms)</th>
                  <td>{run.crawl_duration_ms ?? "-"}</td>
                </tr>
              </tbody>
            </table>
          </div>

          <div className="panel stack">
            <h2>Summary</h2>
            {summary ? (
              <>
                <table className="table">
                  <tbody>
                    <tr>
                      <th>Total Findings</th>
                      <td>{summary.total_findings}</td>
                    </tr>
                    <tr>
                      <th>Critical Findings</th>
                      <td>{summary.critical_findings}</td>
                    </tr>
                    <tr>
                      <th>Warning Findings</th>
                      <td>{summary.warning_findings}</td>
                    </tr>
                    <tr>
                      <th>Info Findings</th>
                      <td>{summary.info_findings}</td>
                    </tr>
                    <tr>
                      <th>Total Pages</th>
                      <td>{summary.total_pages}</td>
                    </tr>
                    <tr>
                      <th>Health Score</th>
                      <td>{summary.health_score}</td>
                    </tr>
                  </tbody>
                </table>
              </>
            ) : (
              <p className="hint muted">No audit summary is available for this run.</p>
            )}
          </div>

          <div className="panel stack">
            <h2>Findings Context</h2>
            <p>
              Loaded findings: <strong>{findings.length}</strong>
            </p>
            <div className="metrics-grid">
              <div className="panel stack panel-compact">
                <h3>By Severity</h3>
                {findingSeverityEntries.length === 0 ? (
                  <p className="hint muted">No severity counts are available.</p>
                ) : (
                  <table className="table">
                    <tbody>
                      {findingSeverityEntries.map(([key, value]) => (
                        <tr key={`severity-${key}`}>
                          <th>{key}</th>
                          <td>{value}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
              <div className="panel stack panel-compact">
                <h3>By Category</h3>
                {findingCategoryEntries.length === 0 ? (
                  <p className="hint muted">No category counts are available.</p>
                ) : (
                  <table className="table">
                    <tbody>
                      {findingCategoryEntries.map(([key, value]) => (
                        <tr key={`category-${key}`}>
                          <th>{key}</th>
                          <td>{value}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            </div>

            {findingPreview.length === 0 ? (
              <p className="hint muted">No findings are currently available for this audit run.</p>
            ) : (
              <>
                <table className="table">
                  <thead>
                    <tr>
                      <th>Title</th>
                      <th>Severity</th>
                      <th>Category</th>
                      <th>Type</th>
                      <th>Rule</th>
                      <th>Suggested Fix</th>
                      <th>Created</th>
                    </tr>
                  </thead>
                  <tbody>
                    {findingPreview.map((item) => (
                      <tr key={item.id}>
                        <td>{item.title}</td>
                        <td>{item.severity}</td>
                        <td>{item.category}</td>
                        <td>{item.finding_type}</td>
                        <td>{item.rule_key}</td>
                        <td>{item.suggested_fix || "-"}</td>
                        <td>{formatDateTime(item.created_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {sortedFindings.length > FINDING_PREVIEW_LIMIT ? (
                  <p className="hint muted">
                    Showing the top {FINDING_PREVIEW_LIMIT} findings by severity and recency out of {sortedFindings.length}.
                  </p>
                ) : null}
              </>
            )}
          </div>

          <div className="panel stack">
            <h2>Related Recommendation Runs ({relatedRecommendationRuns.length})</h2>
            {relatedRecommendationRuns.length === 0 ? (
              <p className="hint muted">No recommendation runs are currently linked to this audit run.</p>
            ) : (
              <>
                <p className="hint muted">
                  Linked recommendation runs report {recommendationTotalsFromRuns.total} recommendation(s): critical {" "}
                  {recommendationTotalsFromRuns.critical}, warning {recommendationTotalsFromRuns.warning}, info {" "}
                  {recommendationTotalsFromRuns.info}.
                </p>
                <table className="table">
                  <thead>
                    <tr>
                      <th>Run ID</th>
                      <th>Status</th>
                      <th>Total</th>
                      <th>Critical</th>
                      <th>Warning</th>
                      <th>Info</th>
                      <th>Comparison Run</th>
                      <th>Started</th>
                      <th>Completed</th>
                    </tr>
                  </thead>
                  <tbody>
                    {relatedRecommendationRuns.map((item) => (
                      <tr key={item.id}>
                        <td>
                          <Link href={buildRecommendationRunHref(item.id, item.site_id)}>
                            <code>{item.id}</code>
                          </Link>
                        </td>
                        <td>{item.status}</td>
                        <td>{item.total_recommendations}</td>
                        <td>{item.critical_recommendations}</td>
                        <td>{item.warning_recommendations}</td>
                        <td>{item.info_recommendations}</td>
                        <td>
                          {item.comparison_run_id ? (
                            <Link href={buildComparisonRunHref(item.comparison_run_id, item.site_id)}>
                              <code>{item.comparison_run_id}</code>
                            </Link>
                          ) : (
                            "-"
                          )}
                        </td>
                        <td>{formatDateTime(item.started_at)}</td>
                        <td>{formatDateTime(item.completed_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
          </div>

          <div className="panel stack">
            <h2>Related Recommendations ({relatedRecommendations.length})</h2>
            {relatedRecommendationRuns.length === 0 ? (
              <p className="hint muted">Related recommendations appear when recommendation runs are linked to this audit.</p>
            ) : relatedRecommendations.length === 0 ? (
              <p className="hint muted">No recommendations were found for the linked recommendation runs.</p>
            ) : (
              <>
                {relatedRecommendationStatusEntries.length > 0 ? (
                  <p className="hint muted">
                    Status breakdown: {relatedRecommendationStatusEntries.map(([key, value]) => `${key}: ${value}`).join(", ")}.
                  </p>
                ) : null}
                <table className="table">
                  <thead>
                    <tr>
                      <th>Title</th>
                      <th>Status</th>
                      <th>Priority</th>
                      <th>Category</th>
                      <th>Source</th>
                      <th>Recommendation Run</th>
                      <th>Comparison Run</th>
                      <th>Created</th>
                    </tr>
                  </thead>
                  <tbody>
                    {relatedRecommendations.map((item) => (
                      <tr key={item.id}>
                        <td>
                          <Link href={buildRecommendationDetailHref(item)}>{item.title}</Link>
                        </td>
                        <td>{item.status}</td>
                        <td>
                          {item.priority_score} ({item.priority_band})
                        </td>
                        <td>{item.category}</td>
                        <td>{recommendationSource(item)}</td>
                        <td>
                          <Link href={buildRecommendationRunHref(item.recommendation_run_id, item.site_id)}>
                            <code>{item.recommendation_run_id}</code>
                          </Link>
                        </td>
                        <td>
                          {item.comparison_run_id ? (
                            <Link href={buildComparisonRunHref(item.comparison_run_id, item.site_id)}>
                              <code>{item.comparison_run_id}</code>
                            </Link>
                          ) : (
                            "-"
                          )}
                        </td>
                        <td>{formatDateTime(item.created_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
          </div>

          <div className="panel stack">
            <h2>Related Competitor Analysis ({relatedComparisons.length})</h2>
            {relatedComparisons.length === 0 ? (
              <p className="hint muted">
                No competitor comparison lineage is linked to this audit run through recommendation runs.
              </p>
            ) : (
              <table className="table">
                <thead>
                  <tr>
                    <th>Comparison Run</th>
                    <th>Status</th>
                    <th>Competitor Set</th>
                    <th>Snapshot Run</th>
                    <th>Baseline Audit</th>
                    <th>Total Findings</th>
                    <th>Created</th>
                  </tr>
                </thead>
                <tbody>
                  {relatedComparisons.map((item) => (
                    <tr key={item.id}>
                      <td>
                        <Link href={buildComparisonRunHref(item.id, item.site_id, item.competitor_set_id)}>
                          <code>{item.id}</code>
                        </Link>
                      </td>
                      <td>{item.status}</td>
                      <td>
                        <Link href={buildCompetitorSetHref(item.competitor_set_id, item.site_id)}>
                          <code>{item.competitor_set_id}</code>
                        </Link>
                      </td>
                      <td>
                        <Link href={buildSnapshotRunHref(item.snapshot_run_id, item.site_id, item.competitor_set_id)}>
                          <code>{item.snapshot_run_id}</code>
                        </Link>
                      </td>
                      <td>
                        {item.baseline_audit_run_id ? (
                          <>
                            <Link href={`/audits/${item.baseline_audit_run_id}`}>
                              <code>{item.baseline_audit_run_id}</code>
                            </Link>
                            {item.baseline_audit_run_id === run.id ? " (this run)" : ""}
                          </>
                        ) : (
                          "-"
                        )}
                      </td>
                      <td>{item.total_findings}</td>
                      <td>{formatDateTime(item.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </>
      ) : null}
    </PageContainer>
  );
}
