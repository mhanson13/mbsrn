"use client";

import { useEffect } from "react";

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
  const message = typeof candidate.message === "string" && candidate.message.trim().length > 0
    ? candidate.message.trim().slice(0, 160)
    : "Global render failure";
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
  const normalizedError = normalizeGlobalError(error);
  const safeDigest = normalizedError.digest || "unavailable";
  const safeMessage = normalizedError.message;
  const safeClassification = normalizedError.classification;

  useEffect(() => {
    const payload = {
      digest: safeDigest,
      message: safeMessage,
      classification: safeClassification,
    };
    if (safeClassification === "unexpected_end_of_form") {
      console.warn("[operator-ui] global_render_warning", payload);
      return;
    }
    console.error("[operator-ui] global_render_error", payload);
  }, [safeClassification, safeDigest, safeMessage]);

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

