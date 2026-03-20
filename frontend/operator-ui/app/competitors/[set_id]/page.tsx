"use client";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { useOperatorContext } from "../../../components/useOperatorContext";
import {
  ApiRequestError,
  fetchCompetitorComparisonRuns,
  fetchCompetitorDomains,
  fetchCompetitorSet,
  fetchCompetitorSnapshotRuns,
  fetchRecommendations,
} from "../../../lib/api/client";
import type {
  CompetitorComparisonRun,
  CompetitorDomain,
  CompetitorSet,
  CompetitorSnapshotRun,
  Recommendation,
} from "../../../lib/api/types";

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

function formatLocation(city: string | null, state: string | null): string {
  const locationParts = [city, state].filter((part) => Boolean(part && part.trim()));
  if (locationParts.length === 0) {
    return "-";
  }
  return locationParts.join(", ");
}

function safeCompetitorDetailErrorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) {
    if (error.status === 401) {
      return "Session expired. Sign in again.";
    }
    if (error.status === 403) {
      return "You are not authorized to view this competitor set.";
    }
    if (error.status === 404) {
      return "Competitor set was not found in your tenant scope.";
    }
  }
  return "Unable to load competitor set details right now. Please try again.";
}

function safeCompetitorRelatedErrorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) {
    if (error.status === 401) {
      return "Session expired. Sign in again.";
    }
    if (error.status === 403) {
      return "You are not authorized to view one or more related competitor resources.";
    }
    if (error.status === 404) {
      return "Some related competitor resources were not found in your tenant scope.";
    }
  }
  return "Unable to load one or more related competitor resources right now.";
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

