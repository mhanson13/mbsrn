"use client";

import Link from "next/link";
import { FormEvent, useEffect, useMemo, useState } from "react";

import { useAuth } from "../../components/AuthProvider";
import { FormContainer } from "../../components/layout/FormContainer";
import { PageContainer } from "../../components/layout/PageContainer";
import { SectionCard } from "../../components/layout/SectionCard";
import { SectionHeader } from "../../components/layout/SectionHeader";
import { SummaryStatCard } from "../../components/layout/SummaryStatCard";
import { useOperatorContext } from "../../components/useOperatorContext";
import {
  activateSite,
  ApiRequestError,
  createAuditRun,
  createSite,
  deactivateSite,
  fetchAuditRunFindings,
  fetchAuditRunSummary,
  fetchAuditRuns,
  fetchRecommendations,
} from "../../lib/api/client";
import type {
  Recommendation,
  SEOAuditFinding,
  SEOAuditRun,
  SEOAuditRunSummary,
  SEOSite,
} from "../../lib/api/types";

interface DerivedSiteStatus {
  label: string;
  badgeClass: string;
}

interface DerivedFindingRecommendation {
  id: string;
  severity: string;
  title: string;
  action: string;
}

const MAX_TOP_FINDINGS = 7;
const MAX_TOP_RECOMMENDATIONS = 7;

function deriveSiteStatus(site: SEOSite): DerivedSiteStatus {
  if (!site.is_active) {
    return { label: "inactive", badgeClass: "badge badge-muted" };
  }
  if (!site.last_audit_run_id) {
    return { label: "not analyzed", badgeClass: "badge badge-muted" };
  }

  const status = (site.last_audit_status || "").trim().toLowerCase();
  if (status === "completed") {
    return { label: "analysis complete", badgeClass: "badge badge-success" };
  }
  if (status === "failed") {
    return { label: "analysis failed", badgeClass: "badge badge-error" };
  }
  return { label: site.last_audit_status || "created", badgeClass: "badge badge-warn" };
}

function getAuditStatusBadge(status: string | null): string {
  const normalized = (status || "").trim().toLowerCase();
  if (normalized === "completed") {
    return "badge badge-success";
  }
  if (normalized === "failed") {
    return "badge badge-error";
  }
  if (!normalized) {
    return "badge badge-muted";
  }
  return "badge badge-warn";
}

function severityRank(value: string): number {
  const normalized = value.trim().toUpperCase();
  if (normalized === "CRITICAL" || normalized === "ERROR") {
    return 0;
  }
  if (normalized === "WARNING" || normalized === "WARN") {
    return 1;
  }
  if (normalized === "INFO") {
    return 2;
  }
  return 3;
}

function formatSignedDelta(value: number): string {
  if (value > 0) {
    return `+${value}`;
  }
  return `${value}`;
}

function parseBaseUrl(value: string): URL {
  let parsed: URL;
  try {
    parsed = new URL(value.trim());
  } catch {
    throw new Error("Base URL must be a valid absolute URL.");
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new Error("Base URL must start with http:// or https://.");
  }
  if (!parsed.hostname) {
    throw new Error("Base URL must include a valid domain.");
  }
  return parsed;
}

function safeSiteActionErrorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) {
    if (error.status === 401) {
      return "Session expired. Sign in again.";
    }
    if (error.status === 403) {
      return "Only admin principals can update site activation.";
    }
    if (error.status === 404) {
      return "Site not found in this business scope.";
    }
    if (error.status === 422) {
      return "Unable to update site activation state.";
    }
  }
  return "Failed to update site activation state.";
}

