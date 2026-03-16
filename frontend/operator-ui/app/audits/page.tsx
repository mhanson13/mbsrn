"use client";

import { useEffect, useState } from "react";

import { useOperatorContext } from "../../components/useOperatorContext";
import { fetchAuditRuns } from "../../lib/api/client";
import type { SEOAuditRun } from "../../lib/api/types";

export default function AuditsPage() {
  const context = useOperatorContext();
  const [runs, setRuns] = useState<SEOAuditRun[]>([]);
  const [loadingRuns, setLoadingRuns] = useState(false);
  const [runsError, setRunsError] = useState<string | null>(null);

  useEffect(() => {
    if (!context.selectedSiteId || context.loading || context.error) {
      return;
    }
    let cancelled = false;
    async function loadRuns() {
      setLoadingRuns(true);
      setRunsError(null);
      try {
        const response = await fetchAuditRuns(context.token, context.businessId, context.selectedSiteId as string);
        if (!cancelled) {
          setRuns(response.items);
        }
      } catch (err) {
        if (!cancelled) {
          setRunsError(err instanceof Error ? err.message : "Failed to load audit runs.");
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
    return <section className="panel">Error: {context.error}</section>;
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

      {loadingRuns ? <p>Loading audit runs...</p> : null}
      {runsError ? <p style={{ color: "#b91c1c" }}>{runsError}</p> : null}

      <table className="table">
        <thead>
          <tr>
            <th>Run ID</th>
            <th>Status</th>
            <th>Pages Crawled</th>
            <th>Pages Skipped</th>
            <th>Errors</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => (
            <tr key={run.id}>
              <td>{run.id}</td>
              <td>{run.status}</td>
              <td>{run.pages_crawled}</td>
              <td>{run.pages_skipped}</td>
              <td>{run.crawl_errors_count}</td>
            </tr>
          ))}
          {runs.length === 0 && !loadingRuns ? (
            <tr>
              <td colSpan={5}>No audit runs found for the selected site.</td>
            </tr>
          ) : null}
        </tbody>
      </table>
    </section>
  );
}
