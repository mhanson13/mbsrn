"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import { useAuth } from "../../components/AuthProvider";
import { FormContainer } from "../../components/layout/FormContainer";
import { PageContainer } from "../../components/layout/PageContainer";
import { SectionCard } from "../../components/layout/SectionCard";
import { SectionHeader } from "../../components/layout/SectionHeader";
import { SummaryStatCard } from "../../components/layout/SummaryStatCard";
import { WorkspaceMetadataGrid, WorkspaceMetadataItem } from "../../components/layout/WorkspaceMetadataGrid";
import { useOperatorContext } from "../../components/useOperatorContext";
import {
  AdminDiagnosticsLogsSection,
  AdminOverviewSection,
  AdminSectionNav,
  AiPromptGovernanceSection,
  AuditCrawlSettingsSection,
  CompetitorGenerationSettingsSection,
  ManagedNamespacePolicySection,
  PublishDeploymentConfigSection,
  SiteRegistryManagementSection,
} from "./components/AdminSections";
import {
  activatePrincipalIdentity,
  activatePrincipal,
  ApiRequestError,
  createPrincipalIdentity,
  createPrincipal,
  executeAdminSiteDelete,
  deactivatePrincipalIdentity,
  deactivatePrincipal,
  fetchBusinessSettings,
  fetchGitHubPublishConfig,
  fetchPrincipalIdentities,
  fetchPrincipals,
  prepareAdminSiteDeletePlan,
  queryGcpLogs,
  updateAdminSite,
  updateBusinessSettings,
  updateGitHubPublishConfig,
} from "../../lib/api/client";
import type {
  BusinessSettings,
  GCPLogEntry,
  GitHubPublishConfig,
  GitHubPublishConfigUpdateRequest,
  MigrationGenerationBudgetConfig,
  MigrationGenerationSafetyConfig,
  GitHubNamespaceIsolationDefaults,
  GitHubNamespaceLimitRangeDefaults,
  GitHubNamespaceNetworkPolicyDefaults,
  GitHubNamespaceResourceQuotaDefaults,
  Principal,
  PrincipalIdentity,
  PrincipalRole,
  SEOSite,
  SEOSiteDeleteExecuteRequest,
  SEOSiteDeleteExecutionResult,
  SEOSiteDeletePlan,
} from "../../lib/api/types";
import {
  COMPETITOR_BIG_BOX_PENALTY_MAX,
  COMPETITOR_BIG_BOX_PENALTY_MIN,
  COMPETITOR_DIRECTORY_PENALTY_MAX,
  COMPETITOR_DIRECTORY_PENALTY_MIN,
  COMPETITOR_LOCAL_ALIGNMENT_BONUS_MAX,
  COMPETITOR_LOCAL_ALIGNMENT_BONUS_MIN,
  COMPETITOR_MIN_RELEVANCE_SCORE_MAX,
  COMPETITOR_MIN_RELEVANCE_SCORE_MIN,
  COMPETITOR_TIMEOUT_SECONDS_MAX,
  COMPETITOR_TIMEOUT_SECONDS_MIN,
  CRAWL_PAGE_LIMIT_MAX,
  CRAWL_PAGE_LIMIT_MIN,
  DEFAULT_COMPETITOR_TIMEOUT_SECONDS,
  DEFAULT_CRAWL_PAGE_LIMIT,
  NOTIFICATION_EMAIL_REGEX,
  NOTIFICATION_PHONE_E164_REGEX,
} from "../../lib/validation/constants";

interface AdminPageLoadResult {
  users: Principal[];
  identities: PrincipalIdentity[];
  identityWarning: string | null;
}

type SettingsSectionHealthStatus = "valid" | "invalid";

interface SettingsSectionHealth {
  status: SettingsSectionHealthStatus;
  message: string | null;
}

interface SettingsHealthSummary {
  crawl: SettingsSectionHealth;
  competitorQuality: SettingsSectionHealth;
  competitorTimeouts: SettingsSectionHealth;
  notifications: SettingsSectionHealth;
}

const GCP_LOGS_PAGE_SIZE_DEFAULT = 25;
const GCP_LOGS_PAGE_SIZE_OPTIONS = [10, 25, 50, 100] as const;
const GCP_LOGS_DEFAULT_TIME_WINDOW_LABEL = "last 24 hours";
const GCP_LOGS_SAMPLE_FILTER =
  'severity="ERROR" resource.labels.namespace_name="mbsrn" -textPayload =~ "INFO*"';
const GITHUB_OWNER_PATTERN = /^[A-Za-z0-9][A-Za-z0-9-]{0,38}$/;
const GITHUB_BRANCH_PATTERN = /^[A-Za-z0-9._/-]{1,120}$/;
const GITHUB_BASE_PATH_PATTERN = /^\/[A-Za-z0-9._/-]{0,159}$/;
const GITHUB_TARGET_ENVIRONMENT_KEY_PATTERN = /^[a-z0-9][a-z0-9_-]{0,79}$/;
const GITHUB_DEPLOY_WORKFLOW_MODE_OPTIONS = ["site_repo_template_v1"] as const;
const GITHUB_GKE_CLUSTER_NAME_PATTERN = /^[a-z0-9][a-z0-9-]{0,118}$/;
const GITHUB_GKE_CLUSTER_LOCATION_PATTERN = /^[a-z0-9][a-z0-9-]{0,118}$/;
const GITHUB_GKE_PROJECT_ID_PATTERN = /^[a-z][a-z0-9-]{4,28}[a-z0-9]$/;
const GITHUB_NAMESPACE_CPU_PATTERN = /^(?:[1-9]\d*m|[1-9]\d*(?:\.\d+)?)$/;
const GITHUB_NAMESPACE_MEMORY_PATTERN = /^(?:[1-9]\d*(?:Ei|Pi|Ti|Gi|Mi|Ki)|[1-9]\d*(?:\.\d+)?(?:E|P|T|G|M|K)i?)$/;
const GITHUB_NAMESPACE_COUNT_PATTERN = /^\d{1,6}$/;
const GITHUB_NETWORK_POLICY_MODE_OPTIONS = ["default_deny_ingress"] as const;
const GITHUB_MANAGED_PREVIEW_ENDPOINT_MODE_OPTIONS = [
  "auto",
  "preview_shared_gateway",
  "dedicated_static_ip",
] as const;
const MIGRATION_GENERATION_DEPTH_OPTIONS = ["compact", "standard", "expanded"] as const;
const MIGRATION_VARIATION_LEVEL_OPTIONS = ["conservative", "balanced", "differentiated"] as const;
const MIGRATION_PREFLIGHT_MODE_OPTIONS = ["compact_fallback", "block_before_provider"] as const;
const MIGRATION_CONTEXT_BUDGET_BOUNDS = { min: 8000, max: 150000 } as const;
const MIGRATION_RECOMMENDATION_LIMIT_BOUNDS = { min: 1, max: 24 } as const;
const MIGRATION_COMPETITOR_LIMIT_BOUNDS = { min: 1, max: 24 } as const;
const MIGRATION_SOURCE_PAGE_SUMMARY_LIMIT_BOUNDS = { min: 3, max: 16 } as const;
const MIGRATION_MEDIA_ASSET_LIMIT_BOUNDS = { min: 4, max: 24 } as const;
const MIGRATION_GENERATED_PAGE_LIMIT_BOUNDS = { min: 4, max: 30 } as const;
const MIGRATION_GENERATED_FILE_LIMIT_BOUNDS = { min: 4, max: 24 } as const;
const MIGRATION_PROVIDER_TIMEOUT_BOUNDS = { min: 60, max: 600 } as const;
const MIGRATION_MAX_FINAL_INPUT_CHARS_BOUNDS = { min: 3000, max: 64000 } as const;
const MIGRATION_MAX_DIFFICULTY_SCORE_BOUNDS = { min: 5, max: 24 } as const;
const MIGRATION_COMPACT_PAGE_LIMIT_BOUNDS = { min: 1, max: 10 } as const;
const MIGRATION_COMPACT_MEDIA_LIMIT_BOUNDS = { min: 0, max: 8 } as const;
const MIGRATION_COMPACT_RECOMMENDATION_LIMIT_BOUNDS = { min: 0, max: 12 } as const;
const MIGRATION_CONTEXT_BUDGET_RECOMMENDED = { min: 45000, max: 100000 } as const;
const MIGRATION_RECOMMENDATION_LIMIT_RECOMMENDED = { min: 6, max: 12 } as const;
const MIGRATION_COMPETITOR_LIMIT_RECOMMENDED = { min: 6, max: 14 } as const;
const MIGRATION_MAX_FINAL_INPUT_CHARS_RECOMMENDED = { min: 16000, max: 32000 } as const;
const MIGRATION_MAX_DIFFICULTY_SCORE_RECOMMENDED = { min: 10, max: 18 } as const;
const MIGRATION_COMPACT_PAGE_LIMIT_RECOMMENDED = { min: 4, max: 7 } as const;
const MIGRATION_COMPACT_MEDIA_LIMIT_RECOMMENDED = { min: 3, max: 6 } as const;
const MIGRATION_COMPACT_RECOMMENDATION_LIMIT_RECOMMENDED = { min: 5, max: 8 } as const;

type MigrationGenerationBudgetNumericField =
  | "migration_context_budget_chars"
  | "migration_recommendation_limit"
  | "migration_competitor_limit"
  | "migration_source_page_summary_limit"
  | "migration_media_asset_limit"
  | "migration_generated_page_limit"
  | "migration_generated_file_limit";

type MigrationGenerationSafetyNumericField =
  | "migration_provider_timeout_seconds"
  | "migration_max_final_input_chars"
  | "migration_max_difficulty_score"
  | "migration_compact_page_limit"
  | "migration_compact_media_asset_limit"
  | "migration_compact_recommendation_limit";

type MigrationGenerationSettingField =
  | MigrationGenerationBudgetNumericField
  | MigrationGenerationSafetyNumericField;

type MigrationGenerationFieldErrorMap = Partial<Record<MigrationGenerationSettingField, string>>;
const DEFAULT_MIGRATION_GENERATION_BUDGET: MigrationGenerationBudgetConfig = {
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
const DEFAULT_MIGRATION_GENERATION_SAFETY: MigrationGenerationSafetyConfig = {
  migration_provider_timeout_seconds: 300,
  migration_preflight_mode: "compact_fallback",
  migration_max_final_input_chars: 32000,
  migration_max_difficulty_score: 18,
  migration_compact_fallback_enabled: true,
  migration_compact_page_limit: 6,
  migration_compact_media_asset_limit: 5,
  migration_compact_recommendation_limit: 8,
};
const DEFAULT_NAMESPACE_ISOLATION_DEFAULTS: GitHubNamespaceIsolationDefaults = {
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
  migration_generation_budget: DEFAULT_MIGRATION_GENERATION_BUDGET,
  migration_generation_safety: DEFAULT_MIGRATION_GENERATION_SAFETY,
};

type AdminPageMode = "all" | "admin" | "userMgmt";

interface AdminPageProps {
  mode?: AdminPageMode;
}

interface SiteManagementDraft {
  name: string;
  url: string;
  searchConsolePropertyUrl: string;
  searchConsoleEnabled: boolean;
}

interface SiteDeleteFormState {
  confirmationPhrase: string;
  acknowledgeDeleteDatabaseRecords: boolean;
  deleteGitHubRepo: boolean;
  acknowledgeDeleteGitHubRepo: boolean;
  deleteRuntimeResources: boolean;
  acknowledgeDeleteRuntimeResources: boolean;
  deleteDnsResources: boolean;
  acknowledgeDeleteDnsResources: boolean;
  forceDeleteActive: boolean;
}

interface GitHubPublishConfigValidationResult {
  owner: string;
  defaultBranch: string;
  basePath: string;
  deployWorkflowMode: string;
  targetEnvironmentKey: string;
  managedGkeClusterName: string | null;
  managedGkeClusterLocation: string | null;
  managedGkeProjectId: string | null;
  ownerError: string | null;
  defaultBranchError: string | null;
  basePathError: string | null;
  deployWorkflowModeError: string | null;
  targetEnvironmentKeyError: string | null;
  managedGkeClusterNameError: string | null;
  managedGkeClusterLocationError: string | null;
  managedGkeProjectIdError: string | null;
  basePathWarning: string | null;
  namespaceIsolationErrors: string[];
  blockingError: string | null;
}

type CompetitorPromptContractWarningState = "none" | "legacy_alias" | "invalid";

interface CompetitorPromptContractWarning {
  state: CompetitorPromptContractWarningState;
  message: string | null;
}

interface AdminHelpIconProps {
  label: string;
  helpText: string;
  testId?: string;
}

function AdminHelpIcon({ label, helpText, testId }: AdminHelpIconProps): JSX.Element {
  return (
    <span className="admin-help-wrapper">
      <span
        className="admin-help-trigger"
        role="button"
        tabIndex={0}
        aria-label="Setting help"
        data-help-text={helpText}
        data-testid={testId}
      />
    </span>
  );
}

interface AdminLabelWithHelpProps {
  label: string;
  helpText?: string;
  muted?: boolean;
  testId?: string;
}

function AdminLabelWithHelp({ label, helpText, muted = false, testId }: AdminLabelWithHelpProps): JSX.Element {
  return (
    <span className="admin-field-label-row">
      <span className={muted ? "hint muted" : undefined}>{label}</span>
      {helpText ? <AdminHelpIcon label={label} helpText={helpText} testId={testId} /> : null}
    </span>
  );
}

function parseBoundedInteger(input: string, bounds: { min: number; max: number }): number | null {
  const normalized = input.trim();
  if (!/^\d+$/.test(normalized)) {
    return null;
  }

  const parsed = Number(normalized);
  if (!Number.isSafeInteger(parsed)) {
    return null;
  }
  if (parsed < bounds.min || parsed > bounds.max) {
    return null;
  }
  return parsed;
}

function promptIncludesField(value: string, fieldName: string): boolean {
  const escaped = fieldName.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const quotedPattern = new RegExp(`["']${escaped}["']`, "i");
  const barePattern = new RegExp(`\\b${escaped}\\b`, "i");
  return quotedPattern.test(value) || barePattern.test(value);
}

function assessCompetitorPromptOverrideContract(promptOverride: string): CompetitorPromptContractWarning {
  const normalized = promptOverride.trim().toLowerCase();
  if (!normalized || !normalized.includes("candidates")) {
    return { state: "none", message: null };
  }

  const hasDomain = promptIncludesField(normalized, "domain");
  const hasBusinessName = promptIncludesField(normalized, "business_name");
  const hasName = promptIncludesField(normalized, "name");
  const hasReasonSelected = promptIncludesField(normalized, "reason_selected");
  const hasReasoning = promptIncludesField(normalized, "reasoning");
  const hasReason = promptIncludesField(normalized, "reason");

  if (!hasDomain || !(hasBusinessName || hasName) || !(hasReasonSelected || hasReasoning || hasReason)) {
    return {
      state: "invalid",
      message:
        "Competitor prompt override appears incompatible with the required output contract. Required fields include business_name, domain, and reason_selected.",
    };
  }

  if ((hasName && !hasBusinessName) || ((hasReasoning || hasReason) && !hasReasonSelected)) {
    return {
      state: "legacy_alias",
      message:
        "Competitor prompt override uses legacy aliases (name/reasoning). Canonical fields are business_name, domain, location_market, service_category_fit, reason_selected, and confidence_score.",
    };
  }

  return { state: "none", message: null };
}

function parseOptionalBoundedInteger(
  input: string,
  bounds: { min: number; max: number },
): number | null | "invalid" {
  const normalized = input.trim();
  if (!normalized) {
    return null;
  }
  const parsed = parseBoundedInteger(normalized, bounds);
  if (parsed === null) {
    return "invalid";
  }
  return parsed;
}

function parseCrawlPageLimit(input: string): number | null {
  return parseBoundedInteger(input, {
    min: CRAWL_PAGE_LIMIT_MIN,
    max: CRAWL_PAGE_LIMIT_MAX,
  });
}

function timeoutSettingToInput(value: number | null): string {
  if (typeof value === "number" && Number.isSafeInteger(value)) {
    return String(value);
  }
  return "";
}

function isBoundedIntegerValue(value: number, bounds: { min: number; max: number }): boolean {
  if (!Number.isSafeInteger(value)) {
    return false;
  }
  return value >= bounds.min && value <= bounds.max;
}

function isValidNotificationPhone(value: string | null): boolean {
  if (!value) {
    return false;
  }
  return NOTIFICATION_PHONE_E164_REGEX.test(value.trim());
}

function isValidNotificationEmail(value: string | null): boolean {
  if (!value) {
    return false;
  }
  return NOTIFICATION_EMAIL_REGEX.test(value.trim());
}

function evaluateSettingsHealth(settings: BusinessSettings | null): SettingsHealthSummary {
  if (!settings) {
    return {
      crawl: { status: "valid", message: null },
      competitorQuality: { status: "valid", message: null },
      competitorTimeouts: { status: "valid", message: null },
      notifications: { status: "valid", message: null },
    };
  }

  const crawlIsValid = isBoundedIntegerValue(settings.seo_audit_crawl_max_pages, {
    min: CRAWL_PAGE_LIMIT_MIN,
    max: CRAWL_PAGE_LIMIT_MAX,
  });

  const competitorQualityIsValid =
    isBoundedIntegerValue(settings.competitor_candidate_min_relevance_score, {
      min: COMPETITOR_MIN_RELEVANCE_SCORE_MIN,
      max: COMPETITOR_MIN_RELEVANCE_SCORE_MAX,
    }) &&
    isBoundedIntegerValue(settings.competitor_candidate_big_box_penalty, {
      min: COMPETITOR_BIG_BOX_PENALTY_MIN,
      max: COMPETITOR_BIG_BOX_PENALTY_MAX,
    }) &&
    isBoundedIntegerValue(settings.competitor_candidate_directory_penalty, {
      min: COMPETITOR_DIRECTORY_PENALTY_MIN,
      max: COMPETITOR_DIRECTORY_PENALTY_MAX,
    }) &&
    isBoundedIntegerValue(settings.competitor_candidate_local_alignment_bonus, {
      min: COMPETITOR_LOCAL_ALIGNMENT_BONUS_MIN,
      max: COMPETITOR_LOCAL_ALIGNMENT_BONUS_MAX,
    });
  const competitorTimeoutsAreValid =
    (settings.competitor_primary_timeout_seconds === null ||
      isBoundedIntegerValue(settings.competitor_primary_timeout_seconds, {
        min: COMPETITOR_TIMEOUT_SECONDS_MIN,
        max: COMPETITOR_TIMEOUT_SECONDS_MAX,
      })) &&
    (settings.competitor_degraded_timeout_seconds === null ||
      isBoundedIntegerValue(settings.competitor_degraded_timeout_seconds, {
        min: COMPETITOR_TIMEOUT_SECONDS_MIN,
        max: COMPETITOR_TIMEOUT_SECONDS_MAX,
      }));

  const smsEnabled = settings.sms_enabled;
  const emailEnabled = settings.email_enabled;
  const smsChannelUsable = smsEnabled && isValidNotificationPhone(settings.notification_phone);
  const emailChannelUsable = emailEnabled && isValidNotificationEmail(settings.notification_email);
  const notificationsAreValid =
    (!smsEnabled || smsChannelUsable) &&
    (!emailEnabled || emailChannelUsable) &&
    (!settings.contractor_alerts_enabled || smsChannelUsable || emailChannelUsable) &&
    (!settings.customer_auto_ack_enabled || smsEnabled || emailEnabled);

  return {
    crawl: {
      status: crawlIsValid ? "valid" : "invalid",
      message: crawlIsValid ? null : "Saved value is outside the allowed range.",
    },
    competitorQuality: {
      status: competitorQualityIsValid ? "valid" : "invalid",
      message: competitorQualityIsValid ? null : "One or more saved values need review.",
    },
    competitorTimeouts: {
      status: competitorTimeoutsAreValid ? "valid" : "invalid",
      message: competitorTimeoutsAreValid ? null : "One or more saved values need review.",
    },
    notifications: {
      status: notificationsAreValid ? "valid" : "invalid",
      message: notificationsAreValid ? null : "One or more saved values need review.",
    },
  };
}

function safeAdminPageErrorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) {
    if (error.status === 401) {
      return "Session expired. Sign in again.";
    }
    if (error.status === 403) {
      return "Business administration is restricted to admin principals.";
    }
    if (error.status === 404) {
      return "Business scope was not found for this session.";
    }
  }
  return "Unable to load admin data right now. Please try again.";
}

function safeCreateUserErrorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) {
    if (error.status === 401) {
      return "Session expired. Sign in again.";
    }
    if (error.status === 403) {
      return "You are not authorized to create users.";
    }
    if (error.status === 422) {
      return "Unable to create user. Check user id, role, and uniqueness.";
    }
  }
  return "Failed to create user.";
}

function safePrincipalActionErrorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) {
    if (error.status === 401) {
      return "Session expired. Sign in again.";
    }
    if (error.status === 403) {
      return "You are not authorized to update users.";
    }
    if (error.status === 404) {
      return "User record not found in this business scope.";
    }
    if (error.status === 422) {
      return "Unable to update this user state. Ensure at least one active admin remains.";
    }
  }
  return "Failed to update user state.";
}

function safeIdentityActionErrorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) {
    if (error.status === 401) {
      return "Session expired. Sign in again.";
    }
    if (error.status === 403) {
      return "You are not authorized to update sign-in identities.";
    }
    if (error.status === 404) {
      return "Sign-in identity not found in this business scope.";
    }
    if (error.status === 422) {
      return "Unable to update sign-in identity state.";
    }
  }
  return "Failed to update sign-in identity state.";
}

function safeCreateIdentityErrorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) {
    if (error.status === 401) {
      return "Session expired. Sign in again.";
    }
    if (error.status === 403) {
      return "You are not authorized to create sign-in identities.";
    }
    if (error.status === 404) {
      return "Principal or business scope was not found.";
    }
    if (error.status === 422) {
      return "Unable to create sign-in identity. Verify provider, subject, and principal mapping.";
    }
  }
  return "Failed to create sign-in identity.";
}

function safeBusinessSettingsErrorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) {
    if (error.status === 401) {
      return "Session expired. Sign in again.";
    }
    if (error.status === 403) {
      return "You are not authorized to view business settings.";
    }
    if (error.status === 404) {
      return "Business settings were not found in this tenant scope.";
    }
  }
  return "Unable to load business settings right now.";
}

function apiErrorMessageContains(error: ApiRequestError, token: string): boolean {
  return error.message.toLowerCase().includes(token.toLowerCase());
}

function apiErrorReasonCode(error: ApiRequestError): string | null {
  const reasonCode = error.detail?.reason_code;
  return typeof reasonCode === "string" && reasonCode.trim() ? reasonCode.trim() : null;
}

function apiErrorFirstIssueMessage(error: ApiRequestError): string | null {
  const collections = [error.detail?.blockers, error.detail?.warnings];
  for (const collection of collections) {
    if (!Array.isArray(collection)) {
      continue;
    }
    for (const item of collection) {
      if (!item || typeof item !== "object") {
        continue;
      }
      const message = (item as Record<string, unknown>).message;
      if (typeof message === "string" && message.trim()) {
        return message.trim();
      }
    }
  }
  return null;
}

function siteDeleteResourceLabel(resourceType: string): string {
  switch (resourceType) {
    case "github_repo":
      return "GitHub repo";
    case "gke_runtime":
      return "GKE/runtime";
    case "dns_record":
      return "DNS record";
    case "static_ip":
      return "Static IP";
    case "managed_certificate":
      return "Managed certificate";
    default:
      return resourceType.replace(/_/g, " ");
  }
}

function siteDeleteStatusLabel(status: string): string {
  switch (status) {
    case "found":
      return "Found";
    case "not_found":
      return "Not found";
    case "not_checked":
      return "Not checked";
    case "blocked":
      return "Blocked";
    case "skipped":
      return "Skipped";
    case "deleted":
      return "Deleted";
    case "failed":
      return "Failed";
    default:
      return status;
  }
}

const EMPTY_SITE_DELETE_FORM_STATE: SiteDeleteFormState = {
  confirmationPhrase: "",
  acknowledgeDeleteDatabaseRecords: false,
  deleteGitHubRepo: false,
  acknowledgeDeleteGitHubRepo: false,
  deleteRuntimeResources: false,
  acknowledgeDeleteRuntimeResources: false,
  deleteDnsResources: false,
  acknowledgeDeleteDnsResources: false,
  forceDeleteActive: false,
};

function safeBusinessSettingsUpdateErrorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) {
    if (error.status === 401) {
      return "Session expired. Sign in again.";
    }
    if (error.status === 403) {
      return "Only admin principals can update crawl settings.";
    }
    if (error.status === 404) {
      return "Business settings were not found in this tenant scope.";
    }
    if (error.status === 422) {
      if (apiErrorMessageContains(error, "seo_audit_crawl_max_pages")) {
        return `Crawl page limit must be between ${CRAWL_PAGE_LIMIT_MIN} and ${CRAWL_PAGE_LIMIT_MAX}.`;
      }
      return "Unable to save SEO crawl settings. Please review the entered crawl limit.";
    }
  }
  return "Failed to update crawl page limit.";
}

function safeCandidateQualitySettingsUpdateErrorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) {
    if (error.status === 401) {
      return "Session expired. Sign in again.";
    }
    if (error.status === 403) {
      return "Only admin principals can update competitor quality tuning.";
    }
    if (error.status === 404) {
      return "Business settings were not found in this tenant scope.";
    }
    if (error.status === 422) {
      // Section-scoped settings saves should map backend validation to the
      // relevant section fields and otherwise use a safe fallback.
      if (apiErrorMessageContains(error, "competitor_candidate_min_relevance_score")) {
        return (
          "Minimum relevance score must be an integer between " +
          `${COMPETITOR_MIN_RELEVANCE_SCORE_MIN} and ${COMPETITOR_MIN_RELEVANCE_SCORE_MAX}.`
        );
      }
      if (apiErrorMessageContains(error, "competitor_candidate_big_box_penalty")) {
        return (
          "Big-box mismatch penalty must be an integer between " +
          `${COMPETITOR_BIG_BOX_PENALTY_MIN} and ${COMPETITOR_BIG_BOX_PENALTY_MAX}.`
        );
      }
      if (apiErrorMessageContains(error, "competitor_candidate_directory_penalty")) {
        return (
          "Directory/aggregator penalty must be an integer between " +
          `${COMPETITOR_DIRECTORY_PENALTY_MIN} and ${COMPETITOR_DIRECTORY_PENALTY_MAX}.`
        );
      }
      if (apiErrorMessageContains(error, "competitor_candidate_local_alignment_bonus")) {
        return (
          "Local alignment bonus must be an integer between " +
          `${COMPETITOR_LOCAL_ALIGNMENT_BONUS_MIN} and ${COMPETITOR_LOCAL_ALIGNMENT_BONUS_MAX}.`
        );
      }
      return "Unable to save this settings section. Please review the entered values.";
    }
  }
  return "Failed to update competitor quality settings.";
}

function safeCompetitorTimeoutSettingsUpdateErrorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) {
    if (error.status === 401) {
      return "Session expired. Sign in again.";
    }
    if (error.status === 403) {
      return "Only admin principals can update competitor generation timeout settings.";
    }
    if (error.status === 404) {
      return "Business settings were not found in this tenant scope.";
    }
    if (error.status === 422) {
      if (apiErrorMessageContains(error, "competitor_primary_timeout_seconds")) {
        return (
          "Primary timeout must be blank or an integer between " +
          `${COMPETITOR_TIMEOUT_SECONDS_MIN} and ${COMPETITOR_TIMEOUT_SECONDS_MAX}.`
        );
      }
      if (apiErrorMessageContains(error, "competitor_degraded_timeout_seconds")) {
        return (
          "Degraded retry timeout must be blank or an integer between " +
          `${COMPETITOR_TIMEOUT_SECONDS_MIN} and ${COMPETITOR_TIMEOUT_SECONDS_MAX}.`
        );
      }
      return "Unable to save competitor timeout settings. Please review the entered values.";
    }
  }
  return "Failed to update competitor timeout settings.";
}

function safePromptSettingsUpdateErrorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) {
    if (error.status === 401) {
      return "Session expired. Sign in again.";
    }
    if (error.status === 403) {
      return "Only admin principals can update AI prompt overrides.";
    }
    if (error.status === 404) {
      return "Business settings were not found in this tenant scope.";
    }
    if (error.status === 422) {
      return "Unable to save AI prompt overrides. Keep each prompt under 20,000 characters.";
    }
  }
  return "Failed to update AI prompt overrides.";
}

function parseAdminSiteUrl(input: string): string {
  const normalized = input.trim();
  let parsed: URL;
  try {
    parsed = new URL(normalized);
  } catch {
    throw new Error("Site URL must be a valid absolute URL.");
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new Error("Site URL must start with http:// or https://.");
  }
  if (!parsed.hostname) {
    throw new Error("Site URL must include a valid domain.");
  }
  return parsed.toString();
}

function safeAdminSiteUpdateErrorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) {
    if (error.status === 401) {
      return "Session expired. Sign in again.";
    }
    if (error.status === 403) {
      return "Only admin principals can edit site name and URL.";
    }
    if (error.status === 404) {
      return "Site not found in this business scope.";
    }
    if (error.status === 422) {
      if (apiErrorMessageContains(error, "search_console_property_url is required when search_console_enabled is true")) {
        return "Search Console property is required when Search Console Enabled is checked.";
      }
      if (apiErrorMessageContains(error, "search_console_property_url")) {
        return "Search Console property must be sc-domain:example.com or https://example.com and must match the configured Search Console property exactly.";
      }
      return "Unable to save site changes. Check name and URL.";
    }
  }
  return "Failed to update site.";
}

function searchConsolePropertyFormatHint(value: string): string | null {
  const normalized = value.trim();
  if (!normalized) {
    return null;
  }

  const lowered = normalized.toLowerCase();
  if (lowered.startsWith("sc-domain:")) {
    const domainPart = normalized.slice("sc-domain:".length).trim();
    if (!domainPart || domainPart.includes("://")) {
      return "Use sc-domain:example.com for domain properties.";
    }
    return null;
  }

  if (lowered.startsWith("http://") || lowered.startsWith("https://")) {
    return null;
  }

  return "Use sc-domain:example.com or https://example.com.";
}

function safeAdminSiteDeleteErrorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) {
    const reasonCode = apiErrorReasonCode(error);
    const issueMessage = apiErrorFirstIssueMessage(error);
    if (error.status === 401) {
      return "Session expired. Sign in again.";
    }
    if (error.status === 403) {
      if (reasonCode === "site_delete_not_authorized") {
        return "Only admin principals can permanently delete sites.";
      }
      return "Only admin principals can permanently delete sites.";
    }
    if (error.status === 404) {
      return "Site not found in this business scope.";
    }
    if (error.status === 409 && reasonCode === "site_delete_active_site_blocked") {
      return issueMessage || "Active sites must be deactivated first or force-deleted with explicit confirmation.";
    }
    if (error.status === 422) {
      if (reasonCode === "site_delete_confirmation_required") {
        return issueMessage || "Prepare a delete plan and complete every delete acknowledgement before executing.";
      }
      if (reasonCode === "site_delete_confirmation_mismatch") {
        return issueMessage || "Confirmation phrase did not match the required permanent delete phrase.";
      }
      if (reasonCode === "github_repo_delete_unmanaged_repo_blocked") {
        return issueMessage || "Configured GitHub repo is not proven MBSRN-managed for this site.";
      }
      if (reasonCode === "github_repo_delete_adoption_required") {
        return issueMessage || "GitHub repo delete is blocked until the repository has an MBSRN management marker.";
      }
      if (reasonCode === "site_delete_foreign_key_blocked") {
        return issueMessage || "Permanent delete was blocked by dependent site records.";
      }
      if (reasonCode === "site_delete_db_failed_after_external_cleanup") {
        return issueMessage || "External cleanup ran, but database deletion failed. Manual remediation is required.";
      }
      if (reasonCode === "site_delete_transaction_failed") {
        return issueMessage || "Permanent delete failed before the database transaction completed.";
      }
      return issueMessage || "Permanent delete failed.";
    }
  }
  return "Failed to permanently delete site.";
}

function safeGcpLogsQueryErrorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) {
    if (error.status === 401) {
      return "Session expired. Sign in again.";
    }
    if (error.status === 403) {
      return "Only admin principals can query Cloud Logging.";
    }
    if (error.status === 422) {
      return "Invalid Cloud Logging filter, page size, or time range.";
    }
    if (error.status === 504) {
      return "Cloud Logging query timed out. Narrow the filter and try again.";
    }
    if (error.status === 502) {
      return "Cloud Logging API query failed. Verify runtime service-account permissions and retry.";
    }
    if (error.status === 503) {
      return error.message || "Cloud Logging query is not configured in this environment.";
    }
  }
  return "Cloud Logging query failed.";
}

function normalizePromptOverrideInput(value: string): string | null {
  const normalized = value.trim();
  if (!normalized) {
    return null;
  }
  return normalized;
}

function normalizeDefaultModelInput(value: string): string | null {
  const normalized = value.trim();
  if (!normalized) {
    return null;
  }
  return normalized;
}

function normalizeGitHubPublishBasePath(value: string): string {
  let normalized = value.trim();
  if (!normalized) {
    return "/";
  }
  normalized = normalized.replace(/\\/g, "/");
  if (!normalized.startsWith("/")) {
    normalized = `/${normalized}`;
  }
  normalized = normalized.replace(/\/{2,}/g, "/");
  if (normalized.length > 1 && normalized.endsWith("/")) {
    normalized = normalized.replace(/\/+$/g, "");
  }
  return normalized || "/";
}

function normalizeNamespaceCount(value: unknown, fallback: number): number {
  if (typeof value === "number" && Number.isSafeInteger(value) && value >= 0 && value <= 999_999) {
    return value;
  }
  const normalized = String(value ?? "").trim();
  if (normalized && /^\d+$/.test(normalized)) {
    const parsed = Number(normalized);
    if (Number.isSafeInteger(parsed) && parsed >= 0 && parsed <= 999_999) {
      return parsed;
    }
  }
  return fallback;
}

function normalizeMigrationBudgetCount(
  value: unknown,
  fallback: number,
  _bounds?: { min: number; max: number },
): number {
  const parsed =
    typeof value === "number" && Number.isSafeInteger(value)
      ? value
      : Number.parseInt(String(value ?? "").trim(), 10);
  if (!Number.isFinite(parsed) || !Number.isSafeInteger(parsed)) {
    return fallback;
  }
  return parsed;
}

function migrationSettingBoundsForField(field: MigrationGenerationSettingField): { min: number; max: number } {
  switch (field) {
    case "migration_context_budget_chars":
      return MIGRATION_CONTEXT_BUDGET_BOUNDS;
    case "migration_recommendation_limit":
      return MIGRATION_RECOMMENDATION_LIMIT_BOUNDS;
    case "migration_competitor_limit":
      return MIGRATION_COMPETITOR_LIMIT_BOUNDS;
    case "migration_source_page_summary_limit":
      return MIGRATION_SOURCE_PAGE_SUMMARY_LIMIT_BOUNDS;
    case "migration_media_asset_limit":
      return MIGRATION_MEDIA_ASSET_LIMIT_BOUNDS;
    case "migration_generated_page_limit":
      return MIGRATION_GENERATED_PAGE_LIMIT_BOUNDS;
    case "migration_generated_file_limit":
      return MIGRATION_GENERATED_FILE_LIMIT_BOUNDS;
    case "migration_provider_timeout_seconds":
      return MIGRATION_PROVIDER_TIMEOUT_BOUNDS;
    case "migration_max_final_input_chars":
      return MIGRATION_MAX_FINAL_INPUT_CHARS_BOUNDS;
    case "migration_max_difficulty_score":
      return MIGRATION_MAX_DIFFICULTY_SCORE_BOUNDS;
    case "migration_compact_page_limit":
      return MIGRATION_COMPACT_PAGE_LIMIT_BOUNDS;
    case "migration_compact_media_asset_limit":
      return MIGRATION_COMPACT_MEDIA_LIMIT_BOUNDS;
    case "migration_compact_recommendation_limit":
      return MIGRATION_COMPACT_RECOMMENDATION_LIMIT_BOUNDS;
    default:
      return { min: 0, max: 0 };
  }
}

function migrationSettingLabel(field: MigrationGenerationSettingField): string {
  switch (field) {
    case "migration_context_budget_chars":
      return "Context budget (chars)";
    case "migration_recommendation_limit":
      return "Recommendation limit";
    case "migration_competitor_limit":
      return "Competitor limit";
    case "migration_source_page_summary_limit":
      return "Source page summary limit";
    case "migration_media_asset_limit":
      return "Media asset context limit";
    case "migration_generated_page_limit":
      return "Generated page limit";
    case "migration_generated_file_limit":
      return "Generated file limit";
    case "migration_provider_timeout_seconds":
      return "Provider timeout seconds";
    case "migration_max_final_input_chars":
      return "Max final input chars";
    case "migration_max_difficulty_score":
      return "Max difficulty score";
    case "migration_compact_page_limit":
      return "Compact page limit";
    case "migration_compact_media_asset_limit":
      return "Compact media limit";
    case "migration_compact_recommendation_limit":
      return "Compact recommendation limit";
    default:
      return field;
  }
}

function migrationSettingValidationMessage(
  field: MigrationGenerationSettingField,
  attemptedValue: number,
): string {
  const bounds = migrationSettingBoundsForField(field);
  return (
    `${migrationSettingLabel(field)} attempted value ${attemptedValue} is outside the backend-allowed range ` +
    `${bounds.min}-${bounds.max}. Save was rejected by backend validation.`
  );
}

function normalizeNamespaceIsolationDefaults(
  value: GitHubNamespaceIsolationDefaults | null | undefined,
): GitHubNamespaceIsolationDefaults {
  const defaults = DEFAULT_NAMESPACE_ISOLATION_DEFAULTS;
  const source = value || defaults;
  return {
    resource_quota: {
      enabled: Boolean(source.resource_quota?.enabled),
      requests_cpu: (source.resource_quota?.requests_cpu || defaults.resource_quota.requests_cpu).trim(),
      requests_memory: (source.resource_quota?.requests_memory || defaults.resource_quota.requests_memory).trim(),
      limits_cpu: (source.resource_quota?.limits_cpu || defaults.resource_quota.limits_cpu).trim(),
      limits_memory: (source.resource_quota?.limits_memory || defaults.resource_quota.limits_memory).trim(),
      pods: normalizeNamespaceCount(source.resource_quota?.pods, defaults.resource_quota.pods),
      services: normalizeNamespaceCount(source.resource_quota?.services, defaults.resource_quota.services),
      configmaps: normalizeNamespaceCount(source.resource_quota?.configmaps, defaults.resource_quota.configmaps),
      secrets: normalizeNamespaceCount(source.resource_quota?.secrets, defaults.resource_quota.secrets),
      persistentvolumeclaims: normalizeNamespaceCount(
        source.resource_quota?.persistentvolumeclaims,
        defaults.resource_quota.persistentvolumeclaims,
      ),
    },
    limit_range: {
      enabled: Boolean(source.limit_range?.enabled),
      default_cpu: (source.limit_range?.default_cpu || defaults.limit_range.default_cpu).trim(),
      default_memory: (source.limit_range?.default_memory || defaults.limit_range.default_memory).trim(),
      default_request_cpu: (
        source.limit_range?.default_request_cpu || defaults.limit_range.default_request_cpu
      ).trim(),
      default_request_memory: (
        source.limit_range?.default_request_memory || defaults.limit_range.default_request_memory
      ).trim(),
      min_cpu: (source.limit_range?.min_cpu || defaults.limit_range.min_cpu).trim(),
      min_memory: (source.limit_range?.min_memory || defaults.limit_range.min_memory).trim(),
      max_cpu: (source.limit_range?.max_cpu || defaults.limit_range.max_cpu).trim(),
      max_memory: (source.limit_range?.max_memory || defaults.limit_range.max_memory).trim(),
    },
    network_policy: {
      enabled: Boolean(source.network_policy?.enabled),
      mode: (
        source.network_policy?.mode ||
        defaults.network_policy.mode
      ).trim().toLowerCase(),
    },
    managed_preview_endpoint: {
      mode: (() => {
        const requestedMode = (
          source.managed_preview_endpoint?.mode ||
          defaults.managed_preview_endpoint.mode
        ).trim().toLowerCase();
        if (
          GITHUB_MANAGED_PREVIEW_ENDPOINT_MODE_OPTIONS.includes(
            requestedMode as (typeof GITHUB_MANAGED_PREVIEW_ENDPOINT_MODE_OPTIONS)[number],
          )
        ) {
          return requestedMode;
        }
        return defaults.managed_preview_endpoint.mode;
      })(),
      shared_preview_static_ip_name: (() => {
        const rawValue = source.managed_preview_endpoint?.shared_preview_static_ip_name;
        if (typeof rawValue !== "string") {
          return null;
        }
        let normalized = rawValue.trim().toLowerCase();
        if (!normalized) {
          return null;
        }
        normalized = normalized.replace(/[^a-z0-9-]+/g, "-");
        normalized = normalized.replace(/--+/g, "-").replace(/^-+|-+$/g, "");
        if (!normalized) {
          return null;
        }
        return normalized.slice(0, 80);
      })(),
    },
    migration_generation_budget: {
      migration_context_budget_chars: normalizeMigrationBudgetCount(
        source.migration_generation_budget?.migration_context_budget_chars,
        defaults.migration_generation_budget.migration_context_budget_chars,
        MIGRATION_CONTEXT_BUDGET_BOUNDS,
      ),
      migration_recommendation_limit: normalizeMigrationBudgetCount(
        source.migration_generation_budget?.migration_recommendation_limit,
        defaults.migration_generation_budget.migration_recommendation_limit,
        MIGRATION_RECOMMENDATION_LIMIT_BOUNDS,
      ),
      migration_competitor_limit: normalizeMigrationBudgetCount(
        source.migration_generation_budget?.migration_competitor_limit,
        defaults.migration_generation_budget.migration_competitor_limit,
        MIGRATION_COMPETITOR_LIMIT_BOUNDS,
      ),
      migration_source_page_summary_limit: normalizeMigrationBudgetCount(
        source.migration_generation_budget?.migration_source_page_summary_limit,
        defaults.migration_generation_budget.migration_source_page_summary_limit,
        MIGRATION_SOURCE_PAGE_SUMMARY_LIMIT_BOUNDS,
      ),
      migration_media_asset_limit: normalizeMigrationBudgetCount(
        source.migration_generation_budget?.migration_media_asset_limit,
        defaults.migration_generation_budget.migration_media_asset_limit,
        MIGRATION_MEDIA_ASSET_LIMIT_BOUNDS,
      ),
      migration_generated_page_limit: normalizeMigrationBudgetCount(
        source.migration_generation_budget?.migration_generated_page_limit,
        defaults.migration_generation_budget.migration_generated_page_limit,
        MIGRATION_GENERATED_PAGE_LIMIT_BOUNDS,
      ),
      migration_generated_file_limit: normalizeMigrationBudgetCount(
        source.migration_generation_budget?.migration_generated_file_limit,
        defaults.migration_generation_budget.migration_generated_file_limit,
        MIGRATION_GENERATED_FILE_LIMIT_BOUNDS,
      ),
      migration_generation_depth: (
        source.migration_generation_budget?.migration_generation_depth ||
        defaults.migration_generation_budget.migration_generation_depth
      ).trim().toLowerCase(),
      migration_variation_level: (
        source.migration_generation_budget?.migration_variation_level ||
        defaults.migration_generation_budget.migration_variation_level
      ).trim().toLowerCase(),
      migration_require_page_variety: Boolean(
        source.migration_generation_budget?.migration_require_page_variety ??
        defaults.migration_generation_budget.migration_require_page_variety,
      ),
      migration_require_design_variation: Boolean(
        source.migration_generation_budget?.migration_require_design_variation ??
        defaults.migration_generation_budget.migration_require_design_variation,
      ),
    },
    migration_generation_safety: {
      migration_provider_timeout_seconds: normalizeMigrationBudgetCount(
        source.migration_generation_safety?.migration_provider_timeout_seconds,
        defaults.migration_generation_safety.migration_provider_timeout_seconds,
        MIGRATION_PROVIDER_TIMEOUT_BOUNDS,
      ),
      migration_preflight_mode: (
        source.migration_generation_safety?.migration_preflight_mode
        || defaults.migration_generation_safety.migration_preflight_mode
      ).trim().toLowerCase(),
      migration_max_final_input_chars: normalizeMigrationBudgetCount(
        source.migration_generation_safety?.migration_max_final_input_chars,
        defaults.migration_generation_safety.migration_max_final_input_chars,
        MIGRATION_MAX_FINAL_INPUT_CHARS_BOUNDS,
      ),
      migration_max_difficulty_score: normalizeMigrationBudgetCount(
        source.migration_generation_safety?.migration_max_difficulty_score,
        defaults.migration_generation_safety.migration_max_difficulty_score,
        MIGRATION_MAX_DIFFICULTY_SCORE_BOUNDS,
      ),
      migration_compact_fallback_enabled: Boolean(
        source.migration_generation_safety?.migration_compact_fallback_enabled ??
        defaults.migration_generation_safety.migration_compact_fallback_enabled,
      ),
      migration_compact_page_limit: normalizeMigrationBudgetCount(
        source.migration_generation_safety?.migration_compact_page_limit,
        defaults.migration_generation_safety.migration_compact_page_limit,
        MIGRATION_COMPACT_PAGE_LIMIT_BOUNDS,
      ),
      migration_compact_media_asset_limit: normalizeMigrationBudgetCount(
        source.migration_generation_safety?.migration_compact_media_asset_limit,
        defaults.migration_generation_safety.migration_compact_media_asset_limit,
        MIGRATION_COMPACT_MEDIA_LIMIT_BOUNDS,
      ),
      migration_compact_recommendation_limit: normalizeMigrationBudgetCount(
        source.migration_generation_safety?.migration_compact_recommendation_limit,
        defaults.migration_generation_safety.migration_compact_recommendation_limit,
        MIGRATION_COMPACT_RECOMMENDATION_LIMIT_BOUNDS,
      ),
    },
  };
}

function validateNamespaceIsolationDefaults(defaults: GitHubNamespaceIsolationDefaults): string[] {
  const errors: string[] = [];
  const normalized = normalizeNamespaceIsolationDefaults(defaults);

  if (normalized.resource_quota.enabled) {
    if (!GITHUB_NAMESPACE_CPU_PATTERN.test(normalized.resource_quota.requests_cpu)) {
      errors.push("ResourceQuota requests CPU is invalid (for example: 500m or 1).");
    }
    if (!GITHUB_NAMESPACE_MEMORY_PATTERN.test(normalized.resource_quota.requests_memory)) {
      errors.push("ResourceQuota requests memory is invalid (for example: 512Mi or 1Gi).");
    }
    if (!GITHUB_NAMESPACE_CPU_PATTERN.test(normalized.resource_quota.limits_cpu)) {
      errors.push("ResourceQuota limits CPU is invalid (for example: 2000m or 2).");
    }
    if (!GITHUB_NAMESPACE_MEMORY_PATTERN.test(normalized.resource_quota.limits_memory)) {
      errors.push("ResourceQuota limits memory is invalid (for example: 2Gi).");
    }
    ([
      ["pods", normalized.resource_quota.pods],
      ["services", normalized.resource_quota.services],
      ["configmaps", normalized.resource_quota.configmaps],
      ["secrets", normalized.resource_quota.secrets],
      ["persistentvolumeclaims", normalized.resource_quota.persistentvolumeclaims],
    ] as const).forEach(([label, count]) => {
      if (!GITHUB_NAMESPACE_COUNT_PATTERN.test(String(count))) {
        errors.push(`ResourceQuota ${label} must be between 0 and 999999.`);
      }
    });
  }

  if (normalized.limit_range.enabled) {
    ([
      ["default CPU", normalized.limit_range.default_cpu],
      ["default request CPU", normalized.limit_range.default_request_cpu],
      ["min CPU", normalized.limit_range.min_cpu],
      ["max CPU", normalized.limit_range.max_cpu],
    ] as const).forEach(([label, value]) => {
      if (!GITHUB_NAMESPACE_CPU_PATTERN.test(value)) {
        errors.push(`LimitRange ${label} is invalid (for example: 500m or 1).`);
      }
    });
    ([
      ["default memory", normalized.limit_range.default_memory],
      ["default request memory", normalized.limit_range.default_request_memory],
      ["min memory", normalized.limit_range.min_memory],
      ["max memory", normalized.limit_range.max_memory],
    ] as const).forEach(([label, value]) => {
      if (!GITHUB_NAMESPACE_MEMORY_PATTERN.test(value)) {
        errors.push(`LimitRange ${label} is invalid (for example: 512Mi or 1Gi).`);
      }
    });
  }

  if (normalized.network_policy.enabled) {
    if (
      !GITHUB_NETWORK_POLICY_MODE_OPTIONS.includes(
        normalized.network_policy.mode as (typeof GITHUB_NETWORK_POLICY_MODE_OPTIONS)[number],
      )
    ) {
      errors.push("NetworkPolicy mode is invalid for platform-managed defaults.");
    }
  }
  if (
    !GITHUB_MANAGED_PREVIEW_ENDPOINT_MODE_OPTIONS.includes(
      normalized.managed_preview_endpoint.mode as (typeof GITHUB_MANAGED_PREVIEW_ENDPOINT_MODE_OPTIONS)[number],
    )
  ) {
    errors.push("Managed preview endpoint mode is invalid.");
  }

  // Migration generation budget/safety field ranges are validated by backend schema
  // and returned as field-specific API errors. Frontend should not block submits here.
  const budget = normalized.migration_generation_budget;
  if (
    !MIGRATION_GENERATION_DEPTH_OPTIONS.includes(
      budget.migration_generation_depth as (typeof MIGRATION_GENERATION_DEPTH_OPTIONS)[number],
    )
  ) {
    errors.push("Migration generation depth is invalid.");
  }
  if (
    !MIGRATION_VARIATION_LEVEL_OPTIONS.includes(
      budget.migration_variation_level as (typeof MIGRATION_VARIATION_LEVEL_OPTIONS)[number],
    )
  ) {
    errors.push("Migration variation level is invalid.");
  }
  const safety = normalized.migration_generation_safety;
  if (
    !MIGRATION_PREFLIGHT_MODE_OPTIONS.includes(
      safety.migration_preflight_mode as (typeof MIGRATION_PREFLIGHT_MODE_OPTIONS)[number],
    )
  ) {
    errors.push("Migration safety preflight mode is invalid.");
  }

  return errors;
}

function validateGitHubPublishConfigInputs({
  ownerInput,
  defaultBranchInput,
  basePathInput,
  deployWorkflowModeInput,
  targetEnvironmentKeyInput,
  managedGkeClusterNameInput,
  managedGkeClusterLocationInput,
  managedGkeProjectIdInput,
  namespaceIsolationDefaults,
  enabled,
}: {
  ownerInput: string;
  defaultBranchInput: string;
  basePathInput: string;
  deployWorkflowModeInput: string;
  targetEnvironmentKeyInput: string;
  managedGkeClusterNameInput: string;
  managedGkeClusterLocationInput: string;
  managedGkeProjectIdInput: string;
  namespaceIsolationDefaults: GitHubNamespaceIsolationDefaults;
  enabled: boolean;
}): GitHubPublishConfigValidationResult {
  const owner = ownerInput.trim();
  const rawDefaultBranch = defaultBranchInput.trim();
  const defaultBranch = rawDefaultBranch || "main";
  const basePath = normalizeGitHubPublishBasePath(basePathInput);
  const deployWorkflowMode =
    deployWorkflowModeInput.trim().toLowerCase() || GITHUB_DEPLOY_WORKFLOW_MODE_OPTIONS[0];
  const targetEnvironmentKey = targetEnvironmentKeyInput.trim().toLowerCase() || "gke_prod";
  const managedGkeClusterName = managedGkeClusterNameInput.trim().toLowerCase() || null;
  const managedGkeClusterLocation = managedGkeClusterLocationInput.trim().toLowerCase() || null;
  const managedGkeProjectId = managedGkeProjectIdInput.trim().toLowerCase() || null;

  let ownerError: string | null = null;
  let defaultBranchError: string | null = null;
  let basePathError: string | null = null;
  let deployWorkflowModeError: string | null = null;
  let targetEnvironmentKeyError: string | null = null;
  let managedGkeClusterNameError: string | null = null;
  let managedGkeClusterLocationError: string | null = null;
  let managedGkeProjectIdError: string | null = null;
  let basePathWarning: string | null = null;
  const namespaceIsolationErrors = validateNamespaceIsolationDefaults(namespaceIsolationDefaults);

  if (enabled && !owner) {
    ownerError = "GitHub owner is required when GitHub publishing is enabled.";
  } else if (owner && !GITHUB_OWNER_PATTERN.test(owner)) {
    ownerError = "GitHub owner is invalid (for example: mhanson13).";
  }

  if (enabled && !rawDefaultBranch) {
    defaultBranchError = "Default branch is required when GitHub publishing is enabled.";
  } else if (
    !GITHUB_BRANCH_PATTERN.test(defaultBranch) ||
    defaultBranch.includes("..") ||
    defaultBranch.startsWith("/") ||
    defaultBranch.endsWith("/") ||
    defaultBranch.includes("//")
  ) {
    defaultBranchError = "Default branch is invalid. Use letters, numbers, ., _, -, or / only.";
  }

  if (!GITHUB_BASE_PATH_PATTERN.test(basePath) || basePath.includes("..")) {
    basePathError = "Base path is invalid. Use '/' or '/subpath' with letters, numbers, -, _, ., and /.";
  } else {
    const rawBasePath = basePathInput.trim();
    if (rawBasePath && rawBasePath !== basePath) {
      basePathWarning = `Base path will be normalized to ${basePath}.`;
    }
  }

  if (!GITHUB_DEPLOY_WORKFLOW_MODE_OPTIONS.includes(deployWorkflowMode as (typeof GITHUB_DEPLOY_WORKFLOW_MODE_OPTIONS)[number])) {
    deployWorkflowModeError =
      "Deploy workflow mode is invalid. Use an approved platform-managed template mode.";
  }
  if (!GITHUB_TARGET_ENVIRONMENT_KEY_PATTERN.test(targetEnvironmentKey)) {
    targetEnvironmentKeyError =
      "Target environment key is invalid. Use lowercase letters, numbers, '-' or '_' only.";
  }
  if (managedGkeClusterName && !GITHUB_GKE_CLUSTER_NAME_PATTERN.test(managedGkeClusterName)) {
    managedGkeClusterNameError =
      "Managed GKE cluster name is invalid. Use lowercase letters, numbers, and '-'.";
  }
  if (
    managedGkeClusterLocation &&
    !GITHUB_GKE_CLUSTER_LOCATION_PATTERN.test(managedGkeClusterLocation)
  ) {
    managedGkeClusterLocationError =
      "Managed GKE cluster location is invalid. Use lowercase region/zone format (for example: us-central1).";
  }
  if (managedGkeProjectId && !GITHUB_GKE_PROJECT_ID_PATTERN.test(managedGkeProjectId)) {
    managedGkeProjectIdError =
      "Managed GCP project ID is invalid. Use lowercase letters, numbers, and '-'.";
  }

  const blockingError =
    ownerError ||
    defaultBranchError ||
    basePathError ||
    deployWorkflowModeError ||
    targetEnvironmentKeyError ||
    managedGkeClusterNameError ||
    managedGkeClusterLocationError ||
    managedGkeProjectIdError ||
    namespaceIsolationErrors[0] ||
    null;
  return {
    owner,
    defaultBranch,
    basePath,
    deployWorkflowMode,
    targetEnvironmentKey,
    managedGkeClusterName,
    managedGkeClusterLocation,
    managedGkeProjectId,
    ownerError,
    defaultBranchError,
    basePathError,
    deployWorkflowModeError,
    targetEnvironmentKeyError,
    managedGkeClusterNameError,
    managedGkeClusterLocationError,
    managedGkeProjectIdError,
    basePathWarning,
    namespaceIsolationErrors,
    blockingError,
  };
}

function safeGitHubPublishConfigLoadErrorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) {
    if (error.status === 401) {
      return "Session expired. Sign in again.";
    }
    if (error.status === 403) {
      return "Only admin principals can view GitHub publish configuration.";
    }
  }
  return "Unable to load GitHub publish configuration right now.";
}

function safeGitHubPublishConfigUpdateErrorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) {
    if (error.status === 401) {
      return "Session expired. Sign in again.";
    }
    if (error.status === 403) {
      return "Only admin principals can update GitHub publish configuration.";
    }
    if (error.status === 422) {
      return error.message || "Unable to save GitHub publish configuration. Review the values and try again.";
    }
  }
  return "Failed to save GitHub publish configuration.";
}

function extractMigrationFieldErrorsFromMessage(
  message: string,
  requestedDefaults: GitHubNamespaceIsolationDefaults,
): MigrationGenerationFieldErrorMap {
  const lowered = message.toLowerCase();
  const requestedBudget = requestedDefaults.migration_generation_budget;
  const requestedSafety = requestedDefaults.migration_generation_safety;
  const result: MigrationGenerationFieldErrorMap = {};

  const registerField = (field: MigrationGenerationSettingField, attemptedValue: number) => {
    if (lowered.includes(field)) {
      result[field] = migrationSettingValidationMessage(field, attemptedValue);
    }
  };

  registerField("migration_context_budget_chars", requestedBudget.migration_context_budget_chars);
  registerField("migration_recommendation_limit", requestedBudget.migration_recommendation_limit);
  registerField("migration_competitor_limit", requestedBudget.migration_competitor_limit);
  registerField("migration_source_page_summary_limit", requestedBudget.migration_source_page_summary_limit);
  registerField("migration_media_asset_limit", requestedBudget.migration_media_asset_limit);
  registerField("migration_generated_page_limit", requestedBudget.migration_generated_page_limit);
  registerField("migration_generated_file_limit", requestedBudget.migration_generated_file_limit);
  registerField("migration_provider_timeout_seconds", requestedSafety.migration_provider_timeout_seconds);
  registerField("migration_max_final_input_chars", requestedSafety.migration_max_final_input_chars);
  registerField("migration_max_difficulty_score", requestedSafety.migration_max_difficulty_score);
  registerField("migration_compact_page_limit", requestedSafety.migration_compact_page_limit);
  registerField("migration_compact_media_asset_limit", requestedSafety.migration_compact_media_asset_limit);
  registerField(
    "migration_compact_recommendation_limit",
    requestedSafety.migration_compact_recommendation_limit,
  );

  return result;
}

function applyGitHubPublishConfigInputs(
  config: GitHubPublishConfig,
  setters: {
    setOwner: (value: string) => void;
    setDefaultBranch: (value: string) => void;
    setBasePath: (value: string) => void;
    setDeployWorkflowMode: (value: string) => void;
    setTargetEnvironmentKey: (value: string) => void;
    setManagedGkeClusterName: (value: string) => void;
    setManagedGkeClusterLocation: (value: string) => void;
    setManagedGkeProjectId: (value: string) => void;
    setRepositoryAutoCreateEnabled: (value: boolean) => void;
    setManagedDeployKeyConfigured: (value: boolean) => void;
    setManagedDeployKeyUpdatedAt: (value: string | null) => void;
    clearManagedDeployKeyInput: () => void;
    setManagedDeployKeyClear: (value: boolean) => void;
    setNamespaceIsolationDefaults: (value: GitHubNamespaceIsolationDefaults) => void;
    setPersistedNamespaceIsolationDefaults: (value: GitHubNamespaceIsolationDefaults) => void;
    setMigrationCapReasons: (value: Record<string, string>) => void;
    setEnabled: (value: boolean) => void;
  },
): void {
  setters.setOwner(config.owner || config.repository || "");
  setters.setDefaultBranch(config.default_branch || "main");
  setters.setBasePath(config.base_path || "/");
  setters.setDeployWorkflowMode(config.deploy_workflow_mode || "site_repo_template_v1");
  setters.setTargetEnvironmentKey(config.target_environment_key || "gke_prod");
  setters.setManagedGkeClusterName(config.managed_gke_cluster_name || "");
  setters.setManagedGkeClusterLocation(config.managed_gke_cluster_location || "");
  setters.setManagedGkeProjectId(config.managed_gke_project_id || "");
  setters.setRepositoryAutoCreateEnabled(Boolean(config.github_repository_auto_create_enabled));
  setters.setManagedDeployKeyConfigured(Boolean(config.managed_gcp_deploy_key_configured));
  setters.setManagedDeployKeyUpdatedAt(config.managed_gcp_deploy_key_updated_at || null);
  setters.clearManagedDeployKeyInput();
  setters.setManagedDeployKeyClear(false);
  const normalizedNamespaceIsolationDefaults = normalizeNamespaceIsolationDefaults(config.namespace_isolation_defaults);
  const normalizedEffectiveNamespaceIsolationDefaults = normalizeNamespaceIsolationDefaults(
    config.namespace_isolation_effective_defaults ?? config.namespace_isolation_defaults,
  );
  setters.setNamespaceIsolationDefaults(normalizedNamespaceIsolationDefaults);
  setters.setPersistedNamespaceIsolationDefaults(normalizedEffectiveNamespaceIsolationDefaults);
  const normalizedCapReasons: Record<string, string> = {};
  const capReasonsSource = config.namespace_isolation_cap_reasons;
  if (capReasonsSource && typeof capReasonsSource === "object") {
    for (const [key, value] of Object.entries(capReasonsSource)) {
      const normalizedKey = key.trim();
      const normalizedValue = String(value ?? "").trim();
      if (!normalizedKey || !normalizedValue) {
        continue;
      }
      normalizedCapReasons[normalizedKey] = normalizedValue;
    }
  }
  setters.setMigrationCapReasons(normalizedCapReasons);
  setters.setEnabled(Boolean(config.enabled));
}

function formatIdentityLabel(identity: PrincipalIdentity): string {
  return identity.email || `${identity.provider}:${identity.provider_subject}`;
}

function formatLabelSummary(labels: Record<string, string> | null): string {
  if (!labels || Object.keys(labels).length === 0) {
    return "";
  }
  return Object.entries(labels)
    .map(([key, value]) => `${key}=${value}`)
    .join(", ");
}

function normalizeOptionalIsoTimeInput(value: string): string | undefined {
  const normalized = value.trim();
  if (!normalized) {
    return undefined;
  }
  return normalized;
}

