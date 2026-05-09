"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";

import { SectionCard } from "../layout/SectionCard";
import { SectionHeader } from "../layout/SectionHeader";
import {
  ApiRequestError,
  disconnectGoogleBusinessProfile,
  fetchGoogleBusinessProfileConnection,
  fetchGoogleBusinessProfileLocations,
  fetchMigrationWorkspaceSummary,
  fetchSiteAnalyticsSummary,
  startGoogleBusinessProfileConnect,
  updateMigrationAnalyticsConfig,
  updateSite,
  upsertMigrationWorkspace,
} from "../../lib/api/client";
import type {
  GoogleBusinessProfileConnectionStatusResponse,
  GoogleBusinessProfileFlatLocation,
  SEOSite,
  SiteAnalyticsSummaryResponse,
} from "../../lib/api/types";

type SelectedSiteSetupIntegrationsPanelProps = {
  token: string;
  businessId: string;
  selectedSite: SEOSite | null;
  refreshSites: () => Promise<SEOSite[]>;
};

type ConnectionUiState =
  | "connected_usable"
  | "connected_access_denied"
  | "oauth_success_pending"
  | "not_connected"
  | "unavailable";
type CallbackNotice = { className: string; message: string } | null;

export function SelectedSiteSetupIntegrationsPanel({
  token,
  businessId,
  selectedSite,
  refreshSites,
}: SelectedSiteSetupIntegrationsPanelProps) {
  const searchParams = useSearchParams();
  const [loadingConnection, setLoadingConnection] = useState(true);
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const [connection, setConnection] = useState<GoogleBusinessProfileConnectionStatusResponse | null>(null);
  const [locations, setLocations] = useState<GoogleBusinessProfileFlatLocation[]>([]);
  const [locationAccessDenied, setLocationAccessDenied] = useState(false);
  const [actionLoading, setActionLoading] = useState(false);

  const [ga4PropertyIdInput, setGa4PropertyIdInput] = useState("");
  const [ga4SaveMessage, setGa4SaveMessage] = useState<string | null>(null);
  const [ga4SaveError, setGa4SaveError] = useState<string | null>(null);
  const [ga4SaveLoading, setGa4SaveLoading] = useState(false);
  const [ga4HealthSummary, setGa4HealthSummary] = useState<SiteAnalyticsSummaryResponse | null>(null);
  const [ga4HealthLoading, setGa4HealthLoading] = useState(false);
  const [ga4HealthError, setGa4HealthError] = useState<string | null>(null);

  const [analyticsEnabled, setAnalyticsEnabled] = useState(true);
  const [analyticsMeasurementId, setAnalyticsMeasurementId] = useState("");
  const [analyticsMode, setAnalyticsMode] = useState<"publish_only" | "publish_and_deploy">("publish_and_deploy");
  const [analyticsLoading, setAnalyticsLoading] = useState(false);
  const [analyticsSaveMessage, setAnalyticsSaveMessage] = useState<string | null>(null);
  const [analyticsSaveError, setAnalyticsSaveError] = useState<string | null>(null);
  const [analyticsSaveLoading, setAnalyticsSaveLoading] = useState(false);

  const selectedSiteId = selectedSite?.id || null;

  const loadConnectionState = useCallback(async () => {
    if (!token || !businessId) {
      return;
    }
    setLoadingConnection(true);
    setConnectionError(null);
    setLocationAccessDenied(false);
    try {
      const connectionResponse = await fetchGoogleBusinessProfileConnection(token);
      setConnection(connectionResponse);
      const canLoadLocations = connectionResponse.connected
        && !connectionResponse.reconnect_required
        && connectionResponse.required_scopes_satisfied
        && connectionResponse.token_status === "usable";
      if (canLoadLocations) {
        try {
          const locationsResponse = await fetchGoogleBusinessProfileLocations(token);
          setLocations(locationsResponse.locations);
        } catch (error) {
          const message = error instanceof Error ? error.message : "Failed to load Google setup status.";
          setLocations([]);
          setConnectionError(message);
          setLocationAccessDenied(isGbpAccessDeniedMessage(message));
        }
      } else {
        setLocations([]);
      }
    } catch (error) {
      setConnectionError(error instanceof Error ? error.message : "Failed to load Google setup status.");
      setConnection(null);
      setLocations([]);
    } finally {
      setLoadingConnection(false);
    }
  }, [businessId, token]);

  useEffect(() => {
    if (!token || !businessId) {
      return;
    }
    void loadConnectionState();
  }, [businessId, loadConnectionState, token]);

  useEffect(() => {
    setGa4PropertyIdInput(selectedSite?.ga4_property_id?.trim() || "");
  }, [selectedSite?.ga4_property_id, selectedSite?.id]);

  useEffect(() => {
    if (!token || !businessId || !selectedSiteId) {
      setGa4HealthSummary(null);
      setGa4HealthError(null);
      setGa4HealthLoading(false);
      return;
    }
    let cancelled = false;
    const loadGa4Health = async () => {
      setGa4HealthLoading(true);
      setGa4HealthError(null);
      try {
        const summary = await fetchSiteAnalyticsSummary(token, businessId, selectedSiteId);
        if (!cancelled) {
          setGa4HealthSummary(summary);
        }
      } catch (error) {
        if (!cancelled) {
          setGa4HealthSummary(null);
          setGa4HealthError(error instanceof Error ? error.message : "Failed to load GA4 health.");
        }
      } finally {
        if (!cancelled) {
          setGa4HealthLoading(false);
        }
      }
    };
    void loadGa4Health();
    return () => {
      cancelled = true;
    };
  }, [businessId, selectedSiteId, selectedSite?.ga4_property_id, token]);

  useEffect(() => {
    if (!token || !businessId || !selectedSite) {
      setAnalyticsEnabled(true);
      setAnalyticsMeasurementId("");
      setAnalyticsMode("publish_and_deploy");
      setAnalyticsLoading(false);
      return;
    }
    let cancelled = false;
    const loadAnalyticsSettings = async () => {
      setAnalyticsLoading(true);
      setAnalyticsSaveError(null);
      setAnalyticsSaveMessage(null);
      try {
        const summary = await fetchMigrationWorkspaceSummary(token, businessId, selectedSite.id);
        const analyticsConfig =
          summary.workspace.analytics_config_json && typeof summary.workspace.analytics_config_json === "object"
            ? (summary.workspace.analytics_config_json as Record<string, unknown>)
            : {};
        const publishReadiness =
          summary.publish_readiness && typeof summary.publish_readiness === "object"
            ? (summary.publish_readiness as Record<string, unknown>)
            : {};
        const deployReadiness =
          summary.deploy_readiness && typeof summary.deploy_readiness === "object"
            ? (summary.deploy_readiness as Record<string, unknown>)
            : {};
        const workspaceMeasurement = String(analyticsConfig.ga_measurement_id || "").trim();
        const readinessWorkspaceMeasurement =
          String(publishReadiness.workspace_ga_measurement_id || "").trim()
          || String(deployReadiness.workspace_ga_measurement_id || "").trim();
        const readinessSiteMeasurement =
          String(publishReadiness.site_ga_measurement_id || "").trim()
          || String(deployReadiness.site_ga_measurement_id || "").trim();
        const nextMode = String(analyticsConfig.insertion_mode || "").trim();

        if (!cancelled) {
          setAnalyticsEnabled(analyticsConfig.enabled !== false);
          setAnalyticsMeasurementId(workspaceMeasurement || readinessWorkspaceMeasurement || readinessSiteMeasurement);
          setAnalyticsMode(nextMode === "publish_only" ? "publish_only" : "publish_and_deploy");
        }
      } catch (error) {
        if (!cancelled) {
          if (error instanceof ApiRequestError && error.status === 404) {
            setAnalyticsEnabled(true);
            setAnalyticsMeasurementId("");
            setAnalyticsMode("publish_and_deploy");
          } else {
            setAnalyticsSaveError(error instanceof Error ? error.message : "Failed to load analytics insertion settings.");
          }
        }
      } finally {
        if (!cancelled) {
          setAnalyticsLoading(false);
        }
      }
    };
    void loadAnalyticsSettings();
    return () => {
      cancelled = true;
    };
  }, [businessId, selectedSite, token]);

  const oauthConnectStatus = normalizeLowerCaseString(searchParams?.get("gbp_connect"));
  const oauthConnectSucceeded = oauthConnectStatus === "success";
  const oauthConnectFailed = oauthConnectStatus === "error";
  const oauthReconnectRequired = normalizeLowerCaseString(searchParams?.get("gbp_reconnect_required")) === "true";
  const tokenIndicatesAccessDenied =
    connection?.connected === true
    && (
      connection.token_status === "insufficient_scope"
      || connection.required_scopes_satisfied === false
    );
  const gbpAccessDenied = locationAccessDenied || tokenIndicatesAccessDenied;

  const connectionUiState = useMemo<ConnectionUiState>(() => {
    if (oauthConnectSucceeded && loadingConnection) {
      return "oauth_success_pending";
    }
    if (connection?.connected && !connection.reconnect_required && !gbpAccessDenied) {
      return "connected_usable";
    }
    if (connection?.connected && !connection.reconnect_required && gbpAccessDenied) {
      return "connected_access_denied";
    }
    if (connectionError && !connection) {
      return "unavailable";
    }
    return "not_connected";
  }, [connection, connectionError, gbpAccessDenied, loadingConnection, oauthConnectSucceeded]);

  const callbackNotice = useMemo<CallbackNotice>(() => {
    if (oauthConnectSucceeded) {
      if (connectionUiState === "connected_usable") {
        return {
          className: "hint success",
          message: "Google returned successfully and Google Profile is connected.",
        };
      }
      if (connectionUiState === "connected_access_denied") {
        return {
          className: "hint error",
          message: "Google returned successfully, but Google Business Profile access is denied for this account.",
        };
      }
      if (connectionUiState === "oauth_success_pending") {
        return null;
      }
      if (connectionUiState === "unavailable") {
        return {
          className: "hint warning",
          message: "Returned from Google, but connection status is temporarily unavailable. Refresh to verify.",
        };
      }
      return {
        className: "hint warning",
        message: "Google returned successfully, but no usable Google Business Profile connection was detected.",
      };
    }
    if (oauthConnectFailed) {
      return {
        className: "hint error",
        message: oauthReconnectRequired
          ? "Google Profile connection requires reauthorization. Please reconnect."
          : "Google Profile connection did not complete. Please try connecting again.",
      };
    }
    return null;
  }, [connectionUiState, oauthConnectFailed, oauthConnectSucceeded, oauthReconnectRequired]);
  const hasConnectedToken = connection?.connected === true;
  const showConnectionErrorDetails = Boolean(connectionError) && connectionUiState !== "connected_access_denied";

  const normalizedGa4PropertyId = ga4PropertyIdInput.trim();
  const ga4PropertyFormatInvalid = normalizedGa4PropertyId.length > 0 && !/^\d{4,20}$/.test(normalizedGa4PropertyId);
  const ga4HealthStatus = ga4HealthSummary?.ga4_health?.ga4_health_status || inferGa4HealthStatus(ga4HealthSummary);
  const ga4AuthMode = normalizeGa4AuthMode(ga4HealthSummary?.ga4_health?.ga4_auth_mode);
  const ga4HealthLabel = formatGa4HealthStatusLabel(ga4HealthStatus);
  const ga4HealthMessage = ga4HealthSummary?.ga4_health?.ga4_health_message
    || ga4DiagnosticReasonMessage(ga4HealthSummary?.ga4_error_reason)
    || "GA4 health is unavailable for this site.";
  const ga4HealthNextAction = ga4HealthNextActionMessage(ga4HealthStatus, ga4AuthMode);
  const ga4AuthModeMessage = formatGa4AuthModeMessage(ga4AuthMode);
  const ga4ScopeReconnectRecommended =
    ga4HealthStatus === "missing_oauth_scope"
    || (ga4AuthMode === "user_oauth" && connection?.ga4_scope_granted === false);

  async function handleConnect(options?: { includeGa4Access?: boolean }) {
    if (!token || !businessId) {
      return;
    }
    setActionLoading(true);
    setConnectionError(null);
    try {
      const start = await startGoogleBusinessProfileConnect(token, options);
      window.location.assign(start.authorization_url);
    } catch (error) {
      setConnectionError(error instanceof Error ? error.message : "Failed to start Google Profile connection.");
      setActionLoading(false);
    }
  }

  async function handleDisconnect() {
    if (!token || !businessId) {
      return;
    }
    setActionLoading(true);
    setConnectionError(null);
    try {
      const result = await disconnectGoogleBusinessProfile(token);
      setConnection(result.connection);
      setLocations([]);
    } catch (error) {
      setConnectionError(error instanceof Error ? error.message : "Failed to disconnect Google Profile.");
    } finally {
      setActionLoading(false);
    }
  }

  async function handleSaveGa4PropertyId() {
    if (!token || !businessId || !selectedSite) {
      return;
    }
    if (ga4PropertyFormatInvalid) {
      setGa4SaveError("Use only the numeric GA4 property ID (for example, 123456789).");
      setGa4SaveMessage(null);
      return;
    }
    setGa4SaveLoading(true);
    setGa4SaveError(null);
    setGa4SaveMessage(null);
    try {
      await updateSite(token, businessId, selectedSite.id, {
        ga4_property_id: normalizedGa4PropertyId || null,
      });
      await refreshSites();
      setGa4SaveMessage("GA4 property saved.");
    } catch (error) {
      setGa4SaveError(error instanceof Error ? error.message : "Failed to save GA4 property.");
    } finally {
      setGa4SaveLoading(false);
    }
  }

  async function handleSaveAnalyticsSettings() {
    if (!token || !businessId || !selectedSite) {
      return;
    }
    setAnalyticsSaveLoading(true);
    setAnalyticsSaveError(null);
    setAnalyticsSaveMessage(null);
    const payload = {
      analytics_config: {
        enabled: analyticsEnabled,
        ga_measurement_id: analyticsMeasurementId.trim() || null,
        insertion_mode: analyticsMode,
      },
    } as const;

    try {
      await updateMigrationAnalyticsConfig(token, businessId, selectedSite.id, payload);
      setAnalyticsSaveMessage("Analytics insertion rules saved.");
    } catch (error) {
      if (error instanceof ApiRequestError && error.status === 404) {
        try {
          await upsertMigrationWorkspace(token, businessId, selectedSite.id, {});
          await updateMigrationAnalyticsConfig(token, businessId, selectedSite.id, payload);
          setAnalyticsSaveMessage("Analytics insertion rules saved.");
        } catch (retryError) {
          setAnalyticsSaveError(
            retryError instanceof Error ? retryError.message : "Failed to save analytics insertion settings.",
          );
        }
      } else {
        setAnalyticsSaveError(error instanceof Error ? error.message : "Failed to save analytics insertion settings.");
      }
    } finally {
      setAnalyticsSaveLoading(false);
    }
  }

  return (
    <SectionCard id="selected-site-setup" variant="support" className="role-surface-support" data-testid="sites-selected-site-setup">
      <SectionHeader
        title="Selected Site Setup"
        subtitle="Google profile connection, GA4 property health, analytics insertion rules, and location status for the selected site."
        headingLevel={2}
        variant="support"
      />

      {selectedSite ? (
        <p className="hint muted" data-testid="sites-selected-site-context">
          Site: <strong>{selectedSite.display_name}</strong> ({selectedSite.normalized_domain})
        </p>
      ) : (
        <p className="hint muted" data-testid="sites-selected-site-context">
          Select a site in the global site selector to manage integrations.
        </p>
      )}

      <div className="stack">
        <div className="panel panel-compact stack-tight" data-testid="sites-google-profile-connection-panel">
          <div className="link-row">
            <strong>Google Profile</strong>
            <span className={`badge ${connectionBadgeClass(connectionUiState)}`}>{connectionUiLabel(connectionUiState)}</span>
          </div>
          <p className="hint muted">
            {connectionPrimaryMessage(connectionUiState, connection)}
          </p>
          <div className="row-wrap-tight">
            <button className="button button-primary" type="button" onClick={() => void handleConnect()} disabled={actionLoading}>
              {hasConnectedToken ? "Reconnect Google Profile" : "Connect Google Profile"}
            </button>
            {hasConnectedToken ? (
              <button type="button" onClick={() => void handleDisconnect()} disabled={actionLoading}>
                Disconnect
              </button>
            ) : null}
            <button type="button" onClick={() => void loadConnectionState()} disabled={actionLoading || loadingConnection}>
              {loadingConnection ? "Refreshing..." : "Refresh"}
            </button>
          </div>
          {connection?.reconnect_required ? (
            <p className="hint warning">This connection needs reauthorization before Google Profile data can be used.</p>
          ) : null}
          {connectionUiState === "connected_access_denied" ? (
            <p className="hint error">Google Business Profile access is denied for this Google account.</p>
          ) : null}
          {callbackNotice ? <p className={callbackNotice.className}>{callbackNotice.message}</p> : null}
          {showConnectionErrorDetails ? <p className="hint error">{connectionError}</p> : null}
        </div>

        <div className="panel panel-compact stack-tight" data-testid="sites-ga4-setup-panel">
          <div className="link-row">
            <strong>GA4 Setup</strong>
            <span className={`badge ${ga4HealthBadgeClass(ga4HealthStatus)}`}>{ga4HealthLabel}</span>
          </div>
          {selectedSite ? (
            <>
              <label className="stack-tight" htmlFor="sites-ga4-property-id">
                <span className="hint muted">GA4 property ID (numeric)</span>
                <input
                  id="sites-ga4-property-id"
                  type="text"
                  value={ga4PropertyIdInput}
                  onChange={(event) => {
                    setGa4PropertyIdInput(event.target.value);
                    setGa4SaveError(null);
                    setGa4SaveMessage(null);
                  }}
                  placeholder="123456789"
                />
              </label>
              <p className="hint muted">Enter the numeric GA4 property ID for this site (not the G- measurement ID).</p>
              <div className="panel panel-compact stack-tight" data-testid="sites-ga4-health">
                <strong>GA4 property health</strong>
                {ga4HealthLoading ? <p className="hint muted">Checking GA4 property health...</p> : null}
                <p className="hint muted">{ga4HealthMessage}</p>
                <p className="hint muted">{ga4AuthModeMessage}</p>
                {ga4HealthNextAction ? <p className="hint muted">{ga4HealthNextAction}</p> : null}
                {ga4HealthError ? <p className="hint error">{ga4HealthError}</p> : null}
              </div>
              {ga4PropertyFormatInvalid ? (
                <p className="hint warning">Use only the numeric GA4 property ID (for example, 123456789).</p>
              ) : null}
              {ga4SaveMessage ? <p className="hint success">{ga4SaveMessage}</p> : null}
              {ga4SaveError ? <p className="hint error">{ga4SaveError}</p> : null}
              <div className="row-wrap-tight">
                <button
                  className="button button-primary"
                  type="button"
                  onClick={() => void handleSaveGa4PropertyId()}
                  disabled={ga4SaveLoading || ga4PropertyFormatInvalid}
                >
                  {ga4SaveLoading ? "Saving..." : "Save GA4 Property"}
                </button>
                {ga4ScopeReconnectRecommended ? (
                  <button
                    className="button"
                    type="button"
                    onClick={() => void handleConnect({ includeGa4Access: true })}
                    disabled={actionLoading}
                  >
                    Reconnect Google with GA4 access
                  </button>
                ) : null}
              </div>
            </>
          ) : (
            <p className="hint muted">Select a site to configure GA4 property connection.</p>
          )}
        </div>

        <div className="panel panel-compact stack-tight" data-testid="sites-analytics-insertion-panel">
          <strong>Analytics Insertion Rules</strong>
          {selectedSite ? (
            <>
              {analyticsLoading ? <p className="hint muted">Loading analytics insertion settings...</p> : null}
              <label className="link-row">
                <input
                  type="checkbox"
                  checked={analyticsEnabled}
                  onChange={(event) => setAnalyticsEnabled(event.target.checked)}
                  disabled={analyticsLoading || analyticsSaveLoading}
                />
                <span>Enable controlled analytics insertion for migration publish/deploy</span>
              </label>
              <label className="stack-tight" htmlFor="sites-analytics-measurement-id">
                <span className="hint muted">GA measurement ID</span>
                <input
                  id="sites-analytics-measurement-id"
                  value={analyticsMeasurementId}
                  onChange={(event) => {
                    setAnalyticsMeasurementId(event.target.value);
                    setAnalyticsSaveError(null);
                    setAnalyticsSaveMessage(null);
                  }}
                  placeholder="G-XXXXXXX"
                  disabled={analyticsLoading || analyticsSaveLoading}
                />
              </label>
              <label className="stack-tight" htmlFor="sites-analytics-mode">
                <span className="hint muted">Insertion mode</span>
                <select
                  id="sites-analytics-mode"
                  value={analyticsMode}
                  onChange={(event) =>
                    setAnalyticsMode(event.target.value === "publish_only" ? "publish_only" : "publish_and_deploy")
                  }
                  disabled={analyticsLoading || analyticsSaveLoading}
                >
                  <option value="publish_and_deploy">Insert during publish and deploy</option>
                  <option value="publish_only">Insert during publish only</option>
                </select>
              </label>
              <p className="hint muted">These settings are site-wide and used by migration publish/deploy controls.</p>
              {analyticsSaveMessage ? <p className="hint success">{analyticsSaveMessage}</p> : null}
              {analyticsSaveError ? <p className="hint error">{analyticsSaveError}</p> : null}
              <div className="row-wrap-tight">
                <button
                  className="button button-primary"
                  type="button"
                  onClick={() => void handleSaveAnalyticsSettings()}
                  disabled={analyticsLoading || analyticsSaveLoading}
                >
                  {analyticsSaveLoading ? "Saving..." : "Save Analytics Rules"}
                </button>
              </div>
            </>
          ) : (
            <p className="hint muted">Select a site to configure analytics insertion rules.</p>
          )}
        </div>

        <div className="panel panel-compact stack-tight" data-testid="sites-gbp-locations-panel">
          <strong>Google Business Profile Locations</strong>
          {connectionUiState === "connected_access_denied" ? (
            <p className="hint error">Google Business Profile access is denied for this Google account.</p>
          ) : connectionUiState !== "connected_usable" ? (
            <p className="hint muted">Connect Google Profile to load locations.</p>
          ) : locations.length === 0 ? (
            <p className="hint muted">No locations were returned for this Google Profile account.</p>
          ) : (
            <div className="table-container">
              <table className="table">
                <thead>
                  <tr>
                    <th>Location</th>
                    <th>Account</th>
                    <th>Status</th>
                    <th>Next action</th>
                  </tr>
                </thead>
                <tbody>
                  {locations.map((location) => {
                    const badge = locationBadge(location);
                    return (
                      <tr key={`${location.account_id}:${location.location_id}`}>
                        <td>
                          <div className="text-strong">{location.title}</div>
                          <div className="text-muted-small">{location.address || "No address provided"}</div>
                        </td>
                        <td>{location.account_name}</td>
                        <td>
                          <span className={`badge ${badge.className}`}>{badge.label}</span>
                        </td>
                        <td>{location.verification.guidance.cta_label ?? location.verification.guidance.title}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </SectionCard>
  );
}

function connectionUiLabel(state: ConnectionUiState): string {
  if (state === "connected_usable") {
    return "Connected";
  }
  if (state === "connected_access_denied") {
    return "Access denied";
  }
  if (state === "oauth_success_pending") {
    return "Checking";
  }
  if (state === "unavailable") {
    return "Unavailable";
  }
  return "Not connected";
}

function connectionBadgeClass(state: ConnectionUiState): string {
  if (state === "connected_usable") {
    return "badge-success";
  }
  if (state === "oauth_success_pending") {
    return "badge-warn";
  }
  if (state === "not_connected") {
    return "badge-muted";
  }
  return "badge-error";
}

function connectionPrimaryMessage(
  state: ConnectionUiState,
  connection: GoogleBusinessProfileConnectionStatusResponse | null,
): string {
  if (state === "connected_usable") {
    return "Google account linked.";
  }
  if (state === "connected_access_denied") {
    return "Google account is linked, but Google Business Profile access is denied for this account.";
  }
  if (state === "oauth_success_pending") {
    return "Returned from Google; checking connection status.";
  }
  if (state === "unavailable") {
    return "Google connection status is temporarily unavailable.";
  }
  if (connection?.reconnect_required) {
    return "Google connection needs reconnect.";
  }
  return "No Google connection for this business yet.";
}

function locationBadge(location: GoogleBusinessProfileFlatLocation): { label: string; className: string } {
  if (
    location.verification.state_summary === "unknown"
    && location.verification.recommended_next_action === "resolve_access"
  ) {
    return { label: "Access issue", className: "badge-error" };
  }
  if (location.verification.state_summary === "verified") {
    return { label: "Verified", className: "badge-success" };
  }
  if (location.verification.state_summary === "pending") {
    return { label: "Pending", className: "badge-warn" };
  }
  if (location.verification.state_summary === "unverified") {
    return { label: "Not verified", className: "badge-muted" };
  }
  return { label: "Unknown", className: "badge-muted" };
}

function normalizeLowerCaseString(value: unknown): string {
  return typeof value === "string" ? value.trim().toLowerCase() : "";
}

function isGbpAccessDeniedMessage(message: string): boolean {
  const normalized = normalizeLowerCaseString(message);
  return (
    normalized.includes("google business profile access is denied")
    || normalized.includes("permission denied")
    || normalized.includes("access denied")
    || normalized.includes("insufficient_scope")
    || normalized.includes("insufficient scope")
  );
}

function normalizeGa4AuthMode(
  value: unknown,
): "user_oauth" | "service_account" | "adc" | "mock" | "unavailable" | "unknown" {
  const normalized = normalizeLowerCaseString(value);
  if (
    normalized === "user_oauth"
    || normalized === "service_account"
    || normalized === "adc"
    || normalized === "mock"
    || normalized === "unavailable"
  ) {
    return normalized;
  }
  return "unknown";
}

function inferGa4HealthStatus(
  summary: SiteAnalyticsSummaryResponse | null,
):
  | "configured"
  | "not_configured"
  | "reachable"
  | "unavailable"
  | "missing_oauth_scope"
  | "permission_denied"
  | "invalid_property"
  | "no_data"
  | "unknown" {
  if (!summary) {
    return "unknown";
  }
  const status = normalizeLowerCaseString(summary.ga4_status);
  const reason = normalizeLowerCaseString(summary.ga4_error_reason);
  if (status === "connected") {
    return reason === "no_data" ? "no_data" : "reachable";
  }
  if (status === "configured") {
    return "configured";
  }
  if (status === "not_configured") {
    return "not_configured";
  }
  if (reason === "missing_oauth_scope") {
    return "missing_oauth_scope";
  }
  if (reason === "access_denied" || reason === "permission_denied") {
    return "permission_denied";
  }
  if (reason === "property_not_found" || reason === "invalid_property_format") {
    return "invalid_property";
  }
  if (status === "error") {
    return "unavailable";
  }
  return "unknown";
}

function formatGa4HealthStatusLabel(
  status:
    | "configured"
    | "not_configured"
    | "reachable"
    | "unavailable"
    | "missing_oauth_scope"
    | "permission_denied"
    | "invalid_property"
    | "no_data"
    | "unknown",
): string {
  if (status === "not_configured") {
    return "Not configured";
  }
  if (status === "configured") {
    return "Configured";
  }
  if (status === "reachable") {
    return "Reachable";
  }
  if (status === "no_data") {
    return "No recent data";
  }
  if (status === "missing_oauth_scope") {
    return "GA4 authorization missing";
  }
  if (status === "permission_denied") {
    return "Permission issue";
  }
  if (status === "invalid_property") {
    return "Invalid property";
  }
  if (status === "unavailable") {
    return "Temporarily unavailable";
  }
  return "Unknown";
}

function ga4HealthBadgeClass(
  status:
    | "configured"
    | "not_configured"
    | "reachable"
    | "unavailable"
    | "missing_oauth_scope"
    | "permission_denied"
    | "invalid_property"
    | "no_data"
    | "unknown",
): string {
  if (status === "reachable") {
    return "badge-success";
  }
  if (status === "configured" || status === "no_data" || status === "missing_oauth_scope") {
    return "badge-warn";
  }
  if (status === "not_configured" || status === "unknown") {
    return "badge-muted";
  }
  return "badge-error";
}

function ga4DiagnosticReasonMessage(
  reason: SiteAnalyticsSummaryResponse["ga4_error_reason"] | null | undefined,
): string | null {
  if (!reason) {
    return null;
  }
  if (reason === "not_configured") {
    return "Add a GA4 property ID for this site.";
  }
  if (reason === "access_denied" || reason === "permission_denied") {
    return "Verify the connected Google account can read this GA4 property.";
  }
  if (reason === "missing_oauth_scope") {
    return "GA4 authorization is missing. Reconnect Google with Analytics read-only access.";
  }
  if (reason === "property_not_found") {
    return "The configured GA4 property was not found.";
  }
  if (reason === "invalid_property_format") {
    return "Use only the numeric GA4 property ID (for example, 123456789).";
  }
  if (reason === "no_data") {
    return "GA4 is reachable, but no recent data was returned.";
  }
  return "GA4 is temporarily unavailable for this site.";
}

function ga4HealthNextActionMessage(
  status:
    | "configured"
    | "not_configured"
    | "reachable"
    | "unavailable"
    | "missing_oauth_scope"
    | "permission_denied"
    | "invalid_property"
    | "no_data"
    | "unknown",
  authMode: "user_oauth" | "service_account" | "adc" | "mock" | "unavailable" | "unknown",
): string | null {
  if (status === "not_configured") {
    return "Next: Add a GA4 property ID for this site.";
  }
  if (status === "missing_oauth_scope") {
    if (authMode === "user_oauth") {
      return "Next: Reconnect Google with Analytics read-only access.";
    }
    return "Next: Verify runtime GA4 credentials include Analytics read-only scope.";
  }
  if (status === "permission_denied") {
    if (authMode === "service_account") {
      return "Next: Grant the configured service account Viewer access to this GA4 property.";
    }
    if (authMode === "adc") {
      return "Next: Grant the runtime Google identity Viewer access to this GA4 property.";
    }
    return "Next: Grant the connected Google account or service account Viewer access to this GA4 property.";
  }
  if (status === "invalid_property") {
    return "Next: Save a valid numeric GA4 property ID for this site.";
  }
  if (status === "no_data") {
    return "Next: Confirm this property has traffic in the selected date range.";
  }
  if (status === "unavailable") {
    return "Next: Retry after a short delay and verify workspace GA4 credentials.";
  }
  return null;
}

function formatGa4AuthModeMessage(
  authMode: "user_oauth" | "service_account" | "adc" | "mock" | "unavailable" | "unknown",
): string {
  if (authMode === "user_oauth") {
    return "GA4 auth mode: Connected Google account OAuth token.";
  }
  if (authMode === "service_account") {
    return "GA4 auth mode: Service account credentials.";
  }
  if (authMode === "adc") {
    return "GA4 auth mode: Application Default Credentials.";
  }
  if (authMode === "mock") {
    return "GA4 auth mode: Mock provider (test/runtime fallback).";
  }
  if (authMode === "unavailable") {
    return "GA4 auth mode: Unavailable.";
  }
  return "GA4 auth mode: Unknown.";
}
