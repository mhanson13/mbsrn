"use client";

import Script from "next/script";
import { useCallback, useEffect, useRef } from "react";
import { normalizeError } from "../lib/errors";

declare global {
  interface Window {
    google?: {
      accounts: {
        id: {
          initialize: (config: Record<string, unknown>) => void;
          renderButton: (element: HTMLElement, options: Record<string, unknown>) => void;
        };
      };
    };
  }
}

interface GoogleSignInProps {
  clientId: string;
  onCredential: (credential: string) => void;
  onInitializationError?: (error: {
    kind: "script_load_failed" | "script_not_ready" | "button_render_failed";
    message: string;
  }) => void;
}

export function GoogleSignIn({ clientId, onCredential, onInitializationError }: GoogleSignInProps) {
  const renderedRef = useRef(false);
  const retryTimeoutRef = useRef<number | null>(null);

  const initializeButton = useCallback((): boolean => {
    if (!clientId || renderedRef.current) {
      return true;
    }

    const googleId = window.google?.accounts?.id;
    const el = document.getElementById("google-signin-button");
    if (!googleId || !el) {
      return false;
    }

    try {
      googleId.initialize({
        client_id: clientId,
        callback: (response: { credential?: string }) => {
          if (response.credential) {
            onCredential(response.credential);
          }
        },
        auto_select: false,
      });
      googleId.renderButton(el, {
        type: "standard",
        size: "large",
        theme: "outline",
        text: "signin_with",
        shape: "pill",
      });
      renderedRef.current = true;
      return true;
    } catch (error) {
      const normalized = normalizeError(error, "Google sign-in button render failed.");
      onInitializationError?.({
        kind: "button_render_failed",
        message: normalized.message,
      });
      return true;
    }
  }, [clientId, onCredential, onInitializationError]);

  useEffect(() => {
    if (!clientId || renderedRef.current) {
      return;
    }

    let attempts = 0;
    const maxAttempts = 20;

    const attemptInitialize = () => {
      if (initializeButton()) {
        return;
      }
      attempts += 1;
      if (attempts >= maxAttempts) {
        onInitializationError?.({
          kind: "script_not_ready",
          message: "Google sign-in script did not initialize in time.",
        });
        return;
      }
      retryTimeoutRef.current = window.setTimeout(attemptInitialize, 150);
    };

    attemptInitialize();

    return () => {
      if (retryTimeoutRef.current !== null) {
        window.clearTimeout(retryTimeoutRef.current);
        retryTimeoutRef.current = null;
      }
    };
  }, [clientId, initializeButton, onInitializationError]);

  return (
    <>
      <Script
        src="https://accounts.google.com/gsi/client"
        strategy="afterInteractive"
        onLoad={() => {
          initializeButton();
        }}
        onError={() => {
          onInitializationError?.({
            kind: "script_load_failed",
            message: "Google Identity Services script failed to load.",
          });
        }}
      />
      <div id="google-signin-button" />
    </>
  );
}
