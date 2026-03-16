"use client";

import { useEffect, useState } from "react";

import { useOperatorContext } from "../../components/useOperatorContext";
import { fetchAutomationRuns } from "../../lib/api/client";
import type { AutomationRun } from "../../lib/api/types";

export default function AutomationPage() {
  const context = useOperatorContext();
  const [items, setItems] = useState<AutomationRun[]>([]);
  const [loadingItems, setLoadingItems] = useState(false);
  const [itemsError, setItemsError] = useState<string | null>(null);

  useEffect(() => {
    if (!context.selectedSiteId || context.loading || context.error) {
      return;
    }
    let cancelled = false;
    async function loadRuns() {
      setLoadingItems(true);
      setItemsError(null);
      try {
        const response = await fetchAutomationRuns(context.token, context.businessId, context.selectedSiteId as string);
        if (!cancelled) {
          setItems(response.items);
        }
      } catch (err) {
        if (!cancelled) {
          setItemsError(err instanceof Error ? err.message : "Failed to load automation runs.");
        }
      } finally {
        if (!cancelled) {
          setLoadingItems(false);
        }
      }
    }
    void loadRuns();
    return () => {
      cancelled = true;
    };
  }, [context.businessId, context.error, context.loading, context.selectedSiteId, context.token]);

  if (context.loading) {
    return <section className="panel">Loading automation...</section>;
  }
  if (context.error) {
    return <section className="panel">Error: {context.error}</section>;
  }

  return (
    <section className="panel stack">
      <h1>Automation Run History</h1>
      <label htmlFor="site-picker-automation">Site</label>
      <select
        id="site-picker-automation"
        value={context.selectedSiteId || ""}
        onChange={(event) => context.setSelectedSiteId(event.target.value)}
      >
        {context.sites.map((site) => (
          <option key={site.id} value={site.id}>
            {site.display_name}
          </option>
        ))}
      </select>

      {loadingItems ? <p>Loading automation runs...</p> : null}
      {itemsError ? <p style={{ color: "#b91c1c" }}>{itemsError}</p> : null}

      <table className="table">
        <thead>
          <tr>
            <th>Run ID</th>
            <th>Status</th>
            <th>Trigger</th>
            <th>Started</th>
            <th>Finished</th>
            <th>Error</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.id}>
              <td>{item.id}</td>
              <td>{item.status}</td>
              <td>{item.trigger_source}</td>
              <td>{item.started_at || "-"}</td>
              <td>{item.finished_at || "-"}</td>
              <td>{item.error_message || "-"}</td>
            </tr>
          ))}
          {items.length === 0 && !loadingItems ? (
            <tr>
              <td colSpan={6}>No automation runs found for this site.</td>
            </tr>
          ) : null}
        </tbody>
      </table>
    </section>
  );
}
