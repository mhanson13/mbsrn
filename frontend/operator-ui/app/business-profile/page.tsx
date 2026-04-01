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
  fetchGoogleBusinessProfileVerificationStatus,
  retryGoogleBusinessProfileLocationVerification,
  startGoogleBusinessProfileConnect,
  startGoogleBusinessProfileLocationVerification,
} from "../../lib/api/client";
import type {
  GoogleBusinessProfileConnectionStatusResponse,
  GoogleBusinessProfileFlatLocation,
  GoogleBusinessProfileVerificationGuidance,
  GoogleBusinessProfileVerificationStatusResponse,
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

  const loadData = useCallback(async () => {
    if (!context.token) {
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
      setError(err instanceof Error ? err.message : "Failed to load Google Business Profile status.");
    } finally {
      setLoading(false);
    }
  }, [context.token]);

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
    if (context.loading || !context.token) {
      return;
    }
    void loadData();
  }, [context.loading, context.token, loadData]);

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
        message: "Google Business Profile connected successfully.",
      });
      return;
    }

    if (status === "error") {
      const reconnectRequired = (params.get("gbp_reconnect_required") || "").trim().toLowerCase() === "true";
      setCallbackNotice({
        className: "hint error",
        message: reconnectRequired
          ? "Google Business Profile connection requires reauthorization. Please reconnect."
          : "Google Business Profile connection did not complete. Please try connecting again.",
      });
      return;
    }

    setCallbackNotice(null);
  }, []);

  const selectedLocation = useMemo(
    () => locations.find((location) => location.location_id === selectedLocationId) ?? null,
    [locations, selectedLocationId],
  );

  async function handleConnect() {
    if (!context.token) {
      return;
    }
    setActionLoading(true);
    setError(null);
    try {
      const start = await startGoogleBusinessProfileConnect(context.token);
      window.location.assign(start.authorization_url);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start Google Business Profile connection.");
      setActionLoading(false);
    }
  }

  async function handleDisconnect() {
    if (!context.token) {
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
      setError(err instanceof Error ? err.message : "Failed to disconnect Google Business Profile.");
    } finally {
      setActionLoading(false);
    }
  }

  async function handleStartVerification() {
    if (!context.token || !selectedLocationId) {
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
    if (!context.token || !selectedLocationId) {
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
    if (!context.token || !selectedLocationId) {
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

  if (context.loading || loading) {
    return (
      <PageContainer width="wide" density="compact">
        <SectionCard as="div" variant="support" className="role-surface-support">
          <SectionHeader
            title="Google Business Profile"
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
            title="Google Business Profile"
            subtitle={`Error: ${context.error}`}
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
            title="Google Business Profile"
            subtitle="Connect, verify, and monitor Google Business Profile readiness for this business."
            headingLevel={1}
            variant="hero"
            meta={(
              <span className="hint muted">Business scope: <code>{context.businessId}</code></span>
            )}
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
              {connectionUiState === "connected" ? "Reconnect Google" : "Connect Google Business Profile"}
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
              This connection needs reauthorization before Google Business Profile data can be used.
            </p>
          ) : null}
          {connectionUiState === "not_connected" ? (
            <p className="hint muted">No Google Business Profile connection exists for this business.</p>
          ) : null}
          {callbackNotice ? <p className={callbackNotice.className}>{callbackNotice.message}</p> : null}
          {error ? <p className="hint error">{error}</p> : null}
        </SectionCard>
      </div>

      <SectionCard variant="summary" className="role-surface-support">
        <SectionHeader
          title="Locations"
          subtitle="Review discovered GBP locations and jump into verification workflows."
          headingLevel={2}
          variant="support"
        />
        {connectionUiState !== "connected" ? (
          <p className="hint muted">Connect Google Business Profile to load locations.</p>
        ) : locations.length === 0 ? (
          <p className="hint muted">No locations were returned for this Google Business Profile account.</p>
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
