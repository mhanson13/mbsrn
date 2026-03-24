import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import SiteWorkspacePage from "./[site_id]/page";
import { ApiRequestError } from "../../lib/api/client";
import type {
  AIPromptPreview,
  BusinessSettings,
  CompetitorComparisonRun,
  CompetitorProfileDraft,
  CompetitorProfileGenerationRun,
  CompetitorProfileGenerationRunDetailResponse,
  CompetitorProfileGenerationRunListResponse,
  CompetitorProfileGenerationSummaryResponse,
  CompetitorDomainListResponse,
  CompetitorSetListResponse,
  CompetitorSnapshotRunListResponse,
  RecommendationAnalysisFreshness,
  Recommendation,
  RecommendationListResponse,
  RecommendationNarrative,
  RecommendationTuningImpactPreview,
  RecommendationRunListResponse,
  RecommendationWorkspaceSummaryResponse,
  SEOAuditRunListResponse,
  SEOSite,
} from "../../lib/api/types";

type OperatorContextMockValue = {
  loading: boolean;
  error: string | null;
  token: string;
  businessId: string;
  sites: SEOSite[];
  selectedSiteId: string | null;
  setSelectedSiteId: jest.Mock;
  refreshSites: jest.Mock;
};

const navigationState = {
  params: { site_id: "site-1" },
};
const FIXED_NOW_MS = Date.parse("2026-03-21T18:00:00Z");

const mockUseOperatorContext = jest.fn<OperatorContextMockValue, []>();
const mockFetchAuditRuns = jest.fn<Promise<SEOAuditRunListResponse>, unknown[]>();
const mockFetchCompetitorSets = jest.fn<Promise<CompetitorSetListResponse>, unknown[]>();
const mockFetchCompetitorDomains = jest.fn<Promise<CompetitorDomainListResponse>, unknown[]>();
const mockFetchCompetitorSnapshotRuns = jest.fn<Promise<CompetitorSnapshotRunListResponse>, unknown[]>();
const mockFetchSiteCompetitorComparisonRuns = jest.fn<
  Promise<{ items: CompetitorComparisonRun[]; total: number }>,
  unknown[]
>();
const mockFetchRecommendations = jest.fn<Promise<RecommendationListResponse>, unknown[]>();
const mockFetchRecommendationWorkspaceSummary = jest.fn<Promise<RecommendationWorkspaceSummaryResponse>, unknown[]>();
const mockFetchRecommendationRuns = jest.fn<Promise<RecommendationRunListResponse>, unknown[]>();
const mockFetchLatestRecommendationRunNarrative = jest.fn<Promise<RecommendationNarrative>, unknown[]>();
const mockPreviewRecommendationTuningImpact = jest.fn<Promise<RecommendationTuningImpactPreview>, unknown[]>();
const mockFetchBusinessSettings = jest.fn<Promise<BusinessSettings>, unknown[]>();
const mockUpdateBusinessSettings = jest.fn<Promise<BusinessSettings>, unknown[]>();
const mockUpdateSite = jest.fn<Promise<SEOSite>, unknown[]>();
const mockFetchCompetitorProfileGenerationRuns = jest.fn<
  Promise<CompetitorProfileGenerationRunListResponse>,
  unknown[]
>();
const mockFetchCompetitorProfileGenerationRunDetail = jest.fn<
  Promise<CompetitorProfileGenerationRunDetailResponse>,
  unknown[]
>();
const mockFetchCompetitorProfileGenerationSummary = jest.fn<
  Promise<CompetitorProfileGenerationSummaryResponse>,
  unknown[]
>();
const mockCreateCompetitorProfileGenerationRun = jest.fn<
  Promise<CompetitorProfileGenerationRunDetailResponse>,
  unknown[]
>();
const mockRetryCompetitorProfileGenerationRun = jest.fn<
  Promise<CompetitorProfileGenerationRunDetailResponse>,
  unknown[]
>();
const mockAcceptCompetitorProfileDraft = jest.fn<Promise<CompetitorProfileDraft>, unknown[]>();
const mockRejectCompetitorProfileDraft = jest.fn<Promise<CompetitorProfileDraft>, unknown[]>();
const mockEditCompetitorProfileDraft = jest.fn<Promise<CompetitorProfileDraft>, unknown[]>();

jest.mock("next/navigation", () => ({
  useParams: () => navigationState.params,
}));

jest.mock("../../components/useOperatorContext", () => ({
  useOperatorContext: () => mockUseOperatorContext(),
}));

jest.mock("../../lib/api/client", () => {
  const actual = jest.requireActual("../../lib/api/client");
  return {
    ...actual,
    fetchAuditRuns: (...args: unknown[]) => mockFetchAuditRuns(...args),
    fetchCompetitorSets: (...args: unknown[]) => mockFetchCompetitorSets(...args),
    fetchCompetitorDomains: (...args: unknown[]) => mockFetchCompetitorDomains(...args),
    fetchCompetitorSnapshotRuns: (...args: unknown[]) => mockFetchCompetitorSnapshotRuns(...args),
    fetchSiteCompetitorComparisonRuns: (...args: unknown[]) => mockFetchSiteCompetitorComparisonRuns(...args),
    fetchRecommendations: (...args: unknown[]) => mockFetchRecommendations(...args),
    fetchRecommendationWorkspaceSummary: (...args: unknown[]) => mockFetchRecommendationWorkspaceSummary(...args),
    fetchRecommendationRuns: (...args: unknown[]) => mockFetchRecommendationRuns(...args),
    fetchLatestRecommendationRunNarrative: (...args: unknown[]) =>
      mockFetchLatestRecommendationRunNarrative(...args),
    previewRecommendationTuningImpact: (...args: unknown[]) => mockPreviewRecommendationTuningImpact(...args),
    fetchBusinessSettings: (...args: unknown[]) => mockFetchBusinessSettings(...args),
    updateBusinessSettings: (...args: unknown[]) => mockUpdateBusinessSettings(...args),
    updateSite: (...args: unknown[]) => mockUpdateSite(...args),
    fetchCompetitorProfileGenerationRuns: (...args: unknown[]) =>
      mockFetchCompetitorProfileGenerationRuns(...args),
    fetchCompetitorProfileGenerationRunDetail: (...args: unknown[]) =>
      mockFetchCompetitorProfileGenerationRunDetail(...args),
    fetchCompetitorProfileGenerationSummary: (...args: unknown[]) =>
      mockFetchCompetitorProfileGenerationSummary(...args),
    createCompetitorProfileGenerationRun: (...args: unknown[]) =>
      mockCreateCompetitorProfileGenerationRun(...args),
    retryCompetitorProfileGenerationRun: (...args: unknown[]) =>
      mockRetryCompetitorProfileGenerationRun(...args),
    acceptCompetitorProfileDraft: (...args: unknown[]) => mockAcceptCompetitorProfileDraft(...args),
    rejectCompetitorProfileDraft: (...args: unknown[]) => mockRejectCompetitorProfileDraft(...args),
    editCompetitorProfileDraft: (...args: unknown[]) => mockEditCompetitorProfileDraft(...args),
  };
});

function buildSite(overrides: Partial<SEOSite> = {}): SEOSite {
  return {
    id: "site-1",
    business_id: "biz-1",
    display_name: "Main Site",
    base_url: "https://example.com/",
    normalized_domain: "example.com",
    is_active: true,
    is_primary: true,
    last_audit_run_id: "audit-1",
    last_audit_status: "completed",
    last_audit_completed_at: "2026-03-21T00:32:00Z",
    ...overrides,
  };
}

function buildBusinessSettings(overrides: Partial<BusinessSettings> = {}): BusinessSettings {
  return {
    id: "biz-1",
    name: "Biz 1",
    notification_phone: "+13035550199",
    notification_email: "owner@example.com",
    sms_enabled: true,
    email_enabled: true,
    customer_auto_ack_enabled: true,
    contractor_alerts_enabled: true,
    seo_audit_crawl_max_pages: 25,
    competitor_candidate_min_relevance_score: 35,
    competitor_candidate_big_box_penalty: 20,
    competitor_candidate_directory_penalty: 35,
    competitor_candidate_local_alignment_bonus: 10,
    timezone: "America/Denver",
    created_at: "2026-03-20T00:00:00Z",
    updated_at: "2026-03-21T00:00:00Z",
    ...overrides,
  };
}

function buildCompetitorProfileGenerationRun(
  overrides: Partial<CompetitorProfileGenerationRun> = {},
): CompetitorProfileGenerationRun {
  return {
    id: "gen-run-default",
    business_id: "biz-1",
    site_id: "site-1",
    parent_run_id: null,
    status: "completed",
    requested_candidate_count: 5,
    generated_draft_count: 0,
    provider_name: "mock",
    model_name: "mock-seo-competitor-profile-v1",
    prompt_version: "seo-competitor-profile-v1",
    failure_category: null,
    error_summary: null,
    completed_at: "2026-03-21T01:00:00Z",
    created_by_principal_id: "principal-1",
    created_at: "2026-03-21T00:59:00Z",
    updated_at: "2026-03-21T01:00:00Z",
    ...overrides,
  };
}

function buildRecommendation(
  overrides: Partial<Recommendation> = {},
  options: { source?: string } = {},
): Recommendation & { source?: string } {
  const recommendation: Recommendation & { source?: string } = {
    id: "rec-1",
    business_id: "biz-1",
    site_id: "site-1",
    recommendation_run_id: "run-1",
    audit_run_id: "audit-1",
    comparison_run_id: "comparison-1",
    status: "open",
    category: "SEO",
    severity: "warning",
    priority_score: 80,
    priority_band: "high",
    effort_bucket: "small",
    title: "Fix title tags",
    rationale: "Title tags are missing core keywords.",
    eeat_categories: [],
    primary_eeat_category: null,
    decision_reason: null,
    created_at: "2026-03-21T00:30:00Z",
    updated_at: "2026-03-21T00:31:00Z",
    ...overrides,
    ...(options.source ? { source: options.source } : {}),
  };
  return recommendation;
}

function buildRecommendationNarrative(
  overrides: Partial<RecommendationNarrative> = {},
): RecommendationNarrative {
  return {
    id: "narrative-1",
    business_id: "biz-1",
    site_id: "site-1",
    recommendation_run_id: "run-1",
    version: 2,
    status: "completed",
    narrative_text: "Narrative for run 1.",
    top_themes_json: ["titles"],
    sections_json: { summary: "AI summary for this run." },
    provider_name: "provider",
    model_name: "model",
    prompt_version: "v2",
    error_message: null,
    created_by_principal_id: "principal-1",
    created_at: "2026-03-21T00:33:00Z",
    updated_at: "2026-03-21T00:33:00Z",
    ...overrides,
  };
}

function buildAIPromptPreview(
  overrides: Partial<AIPromptPreview> = {},
): AIPromptPreview {
  return {
    available: true,
    prompt_type: "recommendation",
    system_prompt: "SYSTEM_PROMPT_TEXT",
    user_prompt: "USER_PROMPT_TEXT",
    model: "gpt-4o-mini",
    prompt_version: "v2",
    truncated: false,
    ...overrides,
  };
}

function buildRecommendationAnalysisFreshness(
  overrides: Partial<RecommendationAnalysisFreshness> = {},
): RecommendationAnalysisFreshness {
  return {
    status: "fresh",
    analysis_generated_at: "2026-03-21T00:30:00Z",
    last_apply_at: null,
    message: "Analysis is up to date with the latest applied changes.",
    ...overrides,
  };
}

function buildRecommendationWorkspaceSummary(
  overrides: Partial<RecommendationWorkspaceSummaryResponse> = {},
): RecommendationWorkspaceSummaryResponse {
  const latestRun = {
    id: "run-1",
    business_id: "biz-1",
    site_id: "site-1",
    audit_run_id: "audit-1",
    comparison_run_id: "comparison-1",
    status: "completed",
    total_recommendations: 1,
    critical_recommendations: 0,
    warning_recommendations: 1,
    info_recommendations: 0,
    category_counts_json: {},
    effort_bucket_counts_json: {},
    started_at: "2026-03-21T00:29:00Z",
    completed_at: "2026-03-21T00:30:00Z",
    duration_ms: 60000,
    error_summary: null,
    created_by_principal_id: "principal-1",
    created_at: "2026-03-21T00:29:00Z",
    updated_at: "2026-03-21T00:30:00Z",
  };
  return {
    business_id: "biz-1",
    site_id: "site-1",
    state: "completed_with_narrative",
    latest_run: latestRun,
    latest_completed_run: latestRun,
    recommendations: {
      items: [buildRecommendation()],
      total: 1,
    },
    latest_narrative: buildRecommendationNarrative(),
    tuning_suggestions: [],
    ...overrides,
  };
}

function baseContext(overrides: Partial<OperatorContextMockValue> = {}): OperatorContextMockValue {
  return {
    loading: false,
    error: null,
    token: "token-1",
    businessId: "biz-1",
    sites: [buildSite()],
    selectedSiteId: null,
    setSelectedSiteId: jest.fn(),
    refreshSites: jest.fn(),
    ...overrides,
  };
}

function seedCompetitorProfileGenerationDefaults(): void {
  mockFetchBusinessSettings.mockResolvedValue(buildBusinessSettings());
  mockUpdateBusinessSettings.mockReset();
  mockUpdateSite.mockResolvedValue(
    buildSite({
      primary_location: "Serving area around ZIP code 80538",
      primary_business_zip: "80538",
    }),
  );
  mockFetchCompetitorProfileGenerationRuns.mockResolvedValue({ items: [], total: 0 });
  mockFetchCompetitorProfileGenerationRunDetail.mockReset();
  mockFetchRecommendationWorkspaceSummary.mockResolvedValue({
    business_id: "biz-1",
    site_id: "site-1",
    state: "no_runs",
    latest_run: null,
    latest_completed_run: null,
    recommendations: { items: [], total: 0 },
    latest_narrative: null,
    tuning_suggestions: [],
  });
  mockFetchCompetitorProfileGenerationSummary.mockResolvedValue({
    business_id: "biz-1",
    site_id: "site-1",
    lookback_days: 30,
    window_start: "2026-02-20T00:00:00Z",
    window_end: "2026-03-21T00:00:00Z",
    queued_count: 0,
    running_count: 0,
    completed_count: 0,
    failed_count: 0,
    retry_child_runs: 0,
    retried_parent_runs: 0,
    failed_runs_retried: 0,
    failure_category_counts: {},
    total_runs: 0,
    total_raw_candidate_count: 0,
    total_included_candidate_count: 0,
    total_excluded_candidate_count: 0,
    exclusion_counts_by_reason: {
      duplicate: 0,
      low_relevance: 0,
      directory_or_aggregator: 0,
      big_box_mismatch: 0,
      existing_domain_match: 0,
      invalid_candidate: 0,
    },
    latest_run_created_at: null,
    latest_run_completed_at: null,
    latest_completed_run_completed_at: null,
    latest_failed_run_completed_at: null,
  });
  mockCreateCompetitorProfileGenerationRun.mockReset();
  mockRetryCompetitorProfileGenerationRun.mockReset();
  mockAcceptCompetitorProfileDraft.mockReset();
  mockRejectCompetitorProfileDraft.mockReset();
  mockEditCompetitorProfileDraft.mockReset();
}

