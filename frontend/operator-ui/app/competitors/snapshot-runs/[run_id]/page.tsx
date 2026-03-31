"use client";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { PageContainer } from "../../../../components/layout/PageContainer";
import { SectionCard } from "../../../../components/layout/SectionCard";
import { SectionHeader } from "../../../../components/layout/SectionHeader";
import { SummaryStatCard } from "../../../../components/layout/SummaryStatCard";
import { WorkflowContextPanel } from "../../../../components/layout/WorkflowContextPanel";
import { useOperatorContext } from "../../../../components/useOperatorContext";
import {
  ApiRequestError,
  fetchCompetitorComparisonRuns,
  fetchCompetitorDomains,
  fetchCompetitorSnapshotPages,
  fetchCompetitorSnapshotRun,
  fetchRecommendationRuns,
  fetchRecommendations,
} from "../../../../lib/api/client";
import type {
  CompetitorComparisonRun,
  CompetitorDomain,
  CompetitorSnapshotPage,
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

function safeSnapshotRunErrorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) {
    if (error.status === 401) {
      return "Session expired. Sign in again.";
    }
    if (error.status === 403) {
      return "You are not authorized to view this snapshot run.";
    }
    if (error.status === 404) {
      return "Snapshot run was not found in your tenant scope.";
    }
  }
  return "Unable to load snapshot run details right now. Please try again.";
}

