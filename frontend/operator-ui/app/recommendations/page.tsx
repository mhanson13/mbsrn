"use client";

import { useEffect, useState } from "react";

import { useOperatorContext } from "../../components/useOperatorContext";
import { fetchRecommendations } from "../../lib/api/client";
import type { Recommendation } from "../../lib/api/types";

export default function RecommendationsPage() {
  const context = useOperatorContext();
  const [items, setItems] = useState<Recommendation[]>([]);
  const [loadingItems, setLoadingItems] = useState(false);
  const [itemsError, setItemsError] = useState<string | null>(null);

  useEffect(() => {
    if (!context.selectedSiteId || context.loading || context.error) {
      return;
    }
    let cancelled = false;
    async function loadRecommendations() {
      setLoadingItems(true);
      setItemsError(null);
      try {
        const response = await fetchRecommendations(
          context.token,
          context.businessId,
          context.selectedSiteId as string,
        );
        if (!cancelled) {
          setItems(response.items);
        }
      } catch (err) {
        if (!cancelled) {
          setItemsError(err instanceof Error ? err.message : "Failed to load recommendations.");
        }
      } finally {
        if (!cancelled) {
          setLoadingItems(false);
        }
      }
    }
    void loadRecommendations();
    return () => {
      cancelled = true;
    };
  }, [context.businessId, context.error, context.loading, context.selectedSiteId, context.token]);

  if (context.loading) {
    return <section className="panel">Loading recommendations...</section>;
  }
  if (context.error) {
    return <section className="panel">Error: {context.error}</section>;
  }

  return (
    <section className="panel stack">
      <h1>Recommendation Workflow</h1>
      <label htmlFor="site-picker-recommendations">Site</label>
      <select
        id="site-picker-recommendations"
        value={context.selectedSiteId || ""}
        onChange={(event) => context.setSelectedSiteId(event.target.value)}
      >
        {context.sites.map((site) => (
          <option key={site.id} value={site.id}>
            {site.display_name}
          </option>
        ))}
      </select>

      {loadingItems ? <p>Loading recommendations...</p> : null}
      {itemsError ? <p style={{ color: "#b91c1c" }}>{itemsError}</p> : null}

      <table className="table">
        <thead>
          <tr>
            <th>Title</th>
            <th>Status</th>
            <th>Category</th>
            <th>Severity</th>
            <th>Priority</th>
            <th>Effort</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.id}>
              <td>{item.title}</td>
              <td>{item.status}</td>
              <td>{item.category}</td>
              <td>{item.severity}</td>
              <td>
                {item.priority_score} ({item.priority_band})
              </td>
              <td>{item.effort_bucket}</td>
            </tr>
          ))}
          {items.length === 0 && !loadingItems ? (
            <tr>
              <td colSpan={6}>No recommendations found for this site.</td>
            </tr>
          ) : null}
        </tbody>
      </table>
    </section>
  );
}
