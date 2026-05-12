"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { GoogleSignIn } from "../components/GoogleSignIn";
import { useAuth } from "../components/AuthProvider";
import { exchangeGoogleIdToken, startGoogleAuth } from "../lib/api/client";
import { normalizeError } from "../lib/errors";
import { sanitizeDiagnosticMessage } from "../lib/runtimeDiagnostics";
import { getPublicAppVersion } from "../lib/runtimeMetadata";

type RootAuthDiagnosticClassification =
  | "auth_bootstrap_invalid_response"
  | "auth_bootstrap_request_failed"
  | "auth_exchange_invalid_response"
  | "auth_exchange_failed"
  | "auth_missing_state"
  | "auth_missing_credential"
  | "gis_initialization_failed";

type GoogleSignInInitializationError = {
  kind: "script_load_failed" | "script_not_ready" | "button_render_failed";
  message: string;
};

function extractOAuthState(payload: unknown): string | null {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return null;
  }
  const candidate = payload as { state?: unknown };
  if (typeof candidate.state !== "string") {
    return null;
  }
  const normalized = candidate.state.trim();
  return normalized.length > 0 ? normalized : null;
}

function isValidExchangeResponse(payload: unknown): boolean {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return false;
  }
  const candidate = payload as {
    access_token?: unknown;
    principal?: unknown;
  };
  return typeof candidate.access_token === "string" && candidate.access_token.trim().length > 0 && !!candidate.principal;
}

function logRootAuthDiagnostic(
  classification: RootAuthDiagnosticClassification,
  message: string,
  level: "warn" | "error" = "error",
): void {
  const payload = {
    route: "/",
    classification,
    message: sanitizeDiagnosticMessage(message, "Login bootstrap failure"),
    app_version: getPublicAppVersion(),
  };
  if (level === "warn") {
    console.warn("[operator-ui] root_auth_warning", payload);
    return;
  }
  console.error("[operator-ui] root_auth_error", payload);
}

export default function LoginPage() {
  const router = useRouter();
  const { setSession, principal } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [redirecting, setRedirecting] = useState(false);
  const [oauthState, setOauthState] = useState<string | null>(null);
  const [oauthStateReady, setOauthStateReady] = useState(false);

  const handleGoogleSignInInitializationError = useCallback((issue: GoogleSignInInitializationError) => {
    logRootAuthDiagnostic("gis_initialization_failed", `${issue.kind}: ${issue.message}`, "warn");
    setError("Google sign-in is temporarily unavailable. Retry in a moment.");
  }, []);

  const initializeGoogleLogin = useCallback(async () => {
    setOauthStateReady(false);
    setError(null);
    try {
      const challenge = await startGoogleAuth();
      const nextState = extractOAuthState(challenge);
      if (!nextState) {
        logRootAuthDiagnostic(
          "auth_bootstrap_invalid_response",
          "Google auth start returned malformed state payload.",
        );
        setOauthState(null);
        setError("Sign-in initialization failed. Retry in a moment.");
        return;
      }
      setOauthState(nextState);
    } catch (error) {
      const normalized = normalizeError(error, "Sign-in initialization failed.");
      logRootAuthDiagnostic("auth_bootstrap_request_failed", normalized.message);
      setOauthState(null);
      setError("Sign-in initialization failed. Retry in a moment.");
    } finally {
      setOauthStateReady(true);
    }
  }, []);

  const handleExchange = useCallback(
    async (tokenValue: string) => {
      const normalizedToken = tokenValue.trim();
      if (!normalizedToken) {
        logRootAuthDiagnostic("auth_missing_credential", "Google credential was missing from callback payload.", "warn");
        setError("Google sign-in did not return a credential. Retry in a moment.");
        return;
      }
      const currentState = oauthState;
      if (!currentState) {
        logRootAuthDiagnostic("auth_missing_state", "Missing login state during Google credential exchange.", "warn");
        setError("Sign-in session is unavailable. Retry in a moment.");
        return;
      }
      setLoading(true);
      setError(null);
      let exchangeSucceeded = false;
      try {
        const result = await exchangeGoogleIdToken(normalizedToken, currentState);
        if (!isValidExchangeResponse(result)) {
          throw new Error("Authentication response was incomplete.");
        }
        exchangeSucceeded = true;
        setSession(result.access_token, result.principal, result.refresh_token);
        router.push("/dashboard");
      } catch (err) {
        const normalized = normalizeError(err, "Authentication failed.");
        if (normalized.message === "Authentication response was incomplete.") {
          logRootAuthDiagnostic("auth_exchange_invalid_response", normalized.message);
          setError("Authentication failed. Retry in a moment.");
        } else {
          logRootAuthDiagnostic("auth_exchange_failed", normalized.message);
          setError("Authentication failed. Retry in a moment.");
        }
      } finally {
        setLoading(false);
        if (!exchangeSucceeded) {
          await initializeGoogleLogin();
        }
      }
    },
    [oauthState, router, setSession, initializeGoogleLogin],
  );

  useEffect(() => {
    if (principal) {
      return;
    }
    void initializeGoogleLogin();
  }, [initializeGoogleLogin, principal]);

  useEffect(() => {
    if (principal) {
      setRedirecting(true);
      router.push("/dashboard");
    }
  }, [principal, router]);

  if (redirecting) {
    return (
      <section className="auth-shell">
        <div className="auth-card auth-card-compact">
          <div className="auth-status">
            <span className="spinner" aria-hidden="true" />
            <p>Finalizing your Operator Workspace session...</p>
          </div>
        </div>
      </section>
    );
  }

  return (
    <section className="auth-shell">
      <div className="auth-card">
        <div className="auth-header">
          <p className="auth-badge">My Business Sucks Right Now</p>
          <h1>Sign in to My Business Sucks Right Now</h1>
          <p className="auth-subtitle">
            MBSRN Operator Workspace. Use your approved Google identity to access business-scoped
            operator tooling, reviews, and recommendation workflows.
          </p>
        </div>

        <div className="auth-section">
          <p className="auth-section-title">Preferred sign-in</p>
          {oauthStateReady && oauthState ? (
            <GoogleSignIn
              clientId={process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID || ""}
              onInitializationError={handleGoogleSignInInitializationError}
              onCredential={(credential) => {
                void handleExchange(credential);
              }}
            />
          ) : (
            <p className="auth-subtitle">Preparing secure sign-in...</p>
          )}
          {oauthStateReady && !oauthState ? (
            <button
              type="button"
              className="button button-secondary"
              onClick={() => {
                void initializeGoogleLogin();
              }}
              disabled={loading}
            >
              Retry sign-in initialization
            </button>
          ) : null}
          {loading ? <p className="auth-subtitle">Signing in...</p> : null}
        </div>

        <div className="auth-policy-block">
          <p className="auth-policy-intro">Review our public policies before signing in:</p>
          <div className="auth-policy-links" aria-label="Legal links">
            <a href="https://www.mbsrn.com/privacy" target="_blank" rel="noreferrer">
              Privacy Policy
            </a>
            <span aria-hidden="true">·</span>
            <a href="https://www.mbsrn.com/terms" target="_blank" rel="noreferrer">
              Terms of Service
            </a>
          </div>
        </div>

        {error ? <p className="auth-error">{error}</p> : null}
      </div>
    </section>
  );
}
