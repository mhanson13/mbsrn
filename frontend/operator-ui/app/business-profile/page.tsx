"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { useOperatorContext } from "../../components/useOperatorContext";
import {
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
  const [actionLoading, setActionLoading] = useState(false);
  const [connection, setConnection] = useState<GoogleBusinessProfileConnectionStatusResponse | null>(null);
  const [locations, setLocations] = useState<GoogleBusinessProfileFlatLocation[]>([]);
  const [selectedLocationId, setSelectedLocationId] = useState<string | null>(null);
  const [verificationStatus, setVerificationStatus] = useState<GoogleBusinessProfileVerificationStatusResponse | null>(null);
  const [verificationLoading, setVerificationLoading] = useState(false);
  const [verificationActionLoading, setVerificationActionLoading] = useState(false);
  const [verificationError, setVerificationError] = useState<string | null>(null);
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
      try {
        const status = await fetchGoogleBusinessProfileVerificationStatus(context.token, locationId);
        setVerificationStatus(status);
        if (!selectedOptionId && status.available_methods.length > 0) {
          setSelectedOptionId(status.available_methods[0].option_id);
        }
      } catch (err) {
        setVerificationStatus(null);
        setVerificationError(err instanceof Error ? err.message : "Failed to load verification status.");
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
      return;
    }
    setVerificationActionLoading(true);
    setVerificationError(null);
    try {
      const action = await startGoogleBusinessProfileLocationVerification(context.token, selectedLocationId, {
        option_id: selectedOptionId,
      });
      setVerificationStatus(action.status);
      await loadData();
    } catch (err) {
      setVerificationError(err instanceof Error ? err.message : "Failed to start verification.");
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
      return;
    }
    setVerificationActionLoading(true);
    setVerificationError(null);
    try {
      const action = await completeGoogleBusinessProfileLocationVerification(context.token, selectedLocationId, {
        verification_id: verificationStatus?.current_verification?.verification_id ?? null,
        code: normalizedCode,
      });
      setVerificationStatus(action.status);
      setVerificationCode("");
      await loadData();
    } catch (err) {
      setVerificationError(err instanceof Error ? err.message : "Failed to complete verification.");
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
    try {
      const action = await retryGoogleBusinessProfileLocationVerification(context.token, selectedLocationId, {
        option_id: selectedOptionId || undefined,
      });
      setVerificationStatus(action.status);
      await loadData();
    } catch (err) {
      setVerificationError(err instanceof Error ? err.message : "Failed to retry verification.");
    } finally {
      setVerificationActionLoading(false);
    }
  }

  if (context.loading || loading) {
    return <section className="panel">Loading Google Business Profile...</section>;
  }
  if (context.error) {
    return <section className="panel">Error: {context.error}</section>;
  }

  return (
    <section className="stack">
      <div className="panel stack">
        <h1>Google Business Profile</h1>
        <p>
          Connection status:{" "}
          <span className={`badge ${connectionBadgeClass(connectionUiState)}`}>
            {connectionUiLabel(connectionUiState)}
          </span>
        </p>
        <p>
          Business scope: <code>{context.businessId}</code>
        </p>

        <div style={{ display: "flex", gap: "0.6rem", flexWrap: "wrap" }}>
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
        {error ? <p className="hint error">{error}</p> : null}
      </div>

      <div className="panel stack">
        <h2>Locations</h2>
        {connectionUiState !== "connected" ? (
          <p className="hint muted">Connect Google Business Profile to load locations.</p>
        ) : locations.length === 0 ? (
          <p className="hint muted">No locations were returned for this Google Business Profile account.</p>
        ) : (
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
                      <div style={{ fontWeight: 600 }}>{location.title}</div>
                      <div style={{ color: "#475569", fontSize: "0.85rem" }}>
                        {location.address || "No address provided"}
                      </div>
                    </td>
                    <td>{location.account_name}</td>
                    <td>
                      <span className={`badge ${badge.className}`}>{badge.label}</span>
                    </td>
                    <td>{location.verification.guidance.cta_label ?? location.verification.guidance.title}</td>
                    <td>
                      <button onClick={() => void loadVerificationStatus(location.location_id)}>
                        {selectedLocationId === location.location_id ? "Refresh status" : "Manage verification"}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {selectedLocation ? (
        <div className="panel stack">
          <h2>Verification Workflow: {selectedLocation.title}</h2>
          {verificationLoading ? <p className="hint muted">Loading verification workflow...</p> : null}
          {verificationStatus ? (
            <>
              <p>
                Workflow state: <VerificationStatusBadge state={verificationStatus.verification_state} />
              </p>
              <div className="stack" style={{ gap: "0.35rem" }}>
                <p style={{ fontWeight: 600 }}>{verificationStatus.guidance.title}</p>
                <p className="hint muted">{verificationStatus.guidance.summary}</p>
                {verificationStatus.guidance.instructions.length > 0 ? (
                  <ol style={{ margin: 0, paddingLeft: "1.1rem" }}>
                    {verificationStatus.guidance.instructions.map((item, index) => (
                      <li key={`instruction-${index}`}>{item}</li>
                    ))}
                  </ol>
                ) : null}
                {verificationStatus.guidance.tips.length > 0 ? (
                  <ul style={{ margin: 0, paddingLeft: "1.1rem" }}>
                    {verificationStatus.guidance.tips.map((item, index) => (
                      <li key={`tip-${index}`}>{item}</li>
                    ))}
                  </ul>
                ) : null}
                {verificationStatus.guidance.warnings.length > 0 ? (
                  <ul style={{ margin: 0, paddingLeft: "1.1rem", color: "#991b1b" }}>
                    {verificationStatus.guidance.warnings.map((item, index) => (
                      <li key={`warning-${index}`}>{item}</li>
                    ))}
                  </ul>
                ) : null}
                {verificationStatus.guidance.troubleshooting.length > 0 ? (
                  <ul style={{ margin: 0, paddingLeft: "1.1rem" }}>
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
        </div>
      ) : null}
    </section>
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
