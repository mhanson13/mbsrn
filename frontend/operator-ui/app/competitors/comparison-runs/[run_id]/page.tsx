"use client";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { PageContainer } from "../../../../components/layout/PageContainer";
import { DetailFocusPanel } from "../../../../components/layout/DetailFocusPanel";
import { SectionCard } from "../../../../components/layout/SectionCard";
import { SectionHeader } from "../../../../components/layout/SectionHeader";
import { SummaryStatCard } from "../../../../components/layout/SummaryStatCard";
import { WorkflowContextPanel } from "../../../../components/layout/WorkflowContextPanel";
import { useOperatorContext } from "../../../../components/useOperatorContext";
import {
  ApiRequestError,
  fetchCompetitorComparisonReport,
  fetchCompetitorSnapshotRun,
  fetchRecommendationRuns,
  fetchRecommendations,
} from "../../../../lib/api/client";
import type {
  CompetitorComparisonReport,
  CompetitorSnapshotRun,
  Recommendation,
  RecommendationRun,
} from "../../../../lib/api/types";

const RELATED_RECOMMENDATION_PAGE_SIZE = 100;

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

function safeComparisonRunErrorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) {
    if (error.status === 401) {
      return "Session expired. Sign in again.";
    }
    if (error.status === 403) {
      return "You are not authorized to view this comparison run.";
    }
    if (error.status === 404) {
      return "Comparison run was not found in your tenant scope.";
    }
  }
  return "Unable to load comparison run details right now. Please try again.";
}

function safeComparisonRelatedErrorMessage(error: unknown): string {
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
  return "Unable to load one or more related resources right now.";
}

