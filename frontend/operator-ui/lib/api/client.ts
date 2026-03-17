import { apiBaseUrl } from "../config";
import type {
  AuthExchangeResponse,
  SEOAuditRunListResponse,
  SEOSiteListResponse,
  CompetitorSetListResponse,
  RecommendationListResponse,
  AutomationRunListResponse,
  GoogleBusinessProfileAccountsResponse,
  GoogleBusinessProfileConnectionStatusResponse,
  GoogleBusinessProfileVerificationActionResponse,
  GoogleBusinessProfileVerificationOptionsResponse,
  GoogleBusinessProfileVerificationStatusResponse,
  GoogleBusinessProfileConnectStartResponse,
  GoogleBusinessProfileCompleteVerificationRequest,
  GoogleBusinessProfileDisconnectResponse,
  GoogleBusinessProfileLocationsResponse,
  GoogleBusinessProfileLocationVerification,
  GoogleBusinessProfileStartVerificationRequest,
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
      detail = formatErrorDetail(payload);
    } catch {
      // ignore parse failures
    }
    throw new Error(detail);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export async function exchangeGoogleIdToken(idToken: string): Promise<AuthExchangeResponse> {
  return apiRequest<AuthExchangeResponse>("/api/auth/google/exchange", {
    method: "POST",
    body: JSON.stringify({ id_token: idToken }),
  });
}

export async function logoutSession(token: string, refreshToken?: string): Promise<void> {
  await apiRequest<void>("/api/auth/logout", {
    method: "POST",
    token,
    body: JSON.stringify({ refresh_token: refreshToken ?? null }),
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

export async function fetchGoogleBusinessProfileConnection(
  token: string,
): Promise<GoogleBusinessProfileConnectionStatusResponse> {
  return apiRequest<GoogleBusinessProfileConnectionStatusResponse>(
    "/api/integrations/google/business-profile/connection",
    { token },
  );
}

export async function startGoogleBusinessProfileConnect(
  token: string,
): Promise<GoogleBusinessProfileConnectStartResponse> {
  return apiRequest<GoogleBusinessProfileConnectStartResponse>(
    "/api/integrations/google/business-profile/connect/start",
    {
      method: "POST",
      token,
    },
  );
}

export async function disconnectGoogleBusinessProfile(
  token: string,
): Promise<GoogleBusinessProfileDisconnectResponse> {
  return apiRequest<GoogleBusinessProfileDisconnectResponse>(
    "/api/integrations/google/business-profile/disconnect",
    {
      method: "POST",
      token,
    },
  );
}

export async function fetchGoogleBusinessProfileAccounts(
  token: string,
): Promise<GoogleBusinessProfileAccountsResponse> {
  return apiRequest<GoogleBusinessProfileAccountsResponse>(
    "/api/integrations/google/business-profile/accounts",
    { token },
  );
}

export async function fetchGoogleBusinessProfileLocations(
  token: string,
): Promise<GoogleBusinessProfileLocationsResponse> {
  return apiRequest<GoogleBusinessProfileLocationsResponse>(
    "/api/integrations/google/business-profile/locations",
    { token },
  );
}

export async function fetchGoogleBusinessProfileLocationVerification(
  token: string,
  locationId: string,
): Promise<GoogleBusinessProfileLocationVerification> {
  return apiRequest<GoogleBusinessProfileLocationVerification>(
    `/api/integrations/google/business-profile/locations/${locationId}/verification`,
    { token },
  );
}

export async function fetchGoogleBusinessProfileVerificationOptions(
  token: string,
  locationId: string,
): Promise<GoogleBusinessProfileVerificationOptionsResponse> {
  return apiRequest<GoogleBusinessProfileVerificationOptionsResponse>(
    `/api/integrations/google/business-profile/locations/${locationId}/verification/options`,
    { token },
  );
}

export async function fetchGoogleBusinessProfileVerificationStatus(
  token: string,
  locationId: string,
): Promise<GoogleBusinessProfileVerificationStatusResponse> {
  return apiRequest<GoogleBusinessProfileVerificationStatusResponse>(
    `/api/integrations/google/business-profile/locations/${locationId}/verification/status`,
    { token },
  );
}

export async function startGoogleBusinessProfileLocationVerification(
  token: string,
  locationId: string,
  payload: GoogleBusinessProfileStartVerificationRequest,
): Promise<GoogleBusinessProfileVerificationActionResponse> {
  return apiRequest<GoogleBusinessProfileVerificationActionResponse>(
    `/api/integrations/google/business-profile/locations/${locationId}/verification/start`,
    {
      method: "POST",
      token,
      body: JSON.stringify(payload),
    },
  );
}

export async function completeGoogleBusinessProfileLocationVerification(
  token: string,
  locationId: string,
  payload: GoogleBusinessProfileCompleteVerificationRequest,
): Promise<GoogleBusinessProfileVerificationActionResponse> {
  return apiRequest<GoogleBusinessProfileVerificationActionResponse>(
    `/api/integrations/google/business-profile/locations/${locationId}/verification/complete`,
    {
      method: "POST",
      token,
      body: JSON.stringify(payload),
    },
  );
}

export async function retryGoogleBusinessProfileLocationVerification(
  token: string,
  locationId: string,
  payload: GoogleBusinessProfileStartVerificationRequest = {},
): Promise<GoogleBusinessProfileVerificationActionResponse> {
  return apiRequest<GoogleBusinessProfileVerificationActionResponse>(
    `/api/integrations/google/business-profile/locations/${locationId}/verification/retry`,
    {
      method: "POST",
      token,
      body: JSON.stringify(payload),
    },
  );
}

function formatErrorDetail(payload: unknown): string {
  if (!payload || typeof payload !== "object") {
    return JSON.stringify(payload);
  }
  const asRecord = payload as Record<string, unknown>;
  const detail = asRecord.detail;
  if (typeof detail === "string") {
    return detail;
  }
  if (detail && typeof detail === "object") {
    const detailRecord = detail as Record<string, unknown>;
    const message = detailRecord.message;
    if (typeof message === "string" && message.trim()) {
      return message;
    }
    return JSON.stringify(detailRecord);
  }
  return JSON.stringify(asRecord);
}
