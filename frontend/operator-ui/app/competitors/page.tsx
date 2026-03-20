"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { useOperatorContext } from "../../components/useOperatorContext";
import { ApiRequestError, fetchCompetitorDomains, fetchCompetitorSets } from "../../lib/api/client";
import type { CompetitorSet } from "../../lib/api/types";

interface CompetitorSetRow extends CompetitorSet {
  domain_count: number;
  active_domain_count: number;
  source_summary: string;
  latest_domain_updated_at: string | null;
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

  const totalDomainCount = useMemo(
    () => competitorSets.reduce((total, item) => total + item.domain_count, 0),
    [competitorSets],
  );
  const hasAnyDomains = useMemo(
    () => competitorSets.some((item) => item.domain_count > 0),
    [competitorSets],
  );

  function buildSetDetailHref(setItem: CompetitorSetRow): string {
    const params = new URLSearchParams();
    params.set("site_id", setItem.site_id);
    return `/competitors/${setItem.id}?${params.toString()}`;
  }

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
      setCompetitorsError(null);
      setLoadingCompetitors(false);
      return;
    }
    let cancelled = false;
    const activeSiteId = selectedSiteId;

    async function loadCompetitors() {
      setLoadingCompetitors(true);
      setCompetitorsError(null);
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

        const rows = await Promise.all(
          setResponse.items.map(async (setItem) => {
            const domainsResponse = await fetchCompetitorDomains(
              token,
              businessId,
              setItem.id,
            );
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
              ...setItem,
              domain_count: domainsResponse.total,
              active_domain_count: activeDomainCount,
              source_summary: sourceSet.size > 0 ? [...sourceSet].sort().join(", ") : "-",
              latest_domain_updated_at: latestDomainUpdatedAt,
            };
          }),
        );
        if (!cancelled) {
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
    return <section className="panel">Loading competitor intelligence...</section>;
  }
  if (contextError) {
    return <section className="panel">Unable to load tenant context. Refresh and sign in again.</section>;
  }
  if (sites.length === 0) {
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
        value={selectedSiteId || ""}
        onChange={(event) => setSelectedSiteId(event.target.value)}
      >
        {sites.map((site) => (
          <option key={site.id} value={site.id}>
            {site.display_name}
          </option>
        ))}
      </select>

      <div style={{ display: "flex", flexWrap: "wrap", gap: "0.75rem" }}>
        <span className="hint muted">Competitor Sets: {competitorSetCount}</span>
        <span className="hint muted">Domains Across Sets: {totalDomainCount}</span>
      </div>

      {loadingCompetitors ? <p className="hint muted">Loading competitors...</p> : null}
      {competitorsError ? <p className="hint error">{competitorsError}</p> : null}

      <table className="table">
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
              style={{ cursor: "pointer" }}
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
                {competitorSetCount === 0
                  ? "No competitor sets found for this site."
                  : "No competitor sets are currently visible for this site."}
              </td>
            </tr>
          ) : null}
        </tbody>
      </table>

      {!loadingCompetitors && competitorSets.length > 0 && !hasAnyDomains ? (
        <p className="hint muted">
          Competitor sets exist, but no domains are attached yet.
        </p>
      ) : null}
    </section>
  );
}

export default function CompetitorsPage() {
  return (
    <Suspense fallback={<section className="panel">Loading competitor intelligence...</section>}>
      <CompetitorsPageContent />
    </Suspense>
  );
}
