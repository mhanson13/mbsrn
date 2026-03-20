import { apiBaseUrl } from "../config";
import type {
  AuthExchangeResponse,
  SEOAuditRun,
  SEOAuditRunCreateRequest,
  SEOAuditRunSummary,
  SEOAuditRunListResponse,
  SEOAuditFindingListResponse,
  Principal,
  PrincipalCreateRequest,
  PrincipalListResponse,
  SEOSite,
  SEOSiteCreateRequest,
  SEOSiteListResponse,
  CompetitorDomainListResponse,
  CompetitorSetListResponse,
  Recommendation,
  RecommendationActionStatus,
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
  GoogleBusinessProfileVerificationErrorDetail,
  GoogleBusinessProfileLocationsResponse,
  GoogleBusinessProfileLocationVerification,
  GoogleBusinessProfileStartVerificationRequest,
} from "./types";

export class ApiRequestError extends Error {
  status: number;
  detail: Record<string, unknown> | null;

  constructor(
    message: string,
    options: { status: number; detail: Record<string, unknown> | null },
  ) {
    super(message);
    this.name = "ApiRequestError";
    this.status = options.status;
    this.detail = options.detail;
  }
}

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
    let message = `HTTP ${response.status}`;
    let detailObject: Record<string, unknown> | null = null;
    try {
      const payload = await response.json();
      const parsed = parseErrorDetail(payload);
      message = parsed.message;
      detailObject = parsed.detail;
    } catch {
      // ignore parse failures
    }
    throw new ApiRequestError(message, { status: response.status, detail: detailObject });
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

export async function createSite(
  token: string,
  businessId: string,
  payload: SEOSiteCreateRequest,
): Promise<SEOSite> {
  return apiRequest<SEOSite>(`/api/businesses/${businessId}/seo/sites`, {
    method: "POST",
    token,
    body: JSON.stringify(payload),
  });
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

export async function fetchAuditRun(
  token: string,
  businessId: string,
  runId: string,
): Promise<SEOAuditRun> {
  return apiRequest<SEOAuditRun>(`/api/businesses/${businessId}/seo/audit-runs/${runId}`, { token });
}

export async function createAuditRun(
  token: string,
  businessId: string,
  siteId: string,
  payload: SEOAuditRunCreateRequest = {},
): Promise<SEOAuditRun> {
  return apiRequest<SEOAuditRun>(`/api/businesses/${businessId}/seo/sites/${siteId}/audit-runs`, {
    method: "POST",
    token,
    body: JSON.stringify(payload),
  });
}

export async function fetchAuditRunSummary(
  token: string,
  businessId: string,
  runId: string,
): Promise<SEOAuditRunSummary> {
  return apiRequest<SEOAuditRunSummary>(`/api/businesses/${businessId}/seo/audit-runs/${runId}/summary`, {
    token,
  });
}

export async function fetchAuditRunFindings(
  token: string,
  businessId: string,
  runId: string,
): Promise<SEOAuditFindingListResponse> {
  return apiRequest<SEOAuditFindingListResponse>(
    `/api/businesses/${businessId}/seo/audit-runs/${runId}/findings`,
    { token },
  );
}

export async function fetchPrincipals(token: string, businessId: string): Promise<PrincipalListResponse> {
  return apiRequest<PrincipalListResponse>(`/api/businesses/${businessId}/principals`, { token });
}

export async function createPrincipal(
  token: string,
  businessId: string,
  payload: PrincipalCreateRequest,
): Promise<Principal> {
  return apiRequest<Principal>(`/api/businesses/${businessId}/principals`, {
    method: "POST",
    token,
    body: JSON.stringify(payload),
  });
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

export async function fetchCompetitorDomains(
  token: string,
  businessId: string,
  competitorSetId: string,
): Promise<CompetitorDomainListResponse> {
  return apiRequest<CompetitorDomainListResponse>(
    `/api/businesses/${businessId}/seo/competitor-sets/${competitorSetId}/domains`,
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

export async function fetchRecommendation(
  token: string,
  businessId: string,
  siteId: string,
  recommendationId: string,
): Promise<Recommendation> {
  return apiRequest<Recommendation>(
    `/api/businesses/${businessId}/seo/sites/${siteId}/recommendations/${recommendationId}`,
    { token },
  );
}

export async function updateRecommendationStatus(
  token: string,
  businessId: string,
  siteId: string,
  recommendationId: string,
  status: RecommendationActionStatus,
): Promise<Recommendation> {
  return apiRequest<Recommendation>(
    `/api/businesses/${businessId}/seo/sites/${siteId}/recommendations/${recommendationId}`,
    {
      method: "PATCH",
      token,
      body: JSON.stringify({ status }),
    },
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

function parseErrorDetail(payload: unknown): {
  message: string;
  detail: Record<string, unknown> | null;
} {
  if (!payload || typeof payload !== "object") {
    return { message: JSON.stringify(payload), detail: null };
  }
  const asRecord = payload as Record<string, unknown>;
  const detail = asRecord.detail;
  if (typeof detail === "string") {
    return { message: detail, detail: null };
  }
  if (detail && typeof detail === "object") {
    const detailRecord = detail as Record<string, unknown>;
    const message = detailRecord.message;
    if (typeof message === "string" && message.trim()) {
      return { message, detail: detailRecord };
    }
    return { message: JSON.stringify(detailRecord), detail: detailRecord };
  }
  return { message: JSON.stringify(asRecord), detail: null };
}

export function asVerificationErrorDetail(
  detail: Record<string, unknown> | null,
): GoogleBusinessProfileVerificationErrorDetail | null {
  if (!detail) {
    return null;
  }
  const code = detail.code;
  const message = detail.message;
  const reconnectRequired = detail.reconnect_required;
  if (
    typeof code !== "string" ||
    typeof message !== "string" ||
    typeof reconnectRequired !== "boolean"
  ) {
    return null;
  }

  const allowedCodes = new Set<GoogleBusinessProfileVerificationErrorDetail["code"]>([
    "reconnect_required",
    "insufficient_scope",
    "permission_denied",
    "verification_not_supported",
    "method_not_available",
    "invalid_verification_state",
    "invalid_code",
    "provider_conflict",
    "provider_error",
    "not_found",
  ]);
  if (!allowedCodes.has(code as GoogleBusinessProfileVerificationErrorDetail["code"])) {
    return null;
  }

  const guidance = detail.guidance;
  return {
    code: code as GoogleBusinessProfileVerificationErrorDetail["code"],
    message,
    reconnect_required: reconnectRequired,
    guidance:
      guidance && typeof guidance === "object"
        ? (guidance as GoogleBusinessProfileVerificationErrorDetail["guidance"])
        : null,
  };
}
