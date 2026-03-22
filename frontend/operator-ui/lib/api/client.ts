import { apiBaseUrl } from "../config";
import type {
  AuthExchangeResponse,
  BusinessSettings,
  BusinessSettingsUpdateRequest,
  SEOAuditRun,
  SEOAuditRunCreateRequest,
  SEOAuditRunSummary,
  SEOAuditRunListResponse,
  SEOAuditFindingListResponse,
  Principal,
  PrincipalCreateRequest,
  PrincipalIdentity,
  PrincipalIdentityCreateRequest,
  PrincipalIdentityListResponse,
  PrincipalListResponse,
  SEOSite,
  SEOSiteCreateRequest,
  SEOSiteListResponse,
  CompetitorComparisonReport,
  CompetitorDomainListResponse,
  CompetitorComparisonRunListResponse,
  CompetitorSnapshotPageListResponse,
  CompetitorSet,
  CompetitorSetListResponse,
  CompetitorProfileDraft,
  CompetitorProfileDraftAcceptRequest,
  CompetitorProfileDraftEditRequest,
  CompetitorProfileDraftRejectRequest,
  CompetitorProfileGenerationRunCreateRequest,
  CompetitorProfileGenerationRunDetailResponse,
  CompetitorProfileGenerationRunListResponse,
  CompetitorProfileGenerationSummaryResponse,
  RecommendationRunListResponse,
  RecommendationRun,
  RecommendationRunCreateRequest,
  RecommendationRunReport,
  RecommendationNarrative,
  RecommendationNarrativeListResponse,
  RecommendationTuningImpactPreview,
  RecommendationTuningImpactPreviewRequest,
  CompetitorSnapshotRun,
  CompetitorSnapshotRunListResponse,
  Recommendation,
  RecommendationActionStatus,
  RecommendationWorkflowUpdatePayload,
  RecommendationListFilters,
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

export async function fetchBusinessSettings(
  token: string,
  businessId: string,
): Promise<BusinessSettings> {
  return apiRequest<BusinessSettings>(`/api/businesses/${businessId}`, { token });
}

export async function updateBusinessSettings(
  token: string,
  businessId: string,
  payload: BusinessSettingsUpdateRequest,
): Promise<BusinessSettings> {
  return apiRequest<BusinessSettings>(`/api/businesses/${businessId}/settings`, {
    method: "PATCH",
    token,
    body: JSON.stringify(payload),
  });
}

export async function deactivateSite(token: string, businessId: string, siteId: string): Promise<SEOSite> {
  return apiRequest<SEOSite>(`/api/businesses/${businessId}/seo/sites/${siteId}/deactivate`, {
    method: "POST",
    token,
  });
}

export async function activateSite(token: string, businessId: string, siteId: string): Promise<SEOSite> {
  return apiRequest<SEOSite>(`/api/businesses/${businessId}/seo/sites/${siteId}/activate`, {
    method: "POST",
    token,
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

export async function fetchPrincipalIdentities(
  token: string,
  businessId: string,
): Promise<PrincipalIdentityListResponse> {
  return apiRequest<PrincipalIdentityListResponse>(`/api/businesses/${businessId}/principal-identities`, { token });
}

export async function createPrincipalIdentity(
  token: string,
  businessId: string,
  payload: PrincipalIdentityCreateRequest,
): Promise<PrincipalIdentity> {
  return apiRequest<PrincipalIdentity>(`/api/businesses/${businessId}/principal-identities`, {
    method: "POST",
    token,
    body: JSON.stringify(payload),
  });
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

export async function deactivatePrincipal(
  token: string,
  businessId: string,
  principalId: string,
): Promise<Principal> {
  return apiRequest<Principal>(`/api/businesses/${businessId}/principals/${principalId}/deactivate`, {
    method: "POST",
    token,
  });
}

export async function activatePrincipal(
  token: string,
  businessId: string,
  principalId: string,
): Promise<Principal> {
  return apiRequest<Principal>(`/api/businesses/${businessId}/principals/${principalId}/activate`, {
    method: "POST",
    token,
  });
}

export async function deactivatePrincipalIdentity(
  token: string,
  businessId: string,
  identityId: string,
): Promise<PrincipalIdentity> {
  return apiRequest<PrincipalIdentity>(
    `/api/businesses/${businessId}/principal-identities/${identityId}/deactivate`,
    {
      method: "POST",
      token,
    },
  );
}

export async function activatePrincipalIdentity(
  token: string,
  businessId: string,
  identityId: string,
): Promise<PrincipalIdentity> {
  return apiRequest<PrincipalIdentity>(
    `/api/businesses/${businessId}/principal-identities/${identityId}/activate`,
    {
      method: "POST",
      token,
    },
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

export async function fetchCompetitorSet(
  token: string,
  businessId: string,
  competitorSetId: string,
): Promise<CompetitorSet> {
  return apiRequest<CompetitorSet>(
    `/api/businesses/${businessId}/seo/competitor-sets/${competitorSetId}`,
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

export async function fetchCompetitorProfileGenerationRuns(
  token: string,
  businessId: string,
  siteId: string,
): Promise<CompetitorProfileGenerationRunListResponse> {
  return apiRequest<CompetitorProfileGenerationRunListResponse>(
    `/api/businesses/${businessId}/seo/sites/${siteId}/competitor-profile-generation-runs`,
    { token },
  );
}

export async function fetchCompetitorProfileGenerationRunDetail(
  token: string,
  businessId: string,
  siteId: string,
  generationRunId: string,
): Promise<CompetitorProfileGenerationRunDetailResponse> {
  return apiRequest<CompetitorProfileGenerationRunDetailResponse>(
    `/api/businesses/${businessId}/seo/sites/${siteId}/competitor-profile-generation-runs/${generationRunId}`,
    { token },
  );
}

export async function fetchCompetitorProfileGenerationSummary(
  token: string,
  businessId: string,
  siteId: string,
): Promise<CompetitorProfileGenerationSummaryResponse> {
  return apiRequest<CompetitorProfileGenerationSummaryResponse>(
    `/api/businesses/${businessId}/seo/sites/${siteId}/competitor-profile-generation-runs/summary`,
    { token },
  );
}

export async function createCompetitorProfileGenerationRun(
  token: string,
  businessId: string,
  siteId: string,
  payload: CompetitorProfileGenerationRunCreateRequest = {},
): Promise<CompetitorProfileGenerationRunDetailResponse> {
  return apiRequest<CompetitorProfileGenerationRunDetailResponse>(
    `/api/businesses/${businessId}/seo/sites/${siteId}/competitor-profile-generation-runs`,
    {
      method: "POST",
      token,
      body: JSON.stringify(payload),
    },
  );
}

export async function retryCompetitorProfileGenerationRun(
  token: string,
  businessId: string,
  siteId: string,
  generationRunId: string,
): Promise<CompetitorProfileGenerationRunDetailResponse> {
  return apiRequest<CompetitorProfileGenerationRunDetailResponse>(
    `/api/businesses/${businessId}/seo/sites/${siteId}/competitor-profile-generation-runs/${generationRunId}/retry`,
    {
      method: "POST",
      token,
    },
  );
}

export async function editCompetitorProfileDraft(
  token: string,
  businessId: string,
  siteId: string,
  generationRunId: string,
  draftId: string,
  payload: CompetitorProfileDraftEditRequest,
): Promise<CompetitorProfileDraft> {
  return apiRequest<CompetitorProfileDraft>(
    `/api/businesses/${businessId}/seo/sites/${siteId}/competitor-profile-generation-runs/${generationRunId}/drafts/${draftId}`,
    {
      method: "PATCH",
      token,
      body: JSON.stringify(payload),
    },
  );
}

export async function rejectCompetitorProfileDraft(
  token: string,
  businessId: string,
  siteId: string,
  generationRunId: string,
  draftId: string,
  payload: CompetitorProfileDraftRejectRequest = {},
): Promise<CompetitorProfileDraft> {
  return apiRequest<CompetitorProfileDraft>(
    `/api/businesses/${businessId}/seo/sites/${siteId}/competitor-profile-generation-runs/${generationRunId}/drafts/${draftId}/reject`,
    {
      method: "POST",
      token,
      body: JSON.stringify(payload),
    },
  );
}

export async function acceptCompetitorProfileDraft(
  token: string,
  businessId: string,
  siteId: string,
  generationRunId: string,
  draftId: string,
  payload: CompetitorProfileDraftAcceptRequest = {},
): Promise<CompetitorProfileDraft> {
  return apiRequest<CompetitorProfileDraft>(
    `/api/businesses/${businessId}/seo/sites/${siteId}/competitor-profile-generation-runs/${generationRunId}/drafts/${draftId}/accept`,
    {
      method: "POST",
      token,
      body: JSON.stringify(payload),
    },
  );
}

export async function fetchCompetitorSnapshotRuns(
  token: string,
  businessId: string,
  competitorSetId: string,
): Promise<CompetitorSnapshotRunListResponse> {
  return apiRequest<CompetitorSnapshotRunListResponse>(
    `/api/businesses/${businessId}/seo/competitor-sets/${competitorSetId}/snapshot-runs`,
    { token },
  );
}

export async function fetchCompetitorSnapshotRun(
  token: string,
  businessId: string,
  snapshotRunId: string,
): Promise<CompetitorSnapshotRun> {
  return apiRequest<CompetitorSnapshotRun>(`/api/businesses/${businessId}/seo/snapshot-runs/${snapshotRunId}`, {
    token,
  });
}

export async function fetchCompetitorSnapshotPages(
  token: string,
  businessId: string,
  snapshotRunId: string,
): Promise<CompetitorSnapshotPageListResponse> {
  return apiRequest<CompetitorSnapshotPageListResponse>(
    `/api/businesses/${businessId}/seo/snapshot-runs/${snapshotRunId}/pages`,
    { token },
  );
}

export async function fetchCompetitorComparisonRuns(
  token: string,
  businessId: string,
  competitorSetId: string,
): Promise<CompetitorComparisonRunListResponse> {
  return apiRequest<CompetitorComparisonRunListResponse>(
    `/api/businesses/${businessId}/seo/competitor-sets/${competitorSetId}/comparison-runs`,
    { token },
  );
}

export async function fetchSiteCompetitorComparisonRuns(
  token: string,
  businessId: string,
  siteId: string,
): Promise<CompetitorComparisonRunListResponse> {
  return apiRequest<CompetitorComparisonRunListResponse>(
    `/api/v1/businesses/${businessId}/seo/sites/${siteId}/competitor-comparison-runs`,
    { token },
  );
}

export async function fetchCompetitorComparisonReport(
  token: string,
  businessId: string,
  comparisonRunId: string,
): Promise<CompetitorComparisonReport> {
  return apiRequest<CompetitorComparisonReport>(
    `/api/businesses/${businessId}/seo/comparison-runs/${comparisonRunId}/report`,
    { token },
  );
}

export async function fetchRecommendationRuns(
  token: string,
  businessId: string,
  siteId: string,
): Promise<RecommendationRunListResponse> {
  return apiRequest<RecommendationRunListResponse>(
    `/api/businesses/${businessId}/seo/sites/${siteId}/recommendation-runs`,
    { token },
  );
}

export async function fetchLatestRecommendationRun(
  token: string,
  businessId: string,
  siteId: string,
): Promise<RecommendationRun | null> {
  const response = await fetchRecommendationRuns(token, businessId, siteId);
  if (response.items.length === 0) {
    return null;
  }
  const sortedRuns = [...response.items].sort((left, right) =>
    right.created_at.localeCompare(left.created_at),
  );
  return sortedRuns.find((item) => item.status === "completed") || sortedRuns[0] || null;
}

export async function createRecommendationRun(
  token: string,
  businessId: string,
  siteId: string,
  payload: RecommendationRunCreateRequest,
): Promise<RecommendationRun> {
  return apiRequest<RecommendationRun>(
    `/api/businesses/${businessId}/seo/sites/${siteId}/recommendation-runs`,
    {
      method: "POST",
      token,
      body: JSON.stringify(payload),
    },
  );
}

export async function fetchRecommendationRun(
  token: string,
  businessId: string,
  siteId: string,
  recommendationRunId: string,
): Promise<RecommendationRun> {
  return apiRequest<RecommendationRun>(
    `/api/businesses/${businessId}/seo/sites/${siteId}/recommendation-runs/${recommendationRunId}`,
    { token },
  );
}

export async function fetchRecommendationRunReport(
  token: string,
  businessId: string,
  siteId: string,
  recommendationRunId: string,
): Promise<RecommendationRunReport> {
  return apiRequest<RecommendationRunReport>(
    `/api/businesses/${businessId}/seo/sites/${siteId}/recommendation-runs/${recommendationRunId}/report`,
    { token },
  );
}

export async function fetchLatestRecommendationRunNarrative(
  token: string,
  businessId: string,
  siteId: string,
  recommendationRunId: string,
): Promise<RecommendationNarrative> {
  return apiRequest<RecommendationNarrative>(
    `/api/businesses/${businessId}/seo/sites/${siteId}/recommendation-runs/${recommendationRunId}/narratives/latest`,
    { token },
  );
}

export async function fetchRecommendationRunNarratives(
  token: string,
  businessId: string,
  siteId: string,
  recommendationRunId: string,
): Promise<RecommendationNarrativeListResponse> {
  return apiRequest<RecommendationNarrativeListResponse>(
    `/api/businesses/${businessId}/seo/sites/${siteId}/recommendation-runs/${recommendationRunId}/narratives`,
    { token },
  );
}

export async function createRecommendationRunNarrative(
  token: string,
  businessId: string,
  siteId: string,
  recommendationRunId: string,
): Promise<RecommendationNarrative> {
  return apiRequest<RecommendationNarrative>(
    `/api/businesses/${businessId}/seo/sites/${siteId}/recommendation-runs/${recommendationRunId}/narratives`,
    {
      method: "POST",
      token,
    },
  );
}

export async function fetchRecommendationNarrative(
  token: string,
  businessId: string,
  siteId: string,
  narrativeId: string,
): Promise<RecommendationNarrative> {
  return apiRequest<RecommendationNarrative>(
    `/api/businesses/${businessId}/seo/sites/${siteId}/recommendation-narratives/${narrativeId}`,
    { token },
  );
}

export async function previewRecommendationTuningImpact(
  token: string,
  businessId: string,
  siteId: string,
  payload: RecommendationTuningImpactPreviewRequest,
): Promise<RecommendationTuningImpactPreview> {
  return apiRequest<RecommendationTuningImpactPreview>(
    `/api/businesses/${businessId}/seo/sites/${siteId}/recommendations/tuning-preview`,
    {
      method: "POST",
      token,
      body: JSON.stringify(payload),
    },
  );
}

export async function fetchRecommendationsForRun(
  token: string,
  businessId: string,
  siteId: string,
  recommendationRunId: string,
): Promise<RecommendationListResponse> {
  return apiRequest<RecommendationListResponse>(
    `/api/businesses/${businessId}/seo/sites/${siteId}/recommendation-runs/${recommendationRunId}/recommendations`,
    { token },
  );
}

export async function fetchRecommendations(
  token: string,
  businessId: string,
  siteId: string,
  filters: RecommendationListFilters = {},
): Promise<RecommendationListResponse> {
  const params = new URLSearchParams();
  if (filters.status) {
    params.set("status", filters.status);
  }
  if (filters.priority_band) {
    params.set("priority_band", filters.priority_band);
  }
  if (filters.category) {
    params.set("category", filters.category);
  }
  if (filters.source_type) {
    params.set("source_type", filters.source_type);
  }
  if (filters.recommendation_run_id) {
    params.set("recommendation_run_id", filters.recommendation_run_id);
  }
  if (filters.sort_by) {
    params.set("sort_by", filters.sort_by);
  }
  if (filters.sort_order) {
    params.set("sort_order", filters.sort_order);
  }
  if (typeof filters.page === "number" && Number.isFinite(filters.page)) {
    params.set("page", String(Math.trunc(filters.page)));
  }
  if (typeof filters.page_size === "number" && Number.isFinite(filters.page_size)) {
    params.set("page_size", String(Math.trunc(filters.page_size)));
  }
  const query = params.toString();

  return apiRequest<RecommendationListResponse>(
    `/api/businesses/${businessId}/seo/sites/${siteId}/recommendations${query ? `?${query}` : ""}`,
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
  payload: RecommendationWorkflowUpdatePayload,
): Promise<Recommendation> {
  const body: Record<string, unknown> = {};
  if (payload.status) {
    body.status = payload.status;
  }
  if ("note" in payload) {
    body.note = payload.note ?? null;
  }
  return apiRequest<Recommendation>(
    `/api/businesses/${businessId}/seo/sites/${siteId}/recommendations/${recommendationId}`,
    {
      method: "PATCH",
      token,
      body: JSON.stringify(body),
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
