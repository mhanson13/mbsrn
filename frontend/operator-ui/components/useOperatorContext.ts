"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { useAuth } from "./AuthProvider";
import { fetchSites } from "../lib/api/client";
import type { SEOSite } from "../lib/api/types";

const STORAGE_SELECTED_SITE_PREFIX = "mbsrn.operator.selected_site_id";
const LEGACY_STORAGE_SELECTED_SITE_PREFIX = "workboots.operator.selected_site_id";
const OPERATOR_SITE_SELECTION_EVENT = "mbsrn:operator-site-selection";

interface OperatorContextResult {
  loading: boolean;
  error: string | null;
  scopeWarning?: string | null;
  token: string;
  businessId: string;
  sites: SEOSite[];
  selectedSiteId: string | null;
  setSelectedSiteId: (siteId: string) => void;
  refreshSites: () => Promise<SEOSite[]>;
}

function selectedSiteStorageKey(businessId: string): string {
  return `${STORAGE_SELECTED_SITE_PREFIX}.${businessId}`;
}

function readStoredSelectedSiteId(businessId: string): string | null {
  if (typeof window === "undefined") {
    return null;
  }
  const value =
    window.localStorage.getItem(selectedSiteStorageKey(businessId)) ||
    window.sessionStorage.getItem(selectedSiteStorageKey(businessId)) ||
    window.sessionStorage.getItem(`${LEGACY_STORAGE_SELECTED_SITE_PREFIX}.${businessId}`);
  return value && value.trim() ? value : null;
}

function writeStoredSelectedSiteId(
  businessId: string,
  siteId: string | null,
  options?: { broadcast?: boolean },
): void {
  if (typeof window === "undefined") {
    return;
  }
  const shouldBroadcast = options?.broadcast ?? true;
  const key = selectedSiteStorageKey(businessId);
  if (siteId && siteId.trim()) {
    window.localStorage.setItem(key, siteId);
    window.sessionStorage.setItem(key, siteId);
    window.sessionStorage.removeItem(`${LEGACY_STORAGE_SELECTED_SITE_PREFIX}.${businessId}`);
  } else {
    window.localStorage.removeItem(key);
    window.sessionStorage.removeItem(key);
    window.sessionStorage.removeItem(`${LEGACY_STORAGE_SELECTED_SITE_PREFIX}.${businessId}`);
  }
  if (shouldBroadcast) {
    window.dispatchEvent(
      new CustomEvent(OPERATOR_SITE_SELECTION_EVENT, {
        detail: { businessId, siteId },
      }),
    );
  }
}