function seedRichWorkspaceData(): void {
  mockFetchAuditRuns.mockResolvedValue({
    items: [
      {
        id: "audit-1",
        business_id: "biz-1",
        site_id: "site-1",
        status: "completed",
        max_pages: 25,
        max_depth: 2,
        pages_discovered: 25,
        created_at: "2026-03-21T00:31:00Z",
        updated_at: "2026-03-21T00:32:00Z",
        started_at: "2026-03-21T00:31:30Z",
        completed_at: "2026-03-21T00:32:00Z",
        crawl_duration_ms: 30000,
        error_summary: null,
        created_by_principal_id: "principal-1",
        pages_crawled: 25,
        pages_skipped: 0,
        duplicate_urls_skipped: 0,
        errors_encountered: 0,
      },
      {
        id: "audit-2",
        business_id: "biz-1",
        site_id: "site-1",
        status: "failed",
        max_pages: 25,
        max_depth: 2,
        pages_discovered: 20,
        created_at: "2026-03-21T00:08:00Z",
        updated_at: "2026-03-21T00:09:00Z",
        started_at: "2026-03-21T00:08:20Z",
        completed_at: "2026-03-21T00:09:00Z",
        crawl_duration_ms: 40000,
        error_summary: "crawl failed",
        created_by_principal_id: "principal-1",
        pages_crawled: 18,
        pages_skipped: 2,
        duplicate_urls_skipped: 0,
        errors_encountered: 3,
      },
      {
        id: "audit-3",
        business_id: "biz-1",
        site_id: "site-1",
        status: "running",
        max_pages: 25,
        max_depth: 2,
        pages_discovered: 10,
        created_at: "2026-03-21T00:07:00Z",
        updated_at: "2026-03-21T00:08:00Z",
        started_at: "2026-03-21T00:08:00Z",
        completed_at: null,
        crawl_duration_ms: null,
        error_summary: null,
        created_by_principal_id: "principal-1",
        pages_crawled: 5,
        pages_skipped: 0,
        duplicate_urls_skipped: 0,
        errors_encountered: 0,
      },
      {
        id: "audit-4",
        business_id: "biz-1",
        site_id: "site-1",
        status: "completed",
        max_pages: 25,
        max_depth: 2,
        pages_discovered: 20,
        created_at: "2026-03-21T00:06:00Z",
        updated_at: "2026-03-21T00:07:00Z",
        started_at: "2026-03-21T00:06:10Z",
        completed_at: "2026-03-21T00:07:00Z",
        crawl_duration_ms: 50000,
        error_summary: null,
        created_by_principal_id: "principal-1",
        pages_crawled: 20,
        pages_skipped: 0,
        duplicate_urls_skipped: 0,
        errors_encountered: 0,
      },
      {
        id: "audit-5",
        business_id: "biz-1",
        site_id: "site-1",
        status: "completed",
        max_pages: 25,
        max_depth: 2,
        pages_discovered: 20,
        created_at: "2026-03-21T00:05:00Z",
        updated_at: "2026-03-21T00:06:00Z",
        started_at: "2026-03-21T00:05:10Z",
        completed_at: "2026-03-21T00:06:00Z",
        crawl_duration_ms: 50000,
        error_summary: null,
        created_by_principal_id: "principal-1",
        pages_crawled: 20,
        pages_skipped: 0,
        duplicate_urls_skipped: 0,
        errors_encountered: 0,
      },
      {
        id: "audit-6",
        business_id: "biz-1",
        site_id: "site-1",
        status: "completed",
        max_pages: 25,
        max_depth: 2,
        pages_discovered: 20,
        created_at: "2026-03-21T00:04:00Z",
        updated_at: "2026-03-21T00:05:00Z",
        started_at: "2026-03-21T00:04:20Z",
        completed_at: "2026-03-21T00:05:00Z",
        crawl_duration_ms: 40000,
        error_summary: null,
        created_by_principal_id: "principal-1",
        pages_crawled: 20,
        pages_skipped: 0,
        duplicate_urls_skipped: 0,
        errors_encountered: 0,
      },
      {
        id: "audit-7",
        business_id: "biz-1",
        site_id: "site-1",
        status: "completed",
        max_pages: 25,
        max_depth: 2,
        pages_discovered: 20,
        created_at: "2026-03-21T00:03:00Z",
        updated_at: "2026-03-21T00:04:00Z",
        started_at: "2026-03-21T00:03:20Z",
        completed_at: "2026-03-21T00:04:00Z",
        crawl_duration_ms: 40000,
        error_summary: null,
        created_by_principal_id: "principal-1",
        pages_crawled: 20,
        pages_skipped: 0,
        duplicate_urls_skipped: 0,
        errors_encountered: 0,
      },
      {
        id: "audit-8",
        business_id: "biz-1",
        site_id: "site-1",
        status: "completed",
        max_pages: 25,
        max_depth: 2,
        pages_discovered: 20,
        created_at: "2026-03-21T00:02:00Z",
        updated_at: "2026-03-21T00:03:00Z",
        started_at: "2026-03-21T00:02:20Z",
        completed_at: "2026-03-21T00:03:00Z",
        crawl_duration_ms: 40000,
        error_summary: null,
        created_by_principal_id: "principal-1",
        pages_crawled: 20,
        pages_skipped: 0,
        duplicate_urls_skipped: 0,
        errors_encountered: 0,
      },
    ],
    total: 8,
  });

  mockFetchCompetitorSets.mockResolvedValue({
    items: [
      {
        id: "set-1",
        business_id: "biz-1",
        site_id: "site-1",
        name: "Primary Competitors",
        city: null,
        state: null,
        is_active: true,
        created_by_principal_id: "principal-1",
        created_at: "2026-03-20T00:00:00Z",
        updated_at: "2026-03-21T00:00:00Z",
      },
    ],
    total: 1,
  });

  mockFetchCompetitorDomains.mockResolvedValue({
    items: [
      {
        id: "domain-1",
        business_id: "biz-1",
        site_id: "site-1",
        competitor_set_id: "set-1",
        domain: "competitor.com",
        base_url: "https://competitor.com/",
        display_name: "Competitor",
        source: "manual",
        is_active: true,
        notes: null,
        created_at: "2026-03-20T00:00:00Z",
        updated_at: "2026-03-21T00:00:00Z",
      },
    ],
    total: 1,
  });

  mockFetchCompetitorSnapshotRuns.mockResolvedValue({
    items: [
      {
        id: "snapshot-1",
        business_id: "biz-1",
        site_id: "site-1",
        competitor_set_id: "set-1",
        client_audit_run_id: "audit-1",
        status: "completed",
        max_domains: 10,
        max_pages_per_domain: 2,
        max_depth: 1,
        same_domain_only: true,
        domains_targeted: 1,
        domains_completed: 1,
        pages_attempted: 2,
        pages_captured: 2,
        pages_skipped: 0,
        errors_encountered: 0,
        started_at: "2026-03-21T00:19:00Z",
        completed_at: "2026-03-21T00:20:00Z",
        duration_ms: 60000,
        error_summary: null,
        created_by_principal_id: "principal-1",
        created_at: "2026-03-21T00:19:00Z",
        updated_at: "2026-03-21T00:20:00Z",
      },
      {
        id: "snapshot-2",
        business_id: "biz-1",
        site_id: "site-1",
        competitor_set_id: "set-1",
        client_audit_run_id: "audit-1",
        status: "failed",
        max_domains: 10,
        max_pages_per_domain: 2,
        max_depth: 1,
        same_domain_only: true,
        domains_targeted: 1,
        domains_completed: 0,
        pages_attempted: 1,
        pages_captured: 0,
        pages_skipped: 0,
        errors_encountered: 1,
        started_at: "2026-03-21T00:17:00Z",
        completed_at: "2026-03-21T00:18:00Z",
        duration_ms: 60000,
        error_summary: "snapshot failed",
        created_by_principal_id: "principal-1",
        created_at: "2026-03-21T00:17:00Z",
        updated_at: "2026-03-21T00:18:00Z",
      },
      {
        id: "snapshot-3",
        business_id: "biz-1",
        site_id: "site-1",
        competitor_set_id: "set-1",
        client_audit_run_id: "audit-1",
        status: "running",
        max_domains: 10,
        max_pages_per_domain: 2,
        max_depth: 1,
        same_domain_only: true,
        domains_targeted: 1,
        domains_completed: 0,
        pages_attempted: 0,
        pages_captured: 0,
        pages_skipped: 0,
        errors_encountered: 0,
        started_at: "2026-03-21T00:17:00Z",
        completed_at: null,
        duration_ms: null,
        error_summary: null,
        created_by_principal_id: "principal-1",
        created_at: "2026-03-21T00:16:00Z",
        updated_at: "2026-03-21T00:17:00Z",
      },
    ],
    total: 3,
  });

  mockFetchSiteCompetitorComparisonRuns.mockResolvedValue({
    items: [
      {
        id: "comparison-1",
        business_id: "biz-1",
        site_id: "site-1",
        competitor_set_id: "set-1",
        snapshot_run_id: "snapshot-1",
        baseline_audit_run_id: "audit-1",
        status: "completed",
        total_findings: 4,
        critical_findings: 1,
        warning_findings: 2,
        info_findings: 1,
        client_pages_analyzed: 10,
        competitor_pages_analyzed: 10,
        finding_type_counts_json: {},
        category_counts_json: {},
        severity_counts_json: {},
        started_at: "2026-03-21T00:24:00Z",
        completed_at: "2026-03-21T00:25:00Z",
        duration_ms: 60000,
        error_summary: null,
        created_by_principal_id: "principal-1",
        created_at: "2026-03-21T00:24:00Z",
        updated_at: "2026-03-21T00:25:00Z",
      },
      {
        id: "comparison-2",
        business_id: "biz-1",
        site_id: "site-1",
        competitor_set_id: "set-1",
        snapshot_run_id: "snapshot-2",
        baseline_audit_run_id: "audit-1",
        status: "failed",
        total_findings: 0,
        critical_findings: 0,
        warning_findings: 0,
        info_findings: 0,
        client_pages_analyzed: 0,
        competitor_pages_analyzed: 0,
        finding_type_counts_json: {},
        category_counts_json: {},
        severity_counts_json: {},
        started_at: "2026-03-21T00:21:00Z",
        completed_at: "2026-03-21T00:22:00Z",
        duration_ms: 60000,
        error_summary: "comparison failed",
        created_by_principal_id: "principal-1",
        created_at: "2026-03-21T00:21:00Z",
        updated_at: "2026-03-21T00:22:00Z",
      },
    ],
    total: 2,
  });

  mockFetchRecommendations.mockResolvedValue({
    items: [
      {
        id: "rec-1",
        business_id: "biz-1",
        site_id: "site-1",
        recommendation_run_id: "run-1",
        audit_run_id: "audit-1",
        comparison_run_id: "comparison-1",
        status: "open",
        category: "SEO",
        severity: "warning",
        priority_score: 80,
        priority_band: "high",
        effort_bucket: "small",
        title: "Fix title tags",
        rationale: "Title tags are missing core keywords.",
        eeat_categories: [],
        primary_eeat_category: null,
        decision_reason: null,
        created_at: "2026-03-21T00:30:00Z",
        updated_at: "2026-03-21T00:31:00Z",
      },
    ],
    total: 1,
    filtered_summary: {
      total: 1,
      open: 1,
      accepted: 0,
      dismissed: 0,
      high_priority: 1,
    },
  });

  mockFetchRecommendationRuns.mockResolvedValue({
    items: [
      {
        id: "run-1",
        business_id: "biz-1",
        site_id: "site-1",
        audit_run_id: "audit-1",
        comparison_run_id: "comparison-1",
        status: "completed",
        total_recommendations: 4,
        critical_recommendations: 1,
        warning_recommendations: 2,
        info_recommendations: 1,
        category_counts_json: {},
        effort_bucket_counts_json: {},
        started_at: "2026-03-21T00:29:00Z",
        completed_at: "2026-03-21T00:30:00Z",
        duration_ms: 60000,
        error_summary: null,
        created_by_principal_id: "principal-1",
        created_at: "2026-03-21T00:29:00Z",
        updated_at: "2026-03-21T00:30:00Z",
      },
      {
        id: "run-2",
        business_id: "biz-1",
        site_id: "site-1",
        audit_run_id: "audit-1",
        comparison_run_id: "comparison-1",
        status: "open",
        total_recommendations: 1,
        critical_recommendations: 0,
        warning_recommendations: 1,
        info_recommendations: 0,
        category_counts_json: {},
        effort_bucket_counts_json: {},
        started_at: "2026-03-21T00:27:00Z",
        completed_at: null,
        duration_ms: null,
        error_summary: null,
        created_by_principal_id: "principal-1",
        created_at: "2026-03-21T00:27:00Z",
        updated_at: "2026-03-21T00:27:00Z",
      },
      {
        id: "run-3",
        business_id: "biz-1",
        site_id: "site-1",
        audit_run_id: "audit-1",
        comparison_run_id: "comparison-2",
        status: "failed",
        total_recommendations: 0,
        critical_recommendations: 0,
        warning_recommendations: 0,
        info_recommendations: 0,
        category_counts_json: {},
        effort_bucket_counts_json: {},
        started_at: "2026-03-21T00:26:00Z",
        completed_at: "2026-03-21T00:26:30Z",
        duration_ms: 30000,
        error_summary: "run failed",
        created_by_principal_id: "principal-1",
        created_at: "2026-03-21T00:26:00Z",
        updated_at: "2026-03-21T00:26:30Z",
      },
    ],
    total: 3,
  });

  const narrativesByRunId: Record<string, RecommendationNarrative> = {
    "run-1": {
      id: "narrative-1",
      business_id: "biz-1",
      site_id: "site-1",
      recommendation_run_id: "run-1",
      version: 2,
      status: "completed",
      narrative_text: "Narrative for run 1.",
      top_themes_json: ["titles"],
      sections_json: { summary: "one" },
      provider_name: "provider",
      model_name: "model",
      prompt_version: "v1",
      error_message: null,
      created_by_principal_id: "principal-1",
      created_at: "2026-03-21T00:33:00Z",
      updated_at: "2026-03-21T00:33:00Z",
    },
    "run-2": {
      id: "narrative-2",
      business_id: "biz-1",
      site_id: "site-1",
      recommendation_run_id: "run-2",
      version: 1,
      status: "failed",
      narrative_text: null,
      top_themes_json: [],
      sections_json: null,
      provider_name: "provider",
      model_name: "model",
      prompt_version: "v1",
      error_message: "provider failed",
      created_by_principal_id: "principal-1",
      created_at: "2026-03-21T00:31:00Z",
      updated_at: "2026-03-21T00:31:00Z",
    },
    "run-3": {
      id: "narrative-3",
      business_id: "biz-1",
      site_id: "site-1",
      recommendation_run_id: "run-3",
      version: 1,
      status: "completed",
      narrative_text: "Narrative for run 3.",
      top_themes_json: ["technical"],
      sections_json: { summary: "three" },
      provider_name: "provider",
      model_name: "model",
      prompt_version: "v1",
      error_message: null,
      created_by_principal_id: "principal-1",
      created_at: "2026-03-21T00:29:30Z",
      updated_at: "2026-03-21T00:29:30Z",
    },
  };

  mockFetchLatestRecommendationRunNarrative.mockImplementation((...args: unknown[]) => {
    const runId = String(args[3] || "");
    const narrative = narrativesByRunId[runId];
    if (!narrative) {
      return Promise.reject(new Error(`Unexpected run id: ${runId}`));
    }
    return Promise.resolve(narrative);
  });

  mockFetchRecommendationWorkspaceSummary.mockResolvedValue({
    business_id: "biz-1",
    site_id: "site-1",
    state: "completed_with_narrative",
    latest_run: {
      id: "run-1",
      business_id: "biz-1",
      site_id: "site-1",
      audit_run_id: "audit-1",
      comparison_run_id: "comparison-1",
      status: "completed",
      total_recommendations: 4,
      critical_recommendations: 1,
      warning_recommendations: 2,
      info_recommendations: 1,
      category_counts_json: {},
      effort_bucket_counts_json: {},
      started_at: "2026-03-21T00:29:00Z",
      completed_at: "2026-03-21T00:30:00Z",
      duration_ms: 60000,
      error_summary: null,
      created_by_principal_id: "principal-1",
      created_at: "2026-03-21T00:29:00Z",
      updated_at: "2026-03-21T00:30:00Z",
    },
    latest_completed_run: {
      id: "run-1",
      business_id: "biz-1",
      site_id: "site-1",
      audit_run_id: "audit-1",
      comparison_run_id: "comparison-1",
      status: "completed",
      total_recommendations: 4,
      critical_recommendations: 1,
      warning_recommendations: 2,
      info_recommendations: 1,
      category_counts_json: {},
      effort_bucket_counts_json: {},
      started_at: "2026-03-21T00:29:00Z",
      completed_at: "2026-03-21T00:30:00Z",
      duration_ms: 60000,
      error_summary: null,
      created_by_principal_id: "principal-1",
      created_at: "2026-03-21T00:29:00Z",
      updated_at: "2026-03-21T00:30:00Z",
    },
    recommendations: {
      items: [
        {
          id: "rec-1",
          business_id: "biz-1",
          site_id: "site-1",
          recommendation_run_id: "run-1",
          audit_run_id: "audit-1",
          comparison_run_id: "comparison-1",
          status: "open",
          category: "SEO",
          severity: "warning",
          priority_score: 80,
          priority_band: "high",
          effort_bucket: "small",
          title: "Fix title tags",
          rationale: "Title tags are missing core keywords.",
          eeat_categories: [],
          primary_eeat_category: null,
          decision_reason: null,
          created_at: "2026-03-21T00:30:00Z",
          updated_at: "2026-03-21T00:31:00Z",
        },
      ],
      total: 1,
      by_status: { open: 1 },
      by_category: { SEO: 1 },
      by_severity: { warning: 1 },
      by_effort_bucket: { small: 1 },
      by_priority_band: { high: 1 },
    },
    latest_narrative: narrativesByRunId["run-1"],
    tuning_suggestions: [],
  });
}

function seedGroupedTimelineWorkspaceData(): void {
  mockFetchAuditRuns.mockResolvedValue({
    items: [
      {
        id: "audit-1",
        business_id: "biz-1",
        site_id: "site-1",
        status: "completed",
        max_pages: 25,
        max_depth: 2,
        pages_discovered: 25,
        created_at: "2026-03-21T10:30:00Z",
        updated_at: "2026-03-21T11:00:00Z",
        started_at: "2026-03-21T10:45:00Z",
        completed_at: "2026-03-21T11:00:00Z",
        crawl_duration_ms: 900000,
        error_summary: null,
        created_by_principal_id: "principal-1",
        pages_crawled: 25,
        pages_skipped: 0,
        duplicate_urls_skipped: 0,
        errors_encountered: 0,
      },
      {
        id: "audit-2",
        business_id: "biz-1",
        site_id: "site-1",
        status: "failed",
        max_pages: 25,
        max_depth: 2,
        pages_discovered: 12,
        created_at: "2026-03-21T08:45:00Z",
        updated_at: "2026-03-21T09:00:00Z",
        started_at: "2026-03-21T08:50:00Z",
        completed_at: "2026-03-21T09:00:00Z",
        crawl_duration_ms: 600000,
        error_summary: "crawl failed",
        created_by_principal_id: "principal-1",
        pages_crawled: 10,
        pages_skipped: 2,
        duplicate_urls_skipped: 0,
        errors_encountered: 1,
      },
      {
        id: "audit-3",
        business_id: "biz-1",
        site_id: "site-1",
        status: "running",
        max_pages: 25,
        max_depth: 2,
        pages_discovered: 8,
        created_at: "2026-03-21T07:30:00Z",
        updated_at: "2026-03-21T08:00:00Z",
        started_at: "2026-03-21T08:00:00Z",
        completed_at: null,
        crawl_duration_ms: null,
        error_summary: null,
        created_by_principal_id: "principal-1",
        pages_crawled: 4,
        pages_skipped: 0,
        duplicate_urls_skipped: 0,
        errors_encountered: 0,
      },
      {
        id: "audit-4",
        business_id: "biz-1",
        site_id: "site-1",
        status: "completed",
        max_pages: 25,
        max_depth: 2,
        pages_discovered: 20,
        created_at: "2026-03-21T06:45:00Z",
        updated_at: "2026-03-21T07:00:00Z",
        started_at: "2026-03-21T06:50:00Z",
        completed_at: "2026-03-21T07:00:00Z",
        crawl_duration_ms: 600000,
        error_summary: null,
        created_by_principal_id: "principal-1",
        pages_crawled: 20,
        pages_skipped: 0,
        duplicate_urls_skipped: 0,
        errors_encountered: 0,
      },
      {
        id: "audit-5",
        business_id: "biz-1",
        site_id: "site-1",
        status: "completed",
        max_pages: 25,
        max_depth: 2,
        pages_discovered: 18,
        created_at: "2026-03-20T21:30:00Z",
        updated_at: "2026-03-20T22:00:00Z",
        started_at: "2026-03-20T21:40:00Z",
        completed_at: "2026-03-20T22:00:00Z",
        crawl_duration_ms: 1200000,
        error_summary: null,
        created_by_principal_id: "principal-1",
        pages_crawled: 18,
        pages_skipped: 0,
        duplicate_urls_skipped: 0,
        errors_encountered: 0,
      },
      {
        id: "audit-6",
        business_id: "biz-1",
        site_id: "site-1",
        status: "completed",
        max_pages: 25,
        max_depth: 2,
        pages_discovered: 16,
        created_at: "2026-03-20T20:30:00Z",
        updated_at: "2026-03-20T21:00:00Z",
        started_at: "2026-03-20T20:45:00Z",
        completed_at: "2026-03-20T21:00:00Z",
        crawl_duration_ms: 900000,
        error_summary: null,
        created_by_principal_id: "principal-1",
        pages_crawled: 16,
        pages_skipped: 0,
        duplicate_urls_skipped: 0,
        errors_encountered: 0,
      },
      {
        id: "audit-7",
        business_id: "biz-1",
        site_id: "site-1",
        status: "completed",
        max_pages: 25,
        max_depth: 2,
        pages_discovered: 14,
        created_at: "2026-03-20T19:45:00Z",
        updated_at: "2026-03-20T20:00:00Z",
        started_at: "2026-03-20T19:50:00Z",
        completed_at: "2026-03-20T20:00:00Z",
        crawl_duration_ms: 600000,
        error_summary: null,
        created_by_principal_id: "principal-1",
        pages_crawled: 14,
        pages_skipped: 0,
        duplicate_urls_skipped: 0,
        errors_encountered: 0,
      },
      {
        id: "audit-8",
        business_id: "biz-1",
        site_id: "site-1",
        status: "completed",
        max_pages: 25,
        max_depth: 2,
        pages_discovered: 10,
        created_at: "2026-03-18T11:45:00Z",
        updated_at: "2026-03-18T12:00:00Z",
        started_at: "2026-03-18T11:50:00Z",
        completed_at: "2026-03-18T12:00:00Z",
        crawl_duration_ms: 600000,
        error_summary: null,
        created_by_principal_id: "principal-1",
        pages_crawled: 10,
        pages_skipped: 0,
        duplicate_urls_skipped: 0,
        errors_encountered: 0,
      },
    ],
    total: 8,
  });

  mockFetchCompetitorSets.mockResolvedValue({
    items: [
      {
        id: "set-1",
        business_id: "biz-1",
        site_id: "site-1",
        name: "Primary Competitors",
        city: null,
        state: null,
        is_active: true,
        created_by_principal_id: "principal-1",
        created_at: "2026-03-20T00:00:00Z",
        updated_at: "2026-03-21T00:00:00Z",
      },
    ],
    total: 1,
  });

  mockFetchCompetitorDomains.mockResolvedValue({
    items: [
      {
        id: "domain-1",
        business_id: "biz-1",
        site_id: "site-1",
        competitor_set_id: "set-1",
        domain: "competitor.com",
        base_url: "https://competitor.com/",
        display_name: "Competitor",
        source: "manual",
        is_active: true,
        notes: null,
        created_at: "2026-03-20T00:00:00Z",
        updated_at: "2026-03-21T00:00:00Z",
      },
    ],
    total: 1,
  });

  mockFetchCompetitorSnapshotRuns.mockResolvedValue({
    items: [
      {
        id: "snapshot-1",
        business_id: "biz-1",
        site_id: "site-1",
        competitor_set_id: "set-1",
        client_audit_run_id: "audit-1",
        status: "completed",
        max_domains: 10,
        max_pages_per_domain: 2,
        max_depth: 1,
        same_domain_only: true,
        domains_targeted: 1,
        domains_completed: 1,
        pages_attempted: 2,
        pages_captured: 2,
        pages_skipped: 0,
        errors_encountered: 0,
        started_at: "2026-03-21T09:50:00Z",
        completed_at: "2026-03-21T10:00:00Z",
        duration_ms: 600000,
        error_summary: null,
        created_by_principal_id: "principal-1",
        created_at: "2026-03-21T09:50:00Z",
        updated_at: "2026-03-21T10:00:00Z",
      },
      {
        id: "snapshot-2",
        business_id: "biz-1",
        site_id: "site-1",
        competitor_set_id: "set-1",
        client_audit_run_id: "audit-5",
        status: "failed",
        max_domains: 10,
        max_pages_per_domain: 2,
        max_depth: 1,
        same_domain_only: true,
        domains_targeted: 1,
        domains_completed: 0,
        pages_attempted: 1,
        pages_captured: 0,
        pages_skipped: 0,
        errors_encountered: 1,
        started_at: "2026-03-20T22:30:00Z",
        completed_at: "2026-03-20T23:00:00Z",
        duration_ms: 1800000,
        error_summary: "snapshot failed",
        created_by_principal_id: "principal-1",
        created_at: "2026-03-20T22:30:00Z",
        updated_at: "2026-03-20T23:00:00Z",
      },
      {
        id: "snapshot-3",
        business_id: "biz-1",
        site_id: "site-1",
        competitor_set_id: "set-1",
        client_audit_run_id: "audit-7",
        status: "completed",
        max_domains: 10,
        max_pages_per_domain: 2,
        max_depth: 1,
        same_domain_only: true,
        domains_targeted: 1,
        domains_completed: 1,
        pages_attempted: 2,
        pages_captured: 2,
        pages_skipped: 0,
        errors_encountered: 0,
        started_at: "2026-03-20T18:30:00Z",
        completed_at: "2026-03-20T19:00:00Z",
        duration_ms: 1800000,
        error_summary: null,
        created_by_principal_id: "principal-1",
        created_at: "2026-03-20T18:30:00Z",
        updated_at: "2026-03-20T19:00:00Z",
      },
    ],
    total: 3,
  });

  mockFetchSiteCompetitorComparisonRuns.mockResolvedValue({
    items: [],
    total: 0,
  });

  mockFetchRecommendations.mockResolvedValue({
    items: [],
    total: 0,
    filtered_summary: {
      total: 0,
      open: 0,
      accepted: 0,
      dismissed: 0,
      high_priority: 0,
    },
  });
  mockFetchRecommendationWorkspaceSummary.mockResolvedValue({
    business_id: "biz-1",
    site_id: "site-1",
    state: "no_runs",
    latest_run: null,
    latest_completed_run: null,
    recommendations: { items: [], total: 0 },
    latest_narrative: null,
    tuning_suggestions: [],
  });

  mockFetchRecommendationRuns.mockResolvedValue({
    items: [],
    total: 0,
  });

  mockFetchLatestRecommendationRunNarrative.mockReset();
}

