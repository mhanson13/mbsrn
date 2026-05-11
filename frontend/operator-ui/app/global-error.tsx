"use client";

import { useEffect } from "react";
import { deriveErrorClassName, sanitizeDiagnosticMessage, sanitizePathname } from "../lib/runtimeDiagnostics";
import { getPublicAppVersion } from "../lib/runtimeMetadata";

type GlobalErrorClassification = "global_render_error" | "unexpected_end_of_form" | "missing_error_object";

function normalizeGlobalError(error: unknown): {
  digest: string | null;
  message: string;
  classification: GlobalErrorClassification;
} {
  if (!error || typeof error !== "object") {
    return {
      digest: null,
      message: "Global render failure",
      classification: "missing_error_object",
    };
  }

  const candidate = error as { digest?: unknown; message?: unknown };
  const digest = typeof candidate.digest === "string" && candidate.digest.trim().length > 0
    ? candidate.digest.trim()
    : null;
  const message = sanitizeDiagnosticMessage(candidate.message, "Global render failure");
  const classification = message.toLowerCase().includes("unexpected end of form")
    ? "unexpected_end_of_form"
    : "global_render_error";
  return { digest, message, classification };
}

export default function GlobalError({
  error,
  reset,
}: {
  error: unknown;
  reset: () => void;
}) {
  const appVersion = getPublicAppVersion();
  const normalizedError = normalizeGlobalError(error);
  const safePathname = sanitizePathname(typeof window === "undefined" ? null : window.location.pathname);
  const safeDigest = normalizedError.digest || "unavailable";
  const safeMessage = normalizedError.message;
  const safeClassification = normalizedError.classification;
  const safeErrorClass = deriveErrorClassName(error);

  useEffect(() => {
    const payload = {
      pathname: safePathname,
      digest: safeDigest,
      message: safeMessage,
      classification: safeClassification,
      error_class: safeErrorClass,
      app_version: appVersion,
    };
    if (safeClassification === "unexpected_end_of_form") {
      console.warn("[operator-ui] global_render_warning", payload);
      return;
    }
    console.error("[operator-ui] global_render_error", payload);
  }, [appVersion, safeClassification, safeDigest, safeErrorClass, safeMessage, safePathname]);

  return (
    <html lang="en">
      <body>
        <main className="workspace-page-shell">
          <section className="operator-page-surface" data-testid="app-global-error-fallback">
            <header className="operator-page-header">
              <h1 className="operator-page-title">Workspace unavailable</h1>
              <p className="operator-page-subtitle">
                We hit a rendering problem at the app boundary. Refresh, then try again.
              </p>
            </header>
            <div className="operator-page-actions">
              <button type="button" className="button" onClick={() => reset()}>
                Try again
              </button>
            </div>
          </section>
        </main>
      </body>
    </html>
  );
}
