"use client";

import { createContext, useContext, useEffect, useMemo, useState } from "react";
import type { AuthPrincipal } from "../lib/api/types";

const STORAGE_TOKEN = "workboots.operator.token";
const STORAGE_PRINCIPAL = "workboots.operator.principal";

interface AuthState {
  token: string | null;
  principal: AuthPrincipal | null;
  setSession: (token: string, principal: AuthPrincipal) => void;
  clearSession: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const [principal, setPrincipal] = useState<AuthPrincipal | null>(null);

  useEffect(() => {
    const storedToken = window.localStorage.getItem(STORAGE_TOKEN);
    const storedPrincipal = window.localStorage.getItem(STORAGE_PRINCIPAL);
    if (storedToken) {
      setToken(storedToken);
    }
    if (storedPrincipal) {
      try {
        setPrincipal(JSON.parse(storedPrincipal) as AuthPrincipal);
      } catch {
        window.localStorage.removeItem(STORAGE_PRINCIPAL);
      }
    }
  }, []);

  const value = useMemo<AuthState>(() => {
    return {
      token,
      principal,
      setSession: (nextToken: string, nextPrincipal: AuthPrincipal) => {
        setToken(nextToken);
        setPrincipal(nextPrincipal);
        window.localStorage.setItem(STORAGE_TOKEN, nextToken);
        window.localStorage.setItem(STORAGE_PRINCIPAL, JSON.stringify(nextPrincipal));
      },
      clearSession: () => {
        setToken(null);
        setPrincipal(null);
        window.localStorage.removeItem(STORAGE_TOKEN);
        window.localStorage.removeItem(STORAGE_PRINCIPAL);
      },
    };
  }, [token, principal]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const value = useContext(AuthContext);
  if (!value) {
    throw new Error("AuthProvider is required.");
  }
  return value;
}
