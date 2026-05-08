"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { PageContainer } from "../../components/layout/PageContainer";
import { SectionCard } from "../../components/layout/SectionCard";
import { SectionHeader } from "../../components/layout/SectionHeader";
import { SummaryStatCard } from "../../components/layout/SummaryStatCard";
import { useOperatorContext } from "../../components/useOperatorContext";
import {
  ApiRequestError,
  asVerificationErrorDetail,
  completeGoogleBusinessProfileLocationVerification,
  disconnectGoogleBusinessProfile,
  fetchGoogleBusinessProfileConnection,
  fetchGoogleBusinessProfileLocations,
  fetchSiteAnalyticsSummary,
  fetchMigrationWorkspaceSummary,
  fetchGoogleBusinessProfileVerificationStatus,
  retryGoogleBusinessProfileLocationVerification,
  startGoogleBusinessProfileConnect,
  startGoogleBusinessProfileLocationVerification,
  updateMigrationAnalyticsConfig,
  updateSite,
  upsertMigrationWorkspace,
} from "../../lib/api/client";
import type {
  GoogleBusinessProfileConnectionStatusResponse,
  GoogleBusinessProfileFlatLocation,
  GoogleBusinessProfileVerificationGuidance,
  GoogleBusinessProfileVerificationStatusResponse,
  SiteAnalyticsSummaryResponse,
} from "../../lib/api/types";
import {
  VerificationCodeEntry,
  VerificationMethodsList,
  VerificationStartAction,
  VerificationStatusBadge,
} from "./components";

type ConnectionUiState = "connected" | "needs_reconnect" | "not_connected";

