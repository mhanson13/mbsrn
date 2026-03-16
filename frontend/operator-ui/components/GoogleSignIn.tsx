"use client";

import Script from "next/script";
import { useEffect, useRef } from "react";

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
}

export function GoogleSignIn({ clientId, onCredential }: GoogleSignInProps) {
  const renderedRef = useRef(false);

  useEffect(() => {
    if (!clientId || renderedRef.current || !window.google) {
      return;
    }
    const el = document.getElementById("google-signin-button");
    if (!el) {
      return;
    }

    window.google.accounts.id.initialize({
      client_id: clientId,
      callback: (response: { credential?: string }) => {
        if (response.credential) {
          onCredential(response.credential);
        }
      },
      auto_select: false,
    });
    window.google.accounts.id.renderButton(el, {
      type: "standard",
      size: "large",
      theme: "outline",
      text: "signin_with",
      shape: "pill",
    });
    renderedRef.current = true;
  }, [clientId, onCredential]);

  return (
    <>
      <Script src="https://accounts.google.com/gsi/client" strategy="afterInteractive" />
      <div id="google-signin-button" />
    </>
  );
}
