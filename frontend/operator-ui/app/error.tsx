"use client";

import { useEffect } from "react";
import { usePathname } from "next/navigation";
import { deriveErrorClassName, sanitizeDiagnosticMessage, sanitizePathname } from "../lib/runtimeDiagnostics";
import { getPublicAppVersion } from "../lib/runtimeMetadata";

type RouteErrorClassification =
  | "route_render_error"
  | "unexpected_end_of_form"
  | "missing_error_object"
  | "stale_server_action_build_mismatch";

function isStaleServerActionBuildMismatch(message: string): boolean {
  const normalized = message.toLowerCase();
  return (
    normalized.includes("failed to find server action") ||
    (normalized.includes("older or newer deployment") && normalized.includes("workers"))
  );
}

type NormalizedRouteError = {
  digest: string | null;
  message: string;
  classification: RouteErrorClassification;
};

function normalizeRouteError(error: unknown): NormalizedRouteError {
  if (!error || typeof error !== "object") {
    return {
      digest: null,
      message: "Route render failure",
      classification: "missing_error_object",
    };
  }

  const candidate = error as { digest?: unknown; message?: unknown };
  const digest = typeof candidate.digest === "string" && candidate.digest.trim().length > 0
    ? candidate.digest.trim()
    : null;
  const message = sanitizeDiagnosticMessage(candidate.message, "Route render failure");
  let classification: RouteErrorClassification = "route_render_error";
  if (message.toLowerCase().includes("unexpected end of form")) {
    classification = "unexpected_end_of_form";
  } else if (isStaleServerActionBuildMismatch(message)) {
    classification = "stale_server_action_build_mismatch";
  }

  return { digest, message, classification };
}

export default function Error({
  error,
  reset,
}: {
  error: unknown;
  reset: () => void;
}) {
  const pathname = usePathname();
  const appVersion = getPublicAppVersion();
  const normalizedError = normalizeRouteError(error);
  const safePathname = sanitizePathname(pathname);
  const safeDigest = normalizedError.digest || "unavailable";
  const safeMessage = normalizedError.message;
  const safeClassification = normalizedError.classification;
  const safeErrorClass = deriveErrorClassName(error);

  useEffect(() => {
    const logPayload = {
      pathname: safePathname,
      digest: safeDigest,
      message: safeMessage,
      classification: safeClassification,
      error_class: safeErrorClass,
      app_version: appVersion,
    };
    if (safeClassification === "unexpected_end_of_form") {
      console.warn("[operator-ui] route_render_warning", logPayload);
      return;
    }
    if (safeClassification === "stale_server_action_build_mismatch") {
      console.warn("[operator-ui] route_render_warning", logPayload);
      return;
    }
    console.error("[operator-ui] route_render_error", logPayload);
  }, [appVersion, safeClassification, safeDigest, safeErrorClass, safeMessage, safePathname]);

  return (
    <main className="workspace-page-shell">
      <section className="operator-page-surface" data-testid="app-route-error-fallback">
        <header className="operator-page-header">
          <h1 className="operator-page-title">Workspace unavailable</h1>
          <p className="operator-page-subtitle">
            {safeClassification === "stale_server_action_build_mismatch"
              ? "The app was updated. Refresh and retry."
              : "We hit a rendering problem for this page. Try again, or refresh if the issue continues."}
          </p>
        </header>
        <div className="operator-page-actions">
          <button type="button" className="button" onClick={() => reset()}>
            Try again
          </button>
        </div>
      </section>
    </main>
  );
}
