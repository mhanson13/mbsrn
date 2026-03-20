"use client";

import { useEffect, useState } from "react";

import { useOperatorContext } from "../../components/useOperatorContext";
import { ApiRequestError, fetchCompetitorDomains, fetchCompetitorSets } from "../../lib/api/client";
import type { CompetitorDomain } from "../../lib/api/types";

interface CompetitorRow extends CompetitorDomain {
  competitor_set_name: string;
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

export default function CompetitorsPage() {
  const context = useOperatorContext();
  const [competitors, setCompetitors] = useState<CompetitorRow[]>([]);
  const [loadingCompetitors, setLoadingCompetitors] = useState(false);
  const [competitorsError, setCompetitorsError] = useState<string | null>(null);
  const [competitorSetCount, setCompetitorSetCount] = useState(0);

  useEffect(() => {
    if (context.loading || context.error || !context.selectedSiteId) {
      setCompetitors([]);
      setCompetitorSetCount(0);
      setCompetitorsError(null);
      setLoadingCompetitors(false);
      return;
    }
    let cancelled = false;
    const selectedSiteId = context.selectedSiteId;

    async function loadCompetitors() {
      setLoadingCompetitors(true);
      setCompetitorsError(null);
      try {
        const setResponse = await fetchCompetitorSets(context.token, context.businessId, selectedSiteId);
        if (cancelled) {
          return;
        }

        setCompetitorSetCount(setResponse.total);
        if (setResponse.items.length === 0) {
          setCompetitors([]);
          return;
        }

        const domainsBySet = await Promise.all(
          setResponse.items.map((setItem) =>
            fetchCompetitorDomains(context.token, context.businessId, setItem.id),
          ),
        );
        if (cancelled) {
          return;
        }

        const setNameById = new Map(setResponse.items.map((setItem) => [setItem.id, setItem.name]));
        const merged = domainsBySet
          .flatMap((response) => response.items)
          .map((item) => ({
            ...item,
            competitor_set_name: setNameById.get(item.competitor_set_id) || item.competitor_set_id,
          }))
          .sort((a, b) => b.created_at.localeCompare(a.created_at));

        if (!cancelled) {
          setCompetitors(merged);
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
  }, [context.businessId, context.error, context.loading, context.selectedSiteId, context.token]);

  if (context.loading) {
    return <section className="panel">Loading competitor intelligence...</section>;
  }
  if (context.error) {
    return <section className="panel">Unable to load tenant context. Refresh and sign in again.</section>;
  }
  if (context.sites.length === 0) {
    return (
      <section className="panel stack">
        <h1>Competitors</h1>
        <p className="hint muted">No SEO sites are configured yet. Add a site first to view competitors.</p>
      </section>
    );
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

      {loadingCompetitors ? <p className="hint muted">Loading competitors...</p> : null}
      {competitorsError ? <p className="hint error">{competitorsError}</p> : null}

      <table className="table">
        <thead>
          <tr>
            <th>Competitor</th>
            <th>Source</th>
            <th>Business</th>
            <th>Site</th>
            <th>Set</th>
            <th>Related Audit Run</th>
            <th>Created</th>
            <th>Updated</th>
          </tr>
        </thead>
        <tbody>
          {competitors.map((item) => (
            <tr key={item.id}>
              <td>{item.display_name || item.domain}</td>
              <td>{item.source}</td>
              <td>{item.business_id}</td>
              <td>{item.site_id}</td>
              <td>{item.competitor_set_name}</td>
              <td>-</td>
              <td>{formatDateTime(item.created_at)}</td>
              <td>{formatDateTime(item.updated_at)}</td>
            </tr>
          ))}
          {!loadingCompetitors && competitors.length === 0 ? (
            <tr>
              <td colSpan={8}>
                {competitorSetCount === 0
                  ? "No competitor sets found for this site."
                  : "No competitors found in this site's competitor sets."}
              </td>
            </tr>
          ) : null}
        </tbody>
      </table>
    </section>
  );
}
