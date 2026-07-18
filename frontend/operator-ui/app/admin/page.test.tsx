import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import AdminPage from "./page";
import UsersCompatibilityPage from "../users/page";

type OperatorContextMockValue = {
  loading: boolean;
  error: string | null;
  token: string;
  businessId: string;
  sites: Array<{
    id: string;
    business_id: string;
    display_name: string;
    base_url: string;
    normalized_domain: string;
    search_console_property_url?: string | null;
    search_console_enabled?: boolean;
    is_active: boolean;
    is_primary: boolean;
    last_audit_run_id: string | null;
    last_audit_status: string | null;
    last_audit_completed_at: string | null;
  }>;
  selectedSiteId: string | null;
  setSelectedSiteId: jest.Mock;
  refreshSites: jest.Mock;
};

const mockUseOperatorContext = jest.fn<OperatorContextMockValue, []>();
const mockUseAuth = jest.fn();
const mockFetchPrincipals = jest.fn();
const mockFetchPrincipalIdentities = jest.fn();
const mockFetchBusinessSettings = jest.fn();
const mockUpdateBusinessSettings = jest.fn();
const mockFetchGitHubPublishConfig = jest.fn();
const mockUpdateGitHubPublishConfig = jest.fn();
const mockPrepareAdminSiteDeletePlan = jest.fn();
const mockExecuteAdminSiteDelete = jest.fn();

const DEFAULT_MIGRATION_GENERATION_BUDGET = {
  migration_context_budget_chars: 90000,
  migration_recommendation_limit: 6,
  migration_competitor_limit: 8,
  migration_source_page_summary_limit: 8,
  migration_media_asset_limit: 16,
  migration_generated_page_limit: 20,
  migration_generated_file_limit: 16,
  migration_generation_depth: "standard",
  migration_variation_level: "balanced",
  migration_require_page_variety: true,
  migration_require_design_variation: true,
};

const DEFAULT_MIGRATION_GENERATION_SAFETY = {
  migration_provider_timeout_seconds: 300,
  migration_preflight_mode: "compact_fallback",
  migration_max_final_input_chars: 32000,
  migration_max_difficulty_score: 18,
  migration_compact_fallback_enabled: true,
  migration_compact_page_limit: 6,
  migration_compact_media_asset_limit: 5,
  migration_compact_recommendation_limit: 8,
};

const DEFAULT_AI_MODEL_SELECTABLE_VALUES = [
  { model: "gpt-5.6-luna", label: "GPT-5.6 Luna", capability_note: "Structured JSON helper and explainer tasks." },
  { model: "gpt-5.6-terra", label: "GPT-5.6 Terra", capability_note: "General generation, multimodal, and web-search tasks." },
  { model: "gpt-5.6", label: "GPT-5.6", capability_note: "High-cost full generation and code-output tasks." },
  { model: "omni-moderation", label: "Omni Moderation", capability_note: "Dedicated moderation tasks." },
  { model: "text-embedding-3-small", label: "Text Embedding 3 Small", capability_note: "Embedding and retrieval tasks." },
  { model: "deterministic", label: "Deterministic", capability_note: "No provider call; use deterministic/manual handling." },
];

function buildAiModelRouting({
  defaultAiModel = null,
  overrides = {},
}: {
  defaultAiModel?: string | null;
  overrides?: Record<string, string>;
} = {}) {
  return [
    {
      task_alias: "requirements_helper",
      task_label: "Requirements Helper",
      capability_note: "Structured JSON helper tasks.",
      capabilities: ["text", "structured_json"],
      override_model: overrides.requirements_helper || null,
      effective_model: overrides.requirements_helper || defaultAiModel || "gpt-5.6-terra",
      source: overrides.requirements_helper ? "task_override" : defaultAiModel ? "business_default" : "env_default",
      fallback_used: !overrides.requirements_helper && !defaultAiModel,
      validation_status: "allowed",
      validation_error: null,
    },
    {
      task_alias: "media_metadata_helper",
      task_label: "Media Metadata Helper",
      capability_note: "Multimodal + structured JSON image tasks.",
      capabilities: ["text", "structured_json", "multimodal"],
      override_model: overrides.media_metadata_helper || null,
      effective_model: overrides.media_metadata_helper || defaultAiModel || "gpt-5.6-terra",
      source: overrides.media_metadata_helper ? "task_override" : defaultAiModel ? "business_default" : "env_default",
      fallback_used: !overrides.media_metadata_helper && !defaultAiModel,
      validation_status: "allowed",
      validation_error: null,
    },
    {
      task_alias: "embeddings",
      task_label: "Embeddings",
      capability_note: "Embedding model or deterministic fallback.",
      capabilities: ["text", "embeddings"],
      override_model: overrides.embeddings || null,
      effective_model: overrides.embeddings || "deterministic",
      source: overrides.embeddings === "deterministic" ? "deterministic" : overrides.embeddings ? "task_override" : "deterministic",
      fallback_used: false,
      validation_status: overrides.embeddings === "deterministic" || !overrides.embeddings ? "deterministic" : "allowed",
      validation_error: null,
    },
  ];
}

