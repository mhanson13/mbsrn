import { apiBaseUrl } from "../config";
import type {
  AuthExchangeResponse,
  SEOAuditRunListResponse,
  SEOSiteListResponse,
  CompetitorSetListResponse,
  RecommendationListResponse,
  AutomationRunListResponse,
} from "./types";

async function apiRequest<T>(
  path: string,
  options: RequestInit & { token?: string } = {},
): Promise<T> {
  const { token, headers, ...rest } = options;
  let mergedHeaders: HeadersInit = {
    "Content-Type": "application/json",
    ...(headers || {}),
  };
  if (token) {
    mergedHeaders = {
      ...mergedHeaders,
      Authorization: `Bearer ${token}`,
    };
  }

  const response = await fetch(`${apiBaseUrl()}${path}`, {
    ...rest,
    headers: mergedHeaders,
    cache: "no-store",
  });

  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const payload = await response.json();
      detail = payload.detail || JSON.stringify(payload);
    } catch {
      // ignore parse failures
    }
    throw new Error(detail);
  }

  return (await response.json()) as T;
}

export async function exchangeGoogleIdToken(idToken: string): Promise<AuthExchangeResponse> {
  return apiRequest<AuthExchangeResponse>("/api/auth/google/exchange", {
    method: "POST",
    body: JSON.stringify({ id_token: idToken }),
  });
}

export async function fetchSites(token: string, businessId: string): Promise<SEOSiteListResponse> {
  return apiRequest<SEOSiteListResponse>(`/api/businesses/${businessId}/seo/sites`, { token });
}

export async function fetchAuditRuns(
  token: string,
  businessId: string,
  siteId: string,
): Promise<SEOAuditRunListResponse> {
  return apiRequest<SEOAuditRunListResponse>(
    `/api/businesses/${businessId}/seo/sites/${siteId}/audit-runs`,
    { token },
  );
}

export async function fetchCompetitorSets(
  token: string,
  businessId: string,
  siteId: string,
): Promise<CompetitorSetListResponse> {
  return apiRequest<CompetitorSetListResponse>(
    `/api/businesses/${businessId}/seo/sites/${siteId}/competitor-sets`,
    { token },
  );
}

export async function fetchRecommendations(
  token: string,
  businessId: string,
  siteId: string,
): Promise<RecommendationListResponse> {
  return apiRequest<RecommendationListResponse>(
    `/api/businesses/${businessId}/seo/sites/${siteId}/recommendations`,
    { token },
  );
}

export async function fetchAutomationRuns(
  token: string,
  businessId: string,
  siteId: string,
): Promise<AutomationRunListResponse> {
  return apiRequest<AutomationRunListResponse>(
    `/api/businesses/${businessId}/seo/sites/${siteId}/automation-runs`,
    { token },
  );
}
