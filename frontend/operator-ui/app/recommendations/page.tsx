"use client";

import { useEffect, useState } from "react";

import { useOperatorContext } from "../../components/useOperatorContext";
import { ApiRequestError, fetchRecommendations } from "../../lib/api/client";
import type { Recommendation } from "../../lib/api/types";

function deriveSourceType(item: Recommendation): string {
  if (item.audit_run_id && item.comparison_run_id) {
    return "mixed";
  }
  if (item.audit_run_id) {
    return "audit";
  }
  if (item.comparison_run_id) {
    return "comparison";
  }
  return "unknown";
}

function safeRecommendationsErrorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) {
    if (error.status === 401) {
      return "Session expired. Sign in again.";
    }
    if (error.status === 403) {
      return "You are not authorized to view recommendations.";
    }
    if (error.status === 404) {
      return "Recommendation data for the selected site was not found.";
    }
  }
  return "Unable to load recommendations right now. Please try again.";
}

export default function RecommendationsPage() {
  const context = useOperatorContext();
  const [items, setItems] = useState<Recommendation[]>([]);
  const [loadingItems, setLoadingItems] = useState(false);
  const [itemsError, setItemsError] = useState<string | null>(null);

  useEffect(() => {
    if (context.loading || context.error || !context.selectedSiteId) {
      setItems([]);
      setItemsError(null);
      setLoadingItems(false);
      return;
    }
    let cancelled = false;
    const selectedSiteId = context.selectedSiteId;

    async function loadRecommendations() {
      setLoadingItems(true);
      setItemsError(null);
      try {
        const response = await fetchRecommendations(context.token, context.businessId, selectedSiteId);
        if (!cancelled) {
          setItems(response.items);
        }
      } catch (err) {
        if (!cancelled) {
          setItemsError(safeRecommendationsErrorMessage(err));
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
    return <section className="panel">Unable to load tenant context. Refresh and sign in again.</section>;
  }
  if (context.sites.length === 0) {
    return (
      <section className="panel stack">
        <h1>Recommendation Workflow</h1>
        <p className="hint muted">No SEO sites are configured yet. Add a site first to view recommendations.</p>
      </section>
    );
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

      {loadingItems ? <p className="hint muted">Loading recommendations...</p> : null}
      {itemsError ? <p className="hint error">{itemsError}</p> : null}

      <table className="table">
        <thead>
          <tr>
            <th>Title</th>
            <th>Summary</th>
            <th>Status</th>
            <th>Category</th>
            <th>Priority</th>
            <th>Source</th>
            <th>Recommendation Run</th>
            <th>Business</th>
            <th>Site</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.id}>
              <td>{item.title}</td>
              <td>{item.rationale}</td>
              <td>{item.status}</td>
              <td>{item.category}</td>
              <td>
                {item.priority_score} ({item.priority_band})
              </td>
              <td>{deriveSourceType(item)}</td>
              <td>{item.recommendation_run_id}</td>
              <td>{item.business_id}</td>
              <td>{item.site_id}</td>
            </tr>
          ))}
          {items.length === 0 && !loadingItems ? (
            <tr>
              <td colSpan={9}>No recommendations found for this site.</td>
            </tr>
          ) : null}
        </tbody>
      </table>
    </section>
  );
}
