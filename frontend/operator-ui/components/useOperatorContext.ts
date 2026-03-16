"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { useAuth } from "./AuthProvider";
import { fetchSites } from "../lib/api/client";
import type { SEOSite } from "../lib/api/types";

interface OperatorContextResult {
  loading: boolean;
  error: string | null;
  token: string;
  businessId: string;
  sites: SEOSite[];
  selectedSiteId: string | null;
  setSelectedSiteId: (siteId: string) => void;
}

export function useOperatorContext(): OperatorContextResult {
  const router = useRouter();
  const { token, principal, clearSession } = useAuth();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sites, setSites] = useState<SEOSite[]>([]);
  const [selectedSiteId, setSelectedSiteIdState] = useState<string | null>(null);

  useEffect(() => {
    if (!token || !principal) {
      clearSession();
      router.push("/");
      return;
    }

    let cancelled = false;
    async function loadSites() {
      setLoading(true);
      setError(null);
      try {
        const response = await fetchSites(token, principal.business_id);
        if (cancelled) {
          return;
        }
        setSites(response.items);
        setSelectedSiteIdState((current) => {
          if (current && response.items.some((site) => site.id === current)) {
            return current;
          }
          return response.items.length > 0 ? response.items[0].id : null;
        });
      } catch (err) {
        if (!cancelled) {
          const message = err instanceof Error ? err.message : "Failed to load SEO sites.";
          if (message.includes("Unauthorized") || message.includes("HTTP 401")) {
            clearSession();
            router.push("/");
            return;
          }
          setError(message);
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void loadSites();
    return () => {
      cancelled = true;
    };
  }, [clearSession, principal, router, token]);

  return {
    loading,
    error,
    token: token || "",
    businessId: principal?.business_id || "",
    sites,
    selectedSiteId,
    setSelectedSiteId: setSelectedSiteIdState,
  };
}