function buildBusinessSettings(overrides: Record<string, unknown> = {}) {
  const defaultAiModel = (overrides.default_ai_model as string | null | undefined) ?? null;
  const aiModelOverrides = (overrides.ai_model_overrides as Record<string, string> | undefined) || {};
  return {
    id: "biz-1",
    name: "Biz",
    notification_phone: null,
    notification_email: null,
    sms_enabled: false,
    email_enabled: false,
    customer_auto_ack_enabled: false,
    contractor_alerts_enabled: false,
    seo_audit_crawl_max_pages: 200,
    competitor_candidate_min_relevance_score: 30,
    competitor_candidate_big_box_penalty: 20,
    competitor_candidate_directory_penalty: 20,
    competitor_candidate_local_alignment_bonus: 10,
    competitor_primary_timeout_seconds: null,
    competitor_degraded_timeout_seconds: null,
    migration_draft_timeout_seconds: null,
    ai_prompt_text_competitor: null,
    ai_prompt_text_recommendations: null,
    default_ai_model: defaultAiModel,
    ai_model_overrides: aiModelOverrides,
    ai_model_routing: buildAiModelRouting({ defaultAiModel, overrides: aiModelOverrides }),
    ai_model_selectable_values: DEFAULT_AI_MODEL_SELECTABLE_VALUES,
    timezone: "UTC",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

jest.mock("../../components/useOperatorContext", () => ({
  useOperatorContext: () => mockUseOperatorContext(),
}));

jest.mock("../../components/AuthProvider", () => ({
  useAuth: () => mockUseAuth(),
}));

jest.mock("../../lib/api/client", () => ({
  ApiRequestError: class extends Error {
    status: number;
    detail: Record<string, unknown> | null;

    constructor(message: string, status = 500, detail: Record<string, unknown> | null = null) {
      super(message);
      this.status = status;
      this.detail = detail;
    }
  },
  activatePrincipalIdentity: jest.fn(),
  activatePrincipal: jest.fn(),
  createPrincipalIdentity: jest.fn(),
  createPrincipal: jest.fn(),
  deactivatePrincipalIdentity: jest.fn(),
  deactivatePrincipal: jest.fn(),
  deleteAdminSite: jest.fn(),
  executeAdminSiteDelete: (...args: unknown[]) => mockExecuteAdminSiteDelete(...args),
  prepareAdminSiteDeletePlan: (...args: unknown[]) => mockPrepareAdminSiteDeletePlan(...args),
  queryGcpLogs: jest.fn(),
  updateAdminSite: jest.fn(),
  fetchGitHubPublishConfig: (...args: unknown[]) => mockFetchGitHubPublishConfig(...args),
  updateGitHubPublishConfig: (...args: unknown[]) => mockUpdateGitHubPublishConfig(...args),
  updateBusinessSettings: (...args: unknown[]) => mockUpdateBusinessSettings(...args),
  fetchPrincipalIdentities: (...args: unknown[]) => mockFetchPrincipalIdentities(...args),
  fetchPrincipals: (...args: unknown[]) => mockFetchPrincipals(...args),
  fetchBusinessSettings: (...args: unknown[]) => mockFetchBusinessSettings(...args),
}));

type StaticIpDeleteResourceOptions = {
  status?: string;
  reasonCode?: string | null;
  summary?: string;
  ownershipStatus?: string;
  ownershipMethod?: string;
  deleteAttempted?: boolean;
  deleteSelected?: boolean;
};

function buildStaticIpDeleteResource({
  status = "found",
  reasonCode = "static_ip_delete_ownership_verified",
  summary = "Verified managed preview static IP ownership for this site.",
  ownershipStatus = "verified",
  ownershipMethod = "labels",
  deleteAttempted = false,
  deleteSelected = false,
}: StaticIpDeleteResourceOptions = {}) {
  const detailOwnershipMethod = ownershipMethod === "dns_fallback" ? "dns_name_fallback" : ownershipMethod;
  return {
    resource_type: "static_ip",
    status,
    reason_code: reasonCode,
    summary,
    static_ip_ownership_status: ownershipStatus,
    static_ip_ownership_method: ownershipMethod,
    static_ip_delete_attempted: deleteAttempted,
    static_ip_delete_selected: deleteSelected,
    static_ip_delete_reason_code: reasonCode,
    static_ip_delete_safe_summary: summary,
    details: {
      ownership_status: ownershipStatus,
      ownership_verification_method: detailOwnershipMethod,
      static_ip_ownership_status: ownershipStatus,
      static_ip_ownership_method: ownershipMethod,
      static_ip_delete_attempted: deleteAttempted,
      static_ip_delete_selected: deleteSelected,
      static_ip_delete_reason_code: reasonCode,
      static_ip_delete_safe_summary: summary,
    },
  };
}

function buildAdminSiteDeletePlan(staticIpResource: ReturnType<typeof buildStaticIpDeleteResource>) {
  return {
    reason_code: "site_delete_plan_ready",
    site_id: "site-1",
    site_name: "Site One",
    domain: "site-one.example",
    is_active: false,
    generated_repo_owner: "managed-owner",
    generated_repo_name: "site-one-repo",
    kubernetes_namespace: "site-one",
    preview_hostname: "site-one.preview.example.com",
    static_ip_name: "site-one-ip",
    managed_certificate_name: "site-one-cert",
    dns_records_expected: [],
    db_dependency_total: 0,
    db_dependencies: [],
    external_resources: [staticIpResource],
    blockers: [],
    warnings: [],
    required_confirmation_phrase: "DELETE site-one.example",
    execution_defaults: {
      delete_github_repo: false,
      delete_runtime_resources: false,
      delete_dns_resources: false,
      force_delete_active: false,
    },
  };
}

function buildAdminSiteDeleteResult(
  staticIpResource: ReturnType<typeof buildStaticIpDeleteResource>,
  overrides: Partial<{
    reason_code: string;
    message: string;
    db_deleted: boolean;
    site_deleted: boolean;
    external_cleanup_selected: boolean;
    external_cleanup_partial: boolean;
  }> = {},
) {
  return {
    reason_code: overrides.reason_code ?? "site_delete_completed",
    message: overrides.message ?? "Site deleted from the control-plane database with partial external cleanup.",
    site_id: "site-1",
    site_name: "Site One",
    domain: "site-one.example",
    db_deleted: overrides.db_deleted ?? true,
    site_deleted: overrides.site_deleted ?? true,
    external_cleanup_selected: overrides.external_cleanup_selected ?? true,
    external_cleanup_partial: overrides.external_cleanup_partial ?? false,
    db_dependency_total: 0,
    db_dependencies: [],
    external_resources: [staticIpResource],
    blockers: [],
    warnings: [],
  };
}

describe("admin route", () => {
  const expectHeadingOrder = (firstHeading: string, secondHeading: string) => {
    const first = screen.getByRole("heading", { name: firstHeading });
    const second = screen.getByRole("heading", { name: secondHeading });
    const relation = first.compareDocumentPosition(second);
    expect(relation & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  };

  const setAdminSiteDeleteContext = () => {
    mockUseAuth.mockReturnValue({
      principal: {
        business_id: "biz-1",
        principal_id: "admin-delete-1",
        display_name: "Admin Delete",
        role: "admin",
        is_active: true,
      },
    });
    mockUseOperatorContext.mockReturnValue({
      loading: false,
      error: null,
      token: "token-1",
      businessId: "biz-1",
      sites: [
        {
          id: "site-1",
          business_id: "biz-1",
          display_name: "Site One",
          base_url: "https://site-one.example",
          normalized_domain: "site-one.example",
          search_console_property_url: null,
          search_console_enabled: false,
          is_active: false,
          is_primary: true,
          last_audit_run_id: null,
          last_audit_status: null,
          last_audit_completed_at: null,
        },
      ],
      selectedSiteId: "site-1",
      setSelectedSiteId: jest.fn(),
      refreshSites: jest.fn(),
    });
  };

  beforeEach(() => {
    mockUpdateBusinessSettings.mockReset();
    mockFetchGitHubPublishConfig.mockReset();
    mockUpdateGitHubPublishConfig.mockReset();
    mockPrepareAdminSiteDeletePlan.mockReset();
    mockExecuteAdminSiteDelete.mockReset();
    mockFetchPrincipals.mockResolvedValue({ items: [], total: 0 });
    mockFetchPrincipalIdentities.mockResolvedValue({ items: [], total: 0 });
    mockFetchBusinessSettings.mockResolvedValue(buildBusinessSettings());
    mockFetchGitHubPublishConfig.mockResolvedValue({
      id: 1,
      owner: "",
      repository: "",
      default_branch: "main",
      base_path: "/",
      deploy_workflow_mode: "site_repo_template_v1",
      target_environment_key: "gke_prod",
      target_environment_source: "admin_config",
      github_repository_auto_create_enabled: false,
      managed_gke_cluster_name: "mbsrn-cluster",
      managed_gke_cluster_location: "us-central1",
      managed_gke_project_id: "mbsrn-prod",
      namespace_isolation_defaults: {
        resource_quota: {
          enabled: false,
          requests_cpu: "1000m",
          requests_memory: "1Gi",
          limits_cpu: "2000m",
          limits_memory: "2Gi",
          pods: 20,
          services: 10,
          configmaps: 40,
          secrets: 40,
          persistentvolumeclaims: 10,
        },
        limit_range: {
          enabled: false,
          default_cpu: "500m",
          default_memory: "512Mi",
          default_request_cpu: "250m",
          default_request_memory: "256Mi",
          min_cpu: "100m",
          min_memory: "128Mi",
          max_cpu: "2000m",
          max_memory: "2Gi",
        },
        network_policy: {
          enabled: false,
          mode: "default_deny_ingress",
        },
        managed_preview_endpoint: {
          mode: "auto",
          shared_preview_static_ip_name: null,
        },
        migration_generation_budget: {
          ...DEFAULT_MIGRATION_GENERATION_BUDGET,
        },
        migration_generation_safety: {
          ...DEFAULT_MIGRATION_GENERATION_SAFETY,
        },
      },
      enabled: false,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    });
    mockUpdateGitHubPublishConfig.mockResolvedValue({
      id: 1,
      owner: "mhanson13",
      repository: "mhanson13",
      default_branch: "main",
      base_path: "/site",
      deploy_workflow_mode: "site_repo_template_v1",
      target_environment_key: "gke_prod",
      target_environment_source: "admin_config",
      github_repository_auto_create_enabled: true,
      managed_gke_cluster_name: "mbsrn-cluster",
      managed_gke_cluster_location: "us-central1",
      managed_gke_project_id: "mbsrn-prod",
      namespace_isolation_defaults: {
        resource_quota: {
          enabled: true,
          requests_cpu: "1200m",
          requests_memory: "2Gi",
          limits_cpu: "2400m",
          limits_memory: "3Gi",
          pods: 30,
          services: 15,
          configmaps: 50,
          secrets: 50,
          persistentvolumeclaims: 15,
        },
        limit_range: {
          enabled: false,
          default_cpu: "500m",
          default_memory: "512Mi",
          default_request_cpu: "250m",
          default_request_memory: "256Mi",
          min_cpu: "100m",
          min_memory: "128Mi",
          max_cpu: "2000m",
          max_memory: "2Gi",
        },
        network_policy: {
          enabled: false,
          mode: "default_deny_ingress",
        },
        managed_preview_endpoint: {
          mode: "auto",
          shared_preview_static_ip_name: null,
        },
        migration_generation_budget: {
          ...DEFAULT_MIGRATION_GENERATION_BUDGET,
        },
        migration_generation_safety: {
          ...DEFAULT_MIGRATION_GENERATION_SAFETY,
        },
      },
      enabled: true,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    });
    mockUpdateBusinessSettings.mockResolvedValue(buildBusinessSettings());
    mockUseOperatorContext.mockReturnValue({
      loading: false,
      error: null,
      token: "token-1",
      businessId: "biz-1",
      sites: [],
      selectedSiteId: null,
      setSelectedSiteId: jest.fn(),
      refreshSites: jest.fn(),
    });
    mockUseAuth.mockReturnValue({
      principal: {
        business_id: "biz-1",
        principal_id: "operator-1",
        display_name: "Operator One",
        role: "operator",
        is_active: true,
      },
    });
  });

  it("renders the admin page shell at /admin for non-admin principals", () => {
    render(<AdminPage />);

    expect(screen.getByRole("heading", { name: "Admin" })).toBeInTheDocument();
    expect(screen.getByText("Business administration is available to admin principals only.")).toBeInTheDocument();
    expect(document.querySelector(".page-container-width-wide")).toBeTruthy();
  });

  it("renders admin settings sections without user management blocks", async () => {
    mockUseAuth.mockReturnValue({
      principal: {
        business_id: "biz-1",
        principal_id: "admin-1",
        display_name: "Admin One",
        role: "admin",
        is_active: true,
      },
    });

    render(<AdminPage />);

    await waitFor(() => {
      expect(mockFetchPrincipals).not.toHaveBeenCalled();
      expect(mockFetchPrincipalIdentities).not.toHaveBeenCalled();
      expect(mockFetchBusinessSettings).toHaveBeenCalled();
    });

    const wrappedSectionHeadings = [
      "Audit & Crawl Settings",
      "SEO Crawl Settings",
      "Competitor Generation Settings",
      "AI Competitor Candidate Quality",
      "AI Competitor Generation Timeouts",
      "AI Provider & Prompt Governance",
      "AI Task Model Routing",
      "AI Prompt Overrides",
      "Publish & Deployment Configuration",
      "GitHub Publish Configuration",
      "Site Registry Management",
      "Site Management",
      "Diagnostics & Logs",
      "GCP Logs Query",
    ];
    wrappedSectionHeadings.forEach((heading) => {
      const headingNode = screen.getByRole("heading", { name: heading });
      const section = headingNode.closest("section");
      expect(section).not.toBeNull();
      expect(section).toHaveClass("section-card");
    });

    expectHeadingOrder("Audit & Crawl Settings", "SEO Crawl Settings");
    expectHeadingOrder("Competitor Generation Settings", "AI Competitor Candidate Quality");
    expectHeadingOrder("AI Provider & Prompt Governance", "AI Task Model Routing");
    expectHeadingOrder("AI Task Model Routing", "AI Prompt Overrides");
    expectHeadingOrder("Publish & Deployment Configuration", "GitHub Publish Configuration");
    expectHeadingOrder("Site Registry Management", "Site Management");
    expectHeadingOrder("Diagnostics & Logs", "GCP Logs Query");

    expect(screen.queryByRole("heading", { name: "User ID Management" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Create User" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Create and Link Identity" })).not.toBeInTheDocument();
    const providerGovernanceCard = screen.getByTestId("admin-card-ai-provider-governance");
    const taskRoutingCard = screen.getByTestId("admin-card-ai-task-model-routing");
    const promptOverridesCard = screen.getByTestId("admin-card-ai-prompt-overrides");
    expect(within(providerGovernanceCard).getByLabelText("Legacy/global fallback model.")).toBeInTheDocument();
    expect(await within(taskRoutingCard).findByLabelText("Requirements Helper")).toBeInTheDocument();
    expect(within(promptOverridesCard).queryByLabelText("Legacy/global fallback model.")).not.toBeInTheDocument();
    expect(within(promptOverridesCard).getByLabelText("Competitor Prompt")).toBeInTheDocument();
    expect(within(promptOverridesCard).getByLabelText("Recommendations Prompt")).toBeInTheDocument();
    expect(screen.queryByLabelText("Migration Draft Timeout (seconds)")).not.toBeInTheDocument();
    expect(screen.getByLabelText("GitHub account/owner")).toBeInTheDocument();
    const publishEnabledToggle = screen.getByLabelText("Enable migration GitHub publish target");
    const publishOwnerField = screen.getByLabelText("GitHub account/owner");
    const publishToggleOrder = publishEnabledToggle.compareDocumentPosition(publishOwnerField);
    expect(publishToggleOrder & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByLabelText("Default Branch")).toBeInTheDocument();
    expect(screen.getByLabelText("Base Path")).toBeInTheDocument();
    expect(screen.getByLabelText("Enable ResourceQuota for managed site namespaces")).toBeInTheDocument();
    expect(screen.getByLabelText("Enable LimitRange for managed site namespaces")).toBeInTheDocument();
    expect(screen.getByLabelText("Enable managed NetworkPolicy scaffold")).toBeInTheDocument();
    expect(screen.getByText("Migration AI Budget")).toBeInTheDocument();
    expect(screen.getAllByText("Migration Generation Safety").length).toBeGreaterThan(0);
    expect(screen.getByLabelText("Context budget (chars)")).toBeInTheDocument();
    expect(screen.getByLabelText("Generation profile")).toBeInTheDocument();
    expect(screen.getByLabelText("Variation level")).toBeInTheDocument();
    expect(screen.getByText("Admin configures governance and platform defaults. Workflow execution remains on dedicated operational routes.")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Prompt overrides affect future generated recommendations and competitor suggestions. Keep overrides bounded and contract-compatible.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Migration draft provider timeout is managed in/i),
    ).toBeInTheDocument();
    expect(screen.getByText("Namespace policy controls managed site Kubernetes defaults for new managed site namespaces.")).toBeInTheDocument();
    expect(screen.getByText("Diagnostics is read-only log investigation for runtime troubleshooting.")).toBeInTheDocument();
    expect(
      screen.queryByText(
        "Controls how closely a competitor must match your business to be included. Higher values mean stricter, more relevant matches.",
      ),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Search Console Property" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Search Console Enabled" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Permanent Delete (destructive)" })).toBeInTheDocument();
    expect(screen.getByText("sc-domain:example.com")).toBeInTheDocument();
    expect(screen.getByText("https://example.com")).toBeInTheDocument();
    expect(
      screen.getByText('severity="ERROR" resource.labels.namespace_name="mbsrn" -textPayload =~ "INFO*"'),
    ).toBeInTheDocument();
    const runQueryButton = screen.getByRole("button", { name: "Run Query" });
    const nextPageButton = screen.getByRole("button", { name: "Next Page" });
    const useExampleButton = screen.getByRole("button", { name: "Use example" });
    const gcpActionRow = runQueryButton.closest(".form-actions");
    expect(gcpActionRow).not.toBeNull();
    expect(nextPageButton.closest(".form-actions")).toBe(gcpActionRow);
    expect(useExampleButton.closest(".form-actions")).toBe(gcpActionRow);
  });

  it("shows lightweight Search Console property format hint for obvious invalid input", async () => {
    mockUseAuth.mockReturnValue({
      principal: {
        business_id: "biz-1",
        principal_id: "admin-3",
        display_name: "Admin Three",
        role: "admin",
        is_active: true,
      },
    });
    mockUseOperatorContext.mockReturnValue({
      loading: false,
      error: null,
      token: "token-1",
      businessId: "biz-1",
      sites: [
        {
          id: "site-1",
          business_id: "biz-1",
          display_name: "Site One",
          base_url: "https://site-one.example",
          normalized_domain: "site-one.example",
          search_console_property_url: null,
          search_console_enabled: false,
          is_active: true,
          is_primary: true,
          last_audit_run_id: null,
          last_audit_status: null,
          last_audit_completed_at: null,
        },
      ],
      selectedSiteId: "site-1",
      setSelectedSiteId: jest.fn(),
      refreshSites: jest.fn(),
    });

    render(<AdminPage />);

    await waitFor(() => {
      expect(mockFetchBusinessSettings).toHaveBeenCalled();
    });

    const propertyInput = screen.getByRole("textbox", { name: "Search Console property site-1" });
    fireEvent.change(propertyInput, { target: { value: "example.com" } });

    expect(screen.getByText("Use sc-domain:example.com or https://example.com.")).toBeInTheDocument();
  });

  it("shows a compact warning when competitor prompt override uses legacy output aliases", async () => {
    mockFetchBusinessSettings.mockResolvedValueOnce({
      id: "biz-1",
      name: "Biz",
      notification_phone: null,
      notification_email: null,
      sms_enabled: false,
      email_enabled: false,
      customer_auto_ack_enabled: false,
      contractor_alerts_enabled: false,
      seo_audit_crawl_max_pages: 200,
      competitor_candidate_min_relevance_score: 30,
      competitor_candidate_big_box_penalty: 20,
      competitor_candidate_directory_penalty: 20,
      competitor_candidate_local_alignment_bonus: 10,
      competitor_primary_timeout_seconds: null,
      competitor_degraded_timeout_seconds: null,
      migration_draft_timeout_seconds: null,
      ai_prompt_text_competitor:
        'PROMPT_VERSION: seo-competitor-profile-v5\n{"candidates":[{"name":"Example","domain":"example.com","reasoning":"same market"}]}',
      ai_prompt_text_recommendations: null,
      default_ai_model: null,
      timezone: "UTC",
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    });
    mockUseAuth.mockReturnValue({
      principal: {
        business_id: "biz-1",
        principal_id: "admin-legacy-prompt",
        display_name: "Admin Prompt",
        role: "admin",
        is_active: true,
      },
    });

    render(<AdminPage />);

    expect(await screen.findByTestId("competitor-prompt-override-warning")).toHaveTextContent("legacy aliases");
  });

  it("renders accessible help icons for key admin settings", async () => {
    mockUseAuth.mockReturnValue({
      principal: {
        business_id: "biz-1",
        principal_id: "admin-help-1",
        display_name: "Admin Help",
        role: "admin",
        is_active: true,
      },
    });

    render(<AdminPage />);

    await waitFor(() => {
      expect(mockFetchBusinessSettings).toHaveBeenCalled();
    });

    const minRelevanceHelp = screen.getByTestId("admin-help-minimum-relevance-score");
    const bigBoxHelp = screen.getByTestId("admin-help-big-box-mismatch-penalty");
    const primaryCompetitorTimeoutHelp = screen.getByTestId("admin-help-competitor-primary-timeout-seconds");
    const degradedCompetitorTimeoutHelp = screen.getByTestId("admin-help-competitor-degraded-timeout-seconds");
    const competitorPromptHelp = screen.getByTestId("admin-help-competitor-prompt");
    const recommendationsPromptHelp = screen.getByTestId("admin-help-recommendations-prompt");
    const defaultModelHelp = screen.getByTestId("admin-help-default-ai-model");
    const fallbackHelp = screen.getByTestId("admin-help-use-deployment-fallbacks");
    const timeoutHelp = screen.getByTestId("admin-help-migration-provider-timeout-seconds");
    const contextBudgetHelp = screen.getByTestId("admin-help-migration-context-budget");
    const preflightHelp = screen.getByTestId("admin-help-preflight-mode");
    const managedClusterHelp = screen.getByTestId("admin-help-managed-gke-cluster-name");
    const networkPolicyModeHelp = screen.getByTestId("admin-help-networkpolicy-mode");

    [
      minRelevanceHelp,
      bigBoxHelp,
      primaryCompetitorTimeoutHelp,
      degradedCompetitorTimeoutHelp,
      competitorPromptHelp,
      recommendationsPromptHelp,
      defaultModelHelp,
      fallbackHelp,
      timeoutHelp,
      contextBudgetHelp,
      preflightHelp,
      managedClusterHelp,
      networkPolicyModeHelp,
    ].forEach((helpButton) => {
      expect(helpButton).toHaveAttribute("aria-label");
      expect(helpButton).toHaveAttribute("data-help-text");
    });

    expect(timeoutHelp).toHaveAttribute(
      "data-help-text",
      "Maximum synchronous timeout is 600 seconds / 10 minutes. Longer timeouts increase latency/cost and do not fix oversized or overly complex prompts.",
    );
    expect(primaryCompetitorTimeoutHelp).toHaveAttribute("data-help-text", expect.stringContaining("first full competitor generation attempt"));
    expect(degradedCompetitorTimeoutHelp).toHaveAttribute("data-help-text", expect.stringContaining("shorter fallback retry"));
    expect(competitorPromptHelp).toHaveAttribute("data-help-text", expect.stringContaining("strict JSON output contract"));
    expect(recommendationsPromptHelp).toHaveAttribute("data-help-text", expect.stringContaining("required JSON/schema fields"));
    expect(defaultModelHelp).toHaveAttribute("data-help-text", expect.stringContaining("Resolution order: explicit request"));
    expect(defaultModelHelp).toHaveAttribute("data-help-text", expect.stringContaining("task override"));
    expect(defaultModelHelp).toHaveAttribute("data-help-text", expect.stringContaining("cost, latency, output style, and compatibility"));
    expect(fallbackHelp).toHaveAttribute(
      "data-help-text",
      "Clears business-level prompt and default-model overrides so deployment defaults are used. This does not delete deployment configuration.",
    );
  });

  it("loads and saves the legacy/global AI model in admin settings", async () => {
    mockFetchBusinessSettings.mockResolvedValueOnce(
      buildBusinessSettings({
        migration_draft_timeout_seconds: 180,
        default_ai_model: "gpt-4.1-mini",
      }),
    );
    mockUpdateBusinessSettings.mockResolvedValueOnce(
      buildBusinessSettings({
        migration_draft_timeout_seconds: 240,
        default_ai_model: "gpt-5-mini",
      }),
    );
    mockUseAuth.mockReturnValue({
      principal: {
        business_id: "biz-1",
        principal_id: "admin-model-1",
        display_name: "Admin Model",
        role: "admin",
        is_active: true,
      },
    });

    render(<AdminPage />);

    const providerGovernanceCard = await screen.findByTestId("admin-card-ai-provider-governance");
    const promptOverridesCard = await screen.findByTestId("admin-card-ai-prompt-overrides");
    const defaultModelInput = within(providerGovernanceCard).getByLabelText("Legacy/global fallback model.");
    expect(within(promptOverridesCard).queryByLabelText("Legacy/global fallback model.")).not.toBeInTheDocument();
    await waitFor(() => {
      expect(defaultModelInput).toHaveValue("gpt-4.1-mini");
    });

    fireEvent.change(defaultModelInput, { target: { value: "gpt-5-mini" } });
    fireEvent.click(screen.getByRole("button", { name: "Save Prompt Overrides" }));

    await waitFor(() => {
    expect(mockUpdateBusinessSettings).toHaveBeenCalled();
    });
    expect(mockUpdateBusinessSettings.mock.calls.at(-1)?.[2]).toMatchObject({
      default_ai_model: "gpt-5-mini",
    });
    expect(await screen.findByLabelText("Legacy/global fallback model.")).toHaveValue("gpt-5-mini");
    expect(screen.queryByLabelText("Migration Draft Timeout (seconds)")).not.toBeInTheDocument();
  });

  it("shows a deprecated-model error for the legacy/global AI model field", async () => {
    const { ApiRequestError } = jest.requireMock("../../lib/api/client");

    mockFetchBusinessSettings.mockResolvedValueOnce(
      buildBusinessSettings({
        migration_draft_timeout_seconds: 180,
      }),
    );
    mockUpdateBusinessSettings.mockRejectedValueOnce(
      new ApiRequestError("default_ai_model cannot use deprecated or blocked model values.", 422),
    );
    mockUseAuth.mockReturnValue({
      principal: {
        business_id: "biz-1",
        principal_id: "admin-model-1",
        display_name: "Admin Model",
        role: "admin",
        is_active: true,
      },
    });

    render(<AdminPage />);

    const providerGovernanceCard = await screen.findByTestId("admin-card-ai-provider-governance");
    const defaultModelInput = within(providerGovernanceCard).getByLabelText("Legacy/global fallback model.");

    fireEvent.change(defaultModelInput, { target: { value: "gpt-4o-mini" } });
    fireEvent.click(screen.getByRole("button", { name: "Save Prompt Overrides" }));

    expect(
      await screen.findByText(
        "Legacy/global fallback model cannot use a deprecated or blocked value. Use a current supported model or clear the field.",
      ),
    ).toBeInTheDocument();
  });

  it("renders AI task model routing rows with effective source details", async () => {
    mockUseAuth.mockReturnValue({
      principal: {
        business_id: "biz-1",
        principal_id: "admin-routing-1",
        display_name: "Admin Routing",
        role: "admin",
        is_active: true,
      },
    });

    render(<AdminPage />);

    const routingCard = await screen.findByTestId("admin-card-ai-task-model-routing");
    const requirementsRow = await within(routingCard).findByTestId("ai-task-model-row-requirements_helper");

    expect(within(requirementsRow).getByLabelText("Requirements Helper")).toBeInTheDocument();
    expect(within(requirementsRow).getByText("Effective source:", { exact: false })).toBeInTheDocument();
    expect(within(requirementsRow).getByText("Deployment fallback")).toBeInTheDocument();
  });

  it("saves and clears task-specific AI model overrides", async () => {
    mockUseAuth.mockReturnValue({
      principal: {
        business_id: "biz-1",
        principal_id: "admin-routing-2",
        display_name: "Admin Routing",
        role: "admin",
        is_active: true,
      },
    });
    mockUpdateBusinessSettings.mockResolvedValueOnce(
      buildBusinessSettings({
        ai_model_overrides: {
          requirements_helper: "gpt-5.6-luna",
        },
      }),
    );
    mockUpdateBusinessSettings.mockResolvedValueOnce(
      buildBusinessSettings({
        default_ai_model: "gpt-5.6-terra",
        ai_model_overrides: {},
      }),
    );

    render(<AdminPage />);

    const routingCard = await screen.findByTestId("admin-card-ai-task-model-routing");
    const requirementsRow = await within(routingCard).findByTestId("ai-task-model-row-requirements_helper");
    const requirementsInput = within(requirementsRow).getByLabelText("Requirements Helper");

    fireEvent.change(requirementsInput, { target: { value: "gpt-5.6-luna" } });
    fireEvent.click(screen.getByRole("button", { name: "Save Task Routing" }));

    await waitFor(() => {
      expect(mockUpdateBusinessSettings).toHaveBeenCalled();
    });
    expect(mockUpdateBusinessSettings.mock.calls.at(-1)?.[2]).toMatchObject({
      ai_model_overrides: {
        requirements_helper: "gpt-5.6-luna",
        media_metadata_helper: null,
        embeddings: null,
      },
    });
    expect(await screen.findByText("AI task model routing updated.")).toBeInTheDocument();
    expect(within(requirementsRow).getByDisplayValue("gpt-5.6-luna")).toBeInTheDocument();
    expect(within(requirementsRow).getByText("Task override")).toBeInTheDocument();

    fireEvent.click(within(requirementsRow).getByRole("button", { name: "Inherit fallback" }));
    fireEvent.click(screen.getByRole("button", { name: "Save Task Routing" }));

    await waitFor(() => {
      expect(mockUpdateBusinessSettings).toHaveBeenCalledTimes(2);
    });
    expect(mockUpdateBusinessSettings.mock.calls.at(-1)?.[2]).toMatchObject({
      ai_model_overrides: {
        requirements_helper: null,
        media_metadata_helper: null,
        embeddings: null,
      },
    });
    expect(within(requirementsRow).getByText("Legacy/global fallback")).toBeInTheDocument();
  });

  it("shows backend task-routing errors for deprecated and capability-mismatch values", async () => {
    const { ApiRequestError } = jest.requireMock("../../lib/api/client");
    mockUseAuth.mockReturnValue({
      principal: {
        business_id: "biz-1",
        principal_id: "admin-routing-3",
        display_name: "Admin Routing",
        role: "admin",
        is_active: true,
      },
    });
    mockUpdateBusinessSettings.mockRejectedValueOnce(
      new ApiRequestError(
        "Configured AI model for task alias 'requirements_helper' cannot use deprecated or blocked model values.",
        422,
        {
          reason_code: "ai_model_deprecated",
          message: "Configured AI model for task alias 'requirements_helper' cannot use deprecated or blocked model values.",
          field: "ai_model_overrides",
          task_alias: "requirements_helper",
        },
      ),
    );
    mockUpdateBusinessSettings.mockRejectedValueOnce(
      new ApiRequestError(
        "Configured AI model for task alias 'media_metadata_helper' does not satisfy required capabilities: multimodal.",
        422,
        {
          reason_code: "ai_model_capability_mismatch",
          message:
            "Configured AI model for task alias 'media_metadata_helper' does not satisfy required capabilities: multimodal.",
          field: "ai_model_overrides",
          task_alias: "media_metadata_helper",
        },
      ),
    );

    render(<AdminPage />);

    const routingCard = await screen.findByTestId("admin-card-ai-task-model-routing");
    const requirementsRow = await within(routingCard).findByTestId("ai-task-model-row-requirements_helper");
    fireEvent.change(within(requirementsRow).getByLabelText("Requirements Helper"), {
      target: { value: "gpt-4o-mini" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save Task Routing" }));

    expect(
      await screen.findByText(
        "Configured AI model for task alias 'requirements_helper' cannot use deprecated or blocked model values.",
      ),
    ).toBeInTheDocument();

    const mediaRow = await within(routingCard).findByTestId("ai-task-model-row-media_metadata_helper");
    fireEvent.change(within(mediaRow).getByLabelText("Media Metadata Helper"), {
      target: { value: "gpt-5.6-luna" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save Task Routing" }));

    expect(
      await screen.findByText(
        "Configured AI model for task alias 'media_metadata_helper' does not satisfy required capabilities: multimodal.",
      ),
    ).toBeInTheDocument();
  });

  it("loads and saves GitHub publish configuration in admin settings", async () => {
    mockFetchGitHubPublishConfig.mockResolvedValue({
      id: 1,
      owner: "mhanson13",
      repository: "mhanson13",
      default_branch: "main",
      base_path: "/",
      deploy_workflow_mode: "site_repo_template_v1",
      target_environment_key: "gke_prod",
      target_environment_source: "admin_config",
      github_repository_auto_create_enabled: false,
      managed_gke_cluster_name: "mbsrn-cluster",
      managed_gke_cluster_location: "us-central1",
      managed_gke_project_id: "mbsrn-prod",
      namespace_isolation_defaults: {
        resource_quota: {
          enabled: false,
          requests_cpu: "1000m",
          requests_memory: "1Gi",
          limits_cpu: "2000m",
          limits_memory: "2Gi",
          pods: 20,
          services: 10,
          configmaps: 40,
          secrets: 40,
          persistentvolumeclaims: 10,
        },
        limit_range: {
          enabled: false,
          default_cpu: "500m",
          default_memory: "512Mi",
          default_request_cpu: "250m",
          default_request_memory: "256Mi",
          min_cpu: "100m",
          min_memory: "128Mi",
          max_cpu: "2000m",
          max_memory: "2Gi",
        },
        network_policy: {
          enabled: false,
          mode: "default_deny_ingress",
        },
        managed_preview_endpoint: {
          mode: "auto",
          shared_preview_static_ip_name: null,
        },
        migration_generation_budget: {
          ...DEFAULT_MIGRATION_GENERATION_BUDGET,
        },
        migration_generation_safety: {
          ...DEFAULT_MIGRATION_GENERATION_SAFETY,
        },
      },
      enabled: true,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    });
    mockUpdateGitHubPublishConfig.mockResolvedValueOnce({
      id: 1,
      owner: "mhanson13",
      repository: "mhanson13",
      default_branch: "release",
      base_path: "/site/content",
      deploy_workflow_mode: "site_repo_template_v1",
      target_environment_key: "gke_prod_blue",
      target_environment_source: "admin_config",
      github_repository_auto_create_enabled: true,
      managed_gke_cluster_name: "mbsrn-cluster-prod",
      managed_gke_cluster_location: "us-central1-b",
      managed_gke_project_id: "mbsrn-prod-2",
      namespace_isolation_defaults: {
        resource_quota: {
          enabled: true,
          requests_cpu: "1200m",
          requests_memory: "2Gi",
          limits_cpu: "2400m",
          limits_memory: "3Gi",
          pods: 30,
          services: 15,
          configmaps: 50,
          secrets: 50,
          persistentvolumeclaims: 15,
        },
        limit_range: {
          enabled: false,
          default_cpu: "500m",
          default_memory: "512Mi",
          default_request_cpu: "250m",
          default_request_memory: "256Mi",
          min_cpu: "100m",
          min_memory: "128Mi",
          max_cpu: "2000m",
          max_memory: "2Gi",
        },
        network_policy: {
          enabled: false,
          mode: "default_deny_ingress",
        },
        managed_preview_endpoint: {
          mode: "auto",
          shared_preview_static_ip_name: null,
        },
        migration_generation_budget: {
          ...DEFAULT_MIGRATION_GENERATION_BUDGET,
        },
        migration_generation_safety: {
          ...DEFAULT_MIGRATION_GENERATION_SAFETY,
        },
      },
      enabled: true,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    });
    mockUseAuth.mockReturnValue({
      principal: {
        business_id: "biz-1",
        principal_id: "admin-gh-1",
        display_name: "Admin GH",
        role: "admin",
        is_active: true,
      },
    });

    render(<AdminPage />);

    const repositoryInput = await screen.findByLabelText("GitHub account/owner");
    await waitFor(() => {
      expect(repositoryInput).toHaveValue("mhanson13");
    });
    const defaultBranchInput = screen.getByLabelText("Default Branch");
    expect(defaultBranchInput).toHaveValue("main");
    const basePathInput = screen.getByLabelText("Base Path");
    expect(basePathInput).toHaveValue("/");
    const deployWorkflowModeInput = screen.getByLabelText("Deploy Workflow Mode");
    expect(deployWorkflowModeInput).toHaveValue("site_repo_template_v1");
    const targetEnvironmentKeyInput = screen.getByLabelText("Target Environment Key");
    expect(targetEnvironmentKeyInput).toHaveValue("gke_prod");
    const repoAutoCreateToggle = screen.getByLabelText(
      "Enable managed repository auto-create for missing publish targets",
    );
    expect(repoAutoCreateToggle).not.toBeChecked();
    const managedGkeClusterNameInput = screen.getByLabelText("Managed GKE Cluster Name");
    expect(managedGkeClusterNameInput).toHaveValue("mbsrn-cluster");
    const managedGkeClusterLocationInput = screen.getByLabelText("Managed GKE Cluster Location");
    expect(managedGkeClusterLocationInput).toHaveValue("us-central1");
    const managedGkeProjectIdInput = screen.getByLabelText("Managed GCP Project ID");
    expect(managedGkeProjectIdInput).toHaveValue("mbsrn-prod");
    const enabledToggle = screen.getByLabelText("Enable migration GitHub publish target");
    expect(enabledToggle).toBeChecked();
    const preview = screen.getByTestId("github-publish-effective-preview");
    expect(preview).toHaveTextContent("mhanson13");
    expect(preview).toHaveTextContent("main");
    expect(preview).toHaveTextContent("/");
    expect(preview).toHaveTextContent("site_repo_template_v1");
    expect(preview).toHaveTextContent("gke_prod");
    expect(preview).toHaveTextContent("admin_config");

    fireEvent.change(defaultBranchInput, { target: { value: "release" } });
    fireEvent.change(basePathInput, { target: { value: "site//content/" } });
    fireEvent.change(targetEnvironmentKeyInput, { target: { value: "gke_prod_blue" } });
    fireEvent.change(managedGkeClusterNameInput, { target: { value: "mbsrn-cluster-prod" } });
    fireEvent.change(managedGkeClusterLocationInput, { target: { value: "us-central1-b" } });
    fireEvent.change(managedGkeProjectIdInput, { target: { value: "mbsrn-prod-2" } });
    fireEvent.change(screen.getByLabelText("Managed Deploy Secret (GCP_DEPLOY_KEY)"), {
      target: { value: "{\"secret\":\"write-only\"}" },
    });
    fireEvent.click(screen.getByLabelText("Enable ResourceQuota for managed site namespaces"));
    fireEvent.change(screen.getByLabelText("Requests CPU"), { target: { value: "1200m" } });
    fireEvent.change(screen.getByLabelText("Requests Memory"), { target: { value: "2Gi" } });
    fireEvent.change(screen.getByLabelText("Limits CPU"), { target: { value: "2400m" } });
    fireEvent.change(screen.getByLabelText("Limits Memory"), { target: { value: "3Gi" } });
    fireEvent.change(screen.getByLabelText("Pods"), { target: { value: "30" } });
    fireEvent.change(screen.getByLabelText("Services"), { target: { value: "15" } });
    fireEvent.change(screen.getByLabelText("ConfigMaps"), { target: { value: "50" } });
    fireEvent.change(screen.getByLabelText("Secrets"), { target: { value: "50" } });
    fireEvent.change(screen.getByLabelText("PersistentVolumeClaims"), { target: { value: "15" } });
    fireEvent.change(screen.getByLabelText("Context budget (chars)"), { target: { value: "22000" } });
    fireEvent.change(screen.getByLabelText("Recommendation limit"), { target: { value: "10" } });
    fireEvent.change(screen.getByLabelText("Generation profile"), { target: { value: "expanded" } });
    fireEvent.change(screen.getByLabelText("Variation level"), { target: { value: "differentiated" } });
    fireEvent.click(screen.getByLabelText("Require page variety"));
    expect(screen.getByTestId("github-publish-migration-generation-safety")).toBeInTheDocument();
    const providerTimeoutInput = screen.getByLabelText("Provider timeout seconds");
    expect(providerTimeoutInput).not.toHaveAttribute("max");
    fireEvent.change(providerTimeoutInput, { target: { value: "240" } });
    fireEvent.change(screen.getByLabelText("Preflight mode"), { target: { value: "block_before_provider" } });
    fireEvent.change(screen.getByLabelText("Max final input chars"), { target: { value: "8500" } });
    fireEvent.change(screen.getByLabelText("Max difficulty score"), { target: { value: "11" } });
    fireEvent.change(screen.getByLabelText("Compact page limit"), { target: { value: "3" } });
    fireEvent.change(screen.getByLabelText("Compact media limit"), { target: { value: "2" } });
    fireEvent.change(screen.getByLabelText("Compact recommendation limit"), { target: { value: "3" } });
    expect(screen.getByTestId("github-publish-effective-preview")).toHaveTextContent("/site/content");
    fireEvent.click(screen.getByRole("button", { name: "Save GitHub Publish Config" }));

    await waitFor(() => {
      expect(mockUpdateGitHubPublishConfig).toHaveBeenCalled();
    });
    expect(mockUpdateGitHubPublishConfig.mock.calls.at(-1)?.[1]).toMatchObject({
      owner: "mhanson13",
      default_branch: "release",
      base_path: "/site/content",
      deploy_workflow_mode: "site_repo_template_v1",
      target_environment_key: "gke_prod_blue",
      github_repository_auto_create_enabled: false,
      managed_gke_cluster_name: "mbsrn-cluster-prod",
      managed_gke_cluster_location: "us-central1-b",
      managed_gke_project_id: "mbsrn-prod-2",
      namespace_isolation_defaults: {
        resource_quota: {
          enabled: true,
          requests_cpu: "1200m",
          requests_memory: "2Gi",
          limits_cpu: "2400m",
          limits_memory: "3Gi",
          pods: 30,
          services: 15,
          configmaps: 50,
          secrets: 50,
          persistentvolumeclaims: 15,
        },
        limit_range: {
          enabled: false,
          default_cpu: "500m",
          default_memory: "512Mi",
          default_request_cpu: "250m",
          default_request_memory: "256Mi",
          min_cpu: "100m",
          min_memory: "128Mi",
          max_cpu: "2000m",
          max_memory: "2Gi",
        },
        network_policy: {
          enabled: false,
          mode: "default_deny_ingress",
        },
        managed_preview_endpoint: {
          mode: "auto",
          shared_preview_static_ip_name: null,
        },
        migration_generation_budget: {
          migration_context_budget_chars: 22000,
          migration_recommendation_limit: 10,
          migration_generation_depth: "expanded",
          migration_variation_level: "differentiated",
          migration_require_page_variety: false,
        },
        migration_generation_safety: {
          migration_provider_timeout_seconds: 240,
          migration_preflight_mode: "block_before_provider",
          migration_max_final_input_chars: 8500,
          migration_max_difficulty_score: 11,
          migration_compact_fallback_enabled: true,
          migration_compact_page_limit: 3,
          migration_compact_media_asset_limit: 2,
          migration_compact_recommendation_limit: 3,
        },
      },
      enabled: true,
    });
    expect(await screen.findByLabelText("Default Branch")).toHaveValue("release");
    expect(screen.getByLabelText("Base Path")).toHaveValue("/site/content");
    expect(screen.getByTestId("github-publish-effective-preview")).toHaveTextContent("/site/content");
    expect(screen.queryByText("{\"secret\":\"write-only\"}")).not.toBeInTheDocument();
  }, 15000);

  it("preserves managed preview endpoint defaults when saving GitHub publish configuration", async () => {
    const fetchedConfig = {
      id: 1,
      owner: "mhanson13",
      repository: "mhanson13",
      default_branch: "main",
      base_path: "/",
      deploy_workflow_mode: "site_repo_template_v1",
      target_environment_key: "gke_prod",
      target_environment_source: "admin_config",
      github_repository_auto_create_enabled: false,
      managed_gke_cluster_name: "mbsrn-cluster",
      managed_gke_cluster_location: "us-central1",
      managed_gke_project_id: "mbsrn-prod",
      namespace_isolation_defaults: {
        resource_quota: {
          enabled: false,
          requests_cpu: "1000m",
          requests_memory: "1Gi",
          limits_cpu: "2000m",
          limits_memory: "2Gi",
          pods: 20,
          services: 10,
          configmaps: 40,
          secrets: 40,
          persistentvolumeclaims: 10,
        },
        limit_range: {
          enabled: false,
          default_cpu: "500m",
          default_memory: "512Mi",
          default_request_cpu: "250m",
          default_request_memory: "256Mi",
          min_cpu: "100m",
          min_memory: "128Mi",
          max_cpu: "2000m",
          max_memory: "2Gi",
        },
        network_policy: {
          enabled: false,
          mode: "default_deny_ingress",
        },
        managed_preview_endpoint: {
          mode: "preview_shared_gateway",
          shared_preview_static_ip_name: "site-preview-shared-ip",
        },
        migration_generation_budget: {
          ...DEFAULT_MIGRATION_GENERATION_BUDGET,
        },
        migration_generation_safety: {
          ...DEFAULT_MIGRATION_GENERATION_SAFETY,
        },
      },
      enabled: true,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    };
    mockFetchGitHubPublishConfig.mockResolvedValueOnce(fetchedConfig);
    mockUpdateGitHubPublishConfig.mockImplementationOnce(async (_token: string, payload: any) => ({
      ...fetchedConfig,
      ...payload,
      namespace_isolation_defaults: payload.namespace_isolation_defaults,
      namespace_isolation_effective_defaults: payload.namespace_isolation_defaults,
      namespace_isolation_cap_reasons: {},
    }));
    mockUseAuth.mockReturnValue({
      principal: {
        business_id: "biz-1",
        principal_id: "admin-gh-managed-preview-endpoint",
        display_name: "Admin Managed Endpoint",
        role: "admin",
        is_active: true,
      },
    });

    render(<AdminPage />);

    await screen.findByLabelText("GitHub account/owner");
    fireEvent.change(screen.getByLabelText("Default Branch"), { target: { value: "release" } });
    fireEvent.click(screen.getByRole("button", { name: "Save GitHub Publish Config" }));

    await waitFor(() => {
      expect(mockUpdateGitHubPublishConfig).toHaveBeenCalled();
    });
    const payload = mockUpdateGitHubPublishConfig.mock.calls.at(-1)?.[1];
    expect(payload.namespace_isolation_defaults.managed_preview_endpoint).toEqual({
      mode: "preview_shared_gateway",
      shared_preview_static_ip_name: "site-preview-shared-ip",
    });
    expect(await screen.findByText("GitHub publish configuration saved.")).toBeInTheDocument();
  });

  it("clears a prior GitHub publish save failure after a later successful save", async () => {
    const failedSaveMessage = "Failed to save GitHub publish configuration.";
    let resolveSecondSave!: (value: unknown) => void;
    const secondSavePromise = new Promise<unknown>((resolve) => {
      resolveSecondSave = resolve;
    });
    mockUpdateGitHubPublishConfig.mockReset();
    mockUpdateGitHubPublishConfig.mockRejectedValueOnce(new Error("temporary failure"));
    mockUpdateGitHubPublishConfig.mockImplementationOnce(() => secondSavePromise as Promise<unknown>);
    mockUseAuth.mockReturnValue({
      principal: {
        business_id: "biz-1",
        principal_id: "admin-gh-retry",
        display_name: "Admin GH Retry",
        role: "admin",
        is_active: true,
      },
    });

    render(<AdminPage />);

    await screen.findByLabelText("GitHub account/owner");
    expect(screen.getByLabelText("Context budget (chars)")).toBeInTheDocument();
    expect(screen.getByTestId("github-publish-effective-preview")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Save GitHub Publish Config" })).toBeEnabled();
    });

    fireEvent.click(screen.getByRole("button", { name: "Save GitHub Publish Config" }));
    await waitFor(() => {
      expect(mockUpdateGitHubPublishConfig).toHaveBeenCalledTimes(1);
    });
    expect(await screen.findByText(failedSaveMessage)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Save GitHub Publish Config" }));
    await waitFor(() => {
      expect(mockUpdateGitHubPublishConfig).toHaveBeenCalledTimes(2);
    });
    await waitFor(() => {
      expect(screen.queryByText(failedSaveMessage)).not.toBeInTheDocument();
    });

    resolveSecondSave({
      id: 1,
      owner: "mhanson13",
      repository: "mhanson13",
      default_branch: "main",
      base_path: "/site",
      deploy_workflow_mode: "site_repo_template_v1",
      target_environment_key: "gke_prod",
      target_environment_source: "admin_config",
      github_repository_auto_create_enabled: true,
      managed_gke_cluster_name: "mbsrn-cluster",
      managed_gke_cluster_location: "us-central1",
      managed_gke_project_id: "mbsrn-prod",
      namespace_isolation_defaults: {
        resource_quota: {
          enabled: false,
          requests_cpu: "1000m",
          requests_memory: "1Gi",
          limits_cpu: "2000m",
          limits_memory: "2Gi",
          pods: 20,
          services: 10,
          configmaps: 40,
          secrets: 40,
          persistentvolumeclaims: 10,
        },
        limit_range: {
          enabled: false,
          default_cpu: "500m",
          default_memory: "512Mi",
          default_request_cpu: "250m",
          default_request_memory: "256Mi",
          min_cpu: "100m",
          min_memory: "128Mi",
          max_cpu: "2000m",
          max_memory: "2Gi",
        },
        network_policy: {
          enabled: false,
          mode: "default_deny_ingress",
        },
        managed_preview_endpoint: {
          mode: "auto",
          shared_preview_static_ip_name: null,
        },
        migration_generation_budget: {
          ...DEFAULT_MIGRATION_GENERATION_BUDGET,
        },
        migration_generation_safety: {
          ...DEFAULT_MIGRATION_GENERATION_SAFETY,
        },
      },
      enabled: true,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    });

    expect(await screen.findByText("GitHub publish configuration saved.")).toBeInTheDocument();
    expect(screen.queryByText(failedSaveMessage)).not.toBeInTheDocument();
  });

  it("shows save success plus notification health warning without displaying generic failed-save copy", async () => {
    mockFetchBusinessSettings.mockResolvedValueOnce({
      id: "biz-1",
      name: "Biz",
      notification_phone: null,
      notification_email: null,
      sms_enabled: false,
      email_enabled: true,
      customer_auto_ack_enabled: false,
      contractor_alerts_enabled: false,
      seo_audit_crawl_max_pages: 200,
      competitor_candidate_min_relevance_score: 30,
      competitor_candidate_big_box_penalty: 20,
      competitor_candidate_directory_penalty: 20,
      competitor_candidate_local_alignment_bonus: 10,
      competitor_primary_timeout_seconds: null,
      competitor_degraded_timeout_seconds: null,
      migration_draft_timeout_seconds: null,
      ai_prompt_text_competitor: null,
      ai_prompt_text_recommendations: null,
      default_ai_model: null,
      timezone: "UTC",
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    });
    mockUseAuth.mockReturnValue({
      principal: {
        business_id: "biz-1",
        principal_id: "admin-gh-health-warning",
        display_name: "Admin GH Health Warning",
        role: "admin",
        is_active: true,
      },
    });

    render(<AdminPage />);

    await screen.findByLabelText("GitHub account/owner");
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Save GitHub Publish Config" })).toBeEnabled();
    });
    fireEvent.click(screen.getByRole("button", { name: "Save GitHub Publish Config" }));
    await waitFor(() => {
      expect(mockUpdateGitHubPublishConfig).toHaveBeenCalled();
    });

    expect(await screen.findByText("GitHub publish configuration saved.")).toBeInTheDocument();
    expect(
      screen.getByText("Notification settings health: One or more saved values need review."),
    ).toBeInTheDocument();
    expect(screen.queryByText("Failed to save GitHub publish configuration.")).not.toBeInTheDocument();
  });

  it("shows a failed-save message when GitHub publish config save request fails", async () => {
    mockUpdateGitHubPublishConfig.mockRejectedValueOnce(new Error("save failed"));
    mockUseAuth.mockReturnValue({
      principal: {
        business_id: "biz-1",
        principal_id: "admin-gh-failed-save",
        display_name: "Admin GH Failed Save",
        role: "admin",
        is_active: true,
      },
    });

    render(<AdminPage />);

    await screen.findByLabelText("GitHub account/owner");
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Save GitHub Publish Config" })).toBeEnabled();
    });
    fireEvent.click(screen.getByRole("button", { name: "Save GitHub Publish Config" }));
    await waitFor(() => {
      expect(mockUpdateGitHubPublishConfig).toHaveBeenCalled();
    });

    expect(await screen.findByText("Failed to save GitHub publish configuration.")).toBeInTheDocument();
    expect(screen.queryByText("GitHub publish configuration saved.")).not.toBeInTheDocument();
  });

  it("shows GitHub publish validation guidance and blocks save until issues are resolved", async () => {
    mockUseAuth.mockReturnValue({
      principal: {
        business_id: "biz-1",
        principal_id: "admin-gh-validate",
        display_name: "Admin GH Validate",
        role: "admin",
        is_active: true,
      },
    });

    render(<AdminPage />);

    const repositoryInput = await screen.findByLabelText("GitHub account/owner");
    const defaultBranchInput = screen.getByLabelText("Default Branch");
    const basePathInput = screen.getByLabelText("Base Path");
    const enabledToggle = screen.getByLabelText("Enable migration GitHub publish target");

    fireEvent.click(enabledToggle);
    fireEvent.change(repositoryInput, { target: { value: "invalid repo" } });
    fireEvent.change(defaultBranchInput, { target: { value: " " } });
    fireEvent.change(basePathInput, { target: { value: "../bad" } });

    expect(
      screen.getByText("GitHub owner is invalid (for example: mhanson13)."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Default branch is required when GitHub publishing is enabled."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Base path is invalid. Use '/' or '/subpath' with letters, numbers, -, _, ., and /."),
    ).toBeInTheDocument();
    expect(screen.getByText("Resolve validation issues above before saving.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save GitHub Publish Config" })).toBeDisabled();
    expect(mockUpdateGitHubPublishConfig).not.toHaveBeenCalled();
  });

  it("allows above-cap requested migration values and shows backend effective capped values", async () => {
    mockUpdateGitHubPublishConfig.mockResolvedValueOnce({
      id: 1,
      owner: "mhanson13",
      repository: "mhanson13",
      default_branch: "main",
      base_path: "/site",
      deploy_workflow_mode: "site_repo_template_v1",
      target_environment_key: "gke_prod",
      target_environment_source: "admin_config",
      github_repository_auto_create_enabled: true,
      managed_gke_cluster_name: "mbsrn-cluster",
      managed_gke_cluster_location: "us-central1",
      managed_gke_project_id: "mbsrn-prod",
      namespace_isolation_defaults: {
        resource_quota: {
          enabled: false,
          requests_cpu: "1000m",
          requests_memory: "1Gi",
          limits_cpu: "2000m",
          limits_memory: "2Gi",
          pods: 20,
          services: 10,
          configmaps: 40,
          secrets: 40,
          persistentvolumeclaims: 10,
        },
        limit_range: {
          enabled: false,
          default_cpu: "500m",
          default_memory: "512Mi",
          default_request_cpu: "250m",
          default_request_memory: "256Mi",
          min_cpu: "100m",
          min_memory: "128Mi",
          max_cpu: "2000m",
          max_memory: "2Gi",
        },
        network_policy: {
          enabled: false,
          mode: "default_deny_ingress",
        },
        managed_preview_endpoint: {
          mode: "auto",
          shared_preview_static_ip_name: null,
        },
        migration_generation_budget: {
          ...DEFAULT_MIGRATION_GENERATION_BUDGET,
          migration_media_asset_limit: 30,
        },
        migration_generation_safety: {
          ...DEFAULT_MIGRATION_GENERATION_SAFETY,
          migration_provider_timeout_seconds: 6000,
          migration_max_final_input_chars: 22000,
          migration_max_difficulty_score: 25,
        },
      },
      namespace_isolation_effective_defaults: {
        resource_quota: {
          enabled: false,
          requests_cpu: "1000m",
          requests_memory: "1Gi",
          limits_cpu: "2000m",
          limits_memory: "2Gi",
          pods: 20,
          services: 10,
          configmaps: 40,
          secrets: 40,
          persistentvolumeclaims: 10,
        },
        limit_range: {
          enabled: false,
          default_cpu: "500m",
          default_memory: "512Mi",
          default_request_cpu: "250m",
          default_request_memory: "256Mi",
          min_cpu: "100m",
          min_memory: "128Mi",
          max_cpu: "2000m",
          max_memory: "2Gi",
        },
        network_policy: {
          enabled: false,
          mode: "default_deny_ingress",
        },
        managed_preview_endpoint: {
          mode: "auto",
          shared_preview_static_ip_name: null,
        },
        migration_generation_budget: {
          ...DEFAULT_MIGRATION_GENERATION_BUDGET,
          migration_media_asset_limit: 24,
        },
        migration_generation_safety: {
          ...DEFAULT_MIGRATION_GENERATION_SAFETY,
          migration_provider_timeout_seconds: 600,
          migration_max_final_input_chars: 22000,
          migration_max_difficulty_score: 24,
        },
      },
      namespace_isolation_cap_reasons: {
        "migration_generation_budget.migration_media_asset_limit":
          "migration_generation_budget.migration_media_asset_limit requested 30 exceeds hard cap 24; effective value 24 is used.",
        "migration_generation_safety.migration_provider_timeout_seconds":
          "migration_generation_safety.migration_provider_timeout_seconds requested 6000 exceeds hard cap 600; effective value 600 is used.",
        "migration_generation_safety.migration_max_difficulty_score":
          "migration_generation_safety.migration_max_difficulty_score requested 25 exceeds hard cap 24; effective value 24 is used.",
      },
      enabled: true,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    });
    mockUseAuth.mockReturnValue({
      principal: {
        business_id: "biz-1",
        principal_id: "admin-migration-ranges",
        display_name: "Admin Migration Ranges",
        role: "admin",
        is_active: true,
      },
    });

    render(<AdminPage />);

    await screen.findByLabelText("GitHub account/owner");
    const providerTimeoutInput = screen.getByLabelText("Provider timeout seconds");
    const maxFinalInput = screen.getByLabelText("Max final input chars");
    const maxDifficultyInput = screen.getByLabelText("Max difficulty score");
    expect(providerTimeoutInput).not.toHaveAttribute("max");
    expect(maxFinalInput).not.toHaveAttribute("max");
    expect(maxDifficultyInput).not.toHaveAttribute("max");

    fireEvent.change(providerTimeoutInput, { target: { value: "6000" } });
    fireEvent.change(maxFinalInput, { target: { value: "22000" } });
    fireEvent.change(maxDifficultyInput, { target: { value: "25" } });
    expect(providerTimeoutInput).toHaveValue(6000);
    expect(maxFinalInput).toHaveValue(22000);
    expect(maxDifficultyInput).toHaveValue(25);

    fireEvent.click(screen.getByRole("button", { name: "Save GitHub Publish Config" }));

    await waitFor(() => {
      expect(mockUpdateGitHubPublishConfig).toHaveBeenCalled();
    });
    const payload = mockUpdateGitHubPublishConfig.mock.calls.at(-1)?.[1];
    expect(payload.namespace_isolation_defaults.migration_generation_safety.migration_provider_timeout_seconds).toBe(
      6000,
    );
    expect(payload.namespace_isolation_defaults.migration_generation_safety.migration_max_final_input_chars).toBe(
      22000,
    );
    expect(payload.namespace_isolation_defaults.migration_generation_safety.migration_max_difficulty_score).toBe(25);
    expect(await screen.findByText("GitHub publish configuration saved.")).toBeInTheDocument();
    expect(screen.queryByText("Failed to save GitHub publish configuration.")).not.toBeInTheDocument();
    const preview = screen.getByTestId("github-publish-effective-preview");
    expect(preview).toHaveTextContent("6000s / 600s / Yes");
    expect(preview).toHaveTextContent("25 / 24 / Yes");
    expect(preview).toHaveTextContent("migration_generation_safety.migration_provider_timeout_seconds requested 6000 exceeds hard cap 600");
  });

  it("shows requested/effective/capped migration preview values", async () => {
    mockUseAuth.mockReturnValue({
      principal: {
        business_id: "biz-1",
        principal_id: "admin-migration-preview",
        display_name: "Admin Migration Preview",
        role: "admin",
        is_active: true,
      },
    });

    render(<AdminPage />);

    await screen.findByLabelText("GitHub account/owner");
    const preview = screen.getByTestId("github-publish-effective-preview");
    expect(preview).toHaveTextContent("300s / 300s / No");

    fireEvent.change(screen.getByLabelText("Provider timeout seconds"), { target: { value: "420" } });
    expect(preview).toHaveTextContent("420s / 300s / Yes");
    expect(preview).toHaveTextContent("Differences before save indicate pending edits.");
  });

  it.each([
    [
      "labels verification",
      buildStaticIpDeleteResource(),
      "Verified by labels.",
      "static_ip_delete_ownership_verified",
    ],
    [
      "DNS/name fallback verification",
      buildStaticIpDeleteResource({
        ownershipMethod: "dns_fallback",
      }),
      "Verified by DNS/name fallback.",
      "static_ip_delete_ownership_verified",
    ],
    [
      "unverified ownership",
      buildStaticIpDeleteResource({
        status: "blocked",
        reasonCode: "static_ip_delete_skipped_unverified_ownership",
        summary: "MBSRN could not prove that this static IP is managed by the selected site.",
        ownershipStatus: "unverified",
        ownershipMethod: "none",
      }),
      "Skipped: ownership unverified.",
      "static_ip_delete_skipped_unverified_ownership",
    ],
    [
      "shared preview gateway",
      buildStaticIpDeleteResource({
        status: "blocked",
        reasonCode: "static_ip_delete_skipped_shared_gateway",
        summary: "This static IP is configured as a shared preview gateway IP.",
        ownershipStatus: "shared",
        ownershipMethod: "none",
      }),
      "Skipped: shared preview gateway.",
      "static_ip_delete_skipped_shared_gateway",
    ],
    [
      "IP in use",
      buildStaticIpDeleteResource({
        status: "blocked",
        reasonCode: "static_ip_delete_skipped_in_use",
        summary: "This static IP is still in use by Google Cloud resources.",
        ownershipStatus: "in_use",
        ownershipMethod: "none",
      }),
      "Skipped: IP is in use.",
      "static_ip_delete_skipped_in_use",
    ],
    [
      "conflicting references",
      buildStaticIpDeleteResource({
        status: "blocked",
        reasonCode: "static_ip_delete_skipped_conflicting_reference",
        summary: "Another site configuration references this static IP or preview hostname.",
        ownershipStatus: "conflicting_reference",
        ownershipMethod: "none",
      }),
      "Skipped: referenced by another site/config.",
      "static_ip_delete_skipped_conflicting_reference",
    ],
    [
      "missing static IP",
      buildStaticIpDeleteResource({
        status: "not_found",
        reasonCode: null,
        summary: "No managed preview static IP was found for the expected project/name.",
        ownershipStatus: "not_found",
        ownershipMethod: "none",
      }),
      "Not found.",
      null,
    ],
  ])(
    "renders concise static-IP delete-plan diagnostics for %s",
    async (_label, staticIpResource, expectedCopy, expectedReasonCode) => {
      setAdminSiteDeleteContext();
      mockPrepareAdminSiteDeletePlan.mockResolvedValue(buildAdminSiteDeletePlan(staticIpResource));

      render(<AdminPage />);

      await screen.findByLabelText("GitHub account/owner");
      fireEvent.click(screen.getByRole("button", { name: "Prepare delete plan" }));

      await waitFor(() => {
        expect(mockPrepareAdminSiteDeletePlan).toHaveBeenCalledWith("token-1", "biz-1", "site-1");
      });
      expect(await screen.findByRole("heading", { name: "Permanent delete plan" })).toBeInTheDocument();
      expect(screen.getAllByText(expectedCopy).length).toBeGreaterThanOrEqual(1);
      expect(screen.getByText("Static IP verification")).toBeInTheDocument();
      expect(screen.getByTestId("admin-site-delete-diagnostics")).toHaveTextContent(
        `"static_ip_ownership_status": "${staticIpResource.static_ip_ownership_status}"`,
      );
      if (expectedReasonCode) {
        expect(screen.getByTestId("admin-site-delete-diagnostics")).toHaveTextContent(expectedReasonCode);
      }
    },
  );

  it("preserves delete execution confirmation flow and renders static-IP failure diagnostics", async () => {
    setAdminSiteDeleteContext();
    const plan = buildAdminSiteDeletePlan(buildStaticIpDeleteResource());
    mockPrepareAdminSiteDeletePlan.mockResolvedValue(plan);
    mockExecuteAdminSiteDelete.mockResolvedValue(
      buildAdminSiteDeleteResult(
        buildStaticIpDeleteResource({
          status: "failed",
          reasonCode: "static_ip_delete_failed",
          summary: "Managed preview static IP deletion request failed.",
          deleteAttempted: true,
          deleteSelected: true,
        }),
        {
          external_cleanup_partial: true,
        },
      ),
    );

    render(<AdminPage />);

    await screen.findByLabelText("GitHub account/owner");
    fireEvent.click(screen.getByRole("button", { name: "Prepare delete plan" }));
    expect(await screen.findByRole("heading", { name: "Permanent delete plan" })).toBeInTheDocument();

    const executeButton = screen.getByRole("button", { name: "Execute permanent delete" });
    expect(executeButton).toBeDisabled();

    fireEvent.change(screen.getByLabelText("Confirmation phrase"), {
      target: { value: plan.required_confirmation_phrase },
    });
    fireEvent.click(
      screen.getByLabelText(/database records for this site will be permanently deleted/i),
    );
    expect(executeButton).toBeEnabled();

    fireEvent.click(
      screen.getByLabelText(/Delete verified managed DNS, static IP, and certificate resources/i),
    );
    expect(executeButton).toBeDisabled();

    fireEvent.click(
      screen.getByLabelText(/DNS\/static IP\/certificate cleanup affects public preview routing and TLS/i),
    );
    expect(executeButton).toBeEnabled();

    fireEvent.click(executeButton);

    await waitFor(() => {
      expect(mockExecuteAdminSiteDelete).toHaveBeenCalledWith(
        "token-1",
        "biz-1",
        "site-1",
        expect.objectContaining({
          confirmation_phrase: plan.required_confirmation_phrase,
          acknowledge_delete_database_records: true,
          delete_dns_resources: true,
          acknowledge_delete_dns_resources: true,
        }),
      );
    });
    expect(await screen.findByText(/Delete failed after label verification\./)).toBeInTheDocument();
    expect(screen.getByTestId("admin-site-delete-diagnostics")).toHaveTextContent("static_ip_delete_failed");
  });

  it("keeps /users as a compatibility route", async () => {
    mockUseAuth.mockReturnValue({
      principal: {
        business_id: "biz-1",
        principal_id: "admin-2",
        display_name: "Admin Two",
        role: "admin",
        is_active: true,
      },
    });
    render(<UsersCompatibilityPage />);
    expect(screen.getByRole("heading", { name: "Admin Overview" })).toBeInTheDocument();
    await waitFor(() => {
      expect(mockFetchPrincipals).toHaveBeenCalled();
      expect(mockFetchPrincipalIdentities).toHaveBeenCalled();
    });
  });
});
