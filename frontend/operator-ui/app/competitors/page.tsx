"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";

import { PageContainer } from "../../components/layout/PageContainer";
import { OperationalItemCard } from "../../components/layout/OperationalItemCard";
import { SectionCard } from "../../components/layout/SectionCard";
import { SectionHeader } from "../../components/layout/SectionHeader";
import { SummaryStatCard } from "../../components/layout/SummaryStatCard";
import { useOperatorContext } from "../../components/useOperatorContext";
import {
  ApiRequestError,
  fetchCompetitorDomains,
  fetchCompetitorSets,
  fetchCompetitorSnapshotRuns,
  fetchSiteCompetitorComparisonRuns,
} from "../../lib/api/client";
import type {
  CompetitorSet,
  CompetitorSnapshotRun,
} from "../../lib/api/types";

interface CompetitorSetRow extends CompetitorSet {
  domain_count: number;
  active_domain_count: number;
  source_summary: string;
  latest_domain_updated_at: string | null;
  latest_snapshot_status: string | null;
}

interface LatestSiteRun {
  id: string;
  competitor_set_id: string;
  competitor_set_name: string;
  status: string;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

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

function safeCompetitorErrorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) {
    if (error.status === 401) {
      return "Session expired. Sign in again.";
    }
    if (error.status === 403) {
      return "You are not authorized to view competitor data.";
    }
    if (error.status === 404) {
      return "Competitor data for the selected site was not found.";
    }
  }
  return "Unable to load competitors right now. Please try again.";
}

function runActivityTimestamp(
  run: Pick<LatestSiteRun, "completed_at" | "updated_at" | "created_at">,
): number {
  const activityAt = run.completed_at || run.updated_at || run.created_at;
  const parsed = Date.parse(activityAt);
  return Number.isNaN(parsed) ? 0 : parsed;
}

function latestByActivity<T extends Pick<LatestSiteRun, "completed_at" | "updated_at" | "created_at">>(
  runs: T[],
): T | null {
  if (runs.length === 0) {
    return null;
  }
  let latest = runs[0];
  let latestTimestamp = runActivityTimestamp(latest);
  for (let index = 1; index < runs.length; index += 1) {
    const candidate = runs[index];
    const candidateTimestamp = runActivityTimestamp(candidate);
    if (candidateTimestamp > latestTimestamp) {
      latest = candidate;
      latestTimestamp = candidateTimestamp;
    }
  }
  return latest;
}

function formatRunStatus(status: string): string {
  const cleaned = status.trim();
  return cleaned || "unknown";
}

function CompetitorsPageContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const context = useOperatorContext();
  const {
    loading: contextLoading,
    error: contextError,
    token,
    businessId,
    sites,
    selectedSiteId,
    setSelectedSiteId,
  } = context;
  const requestedSiteId = (searchParams.get("site_id") || "").trim();
  const [competitorSets, setCompetitorSets] = useState<CompetitorSetRow[]>([]);
  const [loadingCompetitors, setLoadingCompetitors] = useState(false);
  const [competitorsError, setCompetitorsError] = useState<string | null>(null);
  const [competitorSetCount, setCompetitorSetCount] = useState(0);
  const [latestSnapshotRun, setLatestSnapshotRun] = useState<LatestSiteRun | null>(null);
  const [latestComparisonRun, setLatestComparisonRun] = useState<LatestSiteRun | null>(null);
  const [readinessWarning, setReadinessWarning] = useState<string | null>(null);

  const totalDomainCount = useMemo(
    () => competitorSets.reduce((total, item) => total + item.domain_count, 0),
    [competitorSets],
  );
  const activeSetCount = useMemo(
    () => competitorSets.filter((item) => item.is_active).length,
    [competitorSets],
  );
  const activeDomainCount = useMemo(
    () => competitorSets.reduce((total, item) => total + item.active_domain_count, 0),
    [competitorSets],
  );
  const selectedSite = useMemo(
    () => sites.find((site) => site.id === selectedSiteId) || null,
    [selectedSiteId, sites],
  );

  function buildSetDetailHref(setItem: CompetitorSetRow): string {
    const params = new URLSearchParams();
    params.set("site_id", setItem.site_id);
    return `/competitors/${setItem.id}?${params.toString()}`;
  }

  function buildSnapshotRunHref(run: LatestSiteRun): string {
    const params = new URLSearchParams();
    params.set("set_id", run.competitor_set_id);
    if (selectedSiteId) {
      params.set("site_id", selectedSiteId);
    }
    return `/competitors/snapshot-runs/${run.id}?${params.toString()}`;
  }

  function buildComparisonRunHref(run: LatestSiteRun): string {
    const params = new URLSearchParams();
    params.set("set_id", run.competitor_set_id);
    if (selectedSiteId) {
      params.set("site_id", selectedSiteId);
    }
    return `/competitors/comparison-runs/${run.id}?${params.toString()}`;
  }

  const readinessGuidance = useMemo(() => {
    if (contextLoading || loadingCompetitors) {
      return "Loading competitor readiness for this site.";
    }
    if (contextError || competitorsError) {
      return "Competitor readiness is temporarily unavailable due to a data-loading issue.";
    }
    if (!selectedSiteId) {
      return "No site is currently selected.";
    }
    if (competitorSetCount === 0) {
      return "This site has no competitor sets configured yet.";
    }
    if (totalDomainCount === 0) {
      return "Competitor sets exist, but no competitor domains are configured yet.";
    }
    if (!latestSnapshotRun) {
      return "Competitor domains exist, but no snapshot run has been recorded yet.";
    }
    if (formatRunStatus(latestSnapshotRun.status).toLowerCase() !== "completed") {
      return `Latest snapshot run is ${formatRunStatus(latestSnapshotRun.status)}. Comparison results may not be available yet.`;
    }
    if (!latestComparisonRun) {
      return "Snapshot results exist, but no comparison run has been recorded yet.";
    }
    if (formatRunStatus(latestComparisonRun.status).toLowerCase() !== "completed") {
      return `Latest comparison run is ${formatRunStatus(latestComparisonRun.status)}. Findings may still be in progress.`;
    }
    return "This site has configured competitor data and recent comparison activity.";
  }, [
    competitorSetCount,
    competitorsError,
    contextError,
    contextLoading,
    latestComparisonRun,
    latestSnapshotRun,
    loadingCompetitors,
    selectedSiteId,
    totalDomainCount,
  ]);

  const tableEmptyReason = useMemo(() => {
    if (competitorsError) {
      return "Competitor data is currently unavailable for this site.";
    }
    if (!selectedSiteId) {
      return "No site is selected. Choose a site to inspect competitors.";
    }
    if (competitorSetCount === 0) {
      return "This site has no competitor sets configured yet.";
    }
    return "Competitor sets are configured, but none are currently visible.";
  }, [competitorSetCount, competitorsError, selectedSiteId]);

  useEffect(() => {
    if (contextLoading || contextError || !requestedSiteId) {
      return;
    }
    const requestedSiteExists = sites.some((site) => site.id === requestedSiteId);
    if (!requestedSiteExists) {
      return;
    }
    if (selectedSiteId !== requestedSiteId) {
      setSelectedSiteId(requestedSiteId);
    }
  }, [
    contextError,
    contextLoading,
    requestedSiteId,
    selectedSiteId,
    setSelectedSiteId,
    sites,
  ]);

  useEffect(() => {
    if (contextLoading || contextError || !selectedSiteId) {
      setCompetitorSets([]);
      setCompetitorSetCount(0);
      setLatestSnapshotRun(null);
      setLatestComparisonRun(null);
      setReadinessWarning(null);
      setCompetitorsError(null);
      setLoadingCompetitors(false);
      return;
    }
    let cancelled = false;
    const activeSiteId = selectedSiteId;

    async function loadCompetitors() {
      setLoadingCompetitors(true);
      setCompetitorsError(null);
      setLatestSnapshotRun(null);
      setLatestComparisonRun(null);
      setReadinessWarning(null);
      try {
        const setResponse = await fetchCompetitorSets(token, businessId, activeSiteId);
        if (cancelled) {
          return;
        }

        setCompetitorSetCount(setResponse.total);
        if (setResponse.items.length === 0) {
          setCompetitorSets([]);
          return;
        }

        let snapshotStatusUnavailable = false;
        const setNameById = new Map<string, string>();
        for (const setItem of setResponse.items) {
          setNameById.set(setItem.id, setItem.name);
        }

        const setDetails = await Promise.all(
          setResponse.items.map(async (setItem) => {
            const domainsResponse = await fetchCompetitorDomains(
              token,
              businessId,
              setItem.id,
            );
            let latestSnapshotCandidate: CompetitorSnapshotRun | null = null;
            try {
              const snapshotRunsResponse = await fetchCompetitorSnapshotRuns(
                token,
                businessId,
                setItem.id,
              );
              latestSnapshotCandidate = latestByActivity(snapshotRunsResponse.items);
            } catch {
              snapshotStatusUnavailable = true;
            }
            const sourceSet = new Set<string>();
            let latestDomainUpdatedAt: string | null = null;
            let activeDomainCount = 0;

            for (const domain of domainsResponse.items) {
              if (domain.source.trim()) {
                sourceSet.add(domain.source.trim());
              }
              if (domain.is_active) {
                activeDomainCount += 1;
              }
              if (!latestDomainUpdatedAt || domain.updated_at > latestDomainUpdatedAt) {
                latestDomainUpdatedAt = domain.updated_at;
              }
            }

            return {
              row: {
                ...setItem,
                domain_count: domainsResponse.total,
                active_domain_count: activeDomainCount,
                source_summary: sourceSet.size > 0 ? [...sourceSet].sort().join(", ") : "-",
                latest_domain_updated_at: latestDomainUpdatedAt,
                latest_snapshot_status: latestSnapshotCandidate ? latestSnapshotCandidate.status : null,
              },
              latestSnapshotCandidate,
            };
          }),
        );

        const rows = setDetails.map((item) => item.row);
        let nextLatestSnapshotRun: LatestSiteRun | null = null;
        let nextLatestComparisonRun: LatestSiteRun | null = null;
        let nextReadinessWarning: string | null = null;
        const latestSnapshotCandidate = latestByActivity(
          setDetails
            .map((item) => item.latestSnapshotCandidate)
            .filter((item): item is CompetitorSnapshotRun => item !== null),
        );
        if (latestSnapshotCandidate) {
          nextLatestSnapshotRun = {
            id: latestSnapshotCandidate.id,
            competitor_set_id: latestSnapshotCandidate.competitor_set_id,
            competitor_set_name:
              setNameById.get(latestSnapshotCandidate.competitor_set_id) ||
              latestSnapshotCandidate.competitor_set_id,
            status: latestSnapshotCandidate.status,
            created_at: latestSnapshotCandidate.created_at,
            updated_at: latestSnapshotCandidate.updated_at,
            completed_at: latestSnapshotCandidate.completed_at,
          };
        }

        let comparisonStatusUnavailable = false;
        try {
          const comparisonRunsResponse = await fetchSiteCompetitorComparisonRuns(
            token,
            businessId,
            activeSiteId,
          );
          const latestComparisonCandidate = latestByActivity(comparisonRunsResponse.items);
          if (latestComparisonCandidate) {
            nextLatestComparisonRun = {
              id: latestComparisonCandidate.id,
              competitor_set_id: latestComparisonCandidate.competitor_set_id,
              competitor_set_name:
                setNameById.get(latestComparisonCandidate.competitor_set_id) ||
                latestComparisonCandidate.competitor_set_id,
              status: latestComparisonCandidate.status,
              created_at: latestComparisonCandidate.created_at,
              updated_at: latestComparisonCandidate.updated_at,
              completed_at: latestComparisonCandidate.completed_at,
            };
          }
        } catch {
          comparisonStatusUnavailable = true;
        }

        if (snapshotStatusUnavailable && comparisonStatusUnavailable) {
          nextReadinessWarning = "Snapshot and comparison run status are temporarily unavailable.";
        } else if (snapshotStatusUnavailable) {
          nextReadinessWarning = "Snapshot run status is temporarily unavailable.";
        } else if (comparisonStatusUnavailable) {
          nextReadinessWarning = "Comparison run status is temporarily unavailable.";
        }

        if (!cancelled) {
          setLatestSnapshotRun(nextLatestSnapshotRun);
          setLatestComparisonRun(nextLatestComparisonRun);
          setReadinessWarning(nextReadinessWarning);
          setCompetitorSets(rows);
        }
      } catch (err) {
        if (!cancelled) {
          setCompetitorsError(safeCompetitorErrorMessage(err));
        }
      } finally {
        if (!cancelled) {
          setLoadingCompetitors(false);
        }
      }
    }
    void loadCompetitors();
    return () => {
      cancelled = true;
    };
  }, [businessId, contextError, contextLoading, selectedSiteId, token]);

  if (contextLoading) {
    return (
      <PageContainer width="wide" density="compact">
        <SectionCard as="div" variant="support" className="role-surface-support">
          <SectionHeader
            title="Competitor Intelligence"
            subtitle="Loading competitor set readiness for your selected site."
            headingLevel={1}
            variant="support"
          />
        </SectionCard>
      </PageContainer>
    );
  }
  if (contextError) {
    return (
      <PageContainer width="wide" density="compact">
        <SectionCard as="div" variant="support" className="role-surface-support">
          <SectionHeader
            title="Competitor Intelligence"
            subtitle="Unable to load tenant context. Refresh and sign in again."
            headingLevel={1}
            variant="support"
          />
        </SectionCard>
      </PageContainer>
    );
  }
  if (sites.length === 0) {
    return (
      <PageContainer width="wide" density="compact">
        <SectionCard variant="support" className="role-surface-support">
          <SectionHeader
            title="Competitor Intelligence"
            subtitle="No SEO sites are configured yet. Add a site first to view competitors."
            headingLevel={1}
            variant="support"
          />
        </SectionCard>
      </PageContainer>
    );
  }

  return (
    <PageContainer width="wide" density="compact">
      <div className="role-dashboard-landing">
        <SectionCard variant="primary" className="role-dashboard-hero">
          <SectionHeader
            title="Competitor Intelligence"
            subtitle="Track competitor set readiness, run status, and domain coverage for the selected site."
            headingLevel={1}
            variant="hero"
            meta={(
              <span className="hint muted">
                Selected site: <code>{selectedSite?.display_name || selectedSiteId || "none"}</code>
              </span>
            )}
          />
          <div className="workspace-summary-strip role-summary-strip">
            <SummaryStatCard
              label="Competitor sets"
              value={competitorSetCount}
              detail={`${activeSetCount} active`}
              tone={competitorSetCount > 0 ? "success" : "warning"}
              variant="elevated"
            />
            <SummaryStatCard
              label="Domains"
              value={totalDomainCount}
              detail={`${activeDomainCount} active domains`}
              tone={totalDomainCount > 0 ? "success" : "warning"}
              variant="elevated"
            />
            <SummaryStatCard
              label="Snapshot status"
              value={latestSnapshotRun ? formatRunStatus(latestSnapshotRun.status) : "none"}
              detail={latestSnapshotRun ? latestSnapshotRun.competitor_set_name : "No snapshot run yet"}
              tone={
                latestSnapshotRun?.status?.toLowerCase() === "completed"
                  ? "success"
                  : latestSnapshotRun
                    ? "warning"
                    : "neutral"
              }
              variant="elevated"
            />
            <SummaryStatCard
              label="Comparison status"
              value={latestComparisonRun ? formatRunStatus(latestComparisonRun.status) : "none"}
              detail={latestComparisonRun ? latestComparisonRun.competitor_set_name : "No comparison run yet"}
              tone={
                latestComparisonRun?.status?.toLowerCase() === "completed"
                  ? "success"
                  : latestComparisonRun
                    ? "warning"
                    : "neutral"
              }
              variant="elevated"
            />
          </div>
        </SectionCard>
      </div>

      <SectionCard variant="summary" className="role-surface-support">
        <SectionHeader
          title="Competitor set inventory"
          subtitle="Review readiness diagnostics and open competitor sets, snapshot runs, and comparison runs."
          headingLevel={2}
          variant="support"
        />
        <label htmlFor="site-picker-competitors">Site</label>
        <select
          id="site-picker-competitors"
          value={selectedSiteId || ""}
          onChange={(event) => setSelectedSiteId(event.target.value)}
        >
          {sites.map((site) => (
            <option key={site.id} value={site.id}>
              {site.display_name}
            </option>
          ))}
        </select>

        <div className="panel stack section-card-variant-support">
          <h2 className="heading-reset">Readiness</h2>
          <p className="hint muted">
            Selected Site:{" "}
            <strong>{selectedSite?.display_name || selectedSiteId || "No site selected"}</strong>
            {selectedSiteId ? (
              <>
                {" "}
                (<code>{selectedSiteId}</code>)
              </>
            ) : null}
          </p>
          <div className="row-wrap">
            <span className="hint muted">Active Sets: {activeSetCount}/{competitorSetCount}</span>
            <span className="hint muted">Competitor Domains: {totalDomainCount}</span>
            <span className="hint muted">Active Domains: {activeDomainCount}</span>
          </div>
          <p className="hint muted">
            Latest Snapshot Run:{" "}
            {latestSnapshotRun ? (
              <>
                <strong>{formatRunStatus(latestSnapshotRun.status)}</strong>{" "}
                ({formatDateTime(latestSnapshotRun.completed_at || latestSnapshotRun.updated_at || latestSnapshotRun.created_at)})
                {" "}for {latestSnapshotRun.competitor_set_name}{" "}
                <Link href={buildSnapshotRunHref(latestSnapshotRun)}>View</Link>
              </>
            ) : (
              "none"
            )}
          </p>
          <p className="hint muted">
            Latest Comparison Run:{" "}
            {latestComparisonRun ? (
              <>
                <strong>{formatRunStatus(latestComparisonRun.status)}</strong>{" "}
                ({formatDateTime(latestComparisonRun.completed_at || latestComparisonRun.updated_at || latestComparisonRun.created_at)})
                {" "}for {latestComparisonRun.competitor_set_name}{" "}
                <Link href={buildComparisonRunHref(latestComparisonRun)}>View</Link>
              </>
            ) : (
              "none"
            )}
          </p>
          {readinessWarning ? <p className="hint warning">{readinessWarning}</p> : null}
          <p className="hint muted">{readinessGuidance}</p>
        </div>

        <div className="row-wrap">
          <span className="hint muted">Competitor Sets: {competitorSetCount}</span>
          <span className="hint muted">Domains Across Sets: {totalDomainCount}</span>
        </div>

        <div className="stack" data-testid="competitor-quick-scan">
          <h3 className="heading-reset">Set quick scan</h3>
          <p className="hint muted">
            Summary-first cards highlight readiness and the next set to review before opening full tables.
          </p>
          {competitorSets.length === 0 && !loadingCompetitors ? (
            <p className="hint muted">No competitor sets available for quick scan.</p>
          ) : null}
          {competitorSets.length > 0 ? (
            <div className="operational-item-list">
              {competitorSets.slice(0, 6).map((item) => {
                const snapshotStatus = item.latest_snapshot_status
                  ? formatRunStatus(item.latest_snapshot_status)
                  : "No snapshot";
                return (
                  <OperationalItemCard
                    key={`competitor-quick-scan-${item.id}`}
                    data-testid={`competitor-quick-scan-item-${item.id}`}
                    title={`Set: ${item.name}`}
                    identity={<code>{item.id}</code>}
                    chips={(
                      <>
                        <span className={`badge ${item.is_active ? "badge-success" : "badge-muted"}`}>
                          {item.is_active ? "Active set" : "Inactive set"}
                        </span>
                        <span className="badge badge-muted">{item.active_domain_count}/{item.domain_count} active domains</span>
                        <span className={`badge ${snapshotStatus.toLowerCase() === "completed" ? "badge-success" : "badge-warn"}`}>
                          Snapshot: {snapshotStatus}
                        </span>
                      </>
                    )}
                    summary={`Location: ${formatLocation(item.city, item.state)}. Provenance: ${item.source_summary}.`}
                    primaryAction={
                      <Link href={buildSetDetailHref(item)} className="button button-tertiary button-inline">
                        Open set detail
                      </Link>
                    }
                    secondaryMeta={
                      <>
                        <span className="hint muted">Latest domain update: {formatDateTime(item.latest_domain_updated_at)}</span>
                      </>
                    }
                    expandedDetail={
                      <>
                        <p className="hint muted">
                          <span className="text-strong">Business:</span> {item.business_id}
                        </p>
                        <p className="hint muted">
                          <span className="text-strong">Site:</span> {item.site_id}
                        </p>
                        <p className="hint muted">
                          <span className="text-strong">Created:</span> {formatDateTime(item.created_at)}
                        </p>
                        <p className="hint muted">
                          <span className="text-strong">Updated:</span> {formatDateTime(item.updated_at)}
                        </p>
                      </>
                    }
                  />
                );
              })}
            </div>
          ) : null}
        </div>

        {loadingCompetitors ? <p className="hint muted">Loading competitors...</p> : null}
        {competitorsError ? <p className="hint error">{competitorsError}</p> : null}

        <div className="table-container">
          <table className="table table-dense">
            <thead>
              <tr>
                <th>Set</th>
                <th>Business</th>
                <th>Site</th>
                <th>Location</th>
                <th>Status</th>
                <th>Domains</th>
                <th>Provenance</th>
                <th>Created By</th>
                <th>Created</th>
                <th>Updated</th>
                <th>Latest Domain Update</th>
              </tr>
            </thead>
            <tbody>
              {competitorSets.map((item) => (
                <tr
                  key={item.id}
                  role="link"
                  tabIndex={0}
                  className="clickable-row"
                  onClick={() => router.push(buildSetDetailHref(item))}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      router.push(buildSetDetailHref(item));
                    }
                  }}
                >
                  <td>
                    <strong>{item.name}</strong>
                    <br />
                    <span className="hint muted">{item.id}</span>
                  </td>
                  <td>{item.business_id}</td>
                  <td>{item.site_id}</td>
                  <td>{formatLocation(item.city, item.state)}</td>
                  <td>{item.is_active ? "active" : "inactive"}</td>
                  <td>
                    {item.active_domain_count}/{item.domain_count} active
                  </td>
                  <td>{item.source_summary}</td>
                  <td>{item.created_by_principal_id || "-"}</td>
                  <td>{formatDateTime(item.created_at)}</td>
                  <td>{formatDateTime(item.updated_at)}</td>
                  <td>{formatDateTime(item.latest_domain_updated_at)}</td>
                </tr>
              ))}
              {!loadingCompetitors && competitorSets.length === 0 ? (
                <tr>
                  <td colSpan={11}>
                    {tableEmptyReason}
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </SectionCard>
    </PageContainer>
  );
}

export default function CompetitorsPage() {
  return (
    <Suspense
      fallback={(
        <PageContainer width="wide" density="compact">
          <SectionCard as="div" variant="support" className="role-surface-support">
            <SectionHeader
              title="Competitor Intelligence"
              subtitle="Loading competitor set readiness for your selected site."
              headingLevel={1}
              variant="support"
            />
          </SectionCard>
        </PageContainer>
      )}
    >
      <CompetitorsPageContent />
    </Suspense>
  );
}
