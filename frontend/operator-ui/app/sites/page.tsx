"use client";

import Link from "next/link";
import { FormEvent, useMemo, useState } from "react";

import { useAuth } from "../../components/AuthProvider";
import { FormContainer } from "../../components/layout/FormContainer";
import {
  OperatorPageHero,
  OperatorPageSectionStack,
} from "../../components/layout/OperatorPageSurface";
import { PageContainer } from "../../components/layout/PageContainer";
import { SectionCard } from "../../components/layout/SectionCard";
import { SectionHeader } from "../../components/layout/SectionHeader";
import { SummaryStatCard } from "../../components/layout/SummaryStatCard";
import { WorkspaceMessageStack } from "../../components/layout/WorkspaceMessageStack";
import { SelectedSiteSetupIntegrationsPanel } from "../../components/sites/SelectedSiteSetupIntegrationsPanel";
import { useOperatorContext } from "../../components/useOperatorContext";
import {
  activateSite,
  ApiRequestError,
  createAuditRun,
  createSite,
  deactivateSite,
} from "../../lib/api/client";
import type { SEOSite } from "../../lib/api/types";

interface DerivedSiteStatus {
  label: string;
  badgeClass: string;
}

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

function siteSetupHref(siteId: string): string {
  return `/sites?site_id=${encodeURIComponent(siteId)}#selected-site-setup`;
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
  const [siteActionSiteId, setSiteActionSiteId] = useState<string | null>(null);
  const [siteActionError, setSiteActionError] = useState<string | null>(null);
  const [siteActionSuccess, setSiteActionSuccess] = useState<string | null>(null);

  const isAdmin = principal?.role === "admin";
  const statuses = useMemo(() => {
    return context.sites.reduce<Record<string, DerivedSiteStatus>>((acc, site) => {
      acc[site.id] = deriveSiteStatus(site);
      return acc;
    }, {});
  }, [context.sites]);
  const selectedSite = useMemo(
    () =>
      context.sites.find((site) => site.id === context.selectedSiteId)
      || context.sites[0]
      || null,
    [context.selectedSiteId, context.sites],
  );

  const activeSiteCount = context.sites.filter((site) => site.is_active).length;
  const completedAuditSiteCount = context.sites.filter(
    (site) => (site.last_audit_status || "").trim().toLowerCase() === "completed",
  ).length;
  const needsAuditSiteCount = context.sites.filter((site) => !site.last_audit_run_id).length;
  const integrationConfiguredCount = context.sites.filter((site) => Boolean((site.ga4_property_id || "").trim())).length;

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
    } catch (error) {
      setSubmitError(error instanceof Error ? error.message : "Failed to create site.");
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
    } catch (error) {
      setTriggerError(error instanceof Error ? error.message : "Failed to trigger site analysis.");
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
    } catch (error) {
      setSiteActionError(safeSiteActionErrorMessage(error));
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
      <OperatorPageHero
        title="Sites"
        subtitle="Manage site inventory, setup integrations, and route operators to the correct workflow surface."
        headingLevel={1}
        data-testid="sites-page-hero"
        summary={(
          <>
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
              label="Audit-ready"
              value={completedAuditSiteCount}
              detail={`${needsAuditSiteCount} site${needsAuditSiteCount === 1 ? "" : "s"} still need a first audit`}
              tone={completedAuditSiteCount > 0 ? "success" : "warning"}
              variant="elevated"
            />
            <SummaryStatCard
              label="Integrations configured"
              value={integrationConfiguredCount}
              detail={`${Math.max(0, context.sites.length - integrationConfiguredCount)} sites still need GA4 setup`}
              tone={integrationConfiguredCount > 0 ? "success" : "warning"}
              variant="elevated"
            />
          </>
        )}
      >
        <details className="panel panel-compact stack-tight" data-testid="sites-add-site-panel" open={context.sites.length === 0}>
          <summary className="text-strong">Add Site</summary>
          <FormContainer onSubmit={(event) => void handleCreateSite(event)}>
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
        </details>

        {submitSuccess || submitError || triggerMessage || triggerError || siteActionSuccess || siteActionError ? (
          <WorkspaceMessageStack data-testid="sites-page-message-stack">
            {submitSuccess ? <p className="hint">{submitSuccess}</p> : null}
            {submitError ? <p className="hint error">{submitError}</p> : null}
            {triggerMessage ? <p className="hint">{triggerMessage}</p> : null}
            {triggerError ? <p className="hint error">{triggerError}</p> : null}
            {siteActionSuccess ? <p className="hint">{siteActionSuccess}</p> : null}
            {siteActionError ? <p className="hint error">{siteActionError}</p> : null}
          </WorkspaceMessageStack>
        ) : null}
      </OperatorPageHero>

      <OperatorPageSectionStack>
        <SectionCard variant="summary" className="role-surface-support">
          <SectionHeader
            title="Configured Sites"
            subtitle="Inventory and setup actions. Use dedicated routes for full audit and recommendation execution."
            headingLevel={2}
            variant="support"
          />
          <div className="table-container">
            <table className="table">
              <thead>
                <tr>
                  <th>Display Name</th>
                  <th>Domain</th>
                  <th>Status</th>
                  <th>Last Audit</th>
                  <th>Workspace</th>
                  <th>Audit</th>
                  <th>Integrations</th>
                  {isAdmin ? <th>Admin Action</th> : null}
                </tr>
              </thead>
              <tbody>
                {context.sites.map((site) => (
                  <tr key={site.id}>
                    <td className="table-cell-wrap">{site.display_name}</td>
                    <td className="table-cell-wrap">{site.normalized_domain}</td>
                    <td>
                      <span className={statuses[site.id]?.badgeClass || "badge badge-muted"}>
                        {statuses[site.id]?.label || "unknown"}
                      </span>
                    </td>
                    <td>{site.last_audit_completed_at || "none"}</td>
                    <td>
                      <Link href={`/sites/${site.id}`} className="button button-secondary button-inline">
                        Open Workspace
                      </Link>
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
                    <td>
                      <Link
                        href={siteSetupHref(site.id)}
                        className="button button-secondary button-inline"
                        onClick={() => context.setSelectedSiteId(site.id)}
                      >
                        Manage Integrations
                      </Link>
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
                    <td colSpan={isAdmin ? 8 : 7}>No sites configured for this business.</td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </SectionCard>

        <SectionCard variant="support" className="role-surface-support" data-testid="sites-selected-site-routing-panel">
          <SectionHeader
            title="Selected Site Routing"
            subtitle="Use compact status and route launchers here, then execute details on dedicated workflow pages."
            headingLevel={2}
            variant="support"
          />
          {selectedSite ? (
            <div className="stack-tight" data-testid="sites-selected-site-summary">
              <p className="hint muted">
                Selected site: <strong>{selectedSite.display_name}</strong> ({selectedSite.normalized_domain})
              </p>
              <p className="hint">
                Last audit status: <strong>{selectedSite.last_audit_status || "Not run yet"}</strong>
              </p>
              <div className="row-wrap-tight">
                <Link href={`/sites/${selectedSite.id}`} className="button button-secondary button-inline">
                  Open Site Workspace
                </Link>
                <Link href="/audits" className="button button-secondary button-inline">
                  Audit Evidence
                </Link>
                <Link href="/recommendations" className="button button-secondary button-inline">
                  Recommendations
                </Link>
                <Link href={`/sites/${selectedSite.id}/migration`} className="button button-secondary button-inline">
                  Migration
                </Link>
              </div>
            </div>
          ) : (
            <p className="hint muted">Select or create a site to unlock setup and workflow routes.</p>
          )}
        </SectionCard>

        <SelectedSiteSetupIntegrationsPanel
          token={context.token}
          businessId={context.businessId}
          selectedSite={selectedSite}
          refreshSites={context.refreshSites}
        />
      </OperatorPageSectionStack>
    </PageContainer>
  );
}
