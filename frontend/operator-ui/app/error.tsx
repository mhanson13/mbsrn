"use client";

import { useEffect } from "react";
import { usePathname } from "next/navigation";

type RouteErrorClassification = "route_render_error" | "unexpected_end_of_form" | "missing_error_object";

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
  const message = typeof candidate.message === "string" && candidate.message.trim().length > 0
    ? candidate.message.trim().slice(0, 160)
    : "Route render failure";
  const classification = message.toLowerCase().includes("unexpected end of form")
    ? "unexpected_end_of_form"
    : "route_render_error";

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
  const normalizedError = normalizeRouteError(error);
  const safePathname = pathname || "unknown";
  const safeDigest = normalizedError.digest || "unavailable";
  const safeMessage = normalizedError.message;
  const safeClassification = normalizedError.classification;

  useEffect(() => {
    const logPayload = {
      pathname: safePathname,
      digest: safeDigest,
      message: safeMessage,
      classification: safeClassification,
    };
    if (safeClassification === "unexpected_end_of_form") {
      console.warn("[operator-ui] route_render_warning", logPayload);
      return;
    }
    console.error("[operator-ui] route_render_error", logPayload);
  }, [safeClassification, safeDigest, safeMessage, safePathname]);

  return (
    <main className="workspace-page-shell">
      <section className="operator-page-surface" data-testid="app-route-error-fallback">
        <header className="operator-page-header">
          <h1 className="operator-page-title">Workspace unavailable</h1>
          <p className="operator-page-subtitle">
            We hit a rendering problem for this page. Try again, or refresh if the issue continues.
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