export default function BusinessProfilePage() {
  const context = useOperatorContext();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [callbackNotice, setCallbackNotice] = useState<{
    className: string;
    message: string;
  } | null>(null);
  const [actionLoading, setActionLoading] = useState(false);
  const [connection, setConnection] = useState<GoogleBusinessProfileConnectionStatusResponse | null>(null);
  const [locations, setLocations] = useState<GoogleBusinessProfileFlatLocation[]>([]);
  const [selectedLocationId, setSelectedLocationId] = useState<string | null>(null);
  const [verificationStatus, setVerificationStatus] = useState<GoogleBusinessProfileVerificationStatusResponse | null>(null);
  const [verificationLoading, setVerificationLoading] = useState(false);
  const [verificationActionLoading, setVerificationActionLoading] = useState(false);
  const [verificationError, setVerificationError] = useState<string | null>(null);
  const [verificationErrorGuidance, setVerificationErrorGuidance] = useState<GoogleBusinessProfileVerificationGuidance | null>(null);
  const [selectedOptionId, setSelectedOptionId] = useState<string>("");
  const [verificationCode, setVerificationCode] = useState("");
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

  const loadData = useCallback(async () => {
    if (!context.token || !context.businessId) {
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const connectionResponse = await fetchGoogleBusinessProfileConnection(context.token);
      setConnection(connectionResponse);
      if (connectionResponse.connected && !connectionResponse.reconnect_required) {
        const locationsResponse = await fetchGoogleBusinessProfileLocations(context.token);
        setLocations(locationsResponse.locations);
      } else {
        setLocations([]);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load Google Profile status.");
    } finally {
      setLoading(false);
    }
  }, [context.token, context.businessId]);

  const loadVerificationStatus = useCallback(
    async (locationId: string) => {
      if (!context.token) {
        return;
      }
      setSelectedLocationId(locationId);
      setVerificationLoading(true);
      setVerificationError(null);
      setVerificationErrorGuidance(null);
      try {
        const status = await fetchGoogleBusinessProfileVerificationStatus(context.token, locationId);
        setVerificationStatus(status);
        if (!selectedOptionId && status.available_methods.length > 0) {
          setSelectedOptionId(status.available_methods[0].option_id);
        }
      } catch (err) {
        setVerificationStatus(null);
        const normalized = normalizeVerificationError(err, "Failed to load verification status.");
        setVerificationError(normalized.message);
        setVerificationErrorGuidance(normalized.guidance);
      } finally {
        setVerificationLoading(false);
      }
    },
    [context.token, selectedOptionId],
  );

  const refreshSelectedVerificationStatus = useCallback(async () => {
    if (!selectedLocationId || !context.token) {
      return;
    }
    await loadVerificationStatus(selectedLocationId);
  }, [context.token, loadVerificationStatus, selectedLocationId]);

  useEffect(() => {
    if (context.loading || !context.token || !context.businessId) {
      return;
    }
    void loadData();
  }, [context.businessId, context.loading, context.token, loadData]);

  const connectionUiState = useMemo<ConnectionUiState>(() => {
    if (!connection?.connected) {
      return "not_connected";
    }
    if (connection.reconnect_required) {
      return "needs_reconnect";
    }
    return "connected";
  }, [connection]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const status = (params.get("gbp_connect") || "").trim().toLowerCase();
    if (!status) {
      setCallbackNotice(null);
      return;
    }

    if (status === "success") {
      setCallbackNotice({
        className: "hint success",
        message: "Google Profile connected successfully.",
      });
      return;
    }

    if (status === "error") {
      const reconnectRequired = (params.get("gbp_reconnect_required") || "").trim().toLowerCase() === "true";
      setCallbackNotice({
        className: "hint error",
        message: reconnectRequired
          ? "Google Profile connection requires reauthorization. Please reconnect."
          : "Google Profile connection did not complete. Please try connecting again.",
      });
      return;
    }

    setCallbackNotice(null);
  }, []);

  const selectedLocation = useMemo(
    () => locations.find((location) => location.location_id === selectedLocationId) ?? null,
    [locations, selectedLocationId],
  );
  const selectedSite = useMemo(
    () =>
      context.sites.find((site) => site.id === context.selectedSiteId)
      || context.sites.find((site) => site.business_id === context.businessId)
      || null,
    [context.businessId, context.selectedSiteId, context.sites],
  );
  const normalizedGa4PropertyId = ga4PropertyIdInput.trim();
  const ga4PropertyFormatInvalid = normalizedGa4PropertyId.length > 0 && !/^\d{4,20}$/.test(normalizedGa4PropertyId);
  const selectedSiteId = selectedSite?.id || null;
  const selectedSiteGa4PropertyId = selectedSite?.ga4_property_id || null;
  const ga4HealthStatus = ga4HealthSummary?.ga4_health?.ga4_health_status
    || inferGa4HealthStatus(ga4HealthSummary);
  const ga4AuthMode = ga4HealthSummary?.ga4_health?.ga4_auth_mode || "unknown";
  const ga4HealthLabel = formatGa4HealthStatusLabel(ga4HealthStatus);
  const ga4HealthMessage = ga4HealthSummary?.ga4_health?.ga4_health_message
    || ga4DiagnosticReasonMessage(ga4HealthSummary?.ga4_error_reason)
    || "GA4 health is unavailable for this site.";
  const ga4HealthNextAction = ga4HealthNextActionMessage(ga4HealthStatus, ga4AuthMode);
  const ga4AuthModeMessage = formatGa4AuthModeMessage(ga4AuthMode);
  const ga4ScopeReconnectRecommended =
    ga4HealthStatus === "missing_oauth_scope"
    || (ga4AuthMode === "user_oauth" && connection?.ga4_scope_granted === false);

  useEffect(() => {
    setGa4PropertyIdInput(selectedSite?.ga4_property_id?.trim() || "");
  }, [selectedSite?.ga4_property_id, selectedSite?.id]);

  useEffect(() => {
    if (!context.token || !context.businessId || !selectedSiteId) {
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
        const summary = await fetchSiteAnalyticsSummary(context.token, context.businessId, selectedSiteId);
        if (!cancelled) {
          setGa4HealthSummary(summary);
        }
      } catch (err) {
        if (!cancelled) {
          setGa4HealthSummary(null);
          setGa4HealthError(err instanceof Error ? err.message : "Failed to load GA4 health.");
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
  }, [context.businessId, context.token, selectedSiteGa4PropertyId, selectedSiteId]);

  useEffect(() => {
    if (!context.token || !context.businessId || !selectedSite) {
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
        const summary = await fetchMigrationWorkspaceSummary(context.token, context.businessId, selectedSite.id);
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
      } catch (err) {
        if (!cancelled) {
          if (err instanceof ApiRequestError && err.status === 404) {
            setAnalyticsEnabled(true);
            setAnalyticsMeasurementId("");
            setAnalyticsMode("publish_and_deploy");
          } else {
            setAnalyticsSaveError(err instanceof Error ? err.message : "Failed to load analytics insertion settings.");
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
  }, [context.businessId, context.token, selectedSite]);

  async function handleConnect(options?: { includeGa4Access?: boolean }) {
    if (!context.token || !context.businessId) {
      return;
    }
    setActionLoading(true);
    setError(null);
    try {
      const start = await startGoogleBusinessProfileConnect(context.token, options);
      window.location.assign(start.authorization_url);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start Google Profile connection.");
      setActionLoading(false);
    }
  }

  async function handleDisconnect() {
    if (!context.token || !context.businessId) {
      return;
    }
    setActionLoading(true);
    setError(null);
    try {
      const result = await disconnectGoogleBusinessProfile(context.token);
      setConnection(result.connection);
      setLocations([]);
      setSelectedLocationId(null);
      setVerificationStatus(null);
      setVerificationError(null);
      setVerificationErrorGuidance(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to disconnect Google Profile.");
    } finally {
      setActionLoading(false);
    }
  }

  async function handleStartVerification() {
    if (!context.token || !context.businessId || !selectedLocationId) {
      return;
    }
    if (!selectedOptionId) {
      setVerificationError("Select a verification method first.");
      setVerificationErrorGuidance(null);
      return;
    }
    setVerificationActionLoading(true);
    setVerificationError(null);
    setVerificationErrorGuidance(null);
    try {
      const action = await startGoogleBusinessProfileLocationVerification(context.token, selectedLocationId, {
        option_id: selectedOptionId,
      });
      setVerificationStatus(action.status);
      await loadData();
    } catch (err) {
      const normalized = normalizeVerificationError(err, "Failed to start verification.");
      setVerificationError(normalized.message);
      setVerificationErrorGuidance(normalized.guidance);
    } finally {
      setVerificationActionLoading(false);
    }
  }

  async function handleCompleteVerification() {
    if (!context.token || !context.businessId || !selectedLocationId) {
      return;
    }
    const normalizedCode = verificationCode.trim();
    if (!normalizedCode) {
      setVerificationError("Enter the verification code.");
      setVerificationErrorGuidance(null);
      return;
    }
    setVerificationActionLoading(true);
    setVerificationError(null);
    setVerificationErrorGuidance(null);
    try {
      const action = await completeGoogleBusinessProfileLocationVerification(context.token, selectedLocationId, {
        verification_id: verificationStatus?.current_verification?.verification_id ?? null,
        code: normalizedCode,
      });
      setVerificationStatus(action.status);
      setVerificationCode("");
      await loadData();
    } catch (err) {
      const normalized = normalizeVerificationError(err, "Failed to complete verification.");
      setVerificationError(normalized.message);
      setVerificationErrorGuidance(normalized.guidance);
    } finally {
      setVerificationActionLoading(false);
    }
  }

  async function handleRetryVerification() {
    if (!context.token || !context.businessId || !selectedLocationId) {
      return;
    }
    setVerificationActionLoading(true);
    setVerificationError(null);
    setVerificationErrorGuidance(null);
    try {
      const action = await retryGoogleBusinessProfileLocationVerification(context.token, selectedLocationId, {
        option_id: selectedOptionId || undefined,
      });
      setVerificationStatus(action.status);
      await loadData();
    } catch (err) {
      const normalized = normalizeVerificationError(err, "Failed to retry verification.");
      setVerificationError(normalized.message);
      setVerificationErrorGuidance(normalized.guidance);
    } finally {
      setVerificationActionLoading(false);
    }
  }

  async function handleSaveGa4PropertyId() {
    if (!context.token || !context.businessId || !selectedSite) {
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
      await updateSite(context.token, context.businessId, selectedSite.id, {
        ga4_property_id: normalizedGa4PropertyId || null,
      });
      await context.refreshSites();
      setGa4SaveMessage("GA4 property saved.");
    } catch (err) {
      setGa4SaveError(err instanceof Error ? err.message : "Failed to save GA4 property.");
    } finally {
      setGa4SaveLoading(false);
    }
  }

  async function handleSaveAnalyticsSettings() {
    if (!context.token || !context.businessId || !selectedSite) {
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
      await updateMigrationAnalyticsConfig(context.token, context.businessId, selectedSite.id, payload);
      setAnalyticsSaveMessage("Analytics insertion rules saved.");
    } catch (err) {
      if (err instanceof ApiRequestError && err.status === 404) {
        try {
          await upsertMigrationWorkspace(context.token, context.businessId, selectedSite.id, {});
          await updateMigrationAnalyticsConfig(context.token, context.businessId, selectedSite.id, payload);
          setAnalyticsSaveMessage("Analytics insertion rules saved.");
        } catch (retryError) {
          setAnalyticsSaveError(
            retryError instanceof Error ? retryError.message : "Failed to save analytics insertion settings.",
          );
        }
      } else {
        setAnalyticsSaveError(err instanceof Error ? err.message : "Failed to save analytics insertion settings.");
      }
    } finally {
      setAnalyticsSaveLoading(false);
    }
  }

  if (context.loading || loading) {
    return (
      <PageContainer width="wide" density="compact">
        <SectionCard as="div" variant="support" className="role-surface-support">
          <SectionHeader
            title="Google Profile"
            subtitle="Loading connection and verification state."
            headingLevel={1}
            variant="support"
          />
        </SectionCard>
      </PageContainer>
    );
  }
  if (context.error) {
    return (
      <PageContainer width="wide" density="compact">
        <SectionCard as="div" variant="support" className="role-surface-support">
          <SectionHeader
            title="Google Profile"
            subtitle={`Error: ${context.error}`}
            headingLevel={1}
            variant="support"
          />
        </SectionCard>
      </PageContainer>
    );
  }
  if (!context.businessId) {
    return (
      <PageContainer width="wide" density="compact">
        <SectionCard as="div" variant="support" className="role-surface-support">
          <SectionHeader
            title="Google Profile"
            subtitle="Business context is unavailable for this session."
            headingLevel={1}
            variant="support"
          />
        </SectionCard>
      </PageContainer>
    );
  }

  return (
    <PageContainer width="wide" density="compact">
      <div className="role-dashboard-landing">
        <SectionCard variant="primary" className="role-dashboard-hero">
          <SectionHeader
            title="Google Profile"
            subtitle="Connect, verify, and monitor Google Profile readiness for this business."
            headingLevel={1}
            variant="hero"
          />
          <div className="workspace-summary-strip role-summary-strip">
            <SummaryStatCard
              label="Connection"
              value={connectionUiLabel(connectionUiState)}
              detail={connectionUiState === "connected" ? "Google account linked" : "Connection requires operator action"}
              tone={connectionUiState === "connected" ? "success" : "warning"}
              variant="elevated"
            />
            <SummaryStatCard
              label="Usability"
              value={connection?.token_status || "unknown"}
              detail={connection?.required_scopes_satisfied ? "Required scopes granted" : "Scope review needed"}
              tone={connection?.required_scopes_satisfied ? "success" : "warning"}
              variant="elevated"
            />
            <SummaryStatCard
              label="Locations"
              value={locations.length}
              detail={locations.length > 0 ? "Fetched from Google account" : "No locations currently loaded"}
              tone={locations.length > 0 ? "neutral" : "warning"}
              variant="elevated"
            />
          </div>
          <p>
            Connection status:{" "}
            <span className={`badge ${connectionBadgeClass(connectionUiState)}`}>
              {connectionUiLabel(connectionUiState)}
            </span>
          </p>
          <div className="row-wrap-tight">
            <button className="primary" onClick={() => void handleConnect()} disabled={actionLoading}>
              {connectionUiState === "connected" ? "Reconnect Google Profile" : "Connect Google Profile"}
            </button>
            {connectionUiState === "connected" ? (
              <button onClick={() => void handleDisconnect()} disabled={actionLoading}>
                Disconnect
              </button>
            ) : null}
            <button onClick={() => void loadData()} disabled={actionLoading}>
              Refresh
            </button>
          </div>
          {connectionUiState === "needs_reconnect" ? (
            <p className="hint warning">
              This connection needs reauthorization before Google Profile data can be used.
            </p>
          ) : null}
          {connectionUiState === "not_connected" ? (
            <p className="hint muted">No Google Profile connection exists.</p>
          ) : null}
          {callbackNotice ? <p className={callbackNotice.className}>{callbackNotice.message}</p> : null}
          {error ? <p className="hint error">{error}</p> : null}
        </SectionCard>
      </div>

      <SectionCard variant="summary" className="role-surface-support">
        <SectionHeader
          title="GA4 Setup"
          subtitle="Configure GA4 property connection for the currently selected site from the Google Profile surface."
          headingLevel={2}
          variant="support"
        />
        {selectedSite ? (
          <div className="stack-tight">
            <p className="hint muted">
              Site: <strong>{selectedSite.display_name}</strong> ({selectedSite.normalized_domain})
            </p>
            <label className="stack-tight" htmlFor="google-profile-ga4-property-id">
              <span className="hint muted">GA4 property ID (numeric)</span>
              <input
                id="google-profile-ga4-property-id"
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
            <p className="hint muted">
              Enter the numeric GA4 property ID for this site (not the G- measurement ID).
            </p>
            <div className="panel panel-compact stack-tight" data-testid="google-profile-ga4-health">
              <div className="link-row">
                <strong>GA4 property health</strong>
                <span className={`badge ${ga4HealthBadgeClass(ga4HealthStatus)}`}>{ga4HealthLabel}</span>
              </div>
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
          </div>
        ) : (
          <p className="hint muted">
            Select a site in the global site selector to configure GA4 property connection.
          </p>
        )}
      </SectionCard>

      <SectionCard variant="summary" className="role-surface-support">
        <SectionHeader
          title="Analytics Insertion Rules"
          subtitle="Configure site-wide migration analytics insertion from the Google Profile surface."
          headingLevel={2}
          variant="support"
        />
        {selectedSite ? (
          <div className="stack-tight">
            <p className="hint muted">
              Site: <strong>{selectedSite.display_name}</strong> ({selectedSite.normalized_domain})
            </p>
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
            <label className="stack-tight" htmlFor="google-profile-analytics-measurement-id">
              <span className="hint muted">GA measurement ID</span>
              <input
                id="google-profile-analytics-measurement-id"
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
            <label className="stack-tight" htmlFor="google-profile-analytics-mode">
              <span className="hint muted">Insertion mode</span>
              <select
                id="google-profile-analytics-mode"
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
            <p className="hint muted">
              These settings are site-wide and used by migration publish/deploy controls.
            </p>
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
          </div>
        ) : (
          <p className="hint muted">
            Select a site in the global site selector to configure analytics insertion rules.
          </p>
        )}
      </SectionCard>

      <SectionCard variant="summary" className="role-surface-support">
        <SectionHeader
          title="Locations"
          subtitle="Review discovered GBP locations and jump into verification workflows."
          headingLevel={2}
          variant="support"
        />
        {connectionUiState !== "connected" ? (
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
                  <th>Verification</th>
                </tr>
              </thead>
              <tbody>
                {locations.map((location) => {
                  const badge = locationBadge(location);
                  return (
                    <tr key={`${location.account_id}:${location.location_id}`}>
                      <td>
                        <div className="text-strong">{location.title}</div>
                        <div className="text-muted-small">
                          {location.address || "No address provided"}
                        </div>
                      </td>
                      <td>{location.account_name}</td>
                      <td>
                        <span className={`badge ${badge.className}`}>{badge.label}</span>
                      </td>
                      <td>{location.verification.guidance.cta_label ?? location.verification.guidance.title}</td>
                      <td>
                        <button type="button" onClick={() => void loadVerificationStatus(location.location_id)}>
                          {selectedLocationId === location.location_id ? "Refresh status" : "Manage verification"}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </SectionCard>

      {selectedLocation ? (
        <SectionCard variant="support" className="role-surface-support">
          <SectionHeader
            title={`Verification Workflow: ${selectedLocation.title}`}
            subtitle="Use the guided flow below to start, complete, or retry Google verification."
            headingLevel={2}
            variant="support"
          />
          {verificationLoading ? <p className="hint muted">Loading verification workflow...</p> : null}
          {verificationStatus ? (
            <>
              <p>
                Workflow state: <VerificationStatusBadge state={verificationStatus.verification_state} />
              </p>
              <div className="stack-tight">
                <p className="text-strong">{verificationStatus.guidance.title}</p>
                <p className="hint muted">{verificationStatus.guidance.summary}</p>
                {verificationStatus.guidance.instructions.length > 0 ? (
                  <ol className="list-compact-reset">
                    {verificationStatus.guidance.instructions.map((item, index) => (
                      <li key={`instruction-${index}`}>{item}</li>
                    ))}
                  </ol>
                ) : null}
                {verificationStatus.guidance.tips.length > 0 ? (
                  <ul className="list-compact-reset">
                    {verificationStatus.guidance.tips.map((item, index) => (
                      <li key={`tip-${index}`}>{item}</li>
                    ))}
                  </ul>
                ) : null}
                {verificationStatus.guidance.warnings.length > 0 ? (
                  <ul className="list-compact-reset list-warning">
                    {verificationStatus.guidance.warnings.map((item, index) => (
                      <li key={`warning-${index}`}>{item}</li>
                    ))}
                  </ul>
                ) : null}
                {verificationStatus.guidance.troubleshooting.length > 0 ? (
                  <ul className="list-compact-reset">
                    {verificationStatus.guidance.troubleshooting.map((item, index) => (
                      <li key={`troubleshooting-${index}`}>{item}</li>
                    ))}
                  </ul>
                ) : null}
              </div>
              <p className="hint muted">{verificationStatus.message}</p>
              <VerificationMethodsList
                methods={verificationStatus.available_methods}
                selectedOptionId={selectedOptionId}
                onChange={setSelectedOptionId}
                disabled={verificationActionLoading}
              />
              <VerificationStartAction
                onStart={() => void handleStartVerification()}
                onRetry={() => void handleRetryVerification()}
                onRefresh={() => void refreshSelectedVerificationStatus()}
                disabledStart={verificationActionLoading || !selectedOptionId}
                disabledRetry={verificationActionLoading || verificationStatus.available_methods.length === 0}
                disabledRefresh={verificationActionLoading}
              />
              <VerificationCodeEntry
                code={verificationCode}
                actionRequired={verificationStatus.action_required}
                onCodeChange={setVerificationCode}
                onSubmit={() => void handleCompleteVerification()}
                disabled={verificationActionLoading}
              />
            </>
          ) : null}
          {verificationError ? <p className="hint error">{verificationError}</p> : null}
          {verificationErrorGuidance ? (
            <div className="stack-tight">
              <p className="text-strong">{verificationErrorGuidance.title}</p>
              <p className="hint muted">{verificationErrorGuidance.summary}</p>
              {verificationErrorGuidance.instructions.length > 0 ? (
                <ol className="list-compact-reset">
                  {verificationErrorGuidance.instructions.map((item, index) => (
                    <li key={`error-instruction-${index}`}>{item}</li>
                  ))}
                </ol>
              ) : null}
            </div>
          ) : null}
        </SectionCard>
      ) : null}
    </PageContainer>
  );
}

function connectionUiLabel(state: ConnectionUiState): string {
  if (state === "connected") {
    return "Connected";
  }
  if (state === "needs_reconnect") {
    return "Needs reconnect";
  }
  return "Not connected";
}

function connectionBadgeClass(state: ConnectionUiState): string {
  if (state === "connected") {
    return "badge-success";
  }
  if (state === "needs_reconnect") {
    return "badge-warn";
  }
  return "badge-muted";
}

function locationBadge(location: GoogleBusinessProfileFlatLocation): { label: string; className: string } {
  if (
    location.verification.state_summary === "unknown" &&
    location.verification.recommended_next_action === "resolve_access"
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
  const status = (summary.ga4_status || "").trim().toLowerCase();
  const reason = (summary.ga4_error_reason || "").trim().toLowerCase();
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
  if (reason === "access_denied") {
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

function normalizeVerificationError(
  error: unknown,
  fallbackMessage: string,
): { message: string; guidance: GoogleBusinessProfileVerificationGuidance | null } {
  if (error instanceof ApiRequestError) {
    const parsed = asVerificationErrorDetail(error.detail);
    if (parsed) {
      return {
        message: parsed.message,
        guidance: parsed.guidance ?? null,
      };
    }
    return { message: error.message, guidance: null };
  }
  if (error instanceof Error) {
    return { message: error.message, guidance: null };
  }
  return { message: fallbackMessage, guidance: null };
}
