"use client";

import type { MigrationSourceCapture, MigrationSourceCaptureMode } from "../../lib/api/types";
import { WorkspaceActionBar } from "../layout/WorkspaceActionBar";

interface SourceCaptureControlsProps {
  sourceUrl: string;
  mode: MigrationSourceCaptureMode;
  authorizationAcknowledged: boolean;
  latestCapture: MigrationSourceCapture | null;
  busy: boolean;
  onSourceUrlChange: (value: string) => void;
  onModeChange: (value: MigrationSourceCaptureMode) => void;
  onAuthorizationChange: (value: boolean) => void;
  onStart: () => void;
  onRefresh: () => void;
}

function captureStatusLabel(capture: MigrationSourceCapture): string {
  if (capture.status === "queued") {
    return "Queued for capture";
  }
  if (capture.status === "running") {
    return capture.mode === "faithful_snapshot" ? "Rendering pages" : "Analyzing source";
  }
  if (capture.status === "completed") {
    return "Source baseline ready";
  }
  return "Action required";
}

function captureModeLabel(mode: MigrationSourceCaptureMode): string {
  return mode === "faithful_snapshot" ? "Faithful browser snapshot" : "Analyze and rebuild";
}

export function SourceCaptureControls({
  sourceUrl,
  mode,
  authorizationAcknowledged,
  latestCapture,
  busy,
  onSourceUrlChange,
  onModeChange,
  onAuthorizationChange,
  onStart,
  onRefresh,
}: SourceCaptureControlsProps): JSX.Element {
  const authorizationRequired = mode === "faithful_snapshot";
  const startDisabled = busy || !sourceUrl.trim() || (authorizationRequired && !authorizationAcknowledged);
  return (
    <div className="panel stack workspace-section-block" data-testid="migration-source-capture-controls">
      <h3>Source Ingest</h3>
      <label className="stack-tight">
        <span className="hint muted">Source URL</span>
        <input
          type="url"
          value={sourceUrl}
          placeholder="https://example.com/"
          onChange={(event) => onSourceUrlChange(event.target.value)}
        />
      </label>
      <label className="stack-tight">
        <span className="hint muted">Ingestion mode</span>
        <select
          value={mode}
          onChange={(event) => onModeChange(event.target.value as MigrationSourceCaptureMode)}
        >
          <option value="analyze_rebuild">Analyze and rebuild</option>
          <option value="faithful_snapshot">Faithful browser snapshot</option>
        </select>
      </label>
      <span className="hint muted">
        {authorizationRequired
          ? "Chromium renders bounded first-party pages and stores an immutable baseline before AI improvements."
          : "Captures bounded source signals for a new AI-generated site."}
      </span>
      {authorizationRequired ? (
        <label className="hint stack-tight" data-testid="faithful-capture-authorization">
          <span>
            <input
              type="checkbox"
              checked={authorizationAcknowledged}
              onChange={(event) => onAuthorizationChange(event.target.checked)}
            />{" "}
            I confirm that I am authorized to capture and reproduce this website’s content.
          </span>
          <span className="hint muted">
            External domains, authentication, commerce backends, uploads, streaming media, and server-side forms are not copied.
          </span>
        </label>
      ) : null}
      <WorkspaceActionBar variant="primary">
        <button type="button" className="button button-primary" onClick={onStart} disabled={startDisabled}>
          {busy ? "Starting..." : authorizationRequired ? "Start faithful snapshot" : "Start source analysis"}
        </button>
        {latestCapture ? (
          <button type="button" className="button button-tertiary" onClick={onRefresh} disabled={busy}>
            Refresh status
          </button>
        ) : null}
      </WorkspaceActionBar>
      {latestCapture ? (
        <div className="panel panel-compact stack-tight" data-testid="migration-source-capture-status">
          <strong>{captureStatusLabel(latestCapture)}</strong>
          <span className="hint muted">
            {captureModeLabel(latestCapture.mode)} · source version {latestCapture.source_version}
          </span>
          {latestCapture.status === "completed" ? (
            <span className="hint">
              {latestCapture.page_count} pages · {latestCapture.asset_count} first-party assets ·{" "}
              {latestCapture.total_bytes.toLocaleString()} bytes
            </span>
          ) : null}
          {latestCapture.status === "failed" ? (
            <span className="hint warning">
              {latestCapture.failure_message || "Source capture failed. Review the reason and retry."}
            </span>
          ) : null}
          {latestCapture.unsupported_features.length > 0 || latestCapture.warning_codes.length > 0 ? (
            <details className="workspace-details-shell">
              <summary>Review capture limitations</summary>
              <div className="stack-tight">
                {latestCapture.unsupported_features.map((item) => (
                  <span key={`unsupported-${item}`} className="hint warning">
                    {item.replace(/_/g, " ")}
                  </span>
                ))}
                {latestCapture.warning_codes.map((item) => (
                  <span key={`warning-${item}`} className="hint muted">
                    {item.replace(/_/g, " ")}
                  </span>
                ))}
              </div>
            </details>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