export function useOperatorContext(): OperatorContextResult {
  const router = useRouter();
  const { token, principal, clearSession } = useAuth();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [scopeWarning, setScopeWarning] = useState<string | null>(null);
  const [sites, setSites] = useState<SEOSite[]>([]);
  const [selectedSiteId, setSelectedSiteIdState] = useState<string | null>(null);
  const selectedSiteIdRef = useRef<string | null>(null);

  const loadSites = useCallback(
    async (accessToken: string, businessId: string): Promise<SEOSite[]> => {
      setLoading(true);
      setError(null);
      try {
        const response = await fetchSites(accessToken, businessId);
        const authorizedSites = response.items.filter((site) => site.business_id === businessId);
        const removedOutOfScopeCount = response.items.length - authorizedSites.length;
        const storedSiteId = readStoredSelectedSiteId(businessId);
        const currentSelectedSiteId = selectedSiteIdRef.current;
        let resolvedSelectedSiteId: string | null = null;
        let nextScopeWarning: string | null = null;
        if (removedOutOfScopeCount > 0) {
          nextScopeWarning = "Some sites were hidden because they are outside your authorized business scope.";
        }
        if (storedSiteId && authorizedSites.some((site) => site.id === storedSiteId)) {
          resolvedSelectedSiteId = storedSiteId;
        } else if (storedSiteId) {
          nextScopeWarning = "Saved workspace site is no longer available in your authorized scope.";
        } else if (currentSelectedSiteId && authorizedSites.some((site) => site.id === currentSelectedSiteId)) {
          resolvedSelectedSiteId = currentSelectedSiteId;
        } else if (currentSelectedSiteId) {
          nextScopeWarning = "Current workspace site is no longer available in your authorized scope.";
        }
        if (!resolvedSelectedSiteId) {
          resolvedSelectedSiteId = authorizedSites.length > 0 ? authorizedSites[0].id : null;
        }
        setSites(authorizedSites);
        setSelectedSiteIdState(resolvedSelectedSiteId);
        selectedSiteIdRef.current = resolvedSelectedSiteId;
        setScopeWarning((current) => nextScopeWarning || current);
        writeStoredSelectedSiteId(businessId, resolvedSelectedSiteId, { broadcast: false });
        return authorizedSites;
      } catch (err) {
        const message = err instanceof Error ? err.message : "Failed to load SEO sites.";
        if (message.includes("Unauthorized") || message.includes("HTTP 401")) {
          clearSession();
          router.push("/");
          return [];
        }
        setError(message);
        throw err;
      } finally {
        setLoading(false);
      }
    },
    [clearSession, router],
  );

  useEffect(() => {
    if (!token || !principal) {
      clearSession();
      router.push("/");
      return;
    }
    const accessToken = token;
    const businessId = principal.business_id;

    async function runLoad() {
      try {
        await loadSites(accessToken, businessId);
      } catch {
        // Error state is already managed in loadSites.
      }
    }

    void runLoad();
  }, [clearSession, loadSites, principal, router, token]);

  const refreshSites = useCallback(async (): Promise<SEOSite[]> => {
    if (!token || !principal) {
      clearSession();
      router.push("/");
      return [];
    }
    return loadSites(token, principal.business_id);
  }, [clearSession, loadSites, principal, router, token]);

  useEffect(() => {
    selectedSiteIdRef.current = selectedSiteId;
  }, [selectedSiteId]);

  useEffect(() => {
    const businessId = principal?.business_id;
    if (!businessId || typeof window === "undefined") {
      return;
    }

    function handleSiteSelectionEvent(event: Event) {
      const customEvent = event as CustomEvent<{ businessId?: string; siteId?: string | null }>;
      const detail = customEvent.detail;
      if (!detail || detail.businessId !== businessId) {
        return;
      }
      const nextSiteId = detail.siteId || null;
      setSelectedSiteIdState((current) => {
        if (current === nextSiteId) {
          return current;
        }
        if (nextSiteId && sites.some((site) => site.id === nextSiteId)) {
          selectedSiteIdRef.current = nextSiteId;
          return nextSiteId;
        }
        if (!nextSiteId) {
          selectedSiteIdRef.current = null;
          return null;
        }
        setScopeWarning("Requested workspace site is unavailable in your authorized scope.");
        return current;
      });
    }

    window.addEventListener(OPERATOR_SITE_SELECTION_EVENT, handleSiteSelectionEvent as EventListener);
    return () => {
      window.removeEventListener(OPERATOR_SITE_SELECTION_EVENT, handleSiteSelectionEvent as EventListener);
    };
  }, [principal?.business_id, sites]);

  const setSelectedSiteId = useCallback(
    (siteId: string) => {
      const businessId = principal?.business_id;
      if (!businessId) {
        return;
      }
      const authorizedSite = sites.find((site) => site.id === siteId && site.business_id === businessId);
      if (!authorizedSite) {
        setScopeWarning("Selected workspace site is unavailable in your authorized scope.");
        return;
      }
      setScopeWarning(null);
      setSelectedSiteIdState(siteId);
      selectedSiteIdRef.current = siteId;
      writeStoredSelectedSiteId(businessId, siteId);
    },
    [principal?.business_id, sites],
  );

  return {
    loading,
    error,
    scopeWarning,
    token: token || "",
    businessId: principal?.business_id || "",
    sites,
    selectedSiteId,
    setSelectedSiteId,
    refreshSites,
  };
}