function seedCompetitorProfileGenerationWorkspaceData(): void {
  seedRichWorkspaceData();

  const run = buildCompetitorProfileGenerationRun({
    id: "gen-run-1",
    status: "completed",
    generated_draft_count: 2,
  });

  const draftOne: CompetitorProfileDraft = {
    id: "draft-1",
    business_id: "biz-1",
    site_id: "site-1",
    generation_run_id: "gen-run-1",
    suggested_name: "Example Alternatives",
    suggested_domain: "example-alternatives.com",
    competitor_type: "direct",
    summary: "Direct overlap in service intent.",
    why_competitor: "Competes for service keywords.",
    evidence: "Heuristic evidence",
    confidence_score: 0.82,
    source: "ai_generated",
    review_status: "pending",
    edited_fields_json: null,
    review_notes: null,
    reviewed_by_principal_id: null,
    reviewed_at: null,
    accepted_competitor_set_id: null,
    accepted_competitor_domain_id: null,
    created_at: "2026-03-21T01:00:00Z",
    updated_at: "2026-03-21T01:00:00Z",
  };

  const draftTwo: CompetitorProfileDraft = {
    id: "draft-2",
    business_id: "biz-1",
    site_id: "site-1",
    generation_run_id: "gen-run-1",
    suggested_name: "Example Marketplace",
    suggested_domain: "example-marketplace.com",
    competitor_type: "marketplace",
    summary: "Marketplace competitor for discovery-stage traffic.",
    why_competitor: "Marketplace terms overlap",
    evidence: "SERP pattern overlap",
    confidence_score: 0.66,
    source: "ai_generated",
    review_status: "pending",
    edited_fields_json: null,
    review_notes: null,
    reviewed_by_principal_id: null,
    reviewed_at: null,
    accepted_competitor_set_id: null,
    accepted_competitor_domain_id: null,
    created_at: "2026-03-21T01:00:00Z",
    updated_at: "2026-03-21T01:00:00Z",
  };

  mockFetchCompetitorProfileGenerationRuns.mockResolvedValue({
    items: [run],
    total: 1,
  });
  mockFetchCompetitorProfileGenerationRunDetail.mockResolvedValue({
    run,
    drafts: [draftOne, draftTwo],
    total_drafts: 2,
  });
  mockFetchCompetitorProfileGenerationSummary.mockResolvedValue({
    business_id: "biz-1",
    site_id: "site-1",
    lookback_days: 30,
    window_start: "2026-02-20T00:00:00Z",
    window_end: "2026-03-21T00:00:00Z",
    queued_count: 0,
    running_count: 0,
    completed_count: 1,
    failed_count: 0,
    retry_child_runs: 0,
    retried_parent_runs: 0,
    failed_runs_retried: 0,
    failure_category_counts: {},
    total_runs: 1,
    total_raw_candidate_count: 2,
    total_included_candidate_count: 2,
    total_excluded_candidate_count: 0,
    exclusion_counts_by_reason: {
      duplicate: 0,
      low_relevance: 0,
      directory_or_aggregator: 0,
      big_box_mismatch: 0,
      existing_domain_match: 0,
      invalid_candidate: 0,
    },
    latest_run_created_at: "2026-03-21T00:59:00Z",
    latest_run_completed_at: "2026-03-21T01:00:00Z",
    latest_completed_run_completed_at: "2026-03-21T01:00:00Z",
    latest_failed_run_completed_at: null,
  });
  mockCreateCompetitorProfileGenerationRun.mockResolvedValue({
    run: buildCompetitorProfileGenerationRun({
      ...run,
      id: "gen-run-2",
      status: "queued",
      created_at: "2026-03-21T01:15:00Z",
      completed_at: null,
      updated_at: "2026-03-21T01:15:00Z",
    }),
    drafts: [],
    total_drafts: 0,
  });
  mockRetryCompetitorProfileGenerationRun.mockResolvedValue({
    run: buildCompetitorProfileGenerationRun({
      ...run,
      id: "gen-run-3",
      parent_run_id: "gen-run-1",
      status: "queued",
      created_at: "2026-03-21T01:16:00Z",
      completed_at: null,
      updated_at: "2026-03-21T01:16:00Z",
    }),
    drafts: [],
    total_drafts: 0,
  });
  mockAcceptCompetitorProfileDraft.mockResolvedValue({
    ...draftOne,
    review_status: "accepted",
    accepted_competitor_set_id: "set-1",
    accepted_competitor_domain_id: "domain-new-1",
    reviewed_by_principal_id: "principal-1",
    reviewed_at: "2026-03-21T01:20:00Z",
  });
  mockRejectCompetitorProfileDraft.mockResolvedValue({
    ...draftTwo,
    review_status: "rejected",
    reviewed_by_principal_id: "principal-1",
    reviewed_at: "2026-03-21T01:21:00Z",
    review_notes: "Not relevant",
  });
  mockEditCompetitorProfileDraft.mockResolvedValue({
    ...draftOne,
    suggested_name: "Edited Competitor Name",
    review_status: "edited",
    edited_fields_json: { suggested_name: "Edited Competitor Name" },
    reviewed_by_principal_id: "principal-1",
    reviewed_at: "2026-03-21T01:22:00Z",
  });
}

beforeEach(() => {
  jest.clearAllMocks();
  jest.spyOn(Date, "now").mockReturnValue(FIXED_NOW_MS);
  window.sessionStorage.clear();
  navigationState.params = { site_id: "site-1" };
  mockUseOperatorContext.mockReturnValue(baseContext());
  seedCompetitorProfileGenerationDefaults();
});

afterEach(() => {
  jest.restoreAllMocks();
});