function safeSnapshotRelatedErrorMessage(error: unknown): string {
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

function deriveComparisonSeverity(run: CompetitorComparisonRun): string {
  if (run.critical_findings > 0) {
    return "critical";
  }
  if (run.warning_findings > 0) {
    return "warning";
  }
  if (run.total_findings > 0) {
    return "info";
  }
  return "none";
}

export default function SnapshotRunDetailPage() {
  const params = useParams<{ run_id: string }>();
  const searchParams = useSearchParams();
  const snapshotRunId = (params?.run_id || "").trim();
  const requestedSetId = (searchParams.get("set_id") || "").trim();
  const requestedSiteId = (searchParams.get("site_id") || "").trim();
  const context = useOperatorContext();

  const [snapshotRun, setSnapshotRun] = useState<CompetitorSnapshotRun | null>(null);
  const [capturedPages, setCapturedPages] = useState<CompetitorSnapshotPage[]>([]);
  const [domainsById, setDomainsById] = useState<Record<string, CompetitorDomain>>({});
  const [relatedComparisonRuns, setRelatedComparisonRuns] = useState<CompetitorComparisonRun[]>([]);
  const [linkedRecommendationRuns, setLinkedRecommendationRuns] = useState<RecommendationRun[]>([]);
  const [relatedRecommendations, setRelatedRecommendations] = useState<Recommendation[]>([]);
  const [truncatedRecommendationRunIds, setTruncatedRecommendationRunIds] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [relatedError, setRelatedError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);

  const selectedSiteDisplayName = useMemo(() => {
    if (!snapshotRun) {
      return null;
    }
    const match = context.sites.find((site) => site.id === snapshotRun.site_id);
    return match?.display_name || null;
  }, [context.sites, snapshotRun]);

  const backToListHref = useMemo(() => {
    const siteId = snapshotRun?.site_id || requestedSiteId;
    if (!siteId) {
      return "/competitors";
    }
    const params = new URLSearchParams();
    params.set("site_id", siteId);
    return `/competitors?${params.toString()}`;
  }, [requestedSiteId, snapshotRun?.site_id]);

  const backToSetHref = useMemo(() => {
    const parentSetId = snapshotRun?.competitor_set_id || requestedSetId;
    const parentSiteId = snapshotRun?.site_id || requestedSiteId;
    if (!parentSetId) {
      return backToListHref;
    }
    const query = new URLSearchParams();
    if (parentSiteId) {
      query.set("site_id", parentSiteId);
    }
    const queryText = query.toString();
    return queryText ? `/competitors/${parentSetId}?${queryText}` : `/competitors/${parentSetId}`;
  }, [backToListHref, requestedSetId, requestedSiteId, snapshotRun]);

  const buildComparisonRunHref = useCallback((run: CompetitorComparisonRun): string => {
    const params = new URLSearchParams();
    const contextSiteId = snapshotRun?.site_id || requestedSiteId || run.site_id;
    const contextSetId = snapshotRun?.competitor_set_id || requestedSetId || run.competitor_set_id;
    if (contextSiteId) {
      params.set("site_id", contextSiteId);
    }
    if (contextSetId) {
      params.set("set_id", contextSetId);
    }
    const query = params.toString();
    return query ? `/competitors/comparison-runs/${run.id}?${query}` : `/competitors/comparison-runs/${run.id}`;
  }, [requestedSetId, requestedSiteId, snapshotRun?.competitor_set_id, snapshotRun?.site_id]);

  const capturedPageTotal = capturedPages.length;
  const linkedRecommendationRunIds = linkedRecommendationRuns.map((item) => item.id);
  const relatedComparisonRunIds = relatedComparisonRuns.map((item) => item.id);

  const workflowContextLinks = useMemo(() => {
    const links: Array<{ href: string; label: string }> = [
      { href: backToListHref, label: "Competitor Sets" },
      { href: backToSetHref, label: "Parent Competitor Set" },
      { href: "/recommendations", label: "Recommendation Queue" },
      { href: "/audits", label: "Audit Runs" },
    ];
    if (snapshotRun?.client_audit_run_id) {
      links.push({ href: `/audits/${snapshotRun.client_audit_run_id}`, label: "Client Audit Run" });
    }
    if (relatedComparisonRuns.length > 0) {
      links.push({ href: buildComparisonRunHref(relatedComparisonRuns[0]), label: "Top linked comparison run" });
    }
    if (linkedRecommendationRuns.length > 0) {
      const topRun = linkedRecommendationRuns[0];
      links.push({ href: buildRecommendationRunHref(topRun.id, topRun.site_id), label: "Top linked recommendation run" });
    }
    return links;
  }, [
    backToListHref,
    backToSetHref,
    buildComparisonRunHref,
    linkedRecommendationRuns,
    relatedComparisonRuns,
    snapshotRun,
  ]);

  const workflowNextStep = useMemo(() => {
    if (relatedComparisonRuns.length > 0) {
      return {
        href: buildComparisonRunHref(relatedComparisonRuns[0]),
        label: "Review linked comparison findings",
        note: "Validate comparative gaps before recommendation review.",
      };
    }
    if (linkedRecommendationRuns.length > 0) {
      const topRun = linkedRecommendationRuns[0];
      return {
        href: buildRecommendationRunHref(topRun.id, topRun.site_id),
        label: "Review linked recommendation run",
        note: "Inspect recommendation outputs tied to this snapshot lineage.",
      };
    }
    return {
      href: backToSetHref,
      label: "Return to parent competitor set",
      note: "Snapshot context is ready for additional comparison runs when needed.",
    };
  }, [backToSetHref, buildComparisonRunHref, linkedRecommendationRuns, relatedComparisonRuns]);

  useEffect(() => {
    if (context.loading || context.error || !snapshotRunId) {
      setSnapshotRun(null);
      setCapturedPages([]);
      setDomainsById({});
      setRelatedComparisonRuns([]);
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
      setSnapshotRun(null);
      setCapturedPages([]);
      setDomainsById({});
      setRelatedComparisonRuns([]);
      setLinkedRecommendationRuns([]);
      setRelatedRecommendations([]);
      setTruncatedRecommendationRunIds([]);

      try {
        const runResult = await fetchCompetitorSnapshotRun(context.token, context.businessId, snapshotRunId);
        if (cancelled) {
          return;
        }
        if (requestedSetId && runResult.competitor_set_id !== requestedSetId) {
          setNotFound(true);
          return;
        }
        if (requestedSiteId && runResult.site_id !== requestedSiteId) {
          setNotFound(true);
          return;
        }
        setSnapshotRun(runResult);

        let nextCapturedPages: CompetitorSnapshotPage[] = [];
        let nextDomainsById: Record<string, CompetitorDomain> = {};
        let nextRelatedComparisonRuns: CompetitorComparisonRun[] = [];

        const [pagesResult, domainsResult, comparisonsResult] = await Promise.allSettled([
          fetchCompetitorSnapshotPages(context.token, context.businessId, runResult.id),
          fetchCompetitorDomains(context.token, context.businessId, runResult.competitor_set_id),
          fetchCompetitorComparisonRuns(context.token, context.businessId, runResult.competitor_set_id),
        ]);
        if (cancelled) {
          return;
        }

        const relatedErrors: unknown[] = [];
        if (pagesResult.status === "fulfilled") {
          nextCapturedPages = pagesResult.value.items;
          setCapturedPages(nextCapturedPages);
        } else {
          relatedErrors.push(pagesResult.reason);
        }
        if (domainsResult.status === "fulfilled") {
          nextDomainsById = Object.fromEntries(
            domainsResult.value.items.map((domain) => [domain.id, domain] as const),
          );
          setDomainsById(nextDomainsById);
        } else {
          relatedErrors.push(domainsResult.reason);
        }
        if (comparisonsResult.status === "fulfilled") {
          nextRelatedComparisonRuns = comparisonsResult.value.items.filter(
            (item) => item.snapshot_run_id === runResult.id,
          );
          setRelatedComparisonRuns(nextRelatedComparisonRuns);
        } else {
          relatedErrors.push(comparisonsResult.reason);
        }
        if (relatedErrors.length > 0) {
          setRelatedError(safeSnapshotRelatedErrorMessage(relatedErrors[0]));
        }

        const relatedComparisonIdSet = new Set(nextRelatedComparisonRuns.map((item) => item.id));
        if (relatedComparisonIdSet.size === 0) {
          return;
        }

        try {
          const recommendationRunsResult = await fetchRecommendationRuns(
            context.token,
            context.businessId,
            runResult.site_id,
          );
          if (cancelled) {
            return;
          }
          const matchingRecommendationRuns = recommendationRunsResult.items.filter(
            (item) => Boolean(item.comparison_run_id) && relatedComparisonIdSet.has(item.comparison_run_id as string),
          );
          setLinkedRecommendationRuns(matchingRecommendationRuns);

          if (matchingRecommendationRuns.length === 0) {
            return;
          }

          const recommendationResponses = await Promise.all(
            matchingRecommendationRuns.map(async (item) => {
              const response = await fetchRecommendations(
                context.token,
                context.businessId,
                runResult.site_id,
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
          if (relatedRecommendationsError instanceof ApiRequestError && relatedRecommendationsError.status === 404) {
            return;
          }
          setRelatedError(safeSnapshotRelatedErrorMessage(relatedRecommendationsError));
        }
      } catch (err) {
        if (cancelled) {
          return;
        }
        if (err instanceof ApiRequestError && err.status === 404) {
          setNotFound(true);
          return;
        }
        setError(safeSnapshotRunErrorMessage(err));
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
    context.businessId,
    context.error,
    context.loading,
    context.token,
    requestedSetId,
    requestedSiteId,
    snapshotRunId,
  ]);

  if (context.loading) {
    return (
      <PageContainer>
        <SectionCard as="div" variant="support" className="role-surface-support">
          <SectionHeader
            title="Snapshot Run Detail"
            subtitle="Loading competitor snapshot run detail."
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
            title="Snapshot Run Detail"
            subtitle="Unable to load tenant context. Refresh and sign in again."
            headingLevel={1}
            variant="support"
          />
        </SectionCard>
      </PageContainer>
    );
  }
  if (!snapshotRunId) {
    return (
      <PageContainer>
        <SectionCard variant="support" className="role-surface-support">
          <SectionHeader
            title="Snapshot Run Detail"
            subtitle="Snapshot run identifier is missing."
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
            title="Snapshot Run Detail"
            subtitle="Inspect captured competitor pages, linked comparison runs, and recommendation lineage."
            headingLevel={1}
            variant="hero"
            meta={<span className="hint muted">Snapshot run: <code>{snapshotRunId}</code></span>}
            actions={<Link href={backToSetHref}>Back to Competitor Set</Link>}
          />
          <div className="workspace-summary-strip role-summary-strip">
            <SummaryStatCard
              label="Run status"
              value={snapshotRun?.status || "Loading"}
              detail="Snapshot execution state"
              tone={snapshotRun?.status?.toLowerCase() === "completed" ? "success" : snapshotRun?.status?.toLowerCase() === "failed" ? "danger" : "warning"}
              variant="elevated"
            />
            <SummaryStatCard
              label="Captured pages"
              value={capturedPageTotal}
              detail="Pages captured in this snapshot"
              tone={capturedPageTotal > 0 ? "success" : "warning"}
              variant="elevated"
            />
            <SummaryStatCard
              label="Related comparisons"
              value={relatedComparisonRuns.length}
              detail="Comparison runs from this snapshot"
              tone={relatedComparisonRuns.length > 0 ? "neutral" : "warning"}
              variant="elevated"
            />
            <SummaryStatCard
              label="Related recommendations"
              value={relatedRecommendations.length}
              detail="Recommendations linked through lineage"
              tone={relatedRecommendations.length > 0 ? "neutral" : "warning"}
              variant="elevated"
            />
          </div>
          {loading ? <p className="hint muted">Loading snapshot run detail...</p> : null}
          {!loading && notFound ? (
            <p className="hint warning">Snapshot run not found or not accessible in your tenant scope.</p>
          ) : null}
          {!loading && error ? <p className="hint error">{error}</p> : null}
        </SectionCard>
      </div>

      {!loading && !notFound && !error && snapshotRun ? (
        <WorkflowContextPanel
          data-testid="snapshot-run-workflow-context"
          lineage="Competitors → Snapshot run → Comparison runs → Recommendation linkage"
          links={workflowContextLinks}
          nextStep={workflowNextStep}
        />
      ) : null}

      {!loading && !notFound && !error && snapshotRun ? (
        <>
          <div className="panel stack">
            <h2>Run Context</h2>
            <p>
              Business ID: <code>{snapshotRun.business_id}</code>
            </p>
            <p>
              Site ID: <code>{snapshotRun.site_id}</code>
              {selectedSiteDisplayName ? <> ({selectedSiteDisplayName})</> : null}
            </p>
            <p>
              Competitor Set ID:{" "}
              <Link href={backToSetHref}>
                <code>{snapshotRun.competitor_set_id}</code>
              </Link>
            </p>
            <p>Status: {snapshotRun.status}</p>
            <p>Created By: {snapshotRun.created_by_principal_id || "-"}</p>
            <p>Started: {formatDateTime(snapshotRun.started_at)}</p>
            <p>Completed: {formatDateTime(snapshotRun.completed_at)}</p>
            <p>Duration (ms): {snapshotRun.duration_ms ?? "-"}</p>
            <p>Created: {formatDateTime(snapshotRun.created_at)}</p>
            <p>Updated: {formatDateTime(snapshotRun.updated_at)}</p>
            <p>Error Summary: {snapshotRun.error_summary || "-"}</p>
          </div>

          <div className="panel stack">
            <h2>Snapshot Metrics</h2>
            <table className="table">
              <tbody>
                <tr>
                  <th>Domains Targeted</th>
                  <td>{snapshotRun.domains_targeted}</td>
                </tr>
                <tr>
                  <th>Domains Completed</th>
                  <td>{snapshotRun.domains_completed}</td>
                </tr>
                <tr>
                  <th>Pages Attempted</th>
                  <td>{snapshotRun.pages_attempted}</td>
                </tr>
                <tr>
                  <th>Pages Captured</th>
                  <td>{snapshotRun.pages_captured}</td>
                </tr>
                <tr>
                  <th>Pages Skipped</th>
                  <td>{snapshotRun.pages_skipped}</td>
                </tr>
                <tr>
                  <th>Errors Encountered</th>
                  <td>{snapshotRun.errors_encountered}</td>
                </tr>
                <tr>
                  <th>Max Domains</th>
                  <td>{snapshotRun.max_domains}</td>
                </tr>
                <tr>
                  <th>Max Pages Per Domain</th>
                  <td>{snapshotRun.max_pages_per_domain}</td>
                </tr>
                <tr>
                  <th>Max Depth</th>
                  <td>{snapshotRun.max_depth}</td>
                </tr>
                <tr>
                  <th>Same Domain Only</th>
                  <td>{snapshotRun.same_domain_only ? "yes" : "no"}</td>
                </tr>
              </tbody>
            </table>
          </div>

          <div className="panel stack">
            <h2>Related Workflow Scope</h2>
            <p className="hint muted">
              Workflow context links above keep snapshot, comparison, and recommendation lineage routes connected.
            </p>
          </div>

          <div className="panel stack">
            <h2>Captured Pages ({capturedPageTotal})</h2>
            {relatedError ? <p className="hint error">{relatedError}</p> : null}
            {capturedPages.length === 0 ? (
              <p className="hint muted">No captured pages are currently available for this snapshot run.</p>
            ) : (
              <table className="table">
                <thead>
                  <tr>
                    <th>Domain</th>
                    <th>Base URL</th>
                    <th>URL</th>
                    <th>Status Code</th>
                    <th>Title</th>
                    <th>Word Count</th>
                    <th>Internal Links</th>
                    <th>H1 Count</th>
                    <th>Fetched</th>
                    <th>Error</th>
                  </tr>
                </thead>
                <tbody>
                  {capturedPages.map((page) => {
                    const domain = domainsById[page.competitor_domain_id];
                    return (
                      <tr key={page.id}>
                        <td>{domain?.display_name || domain?.domain || page.competitor_domain_id}</td>
                        <td>{domain?.base_url || "-"}</td>
                        <td>{page.url}</td>
                        <td>{page.status_code ?? "-"}</td>
                        <td>{page.title || "-"}</td>
                        <td>{page.word_count ?? "-"}</td>
                        <td>{page.internal_link_count ?? "-"}</td>
                        <td>{page.h1_json?.length ?? "-"}</td>
                        <td>{formatDateTime(page.fetched_at)}</td>
                        <td>{page.error_summary || "-"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>

          <div className="panel stack">
            <h2>Related Comparison Runs ({relatedComparisonRuns.length})</h2>
            {relatedComparisonRuns.length === 0 ? (
              <p className="hint muted">
                No comparison runs are currently linked to this snapshot run.
              </p>
            ) : (
              <table className="table">
                <thead>
                  <tr>
                    <th>Run ID</th>
                    <th>Status</th>
                    <th>Severity</th>
                    <th>Baseline Audit</th>
                    <th>Total Findings</th>
                    <th>Created</th>
                  </tr>
                </thead>
                <tbody>
                  {relatedComparisonRuns.map((run) => (
                    <tr key={run.id}>
                      <td>
                        <Link href={buildComparisonRunHref(run)}>
                          <code>{run.id}</code>
                        </Link>
                      </td>
                      <td>{run.status}</td>
                      <td>{deriveComparisonSeverity(run)}</td>
                      <td>
                        {run.baseline_audit_run_id ? (
                          <Link href={`/audits/${run.baseline_audit_run_id}`}>
                            <code>{run.baseline_audit_run_id}</code>
                          </Link>
                        ) : (
                          "-"
                        )}
                      </td>
                      <td>{run.total_findings}</td>
                      <td>{formatDateTime(run.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          <div className="panel stack">
            <h2>Related Recommendations</h2>
            {relatedComparisonRuns.length === 0 ? (
              <p className="hint muted">
                Recommendation linkage requires at least one related comparison run.
              </p>
            ) : linkedRecommendationRuns.length === 0 ? (
              <>
                <p className="hint muted">
                  Linked comparison run IDs:{" "}<span className="inline-code-list">
                    {relatedComparisonRunIds.map((item) => (
                      <code key={item}>{item}</code>
                    ))}
                  </span>
                </p>
                <p className="hint muted">
                  No recommendation runs are currently linked to this snapshot run lineage.
                </p>
              </>
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
