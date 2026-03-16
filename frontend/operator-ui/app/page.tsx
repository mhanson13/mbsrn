"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { GoogleSignIn } from "../components/GoogleSignIn";
import { useAuth } from "../components/AuthProvider";
import { exchangeGoogleIdToken } from "../lib/api/client";

export default function LoginPage() {
  const router = useRouter();
  const { setSession, principal } = useAuth();
  const [idToken, setIdToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleExchange = useCallback(
    async (tokenValue: string) => {
      setLoading(true);
      setError(null);
      try {
        const result = await exchangeGoogleIdToken(tokenValue);
        setSession(result.access_token, result.principal);
        router.push("/dashboard");
      } catch (err) {
        setError(err instanceof Error ? err.message : "Authentication failed.");
      } finally {
        setLoading(false);
      }
    },
    [router, setSession],
  );

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!idToken.trim()) {
      setError("Google id_token is required.");
      return;
    }
    await handleExchange(idToken.trim());
  };

  useEffect(() => {
    if (principal) {
      router.push("/dashboard");
    }
  }, [principal, router]);

  return (
    <section className="panel stack" style={{ maxWidth: 640, margin: "2rem auto" }}>
      <h1>Operator Sign In</h1>
      <p>
        Authenticate with Google, then the backend maps your Google identity (<code>sub</code>)
        to an internal principal and business scope.
      </p>

      <GoogleSignIn
        clientId={process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID || ""}
        onCredential={(credential) => {
          void handleExchange(credential);
        }}
      />

      <form onSubmit={(event) => void handleSubmit(event)} className="stack">
        <label htmlFor="idToken">Manual Google id_token exchange (fallback)</label>
        <input
          id="idToken"
          value={idToken}
          onChange={(event) => setIdToken(event.target.value)}
          placeholder="Paste Google id_token"
        />
        <button className="primary" type="submit" disabled={loading}>
          {loading ? "Signing in..." : "Exchange Token"}
        </button>
      </form>

      {error ? <p style={{ color: "#b91c1c" }}>{error}</p> : null}
    </section>
  );
}
