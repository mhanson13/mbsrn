"use client";

import { useEffect, useState } from "react";

import { useOperatorContext } from "../../components/useOperatorContext";
import { ApiRequestError, fetchAuditRuns } from "../../lib/api/client";
import type { SEOAuditRun } from "../../lib/api/types";

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

function deriveResultIndicator(run: SEOAuditRun): string {
  const status = (run.status || "").trim().toLowerCase();
  if (status === "completed") {
    if (run.errors_encountered > 0) {
      return `Completed with ${run.errors_encountered} crawl error(s)`;
    }
    return `Completed; ${run.pages_crawled} page(s) crawled`;
  }
  if (status === "failed") {
    return run.error_summary ? "Run failed; review run details" : "Run failed";
  }
  if (status === "running" || status === "queued") {
    return "Run in progress";
  }
  return "Status unknown";
}

function safeAuditErrorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) {
    if (error.status === 401) {
      return "Session expired. Sign in again.";
    }
    if (error.status === 403) {
      return "You are not authorized to view audit runs.";
    }
    if (error.status === 404) {
      return "Audit data for the selected site was not found.";
    }
  }
  return "Unable to load audit runs right now. Please try again.";
}

export default function AuditsPage() {
  const context = useOperatorContext();
  const [runs, setRuns] = useState<SEOAuditRun[]>([]);
  const [loadingRuns, setLoadingRuns] = useState(false);
  const [runsError, setRunsError] = useState<string | null>(null);

  useEffect(() => {
    if (context.loading || context.error || !context.selectedSiteId) {
      setRuns([]);
      setRunsError(null);
      setLoadingRuns(false);
      return;
    }
    let cancelled = false;
    const selectedSiteId = context.selectedSiteId;

    async function loadRuns() {
      setLoadingRuns(true);
      setRunsError(null);
      try {
        const response = await fetchAuditRuns(context.token, context.businessId, selectedSiteId);
        if (!cancelled) {
          setRuns(response.items);
        }
      } catch (err) {
        if (!cancelled) {
          setRunsError(safeAuditErrorMessage(err));
        }
      } finally {
        if (!cancelled) {
          setLoadingRuns(false);
        }
      }
    }
    void loadRuns();
    return () => {
      cancelled = true;
    };
  }, [context.businessId, context.error, context.loading, context.selectedSiteId, context.token]);

  if (context.loading) {
    return <section className="panel">Loading audits...</section>;
  }
  if (context.error) {
    return <section className="panel">Unable to load tenant context. Refresh and sign in again.</section>;
  }
  if (context.sites.length === 0) {
    return (
      <section className="panel stack">
        <h1>Audit Runs</h1>
        <p className="hint muted">No SEO sites are configured yet. Add a site first to view audit runs.</p>
      </section>
    );
  }

  return (
    <section className="panel stack">
      <h1>Audit Runs</h1>
      <label htmlFor="site-picker-audit">Site</label>
      <select
        id="site-picker-audit"
        value={context.selectedSiteId || ""}
        onChange={(event) => context.setSelectedSiteId(event.target.value)}
      >
        {context.sites.map((site) => (
          <option key={site.id} value={site.id}>
            {site.display_name}
          </option>
        ))}
      </select>

      {loadingRuns ? <p className="hint muted">Loading audit runs...</p> : null}
      {runsError ? <p className="hint error">{runsError}</p> : null}

      <table className="table">
        <thead>
          <tr>
            <th>Run ID</th>
            <th>Business</th>
            <th>Site</th>
            <th>Status</th>
            <th>Created</th>
            <th>Started</th>
            <th>Completed</th>
            <th>Result</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => (
            <tr key={run.id}>
              <td>{run.id}</td>
              <td>{run.business_id}</td>
              <td>{run.site_id}</td>
              <td>{run.status}</td>
              <td>{formatDateTime(run.created_at)}</td>
              <td>{formatDateTime(run.started_at)}</td>
              <td>{formatDateTime(run.completed_at)}</td>
              <td>{deriveResultIndicator(run)}</td>
            </tr>
          ))}
          {runs.length === 0 && !loadingRuns ? (
            <tr>
              <td colSpan={8}>No audit runs found for the selected site.</td>
            </tr>
          ) : null}
        </tbody>
      </table>
    </section>
  );
}