export default function CompetitorSetDetailPage() {
  const params = useParams<{ set_id: string }>();
  const searchParams = useSearchParams();
  const competitorSetId = (params?.set_id || "").trim();
  const requestedSiteId = (searchParams.get("site_id") || "").trim();
  const context = useOperatorContext();

  const [competitorSet, setCompetitorSet] = useState<CompetitorSet | null>(null);
  const [domains, setDomains] = useState<CompetitorDomain[]>([]);
  const [snapshotRuns, setSnapshotRuns] = useState<CompetitorSnapshotRun[]>([]);
  const [comparisonRuns, setComparisonRuns] = useState<CompetitorComparisonRun[]>([]);
  const [relatedRecommendations, setRelatedRecommendations] = useState<Recommendation[]>([]);
  const [relatedRecommendationsTruncated, setRelatedRecommendationsTruncated] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [relatedError, setRelatedError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);

  const selectedSiteDisplayName = useMemo(() => {
    if (!competitorSet) {
      return null;
    }
    const match = context.sites.find((site) => site.id === competitorSet.site_id);
    return match?.display_name || null;
  }, [competitorSet, context.sites]);

  const latestComparisonRun = useMemo(() => {
    if (comparisonRuns.length === 0) {
      return null;
    }
    return comparisonRuns[0];
  }, [comparisonRuns]);

  const backToListHref = useMemo(() => {
    const siteId = competitorSet?.site_id || requestedSiteId;
    if (!siteId) {
      return "/competitors";
    }
    const params = new URLSearchParams();
    params.set("site_id", siteId);
    return `/competitors?${params.toString()}`;
  }, [competitorSet?.site_id, requestedSiteId]);

  function buildComparisonRunHref(run: CompetitorComparisonRun): string {
    const params = new URLSearchParams();
    const contextSiteId = competitorSet?.site_id || requestedSiteId || run.site_id;
    const contextSetId = competitorSet?.id || competitorSetId || run.competitor_set_id;
    if (contextSiteId) {
      params.set("site_id", contextSiteId);
    }
    if (contextSetId) {
      params.set("set_id", contextSetId);
    }
    const query = params.toString();
    return query ? `/competitors/comparison-runs/${run.id}?${query}` : `/competitors/comparison-runs/${run.id}`;
  }

  function buildSnapshotRunHref(run: CompetitorSnapshotRun): string {
    const params = new URLSearchParams();
    const contextSiteId = competitorSet?.site_id || requestedSiteId || run.site_id;
    const contextSetId = competitorSet?.id || competitorSetId || run.competitor_set_id;
    if (contextSiteId) {
      params.set("site_id", contextSiteId);
    }
    if (contextSetId) {
      params.set("set_id", contextSetId);
    }
    const query = params.toString();
    return query ? `/competitors/snapshot-runs/${run.id}?${query}` : `/competitors/snapshot-runs/${run.id}`;
  }

  useEffect(() => {
    if (context.loading || context.error || !competitorSetId) {
      setCompetitorSet(null);
      setDomains([]);
      setSnapshotRuns([]);
      setComparisonRuns([]);
      setRelatedRecommendations([]);
      setRelatedRecommendationsTruncated(false);
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
      setCompetitorSet(null);
      setDomains([]);
      setSnapshotRuns([]);
      setComparisonRuns([]);
      setRelatedRecommendations([]);
      setRelatedRecommendationsTruncated(false);

      try {
        const setResult = await fetchCompetitorSet(context.token, context.businessId, competitorSetId);
        if (cancelled) {
          return;
        }
        if (requestedSiteId && setResult.site_id !== requestedSiteId) {
          setNotFound(true);
          return;
        }
        setCompetitorSet(setResult);

        const [domainsResult, snapshotsResult, comparisonsResult] = await Promise.all([
          fetchCompetitorDomains(context.token, context.businessId, setResult.id),
          fetchCompetitorSnapshotRuns(context.token, context.businessId, setResult.id),
          fetchCompetitorComparisonRuns(context.token, context.businessId, setResult.id),
        ]);
        if (cancelled) {
          return;
        }
        setDomains(domainsResult.items);
        setSnapshotRuns(snapshotsResult.items);
        setComparisonRuns(comparisonsResult.items);

        if (comparisonsResult.items.length === 0) {
          return;
        }

        const topComparisonRun = comparisonsResult.items[0];
        try {
          const relatedRecommendationsResult = await fetchRecommendations(
            context.token,
            context.businessId,
            setResult.site_id,
            {
              source_type: "comparison",
              sort_by: "created_at",
              sort_order: "desc",
              page: 1,
              page_size: RELATED_RECOMMENDATION_PAGE_SIZE,
            },
          );
          if (cancelled) {
            return;
          }
          const matchingRecommendations = relatedRecommendationsResult.items
            .filter((item) => item.comparison_run_id === topComparisonRun.id)
            .sort((a, b) => b.priority_score - a.priority_score);
          setRelatedRecommendations(matchingRecommendations);
          setRelatedRecommendationsTruncated(relatedRecommendationsResult.total > relatedRecommendationsResult.items.length);
        } catch (relatedRecommendationsError) {
          if (cancelled) {
            return;
          }
          if (relatedRecommendationsError instanceof ApiRequestError && relatedRecommendationsError.status === 404) {
            return;
          }
          setRelatedError(safeCompetitorRelatedErrorMessage(relatedRecommendationsError));
        }
      } catch (err) {
        if (cancelled) {
          return;
        }
        if (err instanceof ApiRequestError && err.status === 404) {
          setNotFound(true);
          return;
        }
        setError(safeCompetitorDetailErrorMessage(err));
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
  }, [competitorSetId, context.businessId, context.error, context.loading, context.token, requestedSiteId]);

  if (context.loading) {
    return <section className="panel">Loading competitor set detail...</section>;
  }
  if (context.error) {
    return <section className="panel">Unable to load tenant context. Refresh and sign in again.</section>;
  }
  if (!competitorSetId) {
    return (
      <section className="panel stack">
        <h1>Competitor Set Detail</h1>
        <p className="hint warning">Competitor set identifier is missing.</p>
        <p>
          <Link href={backToListHref}>Back to Competitor Sets</Link>
        </p>
      </section>
    );
  }

  return (
    <section className="stack">
      <div className="panel stack">
        <p>
          <Link href={backToListHref}>Back to Competitor Sets</Link>
        </p>
        <h1>Competitor Set Detail</h1>
        <p>
          Competitor Set ID: <code>{competitorSetId}</code>
        </p>

        {loading ? <p className="hint muted">Loading competitor set detail...</p> : null}
        {!loading && notFound ? (
          <p className="hint warning">Competitor set not found or not accessible in your tenant scope.</p>
        ) : null}
        {!loading && error ? <p className="hint error">{error}</p> : null}
      </div>

      {!loading && !notFound && !error && competitorSet ? (
        <>
          <div className="panel stack">
            <h2>Set Context</h2>
            <p>
              Name: <strong>{competitorSet.name}</strong>
            </p>
            <p>
              Business ID: <code>{competitorSet.business_id}</code>
            </p>
            <p>
              Site ID: <code>{competitorSet.site_id}</code>
            </p>
            <p>Site Name: {selectedSiteDisplayName || "-"}</p>
            <p>Location: {formatLocation(competitorSet.city, competitorSet.state)}</p>
            <p>Status: {competitorSet.is_active ? "active" : "inactive"}</p>
            <p>Created By: {competitorSet.created_by_principal_id || "-"}</p>
            <p>Created: {formatDateTime(competitorSet.created_at)}</p>
            <p>Updated: {formatDateTime(competitorSet.updated_at)}</p>
          </div>

          <div className="panel stack">
            <h2>Related SEO Navigation</h2>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "0.75rem" }}>
              <Link href="/sites">View Sites</Link>
              <Link href="/audits">View Audit Runs</Link>
              <Link href="/recommendations">View Recommendation Queue</Link>
            </div>
            <p className="hint muted">
              Recommendation queue and audit views remain site-scoped in the operator context.
            </p>
          </div>

          <div className="panel stack">
            <h2>Competitor Domains ({domains.length})</h2>
            {domains.length === 0 ? (
              <p className="hint muted">No domains are currently attached to this competitor set.</p>
            ) : (
              <table className="table">
                <thead>
                  <tr>
                    <th>Display Name</th>
                    <th>Domain</th>
                    <th>Base URL</th>
                    <th>Source</th>
                    <th>Status</th>
                    <th>Notes</th>
                    <th>Created</th>
                    <th>Updated</th>
                  </tr>
                </thead>
                <tbody>
                  {domains.map((domain) => (
                    <tr key={domain.id}>
                      <td>{domain.display_name || "-"}</td>
                      <td>{domain.domain}</td>
                      <td>{domain.base_url}</td>
                      <td>{domain.source || "-"}</td>
                      <td>{domain.is_active ? "active" : "inactive"}</td>
                      <td>{domain.notes || "-"}</td>
                      <td>{formatDateTime(domain.created_at)}</td>
                      <td>{formatDateTime(domain.updated_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          <div className="panel stack">
            <h2>Snapshot Runs ({snapshotRuns.length})</h2>
            {snapshotRuns.length === 0 ? (
              <p className="hint muted">No snapshot runs have been recorded for this competitor set.</p>
            ) : (
              <>
                <p className="hint muted">
                  Open a run ID to inspect captured-page context and related comparisons.
                </p>
                <table className="table">
                  <thead>
                    <tr>
                      <th>Run ID</th>
                      <th>Status</th>
                      <th>Client Audit Run</th>
                      <th>Domains Targeted</th>
                      <th>Domains Completed</th>
                      <th>Pages Captured</th>
                      <th>Errors</th>
                      <th>Created</th>
                      <th>Updated</th>
                    </tr>
                  </thead>
                  <tbody>
                    {snapshotRuns.map((run) => (
                      <tr key={run.id}>
                        <td>
                          <Link href={buildSnapshotRunHref(run)}>
                            <code>{run.id}</code>
                          </Link>
                        </td>
                        <td>{run.status}</td>
                        <td>
                          {run.client_audit_run_id ? (
                            <Link href={`/audits/${run.client_audit_run_id}`}>
                              <code>{run.client_audit_run_id}</code>
                            </Link>
                          ) : (
                            "-"
                          )}
                        </td>
                        <td>{run.domains_targeted}</td>
                        <td>{run.domains_completed}</td>
                        <td>{run.pages_captured}</td>
                        <td>{run.errors_encountered}</td>
                        <td>{formatDateTime(run.created_at)}</td>
                        <td>{formatDateTime(run.updated_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
          </div>

          <div className="panel stack">
            <h2>Comparison Runs ({comparisonRuns.length})</h2>
            {comparisonRuns.length === 0 ? (
              <p className="hint muted">No comparison runs have been recorded for this competitor set.</p>
            ) : (
              <>
                <p className="hint muted">Open a run ID to inspect detailed findings, metrics, and linked records.</p>
                <table className="table">
                  <thead>
                    <tr>
                      <th>Run ID</th>
                      <th>Status</th>
                      <th>Severity</th>
                      <th>Baseline Audit</th>
                      <th>Total Findings</th>
                      <th>Client Pages</th>
                      <th>Competitor Pages</th>
                      <th>Created</th>
                      <th>Updated</th>
                    </tr>
                  </thead>
                  <tbody>
                    {comparisonRuns.map((run) => (
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
                        <td>{run.client_pages_analyzed}</td>
                        <td>{run.competitor_pages_analyzed}</td>
                        <td>{formatDateTime(run.created_at)}</td>
                        <td>{formatDateTime(run.updated_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
          </div>

          <div className="panel stack">
            <h2>Related Recommendations</h2>
            {relatedError ? <p className="hint error">{relatedError}</p> : null}
            {!latestComparisonRun ? (
              <p className="hint muted">No comparison run is available yet to correlate recommendations.</p>
            ) : relatedRecommendations.length === 0 ? (
              <p className="hint muted">
                No recommendations are currently linked to the latest comparison run.
              </p>
            ) : (
              <>
                <p className="hint muted">
                  Showing recommendations linked to comparison run <code>{latestComparisonRun.id}</code>.
                </p>
                <table className="table">
                  <thead>
                    <tr>
                      <th>Title</th>
                      <th>Status</th>
                      <th>Priority</th>
                      <th>Category</th>
                      <th>Created</th>
                    </tr>
                  </thead>
                  <tbody>
                    {relatedRecommendations.map((item) => (
                      <tr key={item.id}>
                        <td>
                          <Link href={`/recommendations/${item.id}?site_id=${encodeURIComponent(item.site_id)}`}>
                            {item.title}
                          </Link>
                        </td>
                        <td>{item.status}</td>
                        <td>
                          {item.priority_score} ({item.priority_band})
                        </td>
                        <td>{item.category}</td>
                        <td>{formatDateTime(item.created_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {relatedRecommendationsTruncated ? (
                  <p className="hint muted">
                    Related recommendation correlation is currently based on the first{" "}
                    {RELATED_RECOMMENDATION_PAGE_SIZE} comparison-sourced recommendations for this site.
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