export default function AdminPageContent({ mode = "all" }: AdminPageProps) {
  const context = useOperatorContext();
  const { principal } = useAuth();
  const [users, setUsers] = useState<Principal[]>([]);
  const [identities, setIdentities] = useState<PrincipalIdentity[]>([]);
  const [loadingUsers, setLoadingUsers] = useState(false);
  const [usersError, setUsersError] = useState<string | null>(null);
  const [identityWarning, setIdentityWarning] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitSuccess, setSubmitSuccess] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionSuccess, setActionSuccess] = useState<string | null>(null);
  const [actingPrincipalId, setActingPrincipalId] = useState<string | null>(null);
  const [identityActionError, setIdentityActionError] = useState<string | null>(null);
  const [identityActionSuccess, setIdentityActionSuccess] = useState<string | null>(null);
  const [actingIdentityId, setActingIdentityId] = useState<string | null>(null);
  const [principalId, setPrincipalId] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [role, setRole] = useState<PrincipalRole>("operator");
  const [identityPrincipalId, setIdentityPrincipalId] = useState("");
  const [identityProvider, setIdentityProvider] = useState("google");
  const [identityProviderSubject, setIdentityProviderSubject] = useState("");
  const [identityEmail, setIdentityEmail] = useState("");
  const [identityEmailVerified, setIdentityEmailVerified] = useState(false);
  const [identityIsActive, setIdentityIsActive] = useState(true);
  const [identitySubmitting, setIdentitySubmitting] = useState(false);
  const [identitySubmitError, setIdentitySubmitError] = useState<string | null>(null);
  const [identitySubmitSuccess, setIdentitySubmitSuccess] = useState<string | null>(null);
  const [businessSettings, setBusinessSettings] = useState<BusinessSettings | null>(null);
  const [businessSettingsLoading, setBusinessSettingsLoading] = useState(false);
  const [businessSettingsLoadError, setBusinessSettingsLoadError] = useState<string | null>(null);
  const [crawlPageLimitInput, setCrawlPageLimitInput] = useState(String(DEFAULT_CRAWL_PAGE_LIMIT));
  const [crawlPageLimitSubmitting, setCrawlPageLimitSubmitting] = useState(false);
  const [crawlPageLimitMessage, setCrawlPageLimitMessage] = useState<string | null>(null);
  const [crawlPageLimitError, setCrawlPageLimitError] = useState<string | null>(null);
  const [candidateMinRelevanceScoreInput, setCandidateMinRelevanceScoreInput] = useState("35");
  const [candidateBigBoxPenaltyInput, setCandidateBigBoxPenaltyInput] = useState("20");
  const [candidateDirectoryPenaltyInput, setCandidateDirectoryPenaltyInput] = useState("35");
  const [candidateLocalAlignmentBonusInput, setCandidateLocalAlignmentBonusInput] = useState("10");
  const [candidateQualitySubmitting, setCandidateQualitySubmitting] = useState(false);
  const [candidateQualityMessage, setCandidateQualityMessage] = useState<string | null>(null);
  const [candidateQualityError, setCandidateQualityError] = useState<string | null>(null);
  const [competitorPrimaryTimeoutInput, setCompetitorPrimaryTimeoutInput] = useState("");
  const [competitorDegradedTimeoutInput, setCompetitorDegradedTimeoutInput] = useState("");
  const [competitorTimeoutSubmitting, setCompetitorTimeoutSubmitting] = useState(false);
  const [competitorTimeoutMessage, setCompetitorTimeoutMessage] = useState<string | null>(null);
  const [competitorTimeoutError, setCompetitorTimeoutError] = useState<string | null>(null);
  const [competitorPromptOverrideInput, setCompetitorPromptOverrideInput] = useState("");
  const [recommendationsPromptOverrideInput, setRecommendationsPromptOverrideInput] = useState("");
  const [defaultAiModelInput, setDefaultAiModelInput] = useState("");
  const [promptOverrideSubmitting, setPromptOverrideSubmitting] = useState(false);
  const [promptOverrideMessage, setPromptOverrideMessage] = useState<string | null>(null);
  const [promptOverrideError, setPromptOverrideError] = useState<string | null>(null);
  const competitorPromptContractWarning = useMemo(
    () => assessCompetitorPromptOverrideContract(competitorPromptOverrideInput),
    [competitorPromptOverrideInput],
  );
  const [githubPublishOwnerInput, setGitHubPublishOwnerInput] = useState("");
  const [githubPublishDefaultBranchInput, setGitHubPublishDefaultBranchInput] = useState("main");
  const [githubPublishBasePathInput, setGitHubPublishBasePathInput] = useState("/");
  const [githubPublishDeployWorkflowModeInput, setGitHubPublishDeployWorkflowModeInput] = useState(
    "site_repo_template_v1",
  );
  const [githubPublishTargetEnvironmentKeyInput, setGitHubPublishTargetEnvironmentKeyInput] = useState(
    "gke_prod",
  );
  const [githubPublishManagedGkeClusterNameInput, setGitHubPublishManagedGkeClusterNameInput] = useState("");
  const [githubPublishManagedGkeClusterLocationInput, setGitHubPublishManagedGkeClusterLocationInput] =
    useState("");
  const [githubPublishManagedGkeProjectIdInput, setGitHubPublishManagedGkeProjectIdInput] = useState("");
  const [githubRepositoryAutoCreateEnabled, setGitHubRepositoryAutoCreateEnabled] = useState(false);
  const [githubPublishManagedDeployKeyInput, setGitHubPublishManagedDeployKeyInput] = useState("");
  const [githubPublishManagedDeployKeyClear, setGitHubPublishManagedDeployKeyClear] = useState(false);
  const [githubPublishManagedDeployKeyConfigured, setGitHubPublishManagedDeployKeyConfigured] = useState(false);
  const [githubPublishManagedDeployKeyUpdatedAt, setGitHubPublishManagedDeployKeyUpdatedAt] = useState<string | null>(
    null,
  );
  const [githubNamespaceIsolationDefaults, setGitHubNamespaceIsolationDefaults] = useState<GitHubNamespaceIsolationDefaults>(
    DEFAULT_NAMESPACE_ISOLATION_DEFAULTS,
  );
  const [githubPersistedNamespaceIsolationDefaults, setGitHubPersistedNamespaceIsolationDefaults] =
    useState<GitHubNamespaceIsolationDefaults>(DEFAULT_NAMESPACE_ISOLATION_DEFAULTS);
  const [githubMigrationCapReasons, setGitHubMigrationCapReasons] = useState<Record<string, string>>({});
  const [githubMigrationFieldErrors, setGitHubMigrationFieldErrors] = useState<MigrationGenerationFieldErrorMap>({});
  const [githubMigrationAdjustmentReason, setGitHubMigrationAdjustmentReason] = useState<string | null>(null);
  const [githubPublishEnabled, setGitHubPublishEnabled] = useState(false);
  const [githubPublishConfigLoading, setGitHubPublishConfigLoading] = useState(false);
  const [githubPublishConfigSubmitting, setGitHubPublishConfigSubmitting] = useState(false);
  const [githubPublishConfigMessage, setGitHubPublishConfigMessage] = useState<string | null>(null);
  const [githubPublishConfigError, setGitHubPublishConfigError] = useState<string | null>(null);
  const [siteDraftsById, setSiteDraftsById] = useState<Record<string, SiteManagementDraft>>({});
  const [siteManagementMessage, setSiteManagementMessage] = useState<string | null>(null);
  const [siteManagementError, setSiteManagementError] = useState<string | null>(null);
  const [updatingSiteId, setUpdatingSiteId] = useState<string | null>(null);
  const [preparingSiteDeleteId, setPreparingSiteDeleteId] = useState<string | null>(null);
  const [deletingSiteId, setDeletingSiteId] = useState<string | null>(null);
  const [siteDeletePlanSiteId, setSiteDeletePlanSiteId] = useState<string | null>(null);
  const [siteDeletePlan, setSiteDeletePlan] = useState<SEOSiteDeletePlan | null>(null);
  const [siteDeleteResult, setSiteDeleteResult] = useState<SEOSiteDeleteExecutionResult | null>(null);
  const [siteDeleteForm, setSiteDeleteForm] = useState<SiteDeleteFormState>(EMPTY_SITE_DELETE_FORM_STATE);
  const [gcpLogsFilterInput, setGcpLogsFilterInput] = useState("");
  const [gcpLogsPageSize, setGcpLogsPageSize] = useState<number>(GCP_LOGS_PAGE_SIZE_DEFAULT);
  const [gcpLogsStartTimeInput, setGcpLogsStartTimeInput] = useState("");
  const [gcpLogsEndTimeInput, setGcpLogsEndTimeInput] = useState("");
  const [gcpLogsEntries, setGcpLogsEntries] = useState<GCPLogEntry[]>([]);
  const [gcpLogsNextPageToken, setGcpLogsNextPageToken] = useState<string | null>(null);
  const [gcpLogsOrderBy, setGcpLogsOrderBy] = useState<string>("timestamp desc");
  const [gcpLogsResourceScope, setGcpLogsResourceScope] = useState<string[]>([]);
  const [gcpLogsEffectiveFilter, setGcpLogsEffectiveFilter] = useState<string>("");
  const [gcpLogsDefaultTimeRangeApplied, setGcpLogsDefaultTimeRangeApplied] = useState<boolean>(false);
  const [gcpLogsLoading, setGcpLogsLoading] = useState(false);
  const [gcpLogsError, setGcpLogsError] = useState<string | null>(null);
  const [gcpLogsMessage, setGcpLogsMessage] = useState<string | null>(null);
  const [gcpLogsHasExecuted, setGcpLogsHasExecuted] = useState(false);

  const isAdmin = principal?.role === "admin";
  const showUserManagement = mode !== "admin";
  const showAdminSettings = mode !== "userMgmt";
  const siteManagementBusy = Boolean(updatingSiteId || preparingSiteDeleteId || deletingSiteId);
  const selectedDeleteSite = useMemo(
    () => context.sites.find((site) => site.id === siteDeletePlanSiteId) ?? null,
    [context.sites, siteDeletePlanSiteId],
  );
  const siteDeleteConfirmationPhraseMatches =
    Boolean(siteDeletePlan?.required_confirmation_phrase) &&
    siteDeleteForm.confirmationPhrase.trim() === (siteDeletePlan?.required_confirmation_phrase || "").trim();
  const siteDeleteAcknowledgementsReady =
    siteDeleteForm.acknowledgeDeleteDatabaseRecords &&
    (!siteDeleteForm.deleteGitHubRepo || siteDeleteForm.acknowledgeDeleteGitHubRepo) &&
    (!siteDeleteForm.deleteRuntimeResources || siteDeleteForm.acknowledgeDeleteRuntimeResources) &&
    (!siteDeleteForm.deleteDnsResources || siteDeleteForm.acknowledgeDeleteDnsResources);
  const siteDeleteExecuteEnabled =
    Boolean(siteDeletePlan) &&
    !preparingSiteDeleteId &&
    !deletingSiteId &&
    siteDeleteConfirmationPhraseMatches &&
    siteDeleteAcknowledgementsReady &&
    (!siteDeletePlan?.is_active || siteDeleteForm.forceDeleteActive);
  const githubPublishValidation = useMemo(
    () =>
      validateGitHubPublishConfigInputs({
        ownerInput: githubPublishOwnerInput,
        defaultBranchInput: githubPublishDefaultBranchInput,
        basePathInput: githubPublishBasePathInput,
        deployWorkflowModeInput: githubPublishDeployWorkflowModeInput,
        targetEnvironmentKeyInput: githubPublishTargetEnvironmentKeyInput,
        managedGkeClusterNameInput: githubPublishManagedGkeClusterNameInput,
        managedGkeClusterLocationInput: githubPublishManagedGkeClusterLocationInput,
        managedGkeProjectIdInput: githubPublishManagedGkeProjectIdInput,
        namespaceIsolationDefaults: githubNamespaceIsolationDefaults,
        enabled: githubPublishEnabled,
      }),
      [
        githubPublishBasePathInput,
        githubPublishDeployWorkflowModeInput,
        githubPublishDefaultBranchInput,
        githubPublishEnabled,
        githubPublishManagedGkeClusterLocationInput,
        githubPublishManagedGkeClusterNameInput,
        githubPublishManagedGkeProjectIdInput,
        githubNamespaceIsolationDefaults,
        githubPublishOwnerInput,
        githubPublishTargetEnvironmentKeyInput,
      ],
    );
  const githubPublishPreviewOwner = githubPublishValidation.owner || "Not configured";
  const requestedMigrationBudget = githubNamespaceIsolationDefaults.migration_generation_budget;
  const requestedMigrationSafety = githubNamespaceIsolationDefaults.migration_generation_safety;
  const effectiveMigrationBudget = githubPersistedNamespaceIsolationDefaults.migration_generation_budget;
  const effectiveMigrationSafety = githubPersistedNamespaceIsolationDefaults.migration_generation_safety;

  const migrationRequestedVsEffectiveDiffCount = useMemo(() => {
    const pairs: Array<[number, number]> = [
      [requestedMigrationSafety.migration_provider_timeout_seconds, effectiveMigrationSafety.migration_provider_timeout_seconds],
      [requestedMigrationSafety.migration_max_final_input_chars, effectiveMigrationSafety.migration_max_final_input_chars],
      [requestedMigrationSafety.migration_max_difficulty_score, effectiveMigrationSafety.migration_max_difficulty_score],
      [requestedMigrationSafety.migration_compact_page_limit, effectiveMigrationSafety.migration_compact_page_limit],
      [requestedMigrationSafety.migration_compact_media_asset_limit, effectiveMigrationSafety.migration_compact_media_asset_limit],
      [
        requestedMigrationSafety.migration_compact_recommendation_limit,
        effectiveMigrationSafety.migration_compact_recommendation_limit,
      ],
      [requestedMigrationBudget.migration_context_budget_chars, effectiveMigrationBudget.migration_context_budget_chars],
      [requestedMigrationBudget.migration_recommendation_limit, effectiveMigrationBudget.migration_recommendation_limit],
      [requestedMigrationBudget.migration_competitor_limit, effectiveMigrationBudget.migration_competitor_limit],
      [requestedMigrationBudget.migration_source_page_summary_limit, effectiveMigrationBudget.migration_source_page_summary_limit],
      [requestedMigrationBudget.migration_media_asset_limit, effectiveMigrationBudget.migration_media_asset_limit],
      [requestedMigrationBudget.migration_generated_page_limit, effectiveMigrationBudget.migration_generated_page_limit],
      [requestedMigrationBudget.migration_generated_file_limit, effectiveMigrationBudget.migration_generated_file_limit],
    ];
    return pairs.filter(([requested, effective]) => requested !== effective).length;
  }, [effectiveMigrationBudget, effectiveMigrationSafety, requestedMigrationBudget, requestedMigrationSafety]);

  const loadUsersData = useCallback(async (): Promise<AdminPageLoadResult> => {
    const principalResponse = await fetchPrincipals(context.token, context.businessId);
    try {
      const identitiesResponse = await fetchPrincipalIdentities(context.token, context.businessId);
      return {
        users: principalResponse.items,
        identities: identitiesResponse.items,
        identityWarning: null,
      };
    } catch {
      return {
        users: principalResponse.items,
        identities: [],
        identityWarning: "Sign-in identity details are temporarily unavailable.",
      };
    }
  }, [context.businessId, context.token]);

  const identitiesByPrincipalId = useMemo(() => {
    const grouped = new Map<string, PrincipalIdentity[]>();
    for (const identity of identities) {
      const bucket = grouped.get(identity.principal_id);
      if (bucket) {
        bucket.push(identity);
      } else {
        grouped.set(identity.principal_id, [identity]);
      }
    }
    return grouped;
  }, [identities]);

  const activeUsersCount = useMemo(
    () => users.filter((user) => user.is_active).length,
    [users],
  );

  const principalsWithoutIdentityCount = useMemo(
    () =>
      users.filter((user) => {
        const userIdentities = identitiesByPrincipalId.get(user.id);
        return !userIdentities || userIdentities.length === 0;
      }).length,
    [identitiesByPrincipalId, users],
  );
  const settingsHealth = useMemo(
    () => evaluateSettingsHealth(businessSettings),
    [businessSettings],
  );

  const normalizedIdentityProvider = useMemo(() => identityProvider.trim().toLowerCase(), [identityProvider]);
  const normalizedIdentityProviderSubject = useMemo(
    () => identityProviderSubject.trim(),
    [identityProviderSubject],
  );

  const existingIdentityForProviderSubject = useMemo(() => {
    if (!normalizedIdentityProvider || !normalizedIdentityProviderSubject) {
      return null;
    }
    return (
      identities.find(
        (identity) =>
          identity.provider === normalizedIdentityProvider &&
          identity.provider_subject === normalizedIdentityProviderSubject,
      ) || null
    );
  }, [identities, normalizedIdentityProvider, normalizedIdentityProviderSubject]);

  const identityAlreadyLinkedToSelectedPrincipal =
    existingIdentityForProviderSubject !== null &&
    existingIdentityForProviderSubject.principal_id === identityPrincipalId;

  const identityLinkedToDifferentPrincipal =
    existingIdentityForProviderSubject !== null &&
    existingIdentityForProviderSubject.principal_id !== identityPrincipalId;

  useEffect(() => {
    if (context.loading || context.error || !isAdmin || !showUserManagement) {
      return;
    }

    let cancelled = false;
    async function loadUsers() {
      setLoadingUsers(true);
      setUsersError(null);
      setIdentityWarning(null);
      try {
        const result = await loadUsersData();
        if (!cancelled) {
          setUsers(result.users);
          setIdentities(result.identities);
          setIdentityWarning(result.identityWarning);
        }
      } catch (err) {
        if (!cancelled) {
          setUsersError(safeAdminPageErrorMessage(err));
        }
      } finally {
        if (!cancelled) {
          setLoadingUsers(false);
        }
      }
    }

    void loadUsers();
    return () => {
      cancelled = true;
    };
  }, [context.error, context.loading, isAdmin, loadUsersData, showUserManagement]);

  useEffect(() => {
    if (context.loading || context.error || !isAdmin || !showAdminSettings) {
      return;
    }

    let cancelled = false;

    async function loadBusinessSettings() {
      setBusinessSettingsLoading(true);
      setBusinessSettingsLoadError(null);
      setGitHubPublishConfigLoading(true);
      setGitHubPublishConfigError(null);
      try {
        const [settingsResult, githubResult] = await Promise.allSettled([
          fetchBusinessSettings(context.token, context.businessId),
          fetchGitHubPublishConfig(context.token),
        ]);
        if (cancelled) {
          return;
        }
        if (settingsResult.status === "fulfilled") {
          const settings = settingsResult.value;
          setBusinessSettings(settings);
          setCrawlPageLimitInput(String(settings.seo_audit_crawl_max_pages));
          setCandidateMinRelevanceScoreInput(String(settings.competitor_candidate_min_relevance_score));
          setCandidateBigBoxPenaltyInput(String(settings.competitor_candidate_big_box_penalty));
          setCandidateDirectoryPenaltyInput(String(settings.competitor_candidate_directory_penalty));
          setCandidateLocalAlignmentBonusInput(String(settings.competitor_candidate_local_alignment_bonus));
          setCompetitorPrimaryTimeoutInput(timeoutSettingToInput(settings.competitor_primary_timeout_seconds));
          setCompetitorDegradedTimeoutInput(timeoutSettingToInput(settings.competitor_degraded_timeout_seconds));
          setCompetitorPromptOverrideInput(settings.ai_prompt_text_competitor || "");
          setRecommendationsPromptOverrideInput(settings.ai_prompt_text_recommendations || "");
          setDefaultAiModelInput(settings.default_ai_model || "");
        } else {
          setBusinessSettingsLoadError(safeBusinessSettingsErrorMessage(settingsResult.reason));
        }

        if (githubResult.status === "fulfilled") {
          applyGitHubPublishConfigInputs(githubResult.value, {
            setOwner: setGitHubPublishOwnerInput,
            setDefaultBranch: setGitHubPublishDefaultBranchInput,
            setBasePath: setGitHubPublishBasePathInput,
            setDeployWorkflowMode: setGitHubPublishDeployWorkflowModeInput,
            setTargetEnvironmentKey: setGitHubPublishTargetEnvironmentKeyInput,
            setManagedGkeClusterName: setGitHubPublishManagedGkeClusterNameInput,
            setManagedGkeClusterLocation: setGitHubPublishManagedGkeClusterLocationInput,
            setManagedGkeProjectId: setGitHubPublishManagedGkeProjectIdInput,
            setRepositoryAutoCreateEnabled: setGitHubRepositoryAutoCreateEnabled,
            setManagedDeployKeyConfigured: setGitHubPublishManagedDeployKeyConfigured,
            setManagedDeployKeyUpdatedAt: setGitHubPublishManagedDeployKeyUpdatedAt,
            clearManagedDeployKeyInput: () => setGitHubPublishManagedDeployKeyInput(""),
            setManagedDeployKeyClear: setGitHubPublishManagedDeployKeyClear,
            setNamespaceIsolationDefaults: setGitHubNamespaceIsolationDefaults,
            setPersistedNamespaceIsolationDefaults: setGitHubPersistedNamespaceIsolationDefaults,
            setMigrationCapReasons: setGitHubMigrationCapReasons,
            setEnabled: setGitHubPublishEnabled,
          });
          setGitHubMigrationFieldErrors({});
          setGitHubMigrationAdjustmentReason(
            Object.keys(githubResult.value.namespace_isolation_cap_reasons || {}).length > 0
              ? "backend_adjusted_values"
              : null,
          );
        } else {
          setGitHubPublishConfigError(safeGitHubPublishConfigLoadErrorMessage(githubResult.reason));
        }
      } finally {
        if (!cancelled) {
          setBusinessSettingsLoading(false);
          setGitHubPublishConfigLoading(false);
        }
      }
    }

    void loadBusinessSettings();
    return () => {
      cancelled = true;
    };
  }, [context.businessId, context.error, context.loading, context.token, isAdmin, showAdminSettings]);

  useEffect(() => {
    if (users.length === 0) {
      if (identityPrincipalId !== "") {
        setIdentityPrincipalId("");
      }
      return;
    }

    const selectedPrincipalExists = users.some((user) => user.id === identityPrincipalId);
    if (!selectedPrincipalExists) {
      setIdentityPrincipalId(users[0].id);
    }
  }, [identityPrincipalId, users]);

  useEffect(() => {
    const nextDrafts: Record<string, SiteManagementDraft> = {};
    for (const site of context.sites) {
      nextDrafts[site.id] = {
        name: site.display_name,
        url: site.base_url,
        searchConsolePropertyUrl: site.search_console_property_url || "",
        searchConsoleEnabled: Boolean(site.search_console_enabled),
      };
    }
    setSiteDraftsById(nextDrafts);
  }, [context.sites]);

  const handleCreateUser = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitting(true);
    setSubmitError(null);
    setSubmitSuccess(null);
    setIdentitySubmitError(null);
    setIdentitySubmitSuccess(null);
    setActionError(null);
    setActionSuccess(null);
    setIdentityActionError(null);
    setIdentityActionSuccess(null);

    try {
      await createPrincipal(context.token, context.businessId, {
        principal_id: principalId.trim(),
        display_name: displayName.trim() || undefined,
        role,
      });
      const refreshed = await loadUsersData();
      setUsers(refreshed.users);
      setIdentities(refreshed.identities);
      setIdentityWarning(refreshed.identityWarning);
      setPrincipalId("");
      setDisplayName("");
      setRole("operator");
      setSubmitSuccess("User record created.");
    } catch (err) {
      setSubmitError(safeCreateUserErrorMessage(err));
    } finally {
      setSubmitting(false);
    }
  };

  const handleCreateAndLinkIdentity = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setIdentitySubmitError(null);
    setIdentitySubmitSuccess(null);
    setSubmitError(null);
    setSubmitSuccess(null);
    setActionError(null);
    setActionSuccess(null);
    setIdentityActionError(null);
    setIdentityActionSuccess(null);

    if (!identityPrincipalId.trim()) {
      setIdentitySubmitError("Select a principal to link this identity.");
      return;
    }
    if (!normalizedIdentityProvider) {
      setIdentitySubmitError("Provider is required.");
      return;
    }
    if (!normalizedIdentityProviderSubject) {
      setIdentitySubmitError("Provider subject is required.");
      return;
    }
    if (identityAlreadyLinkedToSelectedPrincipal) {
      setIdentitySubmitError("This identity is already linked to the selected principal.");
      return;
    }
    if (identityLinkedToDifferentPrincipal) {
      setIdentitySubmitError(
        `This identity is already linked to principal "${existingIdentityForProviderSubject?.principal_id}".`,
      );
      return;
    }

    setIdentitySubmitting(true);
    try {
      await createPrincipalIdentity(context.token, context.businessId, {
        provider: normalizedIdentityProvider,
        provider_subject: normalizedIdentityProviderSubject,
        principal_id: identityPrincipalId.trim(),
        email: identityEmail.trim() || undefined,
        email_verified: identityEmailVerified,
        is_active: identityIsActive,
      });
      const refreshed = await loadUsersData();
      setUsers(refreshed.users);
      setIdentities(refreshed.identities);
      setIdentityWarning(refreshed.identityWarning);
      setIdentityProviderSubject("");
      setIdentityEmail("");
      setIdentityEmailVerified(false);
      setIdentityIsActive(true);
      setIdentitySubmitSuccess(`Identity linked to principal "${identityPrincipalId.trim()}".`);
    } catch (err) {
      setIdentitySubmitError(safeCreateIdentityErrorMessage(err));
    } finally {
      setIdentitySubmitting(false);
    }
  };

  const handleUpdateCrawlPageLimit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setCrawlPageLimitMessage(null);
    setCrawlPageLimitError(null);
    setCompetitorTimeoutMessage(null);

    const parsed = parseCrawlPageLimit(crawlPageLimitInput);
    if (parsed === null) {
      setCrawlPageLimitError(
        `Crawl page limit must be an integer between ${CRAWL_PAGE_LIMIT_MIN} and ${CRAWL_PAGE_LIMIT_MAX}.`,
      );
      return;
    }

    setCrawlPageLimitSubmitting(true);
    try {
      const updated = await updateBusinessSettings(context.token, context.businessId, {
        seo_audit_crawl_max_pages: parsed,
      });
      setBusinessSettings(updated);
      setCrawlPageLimitInput(String(updated.seo_audit_crawl_max_pages));
      setCrawlPageLimitMessage(`SEO crawl page limit updated to ${updated.seo_audit_crawl_max_pages}.`);
    } catch (err) {
      setCrawlPageLimitError(safeBusinessSettingsUpdateErrorMessage(err));
    } finally {
      setCrawlPageLimitSubmitting(false);
    }
  };

  const handleUpdateCompetitorCandidateQuality = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setCandidateQualityError(null);
    setCrawlPageLimitMessage(null);
    setCandidateQualityMessage(null);
    setPromptOverrideMessage(null);
    setCompetitorTimeoutMessage(null);

    const minRelevanceScore = parseBoundedInteger(candidateMinRelevanceScoreInput, {
      min: COMPETITOR_MIN_RELEVANCE_SCORE_MIN,
      max: COMPETITOR_MIN_RELEVANCE_SCORE_MAX,
    });
    if (minRelevanceScore === null) {
      setCandidateQualityError(
        (
          "Minimum relevance score must be an integer between " +
          `${COMPETITOR_MIN_RELEVANCE_SCORE_MIN} and ${COMPETITOR_MIN_RELEVANCE_SCORE_MAX}.`
        ),
      );
      return;
    }

    const bigBoxPenalty = parseBoundedInteger(candidateBigBoxPenaltyInput, {
      min: COMPETITOR_BIG_BOX_PENALTY_MIN,
      max: COMPETITOR_BIG_BOX_PENALTY_MAX,
    });
    if (bigBoxPenalty === null) {
      setCandidateQualityError(
        (
          "Big-box mismatch penalty must be an integer between " +
          `${COMPETITOR_BIG_BOX_PENALTY_MIN} and ${COMPETITOR_BIG_BOX_PENALTY_MAX}.`
        ),
      );
      return;
    }

    const directoryPenalty = parseBoundedInteger(candidateDirectoryPenaltyInput, {
      min: COMPETITOR_DIRECTORY_PENALTY_MIN,
      max: COMPETITOR_DIRECTORY_PENALTY_MAX,
    });
    if (directoryPenalty === null) {
      setCandidateQualityError(
        (
          "Directory/aggregator penalty must be an integer between " +
          `${COMPETITOR_DIRECTORY_PENALTY_MIN} and ${COMPETITOR_DIRECTORY_PENALTY_MAX}.`
        ),
      );
      return;
    }

    const localAlignmentBonus = parseBoundedInteger(candidateLocalAlignmentBonusInput, {
      min: COMPETITOR_LOCAL_ALIGNMENT_BONUS_MIN,
      max: COMPETITOR_LOCAL_ALIGNMENT_BONUS_MAX,
    });
    if (localAlignmentBonus === null) {
      setCandidateQualityError(
        (
          "Local alignment bonus must be an integer between " +
          `${COMPETITOR_LOCAL_ALIGNMENT_BONUS_MIN} and ${COMPETITOR_LOCAL_ALIGNMENT_BONUS_MAX}.`
        ),
      );
      return;
    }

    setCandidateQualitySubmitting(true);
    try {
      const updated = await updateBusinessSettings(context.token, context.businessId, {
        competitor_candidate_min_relevance_score: minRelevanceScore,
        competitor_candidate_big_box_penalty: bigBoxPenalty,
        competitor_candidate_directory_penalty: directoryPenalty,
        competitor_candidate_local_alignment_bonus: localAlignmentBonus,
      });
      setBusinessSettings(updated);
      setCandidateMinRelevanceScoreInput(String(updated.competitor_candidate_min_relevance_score));
      setCandidateBigBoxPenaltyInput(String(updated.competitor_candidate_big_box_penalty));
      setCandidateDirectoryPenaltyInput(String(updated.competitor_candidate_directory_penalty));
      setCandidateLocalAlignmentBonusInput(String(updated.competitor_candidate_local_alignment_bonus));
      setCandidateQualityMessage("AI competitor candidate quality settings updated.");
    } catch (err) {
      setCandidateQualityError(safeCandidateQualitySettingsUpdateErrorMessage(err));
    } finally {
      setCandidateQualitySubmitting(false);
    }
  };

  const handleUpdateCompetitorTimeoutSettings = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setCompetitorTimeoutError(null);
    setCompetitorTimeoutMessage(null);
    setCrawlPageLimitMessage(null);
    setCandidateQualityMessage(null);
    setPromptOverrideMessage(null);

    const primaryTimeout = parseOptionalBoundedInteger(competitorPrimaryTimeoutInput, {
      min: COMPETITOR_TIMEOUT_SECONDS_MIN,
      max: COMPETITOR_TIMEOUT_SECONDS_MAX,
    });
    if (primaryTimeout === "invalid") {
      setCompetitorTimeoutError(
        (
          "Primary timeout must be blank or an integer between " +
          `${COMPETITOR_TIMEOUT_SECONDS_MIN} and ${COMPETITOR_TIMEOUT_SECONDS_MAX}.`
        ),
      );
      return;
    }

    const degradedTimeout = parseOptionalBoundedInteger(competitorDegradedTimeoutInput, {
      min: COMPETITOR_TIMEOUT_SECONDS_MIN,
      max: COMPETITOR_TIMEOUT_SECONDS_MAX,
    });
    if (degradedTimeout === "invalid") {
      setCompetitorTimeoutError(
        (
          "Degraded retry timeout must be blank or an integer between " +
          `${COMPETITOR_TIMEOUT_SECONDS_MIN} and ${COMPETITOR_TIMEOUT_SECONDS_MAX}.`
        ),
      );
      return;
    }

    setCompetitorTimeoutSubmitting(true);
    try {
      const updated = await updateBusinessSettings(context.token, context.businessId, {
        competitor_primary_timeout_seconds: primaryTimeout,
        competitor_degraded_timeout_seconds: degradedTimeout,
      });
      setBusinessSettings(updated);
      setCompetitorPrimaryTimeoutInput(timeoutSettingToInput(updated.competitor_primary_timeout_seconds));
      setCompetitorDegradedTimeoutInput(timeoutSettingToInput(updated.competitor_degraded_timeout_seconds));
      setCompetitorTimeoutMessage("Competitor generation timeout settings updated.");
    } catch (err) {
      setCompetitorTimeoutError(safeCompetitorTimeoutSettingsUpdateErrorMessage(err));
    } finally {
      setCompetitorTimeoutSubmitting(false);
    }
  };

  const handleSavePromptOverrides = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setPromptOverrideMessage(null);
    setPromptOverrideError(null);
    setCrawlPageLimitMessage(null);
    setCandidateQualityMessage(null);
    setCompetitorTimeoutMessage(null);

    setPromptOverrideSubmitting(true);
    try {
      const updated = await updateBusinessSettings(context.token, context.businessId, {
        ai_prompt_text_competitor: normalizePromptOverrideInput(competitorPromptOverrideInput),
        ai_prompt_text_recommendations: normalizePromptOverrideInput(recommendationsPromptOverrideInput),
        default_ai_model: normalizeDefaultModelInput(defaultAiModelInput),
      });
      setBusinessSettings(updated);
      setCompetitorPromptOverrideInput(updated.ai_prompt_text_competitor || "");
      setRecommendationsPromptOverrideInput(updated.ai_prompt_text_recommendations || "");
      setDefaultAiModelInput(updated.default_ai_model || "");
      setPromptOverrideMessage("AI prompt/default model settings updated.");
    } catch (err) {
      setPromptOverrideError(safePromptSettingsUpdateErrorMessage(err));
    } finally {
      setPromptOverrideSubmitting(false);
    }
  };

  const handleClearPromptOverrides = async () => {
    setPromptOverrideMessage(null);
    setPromptOverrideError(null);
    setCrawlPageLimitMessage(null);
    setCandidateQualityMessage(null);
    setCompetitorTimeoutMessage(null);
    setPromptOverrideSubmitting(true);
    try {
      const updated = await updateBusinessSettings(context.token, context.businessId, {
        ai_prompt_text_competitor: null,
        ai_prompt_text_recommendations: null,
      });
      setBusinessSettings(updated);
      setCompetitorPromptOverrideInput(updated.ai_prompt_text_competitor || "");
      setRecommendationsPromptOverrideInput(updated.ai_prompt_text_recommendations || "");
      setDefaultAiModelInput(updated.default_ai_model || "");
      setPromptOverrideMessage("AI prompt overrides cleared. Deployment fallback/default is now active.");
    } catch (err) {
      setPromptOverrideError(safePromptSettingsUpdateErrorMessage(err));
    } finally {
      setPromptOverrideSubmitting(false);
    }
  };

  const updateNamespaceResourceQuota = <K extends keyof GitHubNamespaceResourceQuotaDefaults>(
    key: K,
    value: GitHubNamespaceResourceQuotaDefaults[K],
  ) => {
    setGitHubNamespaceIsolationDefaults((current) => ({
      ...current,
      resource_quota: {
        ...current.resource_quota,
        [key]: value,
      },
    }));
  };

  const updateNamespaceLimitRange = <K extends keyof GitHubNamespaceLimitRangeDefaults>(
    key: K,
    value: GitHubNamespaceLimitRangeDefaults[K],
  ) => {
    setGitHubNamespaceIsolationDefaults((current) => ({
      ...current,
      limit_range: {
        ...current.limit_range,
        [key]: value,
      },
    }));
  };

  const updateNamespaceNetworkPolicy = <K extends keyof GitHubNamespaceNetworkPolicyDefaults>(
    key: K,
    value: GitHubNamespaceNetworkPolicyDefaults[K],
  ) => {
    setGitHubNamespaceIsolationDefaults((current) => ({
      ...current,
      network_policy: {
        ...current.network_policy,
        [key]: value,
      },
    }));
  };

  const updateMigrationGenerationBudget = <K extends keyof MigrationGenerationBudgetConfig>(
    key: K,
    value: MigrationGenerationBudgetConfig[K],
  ) => {
    setGitHubNamespaceIsolationDefaults((current) => ({
      ...current,
      migration_generation_budget: {
        ...current.migration_generation_budget,
        [key]: value,
      },
    }));
    if (typeof key === "string") {
      const migrationKey = key as MigrationGenerationSettingField;
      setGitHubMigrationFieldErrors((current) => {
        if (!current[migrationKey]) {
          return current;
        }
        const next = { ...current };
        delete next[migrationKey];
        return next;
      });
    }
    setGitHubMigrationAdjustmentReason(null);
    setGitHubMigrationCapReasons({});
  };

  const updateMigrationGenerationSafety = <K extends keyof MigrationGenerationSafetyConfig>(
    key: K,
    value: MigrationGenerationSafetyConfig[K],
  ) => {
    setGitHubNamespaceIsolationDefaults((current) => ({
      ...current,
      migration_generation_safety: {
        ...current.migration_generation_safety,
        [key]: value,
      },
    }));
    if (typeof key === "string") {
      const migrationKey = key as MigrationGenerationSettingField;
      setGitHubMigrationFieldErrors((current) => {
        if (!current[migrationKey]) {
          return current;
        }
        const next = { ...current };
        delete next[migrationKey];
        return next;
      });
    }
    setGitHubMigrationAdjustmentReason(null);
    setGitHubMigrationCapReasons({});
  };

  const handleSaveGitHubPublishConfig = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setGitHubPublishConfigMessage(null);
    setGitHubPublishConfigError(null);
    setGitHubMigrationFieldErrors({});
    setGitHubMigrationAdjustmentReason(null);
    setGitHubMigrationCapReasons({});

    const validation = validateGitHubPublishConfigInputs({
      ownerInput: githubPublishOwnerInput,
      defaultBranchInput: githubPublishDefaultBranchInput,
      basePathInput: githubPublishBasePathInput,
      deployWorkflowModeInput: githubPublishDeployWorkflowModeInput,
      targetEnvironmentKeyInput: githubPublishTargetEnvironmentKeyInput,
      managedGkeClusterNameInput: githubPublishManagedGkeClusterNameInput,
      managedGkeClusterLocationInput: githubPublishManagedGkeClusterLocationInput,
      managedGkeProjectIdInput: githubPublishManagedGkeProjectIdInput,
      namespaceIsolationDefaults: githubNamespaceIsolationDefaults,
      enabled: githubPublishEnabled,
    });
    if (validation.blockingError) {
      setGitHubPublishConfigError(validation.blockingError);
      return;
    }

    setGitHubPublishConfigSubmitting(true);
    const requestedNamespaceDefaults = normalizeNamespaceIsolationDefaults(githubNamespaceIsolationDefaults);
    try {
      const managedDeployKeyValue = githubPublishManagedDeployKeyInput.trim();
      const payload: GitHubPublishConfigUpdateRequest = {
        owner: validation.owner || "",
        default_branch: validation.defaultBranch,
        base_path: validation.basePath,
        deploy_workflow_mode: validation.deployWorkflowMode,
        target_environment_key: validation.targetEnvironmentKey,
        github_repository_auto_create_enabled: githubRepositoryAutoCreateEnabled,
        managed_gke_cluster_name: validation.managedGkeClusterName,
        managed_gke_cluster_location: validation.managedGkeClusterLocation,
        managed_gke_project_id: validation.managedGkeProjectId,
        namespace_isolation_defaults: requestedNamespaceDefaults,
        enabled: githubPublishEnabled,
      };
      if (managedDeployKeyValue) {
        payload.managed_gcp_deploy_key_value = managedDeployKeyValue;
      }
      if (githubPublishManagedDeployKeyClear) {
        payload.managed_gcp_deploy_key_clear = true;
      }

      const updated = await updateGitHubPublishConfig(context.token, payload);
      setGitHubPublishConfigError(null);

      try {
        const effectiveNamespaceDefaults = normalizeNamespaceIsolationDefaults(
          updated.namespace_isolation_effective_defaults ?? updated.namespace_isolation_defaults,
        );
        const requestedSafety = requestedNamespaceDefaults.migration_generation_safety;
        const effectiveSafety = effectiveNamespaceDefaults.migration_generation_safety;
        const requestedBudget = requestedNamespaceDefaults.migration_generation_budget;
        const effectiveBudget = effectiveNamespaceDefaults.migration_generation_budget;
        const capReasonsCount = Object.keys(updated.namespace_isolation_cap_reasons || {}).length;
        const migrationAdjusted =
          requestedSafety.migration_provider_timeout_seconds !== effectiveSafety.migration_provider_timeout_seconds ||
          requestedSafety.migration_max_final_input_chars !== effectiveSafety.migration_max_final_input_chars ||
          requestedSafety.migration_max_difficulty_score !== effectiveSafety.migration_max_difficulty_score ||
          requestedSafety.migration_compact_page_limit !== effectiveSafety.migration_compact_page_limit ||
          requestedSafety.migration_compact_media_asset_limit !== effectiveSafety.migration_compact_media_asset_limit ||
          requestedSafety.migration_compact_recommendation_limit !==
            effectiveSafety.migration_compact_recommendation_limit ||
          requestedBudget.migration_context_budget_chars !== effectiveBudget.migration_context_budget_chars ||
          requestedBudget.migration_recommendation_limit !== effectiveBudget.migration_recommendation_limit ||
          requestedBudget.migration_competitor_limit !== effectiveBudget.migration_competitor_limit ||
          requestedBudget.migration_source_page_summary_limit !==
            effectiveBudget.migration_source_page_summary_limit ||
          requestedBudget.migration_media_asset_limit !== effectiveBudget.migration_media_asset_limit ||
          requestedBudget.migration_generated_page_limit !== effectiveBudget.migration_generated_page_limit ||
          requestedBudget.migration_generated_file_limit !== effectiveBudget.migration_generated_file_limit;
        applyGitHubPublishConfigInputs(updated, {
          setOwner: setGitHubPublishOwnerInput,
          setDefaultBranch: setGitHubPublishDefaultBranchInput,
          setBasePath: setGitHubPublishBasePathInput,
          setDeployWorkflowMode: setGitHubPublishDeployWorkflowModeInput,
          setTargetEnvironmentKey: setGitHubPublishTargetEnvironmentKeyInput,
          setManagedGkeClusterName: setGitHubPublishManagedGkeClusterNameInput,
          setManagedGkeClusterLocation: setGitHubPublishManagedGkeClusterLocationInput,
          setManagedGkeProjectId: setGitHubPublishManagedGkeProjectIdInput,
          setRepositoryAutoCreateEnabled: setGitHubRepositoryAutoCreateEnabled,
          setManagedDeployKeyConfigured: setGitHubPublishManagedDeployKeyConfigured,
          setManagedDeployKeyUpdatedAt: setGitHubPublishManagedDeployKeyUpdatedAt,
          clearManagedDeployKeyInput: () => setGitHubPublishManagedDeployKeyInput(""),
          setManagedDeployKeyClear: setGitHubPublishManagedDeployKeyClear,
          setNamespaceIsolationDefaults: setGitHubNamespaceIsolationDefaults,
          setPersistedNamespaceIsolationDefaults: setGitHubPersistedNamespaceIsolationDefaults,
          setMigrationCapReasons: setGitHubMigrationCapReasons,
          setEnabled: setGitHubPublishEnabled,
        });
        setGitHubMigrationAdjustmentReason(
          migrationAdjusted || capReasonsCount > 0 ? "backend_adjusted_values" : null,
        );
      } catch {
        setGitHubMigrationAdjustmentReason(null);
        setGitHubMigrationCapReasons({});
      }
      setGitHubPublishConfigMessage("GitHub publish configuration saved.");
    } catch (err) {
      if (err instanceof ApiRequestError && err.status === 422) {
        const fieldErrors = extractMigrationFieldErrorsFromMessage(err.message, requestedNamespaceDefaults);
        setGitHubMigrationFieldErrors(fieldErrors);
        if (Object.keys(fieldErrors).length > 0) {
          setGitHubMigrationAdjustmentReason("backend_validation_rejected");
          setGitHubPublishConfigError(
            "Backend validation rejected one or more migration generation settings. Review highlighted fields and try again.",
          );
        } else {
          setGitHubPublishConfigError(safeGitHubPublishConfigUpdateErrorMessage(err));
        }
      } else {
        setGitHubPublishConfigError(safeGitHubPublishConfigUpdateErrorMessage(err));
      }
    } finally {
      setGitHubPublishConfigSubmitting(false);
    }
  };

  const handleSiteDraftChange = (
    siteId: string,
    field: "name" | "url" | "searchConsolePropertyUrl",
    value: string,
  ) => {
    setSiteDraftsById((current) => {
      const existing = current[siteId] || {
        name: "",
        url: "",
        searchConsolePropertyUrl: "",
        searchConsoleEnabled: false,
      };
      return {
        ...current,
        [siteId]: {
          ...existing,
          [field]: value,
        },
      };
    });
  };

  const handleSiteDraftToggle = (siteId: string, searchConsoleEnabled: boolean) => {
    setSiteDraftsById((current) => {
      const existing = current[siteId] || {
        name: "",
        url: "",
        searchConsolePropertyUrl: "",
        searchConsoleEnabled: false,
      };
      return {
        ...current,
        [siteId]: {
          ...existing,
          searchConsoleEnabled,
        },
      };
    });
  };

  const handleSaveSite = async (site: SEOSite) => {
    const draft = siteDraftsById[site.id];
    const normalizedName = (draft?.name || "").trim();
    if (!normalizedName) {
      setSiteManagementError("Site name cannot be empty.");
      setSiteManagementMessage(null);
      return;
    }

    let normalizedUrl: string;
    try {
      normalizedUrl = parseAdminSiteUrl(draft?.url || "");
    } catch (err) {
      setSiteManagementError(err instanceof Error ? err.message : "Site URL is invalid.");
      setSiteManagementMessage(null);
      return;
    }

    const normalizedSearchConsolePropertyUrl = (draft?.searchConsolePropertyUrl || "").trim();

    setSiteManagementError(null);
    setSiteManagementMessage(null);
    setUpdatingSiteId(site.id);
    try {
      const updatedSite = await updateAdminSite(context.token, context.businessId, site.id, {
        name: normalizedName,
        url: normalizedUrl,
        search_console_property_url: normalizedSearchConsolePropertyUrl || null,
        search_console_enabled: draft?.searchConsoleEnabled ?? false,
      });
      await context.refreshSites();
      setSiteManagementMessage(`Site ${updatedSite.display_name} updated.`);
    } catch (err) {
      setSiteManagementError(safeAdminSiteUpdateErrorMessage(err));
    } finally {
      setUpdatingSiteId(null);
    }
  };

  const handlePrepareDeletePlan = async (site: SEOSite) => {
    setSiteManagementError(null);
    setSiteManagementMessage(null);
    setSiteDeleteResult(null);
    setPreparingSiteDeleteId(site.id);
    try {
      const plan = await prepareAdminSiteDeletePlan(context.token, context.businessId, site.id);
      setSiteDeletePlanSiteId(site.id);
      setSiteDeletePlan(plan);
      setSiteDeleteForm({
        confirmationPhrase: "",
        acknowledgeDeleteDatabaseRecords: false,
        deleteGitHubRepo: plan.execution_defaults.delete_github_repo,
        acknowledgeDeleteGitHubRepo: false,
        deleteRuntimeResources: plan.execution_defaults.delete_runtime_resources,
        acknowledgeDeleteRuntimeResources: false,
        deleteDnsResources: plan.execution_defaults.delete_dns_resources,
        acknowledgeDeleteDnsResources: false,
        forceDeleteActive: plan.execution_defaults.force_delete_active,
      });
      setSiteManagementMessage(`Delete plan prepared for ${plan.site_name}.`);
    } catch (err) {
      setSiteManagementError(safeAdminSiteDeleteErrorMessage(err));
    } finally {
      setPreparingSiteDeleteId(null);
    }
  };

  const handleSiteDeleteFormToggle = (field: keyof SiteDeleteFormState, checked: boolean) => {
    setSiteDeleteForm((current) => {
      const nextState: SiteDeleteFormState = {
        ...current,
        [field]: checked,
      };
      if (field === "deleteGitHubRepo" && !checked) {
        nextState.acknowledgeDeleteGitHubRepo = false;
      }
      if (field === "deleteRuntimeResources" && !checked) {
        nextState.acknowledgeDeleteRuntimeResources = false;
      }
      if (field === "deleteDnsResources" && !checked) {
        nextState.acknowledgeDeleteDnsResources = false;
      }
      return nextState;
    });
  };

  const handleExecuteSiteDelete = async () => {
    if (!siteDeletePlan) {
      return;
    }

    const payload: SEOSiteDeleteExecuteRequest = {
      confirmation_phrase: siteDeleteForm.confirmationPhrase.trim(),
      acknowledge_delete_database_records: siteDeleteForm.acknowledgeDeleteDatabaseRecords,
      delete_github_repo: siteDeleteForm.deleteGitHubRepo,
      acknowledge_delete_github_repo: siteDeleteForm.acknowledgeDeleteGitHubRepo,
      delete_runtime_resources: siteDeleteForm.deleteRuntimeResources,
      acknowledge_delete_runtime_resources: siteDeleteForm.acknowledgeDeleteRuntimeResources,
      delete_dns_resources: siteDeleteForm.deleteDnsResources,
      acknowledge_delete_dns_resources: siteDeleteForm.acknowledgeDeleteDnsResources,
      force_delete_active: siteDeleteForm.forceDeleteActive,
    };

    setSiteManagementError(null);
    setSiteManagementMessage(null);
    setDeletingSiteId(siteDeletePlan.site_id);
    try {
      const result = await executeAdminSiteDelete(
        context.token,
        context.businessId,
        siteDeletePlan.site_id,
        payload,
      );
      setSiteDeleteResult(result);
      if (result.db_deleted) {
        await context.refreshSites();
      }
      setSiteManagementMessage(result.message);
    } catch (err) {
      setSiteManagementError(safeAdminSiteDeleteErrorMessage(err));
    } finally {
      setDeletingSiteId(null);
    }
  };

  const handleDismissSiteDeletePlan = () => {
    setSiteDeletePlanSiteId(null);
    setSiteDeletePlan(null);
    setSiteDeleteResult(null);
    setSiteDeleteForm(EMPTY_SITE_DELETE_FORM_STATE);
  };

  const runGcpLogsQuery = async (pageToken: string | null = null) => {
    const normalizedFilter = gcpLogsFilterInput.trim();
    if (!normalizedFilter) {
      setGcpLogsError("Cloud Logging filter is required.");
      setGcpLogsMessage(null);
      return;
    }

    setGcpLogsLoading(true);
    setGcpLogsError(null);
    setGcpLogsMessage(null);
    try {
      const normalizedStartTime = normalizeOptionalIsoTimeInput(gcpLogsStartTimeInput);
      const normalizedEndTime = normalizeOptionalIsoTimeInput(gcpLogsEndTimeInput);
      const requestPayload: {
        filter: string;
        page_size: number;
        page_token?: string;
        start_time?: string;
        end_time?: string;
      } = {
        filter: normalizedFilter,
        page_size: gcpLogsPageSize,
        page_token: pageToken || undefined,
      };
      if (normalizedStartTime) {
        requestPayload.start_time = normalizedStartTime;
      }
      if (normalizedEndTime) {
        requestPayload.end_time = normalizedEndTime;
      }
      const response = await queryGcpLogs(context.token, context.businessId, requestPayload);
      setGcpLogsEntries(response.entries);
      setGcpLogsNextPageToken(response.next_page_token || null);
      setGcpLogsOrderBy(response.order_by);
      setGcpLogsResourceScope(response.resource_scope);
      setGcpLogsEffectiveFilter(response.effective_filter || "");
      setGcpLogsDefaultTimeRangeApplied(Boolean(response.default_time_range_applied));
      setGcpLogsHasExecuted(true);
      if (response.entries.length === 0) {
        setGcpLogsMessage(
          response.default_time_range_applied
            ? `No logs matched this filter. Defaulting to ${GCP_LOGS_DEFAULT_TIME_WINDOW_LABEL}.`
            : "No logs matched this filter.",
        );
      } else if (pageToken) {
        setGcpLogsMessage(`Loaded next page with ${response.entries.length} log entries.`);
      } else {
        setGcpLogsMessage(
          response.default_time_range_applied
            ? `Retrieved ${response.entries.length} log entries. Defaulting to ${GCP_LOGS_DEFAULT_TIME_WINDOW_LABEL}.`
            : `Retrieved ${response.entries.length} log entries.`,
        );
      }
    } catch (err) {
      setGcpLogsError(safeGcpLogsQueryErrorMessage(err));
      setGcpLogsHasExecuted(true);
      if (!pageToken) {
        setGcpLogsEntries([]);
        setGcpLogsNextPageToken(null);
        setGcpLogsEffectiveFilter("");
        setGcpLogsDefaultTimeRangeApplied(false);
      }
    } finally {
      setGcpLogsLoading(false);
    }
  };

  const handleSubmitGcpLogsQuery = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    await runGcpLogsQuery();
  };

  const handleLoadNextGcpLogsPage = async () => {
    if (!gcpLogsNextPageToken || gcpLogsLoading) {
      return;
    }
    await runGcpLogsQuery(gcpLogsNextPageToken);
  };

  const handleToggleUserActive = async (user: Principal) => {
    const activating = !user.is_active;
    const actionLabel = activating ? "reactivate" : "deactivate";
    const confirmed = window.confirm(
      `Confirm ${actionLabel} for user "${user.id}"? This updates business access immediately.`,
    );
    if (!confirmed) {
      return;
    }

    setActionError(null);
    setActionSuccess(null);
    setActingPrincipalId(user.id);
    setIdentityActionError(null);
    setIdentityActionSuccess(null);
    setSubmitError(null);
    setSubmitSuccess(null);
    setIdentitySubmitError(null);
    setIdentitySubmitSuccess(null);
    try {
      if (activating) {
        await activatePrincipal(context.token, context.businessId, user.id);
      } else {
        await deactivatePrincipal(context.token, context.businessId, user.id);
      }
      const refreshed = await loadUsersData();
      setUsers(refreshed.users);
      setIdentities(refreshed.identities);
      setIdentityWarning(refreshed.identityWarning);
      setActionSuccess(
        activating ? `User ${user.id} reactivated.` : `User ${user.id} deactivated.`,
      );
    } catch (err) {
      setActionError(safePrincipalActionErrorMessage(err));
    } finally {
      setActingPrincipalId(null);
    }
  };

  const handleToggleIdentityActive = async (identity: PrincipalIdentity) => {
    const activating = !identity.is_active;
    const actionLabel = activating ? "reactivate" : "deactivate";
    const identityLabel = formatIdentityLabel(identity);
    const confirmed = window.confirm(
      `Confirm ${actionLabel} sign-in identity "${identityLabel}" for principal "${identity.principal_id}"?`,
    );
    if (!confirmed) {
      return;
    }

    setIdentityActionError(null);
    setIdentityActionSuccess(null);
    setActingIdentityId(identity.id);
    setActionError(null);
    setActionSuccess(null);
    setSubmitError(null);
    setSubmitSuccess(null);
    setIdentitySubmitError(null);
    setIdentitySubmitSuccess(null);
    try {
      if (activating) {
        await activatePrincipalIdentity(context.token, context.businessId, identity.id);
      } else {
        await deactivatePrincipalIdentity(context.token, context.businessId, identity.id);
      }
      const refreshed = await loadUsersData();
      setUsers(refreshed.users);
      setIdentities(refreshed.identities);
      setIdentityWarning(refreshed.identityWarning);
      setIdentityActionSuccess(
        activating
          ? `Identity ${identityLabel} reactivated.`
          : `Identity ${identityLabel} deactivated.`,
      );
    } catch (err) {
      setIdentityActionError(safeIdentityActionErrorMessage(err));
    } finally {
      setActingIdentityId(null);
    }
  };

  if (context.loading) {
    return (
      <PageContainer width="wide" density="compact">
        <SectionCard as="div">Loading users...</SectionCard>
      </PageContainer>
    );
  }
  if (context.error) {
    return (
      <PageContainer width="wide" density="compact">
        <SectionCard as="div">Error: {context.error}</SectionCard>
      </PageContainer>
    );
  }
  if (!isAdmin) {
    return (
      <PageContainer width="wide" density="compact">
        <SectionCard variant="support">
          <SectionHeader
            title={mode === "userMgmt" ? "User Mgmt" : "Admin"}
            subtitle="Business administration is available to admin principals only."
            headingLevel={1}
            variant="support"
          />
        </SectionCard>
      </PageContainer>
    );
  }

  return (
    <PageContainer width="wide" density="compact">
      <div className={mode === "admin" ? "stack" : "role-dashboard-landing"}>
        <AdminOverviewSection
          mode={mode}
          businessId={context.businessId}
          principalRole={principal?.role ?? null}
        >
          <div className="workspace-summary-strip role-summary-strip">
            {showUserManagement ? (
              <>
                <SummaryStatCard
                  label="Principals"
                  value={users.length}
                  detail={`${activeUsersCount} active`}
                  tone={activeUsersCount > 0 ? "success" : "warning"}
                  variant="elevated"
                />
                <SummaryStatCard
                  label="Sign-in identities"
                  value={identities.length}
                  detail={`${principalsWithoutIdentityCount} principals missing identity links`}
                  tone={principalsWithoutIdentityCount > 0 ? "warning" : "success"}
                  variant="elevated"
                />
              </>
            ) : null}
            {showAdminSettings ? (
              <>
                <SummaryStatCard
                  label="Managed sites"
                  value={context.sites.length}
                  detail={context.sites.length > 0 ? "Admin edit and delete controls available" : "No sites configured"}
                  tone={context.sites.length > 0 ? "neutral" : "warning"}
                  variant="elevated"
                />
                <SummaryStatCard
                  label="Settings health"
                  value={
                    settingsHealth.crawl.status === "invalid" ||
                    settingsHealth.competitorQuality.status === "invalid" ||
                    settingsHealth.competitorTimeouts.status === "invalid" ||
                    settingsHealth.notifications.status === "invalid"
                      ? "Review needed"
                      : "Stable"
                  }
                  detail="Crawl, competitor quality, timeouts, and notification channels"
                  tone={
                    settingsHealth.crawl.status === "invalid" ||
                    settingsHealth.competitorQuality.status === "invalid" ||
                    settingsHealth.competitorTimeouts.status === "invalid" ||
                    settingsHealth.notifications.status === "invalid"
                      ? "warning"
                      : "success"
                  }
                  variant="elevated"
                />
                <SummaryStatCard
                  label="GitHub publish target"
                  value={
                    githubPublishEnabled
                      ? githubPublishValidation.blockingError
                        ? "Needs review"
                        : githubPublishValidation.owner
                          ? "Enabled"
                          : "Needs setup"
                      : "Disabled"
                  }
                  detail={
                    githubPublishValidation.owner
                      ? `${githubPublishValidation.owner} @ ${githubPublishValidation.defaultBranch} (${githubPublishValidation.basePath})`
                      : "Configure GitHub account/owner, branch fallback, and base path for migration publish."
                  }
                  tone={
                    githubPublishEnabled
                      ? githubPublishValidation.blockingError
                        ? "warning"
                        : githubPublishValidation.owner
                        ? "success"
                        : "warning"
                      : "neutral"
                  }
                  variant="elevated"
                />
              </>
            ) : null}
          </div>
          {showUserManagement ? (
            <div className="link-row">
              <span className="hint muted">Principals: {users.length}</span>
              <span className="hint muted">Active principals: {activeUsersCount}</span>
              <span className="hint muted">Sign-in identities: {identities.length}</span>
              <span className="hint muted">Principals without identity: {principalsWithoutIdentityCount}</span>
            </div>
          ) : null}
          {showAdminSettings ? (
            <>
              <p className="hint muted">
                Admin configures governance and platform defaults. Workflow execution remains on dedicated operational routes.
              </p>
              <AdminSectionNav />
            </>
          ) : null}
        </AdminOverviewSection>

          {showUserManagement ? (
            <>
              <SectionCard variant="summary" className="role-surface-support">
                <SectionHeader
                  title="Create User"
                  subtitle="Add a principal to this business and assign an initial role."
                  headingLevel={2}
                  variant="support"
                />
                <FormContainer onSubmit={(event) => void handleCreateUser(event)}>
                  <label htmlFor="principal-id">User ID</label>
                  <input
                    id="principal-id"
                    value={principalId}
                    onChange={(event) => setPrincipalId(event.target.value)}
                    placeholder="user@example.com"
                    required
                  />

                  <label htmlFor="display-name">Display Name (optional)</label>
                  <input
                    id="display-name"
                    value={displayName}
                    onChange={(event) => setDisplayName(event.target.value)}
                    placeholder="Operator Name"
                  />

                  <label htmlFor="user-role">Role</label>
                  <select
                    id="user-role"
                    className="operator-select"
                    value={role}
                    onChange={(event) => setRole(event.target.value as PrincipalRole)}
                  >
                    <option value="operator">operator</option>
                    <option value="admin">admin</option>
                  </select>

                  <div className="form-actions">
                    <button className="button button-primary" type="submit" disabled={submitting}>
                      {submitting ? "Creating..." : "Create User"}
                    </button>
                  </div>
                </FormContainer>
              </SectionCard>

              <SectionCard variant="summary" className="role-surface-support">
                <SectionHeader
                  title="Create and Link Identity"
                  subtitle="Create a sign-in identity and map it to a principal in this business."
                  headingLevel={2}
                  variant="support"
                />
                <FormContainer onSubmit={(event) => void handleCreateAndLinkIdentity(event)}>
                  <label htmlFor="identity-principal">Principal</label>
                  <select
                    id="identity-principal"
                    className="operator-select"
                    value={identityPrincipalId}
                    onChange={(event) => setIdentityPrincipalId(event.target.value)}
                    required
                    disabled={users.length === 0 || identitySubmitting}
                  >
                    {users.length === 0 ? <option value="">No principals available</option> : null}
                    {users.map((user) => (
                      <option key={user.id} value={user.id}>
                        {user.id} ({user.role})
                      </option>
                    ))}
                  </select>

                  <label htmlFor="identity-provider">Provider</label>
                  <input
                    id="identity-provider"
                    value={identityProvider}
                    onChange={(event) => setIdentityProvider(event.target.value)}
                    placeholder="google"
                    required
                    disabled={identitySubmitting}
                  />

                  <label htmlFor="identity-provider-subject">Provider Subject</label>
                  <input
                    id="identity-provider-subject"
                    value={identityProviderSubject}
                    onChange={(event) => setIdentityProviderSubject(event.target.value)}
                    placeholder="provider subject"
                    required
                    disabled={identitySubmitting}
                  />

                  <label htmlFor="identity-email">Email (optional)</label>
                  <input
                    id="identity-email"
                    value={identityEmail}
                    onChange={(event) => setIdentityEmail(event.target.value)}
                    placeholder="user@example.com"
                    disabled={identitySubmitting}
                  />

                  <label htmlFor="identity-email-verified" className="checkbox-chip">
                    <input
                      id="identity-email-verified"
                      type="checkbox"
                      checked={identityEmailVerified}
                      onChange={(event) => setIdentityEmailVerified(event.target.checked)}
                      disabled={identitySubmitting}
                    />
                    Email verified
                  </label>

                  <label htmlFor="identity-is-active" className="checkbox-chip">
                    <input
                      id="identity-is-active"
                      type="checkbox"
                      checked={identityIsActive}
                      onChange={(event) => setIdentityIsActive(event.target.checked)}
                      disabled={identitySubmitting}
                    />
                    Identity active
                  </label>

                  {identityAlreadyLinkedToSelectedPrincipal ? (
                    <p className="hint warning">This identity is already linked to the selected principal.</p>
                  ) : null}
                  {identityLinkedToDifferentPrincipal ? (
                    <p className="hint warning">
                      This identity is already linked to principal{" "}
                      <code>{existingIdentityForProviderSubject?.principal_id}</code>.
                    </p>
                  ) : null}

                  <div className="form-actions">
                    <button
                      className="button button-primary"
                      type="submit"
                      disabled={
                        identitySubmitting ||
                        users.length === 0 ||
                        identityAlreadyLinkedToSelectedPrincipal ||
                        identityLinkedToDifferentPrincipal
                      }
                    >
                      {identitySubmitting ? "Creating and Linking..." : "Create and Link Identity"}
                    </button>
                  </div>
                </FormContainer>
              </SectionCard>
            </>
          ) : null}

        {showAdminSettings ? (
          <AuditCrawlSettingsSection>
            <SectionCard variant="summary" className="role-surface-support">
              <SectionHeader
                title="SEO Crawl Settings"
                subtitle="Configure crawl page limits used by SEO audits and automation for this business."
                headingLevel={2}
                variant="support"
              />
              <FormContainer onSubmit={(event) => void handleUpdateCrawlPageLimit(event)} noValidate>
                {settingsHealth.crawl.status === "invalid" ? (
                  <p className="hint warning">
                    Settings health: {settingsHealth.crawl.message}
                  </p>
                ) : null}
                <label htmlFor="seo-audit-crawl-max-pages">
                  <AdminLabelWithHelp
                    label="Crawl Page Limit"
                    helpText={`Sets the per-audit crawl ceiling. Allowed range: ${CRAWL_PAGE_LIMIT_MIN}-${CRAWL_PAGE_LIMIT_MAX}.`}
                  />
                </label>
                <input
                  id="seo-audit-crawl-max-pages"
                  type="number"
                  min={CRAWL_PAGE_LIMIT_MIN}
                  max={CRAWL_PAGE_LIMIT_MAX}
                  step={1}
                  value={crawlPageLimitInput}
                  onChange={(event) => setCrawlPageLimitInput(event.target.value)}
                  disabled={businessSettingsLoading || crawlPageLimitSubmitting}
                  required
                />
                <div className="form-actions">
                  <button
                    className="button button-primary"
                    type="submit"
                    disabled={businessSettingsLoading || crawlPageLimitSubmitting}
                  >
                    {crawlPageLimitSubmitting ? "Saving..." : "Save Crawl Limit"}
                  </button>
                </div>
                {businessSettingsLoading ? <p className="hint muted">Loading business settings...</p> : null}
                {crawlPageLimitMessage ? <p className="hint">{crawlPageLimitMessage}</p> : null}
                {crawlPageLimitError ? <p className="hint error">{crawlPageLimitError}</p> : null}
              </FormContainer>
            </SectionCard>
          </AuditCrawlSettingsSection>
        ) : null}

        {showAdminSettings ? (
        <CompetitorGenerationSettingsSection>
        <SectionCard variant="summary" className="role-surface-support">
          <SectionHeader
            title="AI Competitor Candidate Quality"
            subtitle="Tune deterministic competitor candidate quality and exclusion thresholds."
            headingLevel={2}
            variant="support"
          />
          <FormContainer className="form-container-full-width" onSubmit={(event) => void handleUpdateCompetitorCandidateQuality(event)} noValidate>
          {settingsHealth.competitorQuality.status === "invalid" ? (
            <p className="hint warning">
              Settings health: {settingsHealth.competitorQuality.message}
            </p>
          ) : null}
          <div className="admin-grid-two">
            <div className="stack-tight">
              <label htmlFor="competitor-candidate-min-relevance-score">
                <AdminLabelWithHelp
                  label="Minimum Relevance Score"
                  helpText="Controls how closely a competitor must match your business. Higher values are stricter; lower values increase recall."
                  testId="admin-help-minimum-relevance-score"
                />
              </label>
              <input
                id="competitor-candidate-min-relevance-score"
                type="number"
                min={COMPETITOR_MIN_RELEVANCE_SCORE_MIN}
                max={COMPETITOR_MIN_RELEVANCE_SCORE_MAX}
                step={1}
                value={candidateMinRelevanceScoreInput}
                onChange={(event) => setCandidateMinRelevanceScoreInput(event.target.value)}
                disabled={businessSettingsLoading || candidateQualitySubmitting}
                required
              />
            </div>

            <div className="stack-tight">
              <label htmlFor="competitor-candidate-big-box-penalty">
                <AdminLabelWithHelp
                  label="Big-Box Mismatch Penalty"
                  helpText="Reduces scoring for national big-box companies that do not match local SMB context."
                  testId="admin-help-big-box-mismatch-penalty"
                />
              </label>
              <input
                id="competitor-candidate-big-box-penalty"
                type="number"
                min={COMPETITOR_BIG_BOX_PENALTY_MIN}
                max={COMPETITOR_BIG_BOX_PENALTY_MAX}
                step={1}
                value={candidateBigBoxPenaltyInput}
                onChange={(event) => setCandidateBigBoxPenaltyInput(event.target.value)}
                disabled={businessSettingsLoading || candidateQualitySubmitting}
                required
              />
            </div>

            <div className="stack-tight">
              <label htmlFor="competitor-candidate-directory-penalty">
                <AdminLabelWithHelp
                  label="Directory/Aggregator Penalty"
                  helpText="Reduces scoring for directory/listing/aggregator sites so real business domains are prioritized."
                />
              </label>
              <input
                id="competitor-candidate-directory-penalty"
                type="number"
                min={COMPETITOR_DIRECTORY_PENALTY_MIN}
                max={COMPETITOR_DIRECTORY_PENALTY_MAX}
                step={1}
                value={candidateDirectoryPenaltyInput}
                onChange={(event) => setCandidateDirectoryPenaltyInput(event.target.value)}
                disabled={businessSettingsLoading || candidateQualitySubmitting}
                required
              />
            </div>

            <div className="stack-tight">
              <label htmlFor="competitor-candidate-local-alignment-bonus">
                <AdminLabelWithHelp
                  label="Local Alignment Bonus"
                  helpText="Boosts candidates that clearly serve the site market/location."
                />
              </label>
              <input
                id="competitor-candidate-local-alignment-bonus"
                type="number"
                min={COMPETITOR_LOCAL_ALIGNMENT_BONUS_MIN}
                max={COMPETITOR_LOCAL_ALIGNMENT_BONUS_MAX}
                step={1}
                value={candidateLocalAlignmentBonusInput}
                onChange={(event) => setCandidateLocalAlignmentBonusInput(event.target.value)}
                disabled={businessSettingsLoading || candidateQualitySubmitting}
                required
              />
            </div>
          </div>
            <div className="form-actions">
              <button
                className="button button-primary"
                type="submit"
                disabled={businessSettingsLoading || candidateQualitySubmitting}
              >
                {candidateQualitySubmitting ? "Saving..." : "Save Candidate Quality Settings"}
              </button>
            </div>
            {candidateQualityMessage ? <p className="hint">{candidateQualityMessage}</p> : null}
            {candidateQualityError ? <p className="hint error">{candidateQualityError}</p> : null}
          </FormContainer>
        </SectionCard>
        <SectionCard variant="summary" className="role-surface-support">
          <SectionHeader
            title="AI Competitor Generation Timeouts"
            subtitle="Set primary and degraded retry timeout windows for competitor generation."
            headingLevel={2}
            variant="support"
          />
          <FormContainer className="form-container-full-width" onSubmit={(event) => void handleUpdateCompetitorTimeoutSettings(event)} noValidate>
          {settingsHealth.competitorTimeouts.status === "invalid" ? (
            <p className="hint warning">
              Settings health: {settingsHealth.competitorTimeouts.message}
            </p>
          ) : null}

          <div className="admin-grid-two">
            <div className="stack-tight">
              <label htmlFor="competitor-primary-timeout-seconds">
                <AdminLabelWithHelp
                  label="Competitor Primary Timeout Seconds"
                  helpText={`Controls how long the first full competitor generation attempt may run. Raising it gives provider/search more time but increases operator wait; lowering it fails faster and relies more on degraded retry. Allowed range: ${COMPETITOR_TIMEOUT_SECONDS_MIN}-${COMPETITOR_TIMEOUT_SECONDS_MAX} seconds.`}
                  testId="admin-help-competitor-primary-timeout-seconds"
                />
              </label>
              <input
                id="competitor-primary-timeout-seconds"
                type="number"
                min={COMPETITOR_TIMEOUT_SECONDS_MIN}
                max={COMPETITOR_TIMEOUT_SECONDS_MAX}
                step={1}
                value={competitorPrimaryTimeoutInput}
                onChange={(event) => setCompetitorPrimaryTimeoutInput(event.target.value)}
                disabled={businessSettingsLoading || competitorTimeoutSubmitting}
                placeholder={String(DEFAULT_COMPETITOR_TIMEOUT_SECONDS)}
              />
            </div>

            <div className="stack-tight">
              <label htmlFor="competitor-degraded-timeout-seconds">
                <AdminLabelWithHelp
                  label="Competitor Degraded Retry Timeout Seconds"
                  helpText={`Controls the shorter fallback retry after primary generation struggles. Raising it may recover more candidates but increases wait time; lowering it returns faster with fewer candidates. Allowed range: ${COMPETITOR_TIMEOUT_SECONDS_MIN}-${COMPETITOR_TIMEOUT_SECONDS_MAX} seconds.`}
                  testId="admin-help-competitor-degraded-timeout-seconds"
                />
              </label>
              <input
                id="competitor-degraded-timeout-seconds"
                type="number"
                min={COMPETITOR_TIMEOUT_SECONDS_MIN}
                max={COMPETITOR_TIMEOUT_SECONDS_MAX}
                step={1}
                value={competitorDegradedTimeoutInput}
                onChange={(event) => setCompetitorDegradedTimeoutInput(event.target.value)}
                disabled={businessSettingsLoading || competitorTimeoutSubmitting}
                placeholder={String(DEFAULT_COMPETITOR_TIMEOUT_SECONDS)}
              />
            </div>
          </div>
            <div className="form-actions">
              <button
                className="button button-primary"
                type="submit"
                disabled={businessSettingsLoading || competitorTimeoutSubmitting}
              >
                {competitorTimeoutSubmitting ? "Saving..." : "Save Competitor Timeouts"}
              </button>
            </div>
            {competitorTimeoutMessage ? <p className="hint">{competitorTimeoutMessage}</p> : null}
            {competitorTimeoutError ? <p className="hint error">{competitorTimeoutError}</p> : null}
          </FormContainer>
        </SectionCard>
        </CompetitorGenerationSettingsSection>
        ) : null}

        {showAdminSettings ? (
        <AiPromptGovernanceSection>
        <SectionCard
          variant="summary"
          className="role-surface-support"
          data-testid="admin-card-ai-provider-governance"
        >
          <SectionHeader
            title="AI Provider & Prompt Governance"
            subtitle="Control the default model and governance behavior used when an AI run does not provide an explicit model."
            headingLevel={2}
            variant="support"
          />
          <div className="panel panel-compact stack-tight">
            <p className="hint muted">
              Default model governance applies across AI-backed workflows unless a run explicitly specifies a model.
            </p>
            <div className="admin-grid-two">
              <div className="stack-tight">
                <label htmlFor="default-ai-model">
                  <AdminLabelWithHelp
                    label="Default AI model"
                    helpText="Controls fallback model selection when no run-specific model is provided. Resolution order: explicit request, business admin default, deployment default, provider fallback. Changing this may affect cost, latency, output style, and compatibility."
                    testId="admin-help-default-ai-model"
                  />
                </label>
                <input
                  id="default-ai-model"
                  type="text"
                  value={defaultAiModelInput}
                  onChange={(event) => setDefaultAiModelInput(event.target.value)}
                  disabled={businessSettingsLoading || promptOverrideSubmitting}
                  placeholder="gpt-4o-mini"
                />
                <p className="hint muted">
                  Current source:{" "}
                  <strong>
                    {businessSettings?.default_ai_model
                      ? "Business admin override"
                      : "Deployment/default fallback"}
                  </strong>
                </p>
              </div>
            </div>
          </div>
        </SectionCard>
        <SectionCard
          variant="summary"
          className="role-surface-support"
          data-testid="admin-card-ai-prompt-overrides"
        >
          <SectionHeader
            title="AI Prompt Overrides"
            subtitle="Override competitor and recommendation prompts for this business scope."
            headingLevel={2}
            variant="support"
          />
          <FormContainer className="form-container-full-width" onSubmit={(event) => void handleSavePromptOverrides(event)} noValidate>
            <p className="hint muted">
              Prompt overrides affect future generated recommendations and competitor suggestions. Keep overrides bounded and contract-compatible.
            </p>
            <p className="hint muted">
              Migration draft provider timeout is managed in <strong>Migration Generation Safety</strong>.
            </p>
            {competitorPromptContractWarning.state === "legacy_alias" ? (
              <p className="hint warning" data-testid="competitor-prompt-override-warning">
                {competitorPromptContractWarning.message}
              </p>
            ) : null}
            {competitorPromptContractWarning.state === "invalid" ? (
              <p className="hint error" data-testid="competitor-prompt-override-warning">
                {competitorPromptContractWarning.message}
              </p>
            ) : null}
            <div className="panel panel-compact stack-tight">
              <strong>Prompt Overrides (high-impact)</strong>
              <div className="admin-grid-two">
                <div className="stack-tight">
                  <label htmlFor="ai-prompt-text-competitor">
                    <AdminLabelWithHelp
                      label="Competitor Prompt"
                      helpText="Controls how AI proposes competitor candidates. Changes affect future competitor generation only. Prompt output must preserve the strict JSON output contract; malformed prompt changes can break parsing or reduce candidate quality."
                      testId="admin-help-competitor-prompt"
                    />
                  </label>
                  <textarea
                    id="ai-prompt-text-competitor"
                    rows={7}
                    value={competitorPromptOverrideInput}
                    onChange={(event) => setCompetitorPromptOverrideInput(event.target.value)}
                    disabled={businessSettingsLoading || promptOverrideSubmitting}
                  />
                  <p className="hint muted">
                    Current source:{" "}
                    <strong>
                      {businessSettings?.ai_prompt_text_competitor
                        ? "Business admin override"
                        : "Deployment/default fallback"}
                    </strong>
                  </p>
                </div>

                <div className="stack-tight">
                  <label htmlFor="ai-prompt-text-recommendations">
                    <AdminLabelWithHelp
                      label="Recommendations Prompt"
                      helpText="Controls AI recommendation generation. Use this to tune tone, prioritization, and evidence framing while preserving required JSON/schema fields consumed by the UI. Malformed prompt changes can return invalid recommendations."
                      testId="admin-help-recommendations-prompt"
                    />
                  </label>
                  <textarea
                    id="ai-prompt-text-recommendations"
                    rows={7}
                    value={recommendationsPromptOverrideInput}
                    onChange={(event) => setRecommendationsPromptOverrideInput(event.target.value)}
                    disabled={businessSettingsLoading || promptOverrideSubmitting}
                  />
                  <p className="hint muted">
                    Current source:{" "}
                    <strong>
                      {businessSettings?.ai_prompt_text_recommendations
                        ? "Business admin override"
                        : "Deployment/default fallback"}
                    </strong>
                  </p>
                </div>
              </div>
            </div>

            <div className="form-actions">
              <button
                className="button button-primary"
                type="submit"
                disabled={businessSettingsLoading || promptOverrideSubmitting}
              >
                {promptOverrideSubmitting ? "Saving..." : "Save Prompt Overrides"}
              </button>
              <span className="admin-action-help-inline">
                <button
                  className="button button-tertiary"
                  type="button"
                  onClick={() => void handleClearPromptOverrides()}
                  disabled={businessSettingsLoading || promptOverrideSubmitting}
                >
                  Use Deployment Fallbacks
                </button>
                <AdminHelpIcon
                  label="Use Deployment Fallbacks"
                  helpText="Clears business-level prompt and default-model overrides so deployment defaults are used. This does not delete deployment configuration."
                  testId="admin-help-use-deployment-fallbacks"
                />
              </span>
            </div>
            {promptOverrideMessage ? <p className="hint">{promptOverrideMessage}</p> : null}
            {promptOverrideError ? <p className="hint error">{promptOverrideError}</p> : null}
          </FormContainer>
        </SectionCard>
        </AiPromptGovernanceSection>
        ) : null}

        {showAdminSettings ? (
        <PublishDeploymentConfigSection>
        <SectionCard variant="summary" className="role-surface-support">
          <SectionHeader
            title="GitHub Publish Configuration"
            subtitle="Set the admin-owned GitHub account/owner, branch fallback, deploy template mode, and target environment mapping used by migration publish/deploy control-plane orchestration."
            headingLevel={2}
            variant="support"
          />
          <FormContainer className="form-container-full-width" onSubmit={(event) => void handleSaveGitHubPublishConfig(event)} noValidate>
            <label htmlFor="github-publish-enabled" className="checkbox-chip">
              <input
                id="github-publish-enabled"
                type="checkbox"
                checked={githubPublishEnabled}
                onChange={(event) => setGitHubPublishEnabled(event.target.checked)}
                disabled={githubPublishConfigLoading || githubPublishConfigSubmitting}
              />
              Enable migration GitHub publish target
            </label>
            <p className="hint muted">
              Managed GKE target metadata and managed deploy secret status are admin-owned here. Secret values are
              write-only and never returned.
            </p>

            <div className="admin-grid-two">
              <div className="stack-tight">
                <label htmlFor="github-publish-owner">
                  <AdminLabelWithHelp
                    label="GitHub account/owner"
                    helpText="Admin-owned repository owner/account used for managed migration publish targets."
                  />
                </label>
                <input
                  id="github-publish-owner"
                  type="text"
                  value={githubPublishOwnerInput}
                  onChange={(event) => setGitHubPublishOwnerInput(event.target.value)}
                  disabled={githubPublishConfigLoading || githubPublishConfigSubmitting}
                  placeholder="mhanson13"
                />
                {githubPublishValidation.ownerError ? (
                  <p className="hint error">{githubPublishValidation.ownerError}</p>
                ) : null}
              </div>

              <div className="stack-tight">
                <label htmlFor="github-publish-default-branch">
                  <AdminLabelWithHelp
                    label="Default Branch"
                    helpText="Fallback branch used when workspace deploy/publish config does not override branch."
                  />
                </label>
                <input
                  id="github-publish-default-branch"
                  type="text"
                  value={githubPublishDefaultBranchInput}
                  onChange={(event) => setGitHubPublishDefaultBranchInput(event.target.value)}
                  disabled={githubPublishConfigLoading || githubPublishConfigSubmitting}
                  placeholder="main"
                />
                {githubPublishValidation.defaultBranchError ? (
                  <p className="hint error">{githubPublishValidation.defaultBranchError}</p>
                ) : null}
              </div>

              <div className="stack-tight">
                <label htmlFor="github-publish-base-path">
                  <AdminLabelWithHelp
                    label="Base Path"
                    helpText="Use / for repo root or a subpath such as /site."
                  />
                </label>
                <input
                  id="github-publish-base-path"
                  type="text"
                  value={githubPublishBasePathInput}
                  onChange={(event) => setGitHubPublishBasePathInput(event.target.value)}
                  disabled={githubPublishConfigLoading || githubPublishConfigSubmitting}
                  placeholder="/"
                />
                {githubPublishValidation.basePathError ? (
                  <p className="hint error">{githubPublishValidation.basePathError}</p>
                ) : null}
                {githubPublishValidation.basePathWarning ? (
                  <p className="hint warning">{githubPublishValidation.basePathWarning}</p>
                ) : null}
              </div>

              <div className="stack-tight">
                <label htmlFor="github-publish-deploy-workflow-mode">
                  <AdminLabelWithHelp
                    label="Deploy Workflow Mode"
                    helpText="Platform-managed workflow template mode used for per-site workflow generation."
                  />
                </label>
                <select
                  id="github-publish-deploy-workflow-mode"
                  value={githubPublishDeployWorkflowModeInput}
                  onChange={(event) => setGitHubPublishDeployWorkflowModeInput(event.target.value)}
                  disabled={githubPublishConfigLoading || githubPublishConfigSubmitting}
                >
                  <option value="site_repo_template_v1">site_repo_template_v1</option>
                </select>
                {githubPublishValidation.deployWorkflowModeError ? (
                  <p className="hint error">{githubPublishValidation.deployWorkflowModeError}</p>
                ) : null}
              </div>

              <div className="stack-tight">
                <label htmlFor="github-publish-target-environment-key">
                  <AdminLabelWithHelp
                    label="Target Environment Key"
                    helpText="Admin-owned environment mapping key consumed by managed workflow template generation."
                  />
                </label>
                <input
                  id="github-publish-target-environment-key"
                  type="text"
                  value={githubPublishTargetEnvironmentKeyInput}
                  onChange={(event) => setGitHubPublishTargetEnvironmentKeyInput(event.target.value)}
                  disabled={githubPublishConfigLoading || githubPublishConfigSubmitting}
                  placeholder="gke_prod"
                />
                {githubPublishValidation.targetEnvironmentKeyError ? (
                  <p className="hint error">{githubPublishValidation.targetEnvironmentKeyError}</p>
                ) : null}
              </div>

              <div className="stack-tight">
                <label htmlFor="github-publish-repository-auto-create-enabled" className="checkbox-chip">
                  <input
                    id="github-publish-repository-auto-create-enabled"
                    type="checkbox"
                    checked={githubRepositoryAutoCreateEnabled}
                    onChange={(event) => setGitHubRepositoryAutoCreateEnabled(event.target.checked)}
                    disabled={githubPublishConfigLoading || githubPublishConfigSubmitting}
                  />
                  Enable managed repository auto-create for missing publish targets
                  <AdminHelpIcon
                    label="Enable managed repository auto-create for missing publish targets"
                    helpText="When enabled, runtime GitHub token may create missing repositories under configured owner."
                  />
                </label>
              </div>

              <div className="stack-tight">
                <label htmlFor="github-publish-managed-gke-cluster-name">
                  <AdminLabelWithHelp
                    label="Managed GKE Cluster Name"
                    helpText="Cluster name used for managed deploy diagnostics/contract targeting."
                    testId="admin-help-managed-gke-cluster-name"
                  />
                </label>
                <input
                  id="github-publish-managed-gke-cluster-name"
                  type="text"
                  value={githubPublishManagedGkeClusterNameInput}
                  onChange={(event) => setGitHubPublishManagedGkeClusterNameInput(event.target.value)}
                  disabled={githubPublishConfigLoading || githubPublishConfigSubmitting}
                  placeholder="mbsrn-cluster"
                />
                {githubPublishValidation.managedGkeClusterNameError ? (
                  <p className="hint error">{githubPublishValidation.managedGkeClusterNameError}</p>
                ) : null}
              </div>

              <div className="stack-tight">
                <label htmlFor="github-publish-managed-gke-cluster-location">
                  <AdminLabelWithHelp
                    label="Managed GKE Cluster Location"
                    helpText="Region/zone for managed GKE target used by deploy diagnostics."
                  />
                </label>
                <input
                  id="github-publish-managed-gke-cluster-location"
                  type="text"
                  value={githubPublishManagedGkeClusterLocationInput}
                  onChange={(event) => setGitHubPublishManagedGkeClusterLocationInput(event.target.value)}
                  disabled={githubPublishConfigLoading || githubPublishConfigSubmitting}
                  placeholder="us-central1"
                />
                {githubPublishValidation.managedGkeClusterLocationError ? (
                  <p className="hint error">{githubPublishValidation.managedGkeClusterLocationError}</p>
                ) : null}
              </div>

              <div className="stack-tight">
                <label htmlFor="github-publish-managed-gke-project-id">
                  <AdminLabelWithHelp
                    label="Managed GCP Project ID"
                    helpText="Project id for managed deploy/runtime contract checks."
                  />
                </label>
                <input
                  id="github-publish-managed-gke-project-id"
                  type="text"
                  value={githubPublishManagedGkeProjectIdInput}
                  onChange={(event) => setGitHubPublishManagedGkeProjectIdInput(event.target.value)}
                  disabled={githubPublishConfigLoading || githubPublishConfigSubmitting}
                  placeholder="mbsrn-prod"
                />
                {githubPublishValidation.managedGkeProjectIdError ? (
                  <p className="hint error">{githubPublishValidation.managedGkeProjectIdError}</p>
                ) : null}
              </div>
            </div>
            <p className="hint muted">
              Managed GKE target fields above are admin-owned source of truth. Repo vars/secrets remain legacy fallback
              only.
            </p>

            <div className="panel panel-compact stack-tight">
              <strong>Managed Deploy Secret (high-risk)</strong>
              <p className="hint muted">
                Deployment configuration controls publish/deploy target behavior. Secret values are write-only and never returned.
              </p>
              <label htmlFor="github-publish-managed-gcp-deploy-key">
                Managed Deploy Secret (GCP_DEPLOY_KEY)
              </label>
              <textarea
                id="github-publish-managed-gcp-deploy-key"
                rows={3}
                value={githubPublishManagedDeployKeyInput}
                onChange={(event) => setGitHubPublishManagedDeployKeyInput(event.target.value)}
                disabled={githubPublishConfigLoading || githubPublishConfigSubmitting}
                placeholder="Paste service-account JSON to set or rotate (write-only)"
                autoComplete="off"
                spellCheck={false}
              />
              <label htmlFor="github-publish-managed-gcp-deploy-key-clear" className="checkbox-chip">
                <input
                  id="github-publish-managed-gcp-deploy-key-clear"
                  type="checkbox"
                  checked={githubPublishManagedDeployKeyClear}
                  onChange={(event) => setGitHubPublishManagedDeployKeyClear(event.target.checked)}
                  disabled={githubPublishConfigLoading || githubPublishConfigSubmitting}
                />
                Clear managed deploy secret on save
              </label>
              <p className="hint muted">
                In-house managed secret for managed deploy targets. The value is never returned after save.
              </p>
              <WorkspaceMetadataGrid>
                <WorkspaceMetadataItem label="Managed deploy secret configured">
                  <span>{githubPublishManagedDeployKeyConfigured ? "Yes" : "No"}</span>
                </WorkspaceMetadataItem>
                <WorkspaceMetadataItem label="Managed deploy secret updated">
                  <span>{githubPublishManagedDeployKeyUpdatedAt || "Never"}</span>
                </WorkspaceMetadataItem>
              </WorkspaceMetadataGrid>
            </div>

            <ManagedNamespacePolicySection />

            <div className="admin-grid-two">
              <div className="panel panel-compact stack-tight">
                <strong>Namespace ResourceQuota defaults</strong>
                <label htmlFor="github-publish-resource-quota-enabled" className="checkbox-chip">
                  <input
                    id="github-publish-resource-quota-enabled"
                    type="checkbox"
                    checked={githubNamespaceIsolationDefaults.resource_quota.enabled}
                    onChange={(event) => updateNamespaceResourceQuota("enabled", event.target.checked)}
                    disabled={githubPublishConfigLoading || githubPublishConfigSubmitting}
                  />
                  Enable ResourceQuota for managed site namespaces
                </label>
                <div className="admin-grid-two admin-grid-two-compact">
                <label htmlFor="github-publish-resource-quota-requests-cpu" className="stack-tight">
                  <span className="hint muted">Requests CPU</span>
                  <input
                    id="github-publish-resource-quota-requests-cpu"
                    type="text"
                    value={githubNamespaceIsolationDefaults.resource_quota.requests_cpu}
                    onChange={(event) => updateNamespaceResourceQuota("requests_cpu", event.target.value)}
                    disabled={githubPublishConfigLoading || githubPublishConfigSubmitting}
                  />
                </label>
                <label htmlFor="github-publish-resource-quota-requests-memory" className="stack-tight">
                  <span className="hint muted">Requests Memory</span>
                  <input
                    id="github-publish-resource-quota-requests-memory"
                    type="text"
                    value={githubNamespaceIsolationDefaults.resource_quota.requests_memory}
                    onChange={(event) => updateNamespaceResourceQuota("requests_memory", event.target.value)}
                    disabled={githubPublishConfigLoading || githubPublishConfigSubmitting}
                  />
                </label>
                <label htmlFor="github-publish-resource-quota-limits-cpu" className="stack-tight">
                  <span className="hint muted">Limits CPU</span>
                  <input
                    id="github-publish-resource-quota-limits-cpu"
                    type="text"
                    value={githubNamespaceIsolationDefaults.resource_quota.limits_cpu}
                    onChange={(event) => updateNamespaceResourceQuota("limits_cpu", event.target.value)}
                    disabled={githubPublishConfigLoading || githubPublishConfigSubmitting}
                  />
                </label>
                <label htmlFor="github-publish-resource-quota-limits-memory" className="stack-tight">
                  <span className="hint muted">Limits Memory</span>
                  <input
                    id="github-publish-resource-quota-limits-memory"
                    type="text"
                    value={githubNamespaceIsolationDefaults.resource_quota.limits_memory}
                    onChange={(event) => updateNamespaceResourceQuota("limits_memory", event.target.value)}
                    disabled={githubPublishConfigLoading || githubPublishConfigSubmitting}
                  />
                </label>
                </div>
                <div className="admin-grid-two admin-grid-two-compact">
                <label htmlFor="github-publish-resource-quota-pods" className="stack-tight">
                  <span className="hint muted">Pods</span>
                  <input
                    id="github-publish-resource-quota-pods"
                    type="number"
                    min={0}
                    max={999999}
                    step={1}
                    value={githubNamespaceIsolationDefaults.resource_quota.pods}
                    onChange={(event) =>
                      updateNamespaceResourceQuota(
                        "pods",
                        Number.parseInt(event.target.value, 10) || 0,
                      )
                    }
                    disabled={githubPublishConfigLoading || githubPublishConfigSubmitting}
                  />
                </label>
                <label htmlFor="github-publish-resource-quota-services" className="stack-tight">
                  <span className="hint muted">Services</span>
                  <input
                    id="github-publish-resource-quota-services"
                    type="number"
                    min={0}
                    max={999999}
                    step={1}
                    value={githubNamespaceIsolationDefaults.resource_quota.services}
                    onChange={(event) =>
                      updateNamespaceResourceQuota(
                        "services",
                        Number.parseInt(event.target.value, 10) || 0,
                      )
                    }
                    disabled={githubPublishConfigLoading || githubPublishConfigSubmitting}
                  />
                </label>
                <label htmlFor="github-publish-resource-quota-configmaps" className="stack-tight">
                  <span className="hint muted">ConfigMaps</span>
                  <input
                    id="github-publish-resource-quota-configmaps"
                    type="number"
                    min={0}
                    max={999999}
                    step={1}
                    value={githubNamespaceIsolationDefaults.resource_quota.configmaps}
                    onChange={(event) =>
                      updateNamespaceResourceQuota(
                        "configmaps",
                        Number.parseInt(event.target.value, 10) || 0,
                      )
                    }
                    disabled={githubPublishConfigLoading || githubPublishConfigSubmitting}
                  />
                </label>
                <label htmlFor="github-publish-resource-quota-secrets" className="stack-tight">
                  <span className="hint muted">Secrets</span>
                  <input
                    id="github-publish-resource-quota-secrets"
                    type="number"
                    min={0}
                    max={999999}
                    step={1}
                    value={githubNamespaceIsolationDefaults.resource_quota.secrets}
                    onChange={(event) =>
                      updateNamespaceResourceQuota(
                        "secrets",
                        Number.parseInt(event.target.value, 10) || 0,
                      )
                    }
                    disabled={githubPublishConfigLoading || githubPublishConfigSubmitting}
                  />
                </label>
                <label htmlFor="github-publish-resource-quota-pvcs" className="stack-tight">
                  <span className="hint muted">PersistentVolumeClaims</span>
                  <input
                    id="github-publish-resource-quota-pvcs"
                    type="number"
                    min={0}
                    max={999999}
                    step={1}
                    value={githubNamespaceIsolationDefaults.resource_quota.persistentvolumeclaims}
                    onChange={(event) =>
                      updateNamespaceResourceQuota(
                        "persistentvolumeclaims",
                        Number.parseInt(event.target.value, 10) || 0,
                      )
                    }
                    disabled={githubPublishConfigLoading || githubPublishConfigSubmitting}
                  />
                </label>
                </div>
              </div>

              <div className="panel panel-compact stack-tight">
                <strong>Namespace LimitRange defaults</strong>
                <label htmlFor="github-publish-limit-range-enabled" className="checkbox-chip">
                  <input
                    id="github-publish-limit-range-enabled"
                    type="checkbox"
                    checked={githubNamespaceIsolationDefaults.limit_range.enabled}
                    onChange={(event) => updateNamespaceLimitRange("enabled", event.target.checked)}
                    disabled={githubPublishConfigLoading || githubPublishConfigSubmitting}
                  />
                  Enable LimitRange for managed site namespaces
                </label>
                <div className="admin-grid-two admin-grid-two-compact">
                <label htmlFor="github-publish-limit-range-default-cpu" className="stack-tight">
                  <span className="hint muted">Default CPU</span>
                  <input
                    id="github-publish-limit-range-default-cpu"
                    type="text"
                    value={githubNamespaceIsolationDefaults.limit_range.default_cpu}
                    onChange={(event) => updateNamespaceLimitRange("default_cpu", event.target.value)}
                    disabled={githubPublishConfigLoading || githubPublishConfigSubmitting}
                  />
                </label>
                <label htmlFor="github-publish-limit-range-default-memory" className="stack-tight">
                  <span className="hint muted">Default Memory</span>
                  <input
                    id="github-publish-limit-range-default-memory"
                    type="text"
                    value={githubNamespaceIsolationDefaults.limit_range.default_memory}
                    onChange={(event) => updateNamespaceLimitRange("default_memory", event.target.value)}
                    disabled={githubPublishConfigLoading || githubPublishConfigSubmitting}
                  />
                </label>
                <label htmlFor="github-publish-limit-range-default-request-cpu" className="stack-tight">
                  <span className="hint muted">Default request CPU</span>
                  <input
                    id="github-publish-limit-range-default-request-cpu"
                    type="text"
                    value={githubNamespaceIsolationDefaults.limit_range.default_request_cpu}
                    onChange={(event) => updateNamespaceLimitRange("default_request_cpu", event.target.value)}
                    disabled={githubPublishConfigLoading || githubPublishConfigSubmitting}
                  />
                </label>
                <label htmlFor="github-publish-limit-range-default-request-memory" className="stack-tight">
                  <span className="hint muted">Default request memory</span>
                  <input
                    id="github-publish-limit-range-default-request-memory"
                    type="text"
                    value={githubNamespaceIsolationDefaults.limit_range.default_request_memory}
                    onChange={(event) => updateNamespaceLimitRange("default_request_memory", event.target.value)}
                    disabled={githubPublishConfigLoading || githubPublishConfigSubmitting}
                  />
                </label>
                <label htmlFor="github-publish-limit-range-min-cpu" className="stack-tight">
                  <span className="hint muted">Min CPU</span>
                  <input
                    id="github-publish-limit-range-min-cpu"
                    type="text"
                    value={githubNamespaceIsolationDefaults.limit_range.min_cpu}
                    onChange={(event) => updateNamespaceLimitRange("min_cpu", event.target.value)}
                    disabled={githubPublishConfigLoading || githubPublishConfigSubmitting}
                  />
                </label>
                <label htmlFor="github-publish-limit-range-min-memory" className="stack-tight">
                  <span className="hint muted">Min Memory</span>
                  <input
                    id="github-publish-limit-range-min-memory"
                    type="text"
                    value={githubNamespaceIsolationDefaults.limit_range.min_memory}
                    onChange={(event) => updateNamespaceLimitRange("min_memory", event.target.value)}
                    disabled={githubPublishConfigLoading || githubPublishConfigSubmitting}
                  />
                </label>
                <label htmlFor="github-publish-limit-range-max-cpu" className="stack-tight">
                  <span className="hint muted">Max CPU</span>
                  <input
                    id="github-publish-limit-range-max-cpu"
                    type="text"
                    value={githubNamespaceIsolationDefaults.limit_range.max_cpu}
                    onChange={(event) => updateNamespaceLimitRange("max_cpu", event.target.value)}
                    disabled={githubPublishConfigLoading || githubPublishConfigSubmitting}
                  />
                </label>
                <label htmlFor="github-publish-limit-range-max-memory" className="stack-tight">
                  <span className="hint muted">Max Memory</span>
                  <input
                    id="github-publish-limit-range-max-memory"
                    type="text"
                    value={githubNamespaceIsolationDefaults.limit_range.max_memory}
                    onChange={(event) => updateNamespaceLimitRange("max_memory", event.target.value)}
                    disabled={githubPublishConfigLoading || githubPublishConfigSubmitting}
                  />
                </label>
                </div>
              </div>
            </div>

            <div className="panel panel-compact stack-tight">
              <strong>Namespace NetworkPolicy defaults</strong>
              <label htmlFor="github-publish-network-policy-enabled" className="checkbox-chip">
                <input
                  id="github-publish-network-policy-enabled"
                  type="checkbox"
                  checked={githubNamespaceIsolationDefaults.network_policy.enabled}
                  onChange={(event) => updateNamespaceNetworkPolicy("enabled", event.target.checked)}
                  disabled={githubPublishConfigLoading || githubPublishConfigSubmitting}
                />
                Enable managed NetworkPolicy scaffold
                <AdminHelpIcon
                  label="Enable managed NetworkPolicy scaffold"
                  helpText="Enable only after ingress/egress expectations are validated for this cluster/environment."
                />
              </label>
              <label htmlFor="github-publish-network-policy-mode">
                <AdminLabelWithHelp
                  label="Policy mode"
                  helpText="NetworkPolicy scaffold mode for new managed namespaces."
                  testId="admin-help-networkpolicy-mode"
                />
              </label>
              <select
                id="github-publish-network-policy-mode"
                value={githubNamespaceIsolationDefaults.network_policy.mode}
                onChange={(event) => updateNamespaceNetworkPolicy("mode", event.target.value)}
                disabled={githubPublishConfigLoading || githubPublishConfigSubmitting}
              >
                <option value="default_deny_ingress">default_deny_ingress</option>
              </select>
            </div>

            <div className="panel panel-compact stack-tight" data-testid="github-publish-migration-generation-budget">
              <strong>Migration AI Budget</strong>
              <p className="hint muted">
                Tune generation depth/variety with bounded limits. Larger budgets can increase latency/cost and failure
                risk.
              </p>
              <p className="hint muted" data-testid="admin-migration-budget-range-summary">
                Recommended: context {MIGRATION_CONTEXT_BUDGET_RECOMMENDED.min.toLocaleString()}-
                {MIGRATION_CONTEXT_BUDGET_RECOMMENDED.max.toLocaleString()} chars, recommendations{" "}
                {MIGRATION_RECOMMENDATION_LIMIT_RECOMMENDED.min}-{MIGRATION_RECOMMENDATION_LIMIT_RECOMMENDED.max},
                competitors {MIGRATION_COMPETITOR_LIMIT_RECOMMENDED.min}-{MIGRATION_COMPETITOR_LIMIT_RECOMMENDED.max}.
                Backend hard caps: context {MIGRATION_CONTEXT_BUDGET_BOUNDS.min.toLocaleString()}-
                {MIGRATION_CONTEXT_BUDGET_BOUNDS.max.toLocaleString()}, recommendations{" "}
                {MIGRATION_RECOMMENDATION_LIMIT_BOUNDS.min}-{MIGRATION_RECOMMENDATION_LIMIT_BOUNDS.max}, competitors{" "}
                {MIGRATION_COMPETITOR_LIMIT_BOUNDS.min}-{MIGRATION_COMPETITOR_LIMIT_BOUNDS.max}, source pages{" "}
                {MIGRATION_SOURCE_PAGE_SUMMARY_LIMIT_BOUNDS.min}-{MIGRATION_SOURCE_PAGE_SUMMARY_LIMIT_BOUNDS.max},
                media {MIGRATION_MEDIA_ASSET_LIMIT_BOUNDS.min}-{MIGRATION_MEDIA_ASSET_LIMIT_BOUNDS.max}, generated
                pages {MIGRATION_GENERATED_PAGE_LIMIT_BOUNDS.min}-{MIGRATION_GENERATED_PAGE_LIMIT_BOUNDS.max}, files{" "}
                {MIGRATION_GENERATED_FILE_LIMIT_BOUNDS.min}-{MIGRATION_GENERATED_FILE_LIMIT_BOUNDS.max}.
              </p>
              <div className="admin-grid-two admin-grid-two-compact">
                <label htmlFor="github-publish-migration-context-budget-chars" className="stack-tight">
                  <AdminLabelWithHelp
                    label="Context budget (chars)"
                    helpText="Upper bound for context assembly before trimming. Higher values increase request size risk."
                    muted
                    testId="admin-help-migration-context-budget"
                  />
                  <input
                    id="github-publish-migration-context-budget-chars"
                    type="number"
                    step={100}
                    value={githubNamespaceIsolationDefaults.migration_generation_budget.migration_context_budget_chars}
                    onChange={(event) =>
                      updateMigrationGenerationBudget(
                        "migration_context_budget_chars",
                        normalizeMigrationBudgetCount(
                          event.target.value,
                          githubNamespaceIsolationDefaults.migration_generation_budget.migration_context_budget_chars,
                          MIGRATION_CONTEXT_BUDGET_BOUNDS,
                        ),
                      )
                    }
                    disabled={githubPublishConfigLoading || githubPublishConfigSubmitting}
                  />
                  {githubMigrationFieldErrors.migration_context_budget_chars ? (
                    <p className="hint error">{githubMigrationFieldErrors.migration_context_budget_chars}</p>
                  ) : null}
                </label>
                <label htmlFor="github-publish-migration-recommendation-limit" className="stack-tight">
                  <AdminLabelWithHelp
                    label="Recommendation limit"
                    helpText="Maximum recommendations included in migration context."
                    muted
                  />
                  <input
                    id="github-publish-migration-recommendation-limit"
                    type="number"
                    step={1}
                    value={githubNamespaceIsolationDefaults.migration_generation_budget.migration_recommendation_limit}
                    onChange={(event) =>
                      updateMigrationGenerationBudget(
                        "migration_recommendation_limit",
                        normalizeMigrationBudgetCount(
                          event.target.value,
                          githubNamespaceIsolationDefaults.migration_generation_budget.migration_recommendation_limit,
                          MIGRATION_RECOMMENDATION_LIMIT_BOUNDS,
                        ),
                      )
                    }
                    disabled={githubPublishConfigLoading || githubPublishConfigSubmitting}
                  />
                  {githubMigrationFieldErrors.migration_recommendation_limit ? (
                    <p className="hint error">{githubMigrationFieldErrors.migration_recommendation_limit}</p>
                  ) : null}
                </label>
                <label htmlFor="github-publish-migration-competitor-limit" className="stack-tight">
                  <AdminLabelWithHelp
                    label="Competitor limit"
                    helpText="Maximum accepted/useful competitors included in migration context."
                    muted
                  />
                  <input
                    id="github-publish-migration-competitor-limit"
                    type="number"
                    step={1}
                    value={githubNamespaceIsolationDefaults.migration_generation_budget.migration_competitor_limit}
                    onChange={(event) =>
                      updateMigrationGenerationBudget(
                        "migration_competitor_limit",
                        normalizeMigrationBudgetCount(
                          event.target.value,
                          githubNamespaceIsolationDefaults.migration_generation_budget.migration_competitor_limit,
                          MIGRATION_COMPETITOR_LIMIT_BOUNDS,
                        ),
                      )
                    }
                    disabled={githubPublishConfigLoading || githubPublishConfigSubmitting}
                  />
                  {githubMigrationFieldErrors.migration_competitor_limit ? (
                    <p className="hint error">{githubMigrationFieldErrors.migration_competitor_limit}</p>
                  ) : null}
                </label>
                <label htmlFor="github-publish-migration-source-page-summary-limit" className="stack-tight">
                  <AdminLabelWithHelp
                    label="Source page summary limit"
                    helpText="Maximum source pages summarized into generation context."
                    muted
                  />
                  <input
                    id="github-publish-migration-source-page-summary-limit"
                    type="number"
                    step={1}
                    value={githubNamespaceIsolationDefaults.migration_generation_budget.migration_source_page_summary_limit}
                    onChange={(event) =>
                      updateMigrationGenerationBudget(
                        "migration_source_page_summary_limit",
                        normalizeMigrationBudgetCount(
                          event.target.value,
                          githubNamespaceIsolationDefaults.migration_generation_budget.migration_source_page_summary_limit,
                          MIGRATION_SOURCE_PAGE_SUMMARY_LIMIT_BOUNDS,
                        ),
                      )
                    }
                    disabled={githubPublishConfigLoading || githubPublishConfigSubmitting}
                  />
                  {githubMigrationFieldErrors.migration_source_page_summary_limit ? (
                    <p className="hint error">{githubMigrationFieldErrors.migration_source_page_summary_limit}</p>
                  ) : null}
                </label>
                <label htmlFor="github-publish-migration-media-asset-limit" className="stack-tight">
                  <AdminLabelWithHelp
                    label="Media asset context limit"
                    helpText="Maximum media assets represented in migration context metadata."
                    muted
                  />
                  <input
                    id="github-publish-migration-media-asset-limit"
                    type="number"
                    step={1}
                    value={githubNamespaceIsolationDefaults.migration_generation_budget.migration_media_asset_limit}
                    onChange={(event) =>
                      updateMigrationGenerationBudget(
                        "migration_media_asset_limit",
                        normalizeMigrationBudgetCount(
                          event.target.value,
                          githubNamespaceIsolationDefaults.migration_generation_budget.migration_media_asset_limit,
                          MIGRATION_MEDIA_ASSET_LIMIT_BOUNDS,
                        ),
                      )
                    }
                    disabled={githubPublishConfigLoading || githubPublishConfigSubmitting}
                  />
                  {githubMigrationFieldErrors.migration_media_asset_limit ? (
                    <p className="hint error">{githubMigrationFieldErrors.migration_media_asset_limit}</p>
                  ) : null}
                </label>
                <label htmlFor="github-publish-migration-generated-page-limit" className="stack-tight">
                  <AdminLabelWithHelp
                    label="Generated page limit"
                    helpText="Target cap for generated pages in draft output contract."
                    muted
                  />
                  <input
                    id="github-publish-migration-generated-page-limit"
                    type="number"
                    step={1}
                    value={githubNamespaceIsolationDefaults.migration_generation_budget.migration_generated_page_limit}
                    onChange={(event) =>
                      updateMigrationGenerationBudget(
                        "migration_generated_page_limit",
                        normalizeMigrationBudgetCount(
                          event.target.value,
                          githubNamespaceIsolationDefaults.migration_generation_budget.migration_generated_page_limit,
                          MIGRATION_GENERATED_PAGE_LIMIT_BOUNDS,
                        ),
                      )
                    }
                    disabled={githubPublishConfigLoading || githubPublishConfigSubmitting}
                  />
                  {githubMigrationFieldErrors.migration_generated_page_limit ? (
                    <p className="hint error">{githubMigrationFieldErrors.migration_generated_page_limit}</p>
                  ) : null}
                </label>
                <label htmlFor="github-publish-migration-generated-file-limit" className="stack-tight">
                  <AdminLabelWithHelp
                    label="Generated file limit"
                    helpText="Target cap for generated files in draft output contract."
                    muted
                  />
                  <input
                    id="github-publish-migration-generated-file-limit"
                    type="number"
                    step={1}
                    value={githubNamespaceIsolationDefaults.migration_generation_budget.migration_generated_file_limit}
                    onChange={(event) =>
                      updateMigrationGenerationBudget(
                        "migration_generated_file_limit",
                        normalizeMigrationBudgetCount(
                          event.target.value,
                          githubNamespaceIsolationDefaults.migration_generation_budget.migration_generated_file_limit,
                          MIGRATION_GENERATED_FILE_LIMIT_BOUNDS,
                        ),
                      )
                    }
                    disabled={githubPublishConfigLoading || githubPublishConfigSubmitting}
                  />
                  {githubMigrationFieldErrors.migration_generated_file_limit ? (
                    <p className="hint error">{githubMigrationFieldErrors.migration_generated_file_limit}</p>
                  ) : null}
                </label>
                <label htmlFor="github-publish-migration-generation-depth" className="stack-tight">
                  <AdminLabelWithHelp
                    label="Generation profile"
                    helpText="Controls compact/standard/expanded generation depth."
                    muted
                  />
                  <select
                    id="github-publish-migration-generation-depth"
                    value={githubNamespaceIsolationDefaults.migration_generation_budget.migration_generation_depth}
                    onChange={(event) =>
                      updateMigrationGenerationBudget(
                        "migration_generation_depth",
                        event.target.value as MigrationGenerationBudgetConfig["migration_generation_depth"],
                      )
                    }
                    disabled={githubPublishConfigLoading || githubPublishConfigSubmitting}
                  >
                    {MIGRATION_GENERATION_DEPTH_OPTIONS.map((value) => (
                      <option key={value} value={value}>
                        {value}
                      </option>
                    ))}
                  </select>
                </label>
                <label htmlFor="github-publish-migration-variation-level" className="stack-tight">
                  <AdminLabelWithHelp
                    label="Variation level"
                    helpText="Controls conservative/balanced/differentiated output variation."
                    muted
                  />
                  <select
                    id="github-publish-migration-variation-level"
                    value={githubNamespaceIsolationDefaults.migration_generation_budget.migration_variation_level}
                    onChange={(event) =>
                      updateMigrationGenerationBudget(
                        "migration_variation_level",
                        event.target.value as MigrationGenerationBudgetConfig["migration_variation_level"],
                      )
                    }
                    disabled={githubPublishConfigLoading || githubPublishConfigSubmitting}
                  >
                    {MIGRATION_VARIATION_LEVEL_OPTIONS.map((value) => (
                      <option key={value} value={value}>
                        {value}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              <div className="admin-grid-two admin-grid-two-compact">
                <label htmlFor="github-publish-migration-require-page-variety" className="checkbox-chip">
                  <input
                    id="github-publish-migration-require-page-variety"
                    type="checkbox"
                    checked={githubNamespaceIsolationDefaults.migration_generation_budget.migration_require_page_variety}
                    onChange={(event) =>
                      updateMigrationGenerationBudget("migration_require_page_variety", event.target.checked)
                    }
                    disabled={githubPublishConfigLoading || githubPublishConfigSubmitting}
                  />
                  Require page variety
                  <AdminHelpIcon
                    label="Require page variety"
                    helpText="Encourages broader page structure diversity in generated drafts."
                  />
                </label>
                <label htmlFor="github-publish-migration-require-design-variation" className="checkbox-chip">
                  <input
                    id="github-publish-migration-require-design-variation"
                    type="checkbox"
                    checked={githubNamespaceIsolationDefaults.migration_generation_budget.migration_require_design_variation}
                    onChange={(event) =>
                      updateMigrationGenerationBudget("migration_require_design_variation", event.target.checked)
                    }
                    disabled={githubPublishConfigLoading || githubPublishConfigSubmitting}
                  />
                  Require design variation
                  <AdminHelpIcon
                    label="Require design variation"
                    helpText="Encourages layout and section variation instead of generic repeated skeletons."
                  />
                </label>
              </div>
            </div>
            <div className="panel panel-compact stack-tight" data-testid="github-publish-migration-generation-safety">
              <strong>Migration Generation Safety</strong>
              <p className="hint muted">
                These settings control when migration draft generation is compacted or blocked before calling the
                provider. Backend hard caps still apply even if Admin values are higher.
              </p>
              <p className="hint muted">Maximum synchronous timeout is 600 seconds (10 minutes).</p>
              <p className="hint muted" data-testid="admin-migration-safety-range-summary">
                Recommended: max final input {MIGRATION_MAX_FINAL_INPUT_CHARS_RECOMMENDED.min.toLocaleString()}-
                {MIGRATION_MAX_FINAL_INPUT_CHARS_RECOMMENDED.max.toLocaleString()} chars, difficulty{" "}
                {MIGRATION_MAX_DIFFICULTY_SCORE_RECOMMENDED.min}-{MIGRATION_MAX_DIFFICULTY_SCORE_RECOMMENDED.max},
                compact pages {MIGRATION_COMPACT_PAGE_LIMIT_RECOMMENDED.min}-
                {MIGRATION_COMPACT_PAGE_LIMIT_RECOMMENDED.max}, compact media{" "}
                {MIGRATION_COMPACT_MEDIA_LIMIT_RECOMMENDED.min}-{MIGRATION_COMPACT_MEDIA_LIMIT_RECOMMENDED.max},
                compact recommendations {MIGRATION_COMPACT_RECOMMENDATION_LIMIT_RECOMMENDED.min}-
                {MIGRATION_COMPACT_RECOMMENDATION_LIMIT_RECOMMENDED.max}. Backend hard caps: timeout{" "}
                {MIGRATION_PROVIDER_TIMEOUT_BOUNDS.min}-{MIGRATION_PROVIDER_TIMEOUT_BOUNDS.max}s, max final input{" "}
                {MIGRATION_MAX_FINAL_INPUT_CHARS_BOUNDS.min.toLocaleString()}-
                {MIGRATION_MAX_FINAL_INPUT_CHARS_BOUNDS.max.toLocaleString()}, difficulty{" "}
                {MIGRATION_MAX_DIFFICULTY_SCORE_BOUNDS.min}-{MIGRATION_MAX_DIFFICULTY_SCORE_BOUNDS.max}, compact
                pages {MIGRATION_COMPACT_PAGE_LIMIT_BOUNDS.min}-{MIGRATION_COMPACT_PAGE_LIMIT_BOUNDS.max}, compact
                media {MIGRATION_COMPACT_MEDIA_LIMIT_BOUNDS.min}-{MIGRATION_COMPACT_MEDIA_LIMIT_BOUNDS.max}, compact
                recommendations {MIGRATION_COMPACT_RECOMMENDATION_LIMIT_BOUNDS.min}-
                {MIGRATION_COMPACT_RECOMMENDATION_LIMIT_BOUNDS.max}.
              </p>
              <p className="hint muted">
                Requested values are persisted for admin intent, while backend policy computes effective bounded
                values used at runtime. Out-of-range values are shown as capped in the preview.
              </p>
              <div className="admin-grid-two admin-grid-two-compact">
                <label htmlFor="github-publish-migration-provider-timeout-seconds" className="stack-tight">
                  <AdminLabelWithHelp
                    label="Provider timeout seconds"
                    helpText="Maximum synchronous timeout is 600 seconds / 10 minutes. Longer timeouts increase latency/cost and do not fix oversized or overly complex prompts."
                    muted
                    testId="admin-help-migration-provider-timeout-seconds"
                  />
                  <input
                    id="github-publish-migration-provider-timeout-seconds"
                    type="number"
                    step={1}
                    value={githubNamespaceIsolationDefaults.migration_generation_safety.migration_provider_timeout_seconds}
                    onChange={(event) =>
                      updateMigrationGenerationSafety(
                        "migration_provider_timeout_seconds",
                        normalizeMigrationBudgetCount(
                          event.target.value,
                          githubNamespaceIsolationDefaults.migration_generation_safety.migration_provider_timeout_seconds,
                          MIGRATION_PROVIDER_TIMEOUT_BOUNDS,
                        ),
                      )
                    }
                    disabled={githubPublishConfigLoading || githubPublishConfigSubmitting}
                  />
                  {githubMigrationFieldErrors.migration_provider_timeout_seconds ? (
                    <p className="hint error">{githubMigrationFieldErrors.migration_provider_timeout_seconds}</p>
                  ) : null}
                </label>
                <label htmlFor="github-publish-migration-preflight-mode" className="stack-tight">
                  <AdminLabelWithHelp
                    label="Preflight mode"
                    helpText="compact_fallback attempts a reduced context before provider call; block_before_provider blocks immediately when thresholds are exceeded."
                    muted
                    testId="admin-help-preflight-mode"
                  />
                  <select
                    id="github-publish-migration-preflight-mode"
                    value={githubNamespaceIsolationDefaults.migration_generation_safety.migration_preflight_mode}
                    onChange={(event) =>
                      updateMigrationGenerationSafety(
                        "migration_preflight_mode",
                        event.target.value as MigrationGenerationSafetyConfig["migration_preflight_mode"],
                      )
                    }
                    disabled={githubPublishConfigLoading || githubPublishConfigSubmitting}
                  >
                    {MIGRATION_PREFLIGHT_MODE_OPTIONS.map((value) => (
                      <option key={value} value={value}>
                        {value}
                      </option>
                    ))}
                  </select>
                </label>
                <label htmlFor="github-publish-migration-max-final-input-chars" className="stack-tight">
                  <AdminLabelWithHelp
                    label="Max final input chars"
                    helpText="Final context size threshold used by preflight safety checks."
                    muted
                  />
                  <input
                    id="github-publish-migration-max-final-input-chars"
                    type="number"
                    step={100}
                    value={githubNamespaceIsolationDefaults.migration_generation_safety.migration_max_final_input_chars}
                    onChange={(event) =>
                      updateMigrationGenerationSafety(
                        "migration_max_final_input_chars",
                        normalizeMigrationBudgetCount(
                          event.target.value,
                          githubNamespaceIsolationDefaults.migration_generation_safety.migration_max_final_input_chars,
                          MIGRATION_MAX_FINAL_INPUT_CHARS_BOUNDS,
                        ),
                      )
                    }
                    disabled={githubPublishConfigLoading || githubPublishConfigSubmitting}
                  />
                  {githubMigrationFieldErrors.migration_max_final_input_chars ? (
                    <p className="hint error">{githubMigrationFieldErrors.migration_max_final_input_chars}</p>
                  ) : null}
                </label>
                <label htmlFor="github-publish-migration-max-difficulty-score" className="stack-tight">
                  <AdminLabelWithHelp
                    label="Max difficulty score"
                    helpText="Complexity threshold used by preflight safety checks."
                    muted
                  />
                  <input
                    id="github-publish-migration-max-difficulty-score"
                    type="number"
                    step={1}
                    value={githubNamespaceIsolationDefaults.migration_generation_safety.migration_max_difficulty_score}
                    onChange={(event) =>
                      updateMigrationGenerationSafety(
                        "migration_max_difficulty_score",
                        normalizeMigrationBudgetCount(
                          event.target.value,
                          githubNamespaceIsolationDefaults.migration_generation_safety.migration_max_difficulty_score,
                          MIGRATION_MAX_DIFFICULTY_SCORE_BOUNDS,
                        ),
                      )
                    }
                    disabled={githubPublishConfigLoading || githubPublishConfigSubmitting}
                  />
                  {githubMigrationFieldErrors.migration_max_difficulty_score ? (
                    <p className="hint error">{githubMigrationFieldErrors.migration_max_difficulty_score}</p>
                  ) : null}
                </label>
                <label htmlFor="github-publish-migration-compact-page-limit" className="stack-tight">
                  <AdminLabelWithHelp
                    label="Compact page limit"
                    helpText="Page cap applied when compact fallback mode is used."
                    muted
                  />
                  <input
                    id="github-publish-migration-compact-page-limit"
                    type="number"
                    step={1}
                    value={githubNamespaceIsolationDefaults.migration_generation_safety.migration_compact_page_limit}
                    onChange={(event) =>
                      updateMigrationGenerationSafety(
                        "migration_compact_page_limit",
                        normalizeMigrationBudgetCount(
                          event.target.value,
                          githubNamespaceIsolationDefaults.migration_generation_safety.migration_compact_page_limit,
                          MIGRATION_COMPACT_PAGE_LIMIT_BOUNDS,
                        ),
                      )
                    }
                    disabled={githubPublishConfigLoading || githubPublishConfigSubmitting}
                  />
                  {githubMigrationFieldErrors.migration_compact_page_limit ? (
                    <p className="hint error">{githubMigrationFieldErrors.migration_compact_page_limit}</p>
                  ) : null}
                </label>
                <label htmlFor="github-publish-migration-compact-media-limit" className="stack-tight">
                  <AdminLabelWithHelp
                    label="Compact media limit"
                    helpText="Media context cap applied when compact fallback mode is used."
                    muted
                  />
                  <input
                    id="github-publish-migration-compact-media-limit"
                    type="number"
                    step={1}
                    value={githubNamespaceIsolationDefaults.migration_generation_safety.migration_compact_media_asset_limit}
                    onChange={(event) =>
                      updateMigrationGenerationSafety(
                        "migration_compact_media_asset_limit",
                        normalizeMigrationBudgetCount(
                          event.target.value,
                          githubNamespaceIsolationDefaults.migration_generation_safety.migration_compact_media_asset_limit,
                          MIGRATION_COMPACT_MEDIA_LIMIT_BOUNDS,
                        ),
                      )
                    }
                    disabled={githubPublishConfigLoading || githubPublishConfigSubmitting}
                  />
                  {githubMigrationFieldErrors.migration_compact_media_asset_limit ? (
                    <p className="hint error">{githubMigrationFieldErrors.migration_compact_media_asset_limit}</p>
                  ) : null}
                </label>
                <label htmlFor="github-publish-migration-compact-recommendation-limit" className="stack-tight">
                  <AdminLabelWithHelp
                    label="Compact recommendation limit"
                    helpText="Recommendation cap applied when compact fallback mode is used."
                    muted
                  />
                  <input
                    id="github-publish-migration-compact-recommendation-limit"
                    type="number"
                    step={1}
                    value={githubNamespaceIsolationDefaults.migration_generation_safety.migration_compact_recommendation_limit}
                    onChange={(event) =>
                      updateMigrationGenerationSafety(
                        "migration_compact_recommendation_limit",
                        normalizeMigrationBudgetCount(
                          event.target.value,
                          githubNamespaceIsolationDefaults.migration_generation_safety.migration_compact_recommendation_limit,
                          MIGRATION_COMPACT_RECOMMENDATION_LIMIT_BOUNDS,
                        ),
                      )
                    }
                    disabled={githubPublishConfigLoading || githubPublishConfigSubmitting}
                  />
                  {githubMigrationFieldErrors.migration_compact_recommendation_limit ? (
                    <p className="hint error">{githubMigrationFieldErrors.migration_compact_recommendation_limit}</p>
                  ) : null}
                </label>
              </div>
              <label htmlFor="github-publish-migration-compact-fallback-enabled" className="checkbox-chip">
                <input
                  id="github-publish-migration-compact-fallback-enabled"
                  type="checkbox"
                  checked={githubNamespaceIsolationDefaults.migration_generation_safety.migration_compact_fallback_enabled}
                  onChange={(event) =>
                    updateMigrationGenerationSafety("migration_compact_fallback_enabled", event.target.checked)
                  }
                  disabled={githubPublishConfigLoading || githubPublishConfigSubmitting}
                />
                Compact fallback enabled
                <AdminHelpIcon
                  label="Compact fallback enabled"
                  helpText="If enabled, preflight can retry once with compact limits before blocking."
                />
              </label>
            </div>
            <div className="panel panel-compact stack-tight" data-testid="github-publish-effective-preview">
              <p className="hint muted">
                <strong>Effective target preview</strong>
              </p>
              <WorkspaceMetadataGrid>
                <WorkspaceMetadataItem label="GitHub account/owner">
                  <code>{githubPublishPreviewOwner}</code>
                </WorkspaceMetadataItem>
                <WorkspaceMetadataItem label="Branch">
                  <code>{githubPublishValidation.defaultBranch}</code>
                </WorkspaceMetadataItem>
                <WorkspaceMetadataItem label="Base path">
                  <code>{githubPublishValidation.basePath}</code>
                </WorkspaceMetadataItem>
                <WorkspaceMetadataItem label="Deploy workflow mode">
                  <code>{githubPublishValidation.deployWorkflowMode}</code>
                </WorkspaceMetadataItem>
                <WorkspaceMetadataItem label="Target environment key">
                  <code>{githubPublishValidation.targetEnvironmentKey}</code>
                </WorkspaceMetadataItem>
                <WorkspaceMetadataItem label="Repository auto-create">
                  <span>{githubRepositoryAutoCreateEnabled ? "Enabled" : "Disabled"}</span>
                </WorkspaceMetadataItem>
                <WorkspaceMetadataItem label="Managed GKE cluster">
                  <code>{githubPublishValidation.managedGkeClusterName || "Not configured"}</code>
                </WorkspaceMetadataItem>
                <WorkspaceMetadataItem label="Managed GKE location">
                  <code>{githubPublishValidation.managedGkeClusterLocation || "Not configured"}</code>
                </WorkspaceMetadataItem>
                <WorkspaceMetadataItem label="Managed GCP project">
                  <code>{githubPublishValidation.managedGkeProjectId || "Not configured"}</code>
                </WorkspaceMetadataItem>
                <WorkspaceMetadataItem label="Managed deploy secret">
                  <span>{githubPublishManagedDeployKeyConfigured ? "Configured" : "Missing"}</span>
                </WorkspaceMetadataItem>
                <WorkspaceMetadataItem label="Target environment source">
                  <code>admin_config</code>
                </WorkspaceMetadataItem>
                <WorkspaceMetadataItem label="ResourceQuota default">
                  <span>{githubNamespaceIsolationDefaults.resource_quota.enabled ? "Enabled" : "Disabled"}</span>
                </WorkspaceMetadataItem>
                <WorkspaceMetadataItem label="LimitRange default">
                  <span>{githubNamespaceIsolationDefaults.limit_range.enabled ? "Enabled" : "Disabled"}</span>
                </WorkspaceMetadataItem>
                <WorkspaceMetadataItem label="NetworkPolicy default">
                  <span>{githubNamespaceIsolationDefaults.network_policy.enabled ? "Enabled" : "Disabled"}</span>
                </WorkspaceMetadataItem>
                <WorkspaceMetadataItem label="NetworkPolicy mode">
                  <code>{githubNamespaceIsolationDefaults.network_policy.mode}</code>
                </WorkspaceMetadataItem>
                <WorkspaceMetadataItem label="Migration profile">
                  <code>{githubNamespaceIsolationDefaults.migration_generation_budget.migration_generation_depth}</code>
                </WorkspaceMetadataItem>
                <WorkspaceMetadataItem label="Migration variation">
                  <code>{githubNamespaceIsolationDefaults.migration_generation_budget.migration_variation_level}</code>
                </WorkspaceMetadataItem>
                <WorkspaceMetadataItem label="Migration context budget (requested / effective / capped)">
                  <code>
                    {requestedMigrationBudget.migration_context_budget_chars} /{" "}
                    {effectiveMigrationBudget.migration_context_budget_chars} /{" "}
                    {requestedMigrationBudget.migration_context_budget_chars !==
                    effectiveMigrationBudget.migration_context_budget_chars
                      ? "Yes"
                      : "No"}
                  </code>
                </WorkspaceMetadataItem>
                <WorkspaceMetadataItem label="Migration recommendation limit (requested / effective / capped)">
                  <code>
                    {requestedMigrationBudget.migration_recommendation_limit} /{" "}
                    {effectiveMigrationBudget.migration_recommendation_limit} /{" "}
                    {requestedMigrationBudget.migration_recommendation_limit !==
                    effectiveMigrationBudget.migration_recommendation_limit
                      ? "Yes"
                      : "No"}
                  </code>
                </WorkspaceMetadataItem>
                <WorkspaceMetadataItem label="Migration timeout (requested / effective / capped)">
                  <code>
                    {requestedMigrationSafety.migration_provider_timeout_seconds}s /{" "}
                    {effectiveMigrationSafety.migration_provider_timeout_seconds}s /{" "}
                    {requestedMigrationSafety.migration_provider_timeout_seconds !==
                    effectiveMigrationSafety.migration_provider_timeout_seconds
                      ? "Yes"
                      : "No"}
                  </code>
                </WorkspaceMetadataItem>
                <WorkspaceMetadataItem label="Migration preflight mode">
                  <code>{requestedMigrationSafety.migration_preflight_mode}</code>
                </WorkspaceMetadataItem>
                <WorkspaceMetadataItem label="Migration max input chars (requested / effective / capped)">
                  <code>
                    {requestedMigrationSafety.migration_max_final_input_chars} /{" "}
                    {effectiveMigrationSafety.migration_max_final_input_chars} /{" "}
                    {requestedMigrationSafety.migration_max_final_input_chars !==
                    effectiveMigrationSafety.migration_max_final_input_chars
                      ? "Yes"
                      : "No"}
                  </code>
                </WorkspaceMetadataItem>
                <WorkspaceMetadataItem label="Migration max difficulty (requested / effective / capped)">
                  <code>
                    {requestedMigrationSafety.migration_max_difficulty_score} /{" "}
                    {effectiveMigrationSafety.migration_max_difficulty_score} /{" "}
                    {requestedMigrationSafety.migration_max_difficulty_score !==
                    effectiveMigrationSafety.migration_max_difficulty_score
                      ? "Yes"
                      : "No"}
                  </code>
                </WorkspaceMetadataItem>
                <WorkspaceMetadataItem label="Migration compact limits (pages/media/reco)">
                  <code>
                    {requestedMigrationSafety.migration_compact_page_limit}/
                    {requestedMigrationSafety.migration_compact_media_asset_limit}/
                    {requestedMigrationSafety.migration_compact_recommendation_limit} requested
                    {" -> "}
                    {effectiveMigrationSafety.migration_compact_page_limit}/
                    {effectiveMigrationSafety.migration_compact_media_asset_limit}/
                    {effectiveMigrationSafety.migration_compact_recommendation_limit} effective
                  </code>
                </WorkspaceMetadataItem>
                <WorkspaceMetadataItem label="Migration settings differ (requested vs effective)">
                  <span>{migrationRequestedVsEffectiveDiffCount > 0 ? "Yes" : "No"}</span>
                </WorkspaceMetadataItem>
                <WorkspaceMetadataItem label="Migration cap reason">
                  <span>
                    {githubMigrationAdjustmentReason === "backend_adjusted_values"
                      ? (
                        Object.keys(githubMigrationCapReasons).length > 0
                          ? Object.values(githubMigrationCapReasons).join(" | ")
                          : "Backend cap policy adjusted one or more requested values."
                      )
                      : githubMigrationAdjustmentReason === "backend_validation_rejected"
                        ? "Last save was rejected by backend validation; requested values were not applied."
                        : "None"}
                  </span>
                </WorkspaceMetadataItem>
                <WorkspaceMetadataItem label="Migration requested/effective note">
                  <span className="hint muted">
                    Differences before save indicate pending edits. Differences after save indicate backend-adjusted
                    effective values.
                  </span>
                </WorkspaceMetadataItem>
                <WorkspaceMetadataItem label="Enabled">
                  <span>{githubPublishEnabled ? "Yes" : "No"}</span>
                </WorkspaceMetadataItem>
              </WorkspaceMetadataGrid>
            </div>

            <div className="form-actions">
              <button
                className="button button-primary"
                type="submit"
                disabled={
                  githubPublishConfigLoading ||
                  githubPublishConfigSubmitting ||
                  Boolean(githubPublishValidation.blockingError)
                }
              >
                {githubPublishConfigSubmitting ? "Saving..." : "Save GitHub Publish Config"}
              </button>
            </div>
            {githubPublishValidation.blockingError ? (
              <p className="hint warning">Resolve validation issues above before saving.</p>
            ) : null}
            {githubPublishValidation.namespaceIsolationErrors.length > 0 ? (
              <ul className="compact-list">
                {githubPublishValidation.namespaceIsolationErrors.map((error) => (
                  <li key={error} className="hint error">
                    {error}
                  </li>
                ))}
              </ul>
            ) : null}
            {githubPublishConfigLoading ? <p className="hint muted">Loading GitHub publish configuration...</p> : null}
            {githubPublishConfigMessage ? <p className="hint">{githubPublishConfigMessage}</p> : null}
            {githubPublishConfigError ? <p className="hint error">{githubPublishConfigError}</p> : null}
          </FormContainer>
        </SectionCard>
        </PublishDeploymentConfigSection>
        ) : null}

        <div className="message-stack">
          {showUserManagement && submitSuccess ? <p className="hint">{submitSuccess}</p> : null}
          {showUserManagement && submitError ? <p className="hint error">{submitError}</p> : null}
          {showUserManagement && identitySubmitSuccess ? <p className="hint">{identitySubmitSuccess}</p> : null}
          {showUserManagement && identitySubmitError ? <p className="hint error">{identitySubmitError}</p> : null}
          {showUserManagement && actionSuccess ? <p className="hint">Principal action: {actionSuccess}</p> : null}
          {showUserManagement && actionError ? <p className="hint error">Principal action: {actionError}</p> : null}
          {showUserManagement && identityActionSuccess ? <p className="hint">Identity action: {identityActionSuccess}</p> : null}
          {showUserManagement && identityActionError ? <p className="hint error">Identity action: {identityActionError}</p> : null}
          {showAdminSettings && businessSettingsLoadError ? <p className="hint error">{businessSettingsLoadError}</p> : null}
          {showAdminSettings && settingsHealth.notifications.status === "invalid" ? (
            <p className="hint warning">
              Notification settings health: {settingsHealth.notifications.message}
            </p>
          ) : null}
          {showUserManagement && loadingUsers ? <p className="hint muted">Loading users...</p> : null}
          {showUserManagement && usersError ? <p className="hint error">{usersError}</p> : null}
          {showUserManagement && identityWarning ? <p className="hint warning">{identityWarning}</p> : null}
          {showUserManagement && !loadingUsers && users.length > 0 && principalsWithoutIdentityCount > 0 ? (
            <p className="hint muted">
              Some principals have no mapped sign-in identity yet. They will not be able to authenticate until an identity is linked.
            </p>
          ) : null}
        </div>
      </div>

      {showAdminSettings ? (
        <>
      <SiteRegistryManagementSection>
      <SectionCard variant="summary" className="role-surface-support">
        <SectionHeader
          title="Site Management"
          subtitle="Rename sites, update base URLs, manage per-site Search Console property settings, and permanently delete site-owned SEO data."
          headingLevel={2}
          variant="support"
        />
        <div className="message-stack">
          {siteManagementMessage ? <p className="hint">{siteManagementMessage}</p> : null}
          {siteManagementError ? <p className="hint error">{siteManagementError}</p> : null}
        </div>
        <p className="hint muted">
          Search Console property format: domain property <code>sc-domain:example.com</code> or URL-prefix
          property <code>https://example.com</code>. The value must match the Search Console property exactly.
        </p>
        <p className="hint warning">
          Site Registry changes affect active site records and destructive deletion behavior. Review before saving or deleting.
        </p>
        {siteDeletePlan ? (
          <div className="panel panel-compact stack-tight" data-testid="admin-site-delete-plan">
            <h3>Permanent delete plan</h3>
            {selectedDeleteSite ? (
              <p className="hint muted">Prepared for {selectedDeleteSite.display_name}.</p>
            ) : null}
            <p className="hint warning">
              Permanent delete is irreversible. Selected external cleanup can remove managed GitHub, runtime, and DNS resources.
            </p>
            <WorkspaceMetadataGrid>
              <WorkspaceMetadataItem label="Site">
                <code>{siteDeletePlan.site_name}</code>
              </WorkspaceMetadataItem>
              <WorkspaceMetadataItem label="Domain">
                <code>{siteDeletePlan.domain}</code>
              </WorkspaceMetadataItem>
              <WorkspaceMetadataItem label="Active">
                <span>{siteDeletePlan.is_active ? "Yes" : "No"}</span>
              </WorkspaceMetadataItem>
              <WorkspaceMetadataItem label="GitHub repo">
                <code>
                  {siteDeletePlan.generated_repo_owner && siteDeletePlan.generated_repo_name
                    ? `${siteDeletePlan.generated_repo_owner}/${siteDeletePlan.generated_repo_name}`
                    : "Not configured"}
                </code>
              </WorkspaceMetadataItem>
              <WorkspaceMetadataItem label="Namespace">
                <code>{siteDeletePlan.kubernetes_namespace || "Not derived"}</code>
              </WorkspaceMetadataItem>
              <WorkspaceMetadataItem label="Preview hostname">
                <code>{siteDeletePlan.preview_hostname || "Not derived"}</code>
              </WorkspaceMetadataItem>
              <WorkspaceMetadataItem label="Static IP">
                <code>{siteDeletePlan.static_ip_name || "Not derived"}</code>
              </WorkspaceMetadataItem>
              <WorkspaceMetadataItem label="Managed certificate">
                <code>{siteDeletePlan.managed_certificate_name || "Not derived"}</code>
              </WorkspaceMetadataItem>
              <WorkspaceMetadataItem label="DB dependency total">
                <span>{siteDeletePlan.db_dependency_total}</span>
              </WorkspaceMetadataItem>
            </WorkspaceMetadataGrid>

            {siteDeletePlan.db_dependencies.length > 0 ? (
              <div>
                <p className="hint muted">Database dependency summary</p>
                <ul className="compact-list">
                  {siteDeletePlan.db_dependencies.map((dependency) => (
                    <li key={dependency.category}>
                      {dependency.category}: {dependency.count} records across {dependency.model_count} tables
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}

            <div>
              <p className="hint muted">External resource summary</p>
              <ul className="compact-list">
                {siteDeletePlan.external_resources.map((resource) => (
                  <li key={resource.resource_type}>
                    {siteDeleteResourceLabel(resource.resource_type)} — {siteDeleteStatusLabel(resource.status)}:{" "}
                    {resource.summary}
                  </li>
                ))}
              </ul>
            </div>

            {siteDeletePlan.blockers.length > 0 ? (
              <div>
                <p className="hint warning">Plan blockers</p>
                <ul className="compact-list">
                  {siteDeletePlan.blockers.map((issue) => (
                    <li key={`${issue.reason_code}-${issue.message}`} className="hint warning">
                      {issue.message}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}

            {siteDeletePlan.warnings.length > 0 ? (
              <div>
                <p className="hint warning">Warnings</p>
                <ul className="compact-list">
                  {siteDeletePlan.warnings.map((issue) => (
                    <li key={`${issue.reason_code}-${issue.message}`} className="hint warning">
                      {issue.message}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}

            <label htmlFor="admin-site-delete-confirmation-phrase">Confirmation phrase</label>
            <input
              id="admin-site-delete-confirmation-phrase"
              value={siteDeleteForm.confirmationPhrase}
              onChange={(event) =>
                setSiteDeleteForm((current) => ({ ...current, confirmationPhrase: event.target.value }))
              }
              placeholder={siteDeletePlan.required_confirmation_phrase}
              disabled={!!preparingSiteDeleteId || !!deletingSiteId}
            />
            <p className="hint muted">
              Type <code>{siteDeletePlan.required_confirmation_phrase}</code> exactly.
            </p>

            <label>
              <input
                type="checkbox"
                checked={siteDeleteForm.acknowledgeDeleteDatabaseRecords}
                onChange={(event) =>
                  handleSiteDeleteFormToggle("acknowledgeDeleteDatabaseRecords", event.target.checked)
                }
                disabled={!!preparingSiteDeleteId || !!deletingSiteId}
              />{" "}
              I acknowledge that MBSRN database records for this site will be permanently deleted.
            </label>

            <label>
              <input
                type="checkbox"
                checked={siteDeleteForm.deleteGitHubRepo}
                onChange={(event) => handleSiteDeleteFormToggle("deleteGitHubRepo", event.target.checked)}
                disabled={!!preparingSiteDeleteId || !!deletingSiteId}
              />{" "}
              Delete generated GitHub repo if ownership verification passes.
            </label>
            {siteDeleteForm.deleteGitHubRepo ? (
              <label>
                <input
                  type="checkbox"
                  checked={siteDeleteForm.acknowledgeDeleteGitHubRepo}
                  onChange={(event) =>
                    handleSiteDeleteFormToggle("acknowledgeDeleteGitHubRepo", event.target.checked)
                  }
                  disabled={!!preparingSiteDeleteId || !!deletingSiteId}
                />{" "}
                I acknowledge that GitHub repo deletion removes repository contents permanently.
              </label>
            ) : null}

            <label>
              <input
                type="checkbox"
                checked={siteDeleteForm.deleteRuntimeResources}
                onChange={(event) => handleSiteDeleteFormToggle("deleteRuntimeResources", event.target.checked)}
                disabled={!!preparingSiteDeleteId || !!deletingSiteId}
              />{" "}
              Delete verified managed GKE/runtime resources.
            </label>
            {siteDeleteForm.deleteRuntimeResources ? (
              <label>
                <input
                  type="checkbox"
                  checked={siteDeleteForm.acknowledgeDeleteRuntimeResources}
                  onChange={(event) =>
                    handleSiteDeleteFormToggle("acknowledgeDeleteRuntimeResources", event.target.checked)
                  }
                  disabled={!!preparingSiteDeleteId || !!deletingSiteId}
                />{" "}
                I acknowledge that runtime cleanup can remove public preview availability immediately.
              </label>
            ) : null}

            <label>
              <input
                type="checkbox"
                checked={siteDeleteForm.deleteDnsResources}
                onChange={(event) => handleSiteDeleteFormToggle("deleteDnsResources", event.target.checked)}
                disabled={!!preparingSiteDeleteId || !!deletingSiteId}
              />{" "}
              Delete verified managed DNS, static IP, and certificate resources.
            </label>
            {siteDeleteForm.deleteDnsResources ? (
              <label>
                <input
                  type="checkbox"
                  checked={siteDeleteForm.acknowledgeDeleteDnsResources}
                  onChange={(event) =>
                    handleSiteDeleteFormToggle("acknowledgeDeleteDnsResources", event.target.checked)
                  }
                  disabled={!!preparingSiteDeleteId || !!deletingSiteId}
                />{" "}
                I acknowledge that DNS/static IP/certificate cleanup affects public preview routing and TLS.
              </label>
            ) : null}

            {siteDeletePlan.is_active ? (
              <>
                <label>
                  <input
                    type="checkbox"
                    checked={siteDeleteForm.forceDeleteActive}
                    onChange={(event) => handleSiteDeleteFormToggle("forceDeleteActive", event.target.checked)}
                    disabled={!!preparingSiteDeleteId || !!deletingSiteId}
                  />{" "}
                  Force delete active site
                </label>
                <p className="hint warning">
                  This site is currently active. Force delete must be checked or the site must be deactivated first.
                </p>
              </>
            ) : null}

            {siteDeleteResult ? (
              <div className="message-stack">
                <p className={siteDeleteResult.db_deleted ? "hint" : "hint error"}>{siteDeleteResult.message}</p>
                {siteDeleteResult.external_cleanup_partial ? (
                  <p className="hint warning">
                    Selected external cleanup completed only partially. Review per-resource results below.
                  </p>
                ) : null}
                {siteDeleteResult.blockers.length > 0 ? (
                  <ul className="compact-list">
                    {siteDeleteResult.blockers.map((issue) => (
                      <li key={`${issue.reason_code}-${issue.message}`} className="hint warning">
                        {issue.message}
                      </li>
                    ))}
                  </ul>
                ) : null}
                {siteDeleteResult.warnings.length > 0 ? (
                  <ul className="compact-list">
                    {siteDeleteResult.warnings.map((issue) => (
                      <li key={`${issue.reason_code}-${issue.message}`} className="hint warning">
                        {issue.message}
                      </li>
                    ))}
                  </ul>
                ) : null}
                <ul className="compact-list">
                  {siteDeleteResult.external_resources.map((resource) => (
                    <li key={`result-${resource.resource_type}`}>
                      {siteDeleteResourceLabel(resource.resource_type)} — {siteDeleteStatusLabel(resource.status)}:{" "}
                      {resource.summary}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}

            <div className="form-actions">
              <button
                type="button"
                className="button button-danger"
                disabled={!siteDeleteExecuteEnabled}
                onClick={() => {
                  void handleExecuteSiteDelete();
                }}
              >
                {deletingSiteId === siteDeletePlan.site_id ? "Deleting..." : "Execute permanent delete"}
              </button>
              <button
                type="button"
                className="button button-secondary"
                disabled={!!preparingSiteDeleteId || !!deletingSiteId}
                onClick={handleDismissSiteDeletePlan}
              >
                Dismiss delete plan
              </button>
            </div>

            <details className="workspace-details-shell" data-testid="admin-site-delete-diagnostics">
              <summary className="hint muted">Advanced Diagnostics</summary>
              <pre>
                {JSON.stringify(
                  {
                    plan: {
                      blockers: siteDeletePlan.blockers,
                      warnings: siteDeletePlan.warnings,
                      external_resources: siteDeletePlan.external_resources,
                    },
                    result: siteDeleteResult
                      ? {
                          reason_code: siteDeleteResult.reason_code,
                          blockers: siteDeleteResult.blockers,
                          warnings: siteDeleteResult.warnings,
                          external_resources: siteDeleteResult.external_resources,
                        }
                      : null,
                  },
                  null,
                  2,
                )}
              </pre>
            </details>
          </div>
        ) : null}
        <div className="table-container">
          <table className="table">
            <thead>
              <tr>
                <th>Site Name</th>
                <th>Site URL</th>
                <th>Search Console Property</th>
                <th>Search Console Enabled</th>
                <th>Domain</th>
                <th>Active</th>
                <th>Edit</th>
                <th>Permanent Delete (destructive)</th>
              </tr>
            </thead>
            <tbody>
              {context.sites.map((site) => (
                <tr key={site.id}>
                  <td>
                    <input
                      aria-label={`Site Name ${site.id}`}
                      value={siteDraftsById[site.id]?.name ?? site.display_name}
                      onChange={(event) => handleSiteDraftChange(site.id, "name", event.target.value)}
                      disabled={siteManagementBusy}
                    />
                  </td>
                  <td>
                    <input
                      aria-label={`Site URL ${site.id}`}
                      value={siteDraftsById[site.id]?.url ?? site.base_url}
                      onChange={(event) => handleSiteDraftChange(site.id, "url", event.target.value)}
                      disabled={siteManagementBusy}
                    />
                  </td>
                  <td>
                    {(() => {
                      const searchConsolePropertyValue =
                        siteDraftsById[site.id]?.searchConsolePropertyUrl ?? site.search_console_property_url ?? "";
                      const formatHint = searchConsolePropertyFormatHint(searchConsolePropertyValue);
                      return (
                        <>
                    <input
                      aria-label={`Search Console property ${site.id}`}
                      value={searchConsolePropertyValue}
                      onChange={(event) => handleSiteDraftChange(site.id, "searchConsolePropertyUrl", event.target.value)}
                      placeholder="sc-domain:example.com"
                      disabled={siteManagementBusy}
                    />
                          {formatHint ? <p className="hint warning">{formatHint}</p> : null}
                        </>
                      );
                    })()}
                  </td>
                  <td>
                    <input
                      aria-label={`Search Console enabled ${site.id}`}
                      type="checkbox"
                      checked={siteDraftsById[site.id]?.searchConsoleEnabled ?? Boolean(site.search_console_enabled)}
                      onChange={(event) => handleSiteDraftToggle(site.id, event.target.checked)}
                      disabled={siteManagementBusy}
                    />
                  </td>
                  <td className="table-cell-wrap">{site.normalized_domain}</td>
                  <td>{site.is_active ? "yes" : "no"}</td>
                  <td>
                    <button
                      type="button"
                      className="button button-secondary button-inline"
                      disabled={siteManagementBusy}
                      onClick={() => {
                        void handleSaveSite(site);
                      }}
                    >
                      {updatingSiteId === site.id ? "Saving..." : "Save"}
                    </button>
                  </td>
                  <td>
                    <button
                      type="button"
                      className="button button-danger button-inline"
                      disabled={siteManagementBusy}
                      onClick={() => {
                        void handlePrepareDeletePlan(site);
                      }}
                    >
                      {preparingSiteDeleteId === site.id
                        ? "Preparing..."
                        : siteDeletePlanSiteId === site.id
                          ? "Refresh delete plan"
                          : "Prepare delete plan"}
                    </button>
                  </td>
                </tr>
              ))}
              {context.sites.length === 0 ? (
                <tr>
                  <td colSpan={8}>No sites found for this business.</td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </SectionCard>
      </SiteRegistryManagementSection>
      <AdminDiagnosticsLogsSection>
      <SectionCard variant="support" className="role-surface-support">
        <SectionHeader
          title="GCP Logs Query"
          subtitle="Admin-only Cloud Logging proxy query using runtime attached service-account credentials (ADC)."
          headingLevel={2}
          variant="support"
        />

        <FormContainer className="form-container-full-width" onSubmit={(event) => void handleSubmitGcpLogsQuery(event)} noValidate>
          <label htmlFor="gcp-logs-filter">Logs Explorer Filter</label>
          <textarea
            id="gcp-logs-filter"
            rows={6}
            value={gcpLogsFilterInput}
            onChange={(event) => setGcpLogsFilterInput(event.target.value)}
            placeholder='jsonPayload.event="competitor_provider_request_error"'
            disabled={gcpLogsLoading}
            required
          />

          <label htmlFor="gcp-logs-page-size">Page Size</label>
          <select
            id="gcp-logs-page-size"
            className="operator-select"
            value={String(gcpLogsPageSize)}
            onChange={(event) => setGcpLogsPageSize(Number(event.target.value))}
            disabled={gcpLogsLoading}
          >
            {GCP_LOGS_PAGE_SIZE_OPTIONS.map((pageSizeOption) => (
              <option key={pageSizeOption} value={String(pageSizeOption)}>
                {pageSizeOption}
              </option>
            ))}
          </select>

          <label htmlFor="gcp-logs-start-time">Start Time (UTC, optional)</label>
          <input
            id="gcp-logs-start-time"
            type="text"
            value={gcpLogsStartTimeInput}
            onChange={(event) => setGcpLogsStartTimeInput(event.target.value)}
            placeholder="2026-03-26T00:00:00Z"
            disabled={gcpLogsLoading}
          />

          <label htmlFor="gcp-logs-end-time">End Time (UTC, optional)</label>
          <input
            id="gcp-logs-end-time"
            type="text"
            value={gcpLogsEndTimeInput}
            onChange={(event) => setGcpLogsEndTimeInput(event.target.value)}
            placeholder="2026-03-27T00:00:00Z"
            disabled={gcpLogsLoading}
          />

          {!gcpLogsStartTimeInput.trim() && !gcpLogsEndTimeInput.trim() ? (
            <p className="hint muted">Defaulting to {GCP_LOGS_DEFAULT_TIME_WINDOW_LABEL} when Start/End are blank.</p>
          ) : null}

          <div className="form-actions">
            <button className="button button-primary" type="submit" disabled={gcpLogsLoading}>
              {gcpLogsLoading ? "Querying..." : "Run Query"}
            </button>
            <button
              className="button button-secondary"
              type="button"
              onClick={() => void handleLoadNextGcpLogsPage()}
              disabled={gcpLogsLoading || !gcpLogsNextPageToken}
            >
              Next Page
            </button>
            <button
              type="button"
              className="button button-tertiary"
              onClick={() => setGcpLogsFilterInput(GCP_LOGS_SAMPLE_FILTER)}
              disabled={gcpLogsLoading}
            >
              Use example
            </button>
          </div>

          <p className="hint muted">
            Scope: <code>{gcpLogsResourceScope.length > 0 ? gcpLogsResourceScope.join(", ") : "configured project"}</code>
            {" | "}
            Order: <code>{gcpLogsOrderBy}</code>
          </p>
          <p className="hint muted">
            Example filter: <code>{GCP_LOGS_SAMPLE_FILTER}</code>
          </p>
          {gcpLogsHasExecuted && gcpLogsEffectiveFilter ? (
            <p className="hint muted">
              Effective Filter: <code>{gcpLogsEffectiveFilter}</code>
              {gcpLogsDefaultTimeRangeApplied ? " (default last 24h applied)" : ""}
            </p>
          ) : null}

          {gcpLogsMessage ? <p className="hint">{gcpLogsMessage}</p> : null}
          {gcpLogsError ? <p className="hint error">{gcpLogsError}</p> : null}
          {gcpLogsHasExecuted && !gcpLogsLoading && gcpLogsEntries.length === 0 && !gcpLogsError ? (
            <p className="hint muted">No entries returned for the current filter and page.</p>
          ) : null}
        </FormContainer>

        <div className="table-container">
          <table className="table">
            <thead>
              <tr>
                <th>Timestamp</th>
                <th>Severity</th>
                <th>Log Name</th>
                <th>Resource</th>
                <th>Insert ID</th>
                <th>Payload Summary</th>
              </tr>
            </thead>
            <tbody>
              {gcpLogsEntries.map((entry, index) => (
                <tr
                  key={`${entry.insert_id || "no-insert-id"}:${entry.timestamp || "no-timestamp"}:${index}`}
                >
                  <td className="table-cell-wrap">{entry.timestamp || "n/a"}</td>
                  <td>{entry.severity || "default"}</td>
                  <td className="table-cell-wrap">{entry.log_name || "n/a"}</td>
                  <td className="table-cell-wrap">
                    <div>{entry.resource_type || "n/a"}</div>
                    {entry.resource_labels ? <div className="hint muted">{formatLabelSummary(entry.resource_labels)}</div> : null}
                    {entry.labels ? <div className="hint muted">{formatLabelSummary(entry.labels)}</div> : null}
                  </td>
                  <td className="table-cell-wrap">{entry.insert_id || "n/a"}</td>
                  <td className="table-cell-wrap">
                    {entry.text_payload_summary || entry.json_payload_summary || entry.proto_payload_summary || "n/a"}
                  </td>
                </tr>
              ))}
              {!gcpLogsLoading && gcpLogsEntries.length === 0 ? (
                <tr>
                  <td colSpan={6}>Run a query to view log entries.</td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </SectionCard>
      </AdminDiagnosticsLogsSection>
      </>
      ) : null}

      {showUserManagement ? (
      <SectionCard variant="support" className="role-surface-support">
        <SectionHeader
          title="User ID Management"
          subtitle="Manage business principals and linked sign-in identities."
          headingLevel={2}
          variant="support"
        />
        <div className="table-container">
          <table className="table">
            <thead>
              <tr>
                <th>User ID</th>
                <th>Display Name</th>
                <th>Role</th>
                <th>Active</th>
                <th>Last Auth</th>
                <th>Sign-In Identities</th>
                <th>Identity Actions</th>
                <th>Principal Action</th>
              </tr>
            </thead>
            <tbody>
              {users.map((user) => {
                const userIdentities = identitiesByPrincipalId.get(user.id) || [];
                return (
                  <tr key={`${user.business_id}:${user.id}`}>
                    <td className="table-cell-wrap">{user.id}</td>
                    <td className="table-cell-wrap">{user.display_name}</td>
                    <td>{user.role}</td>
                    <td>{user.is_active ? "yes" : "no"}</td>
                    <td>{user.last_authenticated_at || "never"}</td>
                    <td>
                      {userIdentities.length === 0 ? (
                        "none"
                      ) : (
                        <ul className="compact-list">
                          {userIdentities.map((identity) => (
                            <li key={identity.id}>
                              {formatIdentityLabel(identity)} ({identity.is_active ? "active" : "inactive"})
                            </li>
                          ))}
                        </ul>
                      )}
                    </td>
                    <td>
                      {userIdentities.length === 0 ? (
                        "none"
                      ) : (
                        <div className="button-stack">
                          {userIdentities.map((identity) => (
                            <button
                              key={identity.id}
                              type="button"
                              className={
                                identity.is_active
                                  ? "button button-danger button-inline"
                                  : "button button-secondary button-inline"
                              }
                              disabled={!!actingIdentityId || !!actingPrincipalId}
                              onClick={() => {
                                void handleToggleIdentityActive(identity);
                              }}
                            >
                              {actingIdentityId === identity.id
                                ? identity.is_active
                                  ? "Deactivating Identity..."
                                  : "Reactivating Identity..."
                                : identity.is_active
                                  ? "Deactivate Identity"
                                  : "Reactivate Identity"}
                            </button>
                          ))}
                        </div>
                      )}
                    </td>
                    <td>
                      <button
                        type="button"
                        className={
                          user.is_active
                            ? "button button-danger button-inline"
                            : "button button-secondary button-inline"
                        }
                        disabled={!!actingPrincipalId || !!actingIdentityId}
                        onClick={() => {
                          void handleToggleUserActive(user);
                        }}
                      >
                        {actingPrincipalId === user.id
                          ? user.is_active
                            ? "Deactivating..."
                            : "Reactivating..."
                          : user.is_active
                            ? "Deactivate"
                            : "Reactivate"}
                      </button>
                    </td>
                  </tr>
                );
              })}
              {!loadingUsers && users.length === 0 ? (
                <tr>
                  <td colSpan={8}>No users found for this business.</td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </SectionCard>
      ) : null}
    </PageContainer>
  );
}
