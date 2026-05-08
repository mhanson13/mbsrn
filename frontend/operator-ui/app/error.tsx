"use client";

import { useEffect } from "react";
import { usePathname } from "next/navigation";

type RouteError = Error & { digest?: string | null };

export default function Error({
  error,
  reset,
}: {
  error: RouteError | null;
  reset: () => void;
}) {
  const pathname = usePathname();
  const digest = typeof error?.digest === "string" ? error.digest : null;
  const safeMessage = typeof error?.message === "string" && error.message.trim().length > 0
    ? error.message.trim().slice(0, 160)
    : "Route render failure";

  useEffect(() => {
    console.error("[operator-ui] route_render_error", {
      pathname: pathname || "unknown",
      digest: digest || "unavailable",
      message: safeMessage,
    });
  }, [pathname, digest, safeMessage]);

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
