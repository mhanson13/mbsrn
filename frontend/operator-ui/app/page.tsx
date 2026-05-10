"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { GoogleSignIn } from "../components/GoogleSignIn";
import { useAuth } from "../components/AuthProvider";
import { exchangeGoogleIdToken, startGoogleAuth } from "../lib/api/client";

export default function LoginPage() {
  const router = useRouter();
  const { setSession, principal } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [redirecting, setRedirecting] = useState(false);
  const [oauthState, setOauthState] = useState<string | null>(null);
  const [oauthStateReady, setOauthStateReady] = useState(false);

  const initializeGoogleLogin = useCallback(async () => {
    setOauthStateReady(false);
    try {
      const challenge = await startGoogleAuth();
      setOauthState(challenge.state);
    } catch {
      setOauthState(null);
      setError("Sign-in initialization failed. Retry in a moment.");
    } finally {
      setOauthStateReady(true);
    }
  }, []);

  const handleExchange = useCallback(
    async (tokenValue: string) => {
      const currentState = oauthState;
      if (!currentState) {
        setError("Sign-in session is unavailable. Retry in a moment.");
        return;
      }
      setLoading(true);
      setError(null);
      let exchangeSucceeded = false;
      try {
        const result = await exchangeGoogleIdToken(tokenValue, currentState);
        exchangeSucceeded = true;
        setSession(result.access_token, result.principal, result.refresh_token);
        router.push("/dashboard");
      } catch (err) {
        setError(err instanceof Error ? err.message : "Authentication failed.");
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
              onCredential={(credential) => {
                void handleExchange(credential);
              }}
            />
          ) : (
            <p className="auth-subtitle">Preparing secure sign-in...</p>
          )}
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