function toSortedCountEntries(countMap: Record<string, number> | null | undefined): Array<[string, number]> {
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

function buildRecommendationRunHref(recommendationRunId: string, siteId: string): string {
  const params = new URLSearchParams();
  params.set("site_id", siteId);
  return `/recommendations/runs/${recommendationRunId}?${params.toString()}`;
}

export default function ComparisonRunDetailPage() {
  const params = useParams<{ run_id: string }>();
  const searchParams = useSearchParams();
  const comparisonRunId = (params?.run_id || "").trim();
  const requestedSetId = (searchParams.get("set_id") || "").trim();
  const requestedSiteId = (searchParams.get("site_id") || "").trim();
  const context = useOperatorContext();

  const [report, setReport] = useState<CompetitorComparisonReport | null>(null);
  const [snapshotRun, setSnapshotRun] = useState<CompetitorSnapshotRun | null>(null);
  const [linkedRecommendationRuns, setLinkedRecommendationRuns] = useState<RecommendationRun[]>([]);
  const [relatedRecommendations, setRelatedRecommendations] = useState<Recommendation[]>([]);
  const [truncatedRecommendationRunIds, setTruncatedRecommendationRunIds] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [relatedError, setRelatedError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);

  const run = report?.run || null;
  const selectedSiteDisplayName = useMemo(() => {
    if (!run) {
      return null;
    }
    const match = context.sites.find((site) => site.id === run.site_id);
    return match?.display_name || null;
  }, [context.sites, run]);

  const backToListHref = useMemo(() => {
    const siteId = run?.site_id || requestedSiteId;
    if (!siteId) {
      return "/competitors";
    }
    const params = new URLSearchParams();
    params.set("site_id", siteId);
    return `/competitors?${params.toString()}`;
  }, [requestedSiteId, run?.site_id]);

  const backToSetHref = useMemo(() => {
    const parentSetId = run?.competitor_set_id || requestedSetId;
    const parentSiteId = run?.site_id || requestedSiteId;
    if (!parentSetId) {
      return backToListHref;
    }
    const query = new URLSearchParams();
    if (parentSiteId) {
      query.set("site_id", parentSiteId);
    }
    const queryText = query.toString();
    return queryText ? `/competitors/${parentSetId}?${queryText}` : `/competitors/${parentSetId}`;
  }, [backToListHref, requestedSetId, requestedSiteId, run]);

  const buildSnapshotRunHref = useCallback((snapshotId: string): string => {
    const params = new URLSearchParams();
    const siteId = run?.site_id || requestedSiteId;
    const setId = run?.competitor_set_id || requestedSetId;
    if (siteId) {
      params.set("site_id", siteId);
    }
    if (setId) {
      params.set("set_id", setId);
    }
    const query = params.toString();
    return query ? `/competitors/snapshot-runs/${snapshotId}?${query}` : `/competitors/snapshot-runs/${snapshotId}`;
  }, [requestedSetId, requestedSiteId, run?.competitor_set_id, run?.site_id]);

  const findings = report?.findings.items || [];
  const findingsTotal = report?.findings.total ?? findings.length;
  const typeCounts = toSortedCountEntries(report?.rollups.findings_by_type);
  const categoryCounts = toSortedCountEntries(report?.rollups.findings_by_category);
  const severityCounts = toSortedCountEntries(report?.rollups.findings_by_severity);
  const metricRollups = report?.rollups.metric_rollups || [];
  const linkedRecommendationRunIds = linkedRecommendationRuns.map((item) => item.id);

  const workflowContextLinks = useMemo(() => {
    const links: Array<{ href: string; label: string }> = [
      { href: backToListHref, label: "Competitor Sets" },
      { href: backToSetHref, label: "Parent Competitor Set" },
      { href: run ? buildSnapshotRunHref(run.snapshot_run_id) : "", label: "Snapshot Run" },
      { href: "/recommendations", label: "Recommendation Queue" },
      { href: "/audits", label: "Audit Runs" },
    ];
    if (run?.baseline_audit_run_id) {
      links.push({ href: `/audits/${run.baseline_audit_run_id}`, label: "Baseline Audit Run" });
    }
    if (snapshotRun?.client_audit_run_id) {
      links.push({ href: `/audits/${snapshotRun.client_audit_run_id}`, label: "Client Audit Run" });
    }
    if (linkedRecommendationRuns.length > 0) {
      const topRun = linkedRecommendationRuns[0];
      links.push({
        href: buildRecommendationRunHref(topRun.id, topRun.site_id),
        label: "Top linked recommendation run",
      });
    }
    return links;
  }, [
    backToListHref,
    backToSetHref,
    buildSnapshotRunHref,
    linkedRecommendationRuns,
    run,
    snapshotRun,
  ]);

  const workflowNextStep = useMemo(() => {
    if (linkedRecommendationRuns.length > 0) {
      const topRun = linkedRecommendationRuns[0];
      return {
        href: buildRecommendationRunHref(topRun.id, topRun.site_id),
        label: "Review linked recommendation run",
        note: "Confirm action priorities from this comparison context.",
      };
    }
    return {
      href: "/recommendations",
      label: "Open recommendation queue",
      note: "Comparison findings feed recommendation generation and triage.",
    };
  }, [linkedRecommendationRuns]);

  const detailFocusTakeaway = useMemo(() => {
    if (!run) {
      return "Comparison run context is still loading.";
    }
    if (run.total_findings > 0) {
      return `Comparison captured ${run.total_findings} finding${run.total_findings === 1 ? "" : "s"} across client and competitor pages.`;
    }
    if (metricRollups.length > 0) {
      return "Comparison finished with metric rollups but no explicit findings.";
    }
    return "Comparison contains no findings yet; review upstream snapshot context if this is unexpected.";
  }, [metricRollups.length, run]);

  const detailFocusNextStep = useMemo(() => {
    if (linkedRecommendationRuns.length > 0) {
      const topRun = linkedRecommendationRuns[0];
      return {
        href: buildRecommendationRunHref(topRun.id, topRun.site_id),
        label: "Review linked recommendation run",
        note: "Use comparison findings as evidence for recommendation action priority.",
      };
    }
    return {
      href: "/recommendations",
      label: "Open recommendation queue",
      note: "Generate or review recommendation output using this comparison as context.",
    };
  }, [linkedRecommendationRuns]);

  useEffect(() => {
    if (context.loading || context.error || !comparisonRunId) {
      setReport(null);
      setSnapshotRun(null);
      setLinkedRecommendationRuns([]);
      setRelatedRecommendations([]);
      setTruncatedRecommendationRunIds([]);
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
      setReport(null);
      setSnapshotRun(null);
      setLinkedRecommendationRuns([]);
      setRelatedRecommendations([]);
      setTruncatedRecommendationRunIds([]);

      try {
        const reportResult = await fetchCompetitorComparisonReport(
          context.token,
          context.businessId,
          comparisonRunId,
        );
        if (cancelled) {
          return;
        }

        if (requestedSetId && reportResult.run.competitor_set_id !== requestedSetId) {
          setNotFound(true);
          return;
        }
        if (requestedSiteId && reportResult.run.site_id !== requestedSiteId) {
          setNotFound(true);
          return;
        }

        setReport(reportResult);

        let nextSnapshotRun: CompetitorSnapshotRun | null = null;
        if (reportResult.run.snapshot_run_id) {
          try {
            nextSnapshotRun = await fetchCompetitorSnapshotRun(
              context.token,
              context.businessId,
              reportResult.run.snapshot_run_id,
            );
          } catch (snapshotError) {
            if (!(snapshotError instanceof ApiRequestError && snapshotError.status === 404)) {
              setRelatedError(safeComparisonRelatedErrorMessage(snapshotError));
            }
          }
        }
        if (!cancelled) {
          setSnapshotRun(nextSnapshotRun);
        }

        try {
          const recommendationRunsResult = await fetchRecommendationRuns(
            context.token,
            context.businessId,
            reportResult.run.site_id,
          );
          if (cancelled) {
            return;
          }
          const matchingRuns = recommendationRunsResult.items.filter(
            (item) => item.comparison_run_id === reportResult.run.id,
          );
          setLinkedRecommendationRuns(matchingRuns);

          if (matchingRuns.length === 0) {
            return;
          }

          const recommendationResponses = await Promise.all(
            matchingRuns.map(async (item) => {
              const response = await fetchRecommendations(
                context.token,
                context.businessId,
                reportResult.run.site_id,
                {
                  recommendation_run_id: item.id,
                  sort_by: "priority_score",
                  sort_order: "desc",
                  page: 1,
                  page_size: RELATED_RECOMMENDATION_PAGE_SIZE,
                },
              );
              return { runId: item.id, response };
            }),
          );

          if (cancelled) {
            return;
          }

          const relatedById = new Map<string, Recommendation>();
          const truncatedRunIds: string[] = [];
          for (const result of recommendationResponses) {
            if (result.response.total > result.response.items.length) {
              truncatedRunIds.push(result.runId);
            }
            for (const recommendation of result.response.items) {
              if (!relatedById.has(recommendation.id)) {
                relatedById.set(recommendation.id, recommendation);
              }
            }
          }

          const sortedRecommendations = [...relatedById.values()].sort((left, right) => {
            if (right.priority_score !== left.priority_score) {
              return right.priority_score - left.priority_score;
            }
            return right.created_at.localeCompare(left.created_at);
          });

          setRelatedRecommendations(sortedRecommendations);
          setTruncatedRecommendationRunIds(truncatedRunIds);
        } catch (relatedRecommendationsError) {
          if (cancelled) {
            return;
          }
          if (
            relatedRecommendationsError instanceof ApiRequestError &&
            relatedRecommendationsError.status === 404
          ) {
            return;
          }
          setRelatedError(safeComparisonRelatedErrorMessage(relatedRecommendationsError));
        }
      } catch (err) {
        if (cancelled) {
          return;
        }
        if (err instanceof ApiRequestError && err.status === 404) {
          setNotFound(true);
          return;
        }
        setError(safeComparisonRunErrorMessage(err));
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
    comparisonRunId,
    context.businessId,
    context.error,
    context.loading,
    context.token,
    requestedSetId,
    requestedSiteId,
  ]);

  if (context.loading) {
    return (
      <PageContainer>
        <SectionCard as="div" variant="support" className="role-surface-support">
          <SectionHeader
            title="Comparison Run Detail"
            subtitle="Loading comparison run detail for this competitor analysis."
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
            title="Comparison Run Detail"
            subtitle="Unable to load tenant context. Refresh and sign in again."
            headingLevel={1}
            variant="support"
          />
        </SectionCard>
      </PageContainer>
    );
  }
  if (!comparisonRunId) {
    return (
      <PageContainer>
        <SectionCard variant="support" className="role-surface-support">
          <SectionHeader
            title="Comparison Run Detail"
            subtitle="Comparison run identifier is missing."
            headingLevel={1}
            variant="support"
          />
          <p><Link href={backToListHref}>Back to Competitor Sets</Link></p>
        </SectionCard>
      </PageContainer>
    );
  }

  return (
    <PageContainer>
      <div className="role-dashboard-landing">
        <SectionCard variant="primary" className="role-dashboard-hero">
          <SectionHeader
            title="Comparison Run Detail"
            subtitle="Inspect comparative findings, metric rollups, and downstream recommendation linkage."
            headingLevel={1}
            variant="hero"
            meta={<span className="hint muted">Comparison run: <code>{comparisonRunId}</code></span>}
            actions={<Link href={backToSetHref}>Back to Competitor Set</Link>}
          />
          <div className="workspace-summary-strip role-summary-strip">
            <SummaryStatCard
              label="Run status"
              value={run?.status || "Loading"}
              detail="Comparison execution state"
              tone={run?.status?.toLowerCase() === "completed" ? "success" : run?.status?.toLowerCase() === "failed" ? "danger" : "warning"}
              variant="elevated"
            />
            <SummaryStatCard
              label="Total findings"
              value={run?.total_findings ?? 0}
              detail="Findings recorded in this run"
              tone={(run?.total_findings || 0) > 0 ? "neutral" : "warning"}
              variant="elevated"
            />
            <SummaryStatCard
              label="Metric rollups"
              value={metricRollups.length}
              detail="Comparative metric summary rows"
              tone={metricRollups.length > 0 ? "neutral" : "warning"}
              variant="elevated"
            />
            <SummaryStatCard
              label="Related recommendations"
              value={relatedRecommendations.length}
              detail="Recommendations linked to this comparison"
              tone={relatedRecommendations.length > 0 ? "success" : "warning"}
              variant="elevated"
            />
          </div>
          {loading ? <p className="hint muted">Loading comparison run detail...</p> : null}
          {!loading && notFound ? (
            <p className="hint warning">Comparison run not found or not accessible in your tenant scope.</p>
          ) : null}
          {!loading && error ? <p className="hint error">{error}</p> : null}
        </SectionCard>
      </div>

      {!loading && !notFound && !error && run ? (
        <WorkflowContextPanel
          data-testid="comparison-run-workflow-context"
          lineage="Competitors → Comparison run → Recommendation linkage"
          links={workflowContextLinks}
          nextStep={workflowNextStep}
        />
      ) : null}

      {!loading && !notFound && !error && run ? (
        <DetailFocusPanel
          data-testid="comparison-run-detail-focus"
          takeaway={detailFocusTakeaway}
          nextStep={detailFocusNextStep}
          detailHint="Run context and aggregate metrics come first, followed by findings detail and recommendation linkage."
        />
      ) : null}

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
            <p>
              Competitor Set ID:{" "}
              <Link href={backToSetHref}>
                <code>{run.competitor_set_id}</code>
              </Link>
            </p>
            <p>
              Snapshot Run ID:{" "}
              <Link href={buildSnapshotRunHref(run.snapshot_run_id)}>
                <code>{run.snapshot_run_id}</code>
              </Link>
            </p>
            <p>Status: {run.status}</p>
            <p>Created By: {run.created_by_principal_id || "-"}</p>
            <p>Started: {formatDateTime(run.started_at)}</p>
            <p>Completed: {formatDateTime(run.completed_at)}</p>
            <p>Duration (ms): {run.duration_ms ?? "-"}</p>
            <p>Created: {formatDateTime(run.created_at)}</p>
            <p>Updated: {formatDateTime(run.updated_at)}</p>
            <p>Error Summary: {run.error_summary || "-"}</p>
          </div>

          <div className="panel stack">
            <h2>Related Workflow Scope</h2>
            <p className="hint muted">
              Workflow context links above keep this comparison connected to snapshot, audit, and recommendation routes.
            </p>
          </div>

          <div className="panel stack">
            <h2>Run Metrics</h2>
            <table className="table">
              <tbody>
                <tr>
                  <th>Total Findings</th>
                  <td>{run.total_findings}</td>
                </tr>
                <tr>
                  <th>Critical Findings</th>
                  <td>{run.critical_findings}</td>
                </tr>
                <tr>
                  <th>Warning Findings</th>
                  <td>{run.warning_findings}</td>
                </tr>
                <tr>
                  <th>Info Findings</th>
                  <td>{run.info_findings}</td>
                </tr>
                <tr>
                  <th>Client Pages Analyzed</th>
                  <td>{run.client_pages_analyzed}</td>
                </tr>
                <tr>
                  <th>Competitor Pages Analyzed</th>
                  <td>{run.competitor_pages_analyzed}</td>
                </tr>
              </tbody>
            </table>
          </div>

          <div className="panel stack">
            <h2>Finding Distributions</h2>
            <div className="metrics-grid">
              <div className="panel stack panel-compact">
                <h3>By Type</h3>
                {typeCounts.length === 0 ? (
                  <p className="hint muted">No type counts are available.</p>
                ) : (
                  <table className="table">
                    <tbody>
                      {typeCounts.map(([key, value]) => (
                        <tr key={`type-${key}`}>
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
                {categoryCounts.length === 0 ? (
                  <p className="hint muted">No category counts are available.</p>
                ) : (
                  <table className="table">
                    <tbody>
                      {categoryCounts.map(([key, value]) => (
                        <tr key={`category-${key}`}>
                          <th>{key}</th>
                          <td>{value}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
              <div className="panel stack panel-compact">
                <h3>By Severity</h3>
                {severityCounts.length === 0 ? (
                  <p className="hint muted">No severity counts are available.</p>
                ) : (
                  <table className="table">
                    <tbody>
                      {severityCounts.map(([key, value]) => (
                        <tr key={`severity-${key}`}>
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
            <h2>Metric Rollups ({metricRollups.length})</h2>
            {metricRollups.length === 0 ? (
              <p className="hint muted">No metric rollups are available for this run.</p>
            ) : (
              <table className="table">
                <thead>
                  <tr>
                    <th>Metric</th>
                    <th>Category</th>
                    <th>Unit</th>
                    <th>Client</th>
                    <th>Competitor</th>
                    <th>Delta</th>
                    <th>Gap Direction</th>
                    <th>Severity</th>
                  </tr>
                </thead>
                <tbody>
                  {metricRollups.map((metric) => (
                    <tr key={metric.key}>
                      <td>{metric.title}</td>
                      <td>{metric.category}</td>
                      <td>{metric.unit}</td>
                      <td>{metric.client_value}</td>
                      <td>{metric.competitor_value}</td>
                      <td>{metric.delta}</td>
                      <td>{metric.gap_direction}</td>
                      <td>{metric.severity}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          <div className="panel stack">
            <h2>Findings ({findingsTotal})</h2>
            {findings.length === 0 ? (
              <p className="hint muted">No findings are recorded for this comparison run.</p>
            ) : (
              <table className="table">
                <thead>
                  <tr>
                    <th>Title</th>
                    <th>Severity</th>
                    <th>Category</th>
                    <th>Type</th>
                    <th>Gap</th>
                    <th>Client Value</th>
                    <th>Competitor Value</th>
                    <th>Created</th>
                  </tr>
                </thead>
                <tbody>
                  {findings.map((finding) => (
                    <tr key={finding.id}>
                      <td>
                        <strong>{finding.title}</strong>
                        <br />
                        <span className="hint muted">{finding.rule_key}</span>
                      </td>
                      <td>{finding.severity}</td>
                      <td>{finding.category}</td>
                      <td>{finding.finding_type}</td>
                      <td>{finding.gap_direction || "-"}</td>
                      <td>{finding.client_value || "-"}</td>
                      <td>{finding.competitor_value || "-"}</td>
                      <td>{formatDateTime(finding.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          <div className="panel stack">
            <h2>Related Recommendations</h2>
            {relatedError ? <p className="hint error">{relatedError}</p> : null}
            {linkedRecommendationRuns.length === 0 ? (
              <p className="hint muted">
                No recommendation runs are currently linked to this comparison run.
              </p>
            ) : relatedRecommendations.length === 0 ? (
              <>
                <p className="hint muted">
                  Linked recommendation run IDs:{" "}<span className="inline-code-list">
                    {linkedRecommendationRunIds.map((item) => (
                      <code key={item}>{item}</code>
                    ))}
                  </span>
                </p>
                <p className="hint muted">No recommendations were found for the linked recommendation runs.</p>
              </>
            ) : (
              <>
                <p className="hint muted">
                  Linked recommendation run IDs:{" "}<span className="inline-code-list">
                    {linkedRecommendationRunIds.map((item) => (
                      <code key={item}>{item}</code>
                    ))}
                  </span>
                </p>
                <table className="table">
                  <thead>
                    <tr>
                      <th>Title</th>
                      <th>Status</th>
                      <th>Priority</th>
                      <th>Category</th>
                      <th>Recommendation Run</th>
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
                        <td>
                          <Link href={buildRecommendationRunHref(item.recommendation_run_id, item.site_id)}>
                            <code>{item.recommendation_run_id}</code>
                          </Link>
                        </td>
                        <td>{formatDateTime(item.created_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {truncatedRecommendationRunIds.length > 0 ? (
                  <p className="hint muted">
                    Recommendation linkage is currently truncated for run IDs{" "}<span className="inline-code-list">
                      {truncatedRecommendationRunIds.map((item) => (
                        <code key={item}>{item}</code>
                      ))}
                    </span>
                    after the first {RELATED_RECOMMENDATION_PAGE_SIZE} items per run.
                  </p>
                ) : null}
              </>
            )}
          </div>
        </>
      ) : null}
    </PageContainer>
  );
}
