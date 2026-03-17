"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { useOperatorContext } from "../../components/useOperatorContext";
import {
  disconnectGoogleBusinessProfile,
  fetchGoogleBusinessProfileConnection,
  fetchGoogleBusinessProfileLocations,
  startGoogleBusinessProfileConnect,
} from "../../lib/api/client";
import type {
  GoogleBusinessProfileConnectionStatusResponse,
  GoogleBusinessProfileFlatLocation,
  GoogleBusinessProfileNextAction,
} from "../../lib/api/types";

type ConnectionUiState = "connected" | "needs_reconnect" | "not_connected";

export default function BusinessProfilePage() {
  const context = useOperatorContext();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState(false);
  const [connection, setConnection] = useState<GoogleBusinessProfileConnectionStatusResponse | null>(null);
  const [locations, setLocations] = useState<GoogleBusinessProfileFlatLocation[]>([]);

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
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to disconnect Google Business Profile.");
    } finally {
      setActionLoading(false);
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
                    <td>{nextActionHint(location.verification.recommended_next_action)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
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

function nextActionHint(action: GoogleBusinessProfileNextAction): string {
  if (action === "none") {
    return "No action required";
  }
  if (action === "start_verification") {
    return "Verify your business";
  }
  if (action === "complete_pending") {
    return "Complete verification";
  }
  if (action === "reconnect_google") {
    return "Reconnect Google";
  }
  return "Resolve access";
}