describe("site workspace timeline controls", () => {
  it("renders 10 events by default and shows show-more control when timeline has more than 10 events", async () => {
    seedRichWorkspaceData();
    render(<SiteWorkspacePage />);

    await screen.findByText("Showing 10 of 19 events");
    expect(screen.getAllByTestId("site-activity-row")).toHaveLength(10);
    expect(screen.getByRole("button", { name: "Show more" })).toBeInTheDocument();
    expect(screen.getByText("Showing 10 of 19 events")).toBeInTheDocument();
  });

  it("renders grouped day headers for visible timeline events", async () => {
    seedGroupedTimelineWorkspaceData();
    render(<SiteWorkspacePage />);

    await screen.findByText("Showing 10 of 11 events");
    const dayHeaders = screen.getAllByTestId("site-activity-day-header").map((item) => item.textContent?.trim());
    expect(dayHeaders).toEqual(["Today", "Yesterday"]);
    expect(dayHeaders.filter((header) => header === "Today")).toHaveLength(1);
    expect(dayHeaders.filter((header) => header === "Yesterday")).toHaveLength(1);
  });

  it("uses Today/Yesterday labels and absolute date labels for older groups", async () => {
    seedGroupedTimelineWorkspaceData();
    const user = userEvent.setup();
    render(<SiteWorkspacePage />);

    await screen.findByRole("button", { name: "Show more" });
    await user.click(screen.getByRole("button", { name: "Show more" }));

    const expectedOlderLabel = new Date("2026-03-18T12:00:00Z").toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
    const dayHeaders = screen.getAllByTestId("site-activity-day-header").map((item) => item.textContent?.trim());
    expect(dayHeaders).toEqual(["Today", "Yesterday", expectedOlderLabel]);
  });

  it("filters by event type client-side", async () => {
    seedRichWorkspaceData();
    const user = userEvent.setup();
    render(<SiteWorkspacePage />);

    await screen.findByRole("checkbox", { name: "Snapshot Runs" });
    await user.click(screen.getByRole("checkbox", { name: "Snapshot Runs" }));

    await waitFor(() => {
      const rows = screen.getAllByTestId("site-activity-row");
      expect(rows.some((row) => row.textContent?.includes("Snapshot Run"))).toBe(false);
      expect(rows.some((row) => row.textContent?.includes("Comparison Run"))).toBe(true);
    });
  });

  it("updates grouped output after event type filter changes", async () => {
    seedGroupedTimelineWorkspaceData();
    const user = userEvent.setup();
    render(<SiteWorkspacePage />);

    await screen.findByRole("checkbox", { name: "Snapshot Runs" });
    await user.click(screen.getByRole("checkbox", { name: "Snapshot Runs" }));

    await waitFor(() => {
      const rows = screen.getAllByTestId("site-activity-row");
      expect(rows.some((row) => row.textContent?.includes("Snapshot Run"))).toBe(false);
      const dayHeaders = screen.getAllByTestId("site-activity-day-header").map((item) => item.textContent?.trim());
      expect(dayHeaders[0]).toBe("Today");
      expect(dayHeaders).toContain("Yesterday");
    });
  });

  it("filters by selected statuses", async () => {
    seedRichWorkspaceData();
    const user = userEvent.setup();
    render(<SiteWorkspacePage />);

    await screen.findByRole("checkbox", { name: "failed" });
    await user.click(screen.getByRole("checkbox", { name: "failed" }));
    await user.click(screen.getByRole("checkbox", { name: "open" }));
    await user.click(screen.getByRole("checkbox", { name: "running" }));

    await waitFor(() => {
      const rows = screen.getAllByTestId("site-activity-row");
      rows.forEach((row) => {
        const statusCell = within(row).getAllByRole("cell")[2];
        expect(statusCell).toHaveTextContent("completed");
      });
    });
  });

  it("updates grouped output after status filter changes", async () => {
    seedGroupedTimelineWorkspaceData();
    const user = userEvent.setup();
    render(<SiteWorkspacePage />);

    await screen.findByRole("checkbox", { name: "completed" });
    await user.click(screen.getByRole("checkbox", { name: "completed" }));
    await user.click(screen.getByRole("checkbox", { name: "running" }));

    await waitFor(() => {
      const rows = screen.getAllByTestId("site-activity-row");
      rows.forEach((row) => {
        const statusCell = within(row).getAllByRole("cell")[2];
        expect(statusCell).toHaveTextContent("failed");
      });
      const dayHeaders = screen.getAllByTestId("site-activity-day-header").map((item) => item.textContent?.trim());
      expect(dayHeaders).toEqual(["Today", "Yesterday"]);
    });
  });

  it("applies combined type + status filters as intersection", async () => {
    seedRichWorkspaceData();
    const user = userEvent.setup();
    render(<SiteWorkspacePage />);

    await screen.findByRole("checkbox", { name: "Audit Runs" });
    await user.click(screen.getByRole("checkbox", { name: "Audit Runs" }));
    await user.click(screen.getByRole("checkbox", { name: "Snapshot Runs" }));
    await user.click(screen.getByRole("checkbox", { name: "Comparison Runs" }));
    await user.click(screen.getByRole("checkbox", { name: "Narratives" }));
    await user.click(screen.getByRole("checkbox", { name: "open" }));
    await user.click(screen.getByRole("checkbox", { name: "failed" }));

    await waitFor(() => {
      const rows = screen.getAllByTestId("site-activity-row");
      expect(rows).toHaveLength(1);
      expect(rows[0]).toHaveTextContent("Recommendation Run");
      const statusCell = within(rows[0]).getAllByRole("cell")[2];
      expect(statusCell).toHaveTextContent("completed");
    });
  });

  it("shows filtered empty message when active filters remove all events", async () => {
    seedRichWorkspaceData();
    const user = userEvent.setup();
    render(<SiteWorkspacePage />);

    await screen.findByRole("checkbox", { name: "Audit Runs" });
    await user.click(screen.getByRole("checkbox", { name: "Audit Runs" }));
    await user.click(screen.getByRole("checkbox", { name: "Snapshot Runs" }));
    await user.click(screen.getByRole("checkbox", { name: "Comparison Runs" }));
    await user.click(screen.getByRole("checkbox", { name: "Recommendation Runs" }));
    await user.click(screen.getByRole("checkbox", { name: "Narratives" }));

    await screen.findByText("No timeline events match the selected filters.");
    expect(screen.queryAllByTestId("site-activity-row")).toHaveLength(0);
  });

  it("supports show more and show less expansion", async () => {
    seedRichWorkspaceData();
    const user = userEvent.setup();
    render(<SiteWorkspacePage />);

    await screen.findByText("Showing 10 of 19 events");
    expect(screen.getAllByTestId("site-activity-row")).toHaveLength(10);
    await user.click(screen.getByRole("button", { name: "Show more" }));
    await waitFor(() => expect(screen.getAllByTestId("site-activity-row")).toHaveLength(19));
    expect(screen.getByRole("button", { name: "Show less" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Show less" }));
    await waitFor(() => expect(screen.getAllByTestId("site-activity-row")).toHaveLength(10));
  });

  it("preserves grouped timeline behavior across show more and show less", async () => {
    seedGroupedTimelineWorkspaceData();
    const user = userEvent.setup();
    render(<SiteWorkspacePage />);

    await screen.findByText("Showing 10 of 11 events");
    expect(screen.getAllByTestId("site-activity-day-header").map((item) => item.textContent?.trim())).toEqual([
      "Today",
      "Yesterday",
    ]);

    await user.click(screen.getByRole("button", { name: "Show more" }));
    await waitFor(() => expect(screen.getAllByTestId("site-activity-row")).toHaveLength(11));
    const expectedOlderLabel = new Date("2026-03-18T12:00:00Z").toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
    expect(screen.getAllByTestId("site-activity-day-header").map((item) => item.textContent?.trim())).toEqual([
      "Today",
      "Yesterday",
      expectedOlderLabel,
    ]);

    await user.click(screen.getByRole("button", { name: "Show less" }));
    await waitFor(() => expect(screen.getAllByTestId("site-activity-row")).toHaveLength(10));
    expect(screen.getAllByTestId("site-activity-day-header").map((item) => item.textContent?.trim())).toEqual([
      "Today",
      "Yesterday",
    ]);
  });

  it("keeps reverse-chronological event ordering inside grouped sections", async () => {
    seedGroupedTimelineWorkspaceData();
    render(<SiteWorkspacePage />);

    await screen.findByText("Showing 10 of 11 events");
    const rows = screen.getAllByTestId("site-activity-row");
    expect(rows[0]).toHaveTextContent("Audit audit-1");
    expect(rows[1]).toHaveTextContent("Snapshot snapshot-1");
    expect(rows[2]).toHaveTextContent("Audit audit-2");
    expect(rows[3]).toHaveTextContent("Audit audit-3");
    expect(rows[4]).toHaveTextContent("Audit audit-4");
  });

  it("renders bounded recommendation narrative tuning suggestions in the workspace narrative section", async () => {
    seedRichWorkspaceData();
    const user = userEvent.setup();
    mockFetchLatestRecommendationRunNarrative.mockReset();
    mockPreviewRecommendationTuningImpact.mockReset();
    mockPreviewRecommendationTuningImpact.mockResolvedValue({
      business_id: "biz-1",
      site_id: "site-1",
      preview_event_id: "preview-event-1",
      source_recommendation_run_id: "run-1",
      source_narrative_id: "narrative-1",
      current_values: {
        competitor_candidate_min_relevance_score: 35,
        competitor_candidate_big_box_penalty: 20,
        competitor_candidate_directory_penalty: 35,
        competitor_candidate_local_alignment_bonus: 10,
      },
      proposed_values: {
        competitor_candidate_min_relevance_score: 30,
        competitor_candidate_big_box_penalty: 20,
        competitor_candidate_directory_penalty: 35,
        competitor_candidate_local_alignment_bonus: 10,
      },
      telemetry_window: {
        lookback_days: 30,
        total_runs: 4,
        total_raw_candidate_count: 10,
        total_included_candidate_count: 4,
        total_excluded_candidate_count: 6,
        exclusion_counts_by_reason: {
          duplicate: 1,
          low_relevance: 3,
          directory_or_aggregator: 1,
          big_box_mismatch: 1,
          existing_domain_match: 0,
          invalid_candidate: 0,
        },
      },
      estimated_impact: {
        insufficient_data: false,
        estimated_included_candidate_delta: 2,
        estimated_excluded_candidate_delta: -2,
        estimated_exclusion_reason_deltas: {
          duplicate: 0,
          low_relevance: -2,
          directory_or_aggregator: 0,
          big_box_mismatch: 0,
          existing_domain_match: 0,
          invalid_candidate: 0,
        },
        summary: "Estimated increase of 2 included candidates over the last 30 days of telemetry.",
        risk_flags: ["Lower minimum relevance score may increase weak or noisy candidates."],
      },
      caveat: "Preview only.",
    });
    mockFetchRecommendationWorkspaceSummary.mockResolvedValue({
      business_id: "biz-1",
      site_id: "site-1",
      state: "completed_with_narrative",
      latest_run: {
        id: "run-1",
        business_id: "biz-1",
        site_id: "site-1",
        audit_run_id: "audit-1",
        comparison_run_id: "comparison-1",
        status: "completed",
        total_recommendations: 4,
        critical_recommendations: 1,
        warning_recommendations: 2,
        info_recommendations: 1,
        category_counts_json: {},
        effort_bucket_counts_json: {},
        started_at: "2026-03-21T00:29:00Z",
        completed_at: "2026-03-21T00:30:00Z",
        duration_ms: 60000,
        error_summary: null,
        created_by_principal_id: "principal-1",
        created_at: "2026-03-21T00:29:00Z",
        updated_at: "2026-03-21T00:30:00Z",
      },
      latest_completed_run: {
        id: "run-1",
        business_id: "biz-1",
        site_id: "site-1",
        audit_run_id: "audit-1",
        comparison_run_id: "comparison-1",
        status: "completed",
        total_recommendations: 4,
        critical_recommendations: 1,
        warning_recommendations: 2,
        info_recommendations: 1,
        category_counts_json: {},
        effort_bucket_counts_json: {},
        started_at: "2026-03-21T00:29:00Z",
        completed_at: "2026-03-21T00:30:00Z",
        duration_ms: 60000,
        error_summary: null,
        created_by_principal_id: "principal-1",
        created_at: "2026-03-21T00:29:00Z",
        updated_at: "2026-03-21T00:30:00Z",
      },
      recommendations: {
        items: [
          {
            id: "rec-1",
            business_id: "biz-1",
            site_id: "site-1",
            recommendation_run_id: "run-1",
            audit_run_id: "audit-1",
            comparison_run_id: "comparison-1",
            status: "open",
            category: "SEO",
            severity: "warning",
            priority_score: 80,
            priority_band: "high",
            effort_bucket: "small",
            title: "Fix title tags",
            rationale: "Title tags are missing core keywords.",
            eeat_categories: [],
            primary_eeat_category: null,
            decision_reason: null,
            created_at: "2026-03-21T00:30:00Z",
            updated_at: "2026-03-21T00:31:00Z",
          },
        ],
        total: 1,
      },
      latest_narrative: {
        id: "narrative-1",
        business_id: "biz-1",
        site_id: "site-1",
        recommendation_run_id: "run-1",
        version: 2,
        status: "completed",
        narrative_text: "Narrative for run 1.",
        top_themes_json: ["titles"],
        sections_json: { summary: "one" },
        provider_name: "provider",
        model_name: "model",
        prompt_version: "v2",
        error_message: null,
        created_by_principal_id: "principal-1",
        created_at: "2026-03-21T00:33:00Z",
        updated_at: "2026-03-21T00:33:00Z",
      },
      tuning_suggestions: [
        {
          setting: "competitor_candidate_min_relevance_score",
          current_value: 35,
          recommended_value: 30,
          reason: "High low_relevance exclusions indicate threshold is too strict.",
          linked_recommendation_ids: ["rec-1"],
          confidence: "medium",
        },
      ],
    });
    mockFetchLatestRecommendationRunNarrative
      .mockResolvedValueOnce({
        id: "narrative-1",
        business_id: "biz-1",
        site_id: "site-1",
        recommendation_run_id: "run-1",
        version: 2,
        status: "completed",
        narrative_text: "Narrative for run 1.",
        top_themes_json: ["titles"],
        sections_json: {
          summary: "one",
          tuning_suggestions: [
            {
              setting: "competitor_candidate_min_relevance_score",
              current_value: 35,
              recommended_value: 30,
              reason: "High low_relevance exclusions indicate threshold is too strict.",
              linked_recommendation_ids: ["rec-1"],
              confidence: "medium",
            },
          ],
        },
        provider_name: "provider",
        model_name: "model",
        prompt_version: "v2",
        error_message: null,
        created_by_principal_id: "principal-1",
        created_at: "2026-03-21T00:33:00Z",
        updated_at: "2026-03-21T00:33:00Z",
      })
      .mockResolvedValueOnce({
        id: "narrative-2",
        business_id: "biz-1",
        site_id: "site-1",
        recommendation_run_id: "run-2",
        version: 1,
        status: "failed",
        narrative_text: null,
        top_themes_json: [],
        sections_json: null,
        provider_name: "provider",
        model_name: "model",
        prompt_version: "v2",
        error_message: "provider failed",
        created_by_principal_id: "principal-1",
        created_at: "2026-03-21T00:31:00Z",
        updated_at: "2026-03-21T00:31:00Z",
      })
      .mockResolvedValueOnce({
        id: "narrative-3",
        business_id: "biz-1",
        site_id: "site-1",
        recommendation_run_id: "run-3",
        version: 1,
        status: "completed",
        narrative_text: "Narrative for run 3.",
        top_themes_json: ["technical"],
        sections_json: { summary: "three" },
        provider_name: "provider",
        model_name: "model",
        prompt_version: "v2",
        error_message: null,
        created_by_principal_id: "principal-1",
        created_at: "2026-03-21T00:29:30Z",
        updated_at: "2026-03-21T00:29:30Z",
      });

    render(<SiteWorkspacePage />);

    await screen.findByRole("heading", { name: "Recommendation Runs and Narratives" });
    await screen.findByTestId("start-here-section");
    expect(screen.getByText("Start Here")).toBeInTheDocument();
    expect(screen.getByText("Adjust minimum relevance score from 35 -> 30")).toBeInTheDocument();
    const startHereButton = screen.getByRole("button", { name: "Preview and Focus" });
    expect((await screen.findAllByRole("link", { name: "run-1" })).length).toBeGreaterThan(0);
    expect(screen.getByText("Minimum relevance score")).toBeInTheDocument();
    expect(screen.getByText("Current -> Suggested:", { exact: false })).toHaveTextContent("35");
    expect(
      screen.getAllByText("High low_relevance exclusions indicate threshold is too strict.").length,
    ).toBeGreaterThan(0);
    await user.click(startHereButton);
    await screen.findAllByText(/Estimated increase of 2 included candidates over the last 30 days of telemetry\./);
    expect(screen.getByText("Impact hint: +2 candidates included")).toBeInTheDocument();
    expect(screen.getByText(/Included delta: \+2; excluded delta: -2/)).toBeInTheDocument();
    expect(
      within(screen.getByTestId("start-here-section")).getByText(
        "Why this first: highest estimated impact on included competitors.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByTestId("tuning-suggestion-card")).toHaveClass("start-here-target-active");
    expect(mockPreviewRecommendationTuningImpact).toHaveBeenCalledWith("token-1", "biz-1", "site-1", {
      recommendation_run_id: "run-1",
      narrative_id: "narrative-1",
      current_values: { competitor_candidate_min_relevance_score: 35 },
      proposed_values: { competitor_candidate_min_relevance_score: 30 },
    });
  });

  it("prioritizes the strongest tuning suggestion for the start-here action", async () => {
    seedRichWorkspaceData();
    mockFetchRecommendationWorkspaceSummary.mockResolvedValue({
      business_id: "biz-1",
      site_id: "site-1",
      state: "completed_with_narrative",
      latest_run: {
        id: "run-1",
        business_id: "biz-1",
        site_id: "site-1",
        audit_run_id: "audit-1",
        comparison_run_id: "comparison-1",
        status: "completed",
        total_recommendations: 2,
        critical_recommendations: 1,
        warning_recommendations: 1,
        info_recommendations: 0,
        category_counts_json: {},
        effort_bucket_counts_json: {},
        started_at: "2026-03-21T00:29:00Z",
        completed_at: "2026-03-21T00:30:00Z",
        duration_ms: 60000,
        error_summary: null,
        created_by_principal_id: "principal-1",
        created_at: "2026-03-21T00:29:00Z",
        updated_at: "2026-03-21T00:30:00Z",
      },
      latest_completed_run: {
        id: "run-1",
        business_id: "biz-1",
        site_id: "site-1",
        audit_run_id: "audit-1",
        comparison_run_id: "comparison-1",
        status: "completed",
        total_recommendations: 2,
        critical_recommendations: 1,
        warning_recommendations: 1,
        info_recommendations: 0,
        category_counts_json: {},
        effort_bucket_counts_json: {},
        started_at: "2026-03-21T00:29:00Z",
        completed_at: "2026-03-21T00:30:00Z",
        duration_ms: 60000,
        error_summary: null,
        created_by_principal_id: "principal-1",
        created_at: "2026-03-21T00:29:00Z",
        updated_at: "2026-03-21T00:30:00Z",
      },
      recommendations: {
        items: [
          {
            id: "rec-1",
            business_id: "biz-1",
            site_id: "site-1",
            recommendation_run_id: "run-1",
            audit_run_id: "audit-1",
            comparison_run_id: "comparison-1",
            status: "open",
            category: "SEO",
            severity: "warning",
            priority_score: 80,
            priority_band: "high",
            effort_bucket: "small",
            title: "Fix title tags",
            rationale: "Title tags are missing core keywords.",
            eeat_categories: [],
            primary_eeat_category: null,
            decision_reason: null,
            created_at: "2026-03-21T00:30:00Z",
            updated_at: "2026-03-21T00:31:00Z",
          },
        ],
        total: 1,
      },
      latest_narrative: {
        id: "narrative-1",
        business_id: "biz-1",
        site_id: "site-1",
        recommendation_run_id: "run-1",
        version: 2,
        status: "completed",
        narrative_text: "Narrative for run 1.",
        top_themes_json: ["titles"],
        sections_json: { summary: "one" },
        provider_name: "provider",
        model_name: "model",
        prompt_version: "v2",
        error_message: null,
        created_by_principal_id: "principal-1",
        created_at: "2026-03-21T00:33:00Z",
        updated_at: "2026-03-21T00:33:00Z",
      },
      tuning_suggestions: [
        {
          setting: "competitor_candidate_min_relevance_score",
          current_value: 35,
          recommended_value: 30,
          reason: "Lower threshold slightly.",
          linked_recommendation_ids: ["rec-1"],
          confidence: "medium",
        },
        {
          setting: "competitor_candidate_directory_penalty",
          current_value: 35,
          recommended_value: 25,
          reason: "Directory exclusions are overrepresented.",
          linked_recommendation_ids: ["rec-1", "rec-2"],
          confidence: "medium",
        },
      ],
    });

    render(<SiteWorkspacePage />);

    const startHereSection = await screen.findByTestId("start-here-section");
    await waitFor(() =>
      expect(within(startHereSection).getByText("Adjust directory penalty from 35 -> 25")).toBeInTheDocument(),
    );
    expect(
      within(startHereSection).getByText(
        "Why this first: linked to multiple recommendations in the latest completed run.",
      ),
    ).toBeInTheDocument();
    expect(within(startHereSection).getByRole("button", { name: "Preview and Focus" })).toBeInTheDocument();
  });

  it("renders insufficient-data tuning preview state safely", async () => {
    seedRichWorkspaceData();
    const user = userEvent.setup();
    mockFetchRecommendationRuns.mockResolvedValue({
      items: [
        {
          id: "run-1",
          business_id: "biz-1",
          site_id: "site-1",
          audit_run_id: "audit-1",
          comparison_run_id: "comparison-1",
          status: "completed",
          total_recommendations: 1,
          critical_recommendations: 0,
          warning_recommendations: 1,
          info_recommendations: 0,
          category_counts_json: {},
          effort_bucket_counts_json: {},
          started_at: "2026-03-21T00:29:00Z",
          completed_at: "2026-03-21T00:30:00Z",
          duration_ms: 60000,
          error_summary: null,
          created_by_principal_id: "principal-1",
          created_at: "2026-03-21T00:29:00Z",
          updated_at: "2026-03-21T00:30:00Z",
        },
      ],
      total: 1,
    });
    mockFetchLatestRecommendationRunNarrative.mockReset();
    mockPreviewRecommendationTuningImpact.mockReset();
    mockFetchRecommendationWorkspaceSummary.mockResolvedValue({
      business_id: "biz-1",
      site_id: "site-1",
      state: "completed_with_narrative",
      latest_run: {
        id: "run-1",
        business_id: "biz-1",
        site_id: "site-1",
        audit_run_id: "audit-1",
        comparison_run_id: "comparison-1",
        status: "completed",
        total_recommendations: 1,
        critical_recommendations: 0,
        warning_recommendations: 1,
        info_recommendations: 0,
        category_counts_json: {},
        effort_bucket_counts_json: {},
        started_at: "2026-03-21T00:29:00Z",
        completed_at: "2026-03-21T00:30:00Z",
        duration_ms: 60000,
        error_summary: null,
        created_by_principal_id: "principal-1",
        created_at: "2026-03-21T00:29:00Z",
        updated_at: "2026-03-21T00:30:00Z",
      },
      latest_completed_run: {
        id: "run-1",
        business_id: "biz-1",
        site_id: "site-1",
        audit_run_id: "audit-1",
        comparison_run_id: "comparison-1",
        status: "completed",
        total_recommendations: 1,
        critical_recommendations: 0,
        warning_recommendations: 1,
        info_recommendations: 0,
        category_counts_json: {},
        effort_bucket_counts_json: {},
        started_at: "2026-03-21T00:29:00Z",
        completed_at: "2026-03-21T00:30:00Z",
        duration_ms: 60000,
        error_summary: null,
        created_by_principal_id: "principal-1",
        created_at: "2026-03-21T00:29:00Z",
        updated_at: "2026-03-21T00:30:00Z",
      },
      recommendations: {
        items: [
          {
            id: "rec-1",
            business_id: "biz-1",
            site_id: "site-1",
            recommendation_run_id: "run-1",
            audit_run_id: "audit-1",
            comparison_run_id: "comparison-1",
            status: "open",
            category: "SEO",
            severity: "warning",
            priority_score: 80,
            priority_band: "high",
            effort_bucket: "small",
            title: "Fix title tags",
            rationale: "Title tags are missing core keywords.",
            eeat_categories: [],
            primary_eeat_category: null,
            decision_reason: null,
            created_at: "2026-03-21T00:30:00Z",
            updated_at: "2026-03-21T00:31:00Z",
          },
        ],
        total: 1,
      },
      latest_narrative: {
        id: "narrative-1",
        business_id: "biz-1",
        site_id: "site-1",
        recommendation_run_id: "run-1",
        version: 2,
        status: "completed",
        narrative_text: "Narrative for run 1.",
        top_themes_json: ["titles"],
        sections_json: { summary: "one" },
        provider_name: "provider",
        model_name: "model",
        prompt_version: "v2",
        error_message: null,
        created_by_principal_id: "principal-1",
        created_at: "2026-03-21T00:33:00Z",
        updated_at: "2026-03-21T00:33:00Z",
      },
      tuning_suggestions: [
        {
          setting: "competitor_candidate_min_relevance_score",
          current_value: 35,
          recommended_value: 30,
          reason: "Low relevance exclusions are high.",
          linked_recommendation_ids: ["rec-1"],
          confidence: "medium",
        },
      ],
    });
    mockFetchLatestRecommendationRunNarrative.mockResolvedValue({
      id: "narrative-1",
      business_id: "biz-1",
      site_id: "site-1",
      recommendation_run_id: "run-1",
      version: 2,
      status: "completed",
      narrative_text: "Narrative for run 1.",
      top_themes_json: ["titles"],
      sections_json: {
        summary: "one",
        tuning_suggestions: [
          {
            setting: "competitor_candidate_min_relevance_score",
            current_value: 35,
            recommended_value: 30,
            reason: "Low relevance exclusions are high.",
            linked_recommendation_ids: ["rec-1"],
            confidence: "medium",
          },
        ],
      },
      provider_name: "provider",
      model_name: "model",
      prompt_version: "v2",
      error_message: null,
      created_by_principal_id: "principal-1",
      created_at: "2026-03-21T00:33:00Z",
      updated_at: "2026-03-21T00:33:00Z",
    });
    mockPreviewRecommendationTuningImpact.mockResolvedValue({
      business_id: "biz-1",
      site_id: "site-1",
      preview_event_id: "preview-event-2",
      source_recommendation_run_id: "run-1",
      source_narrative_id: "narrative-1",
      current_values: {
        competitor_candidate_min_relevance_score: 35,
        competitor_candidate_big_box_penalty: 20,
        competitor_candidate_directory_penalty: 35,
        competitor_candidate_local_alignment_bonus: 10,
      },
      proposed_values: {
        competitor_candidate_min_relevance_score: 30,
        competitor_candidate_big_box_penalty: 20,
        competitor_candidate_directory_penalty: 35,
        competitor_candidate_local_alignment_bonus: 10,
      },
      telemetry_window: {
        lookback_days: 30,
        total_runs: 0,
        total_raw_candidate_count: 0,
        total_included_candidate_count: 0,
        total_excluded_candidate_count: 0,
        exclusion_counts_by_reason: {
          duplicate: 0,
          low_relevance: 0,
          directory_or_aggregator: 0,
          big_box_mismatch: 0,
          existing_domain_match: 0,
          invalid_candidate: 0,
        },
      },
      estimated_impact: {
        insufficient_data: true,
        estimated_included_candidate_delta: 0,
        estimated_excluded_candidate_delta: 0,
        estimated_exclusion_reason_deltas: {
          duplicate: 0,
          low_relevance: 0,
          directory_or_aggregator: 0,
          big_box_mismatch: 0,
          existing_domain_match: 0,
          invalid_candidate: 0,
        },
        summary: "Insufficient recent competitor telemetry for deterministic impact estimation.",
        risk_flags: [],
      },
      caveat: "Preview only.",
    });

    render(<SiteWorkspacePage />);

    await screen.findByRole("heading", { name: "Recommendation Runs and Narratives" });
    expect((await screen.findAllByRole("link", { name: "run-1" })).length).toBeGreaterThan(0);
    await user.click(screen.getAllByRole("button", { name: "Preview Impact" })[0]);
    await screen.findAllByText(/Insufficient recent competitor telemetry for deterministic impact estimation\./);
    expect(screen.getByText(/Included delta: 0; excluded delta: 0/)).toBeInTheDocument();
  });

  it("applies a tuning suggestion with explicit confirmation and refreshes surfaced values", async () => {
    seedRichWorkspaceData();
    const user = userEvent.setup();
    jest.spyOn(window, "confirm").mockReturnValue(true);

    mockFetchBusinessSettings.mockResolvedValue(
      buildBusinessSettings({ competitor_candidate_min_relevance_score: 35 }),
    );
    mockFetchRecommendationWorkspaceSummary.mockResolvedValue({
      business_id: "biz-1",
      site_id: "site-1",
      state: "completed_with_narrative",
      latest_run: {
        id: "run-1",
        business_id: "biz-1",
        site_id: "site-1",
        audit_run_id: "audit-1",
        comparison_run_id: "comparison-1",
        status: "completed",
        total_recommendations: 1,
        critical_recommendations: 0,
        warning_recommendations: 1,
        info_recommendations: 0,
        category_counts_json: {},
        effort_bucket_counts_json: {},
        started_at: "2026-03-21T00:29:00Z",
        completed_at: "2026-03-21T00:30:00Z",
        duration_ms: 60000,
        error_summary: null,
        created_by_principal_id: "principal-1",
        created_at: "2026-03-21T00:29:00Z",
        updated_at: "2026-03-21T00:30:00Z",
      },
      latest_completed_run: {
        id: "run-1",
        business_id: "biz-1",
        site_id: "site-1",
        audit_run_id: "audit-1",
        comparison_run_id: "comparison-1",
        status: "completed",
        total_recommendations: 1,
        critical_recommendations: 0,
        warning_recommendations: 1,
        info_recommendations: 0,
        category_counts_json: {},
        effort_bucket_counts_json: {},
        started_at: "2026-03-21T00:29:00Z",
        completed_at: "2026-03-21T00:30:00Z",
        duration_ms: 60000,
        error_summary: null,
        created_by_principal_id: "principal-1",
        created_at: "2026-03-21T00:29:00Z",
        updated_at: "2026-03-21T00:30:00Z",
      },
      recommendations: {
        items: [
          {
            id: "rec-1",
            business_id: "biz-1",
            site_id: "site-1",
            recommendation_run_id: "run-1",
            audit_run_id: "audit-1",
            comparison_run_id: "comparison-1",
            status: "open",
            category: "SEO",
            severity: "warning",
            priority_score: 80,
            priority_band: "high",
            effort_bucket: "small",
            title: "Fix title tags",
            rationale: "Title tags are missing core keywords.",
            eeat_categories: [],
            primary_eeat_category: null,
            decision_reason: null,
            created_at: "2026-03-21T00:30:00Z",
            updated_at: "2026-03-21T00:31:00Z",
          },
        ],
        total: 1,
      },
      latest_narrative: {
        id: "narrative-1",
        business_id: "biz-1",
        site_id: "site-1",
        recommendation_run_id: "run-1",
        version: 2,
        status: "completed",
        narrative_text: "Narrative for run 1.",
        top_themes_json: ["titles"],
        sections_json: { summary: "one" },
        provider_name: "provider",
        model_name: "model",
        prompt_version: "v2",
        error_message: null,
        created_by_principal_id: "principal-1",
        created_at: "2026-03-21T00:33:00Z",
        updated_at: "2026-03-21T00:33:00Z",
      },
      tuning_suggestions: [
        {
          setting: "competitor_candidate_min_relevance_score",
          current_value: 35,
          recommended_value: 30,
          reason: "High low_relevance exclusions indicate threshold is too strict.",
          linked_recommendation_ids: ["rec-1"],
          confidence: "medium",
        },
      ],
    });
    mockPreviewRecommendationTuningImpact.mockResolvedValue({
      business_id: "biz-1",
      site_id: "site-1",
      preview_event_id: "preview-event-apply-1",
      source_recommendation_run_id: "run-1",
      source_narrative_id: "narrative-1",
      current_values: {
        competitor_candidate_min_relevance_score: 35,
        competitor_candidate_big_box_penalty: 20,
        competitor_candidate_directory_penalty: 35,
        competitor_candidate_local_alignment_bonus: 10,
      },
      proposed_values: {
        competitor_candidate_min_relevance_score: 30,
        competitor_candidate_big_box_penalty: 20,
        competitor_candidate_directory_penalty: 35,
        competitor_candidate_local_alignment_bonus: 10,
      },
      telemetry_window: {
        lookback_days: 30,
        total_runs: 4,
        total_raw_candidate_count: 10,
        total_included_candidate_count: 4,
        total_excluded_candidate_count: 6,
        exclusion_counts_by_reason: {
          duplicate: 1,
          low_relevance: 3,
          directory_or_aggregator: 1,
          big_box_mismatch: 1,
          existing_domain_match: 0,
          invalid_candidate: 0,
        },
      },
      estimated_impact: {
        insufficient_data: false,
        estimated_included_candidate_delta: 2,
        estimated_excluded_candidate_delta: -2,
        estimated_exclusion_reason_deltas: {
          duplicate: 0,
          low_relevance: -2,
          directory_or_aggregator: 0,
          big_box_mismatch: 0,
          existing_domain_match: 0,
          invalid_candidate: 0,
        },
        summary: "Estimated increase of 2 included candidates over the last 30 days of telemetry.",
        risk_flags: ["Lower minimum relevance score may increase weak or noisy candidates."],
      },
      caveat: "Preview only.",
    });
    mockUpdateBusinessSettings.mockResolvedValue(
      buildBusinessSettings({ competitor_candidate_min_relevance_score: 30 }),
    );

    render(<SiteWorkspacePage />);

    await screen.findByText("Minimum relevance score");
    expect(screen.getByText("Current -> Suggested:", { exact: false })).toHaveTextContent("35");
    await user.click(screen.getAllByRole("button", { name: "Preview Impact" })[0]);
    await screen.findAllByText(/Estimated increase of 2 included candidates over the last 30 days of telemetry\./);

    await user.click(screen.getByRole("button", { name: "Apply Suggestion" }));

    await waitFor(() =>
      expect(mockUpdateBusinessSettings).toHaveBeenCalledWith("token-1", "biz-1", {
        competitor_candidate_min_relevance_score: 30,
        competitor_tuning_preview_event_id: "preview-event-apply-1",
      }),
    );
    await waitFor(() => expect(mockFetchRecommendationWorkspaceSummary).toHaveBeenCalledTimes(2));
    expect(screen.getByText("Current -> Suggested:", { exact: false })).toHaveTextContent("30");
    expect(
      screen.getByText(
        "Setting updated: Minimum relevance score is now 30. New run will reflect this change.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Applied" })).toBeDisabled();
  });

  it("surfaces safe apply errors without leaking state across other suggestions", async () => {
    seedRichWorkspaceData();
    const user = userEvent.setup();
    jest.spyOn(window, "confirm").mockReturnValue(true);

    mockFetchRecommendationWorkspaceSummary.mockResolvedValue({
      business_id: "biz-1",
      site_id: "site-1",
      state: "completed_with_narrative",
      latest_run: {
        id: "run-1",
        business_id: "biz-1",
        site_id: "site-1",
        audit_run_id: "audit-1",
        comparison_run_id: "comparison-1",
        status: "completed",
        total_recommendations: 1,
        critical_recommendations: 0,
        warning_recommendations: 1,
        info_recommendations: 0,
        category_counts_json: {},
        effort_bucket_counts_json: {},
        started_at: "2026-03-21T00:29:00Z",
        completed_at: "2026-03-21T00:30:00Z",
        duration_ms: 60000,
        error_summary: null,
        created_by_principal_id: "principal-1",
        created_at: "2026-03-21T00:29:00Z",
        updated_at: "2026-03-21T00:30:00Z",
      },
      latest_completed_run: {
        id: "run-1",
        business_id: "biz-1",
        site_id: "site-1",
        audit_run_id: "audit-1",
        comparison_run_id: "comparison-1",
        status: "completed",
        total_recommendations: 1,
        critical_recommendations: 0,
        warning_recommendations: 1,
        info_recommendations: 0,
        category_counts_json: {},
        effort_bucket_counts_json: {},
        started_at: "2026-03-21T00:29:00Z",
        completed_at: "2026-03-21T00:30:00Z",
        duration_ms: 60000,
        error_summary: null,
        created_by_principal_id: "principal-1",
        created_at: "2026-03-21T00:29:00Z",
        updated_at: "2026-03-21T00:30:00Z",
      },
      recommendations: { items: [], total: 0 },
      latest_narrative: {
        id: "narrative-1",
        business_id: "biz-1",
        site_id: "site-1",
        recommendation_run_id: "run-1",
        version: 2,
        status: "completed",
        narrative_text: "Narrative for run 1.",
        top_themes_json: ["titles"],
        sections_json: { summary: "one" },
        provider_name: "provider",
        model_name: "model",
        prompt_version: "v2",
        error_message: null,
        created_by_principal_id: "principal-1",
        created_at: "2026-03-21T00:33:00Z",
        updated_at: "2026-03-21T00:33:00Z",
      },
      tuning_suggestions: [
        {
          setting: "competitor_candidate_min_relevance_score",
          current_value: 35,
          recommended_value: 30,
          reason: "Suggestion one.",
          linked_recommendation_ids: ["rec-1"],
          confidence: "medium",
        },
        {
          setting: "competitor_candidate_directory_penalty",
          current_value: 35,
          recommended_value: 30,
          reason: "Suggestion two.",
          linked_recommendation_ids: ["rec-1"],
          confidence: "medium",
        },
      ],
    });
    mockUpdateBusinessSettings.mockRejectedValue(
      new ApiRequestError("Competitor quality settings must use bounded integer values.", {
        status: 422,
        detail: null,
      }),
    );

    render(<SiteWorkspacePage />);

    await screen.findByText("Directory penalty");
    expect(screen.getAllByText("Current -> Suggested:", { exact: false }).length).toBeGreaterThan(0);
    expect(screen.getByText("Suggestion two.")).toBeInTheDocument();
    const applyButtons = await screen.findAllByRole("button", { name: "Apply Suggestion" });
    await user.click(applyButtons[0]);

    await screen.findByText("Competitor quality settings must use bounded integer values.");
    expect(screen.getByText("Directory penalty")).toBeInTheDocument();
    expect(screen.getByText("Suggestion two.")).toBeInTheDocument();
    expect(screen.queryAllByText("Competitor quality settings must use bounded integer values.")).toHaveLength(1);
  });

  it("surfaces latest completed deterministic recommendations and ai narrative overlay", async () => {
    seedRichWorkspaceData();
    const user = userEvent.setup();
    render(<SiteWorkspacePage />);

    await screen.findByRole("heading", { name: "Top Insights" });
    const startHereSection = await screen.findByTestId("start-here-section");
    expect(within(startHereSection).getByText("Start Here")).toBeInTheDocument();
    expect(within(startHereSection).getByText("Fix title tags")).toBeInTheDocument();
    expect(within(startHereSection).getByText("Marked HIGH IMPACT")).toBeInTheDocument();
    expect(
      within(startHereSection).getByText(
        "Why this first: highest priority score (80) in the latest completed run.",
      ),
    ).toBeInTheDocument();
    const focusRecommendationButton = within(startHereSection).getByRole("button", { name: "Focus Recommendation" });
    expect(focusRecommendationButton).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("You have 1 actionable improvements")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("0 tuning opportunities identified")).toBeInTheDocument());
    expect(
      screen.getByText("Preview a tuning suggestion to estimate included-candidate impact"),
    ).toBeInTheDocument();
    await screen.findByRole("heading", { name: "Recommendation Runs and Narratives" });
    await screen.findByRole("heading", { name: "Latest Completed Run" });
    await screen.findByRole("heading", { name: "Deterministic Recommendations" });
    expect(screen.getByText("HIGH IMPACT")).toBeInTheDocument();
    expect(screen.getByText("Title tags are missing core keywords.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "AI Narrative Overlay" })).toBeInTheDocument();
    expect(screen.getByText("Narrative for run 1.")).toBeInTheDocument();
    await user.click(focusRecommendationButton);
    expect(document.getElementById("workspace-recommendation-rec-1")).toHaveClass("start-here-target-active");
    expect(mockFetchRecommendationWorkspaceSummary).toHaveBeenCalledWith("token-1", "biz-1", "site-1");
  });

  it("renders action, competitor, and support context when all optional narrative fields are present", async () => {
    seedRichWorkspaceData();
    mockFetchRecommendationWorkspaceSummary.mockResolvedValue(
      buildRecommendationWorkspaceSummary({
        latest_narrative: buildRecommendationNarrative({
          action_summary: {
            primary_action: "Tighten service page headings for emergency plumbing queries.",
            why_it_matters: "This improves local intent coverage for high-converting service terms.",
            first_step: "Update H1 and top two supporting headings on the emergency plumbing page.",
            evidence: ["Recommendation rec-1", "Competitor pages cover emergency intent more clearly"],
          },
          competitor_influence: {
            used: true,
            summary: "Nearby competitors are outperforming on emergency intent clarity.",
            top_opportunities: ["Clarify emergency response messaging", "Strengthen trust signals above the fold"],
            competitor_names: ["Rapid Rooter", "Denver Drain Pros"],
          },
          signal_summary: {
            support_level: "high",
            evidence_sources: ["site", "competitors", "references"],
            competitor_signal_used: true,
            site_signal_used: true,
            reference_signal_used: true,
          },
        }),
      }),
    );

    render(<SiteWorkspacePage />);

    await screen.findByRole("heading", { name: "AI Narrative Overlay" });
    const actionSummary = screen.getByTestId("narrative-action-summary");
    expect(within(actionSummary).getByText("Next best move")).toBeInTheDocument();
    expect(
      within(actionSummary).getByText("Tighten service page headings for emergency plumbing queries."),
    ).toBeInTheDocument();
    expect(
      within(actionSummary).getByText(
        "Why this matters: This improves local intent coverage for high-converting service terms.",
      ),
    ).toBeInTheDocument();
    expect(
      within(actionSummary).getByText(
        "Start here: Update H1 and top two supporting headings on the emergency plumbing page.",
      ),
    ).toBeInTheDocument();
    expect(within(actionSummary).getByText("Recommendation rec-1")).toBeInTheDocument();

    const competitorInfluence = screen.getByTestId("narrative-competitor-influence");
    expect(within(competitorInfluence).getByText("Competitor-informed")).toBeInTheDocument();
    expect(
      within(competitorInfluence).getByText("Nearby competitors are outperforming on emergency intent clarity."),
    ).toBeInTheDocument();
    expect(
      within(competitorInfluence).getByText(
        "Top opportunities: Clarify emergency response messaging, Strengthen trust signals above the fold",
      ),
    ).toBeInTheDocument();
    expect(
      within(competitorInfluence).getByText("Nearby competitors: Rapid Rooter, Denver Drain Pros"),
    ).toBeInTheDocument();

    const signalSummary = screen.getByTestId("narrative-signal-summary");
    expect(within(signalSummary).getByText("Backed by")).toBeInTheDocument();
    expect(within(signalSummary).getByText("Support level: High")).toBeInTheDocument();
    expect(within(signalSummary).getByText("site")).toBeInTheDocument();
    expect(within(signalSummary).getByText("competitors")).toBeInTheDocument();
    expect(within(signalSummary).getByText("references")).toBeInTheDocument();
    expect(
      within(signalSummary).getByText("Signal check: site yes; competitors yes; references yes."),
    ).toBeInTheDocument();
  });

  it("renders deterministic start-here-by-theme helper when provided", async () => {
    seedRichWorkspaceData();
    const user = userEvent.setup();
    mockFetchRecommendationWorkspaceSummary.mockResolvedValue(
      buildRecommendationWorkspaceSummary({
        start_here: {
          theme: "trust_and_legitimacy",
          theme_label: "Trust & legitimacy",
          recommendation_id: "rec-1",
          title: "Fix title tags",
          reason: "Start here because competitor-backed evidence highlights this gap first.",
          context_flags: ["competitor_backed", "pending_refresh_context"],
        },
      }),
    );

    render(<SiteWorkspacePage />);

    const helper = await screen.findByTestId("start-here-theme-helper");
    expect(within(helper).getByText("Start here by theme")).toBeInTheDocument();
    expect(within(helper).getByText("Trust & legitimacy")).toBeInTheDocument();
    expect(within(helper).getByText("Fix title tags")).toBeInTheDocument();
    expect(
      within(helper).getByText("Start here because competitor-backed evidence highlights this gap first."),
    ).toBeInTheDocument();
    expect(within(helper).getByText("Competitor-backed")).toBeInTheDocument();
    expect(within(helper).getByText("Refresh pending")).toBeInTheDocument();

    await user.click(within(helper).getByRole("button", { name: "Jump to recommendation" }));
    expect(document.getElementById("workspace-recommendation-rec-1")).toHaveClass("start-here-target-active");
  });

  it("keeps start-here jump/focus working with grouped recommendation sections", async () => {
    seedRichWorkspaceData();
    const user = userEvent.setup();
    mockFetchRecommendationWorkspaceSummary.mockResolvedValue(
      buildRecommendationWorkspaceSummary({
        recommendations: {
          items: [
            buildRecommendation({
              id: "rec-theme-jump-1",
              title: "Publish license and insurance proof",
              theme: "trust_and_legitimacy",
              theme_label: "Trust & legitimacy",
            }),
            buildRecommendation({
              id: "rec-theme-jump-2",
              title: "Publish project stories for core services",
              theme: "experience_and_proof",
              theme_label: "Experience & proof",
            }),
          ],
          total: 2,
        },
        grouped_recommendations: [
          {
            theme: "trust_and_legitimacy",
            label: "Trust & legitimacy",
            count: 1,
            recommendation_ids: ["rec-theme-jump-1"],
          },
          {
            theme: "experience_and_proof",
            label: "Experience & proof",
            count: 1,
            recommendation_ids: ["rec-theme-jump-2"],
          },
        ],
        start_here: {
          theme: "experience_and_proof",
          theme_label: "Experience & proof",
          recommendation_id: "rec-theme-jump-2",
          title: "Publish project stories for core services",
          reason: "Start here because this is the first action in the strongest visible theme gap.",
          context_flags: [],
        },
      }),
    );

    render(<SiteWorkspacePage />);

    await screen.findByTestId("recommendation-theme-groups");
    const helper = await screen.findByTestId("start-here-theme-helper");
    expect(within(helper).getByText("Experience & proof")).toBeInTheDocument();

    await user.click(within(helper).getByRole("button", { name: "Jump to recommendation" }));
    expect(document.getElementById("workspace-recommendation-rec-theme-jump-2")).toHaveClass(
      "start-here-target-active",
    );
  });

  it("keeps start-here-by-theme helper hidden when summary omits it", async () => {
    seedRichWorkspaceData();
    mockFetchRecommendationWorkspaceSummary.mockResolvedValue(
      buildRecommendationWorkspaceSummary({
        start_here: null,
      }),
    );

    render(<SiteWorkspacePage />);

    await screen.findByRole("heading", { name: "AI Narrative Overlay" });
    expect(screen.queryByTestId("start-here-theme-helper")).not.toBeInTheDocument();
  });

  it("renders only action summary when competitor and support context are absent", async () => {
    seedRichWorkspaceData();
    mockFetchRecommendationWorkspaceSummary.mockResolvedValue(
      buildRecommendationWorkspaceSummary({
        latest_narrative: buildRecommendationNarrative({
          action_summary: {
            primary_action: "Publish a dedicated emergency service FAQ section.",
            why_it_matters: "This improves answer relevance for urgent local searches.",
            first_step: "Add top customer emergency questions to the service page.",
            evidence: ["Recommendation rec-1"],
          },
          competitor_influence: null,
          signal_summary: null,
        }),
      }),
    );

    render(<SiteWorkspacePage />);

    await screen.findByRole("heading", { name: "AI Narrative Overlay" });
    expect(screen.getByTestId("narrative-action-summary")).toBeInTheDocument();
    expect(screen.queryByTestId("narrative-competitor-influence")).not.toBeInTheDocument();
    expect(screen.queryByTestId("narrative-signal-summary")).not.toBeInTheDocument();
  });

  it("preserves legacy narrative rendering when optional narrative fields are missing", async () => {
    seedRichWorkspaceData();
    mockFetchRecommendationWorkspaceSummary.mockResolvedValue(
      buildRecommendationWorkspaceSummary({
        latest_narrative: buildRecommendationNarrative({
          action_summary: null,
          competitor_influence: null,
          signal_summary: null,
        }),
      }),
    );

    render(<SiteWorkspacePage />);

    await screen.findByRole("heading", { name: "AI Narrative Overlay" });
    expect(screen.getByText("Narrative for run 1.")).toBeInTheDocument();
    expect(screen.queryByTestId("narrative-action-summary")).not.toBeInTheDocument();
    expect(screen.queryByTestId("narrative-competitor-influence")).not.toBeInTheDocument();
    expect(screen.queryByTestId("narrative-signal-summary")).not.toBeInTheDocument();
  });

  it("renders competitor rationale block without support summary when only competitor influence exists", async () => {
    seedRichWorkspaceData();
    mockFetchRecommendationWorkspaceSummary.mockResolvedValue(
      buildRecommendationWorkspaceSummary({
        latest_narrative: buildRecommendationNarrative({
          action_summary: null,
          competitor_influence: {
            used: true,
            summary: "Competitor pages are stronger on local conversion trust signals.",
            top_opportunities: ["Add local proof points above the fold"],
            competitor_names: ["Trusted Denver Plumbing"],
          },
          signal_summary: null,
        }),
      }),
    );

    render(<SiteWorkspacePage />);

    await screen.findByRole("heading", { name: "AI Narrative Overlay" });
    expect(screen.getByTestId("narrative-competitor-influence")).toBeInTheDocument();
    expect(screen.queryByTestId("narrative-action-summary")).not.toBeInTheDocument();
    expect(screen.queryByTestId("narrative-signal-summary")).not.toBeInTheDocument();
  });

  it("renders support indicators without competitor rationale when only signal summary exists", async () => {
    seedRichWorkspaceData();
    mockFetchRecommendationWorkspaceSummary.mockResolvedValue(
      buildRecommendationWorkspaceSummary({
        latest_narrative: buildRecommendationNarrative({
          action_summary: null,
          competitor_influence: null,
          signal_summary: {
            support_level: "medium",
            evidence_sources: ["site", "themes"],
            competitor_signal_used: false,
            site_signal_used: true,
            reference_signal_used: false,
          },
        }),
      }),
    );

    render(<SiteWorkspacePage />);

    await screen.findByRole("heading", { name: "AI Narrative Overlay" });
    expect(screen.getByTestId("narrative-signal-summary")).toBeInTheDocument();
    expect(screen.getByText("Support level: Medium")).toBeInTheDocument();
    expect(screen.queryByTestId("narrative-action-summary")).not.toBeInTheDocument();
    expect(screen.queryByTestId("narrative-competitor-influence")).not.toBeInTheDocument();
  });

  it("renders recommendation EEAT badges and workspace EEAT gap summary when metadata exists", async () => {
    seedRichWorkspaceData();
    mockFetchRecommendationWorkspaceSummary.mockResolvedValue(
      buildRecommendationWorkspaceSummary({
        recommendations: {
          items: [
            buildRecommendation({
              id: "rec-eeat-1",
              title: "Publish license and insurance proof",
              eeat_categories: ["trustworthiness", "authoritativeness"],
              primary_eeat_category: "trustworthiness",
              priority_reasons: ["competitor_gap", "trust_gap", "high_clarity_action"],
              primary_priority_reason: "competitor_gap",
            }),
          ],
          total: 1,
        },
        ordering_explanation: {
          message: "Ordering reflects deterministic recommendation metadata only; no score is used.",
          context_reasons: ["competitor_gap", "trust_gap"],
        },
        eeat_gap_summary: {
          top_gap_categories: ["trustworthiness", "experience"],
          supporting_signals: [
            "Competitor signal: add verified review badges",
            "Recommendation: Publish license and insurance proof",
          ],
          message: "Visible EEAT gaps: Trustworthiness, Experience.",
        },
      }),
    );

    render(<SiteWorkspacePage />);

    await screen.findByRole("heading", { name: "Latest Completed Run" });
    const eeatBadges = screen.getByTestId("recommendation-eeat-badges");
    expect(within(eeatBadges).getByText("Trustworthiness")).toBeInTheDocument();
    expect(within(eeatBadges).getByText("Authoritativeness")).toBeInTheDocument();
    const priorityReasonBadges = screen.getByTestId("recommendation-priority-reasons");
    expect(within(priorityReasonBadges).getByText("Competitor gap")).toBeInTheDocument();
    expect(within(priorityReasonBadges).getByText("Trust gap")).toBeInTheDocument();
    expect(within(priorityReasonBadges).getByText("Clear next step")).toBeInTheDocument();

    const orderingExplanation = screen.getByTestId("recommendation-ordering-explanation");
    expect(within(orderingExplanation).getByText("Why this order")).toBeInTheDocument();
    expect(
      within(orderingExplanation).getByText(
        "Ordering reflects deterministic recommendation metadata only; no score is used.",
      ),
    ).toBeInTheDocument();

    const gapSummary = screen.getByTestId("narrative-eeat-gap-summary");
    expect(within(gapSummary).getByText("EEAT gap summary")).toBeInTheDocument();
    expect(within(gapSummary).getByText("Trustworthiness")).toBeInTheDocument();
    expect(within(gapSummary).getByText("Experience")).toBeInTheDocument();
    expect(within(gapSummary).getByText("Visible EEAT gaps: Trustworthiness, Experience.")).toBeInTheDocument();
  });

  it("keeps workspace EEAT metadata blocks hidden when response omits them", async () => {
    seedRichWorkspaceData();
    mockFetchRecommendationWorkspaceSummary.mockResolvedValue(
      buildRecommendationWorkspaceSummary({
        recommendations: {
          items: [
            buildRecommendation({
              id: "rec-plain-1",
              title: "Fix title tags",
              eeat_categories: [],
              primary_eeat_category: null,
              priority_reasons: [],
              primary_priority_reason: null,
            }),
          ],
          total: 1,
        },
        ordering_explanation: null,
        eeat_gap_summary: null,
      }),
    );

    render(<SiteWorkspacePage />);

    await screen.findByRole("heading", { name: "Latest Completed Run" });
    expect(screen.queryByTestId("recommendation-eeat-badges")).not.toBeInTheDocument();
    expect(screen.queryByTestId("recommendation-priority-reasons")).not.toBeInTheDocument();
    expect(screen.queryByTestId("recommendation-ordering-explanation")).not.toBeInTheDocument();
    expect(screen.queryByTestId("narrative-eeat-gap-summary")).not.toBeInTheDocument();
  });

  it("renders deterministic recommendation theme groups when grouped metadata is present", async () => {
    seedRichWorkspaceData();
    mockFetchRecommendationWorkspaceSummary.mockResolvedValue(
      buildRecommendationWorkspaceSummary({
        recommendations: {
          items: [
            buildRecommendation({
              id: "rec-theme-1",
              title: "Publish license and insurance trust proof",
              eeat_categories: ["trustworthiness"],
              primary_eeat_category: "trustworthiness",
              theme: "trust_and_legitimacy",
              theme_label: "Trust & legitimacy",
            }),
            buildRecommendation({
              id: "rec-theme-2",
              title: "Publish project stories and before/after proof",
              eeat_categories: ["experience"],
              primary_eeat_category: "experience",
              theme: "experience_and_proof",
              theme_label: "Experience & proof",
            }),
            buildRecommendation({
              id: "rec-theme-3",
              title: "Add recognized directory citations and credentials",
              eeat_categories: ["authoritativeness"],
              primary_eeat_category: "authoritativeness",
              theme: "authority_and_visibility",
              theme_label: "Authority & visibility",
            }),
            buildRecommendation({
              id: "rec-theme-4",
              title: "Publish your project intake process and quality checks",
              eeat_categories: ["expertise"],
              primary_eeat_category: "expertise",
              theme: "expertise_and_process",
              theme_label: "Expertise & process",
            }),
            buildRecommendation({
              id: "rec-theme-5",
              title: "Improve title tags and service-page structure",
              theme: "general_site_improvement",
              theme_label: "General site improvement",
            }),
          ],
          total: 5,
        },
        grouped_recommendations: [
          {
            theme: "trust_and_legitimacy",
            label: "Trust & legitimacy",
            count: 1,
            recommendation_ids: ["rec-theme-1"],
          },
          {
            theme: "experience_and_proof",
            label: "Experience & proof",
            count: 1,
            recommendation_ids: ["rec-theme-2"],
          },
          {
            theme: "authority_and_visibility",
            label: "Authority & visibility",
            count: 1,
            recommendation_ids: ["rec-theme-3"],
          },
          {
            theme: "expertise_and_process",
            label: "Expertise & process",
            count: 1,
            recommendation_ids: ["rec-theme-4"],
          },
          {
            theme: "general_site_improvement",
            label: "General site improvement",
            count: 1,
            recommendation_ids: ["rec-theme-5"],
          },
        ],
      }),
    );

    render(<SiteWorkspacePage />);

    await screen.findByRole("heading", { name: "Deterministic Recommendations" });
    const groupedBlock = screen.getByTestId("recommendation-theme-groups");
    expect(groupedBlock).toBeInTheDocument();
    const renderedThemeOrder = Array.from(
      groupedBlock.querySelectorAll('[data-testid^="recommendation-theme-group-"] strong'),
    ).map((node) => (node.textContent || "").trim());
    expect(renderedThemeOrder).toEqual([
      "Trust & legitimacy",
      "Experience & proof",
      "Authority & visibility",
      "Expertise & process",
      "General site improvement",
    ]);

    const trustGroup = screen.getByTestId("recommendation-theme-group-trust_and_legitimacy");
    expect(within(trustGroup).getByText("Trust & legitimacy")).toBeInTheDocument();
    expect(within(trustGroup).getByText("Publish license and insurance trust proof")).toBeInTheDocument();
    expect(
      within(trustGroup).getByText(
        "Improve visible business trust signals like reviews, verification, and contact legitimacy.",
      ),
    ).toBeInTheDocument();
    expect(within(trustGroup).getAllByRole("row")).toHaveLength(2);

    const experienceGroup = screen.getByTestId("recommendation-theme-group-experience_and_proof");
    expect(within(experienceGroup).getByText("Experience & proof")).toBeInTheDocument();
    expect(within(experienceGroup).getByText("Publish project stories and before/after proof")).toBeInTheDocument();
    expect(
      within(experienceGroup).getByText(
        "Show proof of real work with testimonials, project examples, and outcome evidence.",
      ),
    ).toBeInTheDocument();
    expect(within(experienceGroup).getAllByRole("row")).toHaveLength(2);

    const authorityGroup = screen.getByTestId("recommendation-theme-group-authority_and_visibility");
    expect(within(authorityGroup).getByText("Authority & visibility")).toBeInTheDocument();
    expect(within(authorityGroup).getByText("Add recognized directory citations and credentials")).toBeInTheDocument();
    expect(
      within(authorityGroup).getByText(
        "Strengthen external credibility through citations, listings, and recognized signals.",
      ),
    ).toBeInTheDocument();
    expect(within(authorityGroup).getAllByRole("row")).toHaveLength(2);

    const expertiseGroup = screen.getByTestId("recommendation-theme-group-expertise_and_process");
    expect(within(expertiseGroup).getByText("Expertise & process")).toBeInTheDocument();
    expect(
      within(expertiseGroup).getByText("Publish your project intake process and quality checks"),
    ).toBeInTheDocument();
    expect(
      within(expertiseGroup).getByText(
        "Clarify how you work and what makes your process credible and capable.",
      ),
    ).toBeInTheDocument();
    expect(within(expertiseGroup).getAllByRole("row")).toHaveLength(2);

    const generalGroup = screen.getByTestId("recommendation-theme-group-general_site_improvement");
    expect(within(generalGroup).getByText("General site improvement")).toBeInTheDocument();
    expect(within(generalGroup).getByText("Improve title tags and service-page structure")).toBeInTheDocument();
    expect(
      within(generalGroup).getByText(
        "Improve core site clarity and fundamentals that support overall performance.",
      ),
    ).toBeInTheDocument();
    expect(within(generalGroup).getAllByRole("row")).toHaveLength(2);
  });

  it("keeps grouped wrapper hidden when grouped metadata is absent or trivial", async () => {
    seedRichWorkspaceData();
    mockFetchRecommendationWorkspaceSummary.mockResolvedValue(
      buildRecommendationWorkspaceSummary({
        recommendations: {
          items: [
            buildRecommendation({
              id: "rec-single-theme",
              title: "Publish trust proof across key service pages",
              theme: "trust_and_legitimacy",
              theme_label: "Trust & legitimacy",
            }),
          ],
          total: 1,
        },
        grouped_recommendations: [
          {
            theme: "trust_and_legitimacy",
            label: "Trust & legitimacy",
            count: 1,
            recommendation_ids: ["rec-single-theme"],
          },
        ],
      }),
    );

    render(<SiteWorkspacePage />);

    await screen.findByRole("heading", { name: "Deterministic Recommendations" });
    expect(screen.queryByTestId("recommendation-theme-groups")).not.toBeInTheDocument();
    expect(screen.queryByTestId("recommendation-theme-summary-trust_and_legitimacy")).not.toBeInTheDocument();
    expect(screen.getAllByText("Publish trust proof across key service pages").length).toBeGreaterThan(0);
  });

  it("renders recommendation apply outcome context when workspace summary includes apply metadata", async () => {
    seedRichWorkspaceData();
    mockFetchRecommendationWorkspaceSummary.mockResolvedValue(
      buildRecommendationWorkspaceSummary({
        apply_outcome: {
          applied: true,
          applied_at: "2026-03-21T01:40:00Z",
          recommendation_label: "Fix title tags",
          expected_change: "Estimated increase of 2 included candidates over the last 30 days of telemetry.",
          reflected_on_next_run: "The next completed recommendation or competitor generation run should reflect this change.",
          source: "recommendation",
        },
      }),
    );

    render(<SiteWorkspacePage />);

    await screen.findByRole("heading", { name: "AI Narrative Overlay" });
    const applyOutcome = screen.getByTestId("narrative-apply-outcome");
    expect(within(applyOutcome).getByText("Latest apply outcome")).toBeInTheDocument();
    expect(within(applyOutcome).getByText("Applied")).toBeInTheDocument();
    expect(within(applyOutcome).getByText("Recommendation: Fix title tags")).toBeInTheDocument();
    expect(
      within(applyOutcome).getByText(
        "Expected change: Estimated increase of 2 included candidates over the last 30 days of telemetry.",
      ),
    ).toBeInTheDocument();
    expect(
      within(applyOutcome).getByText(
        "Reflects on next run: The next completed recommendation or competitor generation run should reflect this change.",
      ),
    ).toBeInTheDocument();
    expect(within(applyOutcome).getByText(/Applied at:/)).toBeInTheDocument();
    expect(within(applyOutcome).getByText("Source: recommendation-guided tuning action.")).toBeInTheDocument();
  });

  it("keeps apply outcome block hidden when workspace summary does not include apply metadata", async () => {
    seedRichWorkspaceData();
    mockFetchRecommendationWorkspaceSummary.mockResolvedValue(
      buildRecommendationWorkspaceSummary({
        apply_outcome: null,
      }),
    );

    render(<SiteWorkspacePage />);

    await screen.findByRole("heading", { name: "AI Narrative Overlay" });
    expect(screen.queryByTestId("narrative-apply-outcome")).not.toBeInTheDocument();
  });

  it("keeps analysis freshness block hidden when workspace summary omits freshness metadata", async () => {
    seedRichWorkspaceData();
    mockFetchRecommendationWorkspaceSummary.mockResolvedValue(
      buildRecommendationWorkspaceSummary(),
    );

    render(<SiteWorkspacePage />);

    await screen.findByRole("heading", { name: "AI Narrative Overlay" });
    expect(screen.queryByTestId("narrative-analysis-freshness")).not.toBeInTheDocument();
  });

  it("renders fresh analysis freshness status when analysis is up to date", async () => {
    seedRichWorkspaceData();
    mockFetchRecommendationWorkspaceSummary.mockResolvedValue(
      buildRecommendationWorkspaceSummary({
        analysis_freshness: buildRecommendationAnalysisFreshness(),
      }),
    );

    render(<SiteWorkspacePage />);

    await screen.findByRole("heading", { name: "AI Narrative Overlay" });
    const freshness = screen.getByTestId("narrative-analysis-freshness");
    expect(within(freshness).getByText("Analysis freshness")).toBeInTheDocument();
    expect(within(freshness).getByText("Fresh")).toBeInTheDocument();
    expect(
      within(freshness).getByText("Analysis is up to date with the latest applied changes."),
    ).toBeInTheDocument();
    expect(within(freshness).getByText(/Analysis generated at:/)).toBeInTheDocument();
  });

  it("renders pending-refresh analysis freshness status when apply is newer than analysis", async () => {
    seedRichWorkspaceData();
    mockFetchRecommendationWorkspaceSummary.mockResolvedValue(
      buildRecommendationWorkspaceSummary({
        analysis_freshness: buildRecommendationAnalysisFreshness({
          status: "pending_refresh",
          analysis_generated_at: "2026-03-21T00:30:00Z",
          last_apply_at: "2026-03-21T01:30:00Z",
          message: "Changes were applied after this analysis. Refresh or re-run to reflect them.",
        }),
      }),
    );

    render(<SiteWorkspacePage />);

    await screen.findByRole("heading", { name: "AI Narrative Overlay" });
    const freshness = screen.getByTestId("narrative-analysis-freshness");
    expect(within(freshness).getByText("Pending Refresh")).toBeInTheDocument();
    expect(
      within(freshness).getByText("Changes were applied after this analysis. Refresh or re-run to reflect them."),
    ).toBeInTheDocument();
    expect(within(freshness).getByText(/Last apply at:/)).toBeInTheDocument();
  });

  it("renders location source metadata when workspace summary includes provenance", async () => {
    seedRichWorkspaceData();
    mockFetchRecommendationWorkspaceSummary.mockResolvedValue(
      buildRecommendationWorkspaceSummary({
        analysis_freshness: buildRecommendationAnalysisFreshness(),
        site_location_context_source: "zip_capture",
      }),
    );

    render(<SiteWorkspacePage />);

    await screen.findByRole("heading", { name: "AI Narrative Overlay" });
    const freshness = screen.getByTestId("narrative-analysis-freshness");
    expect(within(freshness).getByText("Location source: ZIP provided")).toBeInTheDocument();
  });

  it("renders competitor context health block with per-check statuses", async () => {
    seedRichWorkspaceData();
    mockFetchRecommendationWorkspaceSummary.mockResolvedValue(
      buildRecommendationWorkspaceSummary({
        competitor_context_health: {
          status: "mixed",
          message: "Competitor matching has partial business context; results may be narrower or more conservative.",
          checks: [
            {
              key: "location_context",
              label: "Location context",
              status: "weak",
              detail: "Location context is weak or missing; local competitor matching may be conservative.",
            },
            {
              key: "industry_context",
              label: "Industry context",
              status: "strong",
              detail: "Industry context is available: Home services.",
            },
            {
              key: "service_focus",
              label: "Service focus",
              status: "strong",
              detail: "Service focus terms are available: plumbing, drain cleaning.",
            },
            {
              key: "target_customer_context",
              label: "Target customer context",
              status: "weak",
              detail: "Target customer context is generic; competitor matching may be conservative.",
            },
          ],
        },
      }),
    );

    render(<SiteWorkspacePage />);

    await screen.findByRole("heading", { name: "AI Narrative Overlay" });
    const contextHealth = screen.getByTestId("competitor-context-health");
    expect(within(contextHealth).getByText("Competitor context health")).toBeInTheDocument();
    expect(within(contextHealth).getByText("Mixed")).toBeInTheDocument();
    expect(
      within(contextHealth).getByText(
        "Competitor matching has partial business context; results may be narrower or more conservative.",
      ),
    ).toBeInTheDocument();
    expect(
      within(contextHealth).getByText(
        "Location context: Location context is weak or missing; local competitor matching may be conservative.",
      ),
    ).toBeInTheDocument();
    expect(
      within(contextHealth).getByText("Industry context: Industry context is available: Home services."),
    ).toBeInTheDocument();
  });

  it("keeps competitor context health block hidden when metadata is absent", async () => {
    seedRichWorkspaceData();
    mockFetchRecommendationWorkspaceSummary.mockResolvedValue(
      buildRecommendationWorkspaceSummary({
        competitor_context_health: null,
      }),
    );

    render(<SiteWorkspacePage />);

    await screen.findByRole("heading", { name: "AI Narrative Overlay" });
    expect(screen.queryByTestId("competitor-context-health")).not.toBeInTheDocument();
  });

  it("renders unknown analysis freshness safely when timestamps are insufficient", async () => {
    seedRichWorkspaceData();
    mockFetchRecommendationWorkspaceSummary.mockResolvedValue(
      buildRecommendationWorkspaceSummary({
        analysis_freshness: buildRecommendationAnalysisFreshness({
          status: "unknown",
          analysis_generated_at: null,
          last_apply_at: null,
          message: "Analysis freshness could not be determined.",
        }),
      }),
    );

    render(<SiteWorkspacePage />);

    await screen.findByRole("heading", { name: "AI Narrative Overlay" });
    const freshness = screen.getByTestId("narrative-analysis-freshness");
    expect(within(freshness).getByText("Unknown")).toBeInTheDocument();
    expect(within(freshness).getByText("Analysis freshness could not be determined.")).toBeInTheDocument();
    expect(within(freshness).queryByText(/Location source:/)).not.toBeInTheDocument();
  });

  it("shows ZIP capture modal when location context is weak and no ZIP is stored", async () => {
    seedRichWorkspaceData();
    mockFetchRecommendationWorkspaceSummary.mockResolvedValue(
      buildRecommendationWorkspaceSummary({
        site_location_context: "Location not yet established from available business/site data.",
        site_location_context_strength: "weak",
        site_primary_location: null,
        site_primary_business_zip: null,
      }),
    );

    render(<SiteWorkspacePage />);

    const modal = await screen.findByTestId("zip-capture-modal");
    expect(within(modal).getByText("Where do you primarily do business?")).toBeInTheDocument();
    expect(within(modal).getByText("Save")).toBeInTheDocument();
    expect(within(modal).getByText("Skip for now")).toBeInTheDocument();
  });

  it("does not show ZIP capture modal when ZIP is already stored", async () => {
    seedRichWorkspaceData();
    mockFetchRecommendationWorkspaceSummary.mockResolvedValue(
      buildRecommendationWorkspaceSummary({
        site_location_context: "Serving area around ZIP code 80538",
        site_location_context_strength: "strong",
        site_primary_location: "Serving area around ZIP code 80538",
        site_primary_business_zip: "80538",
      }),
    );

    render(<SiteWorkspacePage />);

    await screen.findByRole("heading", { name: "AI Narrative Overlay" });
    expect(screen.queryByTestId("zip-capture-modal")).not.toBeInTheDocument();
  });

  it("saves ZIP from modal via site update endpoint and dismisses the prompt", async () => {
    seedRichWorkspaceData();
    mockFetchRecommendationWorkspaceSummary.mockResolvedValue(
      buildRecommendationWorkspaceSummary({
        site_location_context: "Location not yet established from available business/site data.",
        site_location_context_strength: "weak",
        site_primary_location: null,
        site_primary_business_zip: null,
      }),
    );
    const user = userEvent.setup();
    render(<SiteWorkspacePage />);

    const modal = await screen.findByTestId("zip-capture-modal");
    const zipInput = within(modal).getByPlaceholderText("80538");
    await user.type(zipInput, "80538");
    await user.click(within(modal).getByRole("button", { name: "Save" }));

    await waitFor(() => {
      expect(mockUpdateSite).toHaveBeenCalledWith(
        "token-1",
        "biz-1",
        "site-1",
        { primary_business_zip: "80538" },
      );
    });
    await waitFor(() => {
      expect(screen.queryByTestId("zip-capture-modal")).not.toBeInTheDocument();
    });
  });

  it("hides ZIP capture modal for the current session when skipped", async () => {
    seedRichWorkspaceData();
    mockFetchRecommendationWorkspaceSummary.mockResolvedValue(
      buildRecommendationWorkspaceSummary({
        site_location_context: "Location not yet established from available business/site data.",
        site_location_context_strength: "weak",
        site_primary_location: null,
        site_primary_business_zip: null,
      }),
    );
    const user = userEvent.setup();
    render(<SiteWorkspacePage />);

    const modal = await screen.findByTestId("zip-capture-modal");
    await user.click(within(modal).getByRole("button", { name: "Skip for now" }));

    await waitFor(() => {
      expect(screen.queryByTestId("zip-capture-modal")).not.toBeInTheDocument();
    });
  });

  it("renders competitor and recommendation prompt preview panels when prompt metadata is available", async () => {
    seedRichWorkspaceData();
    const user = userEvent.setup();
    mockFetchRecommendationWorkspaceSummary.mockResolvedValue(
      buildRecommendationWorkspaceSummary({
        competitor_prompt_preview: buildAIPromptPreview({
          prompt_type: "competitor",
          system_prompt: "COMPETITOR_SYSTEM",
          user_prompt: "COMPETITOR_USER",
          model: "gpt-4o-mini",
          prompt_version: "seo-competitor-profile-v1",
        }),
        recommendation_prompt_preview: buildAIPromptPreview({
          prompt_type: "recommendation",
          system_prompt: "NARRATIVE_SYSTEM",
          user_prompt: "NARRATIVE_USER",
          model: "gpt-4o-mini",
          prompt_version: "seo-recommendation-narrative-v2",
        }),
      }),
    );

    render(<SiteWorkspacePage />);

    const competitorPanel = await screen.findByTestId("competitor-prompt-preview");
    expect(within(competitorPanel).getByText("View AI prompt")).toBeInTheDocument();
    const recommendationPanel = await screen.findByTestId("recommendation-prompt-preview");
    await user.click(within(recommendationPanel).getByText("View AI prompt"));
    expect(within(recommendationPanel).getByText("System prompt")).toBeInTheDocument();
    expect(within(recommendationPanel).getByText("NARRATIVE_SYSTEM")).toBeInTheDocument();
    expect(within(recommendationPanel).getByText("NARRATIVE_USER")).toBeInTheDocument();
  });

  it("hides prompt preview panels when workspace summary has no prompt metadata", async () => {
    seedRichWorkspaceData();
    mockFetchRecommendationWorkspaceSummary.mockResolvedValue(
      buildRecommendationWorkspaceSummary({
        competitor_prompt_preview: null,
        recommendation_prompt_preview: null,
      }),
    );

    render(<SiteWorkspacePage />);

    await screen.findByRole("heading", { name: "AI Competitor Profiles" });
    expect(screen.queryByTestId("competitor-prompt-preview")).not.toBeInTheDocument();
    expect(screen.queryByTestId("recommendation-prompt-preview")).not.toBeInTheDocument();
  });

  it("supports prompt copy and download actions with safe export text", async () => {
    seedRichWorkspaceData();
    const user = userEvent.setup();
    mockFetchRecommendationWorkspaceSummary.mockResolvedValue(
      buildRecommendationWorkspaceSummary({
        recommendation_prompt_preview: buildAIPromptPreview({
          prompt_type: "recommendation",
          system_prompt: "REC_SYSTEM",
          user_prompt: "REC_USER",
        }),
      }),
    );
    const writeText = jest.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      configurable: true,
    });
    const originalCreateObjectURL = URL.createObjectURL;
    const originalRevokeObjectURL = URL.revokeObjectURL;
    const createObjectURLMock = jest.fn(() => "blob:recommendation-prompt");
    const revokeObjectURLMock = jest.fn();
    Object.defineProperty(URL, "createObjectURL", {
      value: createObjectURLMock,
      configurable: true,
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      value: revokeObjectURLMock,
      configurable: true,
    });
    const anchorClickSpy = jest.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);

    render(<SiteWorkspacePage />);

    const recommendationPanel = await screen.findByTestId("recommendation-prompt-preview");
    await user.click(within(recommendationPanel).getByText("View AI prompt"));
    await user.click(within(recommendationPanel).getByRole("button", { name: "Copy Prompt" }));
    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));
    expect(writeText.mock.calls[0][0]).toContain("Prompt Type: Recommendation Narrative");
    expect(writeText.mock.calls[0][0]).toContain("System Prompt:");
    expect(writeText.mock.calls[0][0]).toContain("REC_SYSTEM");
    expect(writeText.mock.calls[0][0]).toContain("User Prompt:");
    expect(writeText.mock.calls[0][0]).toContain("REC_USER");
    expect(within(recommendationPanel).getByText("Prompt copied.")).toBeInTheDocument();

    await user.click(within(recommendationPanel).getByRole("button", { name: "Download Prompt (.txt)" }));
    expect(createObjectURLMock).toHaveBeenCalledTimes(1);
    expect(anchorClickSpy).toHaveBeenCalledTimes(1);
    expect(revokeObjectURLMock).toHaveBeenCalledWith("blob:recommendation-prompt");

    anchorClickSpy.mockRestore();
    Object.defineProperty(URL, "createObjectURL", {
      value: originalCreateObjectURL,
      configurable: true,
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      value: originalRevokeObjectURL,
      configurable: true,
    });
  });

  it("renders ai opportunities only when ai-backed recommendation signals are present", async () => {
    seedRichWorkspaceData();
    mockFetchRecommendationWorkspaceSummary.mockResolvedValue({
      business_id: "biz-1",
      site_id: "site-1",
      state: "completed_no_narrative",
      latest_run: {
        id: "run-1",
        business_id: "biz-1",
        site_id: "site-1",
        audit_run_id: "audit-1",
        comparison_run_id: "comparison-1",
        status: "completed",
        total_recommendations: 1,
        critical_recommendations: 0,
        warning_recommendations: 1,
        info_recommendations: 0,
        category_counts_json: {},
        effort_bucket_counts_json: {},
        started_at: "2026-03-21T00:29:00Z",
        completed_at: "2026-03-21T00:30:00Z",
        duration_ms: 60000,
        error_summary: null,
        created_by_principal_id: "principal-1",
        created_at: "2026-03-21T00:29:00Z",
        updated_at: "2026-03-21T00:30:00Z",
      },
      latest_completed_run: {
        id: "run-1",
        business_id: "biz-1",
        site_id: "site-1",
        audit_run_id: "audit-1",
        comparison_run_id: "comparison-1",
        status: "completed",
        total_recommendations: 1,
        critical_recommendations: 0,
        warning_recommendations: 1,
        info_recommendations: 0,
        category_counts_json: {},
        effort_bucket_counts_json: {},
        started_at: "2026-03-21T00:29:00Z",
        completed_at: "2026-03-21T00:30:00Z",
        duration_ms: 60000,
        error_summary: null,
        created_by_principal_id: "principal-1",
        created_at: "2026-03-21T00:29:00Z",
        updated_at: "2026-03-21T00:30:00Z",
      },
      recommendations: { items: [buildRecommendation()], total: 1 },
      latest_narrative: null,
      tuning_suggestions: [],
    });

    render(<SiteWorkspacePage />);

    await screen.findByRole("heading", { name: "Latest Completed Run" });
    expect(screen.queryByRole("heading", { name: "AI Opportunities" })).not.toBeInTheDocument();
    expect(screen.queryByText("AI Suggested")).not.toBeInTheDocument();
  });

  it("renders ai opportunities with view-more and expand-collapse details", async () => {
    seedRichWorkspaceData();
    const user = userEvent.setup();
    mockFetchRecommendationWorkspaceSummary.mockResolvedValue({
      business_id: "biz-1",
      site_id: "site-1",
      state: "completed_with_narrative",
      latest_run: {
        id: "run-1",
        business_id: "biz-1",
        site_id: "site-1",
        audit_run_id: "audit-1",
        comparison_run_id: "comparison-1",
        status: "completed",
        total_recommendations: 4,
        critical_recommendations: 1,
        warning_recommendations: 2,
        info_recommendations: 1,
        category_counts_json: {},
        effort_bucket_counts_json: {},
        started_at: "2026-03-21T00:29:00Z",
        completed_at: "2026-03-21T00:30:00Z",
        duration_ms: 60000,
        error_summary: null,
        created_by_principal_id: "principal-1",
        created_at: "2026-03-21T00:29:00Z",
        updated_at: "2026-03-21T00:30:00Z",
      },
      latest_completed_run: {
        id: "run-1",
        business_id: "biz-1",
        site_id: "site-1",
        audit_run_id: "audit-1",
        comparison_run_id: "comparison-1",
        status: "completed",
        total_recommendations: 4,
        critical_recommendations: 1,
        warning_recommendations: 2,
        info_recommendations: 1,
        category_counts_json: {},
        effort_bucket_counts_json: {},
        started_at: "2026-03-21T00:29:00Z",
        completed_at: "2026-03-21T00:30:00Z",
        duration_ms: 60000,
        error_summary: null,
        created_by_principal_id: "principal-1",
        created_at: "2026-03-21T00:29:00Z",
        updated_at: "2026-03-21T00:30:00Z",
      },
      recommendations: {
        items: [
          buildRecommendation({ id: "rec-1", title: "Fix title tags", priority_score: 90 }),
          buildRecommendation({ id: "rec-2", title: "Improve heading structure", priority_score: 75 }),
          buildRecommendation({ id: "rec-3", title: "Strengthen internal links", priority_score: 70 }),
          buildRecommendation({ id: "rec-4", title: "Update service-area pages", priority_score: 65 }),
        ],
        total: 4,
      },
      latest_narrative: {
        id: "narrative-1",
        business_id: "biz-1",
        site_id: "site-1",
        recommendation_run_id: "run-1",
        version: 2,
        status: "completed",
        narrative_text:
          "AI narrative summary: title and heading updates are expected to improve ranking stability and click-through.",
        top_themes_json: ["titles", "headings"],
        sections_json: { summary: "AI summary for this run." },
        provider_name: "provider",
        model_name: "model",
        prompt_version: "v2",
        error_message: null,
        created_by_principal_id: "principal-1",
        created_at: "2026-03-21T00:33:00Z",
        updated_at: "2026-03-21T00:33:00Z",
      },
      tuning_suggestions: [
        {
          setting: "competitor_candidate_min_relevance_score",
          current_value: 35,
          recommended_value: 30,
          reason:
            "High low_relevance exclusions indicate threshold is too strict and is likely suppressing valid local competitors.",
          linked_recommendation_ids: ["rec-1", "rec-2"],
          confidence: "high",
        },
      ],
    });

    render(<SiteWorkspacePage />);

    const aiOpportunitiesSection = await screen.findByTestId("ai-opportunities-section");
    expect(screen.getByRole("heading", { name: "AI Opportunities" })).toBeInTheDocument();
    expect(
      screen.getByText("AI suggestions are advisory and should be reviewed."),
    ).toBeInTheDocument();
    expect(within(aiOpportunitiesSection).getAllByTestId("ai-opportunity-card")).toHaveLength(3);
    expect(screen.getAllByText("AI Suggested")).toHaveLength(3);
    await user.click(screen.getByRole("button", { name: "View more AI opportunities (1 more)" }));
    expect(within(aiOpportunitiesSection).getAllByTestId("ai-opportunity-card")).toHaveLength(4);
    await user.click(within(aiOpportunitiesSection).getAllByRole("button", { name: "View details" })[0]);
    expect(within(aiOpportunitiesSection).getByText("Supporting signals")).toBeInTheDocument();
    expect(within(aiOpportunitiesSection).getByText(/Related context: titles, headings/)).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Deterministic Recommendations" })).toBeInTheDocument();
  });

  it("bridges ai opportunities to linked tuning suggestions with temporary highlight", async () => {
    jest.useFakeTimers();
    const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime });
    seedRichWorkspaceData();
    mockFetchRecommendationWorkspaceSummary.mockResolvedValue({
      business_id: "biz-1",
      site_id: "site-1",
      state: "completed_with_narrative",
      latest_run: {
        id: "run-1",
        business_id: "biz-1",
        site_id: "site-1",
        audit_run_id: "audit-1",
        comparison_run_id: "comparison-1",
        status: "completed",
        total_recommendations: 1,
        critical_recommendations: 0,
        warning_recommendations: 1,
        info_recommendations: 0,
        category_counts_json: {},
        effort_bucket_counts_json: {},
        started_at: "2026-03-21T00:29:00Z",
        completed_at: "2026-03-21T00:30:00Z",
        duration_ms: 60000,
        error_summary: null,
        created_by_principal_id: "principal-1",
        created_at: "2026-03-21T00:29:00Z",
        updated_at: "2026-03-21T00:30:00Z",
      },
      latest_completed_run: {
        id: "run-1",
        business_id: "biz-1",
        site_id: "site-1",
        audit_run_id: "audit-1",
        comparison_run_id: "comparison-1",
        status: "completed",
        total_recommendations: 1,
        critical_recommendations: 0,
        warning_recommendations: 1,
        info_recommendations: 0,
        category_counts_json: {},
        effort_bucket_counts_json: {},
        started_at: "2026-03-21T00:29:00Z",
        completed_at: "2026-03-21T00:30:00Z",
        duration_ms: 60000,
        error_summary: null,
        created_by_principal_id: "principal-1",
        created_at: "2026-03-21T00:29:00Z",
        updated_at: "2026-03-21T00:30:00Z",
      },
      recommendations: {
        items: [buildRecommendation({ id: "rec-1", title: "Fix title tags" })],
        total: 1,
      },
      latest_narrative: {
        id: "narrative-1",
        business_id: "biz-1",
        site_id: "site-1",
        recommendation_run_id: "run-1",
        version: 2,
        status: "completed",
        narrative_text: "Narrative for run 1.",
        top_themes_json: ["titles"],
        sections_json: { summary: "AI summary." },
        provider_name: "provider",
        model_name: "model",
        prompt_version: "v2",
        error_message: null,
        created_by_principal_id: "principal-1",
        created_at: "2026-03-21T00:33:00Z",
        updated_at: "2026-03-21T00:33:00Z",
      },
      tuning_suggestions: [
        {
          setting: "competitor_candidate_min_relevance_score",
          current_value: 35,
          recommended_value: 30,
          reason: "High low_relevance exclusions indicate threshold is too strict.",
          linked_recommendation_ids: ["rec-1"],
          confidence: "medium",
        },
      ],
    });

    render(<SiteWorkspacePage />);

    const aiSection = await screen.findByTestId("ai-opportunities-section");
    expect(within(aiSection).getByText("Backed by tuning suggestion")).toBeInTheDocument();
    await user.click(within(aiSection).getByRole("button", { name: "View Recommended Action" }));
    const tuningCard = await screen.findByTestId("tuning-suggestion-card");
    expect(tuningCard).toHaveClass("start-here-target-active");
    act(() => {
      jest.advanceTimersByTime(2000);
    });
    expect(tuningCard).not.toHaveClass("start-here-target-active");
    jest.useRealTimers();
  });

  it("shows ai opportunity preview bridge and no-preview fallback safely", async () => {
    seedRichWorkspaceData();
    const user = userEvent.setup();
    mockFetchRecommendationWorkspaceSummary.mockResolvedValue({
      business_id: "biz-1",
      site_id: "site-1",
      state: "completed_with_narrative",
      latest_run: {
        id: "run-1",
        business_id: "biz-1",
        site_id: "site-1",
        audit_run_id: "audit-1",
        comparison_run_id: "comparison-1",
        status: "completed",
        total_recommendations: 2,
        critical_recommendations: 0,
        warning_recommendations: 2,
        info_recommendations: 0,
        category_counts_json: {},
        effort_bucket_counts_json: {},
        started_at: "2026-03-21T00:29:00Z",
        completed_at: "2026-03-21T00:30:00Z",
        duration_ms: 60000,
        error_summary: null,
        created_by_principal_id: "principal-1",
        created_at: "2026-03-21T00:29:00Z",
        updated_at: "2026-03-21T00:30:00Z",
      },
      latest_completed_run: {
        id: "run-1",
        business_id: "biz-1",
        site_id: "site-1",
        audit_run_id: "audit-1",
        comparison_run_id: "comparison-1",
        status: "completed",
        total_recommendations: 2,
        critical_recommendations: 0,
        warning_recommendations: 2,
        info_recommendations: 0,
        category_counts_json: {},
        effort_bucket_counts_json: {},
        started_at: "2026-03-21T00:29:00Z",
        completed_at: "2026-03-21T00:30:00Z",
        duration_ms: 60000,
        error_summary: null,
        created_by_principal_id: "principal-1",
        created_at: "2026-03-21T00:29:00Z",
        updated_at: "2026-03-21T00:30:00Z",
      },
      recommendations: {
        items: [
          buildRecommendation({ id: "rec-1", title: "Fix title tags" }),
          buildRecommendation({ id: "rec-2", title: "Improve category coverage", priority_score: 70 }),
        ],
        total: 2,
      },
      latest_narrative: {
        id: "narrative-1",
        business_id: "biz-1",
        site_id: "site-1",
        recommendation_run_id: "run-1",
        version: 2,
        status: "completed",
        narrative_text: "Narrative for run 1.",
        top_themes_json: ["titles"],
        sections_json: { summary: "AI summary." },
        provider_name: "provider",
        model_name: "model",
        prompt_version: "v2",
        error_message: null,
        created_by_principal_id: "principal-1",
        created_at: "2026-03-21T00:33:00Z",
        updated_at: "2026-03-21T00:33:00Z",
      },
      tuning_suggestions: [
        {
          setting: "competitor_candidate_min_relevance_score",
          current_value: 35,
          recommended_value: 30,
          reason: "Low relevance exclusions are high.",
          linked_recommendation_ids: ["rec-1"],
          confidence: "medium",
        },
      ],
    });
    mockPreviewRecommendationTuningImpact.mockResolvedValue({
      business_id: "biz-1",
      site_id: "site-1",
      preview_event_id: "preview-event-2",
      source_recommendation_run_id: "run-1",
      source_narrative_id: "narrative-1",
      current_values: {
        competitor_candidate_min_relevance_score: 35,
        competitor_candidate_big_box_penalty: 20,
        competitor_candidate_directory_penalty: 35,
        competitor_candidate_local_alignment_bonus: 10,
      },
      proposed_values: {
        competitor_candidate_min_relevance_score: 30,
        competitor_candidate_big_box_penalty: 20,
        competitor_candidate_directory_penalty: 35,
        competitor_candidate_local_alignment_bonus: 10,
      },
      telemetry_window: {
        lookback_days: 30,
        total_runs: 0,
        total_raw_candidate_count: 0,
        total_included_candidate_count: 0,
        total_excluded_candidate_count: 0,
        exclusion_counts_by_reason: {
          duplicate: 0,
          low_relevance: 0,
          directory_or_aggregator: 0,
          big_box_mismatch: 0,
          existing_domain_match: 0,
          invalid_candidate: 0,
        },
      },
      estimated_impact: {
        insufficient_data: false,
        estimated_included_candidate_delta: 2,
        estimated_excluded_candidate_delta: -2,
        estimated_exclusion_reason_deltas: {
          duplicate: 0,
          low_relevance: -2,
          directory_or_aggregator: 0,
          big_box_mismatch: 0,
          existing_domain_match: 0,
          invalid_candidate: 0,
        },
        summary: "Estimated increase of 2 included candidates over the last 30 days of telemetry.",
        risk_flags: [],
      },
      caveat: "Preview only.",
    });

    render(<SiteWorkspacePage />);

    const aiSection = await screen.findByTestId("ai-opportunities-section");
    expect(within(aiSection).getByText("Impact will be reflected in next run.")).toBeInTheDocument();
    await user.click(screen.getAllByRole("button", { name: "Preview Impact" })[0]);
    await screen.findAllByText("Estimated increase of 2 included candidates over the last 30 days of telemetry.");
    expect(within(aiSection).getByText("Expected impact (from preview):")).toBeInTheDocument();
    expect(within(aiSection).getByText("View Preview")).toBeInTheDocument();
  });

  it("tracks recent change attribution when apply follows ai recommendation bridge", async () => {
    seedRichWorkspaceData();
    const user = userEvent.setup();
    jest.spyOn(window, "confirm").mockReturnValue(true);
    mockFetchBusinessSettings.mockResolvedValue(buildBusinessSettings({ competitor_candidate_min_relevance_score: 35 }));
    const summaryPayload: RecommendationWorkspaceSummaryResponse = {
      business_id: "biz-1",
      site_id: "site-1",
      state: "completed_with_narrative",
      latest_run: {
        id: "run-1",
        business_id: "biz-1",
        site_id: "site-1",
        audit_run_id: "audit-1",
        comparison_run_id: "comparison-1",
        status: "completed",
        total_recommendations: 1,
        critical_recommendations: 0,
        warning_recommendations: 1,
        info_recommendations: 0,
        category_counts_json: {},
        effort_bucket_counts_json: {},
        started_at: "2026-03-21T00:29:00Z",
        completed_at: "2026-03-21T00:30:00Z",
        duration_ms: 60000,
        error_summary: null,
        created_by_principal_id: "principal-1",
        created_at: "2026-03-21T00:29:00Z",
        updated_at: "2026-03-21T00:30:00Z",
      },
      latest_completed_run: {
        id: "run-1",
        business_id: "biz-1",
        site_id: "site-1",
        audit_run_id: "audit-1",
        comparison_run_id: "comparison-1",
        status: "completed",
        total_recommendations: 1,
        critical_recommendations: 0,
        warning_recommendations: 1,
        info_recommendations: 0,
        category_counts_json: {},
        effort_bucket_counts_json: {},
        started_at: "2026-03-21T00:29:00Z",
        completed_at: "2026-03-21T00:30:00Z",
        duration_ms: 60000,
        error_summary: null,
        created_by_principal_id: "principal-1",
        created_at: "2026-03-21T00:29:00Z",
        updated_at: "2026-03-21T00:30:00Z",
      },
      recommendations: { items: [buildRecommendation({ id: "rec-1", title: "Fix title tags" })], total: 1 },
      latest_narrative: {
        id: "narrative-1",
        business_id: "biz-1",
        site_id: "site-1",
        recommendation_run_id: "run-1",
        version: 2,
        status: "completed",
        narrative_text: "Narrative for run 1.",
        top_themes_json: ["titles"],
        sections_json: { summary: "AI summary." },
        provider_name: "provider",
        model_name: "model",
        prompt_version: "v2",
        error_message: null,
        created_by_principal_id: "principal-1",
        created_at: "2026-03-21T00:33:00Z",
        updated_at: "2026-03-21T00:33:00Z",
      },
      tuning_suggestions: [
        {
          setting: "competitor_candidate_min_relevance_score",
          current_value: 35,
          recommended_value: 30,
          reason: "Low relevance exclusions are high.",
          linked_recommendation_ids: ["rec-1"],
          confidence: "medium",
        },
      ],
    };
    mockFetchRecommendationWorkspaceSummary.mockResolvedValue(summaryPayload);
    mockUpdateBusinessSettings.mockResolvedValue(
      buildBusinessSettings({ competitor_candidate_min_relevance_score: 30 }),
    );

    render(<SiteWorkspacePage />);

    const aiSection = await screen.findByTestId("ai-opportunities-section");
    await user.click(within(aiSection).getByRole("button", { name: "View Recommended Action" }));
    await user.click(screen.getByRole("button", { name: "Apply Suggestion" }));

    const recentChangesPanel = await screen.findByTestId("recent-changes-panel");
    expect(within(recentChangesPanel).getByText("From AI Recommendation")).toBeInTheDocument();
    expect(within(recentChangesPanel).getByText("Fix title tags")).toBeInTheDocument();
  });

  it("shows safe in-progress state when no completed recommendation run exists yet", async () => {
    seedRichWorkspaceData();
    mockFetchRecommendationWorkspaceSummary.mockResolvedValue({
      business_id: "biz-1",
      site_id: "site-1",
      state: "no_completed_runs",
      latest_run: {
        id: "run-open-1",
        business_id: "biz-1",
        site_id: "site-1",
        audit_run_id: "audit-1",
        comparison_run_id: "comparison-1",
        status: "running",
        total_recommendations: 0,
        critical_recommendations: 0,
        warning_recommendations: 0,
        info_recommendations: 0,
        category_counts_json: {},
        effort_bucket_counts_json: {},
        started_at: "2026-03-21T00:29:00Z",
        completed_at: null,
        duration_ms: null,
        error_summary: null,
        created_by_principal_id: "principal-1",
        created_at: "2026-03-21T00:29:00Z",
        updated_at: "2026-03-21T00:30:00Z",
      },
      latest_completed_run: null,
      recommendations: { items: [], total: 0 },
      latest_narrative: null,
      tuning_suggestions: [],
    });
    render(<SiteWorkspacePage />);

    await screen.findByRole("heading", { name: "Latest Completed Run" });
    await screen.findByText("No immediate action available");
    expect(
      screen.getByText("Run analysis to generate recommendations and tuning guidance."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Why this first: no completed recommendation run or tuning suggestion is available yet."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Focus Recommendation|Preview and Focus|Focus Tuning Suggestion/i })).not.toBeInTheDocument();
    await screen.findByText(/No completed recommendation run is available yet\./);
    expect(mockFetchRecommendationWorkspaceSummary).toHaveBeenCalledWith("token-1", "biz-1", "site-1");
  });

  it("renders safe latest-run narrative missing state", async () => {
    seedRichWorkspaceData();
    mockFetchRecommendationWorkspaceSummary.mockResolvedValue({
      business_id: "biz-1",
      site_id: "site-1",
      state: "completed_no_narrative",
      latest_run: {
        id: "run-1",
        business_id: "biz-1",
        site_id: "site-1",
        audit_run_id: "audit-1",
        comparison_run_id: "comparison-1",
        status: "completed",
        total_recommendations: 4,
        critical_recommendations: 1,
        warning_recommendations: 2,
        info_recommendations: 1,
        category_counts_json: {},
        effort_bucket_counts_json: {},
        started_at: "2026-03-21T00:29:00Z",
        completed_at: "2026-03-21T00:30:00Z",
        duration_ms: 60000,
        error_summary: null,
        created_by_principal_id: "principal-1",
        created_at: "2026-03-21T00:29:00Z",
        updated_at: "2026-03-21T00:30:00Z",
      },
      latest_completed_run: {
        id: "run-1",
        business_id: "biz-1",
        site_id: "site-1",
        audit_run_id: "audit-1",
        comparison_run_id: "comparison-1",
        status: "completed",
        total_recommendations: 4,
        critical_recommendations: 1,
        warning_recommendations: 2,
        info_recommendations: 1,
        category_counts_json: {},
        effort_bucket_counts_json: {},
        started_at: "2026-03-21T00:29:00Z",
        completed_at: "2026-03-21T00:30:00Z",
        duration_ms: 60000,
        error_summary: null,
        created_by_principal_id: "principal-1",
        created_at: "2026-03-21T00:29:00Z",
        updated_at: "2026-03-21T00:30:00Z",
      },
      recommendations: { items: [], total: 0 },
      latest_narrative: null,
      tuning_suggestions: [],
    });
    render(<SiteWorkspacePage />);

    await screen.findByRole("heading", { name: "Latest Completed Run" });
    await screen.findByText("No narrative has been generated for the latest completed recommendation run yet.");
  });

  it("renders safe latest-run workspace summary load failures", async () => {
    seedRichWorkspaceData();
    mockFetchRecommendationWorkspaceSummary.mockRejectedValueOnce(new Error("failed workspace summary"));
    render(<SiteWorkspacePage />);

    await screen.findByRole("heading", { name: "Latest Completed Run" });
    await screen.findByText("Unable to load recommendation workspace summary right now. Please try again.");
  });

  it("keeps loading and warning timeline regression behavior", async () => {
    mockUseOperatorContext.mockReturnValue(baseContext({ loading: true }));
    const { rerender } = render(<SiteWorkspacePage />);
    expect(screen.getByText("Loading site workspace...")).toBeInTheDocument();

    mockUseOperatorContext.mockReturnValue(baseContext());
    seedRichWorkspaceData();
    mockFetchCompetitorDomains.mockRejectedValueOnce(new Error("domain fetch failed"));
    rerender(<SiteWorkspacePage />);

    await screen.findByRole("heading", { name: "Site Activity Timeline" });
    await screen.findByText("Some activity data could not be loaded. Available events are still shown.");
    expect(screen.getAllByTestId("site-activity-row").length).toBeGreaterThan(0);
  });

  it("shows safe empty timeline state when no site activity exists", async () => {
    mockFetchAuditRuns.mockResolvedValue({ items: [], total: 0 });
    mockFetchCompetitorSets.mockResolvedValue({ items: [], total: 0 });
    mockFetchSiteCompetitorComparisonRuns.mockResolvedValue({ items: [], total: 0 });
    mockFetchRecommendations.mockResolvedValue({
      items: [],
      total: 0,
      filtered_summary: {
        total: 0,
        open: 0,
        accepted: 0,
        dismissed: 0,
        high_priority: 0,
      },
    });
    mockFetchRecommendationRuns.mockResolvedValue({ items: [], total: 0 });

    render(<SiteWorkspacePage />);

    await screen.findByRole("heading", { name: "Site Activity Timeline" });
    await screen.findByText("No recent site activity events are available for this site yet.");
    expect(screen.queryAllByTestId("site-activity-row")).toHaveLength(0);
  });

  it("shows safe not-found state for inaccessible site ids", async () => {
    navigationState.params = { site_id: "site-missing" };

    render(<SiteWorkspacePage />);

    await screen.findByText("This site was not found or is not accessible in your tenant scope.");
    expect(mockFetchAuditRuns).not.toHaveBeenCalled();
  });
});