export default function SitesPage() {
  const { principal } = useAuth();
  const context = useOperatorContext();
  const [displayName, setDisplayName] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [submitLoading, setSubmitLoading] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitSuccess, setSubmitSuccess] = useState<string | null>(null);
  const [triggeringSiteId, setTriggeringSiteId] = useState<string | null>(null);
  const [triggerMessage, setTriggerMessage] = useState<string | null>(null);
  const [triggerError, setTriggerError] = useState<string | null>(null);
  const [loadingIntelligence, setLoadingIntelligence] = useState(false);
  const [intelligenceError, setIntelligenceError] = useState<string | null>(null);
  const [latestRun, setLatestRun] = useState<SEOAuditRun | null>(null);
  const [previousRun, setPreviousRun] = useState<SEOAuditRun | null>(null);
  const [latestSummary, setLatestSummary] = useState<SEOAuditRunSummary | null>(null);
  const [previousSummary, setPreviousSummary] = useState<SEOAuditRunSummary | null>(null);
  const [topFindings, setTopFindings] = useState<SEOAuditFinding[]>([]);
  const [recommendations, setRecommendations] = useState<Recommendation[]>([]);
  const [siteActionSiteId, setSiteActionSiteId] = useState<string | null>(null);
  const [siteActionError, setSiteActionError] = useState<string | null>(null);
  const [siteActionSuccess, setSiteActionSuccess] = useState<string | null>(null);

  const isAdmin = principal?.role === "admin";
  const activeSiteCount = context.sites.filter((site) => site.is_active).length;
  const completedAuditSiteCount = context.sites.filter(
    (site) => (site.last_audit_status || "").trim().toLowerCase() === "completed",
  ).length;
  const needsAuditSiteCount = context.sites.filter((site) => !site.last_audit_run_id).length;

  const statuses = useMemo(() => {
    return context.sites.reduce<Record<string, DerivedSiteStatus>>((acc, site) => {
      acc[site.id] = deriveSiteStatus(site);
      return acc;
    }, {});
  }, [context.sites]);

  const selectedSite = useMemo(() => {
    if (!context.selectedSiteId) {
      return null;
    }
    return context.sites.find((site) => site.id === context.selectedSiteId) || null;
  }, [context.selectedSiteId, context.sites]);

  const derivedRecommendations = useMemo<DerivedFindingRecommendation[]>(() => {
    if (recommendations.length > 0) {
      return [];
    }
    return topFindings.slice(0, MAX_TOP_RECOMMENDATIONS).map((item) => ({
      id: item.id,
      severity: item.severity,
      title: item.title,
      action: item.suggested_fix || "Review this finding and apply a targeted fix in content or templates.",
    }));
  }, [recommendations.length, topFindings]);

  const healthDelta =
    latestSummary && previousSummary
      ? latestSummary.health_score - previousSummary.health_score
      : null;
  const issueDelta =
    latestSummary && previousSummary
      ? latestSummary.total_findings - previousSummary.total_findings
      : null;

  useEffect(() => {
    if (!context.selectedSiteId || context.loading || context.error) {
      setLatestRun(null);
      setPreviousRun(null);
      setLatestSummary(null);
      setPreviousSummary(null);
      setTopFindings([]);
      setRecommendations([]);
      setIntelligenceError(null);
      setLoadingIntelligence(false);
      return;
    }

    let cancelled = false;

    async function loadIntelligence() {
      setLoadingIntelligence(true);
      setIntelligenceError(null);
      try {
        const runResponse = await fetchAuditRuns(context.token, context.businessId, context.selectedSiteId as string);
        const latest = runResponse.items[0] || null;
        const previous = runResponse.items[1] || null;

        const [latestSummaryResponse, latestFindingsResponse, previousSummaryResponse, recommendationResponse] =
          await Promise.all([
            latest
              ? fetchAuditRunSummary(context.token, context.businessId, latest.id)
              : Promise.resolve<SEOAuditRunSummary | null>(null),
            latest
              ? fetchAuditRunFindings(context.token, context.businessId, latest.id)
              : Promise.resolve({ items: [] as SEOAuditFinding[] }),
            previous
              ? fetchAuditRunSummary(context.token, context.businessId, previous.id)
              : Promise.resolve<SEOAuditRunSummary | null>(null),
            fetchRecommendations(context.token, context.businessId, context.selectedSiteId as string),
          ]);

        if (cancelled) {
          return;
        }

        const orderedFindings = [...latestFindingsResponse.items]
          .sort((a, b) => {
            const severityDiff = severityRank(a.severity) - severityRank(b.severity);
            if (severityDiff !== 0) {
              return severityDiff;
            }
            return a.title.localeCompare(b.title);
          })
          .slice(0, MAX_TOP_FINDINGS);

        const orderedRecommendations = [...recommendationResponse.items]
          .sort((a, b) => {
            if (a.priority_score !== b.priority_score) {
              return b.priority_score - a.priority_score;
            }
            const severityDiff = severityRank(a.severity) - severityRank(b.severity);
            if (severityDiff !== 0) {
              return severityDiff;
            }
            return a.title.localeCompare(b.title);
          })
          .slice(0, MAX_TOP_RECOMMENDATIONS);

        setLatestRun(latest);
        setPreviousRun(previous);
        setLatestSummary(latestSummaryResponse);
        setPreviousSummary(previousSummaryResponse);
        setTopFindings(orderedFindings);
        setRecommendations(orderedRecommendations);
      } catch (err) {
        if (!cancelled) {
          setIntelligenceError(
            err instanceof Error ? err.message : "Failed to load SEO intelligence for the selected site.",
          );
        }
      } finally {
        if (!cancelled) {
          setLoadingIntelligence(false);
        }
      }
    }

    void loadIntelligence();

    return () => {
      cancelled = true;
    };
  }, [
    context.businessId,
    context.error,
    context.loading,
    context.selectedSiteId,
    context.token,
  ]);

  const handleCreateSite = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitLoading(true);
    setSubmitError(null);
    setSubmitSuccess(null);
    setTriggerMessage(null);
    setTriggerError(null);

    try {
      const parsedBaseUrl = parseBaseUrl(baseUrl);
      const normalizedDisplayName = displayName.trim() || parsedBaseUrl.hostname;
      const created = await createSite(context.token, context.businessId, {
        display_name: normalizedDisplayName,
        base_url: parsedBaseUrl.toString(),
      });
      await context.refreshSites();
      context.setSelectedSiteId(created.id);
      setDisplayName("");
      setBaseUrl("");
      setSubmitSuccess(`Created site ${created.display_name}.`);
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "Failed to create site.");
    } finally {
      setSubmitLoading(false);
    }
  };

  const handleTriggerAudit = async (site: SEOSite) => {
    setTriggeringSiteId(site.id);
    setTriggerError(null);
    setTriggerMessage(null);
    setSubmitSuccess(null);

    try {
      const run = await createAuditRun(context.token, context.businessId, site.id, {
        max_depth: 2,
      });
      await context.refreshSites();
      setTriggerMessage(`Audit run ${run.id} finished with status ${run.status}.`);
    } catch (err) {
      setTriggerError(err instanceof Error ? err.message : "Failed to trigger site analysis.");
    } finally {
      setTriggeringSiteId(null);
    }
  };

  const handleToggleSiteActive = async (site: SEOSite) => {
    const activating = !site.is_active;
    const actionLabel = activating ? "reactivate" : "deactivate";
    const confirmed = window.confirm(
      `Confirm ${actionLabel} for site "${site.display_name}" (${site.normalized_domain})?`,
    );
    if (!confirmed) {
      return;
    }

    setSiteActionError(null);
    setSiteActionSuccess(null);
    setSiteActionSiteId(site.id);
    try {
      if (activating) {
        await activateSite(context.token, context.businessId, site.id);
      } else {
        await deactivateSite(context.token, context.businessId, site.id);
      }
      await context.refreshSites();
      setSiteActionSuccess(
        activating ? `Site ${site.display_name} reactivated.` : `Site ${site.display_name} deactivated.`,
      );
    } catch (err) {
      setSiteActionError(safeSiteActionErrorMessage(err));
    } finally {
      setSiteActionSiteId(null);
    }
  };

  if (context.loading) {
    return (
      <PageContainer>
        <SectionCard as="div">Loading sites...</SectionCard>
      </PageContainer>
    );
  }
  if (context.error) {
    return (
      <PageContainer>
        <SectionCard as="div">Error: {context.error}</SectionCard>
      </PageContainer>
    );
  }

  return (
    <PageContainer>
      <div className="role-dashboard-landing">
        <SectionCard variant="primary" className="role-dashboard-hero">
          <SectionHeader
            title="SEO Sites"
            subtitle="Manage tracked properties, trigger audits, and monitor site intelligence."
            headingLevel={1}
            variant="hero"
            meta={(
              <>
                <span className="hint muted">Business: <code>{context.businessId}</code></span>
                {principal ? <span className="hint muted">Role: {principal.role}</span> : null}
              </>
            )}
          />
          <div className="workspace-summary-strip role-summary-strip">
            <SummaryStatCard
              label="Tracked sites"
              value={context.sites.length}
              detail={context.sites.length === 0 ? "No sites configured yet" : "Currently configured"}
              tone={context.sites.length > 0 ? "success" : "warning"}
              variant="elevated"
            />
            <SummaryStatCard
              label="Active sites"
              value={activeSiteCount}
              detail={`${Math.max(0, context.sites.length - activeSiteCount)} inactive`}
              tone={activeSiteCount > 0 ? "success" : "warning"}
              variant="elevated"
            />
            <SummaryStatCard
              label="Audit-ready insight"
              value={completedAuditSiteCount > 0 ? "Available" : "Missing"}
              detail={`${completedAuditSiteCount} site${completedAuditSiteCount === 1 ? "" : "s"} with completed audits`}
              tone={completedAuditSiteCount > 0 ? "success" : "warning"}
              variant="elevated"
            />
            <SummaryStatCard
              label="Needs first audit"
              value={needsAuditSiteCount}
              detail={needsAuditSiteCount > 0 ? "Run first audit from this page" : "All sites have at least one run"}
              tone={needsAuditSiteCount > 0 ? "warning" : "neutral"}
              variant="elevated"
            />
          </div>

          <FormContainer onSubmit={(event) => void handleCreateSite(event)}>
            <h2>Add Site</h2>
            <label htmlFor="base-url">Base URL</label>
            <input
              id="base-url"
              value={baseUrl}
              onChange={(event) => setBaseUrl(event.target.value)}
              placeholder="https://example.com"
              required
            />
            <label htmlFor="display-name">Display Name (optional)</label>
            <input
              id="display-name"
              value={displayName}
              onChange={(event) => setDisplayName(event.target.value)}
              placeholder="Example Site"
            />
            <div className="form-actions">
              <button className="button button-primary" type="submit" disabled={submitLoading}>
                {submitLoading ? "Adding site..." : "Add Site"}
              </button>
            </div>
          </FormContainer>

          <div className="message-stack">
            {submitSuccess ? <p className="hint">{submitSuccess}</p> : null}
            {submitError ? <p className="hint error">{submitError}</p> : null}
            {triggerMessage ? <p className="hint">{triggerMessage}</p> : null}
            {triggerError ? <p className="hint error">{triggerError}</p> : null}
            {siteActionSuccess ? <p className="hint">{siteActionSuccess}</p> : null}
            {siteActionError ? <p className="hint error">{siteActionError}</p> : null}
          </div>
        </SectionCard>
      </div>

      <SectionCard variant="summary" className="role-surface-support">
        <SectionHeader
          title="Configured Sites"
          subtitle="Current site inventory with audit status and direct workspace actions."
          headingLevel={2}
          variant="support"
          meta={selectedSite ? <span className="hint muted">Selected site: <code>{selectedSite.id}</code></span> : null}
        />
        <div className="table-container">
          <table className="table">
            <thead>
              <tr>
                <th>Display Name</th>
                <th>Base URL</th>
                <th>Domain</th>
                <th>Status</th>
                <th>Last Audit</th>
                <th>Primary</th>
                <th>Active</th>
                <th>Workspace</th>
                <th>Action</th>
                {isAdmin ? <th>Admin Action</th> : null}
              </tr>
            </thead>
            <tbody>
              {context.sites.map((site) => (
                <tr key={site.id}>
                  <td className="table-cell-wrap">{site.display_name}</td>
                  <td className="table-cell-wrap">{site.base_url}</td>
                  <td className="table-cell-wrap">{site.normalized_domain}</td>
                  <td>
                    <span className={statuses[site.id]?.badgeClass || "badge badge-muted"}>
                      {statuses[site.id]?.label || "unknown"}
                    </span>
                  </td>
                  <td>{site.last_audit_completed_at || "none"}</td>
                  <td>{site.is_primary ? "yes" : "no"}</td>
                  <td>{site.is_active ? "yes" : "no"}</td>
                  <td>
                    <Link href={`/sites/${site.id}`}>Open Workspace</Link>
                  </td>
                  <td>
                    <button
                      type="button"
                      className="button button-secondary button-inline"
                      disabled={!!triggeringSiteId || !site.is_active}
                      onClick={() => {
                        void handleTriggerAudit(site);
                      }}
                    >
                      {triggeringSiteId === site.id
                        ? "Running..."
                        : site.last_audit_run_id
                          ? "Run Audit Again"
                          : "Run First Audit"}
                    </button>
                  </td>
                  {isAdmin ? (
                    <td>
                      <button
                        type="button"
                        className={
                          site.is_active
                            ? "button button-danger button-inline"
                            : "button button-secondary button-inline"
                        }
                        disabled={!!siteActionSiteId}
                        onClick={() => {
                          void handleToggleSiteActive(site);
                        }}
                      >
                        {siteActionSiteId === site.id
                          ? site.is_active
                            ? "Deactivating..."
                            : "Reactivating..."
                          : site.is_active
                            ? "Deactivate Site"
                            : "Reactivate Site"}
                      </button>
                    </td>
                  ) : null}
                </tr>
              ))}
              {context.sites.length === 0 ? (
                <tr>
                  <td colSpan={isAdmin ? 10 : 9}>No sites configured for this business.</td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </SectionCard>

      <SectionCard variant="support" className="role-surface-support">
        <SectionHeader
          title="Site Intelligence"
          subtitle="Latest audit findings, recommendations, and trend deltas for the selected site."
          headingLevel={2}
          variant="support"
        />

        <div className="form-container">
          <label htmlFor="site-picker-intelligence">Selected Site</label>
          <select
            id="site-picker-intelligence"
            value={context.selectedSiteId || ""}
            onChange={(event) => context.setSelectedSiteId(event.target.value)}
            disabled={context.sites.length === 0}
          >
            {context.sites.map((site) => (
              <option key={site.id} value={site.id}>
                {site.display_name}
              </option>
            ))}
          </select>
        </div>

        {!selectedSite ? <p className="hint muted">No site selected.</p> : null}
        {loadingIntelligence ? <p className="hint muted">Loading site intelligence...</p> : null}
        {intelligenceError ? <p className="hint error">{intelligenceError}</p> : null}

        {selectedSite && !loadingIntelligence && !intelligenceError ? (
          <>
            {!latestSummary ? (
              <p className="hint warning">
                No audit summary yet for this site. Run the first audit to generate intelligence data.
              </p>
            ) : (
              <>
                <div className="stack">
                  <h3>Latest Audit Summary</h3>
                  <p>
                    Status:{" "}
                    <span className={getAuditStatusBadge(latestSummary.status)}>{latestSummary.status}</span>
                  </p>
                  <p>
                    Last audit timestamp:{" "}
                    <code>{latestRun?.completed_at || latestRun?.started_at || "unknown"}</code>
                  </p>
                  <p>
                    Health score (audit-derived): <strong>{latestSummary.health_score}</strong>
                  </p>
                  <p>
                    Total findings: <strong>{latestSummary.total_findings}</strong> (critical{" "}
                    {latestSummary.critical_findings}, warning {latestSummary.warning_findings}, info{" "}
                    {latestSummary.info_findings})
                  </p>
                </div>

                <div className="stack">
                  <h3>Prioritized Findings (Top {MAX_TOP_FINDINGS})</h3>
                  {topFindings.length === 0 ? (
                    <p className="hint muted">No findings were recorded for the latest audit.</p>
                  ) : (
                    <div className="table-container">
                      <table className="table">
                        <thead>
                          <tr>
                            <th>Severity</th>
                            <th>Category</th>
                            <th>Issue</th>
                            <th>Suggested Fix</th>
                          </tr>
                        </thead>
                        <tbody>
                          {topFindings.map((item) => (
                            <tr key={item.id}>
                              <td>{item.severity}</td>
                              <td>{item.category}</td>
                              <td>{item.title}</td>
                              <td>{item.suggested_fix || "-"}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>

                <div className="stack">
                  <h3>Recommendations</h3>
                  {recommendations.length > 0 ? (
                    <div className="table-container">
                      <table className="table">
                        <thead>
                          <tr>
                            <th>Priority</th>
                            <th>Severity</th>
                            <th>Recommendation</th>
                            <th>Rationale</th>
                          </tr>
                        </thead>
                        <tbody>
                          {recommendations.map((item) => (
                            <tr key={item.id}>
                              <td>
                                {item.priority_score} ({item.priority_band})
                              </td>
                              <td>{item.severity}</td>
                              <td>{item.title}</td>
                              <td>{item.rationale}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : derivedRecommendations.length > 0 ? (
                    <>
                      <p className="hint muted">
                        No persisted recommendation items exist yet. Showing direct next steps derived from latest
                        findings.
                      </p>
                      <div className="table-container">
                        <table className="table">
                          <thead>
                            <tr>
                              <th>Severity</th>
                              <th>Recommendation</th>
                              <th>Source Mapping</th>
                            </tr>
                          </thead>
                          <tbody>
                            {derivedRecommendations.map((item) => (
                              <tr key={item.id}>
                                <td>{item.severity}</td>
                                <td>{item.title}</td>
                                <td>{item.action}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </>
                  ) : (
                    <p className="hint muted">No recommendations or actionable findings are available yet.</p>
                  )}
                </div>

                <div className="stack">
                  <h3>Change Over Time</h3>
                  {latestSummary && previousSummary ? (
                    <>
                      <p>
                        Latest audit run: <code>{latestRun?.completed_at || latestRun?.started_at || "unknown"}</code>
                      </p>
                      <p>
                        Previous audit run:{" "}
                        <code>{previousRun?.completed_at || previousRun?.started_at || "unknown"}</code>
                      </p>
                      <p>
                        Health score delta: <strong>{formatSignedDelta(healthDelta || 0)}</strong>
                      </p>
                      <p>
                        Issue count delta: <strong>{formatSignedDelta(issueDelta || 0)}</strong> (negative means fewer
                        findings)
                      </p>
                    </>
                  ) : (
                    <p className="hint muted">No historical comparison yet. Complete at least two audits.</p>
                  )}
                </div>
              </>
            )}
          </>
        ) : null}
      </SectionCard>
    </PageContainer>
  );
}
