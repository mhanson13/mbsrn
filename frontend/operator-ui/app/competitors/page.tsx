"use client";

import { useEffect, useState } from "react";

import { useOperatorContext } from "../../components/useOperatorContext";
import { fetchCompetitorSets } from "../../lib/api/client";
import type { CompetitorSet } from "../../lib/api/types";

export default function CompetitorsPage() {
  const context = useOperatorContext();
  const [sets, setSets] = useState<CompetitorSet[]>([]);
  const [loadingSets, setLoadingSets] = useState(false);
  const [setsError, setSetsError] = useState<string | null>(null);

  useEffect(() => {
    if (!context.selectedSiteId || context.loading || context.error) {
      return;
    }
    let cancelled = false;
    async function loadSets() {
      setLoadingSets(true);
      setSetsError(null);
      try {
        const response = await fetchCompetitorSets(context.token, context.businessId, context.selectedSiteId as string);
        if (!cancelled) {
          setSets(response.items);
        }
      } catch (err) {
        if (!cancelled) {
          setSetsError(err instanceof Error ? err.message : "Failed to load competitor sets.");
        }
      } finally {
        if (!cancelled) {
          setLoadingSets(false);
        }
      }
    }
    void loadSets();
    return () => {
      cancelled = true;
    };
  }, [context.businessId, context.error, context.loading, context.selectedSiteId, context.token]);

  if (context.loading) {
    return <section className="panel">Loading competitor intelligence...</section>;
  }
  if (context.error) {
    return <section className="panel">Error: {context.error}</section>;
  }

  return (
    <section className="panel stack">
      <h1>Competitor Intelligence</h1>
      <label htmlFor="site-picker-competitors">Site</label>
      <select
        id="site-picker-competitors"
        value={context.selectedSiteId || ""}
        onChange={(event) => context.setSelectedSiteId(event.target.value)}
      >
        {context.sites.map((site) => (
          <option key={site.id} value={site.id}>
            {site.display_name}
          </option>
        ))}
      </select>

      {loadingSets ? <p>Loading competitor sets...</p> : null}
      {setsError ? <p style={{ color: "#b91c1c" }}>{setsError}</p> : null}

      <table className="table">
        <thead>
          <tr>
            <th>Set ID</th>
            <th>Name</th>
            <th>Description</th>
            <th>Active</th>
          </tr>
        </thead>
        <tbody>
          {sets.map((item) => (
            <tr key={item.id}>
              <td>{item.id}</td>
              <td>{item.name}</td>
              <td>{item.description || "-"}</td>
              <td>{item.is_active ? "yes" : "no"}</td>
            </tr>
          ))}
          {sets.length === 0 && !loadingSets ? (
            <tr>
              <td colSpan={4}>No competitor sets found for this site.</td>
            </tr>
          ) : null}
        </tbody>
      </table>
    </section>
  );
}