describe("site workspace ai competitor profile drafts", () => {
  it("renders generate control and latest draft review table", async () => {
    seedCompetitorProfileGenerationWorkspaceData();
    render(<SiteWorkspacePage />);

    await screen.findByRole("heading", { name: "AI Competitor Profiles" });
    expect(screen.getByRole("button", { name: "Generate Competitor Profiles" })).toBeInTheDocument();
    expect(await screen.findByText(/Latest Run:/i)).toBeInTheDocument();
    const metadataLine = screen.getByText((_, element) => {
      if (!element || element.tagName.toLowerCase() !== "p") {
        return false;
      }
      const text = element.textContent || "";
      return (
        text.includes("Provider:") &&
        text.includes("Model:") &&
        text.includes("Prompt:")
      );
    });
    expect(metadataLine).toHaveTextContent(/Provider:\s*mock/);
    expect(metadataLine).toHaveTextContent(/Model:\s*mock-seo-competitor-profile-v1/);
    expect(metadataLine).toHaveTextContent(/Prompt:\s*seo-competitor-profile-v1/);
    expect(screen.getByText(/Last 30d: queued 0 \| running 0 \| completed 1 \| failed 0/)).toBeInTheDocument();
    expect(screen.getByText(/Candidate telemetry \(1 runs\): raw 2 \| included 2 \| excluded 0/)).toBeInTheDocument();
    expect(screen.queryByText(/Exclusion reasons:/i)).not.toBeInTheDocument();
    expect(screen.queryByTestId("rejected-competitor-candidates-debug")).not.toBeInTheDocument();
    expect(screen.queryByTestId("tuning-rejected-competitor-candidates-debug")).not.toBeInTheDocument();
    expect(screen.queryByTestId("competitor-candidate-pipeline-summary-debug")).not.toBeInTheDocument();
    expect(screen.getAllByTestId("competitor-profile-draft-row")).toHaveLength(2);
    expect(mockFetchCompetitorProfileGenerationRuns).toHaveBeenCalled();
    expect(mockFetchCompetitorProfileGenerationRunDetail).toHaveBeenCalled();
    expect(mockFetchCompetitorProfileGenerationSummary).toHaveBeenCalled();
  });

  it("renders non-zero exclusion reason aggregates in summary", async () => {
    seedCompetitorProfileGenerationWorkspaceData();
    mockFetchCompetitorProfileGenerationSummary.mockResolvedValue({
      business_id: "biz-1",
      site_id: "site-1",
      lookback_days: 30,
      window_start: "2026-02-20T00:00:00Z",
      window_end: "2026-03-21T00:00:00Z",
      queued_count: 0,
      running_count: 0,
      completed_count: 2,
      failed_count: 1,
      retry_child_runs: 0,
      retried_parent_runs: 0,
      failed_runs_retried: 0,
      failure_category_counts: {},
      total_runs: 3,
      total_raw_candidate_count: 8,
      total_included_candidate_count: 2,
      total_excluded_candidate_count: 6,
      preview_accuracy_rate: 0.8,
      avg_error_margin: 1.2,
      last_n_preview_accuracy: {
        window_size: 10,
        sample_size: 5,
        direction_correct_count: 4,
        accuracy_rate: 0.8,
        avg_error_margin: 1.2,
      },
      exclusion_counts_by_reason: {
        duplicate: 1,
        low_relevance: 2,
        directory_or_aggregator: 2,
        big_box_mismatch: 1,
        existing_domain_match: 0,
        invalid_candidate: 0,
      },
      latest_run_created_at: "2026-03-21T00:59:00Z",
      latest_run_completed_at: "2026-03-21T01:00:00Z",
      latest_completed_run_completed_at: "2026-03-21T01:00:00Z",
      latest_failed_run_completed_at: null,
    });

    render(<SiteWorkspacePage />);

    await screen.findByRole("heading", { name: "AI Competitor Profiles" });
    expect(screen.getByText(/Candidate telemetry \(3 runs\): raw 8 \| included 2 \| excluded 6/)).toBeInTheDocument();
    expect(screen.getByText(/Preview accuracy \(last 5\): 80% directionally correct \| avg error margin 1.2/)).toBeInTheDocument();
    expect(screen.getByText(/Exclusion reasons:/i)).toHaveTextContent(
      "Exclusion reasons: big box mismatch=1, directory or aggregator=2, duplicate=1, low relevance=2",
    );
  });

  it("renders rejected competitor candidates debug details when run detail includes deterministic rejections", async () => {
    seedCompetitorProfileGenerationWorkspaceData();
    const run = buildCompetitorProfileGenerationRun({
      id: "gen-run-debug-rejections",
      status: "completed",
      generated_draft_count: 1,
    });
    mockFetchCompetitorProfileGenerationRuns.mockResolvedValue({
      items: [run],
      total: 1,
    });
    mockFetchCompetitorProfileGenerationRunDetail.mockResolvedValue({
      run,
      drafts: [
        {
          id: "draft-valid",
          business_id: "biz-1",
          site_id: "site-1",
          generation_run_id: run.id,
          suggested_name: "Valid Competitor",
          suggested_domain: "valid-competitor.example",
          competitor_type: "direct",
          summary: "Valid draft summary",
          why_competitor: "Valid rationale",
          evidence: "Valid evidence",
          confidence_score: 0.7,
          source: "ai_generated",
          review_status: "pending",
          edited_fields_json: null,
          review_notes: null,
          reviewed_by_principal_id: null,
          reviewed_at: null,
          accepted_competitor_set_id: null,
          accepted_competitor_domain_id: null,
          created_at: "2026-03-21T01:00:00Z",
          updated_at: "2026-03-21T01:00:00Z",
        },
      ],
      total_drafts: 1,
      rejected_candidate_count: 3,
      rejected_candidates: [
        {
          domain: "parked-candidate.com",
          reasons: ["parked_domain"],
          summary: "Unclear overlap.",
        },
        {
          domain: "out-of-market.example",
          reasons: ["out_of_market", "insufficient_overlap_evidence"],
          summary: "Appears to serve a different region.",
        },
      ],
      candidate_pipeline_summary: {
        proposed_candidate_count: 5,
        rejected_by_eligibility_count: 3,
        eligible_candidate_count: 2,
        rejected_by_tuning_count: 1,
        final_candidate_count: 1,
      },
      tuning_rejected_candidate_count: 3,
      tuning_rejected_candidates: [
        {
          domain: "directory.example",
          reasons: ["directory_or_aggregator_penalty"],
          final_score: 42,
          summary: "Directory-heavy listing site.",
        },
        {
          domain: "big-box.example",
          reasons: ["big_box_mismatch_penalty"],
          final_score: 39,
          summary: "National chain mismatch.",
        },
      ],
      tuning_rejection_reason_counts: {
        below_minimum_relevance_score: 1,
        directory_or_aggregator_penalty: 1,
        big_box_mismatch_penalty: 1,
        insufficient_local_alignment: 1,
      },
    });

    render(<SiteWorkspacePage />);

    const debugBlock = await screen.findByTestId("rejected-competitor-candidates-debug");
    expect(within(debugBlock).getByText(/Rejected competitor candidates \(debug\)/i)).toBeInTheDocument();
    expect(within(debugBlock).getByText(/: 3/)).toBeInTheDocument();
    expect(within(debugBlock).getByText("parked-candidate.com")).toBeInTheDocument();
    expect(within(debugBlock).getByText("parked domain")).toBeInTheDocument();
    expect(within(debugBlock).getByText("out of market")).toBeInTheDocument();
    expect(within(debugBlock).getByText("insufficient overlap evidence")).toBeInTheDocument();
    expect(
      within(debugBlock).getByText("Showing 2 of 3 rejected candidates."),
    ).toBeInTheDocument();
    const pipelineDebug = screen.getByTestId("competitor-candidate-pipeline-summary-debug");
    expect(within(pipelineDebug).getByText(/Candidate pipeline \(debug\)/i)).toBeInTheDocument();
    expect(within(pipelineDebug).getByText("Proposed: 5")).toBeInTheDocument();
    expect(within(pipelineDebug).getByText("Rejected by eligibility: 3")).toBeInTheDocument();
    expect(within(pipelineDebug).getByText("Eligible after filtering: 2")).toBeInTheDocument();
    expect(within(pipelineDebug).getByText("Removed by tuning: 1")).toBeInTheDocument();
    expect(within(pipelineDebug).getByText("Final returned: 1")).toBeInTheDocument();

    const tuningDebug = screen.getByTestId("tuning-rejected-competitor-candidates-debug");
    expect(within(tuningDebug).getByText(/Removed by tuning \(debug\)/i)).toBeInTheDocument();
    expect(within(tuningDebug).getByText(/: 3/)).toBeInTheDocument();
    expect(within(tuningDebug).getByText("directory.example")).toBeInTheDocument();
    expect(within(tuningDebug).getByText("directory or aggregator penalty")).toBeInTheDocument();
    expect(within(tuningDebug).getByText("big box mismatch penalty")).toBeInTheDocument();
    expect(within(tuningDebug).getByText("Showing 2 of 3 removed-by-tuning candidates.")).toBeInTheDocument();
  });

  it("triggers generation and refreshes visible drafts", async () => {
    seedCompetitorProfileGenerationWorkspaceData();
    const user = userEvent.setup();
    render(<SiteWorkspacePage />);

    await screen.findByRole("button", { name: "Generate Competitor Profiles" });
    await user.click(screen.getByRole("button", { name: "Generate Competitor Profiles" }));

    await screen.findByText("Competitor profile generation queued. Drafts will appear after the run completes.");
    expect(mockCreateCompetitorProfileGenerationRun).toHaveBeenCalledWith(
      "token-1",
      "biz-1",
      "site-1",
      { candidate_count: 5 },
    );
  });

  it("polls queued/running runs and renders drafts after completion", async () => {
    seedRichWorkspaceData();
    const runningRun = buildCompetitorProfileGenerationRun({
      id: "gen-run-async-1",
      status: "running",
      generated_draft_count: 0,
      completed_at: null,
      created_at: "2026-03-21T01:30:00Z",
      updated_at: "2026-03-21T01:30:00Z",
    });
    const completedRun = buildCompetitorProfileGenerationRun({
      ...runningRun,
      status: "completed",
      generated_draft_count: 1,
      completed_at: "2026-03-21T01:31:30Z",
      updated_at: "2026-03-21T01:31:30Z",
    });
    const completedDraft: CompetitorProfileDraft = {
      id: "draft-async-1",
      business_id: "biz-1",
      site_id: "site-1",
      generation_run_id: runningRun.id,
      suggested_name: "Async Competitor",
      suggested_domain: "async-competitor.example",
      competitor_type: "direct",
      summary: "Completed async summary",
      why_competitor: "Completed async rationale",
      evidence: "Completed async evidence",
      confidence_score: 0.74,
      source: "ai_generated",
      review_status: "pending",
      edited_fields_json: null,
      review_notes: null,
      reviewed_by_principal_id: null,
      reviewed_at: null,
      accepted_competitor_set_id: null,
      accepted_competitor_domain_id: null,
      created_at: "2026-03-21T01:31:30Z",
      updated_at: "2026-03-21T01:31:30Z",
    };

    mockFetchCompetitorProfileGenerationRuns
      .mockResolvedValueOnce({ items: [runningRun], total: 1 })
      .mockResolvedValueOnce({ items: [runningRun], total: 1 })
      .mockResolvedValue({ items: [completedRun], total: 1 });
    mockFetchCompetitorProfileGenerationRunDetail
      .mockResolvedValueOnce({
        run: runningRun,
        drafts: [],
        total_drafts: 0,
      })
      .mockResolvedValueOnce({
        run: runningRun,
        drafts: [],
        total_drafts: 0,
      })
      .mockResolvedValue({
        run: completedRun,
        drafts: [completedDraft],
        total_drafts: 1,
      });

    render(<SiteWorkspacePage />);

    await screen.findByText("Generation is in progress for this run.");
    await waitFor(
      () => {
        expect(mockFetchCompetitorProfileGenerationRuns.mock.calls.length).toBeGreaterThanOrEqual(3);
      },
      { timeout: 8000 },
    );
    await waitFor(
      () => {
        expect(screen.getAllByTestId("competitor-profile-draft-row")).toHaveLength(1);
      },
      { timeout: 8000 },
    );
    await waitFor(
      () => {
        expect(screen.queryByText("Generation is in progress for this run.")).not.toBeInTheDocument();
      },
      { timeout: 8000 },
    );
  });

  it("accept/reject/edit actions update draft states", async () => {
    seedCompetitorProfileGenerationWorkspaceData();
    const user = userEvent.setup();
    render(<SiteWorkspacePage />);

    await screen.findAllByTestId("competitor-profile-draft-row");

    await user.click(screen.getAllByRole("button", { name: "Edit" })[0]);
    const nameInput = screen.getByLabelText("Suggested Name");
    await user.clear(nameInput);
    await user.type(nameInput, "Edited Competitor Name");
    await user.click(screen.getByRole("button", { name: "Save Edits" }));
    await screen.findByText("Draft edits saved. Accept explicitly to create competitor records.");
    expect(mockEditCompetitorProfileDraft).toHaveBeenCalled();

    await user.click(screen.getAllByRole("button", { name: "Accept" })[0]);
    await screen.findByText("Draft accepted and added to competitors.");
    expect(mockAcceptCompetitorProfileDraft).toHaveBeenCalled();

    const rejectButtons = screen.getAllByRole("button", { name: "Reject" });
    const enabledRejectButton = rejectButtons.find((button) => !button.hasAttribute("disabled"));
    expect(enabledRejectButton).toBeDefined();
    await user.click(enabledRejectButton as HTMLButtonElement);
    await screen.findByText("Draft rejected. No competitor record was created.");
    expect(mockRejectCompetitorProfileDraft).toHaveBeenCalled();
  });

  it("renders safe failed-generation context", async () => {
    seedRichWorkspaceData();
    const failedRun = buildCompetitorProfileGenerationRun({
      id: "gen-run-failed",
      status: "failed",
      generated_draft_count: 0,
      failure_category: "provider_config",
      error_summary: "Competitor profile generation failed",
    });
    mockFetchCompetitorProfileGenerationRuns.mockResolvedValue({
      items: [failedRun],
      total: 1,
    });
    mockFetchCompetitorProfileGenerationRunDetail.mockResolvedValue({
      run: failedRun,
      drafts: [],
      total_drafts: 0,
    });

    render(<SiteWorkspacePage />);

    await screen.findByText("Competitor profile generation failed");
    expect(screen.getByText(/Failure Category:/i)).toHaveTextContent("provider config");
    expect(screen.getByText("This run did not produce any reviewable drafts.")).toBeInTheDocument();
  });

  it("shows retry action for failed generation runs", async () => {
    seedRichWorkspaceData();
    const failedRun = buildCompetitorProfileGenerationRun({
      id: "gen-run-failed",
      status: "failed",
      generated_draft_count: 0,
      failure_category: "provider_config",
      error_summary: "Competitor profile generation failed",
    });
    mockFetchCompetitorProfileGenerationRuns.mockResolvedValue({
      items: [failedRun],
      total: 1,
    });
    mockFetchCompetitorProfileGenerationRunDetail.mockResolvedValue({
      run: failedRun,
      drafts: [],
      total_drafts: 0,
    });

    render(<SiteWorkspacePage />);

    await screen.findByText("Competitor profile generation failed");
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });

  it("retries a failed generation run and promotes the new queued run", async () => {
    seedRichWorkspaceData();
    const user = userEvent.setup();
    const failedRun = buildCompetitorProfileGenerationRun({
      id: "gen-run-failed",
      status: "failed",
      generated_draft_count: 0,
      failure_category: "provider_config",
      error_summary: "Competitor profile generation failed",
    });
    const retriedRun = buildCompetitorProfileGenerationRun({
      ...failedRun,
      id: "gen-run-retry-1",
      parent_run_id: "gen-run-failed",
      status: "queued",
      error_summary: null,
      completed_at: null,
      created_at: "2026-03-21T01:02:00Z",
      updated_at: "2026-03-21T01:02:00Z",
    });
    mockFetchCompetitorProfileGenerationRuns
      .mockResolvedValueOnce({
        items: [failedRun],
        total: 1,
      })
      .mockResolvedValue({
        items: [retriedRun],
        total: 1,
      });
    mockFetchCompetitorProfileGenerationRunDetail
      .mockResolvedValueOnce({
        run: failedRun,
        drafts: [],
        total_drafts: 0,
      })
      .mockResolvedValue({
        run: retriedRun,
        drafts: [],
        total_drafts: 0,
      });
    mockRetryCompetitorProfileGenerationRun.mockResolvedValue({
      run: retriedRun,
      drafts: [],
      total_drafts: 0,
    });

    render(<SiteWorkspacePage />);

    await screen.findByRole("button", { name: "Retry" });
    await user.click(screen.getByRole("button", { name: "Retry" }));

    await screen.findByText("Retry queued. Drafts will appear after the run completes.");
    expect(mockRetryCompetitorProfileGenerationRun).toHaveBeenCalledWith(
      "token-1",
      "biz-1",
      "site-1",
      "gen-run-failed",
    );
    await waitFor(() => {
      expect(screen.getByText(/Latest Run:/i)).toHaveTextContent("gen-run-retry-1");
    });
    expect(screen.getByText(/Retry of run/i)).toHaveTextContent("gen-run-failed");
    expect(screen.getByText("Generation is in progress for this run.")).toBeInTheDocument();
  });

  it("renders safe retry error state when retry request fails", async () => {
    seedRichWorkspaceData();
    const user = userEvent.setup();
    const failedRun = buildCompetitorProfileGenerationRun({
      id: "gen-run-failed",
      status: "failed",
      generated_draft_count: 0,
      failure_category: "provider_config",
      error_summary: "Competitor profile generation failed",
    });
    mockFetchCompetitorProfileGenerationRuns.mockResolvedValue({
      items: [failedRun],
      total: 1,
    });
    mockFetchCompetitorProfileGenerationRunDetail.mockResolvedValue({
      run: failedRun,
      drafts: [],
      total_drafts: 0,
    });
    mockRetryCompetitorProfileGenerationRun.mockRejectedValue(
      new ApiRequestError("Retry is not allowed for this run", {
        status: 422,
        detail: null,
      }),
    );

    render(<SiteWorkspacePage />);

    await screen.findByRole("button", { name: "Retry" });
    await user.click(screen.getByRole("button", { name: "Retry" }));

    await screen.findByText("Retry is not allowed for this run");
    expect(screen.getByText(/Latest Run:/i)).toHaveTextContent("gen-run-failed");
  });
});
