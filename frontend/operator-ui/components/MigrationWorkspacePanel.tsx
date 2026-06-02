"use client";

import { type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { WorkspaceActionBar } from "./layout/WorkspaceActionBar";
import { WorkspaceEmptyStateCard } from "./layout/WorkspaceEmptyStateCard";
import { WorkspaceMessageStack } from "./layout/WorkspaceMessageStack";
import { WorkspaceMetadataGrid, WorkspaceMetadataItem } from "./layout/WorkspaceMetadataGrid";
import {
  ApiRequestError,
  adoptMigrationPublishRepository,
  approveMigrationArtifactVersion,
  deleteMigrationArtifactVersion,
  deployMigrationArtifactVersion,
  fetchMigrationArtifactVersions,
  fetchMigrationDraftReadiness,
  fetchMigrationDeployHistory,
  fetchMigrationMediaAssets,
  fetchMigrationPublishHistory,
  fetchMigrationWorkspaceSummary,
  generateMigrationDraftArtifacts,
  importMigrationDiscoveredMediaAssets,
  ingestMigrationSource,
  publishMigrationArtifactVersion,
  refreshMigrationDeployStatus,
  suggestMigrationRequirementField,
  suggestMigrationMediaAssetsMetadataBatch,
  updateMigrationMediaAsset,
  updateMigrationMediaAssetLifecycle,
  updateMigrationPublishConfig,
  updateMigrationDeployConfig,
  updateMigrationRequirements,
  uploadMigrationMediaAsset,
  upsertMigrationWorkspace,
} from "../lib/api/client";
import type {
  MigrationArtifactVersion,
  MigrationDeployConfig,
  MigrationOperatorRequirements,
  MigrationRequirementSuggestionField,
  MigrationPublishConfig,
  MigrationWorkspaceSummary,
} from "../lib/api/types";

interface MigrationWorkspacePanelProps {
  token: string;
  businessId: string;
  siteId: string;
}

type BusyAction =
  | "load"
  | "ingest"
  | "save_requirements"
  | "save_publish_config"
  | "save_deploy_config"
  | "generate"
  | "approve"
  | "adopt_repository"
  | "publish"
  | "deploy"
  | "refresh_deploy_status"
  | "delete_draft"
  | "upload_media"
  | "import_media"
  | "suggest_media"
  | "suggest_media_batch"
  | "update_media"
  | null;

const EMPTY_REQUIREMENTS: MigrationOperatorRequirements = {
  business_objectives: [],
  requested_pages: [],
  must_include: [],
  must_avoid: [],
  tone_preferences: [],
  calls_to_action: [],
  additional_notes: null,
};

type RequirementSuggestionStatus = "idle" | "loading" | "completed" | "failed" | "not_available";

interface RequirementSuggestionState {
  value: string;
  status: RequirementSuggestionStatus;
  reasonCode: string | null;
  errorMessage: string | null;
  contextSourcesUsed: string[];
  generatedAt: string | null;
  open: boolean;
}

function createEmptyRequirementSuggestionState(): RequirementSuggestionState {
  return {
    value: "",
    status: "idle",
    reasonCode: null,
    errorMessage: null,
    contextSourcesUsed: [],
    generatedAt: null,
    open: false,
  };
}

function createDefaultRequirementSuggestionMap(): Record<MigrationRequirementSuggestionField, RequirementSuggestionState> {
  return {
    business_objectives: createEmptyRequirementSuggestionState(),
    requested_pages: createEmptyRequirementSuggestionState(),
    must_include: createEmptyRequirementSuggestionState(),
    must_avoid: createEmptyRequirementSuggestionState(),
    tone: createEmptyRequirementSuggestionState(),
    calls_to_action: createEmptyRequirementSuggestionState(),
  };
}

const EMPTY_PUBLISH_CONFIG: MigrationPublishConfig = {
  enabled: true,
  repo_owner: null,
  repo_name: null,
  branch: null,
  artifact_root: null,
};

const MIGRATION_UPLOAD_ALLOWED_MIME_TYPES = new Set([
  "image/jpeg",
  "image/png",
  "image/webp",
  "image/gif",
]);

type MigrationFailureCategory =
  | "config_missing"
  | "target_invalid"
  | "approval_required"
  | "duplicate_request"
  | "artifact_invalid"
  | "provider_error"
  | "deploy_error"
  | "unknown_error";

type DraftGenerationFailureCategory =
  | "provider_error"
  | "artifact_invalid"
  | "config_missing"
  | "unknown_error";

type DraftReadinessStatus = "ready" | "ready_with_warnings" | "not_ready";

interface DraftReadinessReason {
  code: string;
  severity: "warning" | "blocking";
  message: string;
}

interface DraftReadinessEvaluation {
  status: DraftReadinessStatus;
  score: number;
  hardBlocked: boolean;
  summary: string;
  reasons: DraftReadinessReason[];
  signals: Record<string, boolean>;
}

interface DraftProviderCompatibilityEvaluation {
  supported: boolean;
  reasonCode: string;
  operatorMessage: string;
  retryable: boolean;
}

type DraftGenerationStateStatus =
  | "ready"
  | "ready_with_warnings"
  | "blocked_by_workspace"
  | "blocked_by_provider"
  | "generation_failed"
  | "generation_partial"
  | "generation_succeeded";

interface DraftGenerationStateEvaluation {
  status: DraftGenerationStateStatus;
  summary: string;
}

interface DraftAIExecutionSummary {
  modelRequested: string | null;
  modelResolved: string | null;
  modelUsed: string | null;
  endpointPath: string | null;
  requestBodyMode: string | null;
  compatibilityDecision: string | null;
  failureSource: string | null;
  requestContractStatus: string | null;
  providerExecutionStatus: string | null;
  artifactStatus: string | null;
  artifactResult: string | null;
  durationMs: number | null;
  timeoutSeconds: number | null;
  timeoutSource: "admin" | "default" | null;
  preflightMode: string | null;
  maxFinalInputChars: number | null;
  maxDifficultyScore: number | null;
  compactFallbackAttempted: boolean | null;
  budgetCapped: boolean | null;
  preflightBlocked: boolean | null;
  preflightBlockReason: string | null;
  preflightBlockedSetting: string | null;
  preflightBlockedSettingActual: number | null;
  preflightBlockedSettingCap: number | null;
  providerCallSkipped: boolean | null;
}

type ArtifactQualityStatus = "high" | "medium" | "low";

interface ArtifactQualityIssue {
  type: string;
  description: string;
}

interface ArtifactQualitySummary {
  qualityStatus: ArtifactQualityStatus;
  operatorSummary: string;
  issues: ArtifactQualityIssue[];
}

interface MigrationDestinationSummaryEvaluation {
  draftPreviewState: string;
  draftPreviewEntryPath: string | null;
  publishRepository: string | null;
  publishBranch: string | null;
  publishArtifactRoot: string | null;
  publishExpectedLocation: string | null;
  publishRepositoryUrl: string | null;
  publishExpectedPublishedUrl: string | null;
  publishState: string;
  publishUrlSource: string | null;
  publishUrlSourceDetail: string | null;
  deployExpectedPublishUrl: string | null;
  deployResolvedLiveUrl: string | null;
  deployPreviewHostname: string | null;
  deployPreviewUrl: string | null;
  deployPreviewState: string;
  deployCustomerDomainUrl: string | null;
  deployCustomerDomainLiveUrl: string | null;
  deployCustomerDomainState: string;
  deployState: string;
  deployUrlSource: string | null;
  deployUrlSourceDetail: string | null;
  deployWorkflowMode: string | null;
  deployTargetEnvironmentKey: string | null;
  deployTargetEnvironmentSource: string | null;
  deploySiteWorkflowFilePath: string | null;
  deployKubernetesNamespace: string | null;
  deployNamespaceSource: string | null;
  deployNamespaceModelStatus: string | null;
  deployWorkflowNamespaceAligned: boolean | null;
  deployManifestNamespaceAligned: boolean | null;
  managedResourceQuotaExpected: boolean | null;
  managedResourceQuotaPresent: boolean | null;
  managedLimitRangeExpected: boolean | null;
  managedLimitRangePresent: boolean | null;
  managedNetworkPolicyExpected: boolean | null;
  managedNetworkPolicyPresent: boolean | null;
  managedNamespacePoliciesAligned: boolean | null;
  currentSiteUrl: string | null;
}

interface DraftPreviewEvaluation {
  available: boolean;
  entryPath: string | null;
  pages: Array<{
    path: string;
    html: string;
    title: string;
  }>;
  reason: string | null;
}

type DeployConsistencyGateStatus = "pass" | "blocked" | "pending" | "warning" | "unknown";

interface MigrationSummaryCardProps {
  label: string;
  emphasis?: boolean;
  children: ReactNode;
}

function MigrationSummaryCard({ label, emphasis = false, children }: MigrationSummaryCardProps): JSX.Element {
  return (
    <div className={emphasis ? "migration-summary-card migration-summary-card-primary" : "migration-summary-card"}>
      <span className="migration-summary-label">{label}</span>
      <div className="migration-summary-value">{children}</div>
    </div>
  );
}

interface MigrationSummarySectionProps {
  workspaceSiteName: string;
  draftGenerationStateStatus: DraftGenerationStateStatus;
  draftGenerationStateLabel: string;
  draftGenerationStateSummary: string;
  draftGenerationStateToneClass: string;
  nextActionMessage: string;
  latestDraftStatusLabel: string;
  selectedArtifactVersionIdTrimmed: string;
  topQualityBadgeClass: string;
  topQualityStatusLabel: string;
  latestArtifactQualityOperatorSummary: string | null;
  summaryPriorityAlert: string | null;
}

function MigrationSummarySection({
  workspaceSiteName,
  draftGenerationStateStatus,
  draftGenerationStateLabel,
  draftGenerationStateSummary,
  draftGenerationStateToneClass,
  nextActionMessage,
  latestDraftStatusLabel,
  selectedArtifactVersionIdTrimmed,
  topQualityBadgeClass,
  topQualityStatusLabel,
  latestArtifactQualityOperatorSummary,
  summaryPriorityAlert,
}: MigrationSummarySectionProps): JSX.Element {
  return (
    <>
      <div className="panel panel-compact stack" data-testid="migration-draft-banner">
        <strong>Draft-only mode: generated files are review artifacts pending explicit approval/publish/deploy.</strong>
        <span className="hint">
          Legacy source content may be incomplete or poor quality. Operator requirements are the source of truth, with
          supporting context applied at lower priority.
        </span>
        <span className="hint warning">GitHub publish does not equal production deployment. Deploy remains explicit.</span>
      </div>

      <div className="panel panel-compact stack migration-summary-band" data-testid="migration-summary-band">
        <strong>Migration Summary</strong>
        <div className="migration-summary-grid">
          <MigrationSummaryCard label="Site">
            <strong data-testid="migration-summary-site-name">{workspaceSiteName}</strong>
          </MigrationSummaryCard>
          <MigrationSummaryCard label="Migration state">
            <span className={draftGenerationStateBadgeClass(draftGenerationStateStatus)}>{draftGenerationStateLabel}</span>
            <span className={draftGenerationStateToneClass}>{draftGenerationStateSummary}</span>
          </MigrationSummaryCard>
          <MigrationSummaryCard label="Next action" emphasis={true}>
            <strong data-testid="migration-next-action">{nextActionMessage}</strong>
          </MigrationSummaryCard>
          <MigrationSummaryCard label="Latest draft">
            <strong>{latestDraftStatusLabel}</strong>
            <span className="hint muted">Selected version: {selectedArtifactVersionIdTrimmed || "None"}</span>
          </MigrationSummaryCard>
          <MigrationSummaryCard label="Artifact quality">
            <span className={topQualityBadgeClass}>Quality: {topQualityStatusLabel}</span>
            <span className="hint muted">
              {latestArtifactQualityOperatorSummary || "Generate and review an artifact to score quality."}
            </span>
          </MigrationSummaryCard>
        </div>
        {summaryPriorityAlert ? (
          <span className="hint warning" data-testid="migration-summary-priority-alert">
            {summaryPriorityAlert}
          </span>
        ) : null}
      </div>
    </>
  );
}

interface MigrationSectionWrapperProps {
  children: ReactNode;
}

function MigrationSourceRequirementsSection({ children }: MigrationSectionWrapperProps): JSX.Element {
  return (
    <>
      <h3 className="hint muted migration-section-title">A. Source + Requirements</h3>
      <p className="hint muted migration-section-subtitle">
        Capture source context and operator replacement requirements before draft generation.
      </p>
      {children}
    </>
  );
}

function MigrationMediaSection({ children }: MigrationSectionWrapperProps): JSX.Element {
  return (
    <>
      <h3 className="hint muted migration-section-title">B. Media / Images</h3>
      <p className="hint muted migration-section-subtitle">
        Media counts, selection status, and image actions live only in this section.
      </p>
      {children}
    </>
  );
}

function MigrationDraftReadinessSection({ children }: MigrationSectionWrapperProps): JSX.Element {
  return (
    <>
      <h3 className="hint muted migration-section-title">C. Draft Readiness + Generate</h3>
      <p className="hint muted migration-section-subtitle">
        Confirm readiness and compatibility, then generate a draft when unblocked.
      </p>
      {children}
    </>
  );
}

function MigrationArtifactReviewSection({ children }: MigrationSectionWrapperProps): JSX.Element {
  return (
    <>
      <h3 className="hint muted migration-section-title">D. Draft Artifact Review</h3>
      <p className="hint muted migration-section-subtitle">
        Review the selected artifact, check quality, then preview, approve, or delete the draft.
      </p>
      {children}
    </>
  );
}

function MigrationPublishDeploySection({ children }: MigrationSectionWrapperProps): JSX.Element {
  return (
    <>
      <h3 className="hint muted migration-section-title">E. Approval / Publish / Deploy</h3>
      <p className="hint muted migration-section-subtitle">
        Approval, publish, and deploy remain explicit and unchanged.
      </p>
      {children}
    </>
  );
}

function MigrationAdvancedDiagnosticsSection({ children }: MigrationSectionWrapperProps): JSX.Element {
  return (
    <>
      <h3 className="hint muted migration-section-title">F. Advanced Diagnostics &amp; History</h3>
      <p className="hint muted migration-section-subtitle">
        Use detailed diagnostics and attempt history only when troubleshooting.
      </p>
      {children}
    </>
  );
}

function toFailureCategoryLabel(value: string | null): string {
  if (!value) {
    return "unknown";
  }
  return value.replace(/_/g, " ");
}

function toRuntimeConfigLabel(prerequisites: Record<string, unknown>): string {
  if (Boolean(prerequisites.github_publisher_configured)) {
    return "Ready";
  }
  const reasonCode = asString(prerequisites.github_publisher_reason_code).trim().toLowerCase();
  if (reasonCode === "runtime_credential_missing") {
    return "Credential unavailable";
  }
  if (reasonCode === "runtime_configuration_invalid") {
    return "Invalid runtime configuration";
  }
  if (reasonCode === "runtime_integration_unavailable") {
    return "Integration unavailable";
  }
  return "Missing/invalid";
}

function parseBlockerCodes(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((item) => asString(item).trim().toLowerCase())
    .filter((item) => item.length > 0);
}

function toDeployBlockerMessage(blockerCodes: string[]): string | null {
  if (blockerCodes.includes("published_artifact_missing")) {
    return "A published artifact is required before deploy.";
  }
  if (blockerCodes.includes("deploy_runtime_unavailable")) {
    return "Platform runtime action required: deploy runtime is unavailable.";
  }
  if (blockerCodes.includes("deploy_integration_unavailable")) {
    return "Platform deployment integration is not configured.";
  }
  if (blockerCodes.includes("deploy_configuration_invalid")) {
    return "Deployment target configuration is invalid.";
  }
  if (blockerCodes.includes("deploy_configuration_missing")) {
    return "Deployment target configuration is missing or disabled.";
  }
  return null;
}

function toErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiRequestError) {
    const message = (error.message || "").trim();
    if (message) {
      return message;
    }
  }
  if (error instanceof Error) {
    const message = (error.message || "").trim();
    if (message) {
      return message;
    }
  }
  return fallback;
}

function parseFailureCategory(
  error: unknown,
  message: string,
  action: "publish" | "deploy" | "approve",
): MigrationFailureCategory {
  if (error instanceof ApiRequestError) {
    const detail = asRecord(error.detail);
    const category = asString(detail.failure_category).trim().toLowerCase();
    if (
      category === "config_missing" ||
      category === "target_invalid" ||
      category === "approval_required" ||
      category === "duplicate_request" ||
      category === "artifact_invalid" ||
      category === "provider_error" ||
      category === "deploy_error" ||
      category === "unknown_error"
    ) {
      return category;
    }
  }
  const normalized = message.trim().toLowerCase();
  if (
    normalized.includes("not configured") ||
    normalized.includes("configuration") ||
    (normalized.includes("credential") && normalized.includes("unavailable")) ||
    (normalized.includes("integration") && normalized.includes("unavailable"))
  ) {
    return "config_missing";
  }
  if (normalized.includes("invalid") || normalized.includes("requires")) {
    return "target_invalid";
  }
  if (normalized.includes("not approved") || normalized.includes("must be published before deploy")) {
    return "approval_required";
  }
  if (normalized.includes("already published") || normalized.includes("already recorded") || normalized.includes("already approved")) {
    return "duplicate_request";
  }
  if (normalized.includes("no publishable files") || normalized.includes("no generated files")) {
    return "artifact_invalid";
  }
  if (action === "deploy") {
    return "deploy_error";
  }
  return "provider_error";
}

function formatActionFailureMessage(
  action: "publish" | "deploy" | "approve",
  category: MigrationFailureCategory,
  message: string,
): string {
  if (category === "config_missing") {
    return `${action === "deploy" ? "Deploy" : action === "publish" ? "Publish" : "Approval"} blocked by runtime configuration. ${message}`;
  }
  if (category === "target_invalid") {
    return `${action === "deploy" ? "Deploy" : action === "publish" ? "Publish" : "Approval"} blocked by target validation. ${message}`;
  }
  if (category === "approval_required") {
    return `${
      action === "deploy" ? "Deploy" : action === "publish" ? "Publish" : "Approval"
    } prerequisites are not satisfied (approval/publish ordering). ${message}`;
  }
  if (category === "duplicate_request") {
    return `Duplicate ${action} request detected. ${message}`;
  }
  if (category === "artifact_invalid") {
    return `${action === "deploy" ? "Deploy" : action === "publish" ? "Publish" : "Approval"} blocked by artifact validation. ${message}`;
  }
  if (category === "deploy_error") {
    return `Deploy execution failed. ${message}`;
  }
  if (category === "provider_error") {
    return `${action === "deploy" ? "Deploy" : action === "publish" ? "Publish" : "Approval"} execution failed. ${message}`;
  }
  return message;
}

function parseDraftGenerationFailure(error: unknown): {
  message: string;
  hint: string | null;
  correlationId: string | null;
} {
  let message = toErrorMessage(error, "Draft generation failed.");
  let category: DraftGenerationFailureCategory = "unknown_error";
  let reason = "";
  let reasonCode = "";
  let retryable: boolean | null = null;
  let correlationId: string | null = null;
  let timeoutSeconds: number | null = null;
  let statusCode: number | null = null;
  let operatorAction: string | null = null;
  if (error instanceof ApiRequestError) {
    statusCode = error.status;
    const detail = asRecord(error.detail);
    const detailMessage = asString(detail.message).trim();
    if (detailMessage) {
      message = detailMessage;
    }
    const categoryValue = asString(detail.failure_category).trim().toLowerCase();
    if (
      categoryValue === "provider_error" ||
      categoryValue === "artifact_invalid" ||
      categoryValue === "config_missing" ||
      categoryValue === "unknown_error"
    ) {
      category = categoryValue;
    }
    reason = asString(detail.failure_reason).trim().toLowerCase();
    reasonCode = asString(detail.error_code || detail.reason_code).trim().toLowerCase();
    operatorAction = asStringOrNull(detail.operator_action);
    retryable = typeof detail.retryable === "boolean" ? detail.retryable : null;
    timeoutSeconds = typeof detail.timeout_seconds === "number" ? Math.max(1, Math.round(detail.timeout_seconds)) : null;
    correlationId =
      asStringOrNull(detail.correlation_id) ||
      asStringOrNull(detail.artifact_version_id) ||
      asStringOrNull(detail.workspace_id);
  }
  let hint: string | null = null;
  if (reason === "timeout" && timeoutSeconds !== null) {
    hint = `Draft generation timed out after ${timeoutSeconds} seconds.`;
  } else if (reason === "timeout" && retryable) {
    hint = "This looks retryable.";
  } else if (reasonCode === "app_auth_required" || reasonCode === "session_expired") {
    hint = "App session expired. Sign back into MBSRN and retry draft generation.";
  } else if (reasonCode === "google_reconnect_required") {
    hint = "Google Search Console/Analytics reconnect is required before draft generation can use live Google signals.";
  } else if (reasonCode === "google_integration_unavailable") {
    hint = "Google integration status is unavailable right now. Retry shortly, then reconnect Google if it persists.";
  } else if (reasonCode === "draft_generation_context_unavailable") {
    hint = "Draft context is currently unavailable. Retry and contact support if this keeps happening.";
  } else if (reasonCode === "migration_generation_preflight_too_large") {
    hint =
      "Generation was blocked before provider call by preflight safety settings. Reduce requirements/selected context or ask Admin to increase bounded migration AI budget.";
  } else if (statusCode === 401) {
    hint = "Operator session appears expired. Re-authenticate to MBSRN. This is separate from Google integration reconnect.";
  } else if (statusCode === 403) {
    hint = "Request was denied by API authorization policy. Review operator role/site scope.";
  } else if (
    reasonCode.includes("google")
    && (reasonCode.includes("reconnect") || reasonCode.includes("consent") || reasonCode.includes("token"))
  ) {
    hint = "Google integration reconnect may be required for analytics signals. Operator session remains separate.";
  } else if (category === "config_missing" || reason === "authentication_failed" || reason === "unsupported_configuration") {
    hint = "Check AI provider configuration.";
  } else if (
    category === "artifact_invalid" ||
    reason === "malformed_response" ||
    reason === "empty_response" ||
    reason === "validation_failed"
  ) {
    hint = "The provider returned an invalid draft payload.";
  } else if (operatorAction) {
    hint = operatorAction;
  } else if (retryable) {
    hint = "This looks retryable.";
  }
  return {
    message,
    hint,
    correlationId,
  };
}

function toDraftAuthIntegrationGuidance(value: string | null): string | null {
  const normalized = (value || "").trim().toLowerCase();
  if (!normalized) {
    return null;
  }
  if (normalized === "app_auth_required" || normalized === "session_expired") {
    return "App session expired. Sign back into MBSRN before retrying draft generation.";
  }
  if (normalized === "google_reconnect_required") {
    return "Google Search Console / Analytics reconnect is required for live Google draft signals.";
  }
  if (normalized === "google_integration_unavailable") {
    return "Google integration state could not be read. Retry shortly, then reconnect Google if this persists.";
  }
  if (normalized === "draft_generation_context_unavailable") {
    return "Draft context could not be assembled. Retry and contact support if the issue persists.";
  }
  if (normalized.includes("google") && normalized.includes("reconnect")) {
    return "Google integration reconnect is required for some analytics signals. Operator app session remains separate.";
  }
  if (normalized.includes("google") && normalized.includes("token")) {
    return "Google integration token refresh failed. Reconnect Google integration and retry draft generation.";
  }
  if (normalized === "authentication_failed" || normalized.includes("session")) {
    return "Operator session authentication may have expired. Re-authenticate in MBSRN and retry.";
  }
  return null;
}

function toMediaSuggestionStatusLabel(value: string | null): string {
  const normalized = (value || "").trim().toLowerCase();
  if (normalized === "completed") {
    return "Suggestion ready";
  }
  if (normalized === "pending") {
    return "Suggestion pending";
  }
  if (normalized === "not_available") {
    return "Suggestion not available";
  }
  if (normalized === "failed") {
    return "Suggestion failed";
  }
  return "Not analyzed yet";
}

function toMediaSuggestionReasonLabel(value: string | null): string | null {
  const normalized = (value || "").trim().toLowerCase();
  if (!normalized) {
    return null;
  }
  if (normalized === "image_metadata_suggested") {
    return "AI metadata suggestion completed.";
  }
  if (normalized === "image_not_imported") {
    return "Image must be imported before AI metadata can be suggested.";
  }
  if (normalized === "media_asset_not_imported") {
    return "Import before using in draft or AI image analysis.";
  }
  if (normalized === "media_asset_not_available") {
    return "Image is not currently available for draft or AI analysis actions.";
  }
  if (normalized === "media_asset_low_value") {
    return "Image was classified as low-value and is excluded from draft/suggestion actions.";
  }
  if (normalized === "media_asset_rejected") {
    return "Image was rejected and cannot be used for draft or AI analysis.";
  }
  if (normalized === "media_action_not_allowed_for_state") {
    return "Action is not allowed for this image lifecycle state.";
  }
  if (normalized === "placeholder_image_detected") {
    return "Candidate was classified as placeholder-like imagery.";
  }
  if (normalized === "tracking_pixel_detected") {
    return "Candidate was classified as tracking/beacon imagery.";
  }
  if (normalized === "layout_asset_detected") {
    return "Candidate was classified as layout/chrome imagery.";
  }
  if (normalized === "non_image_candidate_detected") {
    return "Candidate appears to be a non-image URL.";
  }
  if (normalized === "image_analysis_not_available") {
    return "AI image analysis is not available for this image in the current runtime.";
  }
  if (normalized === "unsupported_image_type") {
    return "Unsupported image type for AI metadata suggestion.";
  }
  if (normalized === "image_too_large") {
    return "Image is too large for metadata suggestion in this pass.";
  }
  if (normalized === "provider_unavailable") {
    return "AI provider is unavailable for image metadata suggestion.";
  }
  if (normalized === "provider_response_invalid") {
    return "AI provider returned an invalid metadata suggestion response.";
  }
  if (normalized === "media_asset_not_found") {
    return "Image was not found for suggestion.";
  }
  if (normalized === "media_asset_not_authorized") {
    return "Image is not authorized for this workspace.";
  }
  if (normalized === "media_suggestion_batch_limit_reached") {
    return "Batch suggestion request exceeds the allowed image count.";
  }
  if (normalized === "remote_image_import_disabled") {
    return "Remote source image import is currently disabled for this environment.";
  }
  if (normalized === "remote_import_disabled") {
    return "Remote source image import is currently disabled for this environment.";
  }
  if (normalized === "remote_image_imported") {
    return "Source image imported into workspace media.";
  }
  if (normalized === "image_not_found_in_source_snapshot") {
    return "The requested discovered image was not found in the current source snapshot.";
  }
  if (normalized === "image_import_unsafe_url") {
    return "Source image URL is not eligible for safe import.";
  }
  if (normalized === "candidate_not_validated") {
    return "Source candidate was not content-validated as an importable image. Refresh discovery first.";
  }
  if (normalized === "image_import_private_address_blocked") {
    return "Source image URL resolves to a blocked private/internal address.";
  }
  if (normalized === "blocked_private_network") {
    return "Source image URL resolves to a blocked private/internal address.";
  }
  if (normalized === "image_fetch_timeout") {
    return "Source image fetch timed out before completion.";
  }
  if (normalized === "fetch_timeout") {
    return "Source image fetch timed out before completion.";
  }
  if (normalized === "image_fetch_failed") {
    return "Source image fetch failed.";
  }
  if (normalized === "image_content_type_mismatch") {
    return "Source image content type does not match payload signature.";
  }
  if (normalized === "unsupported_content_type" || normalized === "unsupported_image_type") {
    return "Source candidate content type is not importable as an image.";
  }
  if (normalized === "file_too_large" || normalized === "image_too_large") {
    return "Source image exceeds the import size limit.";
  }
  if (normalized === "unsafe_redirect") {
    return "Source image URL redirect chain was blocked for safety.";
  }
  if (normalized === "storage_write_failed") {
    return "Source image fetch succeeded but storing the image failed.";
  }
  if (normalized === "media_import_count_limit_reached") {
    return "Source image import limit was reached for this workspace/request.";
  }
  if (normalized === "removed") {
    return "Image was removed from this migration workspace.";
  }
  if (normalized === "ignored") {
    return "Discovered image was ignored and hidden from the default list.";
  }
  if (normalized === "already_removed") {
    return "Image was already removed or ignored.";
  }
  if (normalized === "not_found") {
    return "Image was not found in this migration workspace.";
  }
  if (normalized === "not_authorized") {
    return "Image is not authorized for this migration workspace.";
  }
  if (normalized === "unsafe_delete_blocked") {
    return "This image cannot be removed in the current lifecycle state.";
  }
  if (normalized === "storage_delete_failed") {
    return "Image metadata was updated, but local storage cleanup failed.";
  }
  return `Suggestion reason: ${normalized}`;
}

function toMediaSuggestionBatchStatusLabel(value: string | null): string {
  const normalized = (value || "").trim().toLowerCase();
  if (normalized === "completed") {
    return "Completed";
  }
  if (normalized === "partial_success") {
    return "Partial success";
  }
  if (normalized === "failed") {
    return "Failed";
  }
  return "Unknown";
}

function toMediaImportStatusLabel(value: string | null): string {
  const normalized = (value || "").trim().toLowerCase();
  if (normalized === "imported") {
    return "Imported";
  }
  if (normalized === "skipped") {
    return "Skipped";
  }
  if (normalized === "failed") {
    return "Failed";
  }
  if (normalized === "disabled") {
    return "Disabled";
  }
  return "Unknown";
}

function toMediaLifecycleLabels(asset: Record<string, unknown>): string[] {
  const labels: string[] = [];
  const provenance = asStringOrNull(asset.provenance);
  const importStatus = (asStringOrNull(asset.import_status) || "").toLowerCase();
  const candidateQuality = (asStringOrNull(asset.candidate_quality) || "useful").toLowerCase();
  const selectedForDraft = Boolean(asset.selected_for_draft);
  const metadataSuggestionApplied = Boolean(asset.metadata_suggestion_applied);
  const suggestion = asRecord(asset.metadata_suggestion);
  const suggestionStatus = (asStringOrNull(suggestion.suggestion_status) || "").toLowerCase();
  if (provenance === "source_site_import") {
    labels.push("Discovered");
    if (candidateQuality === "low_value") {
      labels.push("Low Value");
    }
    if (candidateQuality === "rejected") {
      labels.push("Rejected");
    }
    if (
      importStatus === "selected" ||
      importStatus === "imported" ||
      importStatus === "uploaded" ||
      importStatus === "available"
    ) {
      labels.push("Imported");
    } else if (importStatus === "discovered" && candidateQuality === "useful") {
      labels.push("Not Available");
    }
  } else if (provenance === "operator_upload") {
    labels.push("Uploaded");
  }
  if (selectedForDraft && isMediaAssetUsableForDraft(asset)) {
    labels.push("Included in Draft");
  }
  if (suggestionStatus === "completed") {
    labels.push("AI Suggested");
  } else if (suggestionStatus === "not_available") {
    labels.push("Not Available");
  } else if (suggestionStatus === "failed" && candidateQuality !== "rejected") {
    labels.push("Rejected");
  }
  if (metadataSuggestionApplied) {
    labels.push("Applied");
  }
  const uniqueLabels: string[] = [];
  const seen = new Set<string>();
  for (const label of labels) {
    const key = label.toLowerCase();
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    uniqueLabels.push(label);
  }
  return uniqueLabels;
}

function toMediaLifecycleBadgeClass(label: string): string {
  if (label === "Included in Draft" || label === "AI Suggested" || label === "Applied") {
    return "badge badge-success";
  }
  if (label === "Low Value") {
    return "badge badge-warn";
  }
  if (label === "Imported" || label === "Uploaded") {
    return "badge badge-warn";
  }
  if (label === "Not Available" || label === "Rejected") {
    return "badge badge-error";
  }
  return "badge";
}

type MediaPrimaryAction = "use_in_draft" | "use_in_draft_anyway" | "none";
type MediaLifecycleAction = "remove" | "ignore" | "none";

type MediaBrowserFilter =
  | "all_usable"
  | "discovered"
  | "uploaded_imported"
  | "unsafe_rejected";

function toMediaAssetDisplayName(asset: Record<string, unknown>, fallback: string): string {
  const displayFilename = asStringOrNull(asset.display_filename);
  if (displayFilename) {
    return displayFilename;
  }
  const filename = asStringOrNull(asset.filename);
  if (filename) {
    return filename;
  }
  const normalizedUrl = asStringOrNull(asset.normalized_url);
  if (normalizedUrl) {
    try {
      const parsed = new URL(normalizedUrl);
      const pathTail = parsed.pathname.split("/").filter(Boolean).slice(-2).join("/");
      if (pathTail) {
        return `${parsed.hostname}/${pathTail}`;
      }
      return parsed.hostname;
    } catch {
      return normalizedUrl;
    }
  }
  return fallback;
}

type MediaPreviewUnavailableReasonCode =
  | "preview_url_missing"
  | "preview_url_unsafe"
  | "image_not_imported"
  | "unsupported_image_type"
  | "storage_preview_not_available";

function isPrivateOrBlockedHostname(hostname: string): boolean {
  const normalized = hostname.trim().toLowerCase();
  if (!normalized) {
    return true;
  }
  if (
    normalized === "localhost" ||
    normalized === "metadata.google.internal" ||
    normalized === "metadata" ||
    normalized.endsWith(".local") ||
    normalized.endsWith(".internal")
  ) {
    return true;
  }
  if (
    normalized === "::1" ||
    normalized.startsWith("fc") ||
    normalized.startsWith("fd")
  ) {
    return true;
  }
  const octets = normalized.split(".");
  if (octets.length === 4 && octets.every((item) => /^\d+$/.test(item))) {
    const [first, second] = octets.map((item) => Number.parseInt(item, 10));
    if (!Number.isFinite(first) || !Number.isFinite(second)) {
      return true;
    }
    if (first === 10 || first === 127 || first === 0) {
      return true;
    }
    if (first === 169 && second === 254) {
      return true;
    }
    if (first === 172 && second >= 16 && second <= 31) {
      return true;
    }
    if (first === 192 && second === 168) {
      return true;
    }
  }
  return false;
}

const MIGRATION_MEDIA_PREVIEW_PATH_PATTERN =
  /^\/api\/businesses\/[^/]+\/seo\/sites\/[^/]+\/migration\/media\/assets\/[^/]+\/preview$/i;

function resolveSafeMediaPreviewUrl(rawUrl: string | null): string | null {
  if (!rawUrl) {
    return null;
  }
  const trimmed = rawUrl.trim();
  if (!trimmed) {
    return null;
  }
  const isRelativePath = trimmed.startsWith("/");
  try {
    if (isRelativePath) {
      if (typeof window === "undefined" || !window.location?.origin) {
        return null;
      }
      const parsed = new URL(trimmed, window.location.origin);
      if (parsed.origin !== window.location.origin) {
        return null;
      }
      if (!MIGRATION_MEDIA_PREVIEW_PATH_PATTERN.test(parsed.pathname)) {
        return null;
      }
      parsed.search = "";
      parsed.hash = "";
      return parsed.pathname;
    }

    const parsed = new URL(trimmed);
    const protocol = parsed.protocol.trim().toLowerCase();
    if (protocol !== "https:" && protocol !== "http:") {
      return null;
    }
    if (isPrivateOrBlockedHostname(parsed.hostname)) {
      return null;
    }
    parsed.search = "";
    parsed.hash = "";
    return parsed.toString();
  } catch {
    return null;
  }
}

function resolveMediaPreviewAvailability(
  asset: Record<string, unknown>,
  options: { remoteImportRequired: boolean },
): { previewUrl: string | null; reasonCode: MediaPreviewUnavailableReasonCode | null } {
  const contentType = (asStringOrNull(asset.content_type) || "").trim().toLowerCase();
  if (contentType && !contentType.startsWith("image/")) {
    return {
      previewUrl: null,
      reasonCode: "unsupported_image_type",
    };
  }
  const candidateUrls = [
    asStringOrNull(asset.preview_url),
    asStringOrNull(asset.display_url),
    asStringOrNull(asset.normalized_url),
  ].filter((value): value is string => Boolean(value));
  let hadUnsafeCandidate = false;
  for (const candidateUrl of candidateUrls) {
    const safePreviewUrl = resolveSafeMediaPreviewUrl(candidateUrl);
    if (safePreviewUrl) {
      return {
        previewUrl: safePreviewUrl,
        reasonCode: null,
      };
    }
    hadUnsafeCandidate = true;
  }
  const provenance = (asStringOrNull(asset.provenance) || "").trim().toLowerCase();
  const importStatus = (asStringOrNull(asset.import_status) || "").trim().toLowerCase();
  const isControlledImage =
    provenance === "operator_upload"
    || importStatus === "imported"
    || importStatus === "selected"
    || importStatus === "available"
    || importStatus === "uploaded";
  if (options.remoteImportRequired) {
    return {
      previewUrl: null,
      reasonCode: hadUnsafeCandidate ? "preview_url_unsafe" : "image_not_imported",
    };
  }
  if (hadUnsafeCandidate) {
    return {
      previewUrl: null,
      reasonCode: "preview_url_unsafe",
    };
  }
  if (isControlledImage) {
    return {
      previewUrl: null,
      reasonCode: "storage_preview_not_available",
    };
  }
  return {
    previewUrl: null,
    reasonCode: "preview_url_missing",
  };
}

function toMediaPreviewUnavailableReasonLabel(value: MediaPreviewUnavailableReasonCode | null): string | null {
  if (value === "preview_url_missing") {
    return "Preview unavailable (preview_url_missing).";
  }
  if (value === "preview_url_unsafe") {
    return "Preview unavailable (preview_url_unsafe).";
  }
  if (value === "image_not_imported") {
    return "Preview unavailable until imported (image_not_imported).";
  }
  if (value === "unsupported_image_type") {
    return "Preview unavailable for unsupported image type (unsupported_image_type).";
  }
  if (value === "storage_preview_not_available") {
    return "Storage preview not available (storage_preview_not_available).";
  }
  return null;
}

function toImageReferenceSlug(displayName: string, fallbackAssetId: string): string {
  const normalizedDisplayName = displayName
    .trim()
    .toLowerCase()
    .replace(/\.[a-z0-9]{2,6}$/i, "");
  const fromDisplayName = normalizedDisplayName
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+/, "")
    .replace(/-+$/, "")
    .slice(0, 28);
  if (fromDisplayName) {
    return fromDisplayName;
  }
  const normalizedFallback = fallbackAssetId
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+/, "")
    .replace(/-+$/, "")
    .slice(0, 28);
  return normalizedFallback || "image-reference";
}

function toMediaPreviewAltText(asset: Record<string, unknown>): string {
  const suggestion = asRecord(asset.metadata_suggestion);
  return (
    asStringOrNull(asset.alt_text) ||
    asStringOrNull(suggestion.suggested_alt_text) ||
    asStringOrNull(asset.display_filename) ||
    asStringOrNull(asset.filename) ||
    "Image preview"
  );
}

function splitLines(value: string): string[] {
  return value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
}

function joinLines(values: string[] | null | undefined): string {
  if (!Array.isArray(values) || values.length === 0) {
    return "";
  }
  return values.map((item) => String(item || "").trim()).filter(Boolean).join("\n");
}

function asRecord(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return {};
  }
  return value as Record<string, unknown>;
}

function asString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function asStringOrNull(value: unknown): string | null {
  const normalized = asString(value).trim();
  return normalized || null;
}

function asBooleanOrNull(value: unknown): boolean | null {
  if (typeof value === "boolean") {
    return value;
  }
  return null;
}

function asStringList(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((item) => String(item || "").trim())
    .filter((item) => item.length > 0);
}

function asRecordList(value: unknown): Array<Record<string, unknown>> {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((item) => asRecord(item))
    .filter((item) => Object.keys(item).length > 0);
}

function asNonNegativeInt(value: unknown): number | null {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return null;
  }
  return Math.max(0, Math.round(value));
}

function asNumberOrNull(value: unknown): number | null {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return null;
  }
  return value;
}

function formatMetricCount(value: number | null): string {
  if (value === null) {
    return "Not available";
  }
  return `${Math.max(0, Math.round(value))}`;
}

function formatEngagementRatePercent(value: number | null): string {
  if (value === null) {
    return "Not available";
  }
  return `${Math.round(value * 1000) / 10}%`;
}

function formatPercentDelta(value: number | null): string {
  if (value === null) {
    return "Not available";
  }
  const rounded = Math.round(value * 10) / 10;
  return `${rounded > 0 ? "+" : ""}${rounded}%`;
}

function formatPointsDelta(value: number | null): string {
  if (value === null) {
    return "Not available";
  }
  const asPercentPoints = Math.round(value * 1000) / 10;
  return `${asPercentPoints > 0 ? "+" : ""}${asPercentPoints} pts`;
}

function normalizeGa4OutcomeSnapshotStatus(value: string | null): string {
  const normalized = (value || "").trim().toLowerCase();
  if (
    normalized === "available"
    || normalized === "pending_after_window"
    || normalized === "insufficient_data"
    || normalized === "not_configured"
    || normalized === "missing_scope"
    || normalized === "permission_denied"
    || normalized === "unavailable"
  ) {
    return normalized;
  }
  return "unavailable";
}

function toGa4OutcomeStatusLabel(value: string): string {
  if (value === "available") {
    return "Available";
  }
  if (value === "pending_after_window") {
    return "Pending";
  }
  if (value === "insufficient_data") {
    return "Insufficient data";
  }
  if (value === "not_configured") {
    return "Not configured";
  }
  if (value === "missing_scope") {
    return "Missing authorization";
  }
  if (value === "permission_denied") {
    return "Permission issue";
  }
  return "Unavailable";
}

function toGa4OutcomeAnchorSubtitle(value: string | null): string {
  const normalized = (value || "").trim().toLowerCase();
  if (normalized === "migration_deployed") {
    return "Observed after deploy";
  }
  if (normalized === "migration_published") {
    return "Observed after publish";
  }
  return "Observed after migration event";
}

function mediaCandidateQuality(asset: Record<string, unknown>): "useful" | "low_value" | "rejected" {
  const normalized = (asStringOrNull(asset.candidate_quality) || "useful").trim().toLowerCase();
  if (normalized === "low_value") {
    return "low_value";
  }
  if (normalized === "rejected") {
    return "rejected";
  }
  return "useful";
}

function mediaCandidateReasonCode(asset: Record<string, unknown>): string | null {
  return asStringOrNull(asset.quality_reason);
}

function isSourceAssetImportRequired(asset: Record<string, unknown>): boolean {
  const provenance = (asStringOrNull(asset.provenance) || "source_site_import").trim().toLowerCase();
  if (provenance !== "source_site_import") {
    return false;
  }
  const importStatus = (asStringOrNull(asset.import_status) || "discovered").trim().toLowerCase();
  return importStatus === "discovered";
}

function isDiscoveredCandidateValidatedForImport(asset: Record<string, unknown>): boolean {
  const contentType = (asStringOrNull(asset.content_type) || "").trim().toLowerCase();
  const fetchStatus = (asStringOrNull(asset.fetch_status) || "").trim().toLowerCase();
  if (contentType.startsWith("image/")) {
    return true;
  }
  return fetchStatus === "validated_head" || fetchStatus === "validated_get" || fetchStatus === "validated_fetch";
}

function isDiscoveredQualityOverrideImportAllowed(asset: Record<string, unknown>): boolean {
  const candidateQuality = mediaCandidateQuality(asset);
  if (candidateQuality !== "low_value") {
    return false;
  }
  const reason = (mediaCandidateReasonCode(asset) || "").trim().toLowerCase();
  return reason !== "tracking_pixel_detected" && reason !== "non_image_candidate_detected";
}

function mediaAssetUnavailableReasonCode(asset: Record<string, unknown>): string | null {
  const candidateQuality = mediaCandidateQuality(asset);
  const candidateReason = mediaCandidateReasonCode(asset);
  if (candidateQuality === "low_value") {
    const normalizedReason = (candidateReason || "").trim().toLowerCase();
    if (normalizedReason === "tracking_pixel_detected" || normalizedReason === "non_image_candidate_detected") {
      return normalizedReason;
    }
    return null;
  }
  if (candidateQuality === "rejected") {
    return candidateReason || "media_asset_rejected";
  }

  const importStatus = (asStringOrNull(asset.import_status) || "").trim().toLowerCase();
  const provenance = (asStringOrNull(asset.provenance) || "").trim().toLowerCase();
  if (importStatus === "failed" || importStatus === "disabled" || importStatus === "not_available") {
    return "media_asset_not_available";
  }
  if (provenance === "source_site_import" && isSourceAssetImportRequired(asset) && !isDiscoveredCandidateValidatedForImport(asset)) {
    return "candidate_not_validated";
  }
  if (provenance === "source_site_import" && isSourceAssetImportRequired(asset)) {
    return "media_asset_not_imported";
  }
  if (
    provenance === "source_site_import"
    && importStatus !== "imported"
    && importStatus !== "selected"
    && importStatus !== "available"
  ) {
    return "media_asset_not_available";
  }
  return null;
}

function isMediaAssetUsableForDraft(asset: Record<string, unknown>): boolean {
  return mediaAssetUnavailableReasonCode(asset) === null;
}

function formatBooleanStateLabel(value: boolean | null, labels?: { trueLabel?: string; falseLabel?: string }): string {
  if (value === true) {
    return labels?.trueLabel || "Yes";
  }
  if (value === false) {
    return labels?.falseLabel || "No";
  }
  return "Unknown";
}

function formatReasonCodeLabel(value: string | null): string {
  if (!value) {
    return "Not available";
  }
  return value.replace(/_/g, " ");
}

function formatDispatchStageLabel(value: string | null): string {
  if (!value) {
    return "Not available";
  }
  const normalized = value.trim().toLowerCase();
  if (!normalized) {
    return "Not available";
  }
  if (normalized === "workflow_dispatch") {
    return "workflow dispatch";
  }
  if (normalized === "workflow_lookup") {
    return "workflow lookup";
  }
  if (normalized === "ref_lookup") {
    return "ref lookup";
  }
  if (normalized === "repo_lookup") {
    return "repo lookup";
  }
  return normalized.replace(/_/g, " ");
}

function toDeployConsistencyStatusLabel(value: DeployConsistencyGateStatus): string {
  if (value === "pass") {
    return "Pass";
  }
  if (value === "blocked") {
    return "Blocked";
  }
  if (value === "pending") {
    return "Pending";
  }
  if (value === "warning") {
    return "Warning";
  }
  return "Unknown";
}

function deployConsistencyStatusBadgeClass(value: DeployConsistencyGateStatus): string {
  if (value === "pass") {
    return "badge badge-success";
  }
  if (value === "blocked") {
    return "badge badge-error";
  }
  if (value === "pending") {
    return "badge badge-warn";
  }
  if (value === "warning") {
    return "badge badge-warn";
  }
  return "badge badge-muted";
}

function normalizeUpperOrNull(value: string | null): string | null {
  if (!value) {
    return null;
  }
  const normalized = value.trim().toUpperCase();
  return normalized.length > 0 ? normalized : null;
}

function isPendingWorkflowRunStatus(value: string | null): boolean {
  const normalized = (value || "").trim().toLowerCase();
  return normalized === "queued" || normalized === "in_progress" || normalized === "pending" || normalized === "requested";
}

function formatWorkflowRemediationOutcomeLabel(value: string | null): string {
  if (!value) {
    return "Not available";
  }
  const normalized = value.trim().toLowerCase();
  if (!normalized) {
    return "Not available";
  }
  return normalized.replace(/_/g, " ");
}

function toWorkflowRemediationOutcomeGuidance(value: string | null): string | null {
  const normalized = (value || "").trim().toLowerCase();
  if (!normalized) {
    return null;
  }
  if (normalized === "remediation_upgraded_managed_placeholder") {
    return "Managed workflow was upgraded during publish. Retry deploy.";
  }
  if (normalized === "remediation_already_current") {
    return "Managed workflow was already current.";
  }
  if (normalized === "remediation_preserved_custom") {
    return "Custom workflow was preserved. Manual workflow correction may be required.";
  }
  if (normalized === "remediation_write_failed") {
    return "Workflow remediation could not be written. Review integration/log details.";
  }
  if (normalized === "remediation_not_attempted") {
    return "Workflow remediation was not attempted on the last publish action.";
  }
  return null;
}

function toManagedGkeConfigGuidance(value: string | null): string | null {
  const normalized = (value || "").trim().toLowerCase();
  if (!normalized) {
    return null;
  }
  if (normalized === "missing_cluster_name") {
    return "Managed deploy target is missing required admin GKE cluster name configuration. Update admin deployment settings.";
  }
  if (normalized === "missing_cluster_location") {
    return "Managed deploy target is missing required admin GKE cluster location configuration. Update admin deployment settings.";
  }
  if (normalized === "missing_gcp_project_id") {
    return "Managed deploy target is missing required admin GKE project id configuration. Update admin deployment settings.";
  }
  if (normalized === "target_repo_deploy_secret_missing") {
    return "Deploy workflow requires target-repo secret GCP_DEPLOY_KEY, but it is missing. Run publish/bootstrap to provision deploy auth prerequisites, then retry deploy.";
  }
  if (normalized === "image_pull_secret_missing") {
    return "Private managed-site image auth is required, but required GHCR pull credentials (GIT_USERID, GIT_EMAIL, GIT_TOKEN) are missing in the MBSRN control-plane runtime. Configure MBSRN deployment settings and verify deploy-prod projects them into the API runtime secret. Target site repositories do not need these secrets.";
  }
  if (normalized === "image_pull_secret_not_referenced") {
    return "Managed deployment manifest is missing required image pull secret reference (ghcr-pull-secret). Republish managed deploy manifests.";
  }
  if (normalized === "certificate_domain_mismatch") {
    return "The deployed certificate does not match the site hostname. This usually means the managed certificate or ingress points at another site's hostname. Republish/deploy after admin verification of generated ingress/certificate resources.";
  }
  if (normalized === "tls_certificate_bound_to_wrong_site") {
    return "The deployed TLS certificate is bound to another site hostname. Republish/deploy after admin verification of generated ingress and managed certificate resources.";
  }
  if (normalized === "stale_managed_certificate_present") {
    return "A previous site's certificate is still present in this environment. This may cause incorrect SSL certificates to be served. Redeploy or remove stale certificates.";
  }
  if (normalized === "managed_certificate_identity_mismatch") {
    return "Managed certificate identity in this namespace does not match the current site. Redeploy or remove stale certificates after admin verification.";
  }
  if (normalized === "ingress_certificate_mismatch") {
    return "Ingress is referencing the wrong managed certificate for this site hostname. Republish/deploy after admin verification of generated ingress/certificate resources.";
  }
  if (normalized === "ingress_certificate_annotation_mismatch") {
    return "Ingress managed-certificate annotation does not match the expected site certificate. Republish/deploy after admin verification.";
  }
  if (normalized === "shared_static_ip_not_allowed_for_per_site_ingress" || normalized === "ingress_static_ip_conflict") {
    return "Per-site managed ingress cannot safely reuse one shared static IP. Republish managed ingress without shared static IP binding and redeploy.";
  }
  if (normalized === "stale_pre_shared_cert_binding_detected") {
    return "Ingress includes stale pre-shared certificate binding metadata. Republish managed ingress resources so ManagedCertificate remains the only certificate binding source.";
  }
  if (normalized === "managed_certificate_failed_not_visible") {
    return "ManagedCertificate is not visible for this hostname yet. Verify DNS/ingress exposure and certificate visibility before retry.";
  }
  if (normalized === "static_ip_address_missing_after_retry") {
    return "Google Cloud created or found the managed static IP resource, but the numeric IP address is still unavailable after bounded describe/list retries. This preview hostname needs the numeric managed preview IP before deploy can continue.";
  }
  if (normalized === "address_not_found_after_retry") {
    return "Google Cloud static IP resource could not be found by exact name after bounded retries/list fallback. Verify static IP scope and visibility for this managed preview deployment.";
  }
  if (normalized === "address_ambiguous_after_retry") {
    return "Google Cloud static IP lookup returned ambiguous matches after bounded retries/list fallback. Resolve duplicate/conflicting address resources, then retry deploy.";
  }
  if (normalized === "address_value_missing_after_retry") {
    return "Google Cloud static IP resource was found, but the numeric address value was still missing after bounded retries/list fallback. Wait and retry deploy after address convergence.";
  }
  if (normalized === "tls_certificate_provisioning" || normalized === "managed_certificate_provisioning") {
    return "Deploy reached the load balancer, but TLS is still provisioning for the preview hostname. Wait for ManagedCertificate to become ACTIVE, then refresh and retry deploy.";
  }
  if (normalized === "generated_workflow_requires_missing_gcp_deploy_key") {
    return "Deploy workflow run failed because required target-repo deploy secret GCP_DEPLOY_KEY was missing. Provision deploy auth prerequisites and rerun deploy.";
  }
  if (normalized === "backendconfig_health_check_mismatch") {
    return "BackendConfig health check path/port does not match the running site-web application health endpoint.";
  }
  if (normalized === "ingress_backend_unhealthy") {
    return "Ingress backend is unhealthy even though pods may be running. Verify BackendConfig, service endpoints, and load balancer backend health.";
  }
  if (normalized === "ingress_backend_502") {
    return "Preview hostname is reachable but returned HTTP 502. Backend health can still report healthy; review in-cluster service/endpoint probe status, pod runtime logs, and ingress/backend convergence diagnostics.";
  }
  if (normalized === "service_has_no_ready_endpoints") {
    return "Service has no ready endpoints for site-web. Verify pod readiness, service selectors, and endpoint population.";
  }
  if (normalized === "pod_ready_but_ingress_backend_unhealthy") {
    return "Pods are ready but ingress backend remains unhealthy. Verify NEG/backend health and load balancer checks.";
  }
  if (normalized === "service_endpoint_missing") {
    return "Service has no ready endpoint addresses after rollout. Verify service selectors and endpoint population.";
  }
  if (normalized === "service_endpoint_unhealthy") {
    return "Service endpoint health checks failed after rollout. Verify in-cluster service response and endpoint health.";
  }
  if (normalized === "in_cluster_service_curl_failed") {
    return "In-cluster curl to site-web service failed after rollout. Verify service routing and container HTTP response.";
  }
  if (normalized === "ingress_backend_unhealthy_after_rollout") {
    return "Ingress backend stayed unhealthy after rollout. Verify endpoints, BackendConfig health checks, and NEG backend state.";
  }
  if (normalized === "backend_config_healthcheck_unhealthy") {
    return "BackendConfig health checks are unhealthy for site-web. Verify request path/port and backend service health.";
  }
  if (normalized === "reachable_but_tls_certificate_mismatch") {
    return "Expected hostname is reachable, but TLS certificate is bound to another site. Verify managed certificate identity and ingress annotation alignment.";
  }
  if (normalized === "ingress_address_pending_but_hostname_reachable") {
    return "Expected hostname is reachable before ingress external address is populated. Continue monitoring ingress status and certificate activation.";
  }
  if (normalized === "draft_preview_auth_context_missing") {
    return "Draft preview route requires an authenticated operator session. Re-open preview from the migration workspace.";
  }
  if (normalized === "draft_preview_route_requires_operator_session") {
    return "Draft preview links that require operator session are blocked inside iframe preview. Use in-app preview navigation controls.";
  }
  if (normalized === "public_image_pull_failed") {
    return "Public image pull failed for site-web. Verify the image reference/tag exists and is readable in GHCR.";
  }
  if (normalized === "private_image_pull_forbidden") {
    return "Private image pull is forbidden. Verify control-plane GHCR credentials and namespace pull-secret provisioning. Target site repositories do not need image-pull secrets.";
  }
  if (normalized === "deployed_content_identity_mismatch") {
    return "Managed deployment image identity does not match this site target. Republish managed deploy files before redeploy so the site uses repo-specific generated content.";
  }
  return null;
}

function formatManagedSiteRolloutStateLabel(value: string | null): string {
  const normalized = (value || "").trim().toLowerCase();
  if (!normalized) {
    return "Not available";
  }
  if (normalized === "managed_workflow_not_yet_republished") {
    return "Managed workflow not yet republished";
  }
  if (normalized === "workflow_republished_but_deploy_not_rerun") {
    return "Workflow republished but deploy not rerun";
  }
  if (normalized === "deploy_running_old_generic_image") {
    return "Deploy running old generic image";
  }
  if (normalized === "deploy_running_expected_site_scoped_image") {
    return "Deploy running expected site-scoped image";
  }
  return normalized.replace(/_/g, " ");
}

function parseImageDigest(value: unknown): string | null {
  if (typeof value === "string") {
    const normalized = value.trim();
    return normalized.length > 0 ? normalized : null;
  }
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  const digestValue = (value as Record<string, unknown>).digest;
  if (typeof digestValue !== "string") {
    return null;
  }
  const normalized = digestValue.trim();
  return normalized.length > 0 ? normalized : null;
}

function extractDigestFromImageReference(value: string | null): string | null {
  if (!value) {
    return null;
  }
  const normalized = value.trim();
  if (!normalized) {
    return null;
  }
  const atIndex = normalized.indexOf("@");
  if (atIndex < 0 || atIndex + 1 >= normalized.length) {
    return null;
  }
  const digest = normalized.slice(atIndex + 1).trim();
  return digest.length > 0 ? digest : null;
}

function toRepositoryProvisioningGuidance(params: {
  repoEnsureOutcome: string | null;
  repositoryExists: boolean | null;
  repositoryAutoCreateEnabled: boolean | null;
  repositoryAutoCreateAvailable: boolean | null;
  repositoryEnsureFailureReasonCode: string | null;
  publishPreflightStatus: string | null;
  publishPreflightBlockerCode: string | null;
  publishPreflightWouldBootstrapBranch: boolean | null;
  publishPreflightWouldReconcileRepoBaseline: boolean | null;
  readmePresent: boolean | null;
  gitignorePresent: boolean | null;
  licensePresent: boolean | null;
}): string | null {
  const {
    repoEnsureOutcome,
    repositoryExists,
    repositoryAutoCreateEnabled,
    repositoryAutoCreateAvailable,
    repositoryEnsureFailureReasonCode,
    publishPreflightStatus,
    publishPreflightBlockerCode,
    publishPreflightWouldBootstrapBranch,
    publishPreflightWouldReconcileRepoBaseline,
    readmePresent,
    gitignorePresent,
    licensePresent,
  } = params;
  const normalizedPreflightBlocker = (publishPreflightBlockerCode || "").trim().toLowerCase();
  if (normalizedPreflightBlocker === "github_workflow_write_not_authorized") {
    return "GitHub runtime is not authorized to write deploy workflow files in the configured repository.";
  }
  if (normalizedPreflightBlocker === "github_contents_write_not_authorized") {
    return "GitHub runtime is not authorized to write repository contents for publish.";
  }
  if (normalizedPreflightBlocker === "github_repo_adoption_required") {
    return "This repository exists but is not marked as MBSRN-managed. Adopt it to allow managed publish updates.";
  }
  if (normalizedPreflightBlocker === "github_branch_not_found_or_uninitialized") {
    return "Target branch is missing or uninitialized and cannot be bootstrapped with current runtime permissions.";
  }
  if (normalizedPreflightBlocker === "github_repo_state_invalid_for_bootstrap") {
    return "Repository bootstrap could not be completed for the configured target branch.";
  }
  if (normalizedPreflightBlocker === "github_repo_management_marker_missing") {
    return "This repository exists but is not marked as MBSRN-managed. Adopt it to allow managed publish updates.";
  }
  if (normalizedPreflightBlocker === "github_repo_management_marker_mismatch") {
    return "This repository is marked as MBSRN-managed for a different business/site and cannot be reused.";
  }
  if (normalizedPreflightBlocker === "github_repo_management_marker_invalid") {
    return "Repository management marker (mbsrn.key) is invalid and must be corrected before publish.";
  }
  if (
    ((publishPreflightStatus || "").trim().toLowerCase() === "ready_with_actions"
      || (publishPreflightStatus || "").trim().toLowerCase() === "warning")
    && publishPreflightWouldBootstrapBranch === true
  ) {
    return "Target branch is missing and will be bootstrapped during live publish.";
  }
  if (
    ((publishPreflightStatus || "").trim().toLowerCase() === "ready_with_actions"
      || (publishPreflightStatus || "").trim().toLowerCase() === "warning")
    && publishPreflightWouldReconcileRepoBaseline === true
  ) {
    const missing: string[] = [];
    if (readmePresent === false) {
      missing.push("README.md");
    }
    if (gitignorePresent === false) {
      missing.push(".gitignore");
    }
    if (licensePresent === false) {
      missing.push("LICENSE");
    }
    const missingSummary = missing.length > 0 ? missing.join(", ") : "managed baseline files";
    return `Repository is MBSRN-managed and missing baseline files (${missingSummary}); live publish will reconcile missing files.`;
  }
  const normalizedOutcome = (repoEnsureOutcome || "").trim().toLowerCase();
  if (normalizedOutcome === "exists") {
    return "Target repository exists.";
  }
  if (normalizedOutcome === "created") {
    return "Target repository was created by the managed runtime token.";
  }
  if (normalizedOutcome === "would_create_on_publish") {
    return "Missing repository will be auto-created on live publish (admin policy enabled).";
  }
  if (normalizedOutcome === "skipped_policy_disabled") {
    return "Missing repository cannot be auto-created because admin policy is disabled.";
  }
  if (normalizedOutcome === "failed_not_authorized") {
    return "Runtime token is not authorized to create repositories under the configured owner.";
  }
  if (normalizedOutcome === "failed_invalid_name") {
    return "Repository name is invalid for auto-create.";
  }
  if (normalizedOutcome === "failed_owner_mismatch") {
    return "Repository owner is outside the admin-owned publish target.";
  }
  if (normalizedOutcome === "failed_conflict") {
    return "Repository create encountered a conflict; re-check repository state and retry.";
  }
  if (normalizedOutcome === "failed_runtime_unavailable") {
    return "Repository auto-create is temporarily unavailable.";
  }
  const normalizedFailureReason = (repositoryEnsureFailureReasonCode || "").trim().toLowerCase();
  if (normalizedFailureReason === "repo_auto_create_not_authorized") {
    return "Runtime token is not authorized to create repositories under the configured owner.";
  }
  if (repositoryExists === true) {
    return "Target repository exists.";
  }
  if (repositoryAutoCreateAvailable === true || (repositoryExists === false && repositoryAutoCreateEnabled === true)) {
    return "Missing repository will be auto-created on live publish (admin policy enabled).";
  }
  if (repositoryExists === false && repositoryAutoCreateEnabled === false) {
    return "Missing repository cannot be auto-created because admin policy is disabled.";
  }
  return null;
}

function parseStringNumberMap(value: unknown): Record<string, number> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return {};
  }
  const parsed: Record<string, number> = {};
  for (const [rawKey, rawValue] of Object.entries(value as Record<string, unknown>)) {
    const key = String(rawKey || "").trim();
    if (!key) {
      continue;
    }
    const numeric = typeof rawValue === "number" && Number.isFinite(rawValue) ? Math.max(0, Math.round(rawValue)) : null;
    if (numeric === null) {
      continue;
    }
    parsed[key] = numeric;
  }
  return parsed;
}

function formatParserRejectionReasonCounts(value: Record<string, number>): string {
  const entries = Object.entries(value).filter(([, count]) => count > 0);
  if (entries.length === 0) {
    return "None";
  }
  return entries
    .sort(([leftKey], [rightKey]) => leftKey.localeCompare(rightKey))
    .map(([key, count]) => `${key}: ${count}`)
    .join(", ");
}

function toDraftRetryLikelihoodGuidance(value: string | null): string | null {
  const normalized = (value || "").trim().toLowerCase();
  if (!normalized) {
    return null;
  }
  if (normalized === "likely_useful") {
    return "Retry is likely useful for this failure class.";
  }
  if (normalized === "conditionally_useful") {
    return "Retry may help, but review draft content quality and structure first.";
  }
  if (normalized === "unlikely_without_contract_fix") {
    return "Retry is unlikely to help without prompt/contract/parser alignment.";
  }
  return "Retry guidance is unknown for this failure class.";
}

function deriveDraftContractIssueFocus(params: {
  missingRequiredFiles: string[];
  densityFailuresByFile: string[];
  parserRejectionReasonCounts: Record<string, number>;
  normalizedItemCount: number | null;
  droppedItemCount: number | null;
}): string | null {
  const {
    missingRequiredFiles,
    densityFailuresByFile,
    parserRejectionReasonCounts,
    normalizedItemCount,
    droppedItemCount,
  } = params;
  const parserDrops = Object.values(parserRejectionReasonCounts).reduce((sum, count) => sum + count, 0);
  if (parserDrops > 0 && ((normalizedItemCount ?? 0) === 0 || (droppedItemCount ?? 0) > 0)) {
    return "Parser/path normalization rejected draft items before contract validation.";
  }
  if (missingRequiredFiles.length > 0) {
    return `Required artifact files are missing: ${missingRequiredFiles.join(", ")}.`;
  }
  if (densityFailuresByFile.length > 0) {
    return "Required files were detected, but content density is below the minimum threshold.";
  }
  return null;
}

function resolveSelectedArtifactVersionId(params: {
  currentId: string;
  artifactVersions: MigrationArtifactVersion[];
  workspaceSummary: MigrationWorkspaceSummary;
}): string {
  const { currentId, artifactVersions, workspaceSummary } = params;
  const validIds = new Set(artifactVersions.map((item) => item.id).filter(Boolean));
  if (validIds.size === 0) {
    return "";
  }
  const trimmedCurrent = currentId.trim();
  if (trimmedCurrent && validIds.has(trimmedCurrent)) {
    return trimmedCurrent;
  }
  const publishReadiness = asRecord(workspaceSummary.publish_readiness);
  const deployReadiness = asRecord(workspaceSummary.deploy_readiness);
  const artifactsById = new Map(artifactVersions.map((item) => [item.id, item]));
  const generatedCandidate = (workspaceSummary.workspace.latest_generated_artifact_version_id || "").trim();
  if (generatedCandidate && validIds.has(generatedCandidate)) {
    const generatedArtifact = artifactsById.get(generatedCandidate);
    if (generatedArtifact && generatedArtifact.approval_status !== "approved") {
      return generatedCandidate;
    }
  }
  const fallbackCandidates = [
    asStringOrNull(publishReadiness.approved_artifact_version_id),
    asStringOrNull(deployReadiness.approved_artifact_version_id),
    workspaceSummary.workspace.latest_approved_artifact_version_id,
    workspaceSummary.workspace.latest_generated_artifact_version_id,
    artifactVersions[0]?.id || null,
  ];
  for (const candidate of fallbackCandidates) {
    const candidateId = (candidate || "").trim();
    if (candidateId && validIds.has(candidateId)) {
      return candidateId;
    }
  }
  return artifactVersions[0]?.id || "";
}

function historyRecordIdentity(record: Record<string, unknown>): string {
  const traceId =
    asStringOrNull(record.deploy_trace_id)
    || asStringOrNull(record.publish_trace_id)
    || asStringOrNull(record.trace_id);
  if (traceId) {
    return `trace:${traceId}`;
  }
  const action = asStringOrNull(record.action) || "unknown";
  const artifactVersionId = asStringOrNull(record.artifact_version_id) || "unknown";
  const timestamp = asStringOrNull(record.timestamp) || "unknown";
  const status = asStringOrNull(record.status) || "unknown";
  const workflowIdentifier = asStringOrNull(record.workflow_identifier_used)
    || asStringOrNull(record.workflow_identifier)
    || asStringOrNull(record.workflow_id)
    || "none";
  return `${action}:${artifactVersionId}:${timestamp}:${status}:${workflowIdentifier}`;
}

function resolveSelectedHistoryRecord(
  history: Array<Record<string, unknown>>,
  selectedIdentity: string,
): Record<string, unknown> {
  if (history.length === 0) {
    return {};
  }
  const trimmedIdentity = selectedIdentity.trim();
  if (!trimmedIdentity) {
    return asRecord(history[history.length - 1]);
  }
  const selected = history.find((item) => historyRecordIdentity(asRecord(item)) === trimmedIdentity);
  if (selected) {
    return asRecord(selected);
  }
  return asRecord(history[history.length - 1]);
}

function parseDraftReadinessReason(value: unknown): DraftReadinessReason | null {
  const record = asRecord(value);
  const severityRaw = asString(record.severity).trim().toLowerCase();
  const severity = severityRaw === "blocking" ? "blocking" : severityRaw === "warning" ? "warning" : null;
  const message = asString(record.message).trim();
  if (!severity || !message) {
    return null;
  }
  return {
    code: asString(record.code).trim(),
    severity,
    message,
  };
}

function draftReadinessReasonMessageFromCode(code: string, severity: "warning" | "blocking"): string {
  const normalized = code.trim().toLowerCase();
  if (normalized === "source_site_ingest_required") {
    return "Run source ingest to capture baseline source-site context.";
  }
  if (normalized === "operator_requirements_required") {
    return "Add operator requirements before generating a draft.";
  }
  if (normalized === "provider_config_missing") {
    return "AI provider configuration is missing or invalid for migration draft generation.";
  }
  if (normalized === "audit_context_unavailable") {
    return "Audit context is not available; draft quality may be limited.";
  }
  if (normalized === "recommendations_context_unavailable") {
    return "Recommendation context is not available; draft quality may be limited.";
  }
  if (normalized === "competitors_context_unavailable") {
    return "Competitor context is not available; draft quality may be limited.";
  }
  if (normalized === "enriched_content_sparse") {
    return "Stored enriched supporting context is sparse; draft quality may be limited.";
  }
  if (normalized === "media_required_but_not_selected") {
    return "Operator requested real/existing media. Import/select source images or upload project photos before approval.";
  }
  if (normalized === "google_reconnect_required") {
    return "Google Search Console / Analytics reconnect is recommended to restore live Google signals.";
  }
  if (normalized === "google_integration_unavailable") {
    return "Google integration state is currently unavailable; retry shortly and reconnect if this persists.";
  }
  if (normalized === "draft_generation_context_unavailable") {
    return "Draft context is unavailable. Retry and contact support if this persists.";
  }
  if (normalized === "app_auth_required" || normalized === "session_expired") {
    return "App session is not valid. Sign back into MBSRN and retry.";
  }
  const label = normalized ? normalized.replace(/_/g, " ") : "unknown readiness state";
  return severity === "blocking"
    ? `Resolve blocking condition: ${label}.`
    : `Warning: ${label}.`;
}

function toDraftReadinessStatusLabel(value: DraftReadinessStatus): string {
  if (value === "ready") {
    return "Ready";
  }
  if (value === "ready_with_warnings") {
    return "Ready with warnings";
  }
  return "Not ready";
}

function parseDraftReadiness(
  contextSummary: Record<string, unknown>,
  draftReadinessPreflight: Record<string, unknown> | null,
): DraftReadinessEvaluation {
  const readinessRecord = asRecord(contextSummary.draft_generation_readiness);
  const readinessStatusRaw = asString(readinessRecord.status).trim().toLowerCase();
  const readinessStatus: DraftReadinessStatus | null =
    readinessStatusRaw === "ready" || readinessStatusRaw === "ready_with_warnings" || readinessStatusRaw === "not_ready"
      ? readinessStatusRaw
      : null;
  const readinessScoreRaw = readinessRecord.score;
  const readinessScore =
    typeof readinessScoreRaw === "number" && Number.isFinite(readinessScoreRaw)
      ? Math.max(0, Math.min(100, Math.round(readinessScoreRaw)))
      : null;
  const readinessHardBlockedRaw = readinessRecord.hard_blocked;
  const readinessHardBlocked = typeof readinessHardBlockedRaw === "boolean" ? readinessHardBlockedRaw : null;
  const readinessSummary = asString(readinessRecord.summary).trim();
  const readinessSignalsRaw = asRecord(readinessRecord.signals);
  const readinessReasonsRaw = Array.isArray(readinessRecord.reasons) ? readinessRecord.reasons : [];
  const readinessReasons = readinessReasonsRaw
    .map((reason) => parseDraftReadinessReason(reason))
    .filter((reason): reason is DraftReadinessReason => reason !== null);

  const preflightRecord = asRecord(draftReadinessPreflight);
  const preflightReady = typeof preflightRecord.ready === "boolean" ? preflightRecord.ready : null;
  const preflightBlockingCodes = asStringList(preflightRecord.blocking_reason_codes);
  const preflightWarningCodes = asStringList(preflightRecord.warning_reason_codes);
  const preflightOperatorAction = asString(preflightRecord.operator_action).trim();
  if (preflightReady !== null) {
    const preflightReasons: DraftReadinessReason[] = [
      ...preflightBlockingCodes.map((code) => ({
        code,
        severity: "blocking" as const,
        message: draftReadinessReasonMessageFromCode(code, "blocking"),
      })),
      ...preflightWarningCodes.map((code) => ({
        code,
        severity: "warning" as const,
        message: draftReadinessReasonMessageFromCode(code, "warning"),
      })),
    ];
    const preflightStatus: DraftReadinessStatus = preflightReady
      ? preflightWarningCodes.length > 0
        ? "ready_with_warnings"
        : "ready"
      : "not_ready";
    const signalMap: Record<string, boolean> = {};
    for (const [key, value] of Object.entries(readinessSignalsRaw)) {
      if (typeof value === "boolean") {
        signalMap[key] = value;
      }
    }
    const computedScore =
      preflightStatus === "ready" ? 100 : preflightStatus === "ready_with_warnings" ? 85 : 40;
    return {
      status: preflightStatus,
      score: readinessScore ?? computedScore,
      hardBlocked: !preflightReady,
      summary:
        preflightOperatorAction ||
        (preflightStatus === "ready"
          ? "Ready to generate draft."
          : preflightStatus === "ready_with_warnings"
            ? "Ready, but draft quality may be limited."
            : "Not ready yet - resolve blocking migration readiness issues."),
      reasons: preflightReasons,
      signals: signalMap,
    };
  }

  if (readinessStatus && readinessScore !== null && readinessHardBlocked !== null && readinessSummary) {
    const signalMap: Record<string, boolean> = {};
    for (const [key, value] of Object.entries(readinessSignalsRaw)) {
      if (typeof value === "boolean") {
        signalMap[key] = value;
      }
    }
    return {
      status: readinessStatus,
      score: readinessScore,
      hardBlocked: readinessHardBlocked,
      summary: readinessSummary,
      reasons: readinessReasons,
      signals: signalMap,
    };
  }

  const fallbackSignals = {
    source_site_ingested: Boolean(contextSummary.has_source_snapshot),
    operator_requirements_present: Boolean(contextSummary.has_operator_requirements),
    audit_available: Boolean(contextSummary.has_audit_summary),
    recommendations_available: Boolean(contextSummary.has_recommendation_summary),
    competitors_available: Boolean(contextSummary.has_competitor_summary),
  };
  const fallbackReasons: DraftReadinessReason[] = [];
  if (!fallbackSignals.source_site_ingested) {
    fallbackReasons.push({
      code: "source_site_ingest_required",
      severity: "blocking",
      message: "Run source ingest to capture baseline source-site context.",
    });
  }
  if (!fallbackSignals.operator_requirements_present) {
    fallbackReasons.push({
      code: "operator_requirements_required",
      severity: "blocking",
      message: "Add operator requirements before generating a draft.",
    });
  }
  if (!fallbackSignals.audit_available) {
    fallbackReasons.push({
      code: "audit_context_unavailable",
      severity: "warning",
      message: "Audit context is not available; draft quality may be limited.",
    });
  }
  if (!fallbackSignals.recommendations_available) {
    fallbackReasons.push({
      code: "recommendations_context_unavailable",
      severity: "warning",
      message: "Recommendation context is not available; draft quality may be limited.",
    });
  }
  if (!fallbackSignals.competitors_available) {
    fallbackReasons.push({
      code: "competitors_context_unavailable",
      severity: "warning",
      message: "Competitor context is not available; draft quality may be limited.",
    });
  }
  let fallbackScore = 0;
  if (fallbackSignals.source_site_ingested) {
    fallbackScore += 20;
  }
  if (fallbackSignals.operator_requirements_present) {
    fallbackScore += 35;
  }
  if (fallbackSignals.audit_available) {
    fallbackScore += 15;
  }
  if (fallbackSignals.recommendations_available) {
    fallbackScore += 15;
  }
  if (fallbackSignals.competitors_available) {
    fallbackScore += 10;
  }
  if (
    fallbackSignals.source_site_ingested &&
    fallbackSignals.operator_requirements_present &&
    fallbackSignals.audit_available &&
    fallbackSignals.recommendations_available &&
    fallbackSignals.competitors_available
  ) {
    fallbackScore += 5;
  }
  const fallbackHardBlocked = fallbackReasons.some((reason) => reason.severity === "blocking");
  const fallbackStatus: DraftReadinessStatus = fallbackHardBlocked
    ? "not_ready"
    : fallbackScore >= 80
      ? "ready"
      : "ready_with_warnings";
  const fallbackSummary =
    fallbackStatus === "ready"
      ? "Ready to generate draft."
      : fallbackStatus === "ready_with_warnings"
        ? "Ready, but draft quality may be limited."
        : "Not ready yet — add source ingest and operator requirements first.";

  return {
    status: fallbackStatus,
    score: Math.max(0, Math.min(100, fallbackScore)),
    hardBlocked: fallbackHardBlocked,
    summary: fallbackSummary,
    reasons: fallbackReasons,
    signals: fallbackSignals,
  };
}

function parseDraftProviderCompatibility(
  contextSummary: Record<string, unknown>,
  migrationDiagnostics: Record<string, unknown>,
): DraftProviderCompatibilityEvaluation {
  const compatibilityRecord = asRecord(contextSummary.draft_provider_compatibility);
  const supportedRaw = compatibilityRecord.supported;
  const reasonCodeRaw = asString(compatibilityRecord.reason_code).trim();
  const operatorMessageRaw = asString(compatibilityRecord.operator_message).trim();
  const retryableRaw = compatibilityRecord.retryable;

  const supportedFromDiagnostics = migrationDiagnostics.draft_provider_compatibility_supported;
  const reasonCodeFromDiagnostics = asString(migrationDiagnostics.draft_provider_compatibility_reason_code).trim();
  const messageFromDiagnostics = asString(migrationDiagnostics.draft_provider_compatibility_message).trim();
  const retryableFromDiagnostics = migrationDiagnostics.draft_provider_compatibility_retryable;

  const supported =
    typeof supportedRaw === "boolean"
      ? supportedRaw
      : typeof supportedFromDiagnostics === "boolean"
        ? supportedFromDiagnostics
        : true;
  const reasonCode =
    reasonCodeRaw ||
    reasonCodeFromDiagnostics ||
    (supported ? "supported" : "unknown_provider_capability");
  const operatorMessage =
    operatorMessageRaw ||
    messageFromDiagnostics ||
    (supported
      ? "AI configuration is compatible with migration draft generation."
      : "The current AI configuration does not support migration draft generation.");
  const retryable =
    typeof retryableRaw === "boolean"
      ? retryableRaw
      : typeof retryableFromDiagnostics === "boolean"
        ? retryableFromDiagnostics
        : false;

  return {
    supported,
    reasonCode,
    operatorMessage,
    retryable,
  };
}

function toDraftGenerationStateLabel(value: DraftGenerationStateStatus): string {
  if (value === "ready") {
    return "Ready";
  }
  if (value === "ready_with_warnings") {
    return "Ready with warnings";
  }
  if (value === "blocked_by_workspace") {
    return "Blocked by workspace";
  }
  if (value === "blocked_by_provider") {
    return "Blocked by provider";
  }
  if (value === "generation_failed") {
    return "Generation failed";
  }
  if (value === "generation_partial") {
    return "Partial draft";
  }
  return "Draft generated";
}

function draftGenerationStateBadgeClass(value: DraftGenerationStateStatus): string {
  if (value === "ready" || value === "generation_succeeded") {
    return "badge badge-success";
  }
  if (value === "ready_with_warnings" || value === "generation_partial") {
    return "badge badge-warn";
  }
  return "badge badge-error";
}

function parseDraftGenerationState(params: {
  contextSummary: Record<string, unknown>;
  draftReadiness: DraftReadinessEvaluation;
  draftProviderCompatibility: DraftProviderCompatibilityEvaluation;
  migrationDiagnostics: Record<string, unknown>;
}): DraftGenerationStateEvaluation {
  const { contextSummary, draftReadiness, draftProviderCompatibility, migrationDiagnostics } = params;
  const stateRecord = asRecord(contextSummary.draft_generation_state);
  const rawStatus = asString(stateRecord.status).trim().toLowerCase();
  const rawSummary = asString(stateRecord.summary).trim();
  if (
    (rawStatus === "ready" ||
      rawStatus === "ready_with_warnings" ||
      rawStatus === "blocked_by_workspace" ||
      rawStatus === "blocked_by_provider" ||
      rawStatus === "generation_failed" ||
      rawStatus === "generation_partial" ||
      rawStatus === "generation_succeeded") &&
    rawSummary
  ) {
    return {
      status: rawStatus,
      summary: rawSummary,
    };
  }

  if (draftReadiness.hardBlocked) {
    return {
      status: "blocked_by_workspace",
      summary: draftReadiness.summary || "Not ready yet - resolve blocking migration readiness issues.",
    };
  }
  if (!draftProviderCompatibility.supported) {
    return {
      status: "blocked_by_provider",
      summary:
        draftProviderCompatibility.operatorMessage ||
        "Blocked: current AI model/configuration is not compatible with migration draft generation.",
    };
  }

  const latestStatus = asString(migrationDiagnostics.last_draft_generation_status).trim().toLowerCase();
  const latestFailureMessage = asString(migrationDiagnostics.last_draft_failure_message).trim();
  if (latestStatus === "failed") {
    return {
      status: "generation_failed",
      summary: latestFailureMessage || "Draft generation failed.",
    };
  }
  if (latestStatus === "partial") {
    return {
      status: "generation_partial",
      summary: "Partial draft generated.",
    };
  }
  if (latestStatus === "completed") {
    return {
      status: "generation_succeeded",
      summary: "Draft generated successfully.",
    };
  }
  if (draftReadiness.status === "ready_with_warnings") {
    return {
      status: "ready_with_warnings",
      summary: draftReadiness.summary || "Ready, but draft quality may be limited.",
    };
  }
  return {
    status: "ready",
    summary: draftReadiness.summary || "Ready to generate draft.",
  };
}

function parseDraftAIExecutionSummary(
  contextSummary: Record<string, unknown>,
  migrationDiagnostics: Record<string, unknown>,
): DraftAIExecutionSummary {
  const aiExecutionRecord = asRecord(contextSummary.ai_execution);
  const modelRequested =
    asStringOrNull(aiExecutionRecord.model_requested) ||
    asStringOrNull(migrationDiagnostics.last_draft_failure_model_requested) ||
    asStringOrNull(migrationDiagnostics.draft_model_requested);
  const modelResolved =
    asStringOrNull(aiExecutionRecord.model_resolved) ||
    asStringOrNull(migrationDiagnostics.last_draft_failure_model_resolved) ||
    asStringOrNull(migrationDiagnostics.draft_model_resolved) ||
    asStringOrNull(migrationDiagnostics.draft_provider_compatibility_model_name);
  const modelUsed =
    asStringOrNull(aiExecutionRecord.model_used) ||
    asStringOrNull(migrationDiagnostics.last_draft_failure_model_used) ||
    asStringOrNull(migrationDiagnostics.draft_model_used) ||
    asStringOrNull(migrationDiagnostics.draft_provider_compatibility_model_name);
  const endpointPath =
    asStringOrNull(aiExecutionRecord.endpoint_path) ||
    asStringOrNull(migrationDiagnostics.last_draft_failure_endpoint_path) ||
    asStringOrNull(migrationDiagnostics.draft_provider_compatibility_endpoint_path);
  const requestBodyMode =
    asStringOrNull(aiExecutionRecord.request_body_mode) ||
    asStringOrNull(migrationDiagnostics.last_draft_failure_request_body_mode) ||
    asStringOrNull(migrationDiagnostics.draft_provider_compatibility_request_body_mode);
  const compatibilityDecision = asStringOrNull(aiExecutionRecord.compatibility_decision);
  const failureSource = asStringOrNull(aiExecutionRecord.failure_source);
  const requestContractStatus = asStringOrNull(aiExecutionRecord.request_contract_status);
  const providerExecutionStatus = asStringOrNull(aiExecutionRecord.provider_execution_status);
  const artifactStatus = asStringOrNull(aiExecutionRecord.artifact_status);
  const artifactResult = asStringOrNull(aiExecutionRecord.artifact_result);
  const durationMs =
    typeof aiExecutionRecord.duration_ms === "number" && Number.isFinite(aiExecutionRecord.duration_ms)
      ? Math.max(0, Math.round(aiExecutionRecord.duration_ms))
      : null;
  const timeoutFromExecution =
    typeof aiExecutionRecord.timeout_seconds === "number" && Number.isFinite(aiExecutionRecord.timeout_seconds)
      ? Math.max(1, Math.round(aiExecutionRecord.timeout_seconds))
      : null;
  const timeoutFromDiagnostics =
    typeof migrationDiagnostics.last_draft_failure_timeout_seconds === "number" &&
    Number.isFinite(migrationDiagnostics.last_draft_failure_timeout_seconds)
      ? Math.max(1, Math.round(migrationDiagnostics.last_draft_failure_timeout_seconds))
      : typeof migrationDiagnostics.draft_timeout_seconds === "number" &&
          Number.isFinite(migrationDiagnostics.draft_timeout_seconds)
        ? Math.max(1, Math.round(migrationDiagnostics.draft_timeout_seconds))
        : null;
  const timeoutSeconds = timeoutFromExecution ?? timeoutFromDiagnostics;
  const timeoutSourceRaw =
    asStringOrNull(aiExecutionRecord.timeout_source) ||
    asStringOrNull(migrationDiagnostics.last_draft_failure_timeout_source) ||
    asStringOrNull(migrationDiagnostics.draft_timeout_source);
  const timeoutSource = timeoutSourceRaw === "admin" || timeoutSourceRaw === "default" ? timeoutSourceRaw : null;
  const generationSafetyRecord = asRecord(aiExecutionRecord.generation_safety);
  const preflightMode = asStringOrNull(generationSafetyRecord.migration_preflight_mode);
  const maxFinalInputChars =
    typeof generationSafetyRecord.migration_max_final_input_chars === "number"
      ? Math.max(0, Math.round(generationSafetyRecord.migration_max_final_input_chars))
      : typeof generationSafetyRecord.max_final_input_chars === "number"
        ? Math.max(0, Math.round(generationSafetyRecord.max_final_input_chars))
        : null;
  const maxDifficultyScore =
    typeof generationSafetyRecord.migration_max_difficulty_score === "number"
      ? Math.max(0, Math.round(generationSafetyRecord.migration_max_difficulty_score))
      : typeof generationSafetyRecord.max_difficulty_score === "number"
        ? Math.max(0, Math.round(generationSafetyRecord.max_difficulty_score))
        : null;
  const compactFallbackAttempted =
    typeof generationSafetyRecord.compact_fallback_attempted === "boolean"
      ? generationSafetyRecord.compact_fallback_attempted
      : null;
  const budgetCapped =
    typeof generationSafetyRecord.budget_capped === "boolean" ? generationSafetyRecord.budget_capped : null;
  const preflightBlocked =
    typeof generationSafetyRecord.preflight_blocked === "boolean"
      ? generationSafetyRecord.preflight_blocked
      : null;
  const preflightBlockReason = asStringOrNull(generationSafetyRecord.preflight_block_reason);
  const preflightBlockedSetting = asStringOrNull(generationSafetyRecord.preflight_blocked_setting);
  const preflightBlockedSettingActual =
    typeof generationSafetyRecord.preflight_blocked_setting_actual === "number"
      ? Math.max(0, Math.round(generationSafetyRecord.preflight_blocked_setting_actual))
      : null;
  const preflightBlockedSettingCap =
    typeof generationSafetyRecord.preflight_blocked_setting_cap === "number"
      ? Math.max(0, Math.round(generationSafetyRecord.preflight_blocked_setting_cap))
      : null;
  const providerCallSkipped =
    typeof generationSafetyRecord.provider_call_skipped === "boolean"
      ? generationSafetyRecord.provider_call_skipped
      : null;
  return {
    modelRequested,
    modelResolved,
    modelUsed,
    endpointPath,
    requestBodyMode,
    compatibilityDecision,
    failureSource,
    requestContractStatus,
    providerExecutionStatus,
    artifactStatus,
    artifactResult,
    durationMs,
    timeoutSeconds,
    timeoutSource,
    preflightMode,
    maxFinalInputChars,
    maxDifficultyScore,
    compactFallbackAttempted,
    budgetCapped,
    preflightBlocked,
    preflightBlockReason,
    preflightBlockedSetting,
    preflightBlockedSettingActual,
    preflightBlockedSettingCap,
    providerCallSkipped,
  };
}

function toDraftFailureSourceLabel(
  value: string | null,
  options?: {
    providerCallSkipped?: boolean | null;
    preflightBlocked?: boolean | null;
  },
): string | null {
  const normalized = (value || "").trim().toLowerCase();
  const providerCallSkipped = options?.providerCallSkipped === true;
  const preflightBlocked = options?.preflightBlocked === true;
  if (
    (providerCallSkipped || preflightBlocked)
    && normalized !== "unknown"
    && normalized !== "local_preflight"
  ) {
    return "Provider call skipped before request";
  }
  if (normalized === "local_preflight") {
    return "Blocked before provider call";
  }
  if (normalized === "remote_provider") {
    return "AI provider rejected request";
  }
  if (normalized === "local_validation") {
    return "Rejected by local validation";
  }
  if (normalized === "unknown") {
    return "Unexpected execution failure";
  }
  return null;
}

function formatGenerationBlockedReason(params: {
  preflightBlocked: boolean | null;
  preflightBlockedSetting: string | null;
  preflightBlockedSettingActual: number | null;
  preflightBlockedSettingCap: number | null;
  preflightBlockReason: string | null;
  budgetOutcome: string | null;
  contextBudgetSizeChars: number | null;
  hint: string | null;
}): string | null {
  const {
    preflightBlocked,
    preflightBlockedSetting,
    preflightBlockedSettingActual,
    preflightBlockedSettingCap,
    preflightBlockReason,
    budgetOutcome,
    contextBudgetSizeChars,
    hint,
  } = params;
  const blocked = preflightBlocked === true || budgetOutcome === "precall_rejected";
  if (!blocked && hint !== "Input too large") {
    return null;
  }

  const normalizedSetting = (preflightBlockedSetting || "").trim().toLowerCase();
  const normalizedReason = (preflightBlockReason || "").trim().toLowerCase();
  const settingIncludes = (needle: string): boolean =>
    normalizedSetting === needle
    || normalizedSetting.startsWith(`${needle} `)
    || normalizedSetting.includes(`,${needle}`)
    || normalizedSetting.includes(`${needle},`);
  if (
    (settingIncludes("migration_max_final_input_chars") && settingIncludes("migration_max_difficulty_score"))
    || normalizedReason === "final_input_and_difficulty_exceeded"
  ) {
    if (typeof preflightBlockedSettingActual === "number" && typeof preflightBlockedSettingCap === "number") {
      return `final input chars ${preflightBlockedSettingActual.toLocaleString()} exceeded cap ${preflightBlockedSettingCap.toLocaleString()} and difficulty score exceeded configured cap`;
    }
    return "final input chars and difficulty score exceeded configured caps";
  }
  if (
    settingIncludes("migration_max_difficulty_score")
    || normalizedReason === "difficulty_score_exceeded"
  ) {
    if (typeof preflightBlockedSettingActual === "number" && typeof preflightBlockedSettingCap === "number") {
      return `difficulty score ${preflightBlockedSettingActual} exceeded cap ${preflightBlockedSettingCap}`;
    }
    if (typeof preflightBlockedSettingCap === "number") {
      return `difficulty score exceeded cap ${preflightBlockedSettingCap}`;
    }
    return "difficulty score exceeded the configured cap";
  }
  if (
    settingIncludes("migration_max_final_input_chars")
    || normalizedReason === "final_input_chars_exceeded"
  ) {
    if (typeof preflightBlockedSettingActual === "number" && typeof preflightBlockedSettingCap === "number") {
      return `final input chars ${preflightBlockedSettingActual.toLocaleString()} exceeded cap ${preflightBlockedSettingCap.toLocaleString()}`;
    }
    if (typeof preflightBlockedSettingCap === "number") {
      return `final input chars exceeded cap ${preflightBlockedSettingCap.toLocaleString()}`;
    }
    return "final input chars exceeded configured cap";
  }
  if (
    settingIncludes("migration_context_budget_chars")
    || normalizedReason === "context_budget_overflow"
  ) {
    if (typeof preflightBlockedSettingCap === "number") {
      return `context exceeded ${preflightBlockedSettingCap.toLocaleString()} char budget`;
    }
    if (typeof contextBudgetSizeChars === "number") {
      return `context exceeded ${contextBudgetSizeChars.toLocaleString()} char budget`;
    }
    return "context exceeded runtime request budget";
  }
  if (normalizedSetting === "trimming_pass_count" || normalizedReason === "trimming_pass_limit_exceeded") {
    if (typeof preflightBlockedSettingActual === "number" && typeof preflightBlockedSettingCap === "number") {
      return `trimming passes ${preflightBlockedSettingActual} exceeded cap ${preflightBlockedSettingCap}`;
    }
    return "trimming pass limit exceeded";
  }
  if (typeof contextBudgetSizeChars === "number") {
    return `context exceeded ${contextBudgetSizeChars.toLocaleString()} char budget`;
  }
  return "runtime preflight safety threshold was exceeded";
}

function toRequestContractStatusLabel(value: string | null): string | null {
  const normalized = (value || "").trim().toLowerCase();
  if (normalized === "accepted") {
    return "Accepted end-to-end";
  }
  if (normalized === "accepted_with_warnings") {
    return "Accepted with warnings";
  }
  if (normalized === "blocked") {
    return "Blocked before provider call";
  }
  if (normalized === "rejected") {
    return "Rejected";
  }
  return null;
}

function parseArtifactQualitySummary(artifact: MigrationArtifactVersion | null): ArtifactQualitySummary | null {
  if (!artifact) {
    return null;
  }
  const evaluation = asRecord(artifact.artifact_quality_evaluation ?? artifact.artifact_quality_evaluation_json);
  const qualityRaw = asString(evaluation.quality_status).trim().toLowerCase();
  const qualityStatus: ArtifactQualityStatus | null =
    qualityRaw === "high" || qualityRaw === "medium" || qualityRaw === "low" ? qualityRaw : null;
  if (!qualityStatus) {
    return null;
  }

  const operatorSummaryRaw = asString(evaluation.operator_summary).trim();
  const issuesRaw = Array.isArray(evaluation.issues) ? evaluation.issues : [];
  const issues: ArtifactQualityIssue[] = issuesRaw
    .map((item) => {
      const record = asRecord(item);
      const description = asString(record.description).trim();
      if (!description) {
        return null;
      }
      return {
        type: asString(record.type).trim(),
        description,
      };
    })
    .filter((item): item is ArtifactQualityIssue => item !== null);

  const operatorSummary =
    operatorSummaryRaw ||
    (qualityStatus === "high"
      ? "High quality draft: core sections and grounding signals are present."
      : qualityStatus === "medium"
        ? "Medium quality draft: review quality issues before approval."
        : "Low quality draft: resolve quality issues before approval.");

  return {
    qualityStatus,
    operatorSummary,
    issues,
  };
}

function artifactQualityStatusLabel(value: ArtifactQualityStatus): string {
  if (value === "high") {
    return "High";
  }
  if (value === "medium") {
    return "Medium";
  }
  return "Low";
}

function artifactQualityBadgeClass(value: ArtifactQualityStatus): string {
  if (value === "high") {
    return "badge badge-success";
  }
  if (value === "medium") {
    return "badge badge-warn";
  }
  return "badge badge-muted";
}

function toArtifactQualityIssueTypeLabel(value: string): string {
  const normalized = value.trim().toLowerCase();
  if (!normalized) {
    return "Issue";
  }
  if (normalized === "required_media_missing") {
    return "required media";
  }
  return normalized.replace(/_/g, " ");
}

function deriveMigrationNextAction(params: {
  draftReadiness: DraftReadinessEvaluation;
  draftProviderCompatibility: DraftProviderCompatibilityEvaluation;
  draftGenerationState: DraftGenerationStateEvaluation;
  selectedArtifact: MigrationArtifactVersion | null;
  artifactQualitySummary: ArtifactQualitySummary | null;
  canPublishSelectedArtifact: boolean;
  canDeploySelectedArtifact: boolean;
}): string {
  const {
    draftReadiness,
    draftProviderCompatibility,
    draftGenerationState,
    selectedArtifact,
    artifactQualitySummary,
    canPublishSelectedArtifact,
    canDeploySelectedArtifact,
  } = params;

  if (draftReadiness.hardBlocked) {
    return "Not ready yet — add source ingest and operator requirements first.";
  }
  if (!draftProviderCompatibility.supported) {
    return "Blocked: resolve AI provider compatibility before generating a draft.";
  }
  if (!selectedArtifact) {
    return "Generate a draft to continue.";
  }
  if (selectedArtifact.status === "partial") {
    return "Review partial draft output and regenerate if needed before approval.";
  }
  if (artifactQualitySummary?.qualityStatus === "low") {
    return "Review draft quality issues before approval.";
  }
  if (selectedArtifact.approval_status !== "approved") {
    return "Review draft quality before approval.";
  }
  if (canPublishSelectedArtifact) {
    return "Approved artifact ready for publish.";
  }
  if (selectedArtifact.publish_status === "published" && canDeploySelectedArtifact) {
    return "Published artifact ready for deploy request.";
  }
  if (selectedArtifact.publish_status === "published" && selectedArtifact.deploy_status !== "deploy_requested") {
    return "Publish completed. Deploy remains a separate explicit step.";
  }
  if (selectedArtifact.deploy_status === "deploy_requested") {
    return "Deploy request submitted. Monitor deploy history.";
  }
  if (draftGenerationState.status === "ready_with_warnings") {
    return "Ready to generate, but draft quality may be limited.";
  }
  return draftGenerationState.summary || "Review current migration state and continue with the next explicit action.";
}

interface ReusedContextEntry {
  available: boolean | null;
  source: string | null;
  timestamp: string | null;
  count: number | null;
}

type NormalizedDiagnosticStatus = "success" | "pending" | "blocked" | "failed" | "unknown";

interface AttemptHistoryGroup {
  key: string;
  label: string;
  count: number;
  latestTimestamp: string | null;
  nextAction: string | null;
}

interface DeployConsistencyGroupedCheck {
  key: string;
  label: string;
  status: DeployConsistencyGateStatus;
  reason: string | null;
}

interface DeployConsistencyGroupingResult {
  checks: DeployConsistencyGroupedCheck[];
  sharedWarnings: Array<{
    key: string;
    message: string;
    affectedChecks: string[];
  }>;
}

function parseReusedContextEntry(value: unknown): ReusedContextEntry {
  const record = asRecord(value);
  const available = typeof record.available === "boolean" ? record.available : null;
  const source = asStringOrNull(record.source);
  const timestamp = asStringOrNull(record.timestamp);
  const count = typeof record.count === "number" && Number.isFinite(record.count) ? Math.max(0, Math.floor(record.count)) : null;
  return {
    available,
    source,
    timestamp,
    count,
  };
}

function formatContextTimestamp(value: string | null): string | null {
  if (!value) {
    return null;
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return null;
  }
  return parsed.toLocaleString();
}

function resolveReusedContextLabel(params: {
  entry: ReusedContextEntry;
  legacyAvailable: boolean;
}): string {
  const available = params.entry.available === null ? params.legacyAvailable : params.entry.available;
  if (!available) {
    return "Not yet available";
  }
  const formattedTimestamp = formatContextTimestamp(params.entry.timestamp);
  if (formattedTimestamp) {
    return `Available (last run ${formattedTimestamp})`;
  }
  return "Available";
}

function resolveReusedContextStatus(params: {
  entry: ReusedContextEntry;
  legacyAvailable: boolean;
}): "Available" | "Missing" | "Stale" {
  const available = params.entry.available === null ? params.legacyAvailable : params.entry.available;
  if (!available) {
    return "Missing";
  }
  const source = (params.entry.source || "").trim().toLowerCase();
  if (source.includes("stale")) {
    return "Stale";
  }
  return "Available";
}

function formatAttemptTimestamp(value: string | null): string {
  return formatContextTimestamp(value) || "n/a";
}

function toTimestampEpoch(value: string | null): number {
  if (!value) {
    return 0;
  }
  const parsed = Date.parse(value);
  if (Number.isNaN(parsed)) {
    return 0;
  }
  return parsed;
}

function truncateSummaryText(value: string, maxLength = 180): string {
  const normalized = value.trim().replace(/\s+/g, " ");
  if (!normalized) {
    return "";
  }
  if (normalized.length <= maxLength) {
    return normalized;
  }
  return `${normalized.slice(0, Math.max(0, maxLength - 1)).trimEnd()}...`;
}

function summarizeDiagnosticReason(...values: Array<string | null | undefined>): string {
  for (const value of values) {
    const normalized = (value || "").trim();
    if (normalized) {
      return truncateSummaryText(normalized, 180);
    }
  }
  return "No blocking diagnostics recorded.";
}

function summarizeListWithLimit(values: string[], maxItems = 3, maxLength = 140): {
  summary: string;
  truncated: boolean;
  hiddenCount: number;
} {
  const normalized = values.map((item) => item.trim()).filter((item) => item.length > 0);
  if (normalized.length === 0) {
    return {
      summary: "none",
      truncated: false,
      hiddenCount: 0,
    };
  }
  const visible = normalized.slice(0, maxItems);
  let summary = visible.join(" | ");
  let truncated = normalized.length > maxItems;
  if (summary.length > maxLength) {
    summary = truncateSummaryText(summary, maxLength);
    truncated = true;
  }
  return {
    summary,
    truncated,
    hiddenCount: Math.max(0, normalized.length - maxItems),
  };
}

function normalizeDiagnosticStatus(value: string | null): NormalizedDiagnosticStatus {
  const normalized = (value || "").trim().toLowerCase();
  if (!normalized) {
    return "unknown";
  }
  if (
    normalized === "queued" ||
    normalized === "in_progress" ||
    normalized === "requested" ||
    normalized === "running" ||
    normalized === "pending" ||
    normalized === "provisioning"
  ) {
    return "pending";
  }
  if (
    normalized === "failed" ||
    normalized === "error" ||
    normalized === "failure" ||
    normalized.includes("failed")
  ) {
    return "failed";
  }
  if (
    normalized === "blocked" ||
    normalized === "not_ready" ||
    normalized === "invalid" ||
    normalized.includes("blocked")
  ) {
    return "blocked";
  }
  if (
    normalized === "completed" ||
    normalized === "succeeded" ||
    normalized === "success" ||
    normalized === "published" ||
    normalized === "deployed" ||
    normalized === "ready" ||
    normalized === "active"
  ) {
    return "success";
  }
  return "unknown";
}

function toDiagnosticStatusLabel(value: NormalizedDiagnosticStatus): string {
  if (value === "success") {
    return "Success";
  }
  if (value === "pending") {
    return "Pending";
  }
  if (value === "blocked") {
    return "Blocked";
  }
  if (value === "failed") {
    return "Failed";
  }
  return "Unknown";
}

function diagnosticStatusBadgeClass(value: NormalizedDiagnosticStatus): string {
  if (value === "success") {
    return "badge badge-success";
  }
  if (value === "pending") {
    return "badge badge-warn";
  }
  if (value === "blocked" || value === "failed") {
    return "badge badge-error";
  }
  return "badge badge-muted";
}

function groupAttemptHistory(
  history: Array<Record<string, unknown>>,
  mode: "publish" | "deploy",
): AttemptHistoryGroup[] {
  const grouped = new Map<string, AttemptHistoryGroup & { latestEpoch: number }>();
  for (const record of history) {
    const failureReason = asStringOrNull(record.failure_reason);
    const dispatchReason = asStringOrNull(record.dispatch_service_reason_code);
    const failureCategory = asStringOrNull(record.failure_category);
    const status = asStringOrNull(record.status);
    const reasonKey = (
      failureReason ||
      dispatchReason ||
      failureCategory ||
      status ||
      "unknown"
    ).trim().toLowerCase();
    if (!reasonKey) {
      continue;
    }
    const label = failureReason
      ? formatReasonCodeLabel(failureReason)
      : dispatchReason
        ? formatReasonCodeLabel(dispatchReason)
        : failureCategory
          ? toFailureCategoryLabel(failureCategory)
          : status
            ? status.replace(/_/g, " ")
            : "unknown";
    const nextAction = mode === "deploy"
      ? summarizeDiagnosticReason(
          toManagedGkeConfigGuidance(dispatchReason),
          asStringOrNull(record.post_conformance_remediation_message),
          asStringOrNull(record.workflow_run_failure_hint),
          asStringOrNull(record.failure_remediation_hint),
        )
      : summarizeDiagnosticReason(
          toWorkflowRemediationOutcomeGuidance(asStringOrNull(record.workflow_remediation_outcome)),
          asStringOrNull(record.failure_remediation_hint),
        );
    const timestamp = asStringOrNull(record.timestamp);
    const epoch = toTimestampEpoch(timestamp);
    const existing = grouped.get(reasonKey);
    if (!existing) {
      grouped.set(reasonKey, {
        key: reasonKey,
        label,
        count: 1,
        latestTimestamp: timestamp,
        nextAction,
        latestEpoch: epoch,
      });
      continue;
    }
    existing.count += 1;
    if (epoch >= existing.latestEpoch) {
      existing.latestEpoch = epoch;
      existing.latestTimestamp = timestamp;
      existing.nextAction = nextAction;
      existing.label = label;
    }
  }
  return Array.from(grouped.values())
    .sort((left, right) => {
      if (right.count !== left.count) {
        return right.count - left.count;
      }
      return right.latestEpoch - left.latestEpoch;
    })
    .map((item) => ({
      key: item.key,
      label: item.label,
      count: item.count,
      latestTimestamp: item.latestTimestamp,
      nextAction: item.nextAction,
    }));
}

function groupDeployConsistency(params: {
  deploymentRolloutStatus: DeployConsistencyGateStatus;
  serviceEndpointsStatus: DeployConsistencyGateStatus;
  backendHealthStatus: DeployConsistencyGateStatus;
  dnsStatus: DeployConsistencyGateStatus;
  managedCertificateStatus: DeployConsistencyGateStatus;
  httpsStatus: DeployConsistencyGateStatus;
  workflowIntegrityStatus: DeployConsistencyGateStatus;
  ingressPolicyStatus: DeployConsistencyGateStatus;
  tlsFailedNotVisible: boolean;
  tlsProvisioning: boolean;
  hasDnsMismatchReason: boolean;
  hasIngressConflictReason: boolean;
  workflowIntegrityReasonCode: string | null;
}): DeployConsistencyGroupingResult {
  const checks: DeployConsistencyGroupedCheck[] = [
    {
      key: "deployment_rollout",
      label: "Deployment rollout",
      status: params.deploymentRolloutStatus,
      reason:
        params.deploymentRolloutStatus === "blocked"
          ? "Rollout verification failed."
          : params.deploymentRolloutStatus === "pending"
            ? "Waiting for rollout/workflow convergence."
            : null,
    },
    {
      key: "service_endpoints",
      label: "Service endpoints",
      status: params.serviceEndpointsStatus,
      reason:
        params.serviceEndpointsStatus === "blocked"
          ? "Service endpoints are missing or unhealthy."
          : params.serviceEndpointsStatus === "pending"
            ? "Waiting for endpoint readiness."
            : null,
    },
    {
      key: "backend_health",
      label: "Backend health",
      status: params.backendHealthStatus,
      reason:
        params.backendHealthStatus === "blocked"
          ? "Ingress/backend health checks are failing."
          : params.backendHealthStatus === "pending"
            ? "Waiting for backend health convergence."
            : null,
    },
    {
      key: "dns_matches_ingress",
      label: "DNS",
      status: params.dnsStatus,
      reason:
        params.dnsStatus === "blocked"
          ? "DNS does not match ingress IP."
          : params.dnsStatus === "pending"
            ? "Waiting for DNS/ingress evidence."
            : null,
    },
    {
      key: "managed_certificate_active",
      label: "Managed certificate",
      status: params.managedCertificateStatus,
      reason:
        params.managedCertificateStatus === "blocked"
          ? params.tlsFailedNotVisible
            ? "Certificate is not visible to Google validation."
            : "Managed certificate is not active."
          : params.managedCertificateStatus === "pending" || params.tlsProvisioning
            ? "Certificate provisioning is in progress."
            : null,
    },
    {
      key: "https_probe",
      label: "HTTPS",
      status: params.httpsStatus,
      reason:
        params.httpsStatus === "blocked"
          ? params.tlsProvisioning
            ? "Waiting on TLS provisioning before HTTPS can pass."
            : "HTTPS verification has not passed."
          : params.httpsStatus === "pending"
            ? params.tlsProvisioning
              ? "Waiting on TLS provisioning before HTTPS can pass."
              : "Waiting for DNS/TLS/backend convergence."
            : null,
    },
    {
      key: "workflow_integrity",
      label: "Workflow integrity",
      status: params.workflowIntegrityStatus,
      reason:
        params.workflowIntegrityStatus === "warning"
          ? "Managed workflow signature differs from expected template."
          : params.workflowIntegrityStatus === "unknown"
            ? "Workflow integrity evidence is incomplete."
            : null,
    },
    {
      key: "ingress_conflict",
      label: "Static IP / ingress policy",
      status: params.ingressPolicyStatus,
      reason:
        params.ingressPolicyStatus === "blocked"
          ? "Ingress ownership/static IP policy conflict detected."
          : params.ingressPolicyStatus === "pending"
            ? "Waiting for ingress policy evidence."
            : null,
    },
  ];

  const sharedWarnings: DeployConsistencyGroupingResult["sharedWarnings"] = [];
  if (
    params.hasDnsMismatchReason &&
    (params.managedCertificateStatus === "blocked" || params.httpsStatus === "blocked")
  ) {
    sharedWarnings.push({
      key: "dns_tls_root_cause",
      message: "DNS mismatch is likely the root cause for certificate/HTTPS failures.",
      affectedChecks: ["DNS", "Managed certificate", "HTTPS"],
    });
  }
  if (params.tlsFailedNotVisible) {
    sharedWarnings.push({
      key: "tls_failed_not_visible",
      message: "Certificate visibility is still pending from external DNS evidence.",
      affectedChecks: ["Managed certificate", "HTTPS"],
    });
  }
  if (params.hasIngressConflictReason) {
    sharedWarnings.push({
      key: "ingress_conflict",
      message: "Ingress/static IP conflict can block DNS, TLS, and HTTPS verification.",
      affectedChecks: ["Static IP / ingress policy", "DNS", "HTTPS"],
    });
  }
  if (params.workflowIntegrityReasonCode === "managed_workflow_signature_mismatch") {
    sharedWarnings.push({
      key: "workflow_integrity_mismatch",
      message: "Workflow signature mismatch may cause non-standard deploy behavior.",
      affectedChecks: ["Workflow integrity"],
    });
  }

  return {
    checks,
    sharedWarnings,
  };
}

function derivePublishTreeUrl(
  repoOwner: string | null,
  repoName: string | null,
  branch: string | null,
  artifactRoot: string | null,
): string | null {
  const owner = (repoOwner || "").trim();
  const repo = (repoName || "").trim();
  const branchValue = (branch || "").trim();
  if (!owner || !repo || !branchValue) {
    return null;
  }
  const root = (artifactRoot || "").trim().replace(/^\/+|\/+$/g, "");
  const encodedBranch = encodeURIComponent(branchValue);
  return root
    ? `https://github.com/${owner}/${repo}/tree/${encodedBranch}/${root}`
    : `https://github.com/${owner}/${repo}/tree/${encodedBranch}`;
}

function extractHostnameFromUrl(value: string | null): string | null {
  if (!value) {
    return null;
  }
  try {
    const parsed = new URL(value);
    return parsed.hostname.toLowerCase();
  } catch {
    return null;
  }
}

function deriveDeployUrlFromInputs(inputs: Record<string, unknown>): { url: string | null; source: string | null } {
  const candidates = ["deploy_url", "public_url", "site_url", "url"];
  for (const key of candidates) {
    const value = asStringOrNull(inputs[key]);
    if (!value) {
      continue;
    }
    const normalized = value.trim();
    if (normalized.startsWith("https://") || normalized.startsWith("http://")) {
      return { url: normalized, source: `deploy_input:${key}` };
    }
  }
  const hostCandidates = ["host", "domain"];
  for (const key of hostCandidates) {
    const value = asStringOrNull(inputs[key]);
    if (!value) {
      continue;
    }
    const normalized = value.trim();
    if (!normalized || normalized.includes("/") || !normalized.includes(".")) {
      continue;
    }
    return { url: `https://${normalized}`, source: `deploy_input:${key}` };
  }
  return { url: null, source: null };
}

function deriveMigrationDestinationSummary(params: {
  contextSummary: Record<string, unknown>;
  publishTarget: Record<string, unknown>;
  deployTarget: Record<string, unknown>;
  effectivePublishRepoOwner: string | null;
  effectivePublishRepoName: string | null;
  effectivePublishBranch: string;
  effectivePublishArtifactRoot: string;
  currentSiteUrl: string | null;
}): MigrationDestinationSummaryEvaluation {
  const destinationSummary = asRecord(params.contextSummary.destination_summary);
  const draftPreview = asRecord(destinationSummary.draft_preview);
  const publishDestination = asRecord(destinationSummary.publish_destination);
  const deployDestination = asRecord(destinationSummary.deploy_destination);

  const publishRepository =
    asStringOrNull(publishDestination.repository) ||
    (params.effectivePublishRepoOwner && params.effectivePublishRepoName
      ? `${params.effectivePublishRepoOwner}/${params.effectivePublishRepoName}`
      : null);
  const publishBranch = asStringOrNull(publishDestination.branch) || params.effectivePublishBranch || null;
  const publishArtifactRoot =
    asStringOrNull(publishDestination.artifact_root) || params.effectivePublishArtifactRoot || null;
  const publishExpectedUrl =
    asStringOrNull(publishDestination.expected_url) ||
    derivePublishTreeUrl(
      params.effectivePublishRepoOwner,
      params.effectivePublishRepoName,
      params.effectivePublishBranch,
      params.effectivePublishArtifactRoot,
    );
  const fallbackDeployUrl = deriveDeployUrlFromInputs(asRecord(params.deployTarget.inputs));
  const publishExpectedPublishedUrl =
    asStringOrNull(publishDestination.expected_publish_url) ||
    asStringOrNull(deployDestination.expected_publish_url) ||
    fallbackDeployUrl.url;
  const publishUrlSource =
    asStringOrNull(publishDestination.url_source) || (fallbackDeployUrl.url ? "deterministic_target_config" : null);
  const publishUrlSourceDetail = asStringOrNull(publishDestination.url_source_detail) || fallbackDeployUrl.source;
  const publishExpectedLocation =
    asStringOrNull(publishDestination.expected_location) ||
    (publishRepository && publishBranch
      ? `${publishRepository}@${publishBranch}:${publishArtifactRoot || "/"}`
      : null);
  const deployExpectedPublishUrl =
    asStringOrNull(deployDestination.expected_publish_url) ||
    asStringOrNull(deployDestination.expected_url) ||
    publishExpectedPublishedUrl ||
    fallbackDeployUrl.url;
  const deployUrlSource =
    asStringOrNull(deployDestination.url_source) ||
    publishUrlSource ||
    (fallbackDeployUrl.url ? "deterministic_target_config" : null);
  const deployUrlSourceDetail = asStringOrNull(deployDestination.url_source_detail) || publishUrlSourceDetail || fallbackDeployUrl.source;
  const deployResolvedLiveCandidate =
    asStringOrNull(deployDestination.active_url) || asStringOrNull(deployDestination.resolved_live_url);
  const deployResolvedLiveUrl =
    deployUrlSource === "deploy_result" || deployUrlSource === "workflow_output" || deployUrlSource === "current_live_probe"
      ? deployResolvedLiveCandidate
      : asStringOrNull(deployDestination.active_url);
  const deployResolvedLiveHost = extractHostnameFromUrl(deployResolvedLiveUrl);
  const deployPreviewHostname = asStringOrNull(deployDestination.preview_hostname);
  const deployPreviewUrl =
    asStringOrNull(deployDestination.preview_url) ||
    (deployPreviewHostname ? `https://${deployPreviewHostname}` : null);
  const deployPreviewLiveUrl =
    deployResolvedLiveUrl && deployPreviewHostname && deployResolvedLiveHost === deployPreviewHostname.toLowerCase()
      ? deployResolvedLiveUrl
      : null;
  const deployPreviewState =
    asStringOrNull(deployDestination.preview_state) ||
    (deployPreviewLiveUrl ? "active_live" : deployPreviewUrl ? "expected_after_deploy" : "not_configured");
  const deployCustomerDomainUrl =
    asStringOrNull(deployDestination.customer_domain_url) || deployExpectedPublishUrl;
  const deployCustomerDomainHost = extractHostnameFromUrl(deployCustomerDomainUrl);
  const deployCustomerDomainLiveUrl =
    asStringOrNull(deployDestination.customer_domain_live_url) ||
    (deployResolvedLiveUrl && deployCustomerDomainHost && deployResolvedLiveHost === deployCustomerDomainHost
      ? deployResolvedLiveUrl
      : null);
  const deployCustomerDomainState =
    asStringOrNull(deployDestination.customer_domain_state) ||
    (deployCustomerDomainUrl
      ? deployCustomerDomainLiveUrl
        ? "active_live"
        : "pending_cutover"
      : "not_configured");
  const deployWorkflowMode =
    asStringOrNull(deployDestination.deploy_workflow_mode) ||
    asStringOrNull(params.deployTarget.deploy_workflow_mode);
  const deployTargetEnvironmentKey =
    asStringOrNull(deployDestination.target_environment_key) ||
    asStringOrNull(params.deployTarget.target_environment_key);
  const deployTargetEnvironmentSource =
    asStringOrNull(deployDestination.target_environment_source) ||
    asStringOrNull(params.deployTarget.target_environment_source);
  const deploySiteWorkflowFilePath =
    asStringOrNull(deployDestination.site_workflow_file_path) ||
    asStringOrNull(deployDestination.resolved_workflow_path) ||
    asStringOrNull(params.deployTarget.site_workflow_file_path) ||
    asStringOrNull(params.deployTarget.resolved_workflow_path);
  const deployKubernetesNamespace =
    asStringOrNull(deployDestination.kubernetes_namespace) ||
    asStringOrNull(params.deployTarget.kubernetes_namespace);
  const deployNamespaceSource =
    asStringOrNull(deployDestination.namespace_source) ||
    asStringOrNull(params.deployTarget.namespace_source);
  const deployNamespaceModelStatus =
    asStringOrNull(deployDestination.namespace_model_status) ||
    asStringOrNull(params.deployTarget.namespace_model_status);
  const deployWorkflowNamespaceAligned =
    asBooleanOrNull(deployDestination.workflow_namespace_aligned) ??
    asBooleanOrNull(params.deployTarget.workflow_namespace_aligned);
  const deployManifestNamespaceAligned =
    asBooleanOrNull(deployDestination.manifest_namespace_aligned) ??
    asBooleanOrNull(params.deployTarget.manifest_namespace_aligned);
  const managedResourceQuotaExpected =
    asBooleanOrNull(deployDestination.managed_resource_quota_expected) ??
    asBooleanOrNull(params.deployTarget.managed_resource_quota_expected);
  const managedResourceQuotaPresent =
    asBooleanOrNull(deployDestination.managed_resource_quota_present) ??
    asBooleanOrNull(params.deployTarget.managed_resource_quota_present);
  const managedLimitRangeExpected =
    asBooleanOrNull(deployDestination.managed_limit_range_expected) ??
    asBooleanOrNull(params.deployTarget.managed_limit_range_expected);
  const managedLimitRangePresent =
    asBooleanOrNull(deployDestination.managed_limit_range_present) ??
    asBooleanOrNull(params.deployTarget.managed_limit_range_present);
  const managedNetworkPolicyExpected =
    asBooleanOrNull(deployDestination.managed_network_policy_expected) ??
    asBooleanOrNull(params.deployTarget.managed_network_policy_expected);
  const managedNetworkPolicyPresent =
    asBooleanOrNull(deployDestination.managed_network_policy_present) ??
    asBooleanOrNull(params.deployTarget.managed_network_policy_present);
  const managedNamespacePoliciesAligned =
    asBooleanOrNull(deployDestination.managed_namespace_policies_aligned) ??
    asBooleanOrNull(params.deployTarget.managed_namespace_policies_aligned);

  return {
    draftPreviewState: asStringOrNull(draftPreview.state) || "unavailable",
    draftPreviewEntryPath: asStringOrNull(draftPreview.entry_path),
    publishRepository,
    publishBranch,
    publishArtifactRoot,
    publishExpectedLocation,
    publishRepositoryUrl: publishExpectedUrl,
    publishExpectedPublishedUrl,
    publishState: asStringOrNull(publishDestination.state) || (publishRepository ? "configured" : "unknown"),
    publishUrlSource,
    publishUrlSourceDetail,
    deployExpectedPublishUrl,
    deployResolvedLiveUrl,
    deployPreviewHostname,
    deployPreviewUrl: deployPreviewLiveUrl || deployPreviewUrl,
    deployPreviewState,
    deployCustomerDomainUrl,
    deployCustomerDomainLiveUrl,
    deployCustomerDomainState,
    deployState: asStringOrNull(deployDestination.state) || (deployExpectedPublishUrl ? "expected_after_deploy" : "unknown"),
    deployUrlSource,
    deployUrlSourceDetail,
    deployWorkflowMode,
    deployTargetEnvironmentKey,
    deployTargetEnvironmentSource,
    deploySiteWorkflowFilePath,
    deployKubernetesNamespace,
    deployNamespaceSource,
    deployNamespaceModelStatus,
    deployWorkflowNamespaceAligned,
    deployManifestNamespaceAligned,
    managedResourceQuotaExpected,
    managedResourceQuotaPresent,
    managedLimitRangeExpected,
    managedLimitRangePresent,
    managedNetworkPolicyExpected,
    managedNetworkPolicyPresent,
    managedNamespacePoliciesAligned,
    currentSiteUrl: asStringOrNull(destinationSummary.current_site_url) || params.currentSiteUrl,
  };
}

function normalizeArtifactPathForPreview(path: string): string {
  return path.replace(/\\/g, "/").replace(/^\/+/, "").trim();
}

function buildArtifactPreviewFileUrl(
  businessId: string,
  siteId: string,
  artifactVersionId: string,
  path: string,
): string | null {
  const normalizedPath = normalizeArtifactPathForPreview(path);
  if (!normalizedPath) {
    return null;
  }
  const encodedPath = normalizedPath
    .split("/")
    .map((segment) => encodeURIComponent(segment))
    .join("/");
  return `/api/businesses/${encodeURIComponent(businessId)}/seo/sites/${encodeURIComponent(
    siteId,
  )}/migration/artifact-versions/${encodeURIComponent(artifactVersionId)}/files/${encodedPath}`;
}

function resolveArtifactRelativePath(entryPath: string, href: string): string | null {
  const normalizedHref = href.trim();
  if (!normalizedHref || normalizedHref.startsWith("#")) {
    return null;
  }
  if (
    normalizedHref.startsWith("http://") ||
    normalizedHref.startsWith("https://") ||
    normalizedHref.startsWith("data:")
  ) {
    return null;
  }
  const cleanedHref = normalizedHref.split("?")[0]?.split("#")[0] || "";
  if (!cleanedHref) {
    return null;
  }
  if (cleanedHref.startsWith("/")) {
    return normalizeArtifactPathForPreview(cleanedHref);
  }
  const baseDir = entryPath.includes("/") ? entryPath.slice(0, entryPath.lastIndexOf("/") + 1) : "";
  try {
    const resolved = new URL(cleanedHref, `https://preview.local/${baseDir}`);
    return normalizeArtifactPathForPreview(resolved.pathname);
  } catch {
    return null;
  }
}

function extractPreviewPageTitle(path: string, html: string): string {
  const titleMatch = html.match(/<title[^>]*>([\s\S]*?)<\/title>/i);
  if (titleMatch && titleMatch[1]) {
    const normalized = titleMatch[1].replace(/\s+/g, " ").trim();
    if (normalized) {
      return normalized;
    }
  }
  return path;
}

function buildDraftPreviewEvaluation(
  artifact: MigrationArtifactVersion | null,
  options: { businessId: string; siteId: string },
): DraftPreviewEvaluation {
  if (!artifact || !Array.isArray(artifact.generated_files_json)) {
    return {
      available: false,
      entryPath: null,
      pages: [],
      reason: "Select an artifact version with generated files to preview.",
    };
  }
  const normalizedFiles = artifact.generated_files_json
    .map((item) => asRecord(item))
    .map((item) => ({
      path: normalizeArtifactPathForPreview(asString(item.path)),
      content: asStringOrNull(item.content),
      mediaType: asString(item.media_type).trim().toLowerCase(),
    }))
    .filter((item) => item.path.length > 0);
  const htmlFiles = normalizedFiles.filter((item) => item.path.endsWith(".html") && Boolean(item.content));
  if (htmlFiles.length === 0) {
    return {
      available: false,
      entryPath: null,
      pages: [],
      reason: "Selected artifact does not contain previewable HTML.",
    };
  }

  const fileMap = new Map<string, { content: string | null; mediaType: string }>();
  normalizedFiles.forEach((item) => {
    fileMap.set(item.path, {
      content: item.content,
      mediaType: item.mediaType,
    });
  });

  const entry = htmlFiles.find((item) => item.path.toLowerCase() === "index.html") || htmlFiles[0];
  const cssContentByPath = new Map<string, string>();
  normalizedFiles.forEach((item) => {
    if (item.path.endsWith(".css") && item.content) {
      cssContentByPath.set(item.path, item.content);
    }
  });
  const linkStylesheetRegex =
    /<link\b(?=[^>]*\brel=["'][^"']*stylesheet[^"']*["'])(?=[^>]*\bhref=["'][^"']+["'])[^>]*\bhref=["']([^"']+)["'][^>]*>/gi;
  const imageSrcRegex = /(<(?:img|source)\b[^>]*?\bsrc=)(["'])([^"']+)(\2)/gi;

  const buildPreviewHtmlForPage = (path: string, content: string): string => {
    let html = content.replace(linkStylesheetRegex, (full, hrefValue: string) => {
      const resolvedPath = resolveArtifactRelativePath(path, hrefValue);
      if (!resolvedPath) {
        return full;
      }
      const cssContent = cssContentByPath.get(resolvedPath);
      if (!cssContent) {
        return full;
      }
      return `<style data-preview-inline-source="${resolvedPath}">\n${cssContent}\n</style>`;
    });
    html = html.replace(
      imageSrcRegex,
      (full, prefix: string, quoteChar: string, srcValue: string) => {
        const resolvedPath = resolveArtifactRelativePath(path, srcValue);
        if (!resolvedPath) {
          return full;
        }
        const resolvedEntry = fileMap.get(resolvedPath);
        if (!resolvedEntry) {
          return full;
        }
        const isImageAsset =
          resolvedEntry.mediaType.startsWith("image/")
          || resolvedPath.endsWith(".png")
          || resolvedPath.endsWith(".jpg")
          || resolvedPath.endsWith(".jpeg")
          || resolvedPath.endsWith(".webp")
          || resolvedPath.endsWith(".gif");
        if (!isImageAsset) {
          return full;
        }
        const assetUrl = buildArtifactPreviewFileUrl(
          options.businessId,
          options.siteId,
          artifact.id,
          resolvedPath,
        );
        if (!assetUrl) {
          return full;
        }
        return `${prefix}${quoteChar}${assetUrl}${quoteChar}`;
      },
    );
    html = html.replace(
      /<a\b([^>]*)\bhref=["']([^"']+)["']([^>]*)>/gi,
      (full, prefix: string, hrefValue: string, suffix: string) => {
        const trimmedHref = hrefValue.trim().toLowerCase();
        if (!trimmedHref || trimmedHref.startsWith("#")) {
          return full;
        }
        const resolvedPath = resolveArtifactRelativePath(path, hrefValue);
        if (resolvedPath && resolvedPath.endsWith(".html") && fileMap.has(resolvedPath)) {
          return `<a${prefix}href="#draft-preview-page=${encodeURIComponent(resolvedPath)}"${suffix}>`;
        }
        return `<a${prefix}href="#" data-preview-link-blocked="true"${suffix}>`;
      },
    );
    const previewBanner =
      '<div style="position:sticky;top:0;z-index:2147483646;padding:10px 14px;border-bottom:1px solid #d6e4ff;background:#eef4ff;color:#12316b;font:600 12px/1.4 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;">Draft preview only. Not published. Not deployed. Use page selector above to navigate this draft site. External/app-auth links are blocked in preview.</div>';
    if (/<body[^>]*>/i.test(html)) {
      html = html.replace(/<body([^>]*)>/i, `<body$1>${previewBanner}`);
    } else {
      html = `${previewBanner}${html}`;
    }
    return html;
  };

  const pages = [...htmlFiles]
    .sort((left, right) => left.path.localeCompare(right.path))
    .map((page) => ({
      path: page.path,
      html: buildPreviewHtmlForPage(page.path, page.content || ""),
      title: extractPreviewPageTitle(page.path, page.content || ""),
    }));

  return {
    available: true,
    entryPath: entry.path,
    pages,
    reason: null,
  };
}

function toDestinationStateLabel(value: string): string {
  const normalized = value.trim().toLowerCase();
  if (normalized === "configured") {
    return "Configured";
  }
  if (normalized === "active_live") {
    return "Confirmed Live";
  }
  if (normalized === "expected_after_deploy") {
    return "Expected after deploy";
  }
  if (normalized === "available") {
    return "Available";
  }
  if (normalized === "unavailable") {
    return "Unavailable";
  }
  if (!normalized) {
    return "Unknown";
  }
  return normalized.replace(/_/g, " ");
}

function normalizeRequirementSuggestionText(value: string | string[] | null | undefined): string {
  if (Array.isArray(value)) {
    return joinLines(asStringList(value));
  }
  return asString(value);
}

function toRequirementSuggestionStatusLabel(value: RequirementSuggestionStatus): string {
  if (value === "completed") {
    return "Completed";
  }
  if (value === "failed") {
    return "Failed";
  }
  if (value === "not_available") {
    return "Not available";
  }
  if (value === "loading") {
    return "Generating...";
  }
  return "Idle";
}

function toRequirementSuggestionReasonLabel(value: string | null): string {
  const normalized = (value || "").trim().toLowerCase();
  if (!normalized) {
    return "";
  }
  if (normalized === "requirements_suggestion_context_unavailable") {
    return "Context for suggestion is currently unavailable.";
  }
  if (normalized === "requirements_suggestion_provider_unavailable") {
    return "AI provider is currently unavailable for requirement suggestions.";
  }
  if (normalized === "requirements_suggestion_provider_invalid") {
    return "AI provider returned an invalid suggestion response.";
  }
  if (normalized === "requirements_suggestion_field_unsupported") {
    return "This requirement field is not supported for suggestions.";
  }
  if (normalized === "requirements_suggestion_budget_rejected") {
    return "Suggestion request exceeded current budget limits.";
  }
  if (normalized === "requirements_suggestion_not_available") {
    return "Suggestion is not available for this field right now.";
  }
  if (normalized === "requirements_suggestion_completed") {
    return "Suggestion generated.";
  }
  return normalized.replace(/_/g, " ");
}

export function MigrationWorkspacePanel({
  token,
  businessId,
  siteId,
}: MigrationWorkspacePanelProps): JSX.Element {
  const [busyAction, setBusyAction] = useState<BusyAction>("load");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [errorHint, setErrorHint] = useState<string | null>(null);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);

  const [summary, setSummary] = useState<MigrationWorkspaceSummary | null>(null);
  const [artifactVersions, setArtifactVersions] = useState<MigrationArtifactVersion[]>([]);
  const [publishHistory, setPublishHistory] = useState<Array<Record<string, unknown>>>([]);
  const [deployHistory, setDeployHistory] = useState<Array<Record<string, unknown>>>([]);
  const [publishHistoryLoaded, setPublishHistoryLoaded] = useState(false);
  const [deployHistoryLoaded, setDeployHistoryLoaded] = useState(false);

  const [sourceUrl, setSourceUrl] = useState("");
  const [businessObjectives, setBusinessObjectives] = useState("");
  const [requestedPages, setRequestedPages] = useState("");
  const [mustInclude, setMustInclude] = useState("");
  const [mustAvoid, setMustAvoid] = useState("");
  const [tonePreferences, setTonePreferences] = useState("");
  const [callsToAction, setCallsToAction] = useState("");
  const [requirementsNotes, setRequirementsNotes] = useState("");
  const [requirementSuggestions, setRequirementSuggestions] = useState<
    Record<MigrationRequirementSuggestionField, RequirementSuggestionState>
  >(createDefaultRequirementSuggestionMap());

  const [mediaUploadFiles, setMediaUploadFiles] = useState<File[]>([]);
  const [mediaUploadCategory, setMediaUploadCategory] = useState("other");
  const [mediaUploadAltText, setMediaUploadAltText] = useState("");
  const [mediaUploadDescription, setMediaUploadDescription] = useState("");
  const [mediaUploadUsageNote, setMediaUploadUsageNote] = useState("");
  const [mediaUploadPageAssignment, setMediaUploadPageAssignment] = useState("");
  const [mediaUploadSelectedForDraft, setMediaUploadSelectedForDraft] = useState(true);
  const [mediaAssetsSnapshot, setMediaAssetsSnapshot] = useState<Record<string, unknown> | null>(null);
  const [mediaImportBatchSnapshot, setMediaImportBatchSnapshot] = useState<Record<string, unknown> | null>(null);
  const [mediaSuggestionBatchSnapshot, setMediaSuggestionBatchSnapshot] = useState<Record<string, unknown> | null>(
    null,
  );
  const [draftReadinessSnapshot, setDraftReadinessSnapshot] = useState<Record<string, unknown> | null>(null);
  const [checkedMediaAssetIds, setCheckedMediaAssetIds] = useState<string[]>([]);
  const [mediaBrowserFilter, setMediaBrowserFilter] = useState<MediaBrowserFilter>("all_usable");

  const [publishRepoName, setPublishRepoName] = useState("");
  const [publishBranch, setPublishBranch] = useState("");

  const [deployEnabled, setDeployEnabled] = useState(false);

  const [selectedArtifactVersionId, setSelectedArtifactVersionId] = useState("");
  const approvalNotes = "";
  const [publishDryRun, setPublishDryRun] = useState(true);
  const [publishCommitMessage, setPublishCommitMessage] = useState("");
  const [publishAnalyticsOverride, setPublishAnalyticsOverride] = useState("");
  const [deployDryRun, setDeployDryRun] = useState(true);

  const [selectedFilePath, setSelectedFilePath] = useState("");
  const [draftPreviewOpen, setDraftPreviewOpen] = useState(false);
  const [selectedPublishHistoryIdentity, setSelectedPublishHistoryIdentity] = useState("");
  const [selectedDeployHistoryIdentity, setSelectedDeployHistoryIdentity] = useState("");
  const draftPreviewFrameRef = useRef<HTMLIFrameElement | null>(null);

  const selectedArtifact = useMemo(() => {
    if (!selectedArtifactVersionId) {
      return null;
    }
    return artifactVersions.find((item) => item.id === selectedArtifactVersionId) || null;
  }, [artifactVersions, selectedArtifactVersionId]);

  const workspaceRecord = asRecord(summary?.workspace);
  const workspaceSiteName =
    asStringOrNull(workspaceRecord.site_display_name) ||
    asStringOrNull(workspaceRecord.site_name) ||
    asStringOrNull(workspaceRecord.site_id) ||
    siteId;
  const sourceSnapshot = summary?.source_snapshot || null;
  const publishReadiness = asRecord(summary?.publish_readiness || {});
  const deployReadiness = asRecord(summary?.deploy_readiness || {});
  const workspacePublishConfig = asRecord(workspaceRecord.publish_config_json || {});
  const selectedArtifactVersionIdTrimmed = selectedArtifactVersionId.trim();
  const publishReadinessArtifactVersionId = asString(publishReadiness.approved_artifact_version_id);
  const deployReadinessArtifactVersionId = asString(deployReadiness.approved_artifact_version_id);
  const isActionInFlight = busyAction !== null;
  const canApproveSelectedArtifact =
    selectedArtifactVersionIdTrimmed.length > 0 &&
    selectedArtifact !== null &&
    selectedArtifact.approval_status !== "approved";
  const canPublishSelectedArtifact =
    selectedArtifactVersionIdTrimmed.length > 0 &&
    selectedArtifact !== null &&
    Boolean(publishReadiness.ready) &&
    (!publishReadinessArtifactVersionId || publishReadinessArtifactVersionId === selectedArtifactVersionIdTrimmed);
  const canDeploySelectedArtifact =
    selectedArtifactVersionIdTrimmed.length > 0 &&
    selectedArtifact !== null &&
    Boolean(deployReadiness.ready) &&
    (!deployReadinessArtifactVersionId || deployReadinessArtifactVersionId === selectedArtifactVersionIdTrimmed);
  const selectedArtifactReferencedByPublishHistory =
    selectedArtifactVersionIdTrimmed.length > 0
      ? publishHistory.some((item) => asString(asRecord(item).artifact_version_id).trim() === selectedArtifactVersionIdTrimmed)
      : false;
  const selectedArtifactReferencedByDeployHistory =
    selectedArtifactVersionIdTrimmed.length > 0
      ? deployHistory.some((item) => asString(asRecord(item).artifact_version_id).trim() === selectedArtifactVersionIdTrimmed)
      : false;
  const selectedArtifactDeleteBlockedReason = (() => {
    if (!selectedArtifact) {
      return "Select an artifact version to delete.";
    }
    if (selectedArtifact.publish_status === "published") {
      return "Published artifacts cannot be deleted.";
    }
    if (summary?.workspace.last_published_artifact_version_id === selectedArtifact.id) {
      return "Artifacts referenced by publish history cannot be deleted.";
    }
    if (summary?.workspace.last_deployed_artifact_version_id === selectedArtifact.id) {
      return "Artifacts referenced by deploy history cannot be deleted.";
    }
    if (selectedArtifactReferencedByPublishHistory) {
      return "Artifacts referenced by publish history cannot be deleted.";
    }
    if (selectedArtifactReferencedByDeployHistory) {
      return "Artifacts referenced by deploy history cannot be deleted.";
    }
    return null;
  })();
  const canDeleteSelectedArtifact = Boolean(selectedArtifact && !selectedArtifactDeleteBlockedReason);
  const publishConfigPrerequisites = asRecord(publishReadiness.config_prerequisites);
  const deployConfigPrerequisites = asRecord(deployReadiness.config_prerequisites);
  const deployBlockerCodes = parseBlockerCodes(deployReadiness.blocker_codes);
  const publishTarget = asRecord(publishReadiness.target);
  const deployTarget = asRecord(deployReadiness.target);
  const effectivePublishRepoOwner = asStringOrNull(publishTarget.repo_owner);
  const effectivePublishRepoName = asStringOrNull(publishTarget.repo_name);
  const effectivePublishRepository =
    effectivePublishRepoOwner && effectivePublishRepoName
      ? `${effectivePublishRepoOwner}/${effectivePublishRepoName}`
      : null;
  const effectivePublishBranch = asStringOrNull(publishTarget.branch) || "main";
  const effectivePublishArtifactRoot = asStringOrNull(publishTarget.artifact_root) || "/";
  const adminPublishConfigured = Boolean(publishConfigPrerequisites.admin_publish_configured);
  const adminPublishEnabled = Boolean(publishConfigPrerequisites.admin_publish_config_enabled);
  const adminPublishReadyLabel = !adminPublishConfigured
    ? "Admin publish target not configured."
    : !adminPublishEnabled
      ? "Admin has disabled GitHub publishing."
      : "Admin publish target is configured and enabled.";
  const publishFailureCategory = asString(publishReadiness.last_failure_category || publishReadiness.failure_category) || null;
  const publishFailureMessage = asString(publishReadiness.last_failure_message) || null;
  const deployFailureMessage = asString(deployReadiness.last_failure_message) || null;
  const publishRuntimeStatusLabel = toRuntimeConfigLabel(publishConfigPrerequisites);
  const deployRuntimeStatusLabel = toRuntimeConfigLabel(deployConfigPrerequisites);
  const publishRuntimeStatusMessage = asStringOrNull(publishConfigPrerequisites.github_publisher_status_message);
  const deployRuntimeStatusMessage = asStringOrNull(deployConfigPrerequisites.github_publisher_status_message);
  const publishRepositoryExists =
    asBooleanOrNull(publishTarget.repository_exists)
    ?? asBooleanOrNull(publishConfigPrerequisites.publish_target_repo_exists);
  const publishRepositoryAutoCreateEnabled =
    asBooleanOrNull(publishTarget.repository_auto_create_enabled)
    ?? asBooleanOrNull(publishConfigPrerequisites.github_repository_auto_create_enabled);
  const publishRepositoryAutoCreateAvailable =
    asBooleanOrNull(publishTarget.repository_auto_create_available)
    ?? asBooleanOrNull(publishConfigPrerequisites.publish_target_repo_auto_create_available);
  const publishRepositoryEnsureFailureReasonCode = asStringOrNull(publishTarget.repository_ensure_failure_reason_code);
  const publishPreflightStatus = asStringOrNull(publishTarget.preflight_status);
  const publishPreflightBlockerCode = asStringOrNull(publishTarget.preflight_blocker_code);
  const publishPreflightWouldBootstrapBranch = asBooleanOrNull(publishTarget.would_bootstrap_branch);
  const publishPreflightWouldReconcileRepoBaseline = asBooleanOrNull(
    publishTarget.repo_baseline_reconciliation_needed,
  );
  const publishReadmePresent = asBooleanOrNull(publishTarget.readme_present);
  const publishGitignorePresent = asBooleanOrNull(publishTarget.gitignore_present);
  const publishLicensePresent = asBooleanOrNull(publishTarget.license_present);
  const publishRepoEnsureOutcome =
    asStringOrNull(publishTarget.repo_ensure_outcome)
    || asStringOrNull(publishConfigPrerequisites.publish_target_repo_ensure_summary);
  const publishRepositoryProvisioningGuidance = toRepositoryProvisioningGuidance({
    repoEnsureOutcome: publishRepoEnsureOutcome,
    repositoryExists: publishRepositoryExists,
    repositoryAutoCreateEnabled: publishRepositoryAutoCreateEnabled,
    repositoryAutoCreateAvailable: publishRepositoryAutoCreateAvailable,
    repositoryEnsureFailureReasonCode: publishRepositoryEnsureFailureReasonCode,
    publishPreflightStatus,
    publishPreflightBlockerCode,
    publishPreflightWouldBootstrapBranch,
    publishPreflightWouldReconcileRepoBaseline,
    readmePresent: publishReadmePresent,
    gitignorePresent: publishGitignorePresent,
    licensePresent: publishLicensePresent,
  });
  const deployPrimaryBlockerMessage = toDeployBlockerMessage(deployBlockerCodes);
  const contextSummary = asRecord(summary?.context_summary);
  const ga4OutcomeSnapshotRecord = asRecord(summary?.ga4_outcome_snapshot);
  const ga4OutcomeSnapshotPresent = summary?.ga4_outcome_snapshot != null && Object.keys(ga4OutcomeSnapshotRecord).length > 0;
  const ga4OutcomeSnapshotStatus = normalizeGa4OutcomeSnapshotStatus(asStringOrNull(ga4OutcomeSnapshotRecord.status));
  const ga4OutcomeSnapshotAnchorType = asStringOrNull(ga4OutcomeSnapshotRecord.anchor_type);
  const ga4OutcomeSnapshotSubtitle = toGa4OutcomeAnchorSubtitle(ga4OutcomeSnapshotAnchorType);
  const ga4OutcomeSnapshotOperatorHint = asStringOrNull(ga4OutcomeSnapshotRecord.operator_hint);
  const ga4OutcomeSnapshotBeforeWindow = asRecord(ga4OutcomeSnapshotRecord.before_window);
  const ga4OutcomeSnapshotAfterWindow = asRecord(ga4OutcomeSnapshotRecord.after_window);
  const ga4OutcomeSnapshotDelta = asRecord(ga4OutcomeSnapshotRecord.delta);
  const ga4OutcomeSnapshotOutcomeDirection = asStringOrNull(ga4OutcomeSnapshotRecord.outcome_direction);
  const ga4OutcomeSnapshotBeforeSessions = asNumberOrNull(ga4OutcomeSnapshotBeforeWindow.sessions);
  const ga4OutcomeSnapshotAfterSessions = asNumberOrNull(ga4OutcomeSnapshotAfterWindow.sessions);
  const ga4OutcomeSnapshotBeforeUsers = asNumberOrNull(ga4OutcomeSnapshotBeforeWindow.users);
  const ga4OutcomeSnapshotAfterUsers = asNumberOrNull(ga4OutcomeSnapshotAfterWindow.users);
  const ga4OutcomeSnapshotBeforeEngagementRate = asNumberOrNull(ga4OutcomeSnapshotBeforeWindow.engagement_rate);
  const ga4OutcomeSnapshotAfterEngagementRate = asNumberOrNull(ga4OutcomeSnapshotAfterWindow.engagement_rate);
  const ga4OutcomeSnapshotSessionsDeltaPercent = asNumberOrNull(ga4OutcomeSnapshotDelta.sessions_delta_percent);
  const ga4OutcomeSnapshotEngagementDeltaPoints = asNumberOrNull(ga4OutcomeSnapshotDelta.engagement_rate_delta_points);
  const ga4OutcomeSnapshotOrganicDeltaPercent = asNumberOrNull(ga4OutcomeSnapshotDelta.organic_sessions_delta_percent);
  const hasGa4OutcomeSnapshot =
    ga4OutcomeSnapshotPresent
    && (
      ga4OutcomeSnapshotStatus === "available"
      || ga4OutcomeSnapshotStatus === "pending_after_window"
      || ga4OutcomeSnapshotStatus === "insufficient_data"
      || ga4OutcomeSnapshotStatus === "not_configured"
      || ga4OutcomeSnapshotStatus === "missing_scope"
      || ga4OutcomeSnapshotStatus === "permission_denied"
      || ga4OutcomeSnapshotStatus === "unavailable"
    );
  const draftInputSummary = asRecord(contextSummary.draft_input_summary);
  const recommendationCategories = asStringList(draftInputSummary.recommendation_categories_included);
  const topRecommendationTitles = asStringList(draftInputSummary.top_recommendation_titles);
  const recommendationCategoriesCompact = summarizeListWithLimit(recommendationCategories, 4, 110);
  const topRecommendationTitlesCompact = summarizeListWithLimit(topRecommendationTitles, 3, 150);
  const recommendationCategoriesSummaryValue =
    recommendationCategoriesCompact.hiddenCount > 0
      ? `${recommendationCategoriesCompact.summary} (+${recommendationCategoriesCompact.hiddenCount} more)`
      : recommendationCategoriesCompact.summary;
  const topRecommendationTitlesSummaryValue =
    topRecommendationTitlesCompact.hiddenCount > 0
      ? `${topRecommendationTitlesCompact.summary} (+${topRecommendationTitlesCompact.hiddenCount} more)`
      : topRecommendationTitlesCompact.summary;
  const mediaSummaryFromContext = asRecord(contextSummary.media_assets);
  const mediaSummaryFromRoute = asRecord(mediaAssetsSnapshot);
  const mediaSummary =
    Object.keys(mediaSummaryFromRoute).length > 0
      ? mediaSummaryFromRoute
      : mediaSummaryFromContext;
  const sourceDiscoveredMediaAssets = asRecordList(mediaSummary.source_discovered);
  const operatorUploadedMediaAssets = asRecordList(mediaSummary.operator_uploaded);
  const selectedMediaAssets = asRecordList(mediaSummary.selected_assets);
  const sourceDiscoveredUsefulMediaAssets = sourceDiscoveredMediaAssets.filter(
    (item) => mediaCandidateQuality(item) === "useful",
  );
  const sourceDiscoveredLowValueMediaAssets = sourceDiscoveredMediaAssets.filter(
    (item) => mediaCandidateQuality(item) === "low_value",
  );
  const sourceDiscoveredRejectedMediaAssets = sourceDiscoveredMediaAssets.filter(
    (item) => mediaCandidateQuality(item) === "rejected",
  );
  const sourceDiscoveredDeemphasizedCount =
    sourceDiscoveredLowValueMediaAssets.length + sourceDiscoveredRejectedMediaAssets.length;
  const draftReadinessPreflight = asRecord(draftReadinessSnapshot);
  const sourceDiscoveredMediaCount =
    asNonNegativeInt(mediaSummary.source_discovered_count) ?? sourceDiscoveredMediaAssets.length;
  const pagesScannedCount =
    asNonNegativeInt(mediaSummary.pages_scanned_count)
    ?? asNonNegativeInt(asRecord(sourceSnapshot || {}).pages_scanned_count)
    ?? 0;
  const pagesScannedUrls = asStringList(asRecord(sourceSnapshot || {}).pages_scanned);
  const usefulDiscoveredImagesCount =
    asNonNegativeInt(draftReadinessPreflight.useful_discovered_images_count)
    ?? asNonNegativeInt(draftInputSummary.useful_discovered_images_count)
    ?? sourceDiscoveredUsefulMediaAssets.length;
  const lowValueDiscoveredImagesCount =
    asNonNegativeInt(draftReadinessPreflight.low_value_discovered_images_count)
    ?? asNonNegativeInt(draftInputSummary.low_value_discovered_images_count)
    ?? sourceDiscoveredLowValueMediaAssets.length;
  const rejectedDiscoveredImagesCount =
    asNonNegativeInt(draftReadinessPreflight.rejected_discovered_images_count)
    ?? asNonNegativeInt(draftInputSummary.rejected_discovered_images_count)
    ?? sourceDiscoveredRejectedMediaAssets.length;
  const sourceImportedMediaCount =
    asNonNegativeInt(mediaSummary.source_imported_count)
    ?? sourceDiscoveredMediaAssets.filter((item) => {
      const importStatus = (asStringOrNull(item.import_status) || "").trim().toLowerCase();
      return importStatus === "imported" || importStatus === "selected" || importStatus === "available";
    }).length;
  const operatorUploadedMediaCount =
    asNonNegativeInt(mediaSummary.operator_uploaded_count) ?? operatorUploadedMediaAssets.length;
  const selectedMediaAssetsCount =
    asNonNegativeInt(mediaSummary.selected_assets_count) ?? selectedMediaAssets.length;
  const mediaRequiredByOperator =
    asBooleanOrNull(draftReadinessPreflight.media_required_by_operator)
    ?? asBooleanOrNull(draftInputSummary.media_required_by_operator)
    ?? false;
  const mediaRequirementSources = asStringList(
    draftReadinessPreflight.media_requirement_sources || draftInputSummary.media_requirement_sources,
  );
  const selectedUsableMediaAssetsCount =
    asNonNegativeInt(draftReadinessPreflight.selected_usable_media_assets_count)
    ?? asNonNegativeInt(draftInputSummary.selected_usable_media_assets_count)
    ?? selectedMediaAssetsCount;
  const artifactMediaSelectedAssetsCount =
    asNonNegativeInt(draftInputSummary.artifact_media_selected_assets_count)
    ?? selectedUsableMediaAssetsCount;
  const artifactMediaMaterializedAssetsCount =
    asNonNegativeInt(draftInputSummary.artifact_media_materialized_assets_count)
    ?? 0;
  const artifactMediaReferencedPathsCount =
    asNonNegativeInt(draftInputSummary.artifact_media_referenced_paths_count)
    ?? 0;
  const artifactMediaUnresolvedReferencesCount =
    asNonNegativeInt(draftInputSummary.artifact_media_unresolved_references_count)
    ?? 0;
  const artifactMediaSelectedNotMaterializedCount =
    asNonNegativeInt(draftInputSummary.artifact_media_selected_not_materialized_count)
    ?? 0;
  const artifactMediaUnreferencedMaterializedCount =
    asNonNegativeInt(draftInputSummary.artifact_media_unreferenced_materialized_count)
    ?? 0;
  const artifactMediaReadyForPublishDeploy = asBooleanOrNull(
    draftInputSummary.artifact_media_ready_for_publish_deploy,
  );
  const artifactMediaBlockerCodes = asStringList(draftInputSummary.artifact_media_blocker_codes);
  const mediaRequirementSatisfied =
    asBooleanOrNull(draftReadinessPreflight.media_requirement_satisfied)
    ?? asBooleanOrNull(draftInputSummary.media_requirement_satisfied)
    ?? (!mediaRequiredByOperator || selectedUsableMediaAssetsCount > 0);
  const usefulDiscoveredButNotImportedOrSelected =
    usefulDiscoveredImagesCount > 0 && sourceImportedMediaCount <= 0 && selectedUsableMediaAssetsCount <= 0;
  const mediaRequirementWarningReason =
    asStringOrNull(draftReadinessPreflight.media_requirement_warning_reason)
    || asStringOrNull(draftInputSummary.media_requirement_warning_reason);
  const usableMediaAssetsCount =
    asNonNegativeInt(draftReadinessPreflight.usable_media_assets_count)
    ?? asNonNegativeInt(draftInputSummary.usable_media_assets_count)
    ?? [...sourceDiscoveredMediaAssets, ...operatorUploadedMediaAssets].filter((item) =>
      isMediaAssetUsableForDraft(item),
    ).length;
  const selectedMediaAssetIds = useMemo(() => {
    const selectedIds: string[] = [];
    const seen = new Set<string>();
    for (const item of selectedMediaAssets) {
      const assetId = asStringOrNull(item.asset_id);
      if (!assetId) {
        continue;
      }
      const key = assetId.toLowerCase();
      if (seen.has(key)) {
        continue;
      }
      seen.add(key);
      selectedIds.push(assetId);
    }
    return selectedIds;
  }, [selectedMediaAssets]);
  const mediaBrowserAssets = useMemo(() => {
    const byAssetKey = new Map<string, Record<string, unknown>>();
    const mergeMediaAssetRecord = (
      current: Record<string, unknown>,
      incoming: Record<string, unknown>,
    ): Record<string, unknown> => {
      const merged: Record<string, unknown> = { ...current, ...incoming };
      const preserveIfMissing = (
        key: "preview_url" | "display_url",
      ): void => {
        const nextValue = incoming[key];
        const currentValue = current[key];
        const nextMissing = nextValue == null || (typeof nextValue === "string" && nextValue.trim().length === 0);
        const currentPresent = currentValue != null && (
          typeof currentValue !== "string" || currentValue.trim().length > 0
        );
        if (nextMissing && currentPresent) {
          merged[key] = currentValue;
        }
      };
      preserveIfMissing("preview_url");
      preserveIfMissing("display_url");
      return merged;
    };
    const ingest = (items: Array<Record<string, unknown>>, sourceTag: string): void => {
      items.forEach((rawItem, index) => {
        const item = asRecord(rawItem);
        const assetId = asStringOrNull(item.asset_id);
        const normalizedUrl = asStringOrNull(item.normalized_url);
        const key = (assetId || normalizedUrl || `${sourceTag}-${index}`).toLowerCase();
        if (!key) {
          return;
        }
        const current = byAssetKey.get(key) || {};
        byAssetKey.set(key, mergeMediaAssetRecord(current, item));
      });
    };
    ingest(sourceDiscoveredMediaAssets, "source");
    ingest(operatorUploadedMediaAssets, "uploaded");
    ingest(selectedMediaAssets, "selected");

    const mergedAssets = Array.from(byAssetKey.values())
      .map((asset, index) => {
        const assetId =
          asStringOrNull(asset.asset_id)
          || asStringOrNull(asset.normalized_url)
          || `asset-${index}`;
        const suggestion = asRecord(asset.metadata_suggestion);
        const suggestionStatus = (asStringOrNull(suggestion.suggestion_status) || "").trim().toLowerCase();
        const suggestionReason = toMediaSuggestionReasonLabel(asStringOrNull(suggestion.reason_code));
        const lifecycleLabels = toMediaLifecycleLabels(asset);
        const remoteImportRequired = isSourceAssetImportRequired(asset);
        const validatedForImport = isDiscoveredCandidateValidatedForImport(asset);
        const unavailableReasonCode = mediaAssetUnavailableReasonCode(asset);
        const unavailableReason = toMediaSuggestionReasonLabel(unavailableReasonCode);
        const canSelectForDraft = isMediaAssetUsableForDraft(asset);
        const canSuggestMetadata = !remoteImportRequired && suggestionStatus !== "not_available";
        const selected = Boolean(asset.selected_for_draft);
        const candidateQuality = mediaCandidateQuality(asset);
        const suggestionCompleted = suggestionStatus === "completed";
        const suggestionApplied = Boolean(asset.metadata_suggestion_applied);
        const provenance = (asStringOrNull(asset.provenance) || "").trim().toLowerCase();
        const importStatus = (asStringOrNull(asset.import_status) || "").trim().toLowerCase();
        const isImportedOrUploaded =
          provenance === "operator_upload"
          || importStatus === "imported"
          || importStatus === "selected"
          || importStatus === "available"
          || importStatus === "uploaded";
        const previewAvailability = resolveMediaPreviewAvailability(asset, { remoteImportRequired });
        const previewUnavailableReason = toMediaPreviewUnavailableReasonLabel(previewAvailability.reasonCode);
        const analysisUnavailableInRuntime =
          suggestionStatus === "not_available"
          && (
            (asStringOrNull(suggestion.reason_code) || "").trim().toLowerCase() === "image_analysis_not_available"
            || (asStringOrNull(suggestion.reason_code) || "").trim().toLowerCase() === "provider_unavailable"
          );
        const metadataStatusLabel = suggestionApplied
          ? "Metadata applied"
          : suggestionCompleted
            ? "Suggestion ready"
            : suggestionStatus === "pending"
              ? "Analysis pending"
              : suggestionStatus === "not_available"
                ? "Analysis unavailable"
                : null;
        const sourceBadgeLabel = provenance === "operator_upload"
          ? "Uploaded"
          : remoteImportRequired
            ? "Discovered"
            : "Imported";
        const blockedReasonCode = (() => {
          if (candidateQuality === "rejected") {
            return mediaCandidateReasonCode(asset) || unavailableReasonCode || "media_asset_rejected";
          }
          if (
            candidateQuality === "low_value"
            && remoteImportRequired
            && !isDiscoveredQualityOverrideImportAllowed(asset)
          ) {
            return mediaCandidateReasonCode(asset) || "media_asset_low_value";
          }
          if (unavailableReasonCode && unavailableReasonCode !== "media_asset_not_imported") {
            return unavailableReasonCode;
          }
          return null;
        })();
        const isBlocked = Boolean(blockedReasonCode);
        let primaryAction: MediaPrimaryAction = "none";
        if (!isBlocked) {
          primaryAction = candidateQuality === "low_value" ? "use_in_draft_anyway" : "use_in_draft";
        }
        const lifecycleAction: MediaLifecycleAction = (() => {
          if (provenance === "source_site_import" && remoteImportRequired) {
            return "ignore";
          }
          if (isImportedOrUploaded) {
            return "remove";
          }
          return "none";
        })();
        const lifecycleActionLabel = (() => {
          if (lifecycleAction === "ignore") {
            return "Ignore";
          }
          if (lifecycleAction === "remove") {
            return provenance === "source_site_import" ? "Remove from workspace" : "Remove image";
          }
          return null;
        })();
        const compactReasonLabel =
          isBlocked
            ? toMediaSuggestionReasonLabel(blockedReasonCode) || unavailableReason || "Blocked for safety reasons."
            : candidateQuality === "low_value"
              ? "Quality warning only. Operator can still use this image in draft."
              : remoteImportRequired
                ? "Import before using in draft or AI image analysis."
                : selected
                  ? "Included in next draft."
                  : "Ready to include in next draft.";
        return {
          asset,
          assetId,
          displayName: toMediaAssetDisplayName(asset, assetId),
          sourceBadgeLabel,
          metadataStatusLabel,
          lifecycleLabels,
          suggestionStatus,
          suggestionReason,
          analysisUnavailableInRuntime,
          selected,
          canSelectForDraft,
          canSuggestMetadata,
          suggestionCompleted,
          suggestionApplied,
          remoteImportRequired,
          validatedForImport,
          candidateQuality,
          mediaUnavailableReasonCode: unavailableReasonCode,
          mediaUnavailableReason: unavailableReason,
          blockedReasonCode,
          isBlocked,
          isImportedOrUploaded,
          primaryAction,
          compactReasonLabel,
          previewUrl: previewAvailability.previewUrl,
          previewUnavailableReasonCode: previewAvailability.reasonCode,
          previewUnavailableReason,
          previewAlt: toMediaPreviewAltText(asset),
          provenance: asStringOrNull(asset.provenance),
          normalizedUrl: asStringOrNull(asset.normalized_url),
          qualityReason: asStringOrNull(asset.quality_reason),
          sourcePageUrl: asStringOrNull(asset.source_page_url),
          lifecycleAction,
          lifecycleActionLabel,
          imageReferenceSlugBase: toImageReferenceSlug(toMediaAssetDisplayName(asset, assetId), assetId),
        };
      })
      .sort((left, right) => {
        const rank = (item: {
          candidateQuality: "useful" | "low_value" | "rejected";
          selected: boolean;
          isBlocked: boolean;
          isImportedOrUploaded: boolean;
          remoteImportRequired: boolean;
        }): number => {
          if (item.isBlocked) {
            return 4;
          }
          if (item.selected) {
            return 0;
          }
          if (item.isImportedOrUploaded) {
            return 1;
          }
          if (item.remoteImportRequired) {
            return 2;
          }
          return 3;
        };
        const leftRank = rank(left);
        const rightRank = rank(right);
        if (leftRank !== rightRank) {
          return leftRank - rightRank;
        }
        return left.displayName.localeCompare(right.displayName, undefined, { sensitivity: "base" });
      });
    const slugCounts = new Map<string, number>();
    return mergedAssets.map((item) => {
      const baseSlug = item.imageReferenceSlugBase;
      const seenCount = slugCounts.get(baseSlug) ?? 0;
      const nextCount = seenCount + 1;
      slugCounts.set(baseSlug, nextCount);
      const imageReferenceSlug = seenCount === 0 ? baseSlug : `${baseSlug}-${nextCount}`;
      return {
        ...item,
        imageReferenceSlug,
        imageReferenceToken: `@image(${imageReferenceSlug})`,
      };
    });
  }, [
    operatorUploadedMediaAssets,
    selectedMediaAssets,
    sourceDiscoveredMediaAssets,
  ]);
  const mediaBrowserAssetLookup = useMemo(() => {
    const lookup = new Map<string, (typeof mediaBrowserAssets)[number]>();
    for (const item of mediaBrowserAssets) {
      lookup.set(item.assetId.toLowerCase(), item);
    }
    return lookup;
  }, [mediaBrowserAssets]);
  const discoveredImportRequiredCount = useMemo(
    () => mediaBrowserAssets.filter((item) => item.remoteImportRequired && !item.isBlocked).length,
    [mediaBrowserAssets],
  );
  const mediaFilterCounts = useMemo(() => {
    const countByFilter = (filter: MediaBrowserFilter): number =>
      mediaBrowserAssets.filter((item) => {
        if (filter === "all_usable") {
          return !item.isBlocked;
        }
        if (filter === "discovered") {
          return (item.provenance || "").trim().toLowerCase() === "source_site_import" && !item.isBlocked;
        }
        if (filter === "uploaded_imported") {
          return item.isImportedOrUploaded && !item.isBlocked;
        }
        return item.isBlocked;
      }).length;
    return {
      all_usable: countByFilter("all_usable"),
      discovered: countByFilter("discovered"),
      uploaded_imported: countByFilter("uploaded_imported"),
      unsafe_rejected: countByFilter("unsafe_rejected"),
    };
  }, [mediaBrowserAssets]);
  const mediaBrowserVisibleAssets = useMemo(() => {
    return mediaBrowserAssets.filter((item) => {
      if (mediaBrowserFilter === "all_usable") {
        return !item.isBlocked;
      }
      if (mediaBrowserFilter === "discovered") {
        return (item.provenance || "").trim().toLowerCase() === "source_site_import" && !item.isBlocked;
      }
      if (mediaBrowserFilter === "uploaded_imported") {
        return item.isImportedOrUploaded && !item.isBlocked;
      }
      return item.isBlocked;
    });
  }, [mediaBrowserAssets, mediaBrowserFilter]);
  const checkedMediaAssetIdsResolved = useMemo(() => {
    if (checkedMediaAssetIds.length === 0) {
      return [];
    }
    const resolved: string[] = [];
    const seen = new Set<string>();
    for (const assetId of checkedMediaAssetIds) {
      const key = assetId.toLowerCase();
      if (seen.has(key)) {
        continue;
      }
      seen.add(key);
      const item = mediaBrowserAssetLookup.get(key);
      if (!item || item.isBlocked) {
        continue;
      }
      resolved.push(item.assetId);
    }
    return resolved;
  }, [checkedMediaAssetIds, mediaBrowserAssetLookup]);
  const checkedMediaAssetLookup = useMemo(
    () => new Set(checkedMediaAssetIdsResolved.map((item) => item.toLowerCase())),
    [checkedMediaAssetIdsResolved],
  );
  useEffect(() => {
    setCheckedMediaAssetIds((current) => {
      const allowed = new Set(
        mediaBrowserAssets
          .filter((item) => !item.isBlocked)
          .map((item) => item.assetId.toLowerCase()),
      );
      const selectedSafe = mediaBrowserAssets
        .filter((item) => item.selected && !item.isBlocked)
        .map((item) => item.assetId);
      const deduped: string[] = [];
      const seen = new Set<string>();
      for (const item of [...current, ...selectedSafe]) {
        const key = item.toLowerCase();
        if (seen.has(key) || !allowed.has(key)) {
          continue;
        }
        seen.add(key);
        deduped.push(item);
      }
      if (deduped.length === current.length && deduped.every((item, index) => item === current[index])) {
        return current;
      }
      return deduped;
    });
  }, [mediaBrowserAssets]);
  const mediaImportBatchRecord = asRecord(mediaImportBatchSnapshot);
  const mediaImportBatchStatus = asStringOrNull(mediaImportBatchRecord.batch_status);
  const mediaImportBatchResults = asRecordList(mediaImportBatchRecord.results);
  const mediaImportBatchImportedCount = asNonNegativeInt(mediaImportBatchRecord.imported_count) ?? 0;
  const mediaImportBatchFailedCount = asNonNegativeInt(mediaImportBatchRecord.failed_count) ?? 0;
  const mediaImportBatchSkippedCount = asNonNegativeInt(mediaImportBatchRecord.skipped_count) ?? 0;
  const mediaImportBatchDisabledCount = asNonNegativeInt(mediaImportBatchRecord.disabled_count) ?? 0;
  const mediaSuggestionBatchRecord = asRecord(mediaSuggestionBatchSnapshot);
  const mediaSuggestionBatchStatus = asStringOrNull(mediaSuggestionBatchRecord.batch_status);
  const mediaSuggestionBatchResults = asRecordList(mediaSuggestionBatchRecord.results);
  const mediaSuggestionBatchCompletedCount = asNonNegativeInt(mediaSuggestionBatchRecord.completed_count) ?? 0;
  const mediaSuggestionBatchFailedCount = asNonNegativeInt(mediaSuggestionBatchRecord.failed_count) ?? 0;
  const mediaSuggestionBatchSkippedCount = asNonNegativeInt(mediaSuggestionBatchRecord.skipped_count) ?? 0;
  const mediaAssetCategories = asStringList(mediaSummary.media_asset_categories);
  const mediaSelectedAssetsTrimmed = Boolean(mediaSummary.selected_assets_trimmed);
  const migrationDiagnostics = asRecord(contextSummary.migration_diagnostics);
  const mediaDiagnostics = asStringList(migrationDiagnostics.media_diagnostics || mediaSummary.diagnostics);
  const currentSiteUrl = asStringOrNull(sourceSnapshot?.final_url) || asStringOrNull(summary?.workspace.source_url);
  const destinationSummary = deriveMigrationDestinationSummary({
    contextSummary,
    publishTarget,
    deployTarget,
    effectivePublishRepoOwner,
    effectivePublishRepoName,
    effectivePublishBranch,
    effectivePublishArtifactRoot,
    currentSiteUrl,
  });
  const publishReadinessReasons = asStringList(publishReadiness.reasons);
  const publishReadinessWarnings = asStringList(publishReadiness.warnings);
  const deployReadinessReasons = asStringList(deployReadiness.reasons);
  const publishReadinessHasCurrentReasons = publishReadinessReasons.length > 0;
  const publishCurrentReadinessReason = publishReadinessReasons[0] || null;
  const publishReasonAppearsGeneric = (() => {
    const normalizedReason = (publishCurrentReadinessReason || "").trim().toLowerCase();
    return (
      normalizedReason === "publish target is not ready."
      || normalizedReason === "publish target is not ready"
      || normalizedReason === "publish target is not enabled."
      || normalizedReason === "publish target is not enabled"
      || normalizedReason === "publish target is not configured."
      || normalizedReason === "publish target is not configured"
    );
  })();
  const publishPrimaryBlockerMessage = !Boolean(publishReadiness.ready)
    ? (
      (publishCurrentReadinessReason && (!publishReasonAppearsGeneric || !publishFailureMessage))
        ? publishCurrentReadinessReason
        : publishRuntimeStatusMessage || publishFailureMessage || publishCurrentReadinessReason || "Publish target is not ready."
    )
    : null;
  const publishSecondaryFailureMessage =
    !Boolean(publishReadiness.ready)
    && !publishReadinessHasCurrentReasons
    && publishFailureMessage
    && publishFailureMessage !== publishPrimaryBlockerMessage
      ? publishFailureMessage
      : null;
  const publishPrimaryWarningMessage = publishReadinessWarnings[0] || null;
  const publishRepoAdoptionRequired = (() => {
    const normalizedPreflightBlocker = (publishPreflightBlockerCode || "").trim().toLowerCase();
    return (
      normalizedPreflightBlocker === "github_repo_adoption_required"
      || normalizedPreflightBlocker === "github_repo_management_marker_missing"
    );
  })();
  const deploySummaryBlockerMessage = !Boolean(deployReadiness.ready)
    ? deployPrimaryBlockerMessage || deployRuntimeStatusMessage || deployReadinessReasons[0] || deployFailureMessage || "Deploy target is not ready."
    : null;
  const publishTargetStateLabel = toDestinationStateLabel(destinationSummary.publishState);
  const deployTargetStateLabel = toDestinationStateLabel(destinationSummary.deployState);
  const hasDestinationAdditionalDiagnostics =
    Boolean(destinationSummary.draftPreviewState) ||
    Boolean(destinationSummary.draftPreviewEntryPath) ||
    Boolean(destinationSummary.currentSiteUrl) ||
    Boolean(destinationSummary.publishRepositoryUrl) ||
    Boolean(destinationSummary.publishExpectedPublishedUrl) ||
    Boolean(destinationSummary.publishUrlSource) ||
    Boolean(destinationSummary.publishUrlSourceDetail) ||
    Boolean(destinationSummary.deployUrlSource) ||
    Boolean(destinationSummary.deployUrlSourceDetail);
  const publishHistoryRecords = useMemo(
    () => publishHistory.map((item) => asRecord(item)),
    [publishHistory],
  );
  const deployHistoryRecords = useMemo(
    () => deployHistory.map((item) => asRecord(item)),
    [deployHistory],
  );
  const selectedPublishHistoryRecord = resolveSelectedHistoryRecord(
    publishHistoryRecords,
    selectedPublishHistoryIdentity,
  );
  const selectedDeployHistoryRecord = resolveSelectedHistoryRecord(
    deployHistoryRecords,
    selectedDeployHistoryIdentity,
  );
  const hasSelectedPublishAttempt = publishHistoryRecords.length > 0;
  const hasSelectedDeployAttempt = deployHistoryRecords.length > 0;
  const latestGeneratedArtifactId = asStringOrNull(summary?.workspace.latest_generated_artifact_version_id);

  // Diagnostics precedence:
  // 1) selected record context (publish/deploy row, selected draft artifact)
  // 2) latest summary diagnostics only for fields missing on selected context
  const publishFailureCategoryFromSelected = asStringOrNull(selectedPublishHistoryRecord.failure_category);
  const publishFailureCategoryFromSummary =
    asStringOrNull(migrationDiagnostics.last_publish_failure_category) ||
    asStringOrNull(publishReadiness.last_failure_category) ||
    asStringOrNull(publishReadiness.failure_category);
  const publishDiagnosticsFailureCategory = publishFailureCategoryFromSelected || publishFailureCategoryFromSummary;
  const publishFailureMessageFromSelected = asStringOrNull(selectedPublishHistoryRecord.failure_message);
  const publishFailureMessageFromSummary =
    asStringOrNull(migrationDiagnostics.last_publish_failure_message) ||
    asStringOrNull(publishReadiness.last_failure_message);
  const publishDiagnosticsFailureMessage = publishFailureMessageFromSelected || publishFailureMessageFromSummary;
  const publishFailureReasonCodeFromSelected = asStringOrNull(selectedPublishHistoryRecord.failure_reason);
  const publishFailureReasonCodeFromSummary =
    asStringOrNull(migrationDiagnostics.last_publish_failure_reason) ||
    asStringOrNull(publishReadiness.last_failure_reason);
  const publishDiagnosticsFailureReasonCode = publishFailureReasonCodeFromSelected || publishFailureReasonCodeFromSummary;
  const publishFailureStageFromSelected =
    asStringOrNull(selectedPublishHistoryRecord.failure_stage) ||
    asStringOrNull(selectedPublishHistoryRecord.dispatch_result_stage);
  const publishFailureStageFromSummary =
    asStringOrNull(migrationDiagnostics.last_publish_failure_stage) ||
    asStringOrNull(publishReadiness.last_failure_stage);
  const publishWorkflowRemediationAttemptedFromSelected = asBooleanOrNull(
    selectedPublishHistoryRecord.workflow_remediation_attempted,
  );
  const publishWorkflowRemediationAttemptedFromSummary =
    asBooleanOrNull(migrationDiagnostics.last_publish_workflow_remediation_attempted) ??
    asBooleanOrNull(publishReadiness.last_workflow_remediation_attempted);
  const publishWorkflowRemediationAttempted =
    publishWorkflowRemediationAttemptedFromSelected ?? publishWorkflowRemediationAttemptedFromSummary;
  const publishWorkflowRemediationOutcomeFromSelected = asStringOrNull(
    selectedPublishHistoryRecord.workflow_remediation_outcome,
  );
  const publishWorkflowRemediationOutcomeFromSummary =
    asStringOrNull(migrationDiagnostics.last_publish_workflow_remediation_outcome) ||
    asStringOrNull(publishReadiness.last_workflow_remediation_outcome);
  const publishWorkflowRemediationOutcome =
    publishWorkflowRemediationOutcomeFromSelected || publishWorkflowRemediationOutcomeFromSummary;
  const publishWorkflowRemediationGuidance = toWorkflowRemediationOutcomeGuidance(
    publishWorkflowRemediationOutcome,
  );
  const publishDiagnosticsUsingSummaryFallback =
    hasSelectedPublishAttempt &&
    ((!publishFailureCategoryFromSelected && !!publishFailureCategoryFromSummary) ||
      (!publishFailureMessageFromSelected && !!publishFailureMessageFromSummary) ||
      (!publishFailureReasonCodeFromSelected && !!publishFailureReasonCodeFromSummary) ||
      (!publishFailureStageFromSelected && !!publishFailureStageFromSummary) ||
      (publishWorkflowRemediationAttemptedFromSelected === null &&
        publishWorkflowRemediationAttemptedFromSummary !== null) ||
      (!publishWorkflowRemediationOutcomeFromSelected && !!publishWorkflowRemediationOutcomeFromSummary));

  const deployWorkflowIdentifier =
    asStringOrNull(selectedDeployHistoryRecord.workflow_identifier_used) ||
    asStringOrNull(selectedDeployHistoryRecord.workflow_identifier) ||
    asStringOrNull(deployReadiness.workflow_identifier_used) ||
    asStringOrNull(deployReadiness.workflow_identifier) ||
    asStringOrNull(deployTarget.workflow_id);
  const deployFailureCategoryFromSelected = asStringOrNull(selectedDeployHistoryRecord.failure_category);
  const deployFailureCategoryFromSummary =
    asStringOrNull(deployReadiness.last_failure_category) ||
    asStringOrNull(deployReadiness.failure_category);
  const deployDiagnosticsFailureCategory = deployFailureCategoryFromSelected || deployFailureCategoryFromSummary;
  const deployWorkflowIdentifierRequestedFromSelected = asStringOrNull(
    selectedDeployHistoryRecord.workflow_identifier_requested,
  );
  const deployWorkflowIdentifierRequestedFromSummary =
    asStringOrNull(deployReadiness.last_failure_workflow_identifier_requested) ||
    asStringOrNull(migrationDiagnostics.last_deploy_failure_workflow_identifier_requested) ||
    asStringOrNull(deployReadiness.workflow_identifier_requested) ||
    asStringOrNull(deployTarget.workflow_id);
  const deployWorkflowIdentifierRequested =
    deployWorkflowIdentifierRequestedFromSelected || deployWorkflowIdentifierRequestedFromSummary;
  const deployWorkflowDispatchResolutionSourceFromSelected = asStringOrNull(
    selectedDeployHistoryRecord.workflow_dispatch_resolution_source,
  );
  const deployWorkflowDispatchResolutionSourceFromSummary =
    asStringOrNull(deployReadiness.last_failure_workflow_dispatch_resolution_source) ||
    asStringOrNull(migrationDiagnostics.last_deploy_failure_workflow_dispatch_resolution_source) ||
    asStringOrNull(deployReadiness.workflow_dispatch_resolution_source);
  const deployWorkflowDispatchResolutionSource =
    deployWorkflowDispatchResolutionSourceFromSelected || deployWorkflowDispatchResolutionSourceFromSummary;
  const deployWorkflowFilePathFromSelected = asStringOrNull(selectedDeployHistoryRecord.workflow_file_path);
  const deployWorkflowFilePathFromSummary =
    asStringOrNull(deployReadiness.last_failure_workflow_file_path) ||
    asStringOrNull(migrationDiagnostics.last_deploy_failure_workflow_file_path) ||
    asStringOrNull(deployReadiness.workflow_file_path) ||
    asStringOrNull(deployTarget.resolved_workflow_path);
  const deployWorkflowFilePath = deployWorkflowFilePathFromSelected || deployWorkflowFilePathFromSummary;
  const deployResolvedWorkflowSource =
    asStringOrNull(selectedDeployHistoryRecord.resolved_workflow_source) ||
    asStringOrNull(deployTarget.resolved_workflow_source);
  const deployWorkflowMode =
    asStringOrNull(selectedDeployHistoryRecord.deploy_workflow_mode) ||
    asStringOrNull(deployTarget.deploy_workflow_mode) ||
    destinationSummary.deployWorkflowMode;
  const deployTargetEnvironmentKey =
    asStringOrNull(selectedDeployHistoryRecord.target_environment_key) ||
    asStringOrNull(deployTarget.target_environment_key) ||
    destinationSummary.deployTargetEnvironmentKey;
  const deployTargetEnvironmentSource =
    asStringOrNull(selectedDeployHistoryRecord.target_environment_source) ||
    asStringOrNull(deployTarget.target_environment_source) ||
    destinationSummary.deployTargetEnvironmentSource;
  const deploySiteWorkflowFilePath =
    asStringOrNull(selectedDeployHistoryRecord.site_workflow_file_path) ||
    asStringOrNull(deployTarget.site_workflow_file_path) ||
    destinationSummary.deploySiteWorkflowFilePath ||
    deployWorkflowFilePath;
  const deployKubernetesNamespace =
    asStringOrNull(selectedDeployHistoryRecord.kubernetes_namespace) ||
    asStringOrNull(deployTarget.kubernetes_namespace) ||
    destinationSummary.deployKubernetesNamespace;
  const deployNamespaceSource =
    asStringOrNull(selectedDeployHistoryRecord.namespace_source) ||
    asStringOrNull(deployTarget.namespace_source) ||
    destinationSummary.deployNamespaceSource;
  const deployNamespaceModelStatus =
    asStringOrNull(selectedDeployHistoryRecord.namespace_model_status) ||
    asStringOrNull(deployTarget.namespace_model_status) ||
    destinationSummary.deployNamespaceModelStatus;
  const deployWorkflowNamespaceAligned =
    asBooleanOrNull(selectedDeployHistoryRecord.workflow_namespace_aligned) ??
    asBooleanOrNull(deployTarget.workflow_namespace_aligned) ??
    destinationSummary.deployWorkflowNamespaceAligned;
  const deployManifestNamespaceAligned =
    asBooleanOrNull(selectedDeployHistoryRecord.manifest_namespace_aligned) ??
    asBooleanOrNull(deployTarget.manifest_namespace_aligned) ??
    destinationSummary.deployManifestNamespaceAligned;
  const managedResourceQuotaExpected =
    asBooleanOrNull(selectedDeployHistoryRecord.managed_resource_quota_expected) ??
    asBooleanOrNull(deployTarget.managed_resource_quota_expected) ??
    destinationSummary.managedResourceQuotaExpected;
  const managedResourceQuotaPresent =
    asBooleanOrNull(selectedDeployHistoryRecord.managed_resource_quota_present) ??
    asBooleanOrNull(deployTarget.managed_resource_quota_present) ??
    destinationSummary.managedResourceQuotaPresent;
  const managedLimitRangeExpected =
    asBooleanOrNull(selectedDeployHistoryRecord.managed_limit_range_expected) ??
    asBooleanOrNull(deployTarget.managed_limit_range_expected) ??
    destinationSummary.managedLimitRangeExpected;
  const managedLimitRangePresent =
    asBooleanOrNull(selectedDeployHistoryRecord.managed_limit_range_present) ??
    asBooleanOrNull(deployTarget.managed_limit_range_present) ??
    destinationSummary.managedLimitRangePresent;
  const managedNetworkPolicyExpected =
    asBooleanOrNull(selectedDeployHistoryRecord.managed_network_policy_expected) ??
    asBooleanOrNull(deployTarget.managed_network_policy_expected) ??
    destinationSummary.managedNetworkPolicyExpected;
  const managedNetworkPolicyPresent =
    asBooleanOrNull(selectedDeployHistoryRecord.managed_network_policy_present) ??
    asBooleanOrNull(deployTarget.managed_network_policy_present) ??
    destinationSummary.managedNetworkPolicyPresent;
  const managedNamespacePoliciesAligned =
    asBooleanOrNull(selectedDeployHistoryRecord.managed_namespace_policies_aligned) ??
    asBooleanOrNull(deployTarget.managed_namespace_policies_aligned) ??
    destinationSummary.managedNamespacePoliciesAligned;
  const deployTraceRepoOwner =
    asStringOrNull(selectedDeployHistoryRecord.repo_owner) || asStringOrNull(deployTarget.repo_owner);
  const deployTraceRepoName =
    asStringOrNull(selectedDeployHistoryRecord.repo_name) || asStringOrNull(deployTarget.repo_name);
  const deployTraceRepo =
    deployTraceRepoOwner && deployTraceRepoName ? `${deployTraceRepoOwner}/${deployTraceRepoName}` : null;
  const deployTraceRef =
    asStringOrNull(selectedDeployHistoryRecord.resolved_ref) ||
    asStringOrNull(selectedDeployHistoryRecord.ref) ||
    asStringOrNull(deployTarget.ref);
  const dispatchServiceReasonCodeFromSelected = asStringOrNull(
    selectedDeployHistoryRecord.dispatch_service_reason_code,
  );
  const dispatchServiceReasonCodeFromSummary =
    asStringOrNull(deployReadiness.last_failure_dispatch_service_reason_code) ||
    asStringOrNull(migrationDiagnostics.last_deploy_failure_dispatch_service_reason_code) ||
    asStringOrNull(deployReadiness.dispatch_service_reason_code);
  const dispatchServiceReasonCode = dispatchServiceReasonCodeFromSelected || dispatchServiceReasonCodeFromSummary;
  const managedGkeConfigDetails = asRecord(deployTarget.managed_gke_config_details);
  const deployAuthMode =
    asStringOrNull(selectedDeployHistoryRecord.deploy_auth_mode) ||
    asStringOrNull(managedGkeConfigDetails.deploy_auth_mode);
  const targetRepoDeploySecretRequired =
    asBooleanOrNull(selectedDeployHistoryRecord.target_repo_deploy_secret_required) ??
    asBooleanOrNull(managedGkeConfigDetails.target_repo_deploy_secret_required);
  const targetRepoDeploySecretName =
    asStringOrNull(selectedDeployHistoryRecord.target_repo_deploy_secret_name) ||
    asStringOrNull(managedGkeConfigDetails.target_repo_deploy_secret_name);
  const targetRepoDeploySecretPresent =
    asBooleanOrNull(selectedDeployHistoryRecord.target_repo_deploy_secret_present) ??
    asBooleanOrNull(managedGkeConfigDetails.target_repo_deploy_secret_present);
  const staticIpErrorDiagnosticsFromSelected = asRecord(selectedDeployHistoryRecord.static_ip_error_diagnostics);
  const staticIpErrorDiagnosticsFromSummary = asRecord(deployReadiness.last_failure_static_ip_error_diagnostics);
  const staticIpErrorDiagnostics =
    Object.keys(staticIpErrorDiagnosticsFromSelected).length > 0
      ? staticIpErrorDiagnosticsFromSelected
      : staticIpErrorDiagnosticsFromSummary;
  const staticIpDescribeAttempts =
    asNonNegativeInt(selectedDeployHistoryRecord.static_ip_describe_attempts) ??
    asNonNegativeInt(staticIpErrorDiagnostics.static_ip_describe_attempts);
  const staticIpListFallbackAttempted =
    asBooleanOrNull(selectedDeployHistoryRecord.static_ip_list_fallback_attempted) ??
    asBooleanOrNull(staticIpErrorDiagnostics.static_ip_list_fallback_attempted);
  const staticIpListFallbackMatchCount =
    asNonNegativeInt(selectedDeployHistoryRecord.static_ip_list_fallback_match_count) ??
    asNonNegativeInt(staticIpErrorDiagnostics.static_ip_list_fallback_match_count);
  const staticIpListFallbackAddressPresent =
    asBooleanOrNull(selectedDeployHistoryRecord.static_ip_list_fallback_address_present) ??
    asBooleanOrNull(staticIpErrorDiagnostics.static_ip_list_fallback_address_present);
  const staticIpListFallbackResponseKeys = (() => {
    const fromSelected = asStringList(selectedDeployHistoryRecord.static_ip_list_fallback_response_keys);
    if (fromSelected.length > 0) {
      return fromSelected;
    }
    return asStringList(staticIpErrorDiagnostics.static_ip_list_fallback_response_keys);
  })();
  const managedGkeConfigGuidance = toManagedGkeConfigGuidance(dispatchServiceReasonCode);
  const showManagedGkeConfigSourceHint = managedGkeConfigGuidance !== null;
  const managedSiteRolloutState = asStringOrNull(deployReadiness.managed_site_rollout_state);
  const managedSiteRolloutMessage = asStringOrNull(deployReadiness.managed_site_rollout_message);
  const managedSiteRolloutFixActive = asBooleanOrNull(deployReadiness.managed_site_rollout_fix_active);
  const managedSiteRolloutStaleEvidence = (managedSiteRolloutState || "").trim().toLowerCase() === "workflow_republished_but_deploy_not_rerun";
  const managedSiteExpectedImageRepository = asStringOrNull(
    deployReadiness.managed_site_rollout_expected_image_repository,
  );
  const managedSiteManifestImageReference = asStringOrNull(
    deployReadiness.managed_site_rollout_manifest_image_reference,
  );
  const managedSiteObservedDeployImageReference =
    asStringOrNull(deployReadiness.managed_site_rollout_observed_deploy_image_reference) ||
    asStringOrNull(selectedDeployHistoryRecord.site_runtime_image_reference);
  const managedSiteObservedDeployImageDigest =
    asStringOrNull(deployReadiness.managed_site_rollout_observed_deploy_image_digest) ||
    asStringOrNull(selectedDeployHistoryRecord.site_runtime_image_digest) ||
    parseImageDigest(selectedDeployHistoryRecord.site_runtime_image_identity) ||
    extractDigestFromImageReference(managedSiteObservedDeployImageReference);
  const managedSiteObservedDeployImageDigestDisplay =
    managedSiteObservedDeployImageReference || managedSiteManifestImageReference
      ? managedSiteObservedDeployImageDigest || "Digest not reported"
      : null;
  const privateImageAuthRequired =
    asBooleanOrNull(deployTarget.private_image_auth_required) ??
    asBooleanOrNull(deployReadiness.private_image_auth_required);
  const privateImageCredentialsAvailableInControlPlane =
    asBooleanOrNull(deployTarget.private_image_credentials_available_in_control_plane) ??
    asBooleanOrNull(deployReadiness.private_image_credentials_available_in_control_plane);
  const targetRepoSecretsNotRequired =
    asBooleanOrNull(deployTarget.target_repo_secrets_not_required) ??
    asBooleanOrNull(deployReadiness.target_repo_secrets_not_required);
  const imagePullSecretNotProvisioned =
    asBooleanOrNull(deployTarget.image_pull_secret_not_provisioned) ??
    asBooleanOrNull(deployReadiness.image_pull_secret_not_provisioned);
  const imagePullSecretProvisioningUnavailable =
    asBooleanOrNull(deployTarget.image_pull_secret_provisioning_unavailable) ??
    asBooleanOrNull(deployReadiness.image_pull_secret_provisioning_unavailable);
  const workflowConformanceChecked =
    asBooleanOrNull(selectedDeployHistoryRecord.workflow_conformance_checked) ??
    asBooleanOrNull(deployReadiness.workflow_conformance_checked);
  const workflowConformanceStatusFromSelected = asStringOrNull(selectedDeployHistoryRecord.workflow_conformance_status);
  const workflowConformanceStatusFromSummary =
    asStringOrNull(deployReadiness.last_failure_workflow_conformance_status) ||
    asStringOrNull(deployReadiness.workflow_conformance_status);
  const workflowConformanceStatus = workflowConformanceStatusFromSelected || workflowConformanceStatusFromSummary;
  const workflowConformanceReasons = (() => {
    const historyReasons = asStringList(selectedDeployHistoryRecord.workflow_conformance_reasons);
    if (historyReasons.length > 0) {
      return historyReasons;
    }
    const failureReasons = asStringList(deployReadiness.last_failure_workflow_conformance_reasons);
    if (failureReasons.length > 0) {
      return failureReasons;
    }
    const diagnosticReasons = asStringList(migrationDiagnostics.last_deploy_failure_workflow_conformance_reasons);
    if (diagnosticReasons.length > 0) {
      return diagnosticReasons;
    }
    return asStringList(deployReadiness.workflow_conformance_reasons);
  })();
  const workflowConformanceEvidenceSummary =
    asStringOrNull(selectedDeployHistoryRecord.workflow_conformance_evidence_summary) ||
    asStringOrNull(deployReadiness.workflow_conformance_evidence_summary);
  const dispatchAttempted =
    asBooleanOrNull(selectedDeployHistoryRecord.dispatch_attempted) ??
    asBooleanOrNull(deployReadiness.last_dispatch_attempted);
  const dispatchRefSent =
    asStringOrNull(selectedDeployHistoryRecord.dispatch_ref_sent) ||
    asStringOrNull(deployReadiness.last_dispatch_ref_sent) ||
    deployTraceRef;
  const workflowInputsConfiguredKeys = (() => {
    const historyKeys = asStringList(selectedDeployHistoryRecord.workflow_inputs_configured_keys);
    if (historyKeys.length > 0) {
      return historyKeys;
    }
    return asStringList(deployReadiness.last_workflow_inputs_configured_keys);
  })();
  const workflowInputsSentKeys = (() => {
    const historyKeys = asStringList(selectedDeployHistoryRecord.workflow_inputs_sent_keys);
    if (historyKeys.length > 0) {
      return historyKeys;
    }
    return asStringList(deployReadiness.last_workflow_inputs_sent_keys);
  })();
  const workflowRunLookupAttempted =
    asBooleanOrNull(selectedDeployHistoryRecord.workflow_run_lookup_attempted) ??
    asBooleanOrNull(deployReadiness.last_workflow_run_lookup_attempted);
  const workflowRunFound =
    asBooleanOrNull(selectedDeployHistoryRecord.workflow_run_found) ??
    asBooleanOrNull(deployReadiness.last_workflow_run_found);
  const workflowJobFailureDetected =
    asBooleanOrNull(selectedDeployHistoryRecord.workflow_job_failure_detected) ??
    asBooleanOrNull(deployReadiness.last_workflow_job_failure_detected);
  const postDispatchState =
    asStringOrNull(selectedDeployHistoryRecord.post_dispatch_state) ||
    asStringOrNull(deployReadiness.last_post_dispatch_state);
  const postConformanceStageFromSelected = asStringOrNull(selectedDeployHistoryRecord.post_conformance_stage);
  const postConformanceStageFromSummary =
    asStringOrNull(deployReadiness.last_post_conformance_stage) ||
    asStringOrNull(migrationDiagnostics.last_deploy_post_conformance_stage);
  const postConformanceStage = postConformanceStageFromSelected || postConformanceStageFromSummary;
  const postConformanceReasonTextFromSelected = asStringOrNull(
    selectedDeployHistoryRecord.post_conformance_reason_text,
  );
  const postConformanceReasonTextFromSummary =
    asStringOrNull(deployReadiness.last_post_conformance_reason_text) ||
    asStringOrNull(migrationDiagnostics.last_deploy_post_conformance_reason_text);
  const postConformanceReasonText = postConformanceReasonTextFromSelected || postConformanceReasonTextFromSummary;
  const postConformanceGuidanceFromSelected = asStringOrNull(
    selectedDeployHistoryRecord.post_conformance_remediation_message,
  );
  const postConformanceGuidanceFromSummary =
    asStringOrNull(deployReadiness.last_post_conformance_remediation_message) ||
    asStringOrNull(migrationDiagnostics.last_deploy_post_conformance_remediation_message);
  const postConformanceGuidance = postConformanceGuidanceFromSelected || postConformanceGuidanceFromSummary;
  const expectedWorkflowOutputs = (() => {
    const historyKeys = asStringList(selectedDeployHistoryRecord.expected_workflow_outputs);
    if (historyKeys.length > 0) {
      return historyKeys;
    }
    const readinessKeys = asStringList(deployReadiness.expected_workflow_outputs);
    if (readinessKeys.length > 0) {
      return readinessKeys;
    }
    return ["resolved_live_url", "live_url", "deployed_url"];
  })();
  const deployEvidenceContractStatus =
    asStringOrNull(selectedDeployHistoryRecord.deploy_evidence_contract_status) ||
    asStringOrNull(deployReadiness.last_deploy_evidence_contract_status);
  const deployEvidenceContractReasons = (() => {
    const historyReasons = asStringList(selectedDeployHistoryRecord.deploy_evidence_contract_reasons);
    if (historyReasons.length > 0) {
      return historyReasons;
    }
    return asStringList(deployReadiness.last_deploy_evidence_contract_reasons);
  })();
  const workflowContractAdvisory =
    asStringOrNull(selectedDeployHistoryRecord.workflow_contract_advisory) ||
    asStringOrNull(deployReadiness.last_workflow_contract_advisory);
  const workflowRunId = (() => {
    const fromHistory = selectedDeployHistoryRecord.workflow_run_id;
    if (typeof fromHistory === "number" && Number.isFinite(fromHistory)) {
      return String(Math.trunc(fromHistory));
    }
    const fromReadiness = deployReadiness.last_workflow_run_id;
    if (typeof fromReadiness === "number" && Number.isFinite(fromReadiness)) {
      return String(Math.trunc(fromReadiness));
    }
    return asStringOrNull(fromHistory) || asStringOrNull(fromReadiness);
  })();
  const workflowRunStatus =
    asStringOrNull(selectedDeployHistoryRecord.workflow_run_status) ||
    asStringOrNull(deployReadiness.last_workflow_run_status);
  const workflowRunConclusion =
    asStringOrNull(selectedDeployHistoryRecord.workflow_run_conclusion) ||
    asStringOrNull(deployReadiness.last_workflow_run_conclusion);
  const deployRunFailureReasonCodeFromSelected = asStringOrNull(
    selectedDeployHistoryRecord.workflow_run_failure_reason_code,
  );
  const deployRunFailureReasonCodeFromSummary = asStringOrNull(
    deployReadiness.last_workflow_run_failure_reason_code,
  );
  const deployRunFailureReasonCode =
    deployRunFailureReasonCodeFromSelected || deployRunFailureReasonCodeFromSummary;
  const deployRunFailureStageFromSelected = asStringOrNull(selectedDeployHistoryRecord.workflow_run_failure_stage);
  const deployRunFailureStageFromSummary = asStringOrNull(deployReadiness.last_workflow_run_failure_stage);
  const deployRunFailureStage = deployRunFailureStageFromSelected || deployRunFailureStageFromSummary;
  const deployRunFailureStepFromSelected = asStringOrNull(selectedDeployHistoryRecord.workflow_run_failure_step);
  const deployRunFailureStepFromSummary = asStringOrNull(deployReadiness.last_workflow_run_failure_step);
  const deployRunFailureStep = deployRunFailureStepFromSelected || deployRunFailureStepFromSummary;
  const deployRunFailureHintFromSelected = asStringOrNull(selectedDeployHistoryRecord.workflow_run_failure_hint);
  const deployRunFailureHintFromSummary = asStringOrNull(deployReadiness.last_workflow_run_failure_hint);
  const deployRunFailureHint = deployRunFailureHintFromSelected || deployRunFailureHintFromSummary;
  const deployFailureReasonCodeFromSelected = asStringOrNull(selectedDeployHistoryRecord.failure_reason);
  const deployFailureReasonCodeFromSummary =
    asStringOrNull(deployReadiness.last_failure_reason) ||
    asStringOrNull(migrationDiagnostics.last_deploy_failure_reason);
  const deployFailureReasonCode = deployFailureReasonCodeFromSelected || deployFailureReasonCodeFromSummary;
  const deployFailureStageFromSelected =
    asStringOrNull(selectedDeployHistoryRecord.failure_stage) ||
    asStringOrNull(selectedDeployHistoryRecord.dispatch_result_stage);
  const deployFailureStageFromSummary =
    asStringOrNull(deployReadiness.last_failure_stage) ||
    asStringOrNull(migrationDiagnostics.last_deploy_failure_stage);
  const deployFailureStage = deployFailureStageFromSelected || deployFailureStageFromSummary;
  const deployWorkflowExistsFromSelected = asBooleanOrNull(selectedDeployHistoryRecord.workflow_exists);
  const deployWorkflowExistsFromSummary =
    asBooleanOrNull(deployReadiness.last_failure_workflow_exists) ??
    asBooleanOrNull(deployReadiness.last_workflow_exists);
  const deployWorkflowExists = deployWorkflowExistsFromSelected ?? deployWorkflowExistsFromSummary;
  const deployFailureRemediationHintFromSelected = asStringOrNull(selectedDeployHistoryRecord.failure_remediation_hint);
  const deployFailureRemediationHintFromSummary =
    asStringOrNull(deployReadiness.last_failure_remediation_hint) ||
    asStringOrNull(migrationDiagnostics.last_deploy_failure_remediation_hint);
  const deployFailureRemediationHint =
    deployFailureRemediationHintFromSelected || deployFailureRemediationHintFromSummary;
  const deployFailureRemediationHintDisplay = managedGkeConfigGuidance ? null : deployFailureRemediationHint;
  const deploymentRolledOutFromSelected =
    asBooleanOrNull(selectedDeployHistoryRecord.deployment_rolled_out) ??
    asBooleanOrNull(selectedDeployHistoryRecord.rollout_verified);
  const deploymentRolledOutFromSummary =
    asBooleanOrNull(deployReadiness.deployment_rolled_out) ?? asBooleanOrNull(deployReadiness.rollout_verified);
  const deploymentRolledOut = deploymentRolledOutFromSelected ?? deploymentRolledOutFromSummary;
  const serviceHasReadyEndpointsFromSelected =
    asBooleanOrNull(selectedDeployHistoryRecord.service_has_ready_endpoints) ??
    asBooleanOrNull(selectedDeployHistoryRecord.service_ready_endpoints);
  const serviceHasReadyEndpointsFromSummary =
    asBooleanOrNull(deployReadiness.service_has_ready_endpoints) ??
    asBooleanOrNull(deployReadiness.service_ready_endpoints);
  const serviceHasReadyEndpoints = serviceHasReadyEndpointsFromSelected ?? serviceHasReadyEndpointsFromSummary;
  const backendHealthHealthyFromSelected =
    asBooleanOrNull(selectedDeployHistoryRecord.gce_backend_healthy) ??
    asBooleanOrNull(selectedDeployHistoryRecord.backend_healthy);
  const backendHealthHealthyFromSummary =
    asBooleanOrNull(deployReadiness.gce_backend_healthy) ?? asBooleanOrNull(deployReadiness.backend_healthy);
  const backendHealthHealthy = backendHealthHealthyFromSelected ?? backendHealthHealthyFromSummary;
  const gceBackendHealthStatus =
    asStringOrNull(selectedDeployHistoryRecord.gce_backend_health_status) ||
    asStringOrNull(deployReadiness.gce_backend_health_status);
  const previewHttpsStatus =
    asNumberOrNull(selectedDeployHistoryRecord.preview_https_status) ?? asNumberOrNull(deployReadiness.preview_https_status);
  const previewHttpStatus =
    asNumberOrNull(selectedDeployHistoryRecord.preview_http_status) ?? asNumberOrNull(deployReadiness.preview_http_status);
  const previewProbeAttempt =
    asNumberOrNull(selectedDeployHistoryRecord.preview_probe_attempt) ??
    asNumberOrNull(deployReadiness.preview_probe_attempt);
  const previewProbeElapsedSeconds =
    asNumberOrNull(selectedDeployHistoryRecord.preview_probe_elapsed_seconds) ??
    asNumberOrNull(deployReadiness.preview_probe_elapsed_seconds);
  const serviceProbeStatus =
    asStringOrNull(selectedDeployHistoryRecord.service_probe_status) ||
    asStringOrNull(deployReadiness.service_probe_status);
  const endpointProbeStatus =
    asStringOrNull(selectedDeployHistoryRecord.endpoint_probe_status) ||
    asStringOrNull(deployReadiness.endpoint_probe_status);
  const runtimeProbeStatus =
    asStringOrNull(selectedDeployHistoryRecord.runtime_probe_status) ||
    asStringOrNull(deployReadiness.runtime_probe_status);
  const inClusterServiceStatusCode =
    asNumberOrNull(selectedDeployHistoryRecord.in_cluster_service_status_code) ??
    asNumberOrNull(deployReadiness.in_cluster_service_status_code);
  const endpointProbeStatusCode =
    asNumberOrNull(selectedDeployHistoryRecord.endpoint_probe_status_code) ??
    asNumberOrNull(deployReadiness.endpoint_probe_status_code);
  const podRestartDetected =
    asBooleanOrNull(selectedDeployHistoryRecord.pod_restart_detected) ??
    asBooleanOrNull(deployReadiness.pod_restart_detected);
  const currentLiveUrl = asStringOrNull(deployReadiness.current_live_url);
  const currentHostReachable = asBooleanOrNull(deployReadiness.current_host_reachable);
  const currentHostReachabilityScheme = asStringOrNull(deployReadiness.current_host_reachability_scheme);
  const currentDeployHttpsReady = asBooleanOrNull(deployReadiness.current_deploy_https_ready);
  const currentCertIdentityValid = asBooleanOrNull(deployReadiness.current_cert_identity_valid);
  const currentHttpsProbeStatusCode = (() => {
    const value = deployReadiness.current_https_probe_status_code;
    return typeof value === "number" && Number.isFinite(value) ? Math.round(value) : null;
  })();
  const currentHttpsProbeErrorSummary = asStringOrNull(deployReadiness.current_https_probe_error_summary);
  const currentLiveEvidenceCheckedAt = asStringOrNull(deployReadiness.current_live_evidence_checked_at);
  const currentLiveEvidenceSource = asStringOrNull(deployReadiness.current_live_evidence_source);
  const currentLiveRuntimeStatus = asStringOrNull(deployReadiness.current_live_runtime_status);
  const currentLiveRuntimeSource = asStringOrNull(deployReadiness.current_live_runtime_source) || currentLiveEvidenceSource;
  const currentLiveRuntimeNote = asStringOrNull(deployReadiness.current_live_runtime_note);
  const selectedWorkflowAttemptStatus =
    asStringOrNull(deployReadiness.selected_workflow_attempt_status) || workflowRunStatus;
  const selectedWorkflowAttemptConclusion =
    asStringOrNull(deployReadiness.selected_workflow_attempt_conclusion) || workflowRunConclusion;
  const selectedWorkflowFailedStep =
    asStringOrNull(deployReadiness.selected_workflow_failed_step) || deployRunFailureStep;
  const selectedWorkflowFailureStage =
    asStringOrNull(deployReadiness.selected_workflow_failure_stage) || deployRunFailureStage;
  const selectedWorkflowFailureReason =
    asStringOrNull(deployReadiness.selected_workflow_failure_reason) || deployRunFailureReasonCode;
  const selectedWorkflowAttemptFailed = Boolean(
    (selectedWorkflowAttemptStatus || "").trim().toLowerCase() === "completed" &&
      (selectedWorkflowAttemptConclusion || "").trim().toLowerCase() !== "success" &&
      (selectedWorkflowAttemptConclusion || "").trim().length > 0,
  );
  const currentLiveEvidenceHealthy = currentDeployHttpsReady === true;
  const currentLiveHealthySelectedWorkflowFailureNote =
    currentLiveRuntimeNote ||
    (currentLiveEvidenceHealthy && selectedWorkflowAttemptFailed
      ? "Selected deploy workflow failed during evidence collection, but current live HTTPS evidence is healthy."
      : null);
  const dnsRecordMatchesIngressFromSelected = asBooleanOrNull(selectedDeployHistoryRecord.dns_record_matches_ingress);
  const dnsRecordMatchesIngressFromSummary = asBooleanOrNull(deployReadiness.dns_record_matches_ingress);
  const dnsRecordMatchesIngress = dnsRecordMatchesIngressFromSelected ?? dnsRecordMatchesIngressFromSummary;
  const dnsExpectedIpFromSelected = asStringOrNull(selectedDeployHistoryRecord.dns_expected_ip);
  const dnsExpectedIpFromSummary = asStringOrNull(deployReadiness.dns_expected_ip);
  const dnsExpectedIp = dnsExpectedIpFromSelected || dnsExpectedIpFromSummary;
  const dnsObservedIpFromSelected = asStringOrNull(selectedDeployHistoryRecord.dns_observed_ip);
  const dnsObservedIpFromSummary = asStringOrNull(deployReadiness.dns_observed_ip);
  const dnsObservedIp = dnsObservedIpFromSelected || dnsObservedIpFromSummary;
  const expectedStaticIpAddressFromSelected = asStringOrNull(selectedDeployHistoryRecord.expected_static_ip_address);
  const expectedStaticIpAddressFromSummary = asStringOrNull(deployReadiness.expected_static_ip_address);
  const expectedStaticIpAddress = expectedStaticIpAddressFromSelected || expectedStaticIpAddressFromSummary;
  const staticIpStatusFromSelected = asStringOrNull(selectedDeployHistoryRecord.static_ip_status);
  const staticIpStatusFromSummary = asStringOrNull(deployReadiness.static_ip_status);
  const staticIpStatus = staticIpStatusFromSelected || staticIpStatusFromSummary;
  const staticIpUsersFromSelected = asStringOrNull(selectedDeployHistoryRecord.static_ip_users);
  const staticIpUsersFromSummary = asStringOrNull(deployReadiness.static_ip_users);
  const staticIpUsers = staticIpUsersFromSelected || staticIpUsersFromSummary;
  const tlsCertificateStatusFromSelected = asStringOrNull(selectedDeployHistoryRecord.tls_certificate_status);
  const tlsCertificateStatusFromSummary = asStringOrNull(deployReadiness.tls_certificate_status);
  const tlsCertificateStatus = tlsCertificateStatusFromSelected || tlsCertificateStatusFromSummary;
  const tlsDomainStatusFromSelected = asStringOrNull(selectedDeployHistoryRecord.tls_domain_status);
  const tlsDomainStatusFromSummary = asStringOrNull(deployReadiness.tls_domain_status);
  const tlsDomainStatus = tlsDomainStatusFromSelected || tlsDomainStatusFromSummary;
  const observedManagedCertificateDomainsFromSelected = asStringOrNull(
    selectedDeployHistoryRecord.observed_managed_certificate_domains,
  );
  const observedManagedCertificateDomainsFromSummary = asStringOrNull(
    deployReadiness.observed_managed_certificate_domains,
  );
  const observedManagedCertificateDomains =
    observedManagedCertificateDomainsFromSelected || observedManagedCertificateDomainsFromSummary;
  const observedManagedCertificateStatusFromSelected = asStringOrNull(
    selectedDeployHistoryRecord.observed_managed_certificate_status,
  );
  const observedManagedCertificateStatusFromSummary = asStringOrNull(
    deployReadiness.observed_managed_certificate_status,
  );
  const observedManagedCertificateStatus =
    observedManagedCertificateStatusFromSelected || observedManagedCertificateStatusFromSummary;
  const observedManagedCertificateDomainStatusFromSelected = asStringOrNull(
    selectedDeployHistoryRecord.observed_managed_certificate_domain_status,
  );
  const observedManagedCertificateDomainStatusFromSummary = asStringOrNull(
    deployReadiness.observed_managed_certificate_domain_status,
  );
  const observedManagedCertificateDomainStatus =
    observedManagedCertificateDomainStatusFromSelected || observedManagedCertificateDomainStatusFromSummary;
  const ingressIpFromSelected = asStringOrNull(selectedDeployHistoryRecord.ingress_ip);
  const ingressIpFromSummary = asStringOrNull(deployReadiness.ingress_ip);
  const ingressIp = ingressIpFromSelected || ingressIpFromSummary;
  const ingressStatusIpFromSelected = asStringOrNull(selectedDeployHistoryRecord.ingress_status_ip);
  const ingressStatusIpFromSummary = asStringOrNull(deployReadiness.ingress_status_ip);
  const ingressStatusIp = ingressStatusIpFromSelected || ingressStatusIpFromSummary;
  const ingressStatusIpMatchesStaticIpFromSelected = asBooleanOrNull(
    selectedDeployHistoryRecord.ingress_status_ip_matches_static_ip,
  );
  const ingressStatusIpMatchesStaticIpFromSummary = asBooleanOrNull(deployReadiness.ingress_status_ip_matches_static_ip);
  const ingressStatusIpMatchesStaticIp =
    ingressStatusIpMatchesStaticIpFromSelected ?? ingressStatusIpMatchesStaticIpFromSummary;
  const staticIpBoundToExpectedForwardingRuleFromSelected = asBooleanOrNull(
    selectedDeployHistoryRecord.static_ip_bound_to_expected_forwarding_rule,
  );
  const staticIpBoundToExpectedForwardingRuleFromSummary = asBooleanOrNull(
    deployReadiness.static_ip_bound_to_expected_forwarding_rule,
  );
  const staticIpBoundToExpectedForwardingRule =
    staticIpBoundToExpectedForwardingRuleFromSelected ?? staticIpBoundToExpectedForwardingRuleFromSummary;
  const ingressConflictDetectedFromSelected = asBooleanOrNull(selectedDeployHistoryRecord.ingress_conflict_detected);
  const ingressConflictDetectedFromSummary = asBooleanOrNull(deployReadiness.ingress_conflict_detected);
  const ingressConflictDetected = ingressConflictDetectedFromSelected ?? ingressConflictDetectedFromSummary;
  const certIdentityValidFromSelected = asBooleanOrNull(selectedDeployHistoryRecord.cert_identity_valid);
  const certIdentityValidFromSummary = asBooleanOrNull(deployReadiness.cert_identity_valid);
  const certIdentityValid = currentCertIdentityValid ?? certIdentityValidFromSelected ?? certIdentityValidFromSummary;
  const deployHttpsReadyFromSelected = asBooleanOrNull(selectedDeployHistoryRecord.deploy_https_ready);
  const deployHttpsReadyFromSummary = asBooleanOrNull(deployReadiness.deploy_https_ready);
  const deployHttpsReady = currentDeployHttpsReady ?? deployHttpsReadyFromSelected ?? deployHttpsReadyFromSummary;
  const workflowIntegrityStatusFromSelected = asStringOrNull(selectedDeployHistoryRecord.workflow_integrity_status);
  const workflowIntegrityStatusFromSummary = asStringOrNull(deployReadiness.workflow_integrity_status);
  const workflowIntegrityStatus =
    ((workflowIntegrityStatusFromSelected || workflowIntegrityStatusFromSummary || "").trim().toLowerCase() || null);
  const workflowIntegrityReasonCodeFromSelected = asStringOrNull(
    selectedDeployHistoryRecord.workflow_integrity_reason_code,
  );
  const workflowIntegrityReasonCodeFromSummary = asStringOrNull(deployReadiness.workflow_integrity_reason_code);
  const workflowIntegrityReasonCode =
    ((workflowIntegrityReasonCodeFromSelected || workflowIntegrityReasonCodeFromSummary || "").trim().toLowerCase() ||
      null);
  const normalizedDispatchServiceReasonCode = (dispatchServiceReasonCode || "").trim().toLowerCase();
  const normalizedDeployFailureReasonCode = (deployFailureReasonCode || "").trim().toLowerCase();
  const normalizedDeployRunFailureReasonCode = (deployRunFailureReasonCode || "").trim().toLowerCase();
  const normalizedDeployRunFailureStage = (deployRunFailureStage || "").trim().toLowerCase();
  const normalizedPostConformanceStage = (postConformanceStage || "").trim().toLowerCase();
  const normalizedTlsCertificateStatus = normalizeUpperOrNull(tlsCertificateStatus);
  const normalizedTlsDomainStatus = normalizeUpperOrNull(tlsDomainStatus);
  const suppressHistoricalDeployFailureReasons = currentLiveEvidenceHealthy && selectedWorkflowAttemptFailed;
  const deployConsistencyReasonCodeSet = new Set(
    [normalizedDispatchServiceReasonCode, normalizedDeployFailureReasonCode, normalizedDeployRunFailureReasonCode]
      .map((value) => value.trim())
      .filter((value) => value.length > 0),
  );
  const hasDeployConsistencyReasonCode = (code: string): boolean =>
    suppressHistoricalDeployFailureReasons ? false : deployConsistencyReasonCodeSet.has(code);
  const dnsMismatchReasonCodes = new Set([
    "dns_record_mismatch",
    "dns_points_to_old_ingress_ip",
    "ingress_ip_assigned_but_dns_not_updated",
  ]);
  const serviceEndpointReasonCodes = new Set([
    "service_has_no_ready_endpoints",
    "service_endpoint_missing",
    "service_endpoint_unhealthy",
    "in_cluster_service_curl_failed",
    "in_cluster_service_curl_failed_after_retries",
  ]);
  const backendHealthReasonCodes = new Set([
    "backendconfig_health_check_mismatch",
    "backend_config_healthcheck_unhealthy",
    "ingress_backend_unhealthy",
    "ingress_backend_502",
    "pod_ready_but_ingress_backend_unhealthy",
    "ingress_backend_unhealthy_after_rollout",
  ]);
  const certIdentityMismatchReasonCodes = new Set([
    "certificate_domain_mismatch",
    "tls_certificate_bound_to_wrong_site",
    "stale_managed_certificate_present",
    "managed_certificate_identity_mismatch",
    "ingress_certificate_mismatch",
    "ingress_certificate_annotation_mismatch",
    "stale_pre_shared_cert_binding_detected",
    "reachable_but_tls_certificate_mismatch",
  ]);
  const ingressConflictReasonCodes = new Set([
    "ingress_static_ip_conflict",
    "shared_static_ip_not_allowed_for_per_site_ingress",
    "stale_pre_shared_cert_binding_detected",
  ]);
  const hasDnsMismatchReason = Array.from(dnsMismatchReasonCodes).some((code) => hasDeployConsistencyReasonCode(code));
  const hasServiceEndpointReason = Array.from(serviceEndpointReasonCodes).some((code) => hasDeployConsistencyReasonCode(code));
  const hasBackendHealthReason = Array.from(backendHealthReasonCodes).some((code) => hasDeployConsistencyReasonCode(code));
  const hasCertIdentityMismatchReason = Array.from(certIdentityMismatchReasonCodes).some((code) =>
    hasDeployConsistencyReasonCode(code),
  );
  const hasIngressConflictReason = Array.from(ingressConflictReasonCodes).some((code) =>
    hasDeployConsistencyReasonCode(code),
  );
  const tlsFailedNotVisible =
    normalizedTlsCertificateStatus === "FAILED_NOT_VISIBLE" ||
    normalizedTlsDomainStatus === "FAILED_NOT_VISIBLE" ||
    hasDeployConsistencyReasonCode("managed_certificate_failed_not_visible");
  const tlsProvisioning =
    normalizedTlsCertificateStatus === "PROVISIONING" ||
    normalizedTlsDomainStatus === "PROVISIONING" ||
    hasDeployConsistencyReasonCode("tls_certificate_provisioning");
  const deployWorkflowConvergencePending =
    isPendingWorkflowRunStatus(workflowRunStatus) ||
    normalizedPostConformanceStage === "workflow_dispatch_attempted" ||
    normalizedPostConformanceStage === "workflow_dispatch_succeeded_waiting_for_run" ||
    (dispatchAttempted === true && workflowRunFound === false);
  const deploymentRolloutGateStatus: DeployConsistencyGateStatus = (() => {
    if (deploymentRolledOut === true || deployHttpsReady === true) {
      return "pass";
    }
    if (
      deploymentRolledOut === false ||
      normalizedDeployRunFailureStage === "rollout_verify" ||
      hasDeployConsistencyReasonCode("rollout_verification_failed")
    ) {
      return "blocked";
    }
    if (deployWorkflowConvergencePending) {
      return "pending";
    }
    return "unknown";
  })();
  const serviceEndpointsGateStatus: DeployConsistencyGateStatus = (() => {
    if (serviceHasReadyEndpoints === true || deployHttpsReady === true) {
      return "pass";
    }
    if (serviceHasReadyEndpoints === false || hasServiceEndpointReason) {
      return "blocked";
    }
    if (deployWorkflowConvergencePending) {
      return "pending";
    }
    return "unknown";
  })();
  const backendHealthGateStatus: DeployConsistencyGateStatus = (() => {
    if (backendHealthHealthy === true || deployHttpsReady === true) {
      return "pass";
    }
    if (backendHealthHealthy === false || hasBackendHealthReason) {
      return "blocked";
    }
    if (
      deployWorkflowConvergencePending ||
      hasDeployConsistencyReasonCode("service_probe_waiting_for_convergence") ||
      hasDeployConsistencyReasonCode("ingress_neg_convergence_pending")
    ) {
      return "pending";
    }
    return "unknown";
  })();
  const dnsMatchesIngressGateStatus: DeployConsistencyGateStatus = (() => {
    if (currentLiveEvidenceHealthy) {
      return "pass";
    }
    if (dnsRecordMatchesIngress === true) {
      return "pass";
    }
    if (dnsRecordMatchesIngress === false || hasDnsMismatchReason) {
      return "blocked";
    }
    if (ingressIp || dnsExpectedIp) {
      return "pending";
    }
    return "unknown";
  })();
  const managedCertificateActiveGateStatus: DeployConsistencyGateStatus = (() => {
    if (deployHttpsReady === true || (normalizedTlsCertificateStatus === "ACTIVE" && normalizedTlsDomainStatus === "ACTIVE")) {
      return "pass";
    }
    if (tlsFailedNotVisible) {
      return "blocked";
    }
    if (tlsProvisioning) {
      return "pending";
    }
    if (normalizedTlsCertificateStatus || normalizedTlsDomainStatus) {
      return "blocked";
    }
    return "unknown";
  })();
  const certificateIdentityGateStatus: DeployConsistencyGateStatus = (() => {
    if (certIdentityValid === true || deployHttpsReady === true) {
      return "pass";
    }
    if (certIdentityValid === false || hasCertIdentityMismatchReason) {
      return "blocked";
    }
    if (tlsProvisioning) {
      return "pending";
    }
    return "unknown";
  })();
  const ingressConflictGateStatus: DeployConsistencyGateStatus = (() => {
    if (currentLiveEvidenceHealthy) {
      return "pass";
    }
    if (ingressConflictDetected === true || hasIngressConflictReason) {
      return "blocked";
    }
    if (ingressConflictDetected === false || deployHttpsReady === true) {
      return "pass";
    }
    if (deployWorkflowConvergencePending) {
      return "pending";
    }
    return "unknown";
  })();
  const httpsProbeGateStatus: DeployConsistencyGateStatus = (() => {
    if (deployHttpsReady === true) {
      return "pass";
    }
    if (deployHttpsReady === false) {
      if (tlsProvisioning) {
        return "pending";
      }
      return "blocked";
    }
    if (deployWorkflowConvergencePending || tlsProvisioning || dnsMatchesIngressGateStatus === "pending") {
      return "pending";
    }
    return "unknown";
  })();
  const workflowIntegrityGateStatus: DeployConsistencyGateStatus = (() => {
    if (workflowIntegrityStatus === "match") {
      return "pass";
    }
    if (workflowIntegrityStatus === "mismatch") {
      return "warning";
    }
    if (workflowIntegrityStatus === "missing") {
      return "unknown";
    }
    return "unknown";
  })();
  const deployConsistencyRemediationHints = (() => {
    const hints = new Set<string>();
    if (dnsMatchesIngressGateStatus === "blocked") {
      hints.add("DNS mismatch: update DNS A record to the observed ingress IP.");
    }
    if (tlsFailedNotVisible) {
      hints.add("FAILED_NOT_VISIBLE: DNS is not visible to Google certificate validation yet.");
    }
    if (tlsProvisioning && httpsProbeGateStatus !== "pass") {
      hints.add("TLS provisioning pending: wait for ManagedCertificate status ACTIVE, then refresh/retry deploy.");
    }
    if (certificateIdentityGateStatus === "blocked" && hasCertIdentityMismatchReason) {
      hints.add("Cert bound to wrong site: certificate identity mismatch or stale binding detected.");
    }
    if (ingressConflictGateStatus === "blocked") {
      hints.add("Ingress conflict: static IP or ingress ownership conflict detected.");
    }
    if (httpsProbeGateStatus === "blocked") {
      hints.add("HTTPS not ready: wait for DNS/TLS/LB convergence or inspect deploy evidence.");
    }
    if (
      workflowIntegrityGateStatus === "warning" ||
      workflowIntegrityReasonCode === "managed_workflow_signature_mismatch"
    ) {
      hints.add(
        "Workflow has been modified outside managed template; behavior may differ from expected deploy contract.",
      );
    }
    return Array.from(hints);
  })();
  const deployDiagnosticsUsingSummaryFallback =
    hasSelectedDeployAttempt &&
    ((!deployFailureCategoryFromSelected && !!deployFailureCategoryFromSummary) ||
      (!deployFailureReasonCodeFromSelected && !!deployFailureReasonCodeFromSummary) ||
      (!deployFailureStageFromSelected && !!deployFailureStageFromSummary) ||
      (!deployWorkflowIdentifierRequestedFromSelected && !!deployWorkflowIdentifierRequestedFromSummary) ||
      (!deployWorkflowFilePathFromSelected && !!deployWorkflowFilePathFromSummary) ||
      (!deployWorkflowDispatchResolutionSourceFromSelected && !!deployWorkflowDispatchResolutionSourceFromSummary) ||
      (!dispatchServiceReasonCodeFromSelected && !!dispatchServiceReasonCodeFromSummary) ||
      (!workflowConformanceStatusFromSelected && !!workflowConformanceStatusFromSummary) ||
      (deployWorkflowExistsFromSelected === null && deployWorkflowExistsFromSummary !== null) ||
      (!deployFailureRemediationHintFromSelected && !!deployFailureRemediationHintFromSummary) ||
      (!deployRunFailureReasonCodeFromSelected && !!deployRunFailureReasonCodeFromSummary) ||
      (!deployRunFailureStageFromSelected && !!deployRunFailureStageFromSummary) ||
      (!deployRunFailureStepFromSelected && !!deployRunFailureStepFromSummary) ||
      (!deployRunFailureHintFromSelected && !!deployRunFailureHintFromSummary) ||
      (!postConformanceStageFromSelected && !!postConformanceStageFromSummary) ||
      (!postConformanceReasonTextFromSelected && !!postConformanceReasonTextFromSummary) ||
      (!postConformanceGuidanceFromSelected && !!postConformanceGuidanceFromSummary) ||
      (deploymentRolledOutFromSelected === null && deploymentRolledOutFromSummary !== null) ||
      (serviceHasReadyEndpointsFromSelected === null && serviceHasReadyEndpointsFromSummary !== null) ||
      (backendHealthHealthyFromSelected === null && backendHealthHealthyFromSummary !== null) ||
      (dnsRecordMatchesIngressFromSelected === null && dnsRecordMatchesIngressFromSummary !== null) ||
      (!dnsExpectedIpFromSelected && !!dnsExpectedIpFromSummary) ||
      (!dnsObservedIpFromSelected && !!dnsObservedIpFromSummary) ||
      (!tlsCertificateStatusFromSelected && !!tlsCertificateStatusFromSummary) ||
      (!tlsDomainStatusFromSelected && !!tlsDomainStatusFromSummary) ||
      (!ingressIpFromSelected && !!ingressIpFromSummary) ||
      (ingressConflictDetectedFromSelected === null && ingressConflictDetectedFromSummary !== null) ||
      (certIdentityValidFromSelected === null && certIdentityValidFromSummary !== null) ||
      (deployHttpsReadyFromSelected === null && deployHttpsReadyFromSummary !== null) ||
      (!workflowIntegrityStatusFromSelected && !!workflowIntegrityStatusFromSummary) ||
      (!workflowIntegrityReasonCodeFromSelected && !!workflowIntegrityReasonCodeFromSummary));
  const draftReadiness = parseDraftReadiness(contextSummary, draftReadinessSnapshot);
  const draftProviderCompatibility = parseDraftProviderCompatibility(contextSummary, migrationDiagnostics);
  const draftGenerationState = parseDraftGenerationState({
    contextSummary,
    draftReadiness,
    draftProviderCompatibility,
    migrationDiagnostics,
  });
  const draftAIExecution = parseDraftAIExecutionSummary(contextSummary, migrationDiagnostics);
  const generationSafetyProfile =
    asStringOrNull(draftInputSummary.generation_safety_profile)
    || draftAIExecution.preflightMode
    || asStringOrNull(draftInputSummary.generation_preflight_mode)
    || "compact_fallback";
  const generationProviderTimeoutSeconds =
    asNonNegativeInt(draftInputSummary.generation_provider_timeout_seconds)
    ?? draftAIExecution.timeoutSeconds
    ?? null;
  const generationPreflightMode =
    asStringOrNull(draftInputSummary.generation_preflight_mode)
    || draftAIExecution.preflightMode
    || generationSafetyProfile;
  const generationMaxFinalInputChars =
    asNonNegativeInt(draftInputSummary.generation_max_final_input_chars)
    ?? draftAIExecution.maxFinalInputChars
    ?? null;
  const generationMaxDifficultyScore =
    asNonNegativeInt(draftInputSummary.generation_max_difficulty_score)
    ?? draftAIExecution.maxDifficultyScore
    ?? null;
  const generationCompactPageLimit =
    asNonNegativeInt(draftInputSummary.generation_compact_page_limit)
    ?? null;
  const generationCompactMediaAssetLimit =
    asNonNegativeInt(draftInputSummary.generation_compact_media_asset_limit)
    ?? null;
  const generationCompactRecommendationLimit =
    asNonNegativeInt(draftInputSummary.generation_compact_recommendation_limit)
    ?? null;
  const generationCompactFallbackEnabled =
    asBooleanOrNull(draftInputSummary.generation_compact_fallback_enabled)
    ?? true;
  const generationCompactFallbackAttempted =
    asBooleanOrNull(draftInputSummary.generation_compact_fallback_attempted)
    ?? draftAIExecution.compactFallbackAttempted;
  const generationBudgetCapped =
    asBooleanOrNull(draftInputSummary.generation_budget_capped)
    ?? draftAIExecution.budgetCapped;
  const generationPreflightBlocked =
    asBooleanOrNull(draftInputSummary.generation_preflight_blocked)
    ?? draftAIExecution.preflightBlocked;
  const generationPreflightBlockReason =
    asStringOrNull(draftInputSummary.generation_preflight_block_reason)
    || draftAIExecution.preflightBlockReason;
  const generationPreflightBlockedSetting =
    asStringOrNull(draftInputSummary.generation_preflight_blocked_setting)
    || draftAIExecution.preflightBlockedSetting;
  const generationPreflightBlockedSettingActual =
    asNonNegativeInt(draftInputSummary.generation_preflight_blocked_setting_actual)
    ?? draftAIExecution.preflightBlockedSettingActual
    ?? null;
  const generationPreflightBlockedSettingCap =
    asNonNegativeInt(draftInputSummary.generation_preflight_blocked_setting_cap)
    ?? draftAIExecution.preflightBlockedSettingCap
    ?? null;
  const generationProviderCallSkipped =
    asBooleanOrNull(draftInputSummary.generation_provider_call_skipped)
    ?? draftAIExecution.providerCallSkipped
    ?? null;
  const generationBudgetCapReason =
    asStringOrNull(draftInputSummary.generation_budget_cap_reason)
    || generationPreflightBlockReason;
  const draftFailureSourceLabel = toDraftFailureSourceLabel(
    asStringOrNull(migrationDiagnostics.last_draft_failure_source) || draftAIExecution.failureSource,
    {
      providerCallSkipped: (
        asBooleanOrNull(draftInputSummary.generation_provider_call_skipped)
        ?? draftAIExecution.providerCallSkipped
      ),
      preflightBlocked: (
        asBooleanOrNull(draftInputSummary.generation_preflight_blocked)
        ?? draftAIExecution.preflightBlocked
      ),
    },
  );
  const draftAIDiagnosticsSummary = asRecord(migrationDiagnostics.last_draft_ai_diagnostics_summary);
  const draftAIFailureCategory = asStringOrNull(draftAIDiagnosticsSummary.failure_category);
  const draftAIFailureReason = asStringOrNull(draftAIDiagnosticsSummary.failure_reason);
  const draftAIFailureSource = asStringOrNull(draftAIDiagnosticsSummary.failure_source);
  const draftAIRetryable = asBooleanOrNull(draftAIDiagnosticsSummary.retryable);
  const draftAIHint = asStringOrNull(draftAIDiagnosticsSummary.hint);
  const draftAIBudgetOutcome = asStringOrNull(draftAIDiagnosticsSummary.budget_outcome);
  const draftAIRetrySuppressed = asBooleanOrNull(draftAIDiagnosticsSummary.retry_suppressed);
  const draftProviderTimedOut =
    (asStringOrNull(migrationDiagnostics.last_draft_failure_reason) || draftAIFailureReason || "").trim().toLowerCase()
    === "timeout";
  const providerTimeoutActionMessage = draftProviderTimedOut
    ? `Provider timed out after ${
      generationProviderTimeoutSeconds !== null ? `${generationProviderTimeoutSeconds} seconds` : "the configured timeout"
    }. Next action: reduce Admin generation budget/safety thresholds or enable compact fallback.`
    : null;
  const draftAITrimmingPassCount =
    typeof draftAIDiagnosticsSummary.trimming_pass_count === "number"
      ? Math.max(0, Math.round(draftAIDiagnosticsSummary.trimming_pass_count))
      : null;
  const draftAIDifficultyBucket = asStringOrNull(draftAIDiagnosticsSummary.difficulty_bucket);
  const draftAIInputSizeBucket = asStringOrNull(draftAIDiagnosticsSummary.input_size_bucket);
  const draftAIDegradedState = asStringOrNull(draftAIDiagnosticsSummary.degraded_state);
  const draftAIContextBudgetSizeChars =
    typeof draftAIDiagnosticsSummary.context_budget_size_chars === "number"
      ? Math.max(0, Math.round(draftAIDiagnosticsSummary.context_budget_size_chars))
      : null;
  const draftAILargestContextBlock = asStringOrNull(draftAIDiagnosticsSummary.largest_context_block);
  const draftAILargestContextBlockSizeChars =
    typeof draftAIDiagnosticsSummary.largest_context_block_size_chars === "number"
      ? Math.max(0, Math.round(draftAIDiagnosticsSummary.largest_context_block_size_chars))
      : null;
  const generationBlockedReasonSummary = formatGenerationBlockedReason({
    preflightBlocked: generationPreflightBlocked,
    preflightBlockedSetting: generationPreflightBlockedSetting,
    preflightBlockedSettingActual: generationPreflightBlockedSettingActual,
    preflightBlockedSettingCap: generationPreflightBlockedSettingCap,
    preflightBlockReason: generationPreflightBlockReason,
    budgetOutcome: draftAIBudgetOutcome,
    contextBudgetSizeChars: draftAIContextBudgetSizeChars,
    hint: draftAIHint,
  });
  const generationPreflightBlockedMessage = generationPreflightBlocked
    ? `Generation was blocked before provider call.${generationPreflightBlockedSetting
      ? ` Blocked setting: ${generationPreflightBlockedSetting}${generationPreflightBlockedSettingActual !== null
        ? ` (${generationPreflightBlockedSettingActual}`
        : ""}${generationPreflightBlockedSettingCap !== null
          ? `${generationPreflightBlockedSettingActual !== null ? " / cap " : " cap "}${generationPreflightBlockedSettingCap}`
          : ""}${generationPreflightBlockedSettingActual !== null ? ")" : ""}.`
      : ""} ${generationMaxFinalInputChars !== null ? `Final input cap: ${generationMaxFinalInputChars}. ` : ""}${
        draftAILargestContextBlock
          ? `Largest included block: ${draftAILargestContextBlock}${draftAILargestContextBlockSizeChars !== null ? ` (${draftAILargestContextBlockSizeChars} chars)` : ""}. `
          : ""
      }Compact fallback attempted: ${generationCompactFallbackAttempted === true ? "Yes" : "No"}. Provider call skipped: ${generationProviderCallSkipped === false ? "No" : "Yes"}. Next action: reduce requirements or selected context, or ask Admin to increase bounded migration AI budget.`
    : null;
  const draftAuthIntegrationGuidance = toDraftAuthIntegrationGuidance(
    asStringOrNull(migrationDiagnostics.last_draft_failure_reason)
    || draftAIFailureReason
    || asStringOrNull(migrationDiagnostics.last_draft_failure_code),
  );
  const selectedArtifactFailureMessage = asStringOrNull(selectedArtifact?.error_summary);
  const draftFailureMessage = selectedArtifactFailureMessage || asStringOrNull(migrationDiagnostics.last_draft_failure_message);
  const draftDiagnosticsUsingSummaryFallback =
    Boolean(selectedArtifact) &&
    latestGeneratedArtifactId !== null &&
    selectedArtifact?.id !== latestGeneratedArtifactId &&
    !selectedArtifactFailureMessage;
  const draftContractStatus = asStringOrNull(migrationDiagnostics.last_draft_contract_status);
  const draftContractReasonCodes = asStringList(migrationDiagnostics.last_draft_contract_reason_codes);
  const draftContractWarningCodes = asStringList(migrationDiagnostics.last_draft_contract_warning_codes);
  const draftContractRetryLikelihood = asStringOrNull(migrationDiagnostics.last_draft_contract_retry_likelihood);
  const draftContractCandidateItemCount =
    typeof migrationDiagnostics.last_draft_contract_candidate_item_count === "number" &&
    Number.isFinite(migrationDiagnostics.last_draft_contract_candidate_item_count)
      ? Math.max(0, Math.round(migrationDiagnostics.last_draft_contract_candidate_item_count))
      : null;
  const draftContractNormalizedItemCount =
    typeof migrationDiagnostics.last_draft_contract_normalized_item_count === "number" &&
    Number.isFinite(migrationDiagnostics.last_draft_contract_normalized_item_count)
      ? Math.max(0, Math.round(migrationDiagnostics.last_draft_contract_normalized_item_count))
      : null;
  const draftContractDroppedItemCount =
    typeof migrationDiagnostics.last_draft_contract_dropped_item_count === "number" &&
    Number.isFinite(migrationDiagnostics.last_draft_contract_dropped_item_count)
      ? Math.max(0, Math.round(migrationDiagnostics.last_draft_contract_dropped_item_count))
      : null;
  const draftContractRequiredFilesExpected = asStringList(
    migrationDiagnostics.last_draft_contract_required_artifact_files_expected,
  );
  const draftContractRequiredFilesPresent = asStringList(
    migrationDiagnostics.last_draft_contract_required_artifact_files_present,
  );
  const draftContractMissingRequiredFiles = asStringList(
    migrationDiagnostics.last_draft_contract_missing_required_artifact_files,
  );
  const draftContractContentDensityFailuresByFile = asStringList(
    migrationDiagnostics.last_draft_contract_content_density_failures_by_file,
  );
  const draftContractParserRejectionReasonCounts = parseStringNumberMap(
    migrationDiagnostics.last_draft_contract_parser_rejection_reason_counts,
  );
  const draftContractPrimaryFileDetected = asBooleanOrNull(
    migrationDiagnostics.last_draft_contract_artifact_primary_file_detected,
  );
  const draftContractIssueFocus = deriveDraftContractIssueFocus({
    missingRequiredFiles: draftContractMissingRequiredFiles,
    densityFailuresByFile: draftContractContentDensityFailuresByFile,
    parserRejectionReasonCounts: draftContractParserRejectionReasonCounts,
    normalizedItemCount: draftContractNormalizedItemCount,
    droppedItemCount: draftContractDroppedItemCount,
  });
  const draftContractRetryGuidance = toDraftRetryLikelihoodGuidance(draftContractRetryLikelihood);
  const draftContractParserRejectionSummary = formatParserRejectionReasonCounts(
    draftContractParserRejectionReasonCounts,
  );
  const requestContractStatusLabel = toRequestContractStatusLabel(draftAIExecution.requestContractStatus);
  const aiExecutionSummaryLabel = `${
    draftAIExecution.modelUsed || draftAIExecution.modelResolved || "n/a"
  } via ${draftAIExecution.endpointPath || "n/a"}`;
  const artifactResultLabel =
    draftAIExecution.artifactResult ||
    (draftAIExecution.artifactStatus === "completed"
      ? "succeeded"
      : draftAIExecution.artifactStatus === "partial"
        ? "partial"
        : draftAIExecution.artifactStatus === "failed"
          ? "failed"
          : null);
  const requestProfileLabel = draftAIExecution.endpointPath
    ? `${draftAIExecution.endpointPath}${
        draftAIExecution.requestBodyMode ? ` (${draftAIExecution.requestBodyMode})` : ""
      }`
    : "n/a";
  const showDraftTimeout = busyAction === "generate" || draftGenerationState.status === "generation_failed";
  const draftTimeoutLabel =
    typeof draftAIExecution.timeoutSeconds === "number"
      ? `${Math.max(1, Math.round(draftAIExecution.timeoutSeconds))} seconds`
      : "n/a";
  const draftDurationLabel =
    typeof draftAIExecution.durationMs === "number" ? `${Math.max(0, Math.round(draftAIExecution.durationMs))} ms` : null;
  const draftGenerationStateLabel = toDraftGenerationStateLabel(draftGenerationState.status);
  const draftReadinessStatusLabel = toDraftReadinessStatusLabel(draftReadiness.status);
  const draftGenerationBlocked = draftReadiness.hardBlocked || !draftProviderCompatibility.supported;
  const draftReadinessToneClass =
    draftReadiness.status === "ready" ? "hint success" : draftReadiness.status === "ready_with_warnings" ? "hint warning" : "hint warning";
  const draftGenerationStateToneClass =
    draftGenerationState.status === "ready" || draftGenerationState.status === "generation_succeeded"
      ? "hint success"
      : draftGenerationState.status === "ready_with_warnings" || draftGenerationState.status === "generation_partial"
        ? "hint warning"
        : "hint warning";
  const draftGenerationBlockedMessage = draftReadiness.hardBlocked
    ? "Resolve blocking readiness items above before generating a draft."
    : "Resolve provider compatibility issues before generating a draft.";
  const draftProviderCompatibilityStatusLabel = draftProviderCompatibility.supported
    ? "Pass"
    : draftProviderCompatibility.retryable
      ? "Warning"
      : "Blocking";
  const draftProviderCompatibilityToneClass = draftProviderCompatibility.supported
    ? "hint success"
    : draftProviderCompatibility.retryable
      ? "hint warning"
      : "hint warning";
  const existingContextSummaries = asRecord(contextSummary.existing_context_summaries);
  const reusedContextSummary = asRecord(contextSummary.reused_context);
  const auditReusedContext = parseReusedContextEntry(reusedContextSummary.audit);
  const recommendationReusedContext = parseReusedContextEntry(reusedContextSummary.recommendations);
  const competitorReusedContext = parseReusedContextEntry(reusedContextSummary.competitors);
  const auditContextLabel = resolveReusedContextLabel({
    entry: auditReusedContext,
    legacyAvailable: Boolean(existingContextSummaries.audit_summary) || Boolean(contextSummary.has_audit_summary),
  });
  const recommendationContextLabel = resolveReusedContextLabel({
    entry: recommendationReusedContext,
    legacyAvailable:
      Boolean(existingContextSummaries.recommendation_summary) || Boolean(contextSummary.has_recommendation_summary),
  });
  const competitorContextLabel = resolveReusedContextLabel({
    entry: competitorReusedContext,
    legacyAvailable: Boolean(existingContextSummaries.competitor_summary) || Boolean(contextSummary.has_competitor_summary),
  });
  const auditContextStatus = resolveReusedContextStatus({
    entry: auditReusedContext,
    legacyAvailable: Boolean(existingContextSummaries.audit_summary) || Boolean(contextSummary.has_audit_summary),
  });
  const recommendationContextStatus = resolveReusedContextStatus({
    entry: recommendationReusedContext,
    legacyAvailable:
      Boolean(existingContextSummaries.recommendation_summary) || Boolean(contextSummary.has_recommendation_summary),
  });
  const competitorContextStatus = resolveReusedContextStatus({
    entry: competitorReusedContext,
    legacyAvailable: Boolean(existingContextSummaries.competitor_summary) || Boolean(contextSummary.has_competitor_summary),
  });
  const auditContextLastRun = formatContextTimestamp(auditReusedContext.timestamp);
  const recommendationContextLastRun = formatContextTimestamp(recommendationReusedContext.timestamp);
  const competitorContextLastRun = formatContextTimestamp(competitorReusedContext.timestamp);
  const latestArtifactForSummary = selectedArtifact || summary?.latest_artifact || artifactVersions[0] || null;
  const draftPreview = useMemo(
    () =>
      buildDraftPreviewEvaluation(selectedArtifact, {
        businessId,
        siteId,
      }),
    [businessId, siteId, selectedArtifact],
  );
  const previewTitleByPath = useMemo(() => {
    const titleMap = new Map<string, string>();
    const pageMap = Array.isArray(selectedArtifact?.page_map_json) ? selectedArtifact.page_map_json : [];
    for (const entry of pageMap) {
      const item = asRecord(entry);
      const path = normalizeArtifactPathForPreview(asString(item.path));
      if (!path) {
        continue;
      }
      const title = asString(item.title).trim() || asString(item.name).trim();
      if (!title || titleMap.has(path)) {
        continue;
      }
      titleMap.set(path, title);
    }
    return titleMap;
  }, [selectedArtifact]);
  const previewEntries = useMemo(
    () =>
      draftPreview.pages.map((page) => ({
        path: page.path,
        title: previewTitleByPath.get(page.path) || page.title || page.path,
      })),
    [draftPreview.pages, previewTitleByPath],
  );
  const activeDraftPreviewPage = useMemo(() => {
    if (!draftPreview.available || draftPreview.pages.length === 0) {
      return null;
    }
    const selectedPath = selectedFilePath.trim();
    if (selectedPath) {
      const selectedPage = draftPreview.pages.find((page) => page.path === selectedPath);
      if (selectedPage) {
        return selectedPage;
      }
    }
    const defaultPath = draftPreview.entryPath || draftPreview.pages[0]?.path || "";
    return draftPreview.pages.find((page) => page.path === defaultPath) || draftPreview.pages[0] || null;
  }, [draftPreview, selectedFilePath]);
  const latestArtifactQualitySummary = parseArtifactQualitySummary(latestArtifactForSummary);
  const latestDraftStatusLabel = latestArtifactForSummary
    ? `v${latestArtifactForSummary.version} (${latestArtifactForSummary.status})`
    : "Not generated";
  const topQualityStatusLabel = latestArtifactQualitySummary
    ? artifactQualityStatusLabel(latestArtifactQualitySummary.qualityStatus)
    : "Not scored";
  const topQualityBadgeClass = latestArtifactQualitySummary
    ? artifactQualityBadgeClass(latestArtifactQualitySummary.qualityStatus)
    : "badge badge-muted";
  const nextActionMessage = deriveMigrationNextAction({
    draftReadiness,
    draftProviderCompatibility,
    draftGenerationState,
    selectedArtifact: latestArtifactForSummary,
    artifactQualitySummary: latestArtifactQualitySummary,
    canPublishSelectedArtifact,
    canDeploySelectedArtifact,
  });
  const summaryPriorityAlert = (() => {
    if (!Boolean(deployReadiness.ready) && deploySummaryBlockerMessage) {
      return `Deploy blocked: ${deploySummaryBlockerMessage}`;
    }
    if (!Boolean(publishReadiness.ready) && publishPrimaryBlockerMessage) {
      return `Publish blocked: ${publishPrimaryBlockerMessage}`;
    }
    if (draftReadiness.hardBlocked) {
      return draftReadiness.summary;
    }
    if (!draftProviderCompatibility.supported) {
      return draftProviderCompatibility.operatorMessage;
    }
    if (mediaRequiredByOperator && !mediaRequirementSatisfied) {
      return "Media required: import or upload and select at least one usable image before approval.";
    }
    const warningReason = draftReadiness.reasons.find((reason) => reason.severity === "warning");
    return warningReason ? warningReason.message : null;
  })();
  const publishReady = Boolean(publishReadiness.ready);
  const deployReady = Boolean(deployReadiness.ready);
  const publishPrimaryReadinessMessage = publishPrimaryBlockerMessage || publishReadinessReasons[0] || null;
  const deployPrimaryReadinessMessage = deploySummaryBlockerMessage || deployReadinessReasons[0] || null;
  const publishDiagnosticsAttemptStatusRaw =
    asStringOrNull(selectedPublishHistoryRecord.status) ||
    asStringOrNull(migrationDiagnostics.last_publish_status) ||
    null;
  const deployDiagnosticsAttemptStatusRaw =
    asStringOrNull(selectedDeployHistoryRecord.status) ||
    asStringOrNull(migrationDiagnostics.last_deploy_status) ||
    null;
  const publishDiagnosticsStatus: NormalizedDiagnosticStatus = (() => {
    if (publishDiagnosticsFailureCategory || publishDiagnosticsFailureReasonCode) {
      return "failed";
    }
    const fromAttempt = normalizeDiagnosticStatus(publishDiagnosticsAttemptStatusRaw);
    if (fromAttempt !== "unknown") {
      return fromAttempt;
    }
    if (!publishReady) {
      return "blocked";
    }
    if (publishReady) {
      return "success";
    }
    return "unknown";
  })();
  const deployDiagnosticsStatus: NormalizedDiagnosticStatus = (() => {
    if (currentLiveEvidenceHealthy) {
      return "success";
    }
    if (deployDiagnosticsFailureCategory || deployFailureReasonCode || deployRunFailureReasonCode) {
      return "failed";
    }
    const fromAttempt = normalizeDiagnosticStatus(deployDiagnosticsAttemptStatusRaw);
    if (fromAttempt !== "unknown") {
      return fromAttempt;
    }
    if (!deployReady) {
      return "blocked";
    }
    if (deployReady) {
      return "success";
    }
    return "unknown";
  })();
  const publishDiagnosticsReasonSummary = summarizeDiagnosticReason(
    publishDiagnosticsFailureMessage,
    publishDiagnosticsFailureReasonCode ? `Reason: ${formatReasonCodeLabel(publishDiagnosticsFailureReasonCode)}` : null,
    publishDiagnosticsFailureCategory ? `Category: ${toFailureCategoryLabel(publishDiagnosticsFailureCategory)}` : null,
    publishPrimaryReadinessMessage,
  );
  const publishDiagnosticsNextAction = summarizeDiagnosticReason(
    publishWorkflowRemediationGuidance,
    asStringOrNull(publishReadiness.operator_action),
    publishPrimaryReadinessMessage,
    publishDiagnosticsStatus === "success" ? "No action required." : "Review publish readiness and retry.",
  );
  const deployDiagnosticsReasonSummary = summarizeDiagnosticReason(
    currentLiveHealthySelectedWorkflowFailureNote,
    currentLiveEvidenceHealthy ? "Current runtime evidence: HTTPS probe succeeded." : null,
    (() => {
      const reasonCodes = new Set(
        [normalizedDispatchServiceReasonCode, normalizedDeployFailureReasonCode, normalizedDeployRunFailureReasonCode]
          .map((value) => value.trim())
          .filter((value) => value.length > 0),
      );
      if (!reasonCodes.has("ingress_backend_502")) {
        return null;
      }
      const parts: string[] = ["Preview hostname returned HTTP 502."];
      if (gceBackendHealthStatus) {
        parts.push(`GCE backend health: ${gceBackendHealthStatus}.`);
      }
      if (serviceProbeStatus) {
        parts.push(`Service probe: ${serviceProbeStatus}.`);
      }
      if (endpointProbeStatus) {
        parts.push(`Endpoint probe: ${endpointProbeStatus}.`);
      }
      if (runtimeProbeStatus) {
        parts.push(`Runtime classification: ${runtimeProbeStatus}.`);
      }
      return parts.join(" ");
    })(),
    (() => {
      const reasonCodes = new Set(
        [normalizedDispatchServiceReasonCode, normalizedDeployFailureReasonCode, normalizedDeployRunFailureReasonCode]
          .map((value) => value.trim())
          .filter((value) => value.length > 0),
      );
      const hasTlsProvisioningReason =
        reasonCodes.has("tls_certificate_provisioning") || reasonCodes.has("managed_certificate_provisioning");
      if (!hasTlsProvisioningReason && !tlsProvisioning) {
        return null;
      }
      if (deployHttpsReady === true) {
        return null;
      }
      const hostname =
        destinationSummary.deployPreviewHostname ||
        extractHostnameFromUrl(destinationSummary.deployResolvedLiveUrl) ||
        extractHostnameFromUrl(currentLiveUrl);
      const parts: string[] = [
        hostname
          ? `Deploy reached the load balancer, but TLS is still provisioning for ${hostname}.`
          : "Deploy reached the load balancer, but TLS is still provisioning for the preview hostname.",
        "Wait for ManagedCertificate to become ACTIVE, then refresh or rerun deploy.",
      ];
      if (staticIpStatus) {
        parts.push(`Static IP status: ${staticIpStatus}.`);
      }
      if (ingressStatusIp) {
        parts.push(`Ingress status IP: ${ingressStatusIp}.`);
      }
      if (ingressStatusIpMatchesStaticIp === true) {
        parts.push("Ingress status IP matches the reserved static IP.");
      }
      if (staticIpBoundToExpectedForwardingRule === true) {
        parts.push("Reserved static IP is bound to the expected forwarding rule.");
      }
      if (tlsCertificateStatus) {
        parts.push(`ManagedCertificate status: ${tlsCertificateStatus}.`);
      }
      if (tlsDomainStatus) {
        parts.push(`ManagedCertificate domain status: ${tlsDomainStatus}.`);
      }
      return parts.join(" ");
    })(),
    managedGkeConfigGuidance,
    deployFailureMessage,
    deployFailureReasonCode ? `Reason: ${formatReasonCodeLabel(deployFailureReasonCode)}` : null,
    deployFailureStage ? `Stage: ${formatDispatchStageLabel(deployFailureStage)}` : null,
    postConformanceReasonText,
    deployPrimaryReadinessMessage,
  );
  const deployDiagnosticsNextAction = summarizeDiagnosticReason(
    currentLiveEvidenceHealthy ? "No action required." : null,
    postConformanceGuidance,
    deployRunFailureHint,
    deployFailureRemediationHintDisplay,
    managedGkeConfigGuidance,
    asStringOrNull(deployReadiness.operator_action),
    deployPrimaryReadinessMessage,
    deployDiagnosticsStatus === "success" ? "No action required." : "Review deploy diagnostics and rerun deploy.",
  );
  const publishDiagnosticsSelectedTimestamp = asStringOrNull(selectedPublishHistoryRecord.timestamp);
  const deployDiagnosticsSelectedTimestamp = asStringOrNull(selectedDeployHistoryRecord.timestamp);
  const publishHistoryLatestAttempts = publishHistoryRecords.slice(-5).reverse();
  const deployHistoryLatestAttempts = deployHistoryRecords.slice(-5).reverse();
  const publishHistoryGroupedFailures = useMemo(
    () => groupAttemptHistory(publishHistoryRecords, "publish"),
    [publishHistoryRecords],
  );
  const deployHistoryGroupedFailures = useMemo(
    () => groupAttemptHistory(deployHistoryRecords, "deploy"),
    [deployHistoryRecords],
  );
  const deployConsistencyGrouping = groupDeployConsistency({
    deploymentRolloutStatus: deploymentRolloutGateStatus,
    serviceEndpointsStatus: serviceEndpointsGateStatus,
    backendHealthStatus: backendHealthGateStatus,
    dnsStatus: dnsMatchesIngressGateStatus,
    managedCertificateStatus: managedCertificateActiveGateStatus,
    httpsStatus: httpsProbeGateStatus,
    workflowIntegrityStatus: workflowIntegrityGateStatus,
    ingressPolicyStatus: ingressConflictGateStatus,
    tlsFailedNotVisible,
    tlsProvisioning,
    hasDnsMismatchReason,
    hasIngressConflictReason,
    workflowIntegrityReasonCode,
  });

  const hydrateFromSummary = useCallback((nextSummary: MigrationWorkspaceSummary) => {
    const workspace = nextSummary.workspace;
    setSourceUrl(workspace.source_url || "");

    const rawRequirements = asRecord(workspace.operator_requirements_json);
    setBusinessObjectives(joinLines(asStringList(rawRequirements.business_objectives)));
    setRequestedPages(joinLines(asStringList(rawRequirements.requested_pages)));
    setMustInclude(joinLines(asStringList(rawRequirements.must_include)));
    setMustAvoid(joinLines(asStringList(rawRequirements.must_avoid)));
    setTonePreferences(joinLines(asStringList(rawRequirements.tone_preferences)));
    setCallsToAction(joinLines(asStringList(rawRequirements.calls_to_action)));
    setRequirementsNotes(asString(rawRequirements.additional_notes));

    const rawPublishConfig = asRecord(workspace.publish_config_json);
    setPublishRepoName(asString(rawPublishConfig.repo_name));
    setPublishBranch(asString(rawPublishConfig.branch));

    const rawDeployConfig = asRecord(workspace.deploy_config_json);
    setDeployEnabled(Boolean(rawDeployConfig.enabled));

  }, []);

  const loadWorkspaceData = useCallback(
    async (ensureWorkspace: boolean, options?: { preserveErrorMessage?: boolean }): Promise<void> => {
      setBusyAction("load");
      if (!options?.preserveErrorMessage) {
        setErrorMessage(null);
        setErrorHint(null);
      }
      try {
        if (ensureWorkspace) {
          await upsertMigrationWorkspace(token, businessId, siteId, {});
        }
        const [workspaceSummary, versionList] = await Promise.all([
          fetchMigrationWorkspaceSummary(token, businessId, siteId),
          fetchMigrationArtifactVersions(token, businessId, siteId),
        ]);
        setSummary(workspaceSummary);
        setArtifactVersions(versionList.items || []);
        setPublishHistory(workspaceSummary.publish_history || []);
        setDeployHistory(workspaceSummary.deploy_history || []);
        setPublishHistoryLoaded(false);
        setDeployHistoryLoaded(false);
        hydrateFromSummary(workspaceSummary);
        const versions = versionList.items || [];
        setSelectedArtifactVersionId((current) =>
          resolveSelectedArtifactVersionId({
            currentId: current,
            artifactVersions: versions,
            workspaceSummary,
          }),
        );
        void (async () => {
          const [mediaResult, readinessResult, publishHistoryResult, deployHistoryResult] = await Promise.allSettled([
            fetchMigrationMediaAssets(token, businessId, siteId),
            fetchMigrationDraftReadiness(token, businessId, siteId),
            fetchMigrationPublishHistory(token, businessId, siteId),
            fetchMigrationDeployHistory(token, businessId, siteId),
          ]);
          if (mediaResult.status === "fulfilled") {
            setMediaAssetsSnapshot(asRecord(mediaResult.value));
          } else {
            setMediaAssetsSnapshot(null);
          }
          if (readinessResult.status === "fulfilled") {
            setDraftReadinessSnapshot(asRecord(readinessResult.value));
          } else {
            setDraftReadinessSnapshot(null);
          }
          if (publishHistoryResult.status === "fulfilled") {
            const latestPublishHistory = publishHistoryResult.value.items || [];
            setPublishHistory(
              latestPublishHistory.length > 0
                ? latestPublishHistory
                : workspaceSummary.publish_history || [],
            );
            setPublishHistoryLoaded(true);
          } else {
            setPublishHistoryLoaded(false);
          }
          if (deployHistoryResult.status === "fulfilled") {
            const latestDeployHistory = deployHistoryResult.value.items || [];
            setDeployHistory(
              latestDeployHistory.length > 0
                ? latestDeployHistory
                : workspaceSummary.deploy_history || [],
            );
            setDeployHistoryLoaded(true);
          } else {
            setDeployHistoryLoaded(false);
          }
        })();
      } catch (error) {
        setErrorHint(null);
        setErrorMessage(toErrorMessage(error, "Failed to load migration workspace."));
      } finally {
        setBusyAction(null);
      }
    },
    [businessId, hydrateFromSummary, siteId, token],
  );

  const loadPublishHistory = useCallback(async (): Promise<void> => {
    if (publishHistoryLoaded || busyAction === "load") {
      return;
    }
    try {
      const response = await fetchMigrationPublishHistory(token, businessId, siteId);
      setPublishHistory((current) => {
        const next = response.items || [];
        if (next.length === 0 && current.length > 0) {
          return current;
        }
        return next;
      });
      setPublishHistoryLoaded(true);
    } catch {
      // Keep summary payload as fallback if on-demand history refresh fails.
      setPublishHistoryLoaded(false);
    }
  }, [businessId, busyAction, publishHistoryLoaded, siteId, token]);

  const loadDeployHistory = useCallback(async (): Promise<void> => {
    if (deployHistoryLoaded || busyAction === "load") {
      return;
    }
    try {
      const response = await fetchMigrationDeployHistory(token, businessId, siteId);
      setDeployHistory((current) => {
        const next = response.items || [];
        if (next.length === 0 && current.length > 0) {
          return current;
        }
        return next;
      });
      setDeployHistoryLoaded(true);
    } catch {
      // Keep summary payload as fallback if on-demand history refresh fails.
      setDeployHistoryLoaded(false);
    }
  }, [businessId, busyAction, deployHistoryLoaded, siteId, token]);

  useEffect(() => {
    void loadWorkspaceData(true);
  }, [loadWorkspaceData]);

  useEffect(() => {
    setRequirementSuggestions(createDefaultRequirementSuggestionMap());
  }, [siteId]);

  useEffect(() => {
    setSelectedPublishHistoryIdentity((current) => {
      const trimmed = current.trim();
      if (publishHistoryRecords.length === 0) {
        return "";
      }
      if (trimmed && publishHistoryRecords.some((item) => historyRecordIdentity(item) === trimmed)) {
        return trimmed;
      }
      return historyRecordIdentity(publishHistoryRecords[publishHistoryRecords.length - 1]);
    });
  }, [publishHistoryRecords]);

  useEffect(() => {
    setSelectedDeployHistoryIdentity((current) => {
      const trimmed = current.trim();
      if (deployHistoryRecords.length === 0) {
        return "";
      }
      if (trimmed && deployHistoryRecords.some((item) => historyRecordIdentity(item) === trimmed)) {
        return trimmed;
      }
      return historyRecordIdentity(deployHistoryRecords[deployHistoryRecords.length - 1]);
    });
  }, [deployHistoryRecords]);

  useEffect(() => {
    setDraftPreviewOpen(false);
    setSelectedFilePath("");
  }, [selectedArtifactVersionId]);

  useEffect(() => {
    if (!draftPreview.available || draftPreview.pages.length === 0) {
      setSelectedFilePath("");
      return;
    }
    setSelectedFilePath((current) => {
      const normalizedCurrent = current.trim();
      if (normalizedCurrent && draftPreview.pages.some((page) => page.path === normalizedCurrent)) {
        return normalizedCurrent;
      }
      return draftPreview.entryPath || draftPreview.pages[0]?.path || "";
    });
  }, [draftPreview]);

  useEffect(() => {
    if (!draftPreviewOpen || draftPreview.pages.length === 0) {
      return;
    }
    const knownPaths = new Set(draftPreview.pages.map((page) => page.path));
    let lastObservedHash = "";
    const syncPreviewPathFromHash = () => {
      const frame = draftPreviewFrameRef.current;
      if (!frame?.contentWindow) {
        return;
      }
      const hash = String(frame.contentWindow.location.hash || "").trim();
      if (!hash || hash === lastObservedHash) {
        return;
      }
      lastObservedHash = hash;
      if (!hash.startsWith("#draft-preview-page=")) {
        return;
      }
      const encodedPath = hash.slice("#draft-preview-page=".length);
      if (!encodedPath) {
        return;
      }
      try {
        const decodedPath = decodeURIComponent(encodedPath).trim();
        if (!decodedPath || !knownPaths.has(decodedPath)) {
          return;
        }
        setSelectedFilePath((current) => (current === decodedPath ? current : decodedPath));
      } catch {
        return;
      }
    };
    const timerId = window.setInterval(syncPreviewPathFromHash, 300);
    return () => {
      window.clearInterval(timerId);
    };
  }, [draftPreview.pages, draftPreviewOpen]);

  const handleIngestSource = async (): Promise<void> => {
    setBusyAction("ingest");
    setErrorMessage(null);
    setErrorHint(null);
    setStatusMessage(null);
    try {
      const workspace = await ingestMigrationSource(token, businessId, siteId, {
        source_url: sourceUrl.trim() || null,
      });
      setSourceUrl(workspace.source_url || sourceUrl);
      setStatusMessage("Source ingest completed.");
      await loadWorkspaceData(false);
    } catch (error) {
      setErrorHint(null);
      setErrorMessage(toErrorMessage(error, "Source ingest failed."));
    } finally {
      setBusyAction(null);
    }
  };

  const handleSaveRequirements = async (): Promise<void> => {
    const payload: MigrationOperatorRequirements = {
      ...EMPTY_REQUIREMENTS,
      business_objectives: splitLines(businessObjectives),
      requested_pages: splitLines(requestedPages),
      must_include: splitLines(mustInclude),
      must_avoid: splitLines(mustAvoid),
      tone_preferences: splitLines(tonePreferences),
      calls_to_action: splitLines(callsToAction),
      additional_notes: asStringOrNull(requirementsNotes),
    };
    setBusyAction("save_requirements");
    setErrorMessage(null);
    setErrorHint(null);
    setStatusMessage(null);
    try {
      await updateMigrationRequirements(token, businessId, siteId, {
        operator_requirements: payload,
      });
      setStatusMessage("Migration requirements saved.");
      await loadWorkspaceData(false);
    } catch (error) {
      setErrorHint(null);
      setErrorMessage(toErrorMessage(error, "Failed to save migration requirements."));
    } finally {
      setBusyAction(null);
    }
  };

  const updateRequirementSuggestion = useCallback(
    (
      field: MigrationRequirementSuggestionField,
      updater: (current: RequirementSuggestionState) => RequirementSuggestionState,
    ): void => {
      setRequirementSuggestions((current) => {
        const fieldState = current[field] || createEmptyRequirementSuggestionState();
        return {
          ...current,
          [field]: updater(fieldState),
        };
      });
    },
    [],
  );

  const applyRequirementFieldUpdate = useCallback(
    (field: MigrationRequirementSuggestionField, updater: (current: string) => string): void => {
      if (field === "business_objectives") {
        setBusinessObjectives((current) => updater(current));
        return;
      }
      if (field === "requested_pages") {
        setRequestedPages((current) => updater(current));
        return;
      }
      if (field === "must_include") {
        setMustInclude((current) => updater(current));
        return;
      }
      if (field === "must_avoid") {
        setMustAvoid((current) => updater(current));
        return;
      }
      if (field === "tone") {
        setTonePreferences((current) => updater(current));
        return;
      }
      setCallsToAction((current) => updater(current));
    },
    [],
  );

  const readRequirementFieldValue = useCallback(
    (field: MigrationRequirementSuggestionField): string => {
      if (field === "business_objectives") {
        return businessObjectives;
      }
      if (field === "requested_pages") {
        return requestedPages;
      }
      if (field === "must_include") {
        return mustInclude;
      }
      if (field === "must_avoid") {
        return mustAvoid;
      }
      if (field === "tone") {
        return tonePreferences;
      }
      return callsToAction;
    },
    [businessObjectives, callsToAction, mustAvoid, mustInclude, requestedPages, tonePreferences],
  );

  const handleSuggestRequirementField = async (
    field: MigrationRequirementSuggestionField,
    options?: { forceRefresh?: boolean },
  ): Promise<void> => {
    const currentValueLines = splitLines(readRequirementFieldValue(field));
    updateRequirementSuggestion(field, (current) => ({
      ...current,
      status: "loading",
      errorMessage: null,
      reasonCode: null,
      open: true,
    }));
    try {
      const response = await suggestMigrationRequirementField(token, businessId, siteId, {
        field,
        current_value: currentValueLines.length > 0 ? currentValueLines : null,
        force_refresh: Boolean(options?.forceRefresh),
      });
      const normalizedStatusRaw = asString(response.suggestion_status).trim().toLowerCase();
      const normalizedStatus: RequirementSuggestionStatus =
        normalizedStatusRaw === "completed" || normalizedStatusRaw === "failed" || normalizedStatusRaw === "not_available"
          ? normalizedStatusRaw
          : "not_available";
      const suggestionValue = normalizeRequirementSuggestionText(response.suggested_value);
      const normalizedReasonCode = asString(response.reason_code).trim() || null;
      const suggestionStatus =
        normalizedStatus === "completed" && !suggestionValue.trim() ? "not_available" : normalizedStatus;
      const errorMessage =
        suggestionStatus === "completed"
          ? null
          : toRequirementSuggestionReasonLabel(normalizedReasonCode) || "Suggestion unavailable for this field.";
      updateRequirementSuggestion(field, (current) => ({
        ...current,
        value: suggestionValue,
        status: suggestionStatus,
        reasonCode: normalizedReasonCode,
        errorMessage,
        contextSourcesUsed: asStringList(response.context_sources_used),
        generatedAt: asStringOrNull(response.generated_at),
        open: true,
      }));
    } catch (error) {
      let reasonCode: string | null = null;
      if (error instanceof ApiRequestError) {
        const detail = asRecord(error.detail);
        reasonCode = asStringOrNull(detail.reason_code) || asStringOrNull(detail.error_code);
      }
      updateRequirementSuggestion(field, (current) => ({
        ...current,
        status: "failed",
        reasonCode,
        errorMessage: toRequirementSuggestionReasonLabel(reasonCode) || toErrorMessage(error, "Failed to suggest requirement text."),
        open: true,
      }));
    }
  };

  const handleRequirementSuggestionCopy = async (field: MigrationRequirementSuggestionField): Promise<void> => {
    const suggestionText = asString(requirementSuggestions[field]?.value).trim();
    if (!suggestionText) {
      return;
    }
    if (!navigator?.clipboard?.writeText) {
      updateRequirementSuggestion(field, (current) => ({
        ...current,
        errorMessage: "Clipboard is unavailable in this browser/session.",
      }));
      return;
    }
    try {
      await navigator.clipboard.writeText(suggestionText);
      updateRequirementSuggestion(field, (current) => ({
        ...current,
        errorMessage: null,
      }));
      setStatusMessage("AI suggestion draft copied.");
    } catch (error) {
      updateRequirementSuggestion(field, (current) => ({
        ...current,
        errorMessage: toErrorMessage(error, "Clipboard copy failed."),
      }));
    }
  };

  const handleRequirementSuggestionAppend = (field: MigrationRequirementSuggestionField): void => {
    const suggestionText = asString(requirementSuggestions[field]?.value).trim();
    if (!suggestionText) {
      return;
    }
    applyRequirementFieldUpdate(field, (current) => {
      const trimmed = current.trim();
      return trimmed ? `${trimmed}\n${suggestionText}` : suggestionText;
    });
    updateRequirementSuggestion(field, (current) => ({
      ...current,
      errorMessage: null,
    }));
  };

  const handleRequirementSuggestionReplace = (field: MigrationRequirementSuggestionField): void => {
    const suggestionText = asString(requirementSuggestions[field]?.value).trim();
    if (!suggestionText) {
      return;
    }
    applyRequirementFieldUpdate(field, () => suggestionText);
    updateRequirementSuggestion(field, (current) => ({
      ...current,
      errorMessage: null,
    }));
  };

  const handleRequirementSuggestionDismiss = (field: MigrationRequirementSuggestionField): void => {
    setRequirementSuggestions((current) => ({
      ...current,
      [field]: createEmptyRequirementSuggestionState(),
    }));
  };

  const handleUploadMediaAsset = async (): Promise<void> => {
    if (mediaUploadFiles.length <= 0) {
      setErrorHint(null);
      setErrorMessage("Select an image file before uploading.");
      return;
    }
    const validFiles: File[] = [];
    let skippedCount = 0;
    for (const file of mediaUploadFiles) {
      const normalizedMimeType = (file.type || "").trim().toLowerCase();
      if (!normalizedMimeType || MIGRATION_UPLOAD_ALLOWED_MIME_TYPES.has(normalizedMimeType)) {
        validFiles.push(file);
      } else {
        skippedCount += 1;
      }
    }
    if (validFiles.length <= 0) {
      setErrorHint(null);
      setErrorMessage("Selected files are not supported image types.");
      return;
    }
    setBusyAction("upload_media");
    setErrorMessage(null);
    setErrorHint(null);
    setStatusMessage(null);
    try {
      let uploadedCount = 0;
      let failedCount = 0;
      for (const file of validFiles) {
        try {
          await uploadMigrationMediaAsset(token, businessId, siteId, {
            file,
            selectedForDraft: mediaUploadSelectedForDraft,
            category: asStringOrNull(mediaUploadCategory),
            altText: asStringOrNull(mediaUploadAltText),
            description: asStringOrNull(mediaUploadDescription),
            usageNote: asStringOrNull(mediaUploadUsageNote),
            pageAssignment: asStringOrNull(mediaUploadPageAssignment),
          });
          uploadedCount += 1;
        } catch {
          failedCount += 1;
        }
      }
      setMediaUploadFiles([]);
      setMediaUploadCategory("other");
      setMediaUploadAltText("");
      setMediaUploadDescription("");
      setMediaUploadUsageNote("");
      setMediaUploadPageAssignment("");
      setMediaUploadSelectedForDraft(true);
      if (uploadedCount > 0 && failedCount === 0 && skippedCount === 0) {
        setStatusMessage("Workspace media uploaded.");
      } else {
        setStatusMessage(
          `Upload completed. Uploaded: ${uploadedCount} | Failed: ${failedCount} | Skipped: ${skippedCount}.`,
        );
      }
      if (failedCount > 0) {
        setErrorHint(null);
        setErrorMessage("One or more image uploads failed. Retry failed files.");
      }
      await loadWorkspaceData(false);
    } catch (error) {
      setErrorHint(null);
      setErrorMessage(toErrorMessage(error, "Media upload failed."));
    } finally {
      setBusyAction(null);
    }
  };

  const handleToggleMediaDraftCheck = (assetId: string, selected: boolean): void => {
    const normalizedAssetId = assetId.trim();
    if (!normalizedAssetId) {
      return;
    }
    setCheckedMediaAssetIds((current) => {
      const key = normalizedAssetId.toLowerCase();
      const filtered = current.filter((item) => item.toLowerCase() !== key);
      if (!selected) {
        return filtered.length === current.length ? current : filtered;
      }
      return [...filtered, normalizedAssetId];
    });
  };

  const handleUseMediaAssetsInDraft = async (
    options?: { assetIds?: string[] },
  ): Promise<void> => {
    const targetAssetIds = (() => {
      const provided = options?.assetIds || [];
      const normalized: string[] = [];
      const seen = new Set<string>();
      const source = provided.length > 0 ? provided : checkedMediaAssetIdsResolved;
      for (const item of source) {
        const value = item.trim();
        if (!value) {
          continue;
        }
        const key = value.toLowerCase();
        if (seen.has(key)) {
          continue;
        }
        seen.add(key);
        normalized.push(value);
      }
      return normalized;
    })();

    if (targetAssetIds.length === 0) {
      setErrorHint(null);
      setErrorMessage("Check at least one safe image before using it in draft.");
      return;
    }

    const targetAssets = targetAssetIds
      .map((assetId) => mediaBrowserAssetLookup.get(assetId.toLowerCase()))
      .filter((item): item is (typeof mediaBrowserAssets)[number] => Boolean(item));
    if (targetAssets.length === 0) {
      setErrorHint(null);
      setErrorMessage("No matching image assets were found for the selected action.");
      return;
    }

    setBusyAction("import_media");
    setErrorMessage(null);
    setErrorHint(null);
    setStatusMessage(null);
    try {
      const includedAssetIds = new Set<string>();
      let importedCount = 0;
      let includedCount = 0;
      let analyzedCount = 0;
      let skippedCount = 0;
      let blockedCount = 0;
      let suggestionsAppliedCount = 0;
      let topBlockedReason: string | null = null;

      const blockedAssets = targetAssets.filter((item) => item.isBlocked);
      blockedCount += blockedAssets.length;
      if (!topBlockedReason && blockedAssets.length > 0) {
        topBlockedReason =
          toMediaSuggestionReasonLabel(blockedAssets[0].blockedReasonCode || null) || "Blocked for safety reasons.";
      }

      const safeAssets = targetAssets.filter((item) => !item.isBlocked);
      const importRequiredAssets = safeAssets.filter((item) => item.remoteImportRequired);
      const directIncludeAssets = safeAssets.filter((item) => !item.remoteImportRequired);

      const importUsefulIds = importRequiredAssets
        .filter((item) => item.candidateQuality !== "low_value")
        .map((item) => item.assetId);
      const importOverrideIds = importRequiredAssets
        .filter((item) => item.candidateQuality === "low_value")
        .map((item) => item.assetId);

      const processImportBatch = async (
        discoveredIds: string[],
        allowQualityOverride: boolean,
      ): Promise<void> => {
        if (discoveredIds.length === 0) {
          return;
        }
        const batchResult = await importMigrationDiscoveredMediaAssets(token, businessId, siteId, {
          discovered_image_ids: discoveredIds,
          selected_for_draft: true,
          ...(allowQualityOverride ? { allow_quality_override: true } : {}),
        });
        setMediaImportBatchSnapshot(asRecord(batchResult));
        importedCount += Math.max(0, Number(batchResult.imported_count || 0));
        skippedCount += Math.max(0, Number(batchResult.skipped_count || 0));
        blockedCount += Math.max(0, Number(batchResult.failed_count || 0));
        blockedCount += Math.max(0, Number(batchResult.disabled_count || 0));
        const results = Array.isArray(batchResult.results) ? batchResult.results : [];
        for (const result of results) {
          const resultRecord = asRecord(result);
          const resultAssetId = asStringOrNull(resultRecord.asset_id);
          const resultStatus = (asStringOrNull(resultRecord.status) || "").toLowerCase();
          if (resultAssetId && (resultStatus === "imported" || resultStatus === "skipped")) {
            includedAssetIds.add(resultAssetId);
            continue;
          }
          if (!topBlockedReason && (resultStatus === "failed" || resultStatus === "disabled")) {
            topBlockedReason = toMediaSuggestionReasonLabel(asStringOrNull(resultRecord.reason_code));
          }
        }
      };

      await processImportBatch(importUsefulIds, false);
      await processImportBatch(importOverrideIds, true);

      for (const item of directIncludeAssets) {
        if (item.selected) {
          includedAssetIds.add(item.assetId);
          skippedCount += 1;
          continue;
        }
        try {
          await updateMigrationMediaAsset(token, businessId, siteId, item.assetId, {
            selected_for_draft: true,
          });
          includedAssetIds.add(item.assetId);
        } catch (error) {
          blockedCount += 1;
          if (!topBlockedReason) {
            topBlockedReason = toErrorMessage(error, "Failed to include image in draft.");
          }
        }
      }

      includedCount = includedAssetIds.size;
      if (includedAssetIds.size > 0) {
        try {
          const batchResult = await suggestMigrationMediaAssetsMetadataBatch(token, businessId, siteId, {
            asset_ids: Array.from(includedAssetIds),
            force_refresh: false,
          });
          setMediaSuggestionBatchSnapshot(asRecord(batchResult));
          analyzedCount = Math.max(0, Number(batchResult.completed_count || 0));
          skippedCount += Math.max(0, Number(batchResult.skipped_count || 0));
          const results = Array.isArray(batchResult.results) ? batchResult.results : [];
          for (const result of results) {
            const resultRecord = asRecord(result);
            const resultAssetId = asStringOrNull(resultRecord.asset_id);
            const suggestionStatus = (asStringOrNull(resultRecord.suggestion_status) || "").toLowerCase();
            if (!resultAssetId || suggestionStatus !== "completed") {
              continue;
            }
            try {
              await updateMigrationMediaAsset(token, businessId, siteId, resultAssetId, {
                apply_suggested_metadata: true,
              });
              suggestionsAppliedCount += 1;
            } catch {
              // Suggestion staging is acceptable if apply is unavailable for this asset/runtime.
            }
          }
        } catch {
          // Do not block draft inclusion when analysis is unavailable in this runtime.
        }
      }

      setCheckedMediaAssetIds((current) => {
        const seen = new Set<string>();
        const next: string[] = [];
        for (const item of [...current, ...Array.from(includedAssetIds)]) {
          const key = item.toLowerCase();
          if (seen.has(key)) {
            continue;
          }
          seen.add(key);
          next.push(item);
        }
        return next;
      });

      await loadWorkspaceData(false);
      const topReasonText = topBlockedReason ? ` | Top reason: ${topBlockedReason}` : "";
      const appliedText = suggestionsAppliedCount > 0 ? ` | Suggestions applied: ${suggestionsAppliedCount}` : "";
      setStatusMessage(
        `Use in draft result: Imported ${importedCount}, Included in draft ${includedCount}, Analyzed ${analyzedCount}, Skipped ${skippedCount}, Blocked ${blockedCount}${appliedText}${topReasonText}.`,
      );
    } catch (error) {
      setErrorHint(null);
      setErrorMessage(toErrorMessage(error, "Failed to use selected images in draft."));
    } finally {
      setBusyAction(null);
    }
  };

  const handleMediaLifecycleAction = async (
    assetId: string,
    action: Extract<MediaLifecycleAction, "remove" | "ignore">,
  ): Promise<void> => {
    const targetAsset = mediaBrowserAssetLookup.get(assetId.toLowerCase());
    if (!targetAsset) {
      setErrorHint(null);
      setErrorMessage("No matching image asset was found for this action.");
      return;
    }
    const actionLabel = action === "ignore" ? "Ignore" : "Remove image";
    const confirmationMessage =
      action === "ignore"
        ? "Ignore this discovered image from the default list?"
        : "Remove this image from the migration workspace?";
    if (!window.confirm(confirmationMessage)) {
      return;
    }

    setBusyAction("update_media");
    setErrorMessage(null);
    setErrorHint(null);
    setStatusMessage(null);
    try {
      const result = await updateMigrationMediaAssetLifecycle(token, businessId, siteId, assetId, {
        action,
      });
      const normalizedStatus = (asStringOrNull(result.status) || "").trim().toLowerCase();
      const reasonLabel = toMediaSuggestionReasonLabel(asStringOrNull(result.reason_code));

      if (normalizedStatus === "removed" || normalizedStatus === "ignored") {
        setCheckedMediaAssetIds((current) => current.filter((item) => item.toLowerCase() !== assetId.toLowerCase()));
      }

      await loadWorkspaceData(false);

      if (normalizedStatus === "removed") {
        setStatusMessage("Image removed from migration workspace.");
        return;
      }
      if (normalizedStatus === "ignored") {
        setStatusMessage("Image ignored from the default discovered list.");
        return;
      }
      if (normalizedStatus === "already_removed") {
        setStatusMessage("Image was already removed or ignored.");
        return;
      }
      if (normalizedStatus === "not_found") {
        setErrorHint(null);
        setErrorMessage("Image was not found in this migration workspace.");
        return;
      }
      if (normalizedStatus === "not_authorized") {
        setErrorHint(null);
        setErrorMessage("Image is not authorized for this migration workspace.");
        return;
      }
      if (normalizedStatus === "unsafe_delete_blocked") {
        setErrorHint(null);
        setErrorMessage(reasonLabel || `${actionLabel} is not allowed for this image lifecycle state.`);
        return;
      }
      setStatusMessage(`${actionLabel} result recorded.${reasonLabel ? ` ${reasonLabel}` : ""}`);
    } catch (error) {
      setErrorHint(null);
      setErrorMessage(toErrorMessage(error, `${actionLabel} failed.`));
    } finally {
      setBusyAction(null);
    }
  };

  const handleSavePublishConfig = async (): Promise<void> => {
    const payload: MigrationPublishConfig = {
      ...EMPTY_PUBLISH_CONFIG,
      enabled: true,
      repo_owner: null,
      repo_name: asStringOrNull(publishRepoName),
      branch: asStringOrNull(publishBranch),
      artifact_root: asStringOrNull(asString(workspacePublishConfig.artifact_root)),
    };
    setBusyAction("save_publish_config");
    setErrorMessage(null);
    setErrorHint(null);
    setStatusMessage(null);
    try {
      await updateMigrationPublishConfig(token, businessId, siteId, {
        publish_config: payload,
      });
      setStatusMessage("Publish repository settings saved.");
      await loadWorkspaceData(true);
    } catch (error) {
      setErrorHint(null);
      setErrorMessage(toErrorMessage(error, "Failed to save publish repository settings."));
    } finally {
      setBusyAction(null);
    }
  };

  const handleSaveDeployConfig = async (): Promise<void> => {
    const payload: MigrationDeployConfig = {
      enabled: deployEnabled,
      repo_owner: null,
      repo_name: null,
      workflow_id: null,
      ref: null,
      inputs: {},
    };
    setBusyAction("save_deploy_config");
    setErrorMessage(null);
    setErrorHint(null);
    setStatusMessage(null);
    try {
      await updateMigrationDeployConfig(token, businessId, siteId, {
        deploy_config: {
          enabled: payload.enabled,
        },
      });
      setStatusMessage("Deploy availability saved.");
      await loadWorkspaceData(true);
    } catch (error) {
      setErrorHint(null);
      setErrorMessage(toErrorMessage(error, "Failed to save deploy target."));
    } finally {
      setBusyAction(null);
    }
  };

  const handleGenerateArtifacts = async (): Promise<void> => {
    if (draftGenerationBlocked) {
      setErrorHint(null);
      setErrorMessage(draftGenerationState.summary || draftGenerationBlockedMessage);
      return;
    }
    setBusyAction("generate");
    setErrorMessage(null);
    setErrorHint(null);
    setStatusMessage(null);
    try {
      let refreshedReadinessPayload: Record<string, unknown> | null = null;
      try {
        refreshedReadinessPayload = asRecord(await fetchMigrationDraftReadiness(token, businessId, siteId));
      } catch {
        refreshedReadinessPayload = null;
      }
      if (refreshedReadinessPayload) {
        setDraftReadinessSnapshot(refreshedReadinessPayload);
        const readyRaw = refreshedReadinessPayload.ready;
        const readinessReady = typeof readyRaw === "boolean" ? readyRaw : true;
        if (!readinessReady) {
          const blockingCodes = asStringList(refreshedReadinessPayload.blocking_reason_codes);
          const firstBlockingCode = blockingCodes.length > 0 ? blockingCodes[0] : null;
          const operatorAction = asString(refreshedReadinessPayload.operator_action).trim();
          setErrorHint(toDraftAuthIntegrationGuidance(firstBlockingCode));
          setErrorMessage(
            operatorAction || "Draft readiness is currently blocked. Resolve blocking issues and retry.",
          );
          return;
        }
      }
      const artifact = await generateMigrationDraftArtifacts(token, businessId, siteId, {
        force_new_version: true,
      });
      setSelectedArtifactVersionId(artifact.id);
      setStatusMessage("Draft migration artifacts generated for operator review.");
      await loadWorkspaceData(false);
    } catch (error) {
      const parsed = parseDraftGenerationFailure(error);
      const hintParts: string[] = [];
      if (parsed.hint) {
        hintParts.push(parsed.hint);
      }
      if (parsed.correlationId) {
        hintParts.push(`Reference: ${parsed.correlationId}.`);
      }
      setErrorHint(hintParts.join(" ") || null);
      setErrorMessage(parsed.message);
      await loadWorkspaceData(false, { preserveErrorMessage: true });
    } finally {
      setBusyAction(null);
    }
  };

  const handleApproveSelectedArtifact = async (): Promise<void> => {
    if (!selectedArtifactVersionId) {
      setErrorHint(null);
      setErrorMessage("Select an artifact version before approving.");
      return;
    }
    setBusyAction("approve");
    setErrorMessage(null);
    setErrorHint(null);
    setStatusMessage(null);
    try {
      await approveMigrationArtifactVersion(token, businessId, siteId, selectedArtifactVersionId, {
        approval_notes: asStringOrNull(approvalNotes),
      });
      setStatusMessage("Selected draft artifact approved.");
      await loadWorkspaceData(false);
    } catch (error) {
      const baseMessage = toErrorMessage(error, "Failed to approve artifact.");
      const category = parseFailureCategory(error, baseMessage, "approve");
      setErrorHint(null);
      setErrorMessage(formatActionFailureMessage("approve", category, baseMessage));
    } finally {
      setBusyAction(null);
    }
  };

  const handleDeleteSelectedArtifact = async (): Promise<void> => {
    if (!selectedArtifactVersionIdTrimmed) {
      setErrorHint(null);
      setErrorMessage("Select a draft artifact before deleting.");
      return;
    }
    if (!canDeleteSelectedArtifact) {
      setErrorHint(null);
      setErrorMessage(selectedArtifactDeleteBlockedReason || "Selected artifact cannot be deleted.");
      return;
    }
    if (!window.confirm("Delete the selected draft artifact? This cannot be undone.")) {
      return;
    }
    setBusyAction("delete_draft");
    setErrorMessage(null);
    setErrorHint(null);
    setStatusMessage(null);
    try {
      const result = await deleteMigrationArtifactVersion(token, businessId, siteId, selectedArtifactVersionIdTrimmed);
      setStatusMessage(
        `Draft artifact v${result.deleted_artifact_version_number} deleted.`,
      );
      await loadWorkspaceData(false);
    } catch (error) {
      const baseMessage = toErrorMessage(error, "Failed to delete draft artifact.");
      setErrorHint(null);
      setErrorMessage(baseMessage);
    } finally {
      setBusyAction(null);
    }
  };

  const handlePublishSelectedArtifact = async (): Promise<void> => {
    if (!selectedArtifactVersionId) {
      setErrorHint(null);
      setErrorMessage("Select an approved artifact version before publishing.");
      return;
    }
    setBusyAction("publish");
    setErrorMessage(null);
    setErrorHint(null);
    setStatusMessage(null);
    try {
      const actionResult = await publishMigrationArtifactVersion(token, businessId, siteId, {
        artifact_version_id: selectedArtifactVersionId,
        dry_run: publishDryRun,
        commit_message: asStringOrNull(publishCommitMessage),
        analytics_measurement_id: asStringOrNull(publishAnalyticsOverride),
      });
      const resultPayload = asRecord(actionResult.result);
      const duplicateArtifactSkipped = resultPayload.duplicate_artifact_skipped === true;
      const workflowProvisioned = resultPayload.deploy_workflow_provisioned === true;
      if (publishDryRun) {
        setStatusMessage("Publish dry-run completed.");
      } else if (duplicateArtifactSkipped && workflowProvisioned) {
        setStatusMessage(
          "Artifact content was already published. Missing deploy workflow was provisioned and verified.",
        );
      } else {
        setStatusMessage("Publish to GitHub completed.");
      }
      await loadWorkspaceData(false);
    } catch (error) {
      const baseMessage = toErrorMessage(error, "Publish failed.");
      const category = parseFailureCategory(error, baseMessage, "publish");
      await loadWorkspaceData(false, { preserveErrorMessage: true });
      setErrorHint(null);
      setErrorMessage(formatActionFailureMessage("publish", category, baseMessage));
    } finally {
      setBusyAction(null);
    }
  };

  const handleAdoptPublishRepository = async (): Promise<void> => {
    if (!effectivePublishRepoOwner || !effectivePublishRepoName) {
      setErrorHint(null);
      setErrorMessage("Publish repository owner/name is required before repository adoption.");
      return;
    }
    const confirmed = window.confirm(
      "Adopt this repository for MBSRN-managed publish? This writes mbsrn.key. After adoption, MBSRN may update managed site files.",
    );
    if (!confirmed) {
      return;
    }
    setBusyAction("adopt_repository");
    setErrorMessage(null);
    setErrorHint(null);
    setStatusMessage(null);
    try {
      const actionResult = await adoptMigrationPublishRepository(token, businessId, siteId);
      const resultPayload = asRecord(actionResult.result);
      const markerWritten = resultPayload.marker_written === true;
      setStatusMessage(
        markerWritten
          ? "Repository adopted for MBSRN-managed publish."
          : "Repository is already marked as MBSRN-managed.",
      );
      await loadWorkspaceData(false);
    } catch (error) {
      const baseMessage = toErrorMessage(error, "Repository adoption failed.");
      await loadWorkspaceData(false, { preserveErrorMessage: true });
      setErrorHint(null);
      setErrorMessage(baseMessage);
    } finally {
      setBusyAction(null);
    }
  };

  const handleDeploySelectedArtifact = async (): Promise<void> => {
    if (!selectedArtifactVersionId) {
      setErrorHint(null);
      setErrorMessage("Select an approved artifact version before deploy.");
      return;
    }
    setBusyAction("deploy");
    setErrorMessage(null);
    setErrorHint(null);
    setStatusMessage(null);
    try {
      await deployMigrationArtifactVersion(token, businessId, siteId, {
        artifact_version_id: selectedArtifactVersionId,
        dry_run: deployDryRun,
      });
      setStatusMessage(deployDryRun ? "Deploy dry-run completed." : "Deploy request submitted.");
      await loadWorkspaceData(false);
    } catch (error) {
      const baseMessage = toErrorMessage(error, "Deploy failed.");
      const category = parseFailureCategory(error, baseMessage, "deploy");
      await loadWorkspaceData(false, { preserveErrorMessage: true });
      setErrorHint(null);
      setErrorMessage(formatActionFailureMessage("deploy", category, baseMessage));
    } finally {
      setBusyAction(null);
    }
  };

  const handleRefreshDeployStatus = async (): Promise<void> => {
    if (!selectedArtifactVersionId) {
      setErrorHint(null);
      setErrorMessage("Select an artifact version before refreshing deploy status.");
      return;
    }
    setBusyAction("refresh_deploy_status");
    setErrorMessage(null);
    setErrorHint(null);
    setStatusMessage(null);
    try {
      const actionResult = await refreshMigrationDeployStatus(token, businessId, siteId, {
        artifact_version_id: selectedArtifactVersionId,
      });
      const result = asRecord(actionResult.result);
      const refreshStatus = asString(result.status).trim().toLowerCase();
      const noChangeReason = asString(result.no_change_reason).trim().toLowerCase();
      const workflowRunStatus = asStringOrNull(result.workflow_run_status);
      const workflowRunConclusion = asStringOrNull(result.workflow_run_conclusion);
      const resolvedLiveUrl = asStringOrNull(result.resolved_live_url);
      if (refreshStatus === "updated") {
        if (resolvedLiveUrl) {
          setStatusMessage("Deploy status refreshed. Confirmed live URL captured from workflow output.");
        } else {
          setStatusMessage("Deploy status refreshed. Workflow run metadata updated.");
        }
      } else if (noChangeReason === "workflow_run_metadata_missing") {
        setStatusMessage("Deploy status refresh found no workflow run metadata yet for this artifact.");
      } else if (noChangeReason === "deploy_record_missing") {
        setStatusMessage("No deploy request record was found for the selected artifact.");
      } else if (noChangeReason === "deploy_target_metadata_missing") {
        setStatusMessage("Deploy status refresh requires stored deploy target metadata.");
      } else if (workflowRunStatus && workflowRunConclusion) {
        setStatusMessage(
          `Deploy status unchanged. Workflow run is ${workflowRunStatus} (${workflowRunConclusion}).`,
        );
      } else if (workflowRunStatus) {
        setStatusMessage(`Deploy status unchanged. Workflow run is ${workflowRunStatus}.`);
      } else {
        setStatusMessage("Deploy status refresh found no new workflow evidence.");
      }
      await loadWorkspaceData(false);
    } catch (error) {
      const baseMessage = toErrorMessage(error, "Deploy status refresh failed.");
      await loadWorkspaceData(false, { preserveErrorMessage: true });
      setErrorHint(null);
      setErrorMessage(baseMessage);
    } finally {
      setBusyAction(null);
    }
  };

  const handleSelectArtifactFile = (path: string): void => {
    if (!selectedArtifactVersionId || !path) {
      return;
    }
    setSelectedFilePath(path);
    setErrorMessage(null);
    setErrorHint(null);
  };

  const artifactQualitySummary = parseArtifactQualitySummary(selectedArtifact);
  const requiredMediaQualityIssue =
    artifactQualitySummary?.issues.find((issue) => issue.type === "required_media_missing") || null;
  const mediaFilterOptions: Array<{ value: MediaBrowserFilter; label: string; count: number }> = [
    { value: "all_usable", label: "All usable images", count: mediaFilterCounts.all_usable },
    { value: "discovered", label: "Discovered", count: mediaFilterCounts.discovered },
    { value: "uploaded_imported", label: "Uploaded/imported", count: mediaFilterCounts.uploaded_imported },
    { value: "unsafe_rejected", label: "Unsafe rejected", count: mediaFilterCounts.unsafe_rejected },
  ];
  const requirementFieldConfigs: Array<{
    field: MigrationRequirementSuggestionField;
    label: string;
    rows: number;
    value: string;
    onChange: (value: string) => void;
  }> = [
    {
      field: "business_objectives",
      label: "Business objectives (one per line)",
      rows: 5,
      value: businessObjectives,
      onChange: setBusinessObjectives,
    },
    {
      field: "requested_pages",
      label: "Requested pages (one per line)",
      rows: 3,
      value: requestedPages,
      onChange: setRequestedPages,
    },
    {
      field: "must_include",
      label: "Must include (one per line)",
      rows: 3,
      value: mustInclude,
      onChange: setMustInclude,
    },
    {
      field: "must_avoid",
      label: "Must avoid (one per line)",
      rows: 3,
      value: mustAvoid,
      onChange: setMustAvoid,
    },
    {
      field: "tone",
      label: "Tone (one per line)",
      rows: 3,
      value: tonePreferences,
      onChange: setTonePreferences,
    },
    {
      field: "calls_to_action",
      label: "Calls to action (one per line)",
      rows: 3,
      value: callsToAction,
      onChange: setCallsToAction,
    },
  ];

  if (busyAction === "load" && !summary) {
    return <p className="hint muted">Loading migration workspace...</p>;
  }

  return (
    <div className="stack migration-workspace-shell" data-testid="migration-workspace-panel">
      <MigrationSummarySection
        workspaceSiteName={workspaceSiteName}
        draftGenerationStateStatus={draftGenerationState.status}
        draftGenerationStateLabel={draftGenerationStateLabel}
        draftGenerationStateSummary={draftGenerationState.summary}
        draftGenerationStateToneClass={draftGenerationStateToneClass}
        nextActionMessage={nextActionMessage}
        latestDraftStatusLabel={latestDraftStatusLabel}
        selectedArtifactVersionIdTrimmed={selectedArtifactVersionIdTrimmed}
        topQualityBadgeClass={topQualityBadgeClass}
        topQualityStatusLabel={topQualityStatusLabel}
        latestArtifactQualityOperatorSummary={latestArtifactQualitySummary?.operatorSummary || null}
        summaryPriorityAlert={summaryPriorityAlert}
      />

      {errorMessage || statusMessage ? (
        <WorkspaceMessageStack data-testid="migration-message-stack">
          {errorMessage ? <p className="hint warning">{errorMessage}</p> : null}
          {errorMessage && errorHint ? (
            <p className="hint muted" data-testid="migration-error-hint">
              {errorHint}
            </p>
          ) : null}
          {statusMessage ? <p className="hint success">{statusMessage}</p> : null}
        </WorkspaceMessageStack>
      ) : null}

      <MigrationSourceRequirementsSection>

      <div className="panel stack workspace-section-block">
        <h3>Source Ingest</h3>
        <label className="stack-tight">
          <span className="hint muted">Source URL</span>
          <input
            type="url"
            value={sourceUrl}
            placeholder="https://legacy.example/"
            onChange={(event) => setSourceUrl(event.target.value)}
          />
        </label>
        <WorkspaceActionBar variant="primary">
          <button
            type="button"
            className="button button-primary"
            onClick={() => void handleIngestSource()}
            disabled={busyAction === "ingest" || busyAction === "load"}
          >
            {busyAction === "ingest" ? "Ingesting..." : "Ingest / Refresh Source"}
          </button>
        </WorkspaceActionBar>
      </div>

      <div className="panel stack workspace-section-block" data-testid="migration-source-summary">
        <h3>Source Snapshot Summary</h3>
        {sourceSnapshot ? (
          <details className="workspace-details-shell" data-testid="migration-source-summary-details">
            <summary>Show source snapshot details</summary>
            <div className="stack-tight">
              <span className="hint">Title: {asString(sourceSnapshot.title) || "-"}</span>
              <span className="hint">Description: {asString(sourceSnapshot.meta_description) || "-"}</span>
              <span className="hint">Canonical: {asString(sourceSnapshot.canonical_url) || "-"}</span>
              <span className="hint">Headings: {asStringList(sourceSnapshot.headings).length}</span>
              <span className="hint">Internal links: {asStringList(sourceSnapshot.internal_links).length}</span>
            </div>
          </details>
        ) : (
          <WorkspaceEmptyStateCard data-testid="migration-source-summary-empty-state">
            <p className="hint muted">No source snapshot ingested yet.</p>
          </WorkspaceEmptyStateCard>
        )}
      </div>

      </MigrationSourceRequirementsSection>

      <MigrationMediaSection>

      <div className="panel stack workspace-section-block" data-testid="migration-media-section">
        <h3>Images</h3>
        <span className="hint muted">
          Uploaded images are already available. Discovered images can be imported and used in draft when they pass safety checks.
        </span>
        <span className="hint muted">
          Check images to use, then run one action to import (if needed), include in draft, and run metadata suggestions where available.
        </span>
        {mediaRequiredByOperator ? (
          <div className="panel panel-compact stack-tight" data-testid="migration-media-required-callout">
            <strong className={mediaRequirementSatisfied ? "hint" : "hint warning"}>Media needed for this draft</strong>
            <span className={mediaRequirementSatisfied ? "hint muted" : "hint warning"}>
              {mediaRequirementSatisfied
                ? "At least one usable image is included in the next draft."
                : usefulDiscoveredButNotImportedOrSelected
                  ? "Useful source images were discovered. Use images in draft before approving."
                  : "No images are included in the next draft yet."}
            </span>
            {mediaRequirementWarningReason ? (
              <span className="hint muted">
                Reason: {draftReadinessReasonMessageFromCode(mediaRequirementWarningReason, "warning")}
              </span>
            ) : null}
            {mediaRequirementSources.length > 0 ? (
              <span className="hint muted">
                Matched requirement cues: {mediaRequirementSources.slice(0, 3).join(", ")}
              </span>
            ) : null}
          </div>
        ) : null}

        <div className="grid grid-2">
          <div className="panel panel-compact stack-tight" data-testid="migration-media-operator-actions">
            <strong>Use Images in Draft</strong>
            <span className="hint muted">
              Use checked images in draft imports safe discovered assets if needed, includes them in draft, then analyzes metadata where available.
            </span>
            <WorkspaceActionBar variant="secondary">
              <button
                type="button"
                className={checkedMediaAssetIdsResolved.length > 0 ? "button button-primary" : "button button-tertiary"}
                onClick={() => void handleUseMediaAssetsInDraft()}
                disabled={isActionInFlight || checkedMediaAssetIdsResolved.length === 0}
              >
                {busyAction === "import_media" ? "Using images..." : "Use checked images in draft"}
              </button>
              <button
                type="button"
                className="button button-tertiary"
                onClick={() => void handleIngestSource()}
                disabled={busyAction === "ingest" || busyAction === "load" || !sourceUrl.trim()}
              >
                {busyAction === "ingest" ? "Refreshing..." : "Discover / Refresh Source Images"}
              </button>
            </WorkspaceActionBar>
            <span className="hint muted">
              Checked safe images: {checkedMediaAssetIdsResolved.length}
            </span>
            <details className="workspace-details-shell" data-testid="migration-media-upload-disclosure">
              <summary>Upload images</summary>
              <div className="stack-tight">
                <label className="stack-tight">
                  <span className="hint muted">Upload image file</span>
                  <input
                    type="file"
                    accept="image/jpeg,image/png,image/webp,image/gif"
                    multiple
                    onChange={(event) => {
                      const files = event.target.files ? Array.from(event.target.files) : [];
                      setMediaUploadFiles(files);
                    }}
                  />
                </label>
                <span className="hint muted" data-testid="migration-media-upload-selection-count">
                  Files selected: {mediaUploadFiles.length}
                </span>
                <label className="stack-tight">
                  <span className="hint muted">Category</span>
                  <select
                    value={mediaUploadCategory}
                    onChange={(event) => setMediaUploadCategory(event.target.value)}
                  >
                    <option value="other">other</option>
                    <option value="customer_gallery">customer_gallery</option>
                    <option value="project_gallery">project_gallery</option>
                    <option value="before_after">before_after</option>
                    <option value="team">team</option>
                    <option value="company">company</option>
                    <option value="service_page">service_page</option>
                    <option value="hero">hero</option>
                    <option value="logo">logo</option>
                  </select>
                </label>
                <label className="stack-tight">
                  <span className="hint muted">Alt text</span>
                  <input value={mediaUploadAltText} onChange={(event) => setMediaUploadAltText(event.target.value)} />
                </label>
                <label className="stack-tight">
                  <span className="hint muted">Description</span>
                  <textarea
                    value={mediaUploadDescription}
                    onChange={(event) => setMediaUploadDescription(event.target.value)}
                    rows={2}
                  />
                </label>
                <label className="stack-tight">
                  <span className="hint muted">Usage note</span>
                  <input value={mediaUploadUsageNote} onChange={(event) => setMediaUploadUsageNote(event.target.value)} />
                </label>
                <label className="stack-tight">
                  <span className="hint muted">Page/gallery assignment</span>
                  <input
                    value={mediaUploadPageAssignment}
                    onChange={(event) => setMediaUploadPageAssignment(event.target.value)}
                  />
                </label>
                <label className="link-row">
                  <input
                    type="checkbox"
                    checked={mediaUploadSelectedForDraft}
                    onChange={(event) => setMediaUploadSelectedForDraft(event.target.checked)}
                  />
                  <span>Include images in draft on upload</span>
                </label>
                <button
                  type="button"
                  className="button button-secondary"
                  onClick={() => void handleUploadMediaAsset()}
                  disabled={isActionInFlight || mediaUploadFiles.length === 0}
                >
                  {busyAction === "upload_media"
                    ? "Uploading..."
                    : mediaUploadFiles.length === 1
                      ? "Upload image"
                      : "Upload images"}
                </button>
              </div>
            </details>
          </div>

          <div className="panel panel-compact stack-tight" data-testid="migration-media-counts">
            <strong>Image Counts</strong>
            <span className="hint">Discovered source images: {sourceDiscoveredMediaCount}</span>
            <span className="hint">Pages scanned: {pagesScannedCount}</span>
            {pagesScannedUrls.length > 0 ? (
              <details className="workspace-details-shell" data-testid="migration-media-pages-scanned">
                <summary>Show scanned pages</summary>
                <ul className="stack-tight">
                  {pagesScannedUrls.slice(0, 8).map((url, index) => (
                    <li key={`migration-media-pages-scanned-${index}`} className="hint muted">{url}</li>
                  ))}
                </ul>
              </details>
            ) : null}
            <span className="hint">Useful discovered candidates: {usefulDiscoveredImagesCount}</span>
            <span className="hint">Low-value quality warnings: {lowValueDiscoveredImagesCount}</span>
            <span className="hint">Unsafe rejected candidates: {rejectedDiscoveredImagesCount}</span>
            <span className="hint">Imported images: {sourceImportedMediaCount}</span>
            <span className="hint">Uploaded images: {operatorUploadedMediaCount}</span>
            <span className="hint">Images included in draft: {selectedMediaAssetsCount}</span>
            <span className="hint">Usable images included in draft: {selectedUsableMediaAssetsCount}</span>
            <span className="hint">Import-ready discovered images: {discoveredImportRequiredCount}</span>
            {mediaImportBatchStatus ? (
              <details className="workspace-details-shell" data-testid="migration-media-import-feedback">
                <summary>Show import result details</summary>
                <div className="stack-tight">
                  <strong>Import result</strong>
                  <span className="hint">Status: {toMediaSuggestionBatchStatusLabel(mediaImportBatchStatus)}</span>
                  <span className="hint">
                    Imported: {mediaImportBatchImportedCount} | Failed: {mediaImportBatchFailedCount} | Skipped: {mediaImportBatchSkippedCount} | Disabled: {mediaImportBatchDisabledCount}
                  </span>
                  {mediaImportBatchResults.length > 0 ? (
                    <ul className="stack-tight">
                      {mediaImportBatchResults.slice(0, 8).map((result, index) => {
                        const resultAssetId = asStringOrNull(result.asset_id) || `import-result-${index}`;
                        const resultStatus = toMediaImportStatusLabel(asStringOrNull(result.status));
                        const resultReason = toMediaSuggestionReasonLabel(asStringOrNull(result.reason_code));
                        return (
                          <li key={`media-import-result-${resultAssetId}-${index}`} className="hint">
                            {resultAssetId}: {resultStatus}{resultReason ? ` (${resultReason})` : ""}
                          </li>
                        );
                      })}
                    </ul>
                  ) : null}
                </div>
              </details>
            ) : null}
            {mediaSuggestionBatchStatus ? (
              <details className="workspace-details-shell" data-testid="migration-media-batch-feedback">
                <summary>Show analysis result details</summary>
                <div className="stack-tight">
                  <strong>Image analysis result</strong>
                  <span className="hint">Status: {toMediaSuggestionBatchStatusLabel(mediaSuggestionBatchStatus)}</span>
                  <span className="hint">
                    Completed: {mediaSuggestionBatchCompletedCount} | Failed: {mediaSuggestionBatchFailedCount} | Skipped: {mediaSuggestionBatchSkippedCount}
                  </span>
                  {mediaSuggestionBatchResults.length > 0 ? (
                    <ul className="stack-tight">
                      {mediaSuggestionBatchResults.slice(0, 8).map((result, index) => {
                        const resultAssetId = asStringOrNull(result.asset_id) || `result-${index}`;
                        const resultStatus = toMediaSuggestionStatusLabel(asStringOrNull(result.suggestion_status));
                        const resultReason = toMediaSuggestionReasonLabel(asStringOrNull(result.reason_code));
                        return (
                          <li key={`media-batch-result-${resultAssetId}-${index}`} className="hint">
                            {resultAssetId}: {resultStatus}{resultReason ? ` (${resultReason})` : ""}
                          </li>
                        );
                      })}
                    </ul>
                  ) : null}
                </div>
              </details>
            ) : null}
          </div>
        </div>

        <div className="panel panel-compact stack-tight migration-media-browser" data-testid="migration-media-source-list">
          <div className="row-space-between">
            <strong>Site images</strong>
            <span className="hint muted">Low-value is a warning only. Unsafe rejected images are blocked.</span>
          </div>
          <div className="migration-media-filter-controls" data-testid="migration-media-filter-controls">
            {mediaFilterOptions.map((option) => (
              <button
                key={`migration-media-filter-${option.value}`}
                type="button"
                className={mediaBrowserFilter === option.value ? "button button-secondary" : "button button-tertiary"}
                data-testid={`migration-media-filter-${option.value}`}
                aria-pressed={mediaBrowserFilter === option.value}
                onClick={() => setMediaBrowserFilter(option.value)}
                disabled={isActionInFlight}
              >
                {option.label} ({option.count})
              </button>
            ))}
          </div>
          {mediaBrowserVisibleAssets.length > 0 ? (
            <div className="migration-media-browser-list migration-media-image-grid" data-testid="migration-media-image-grid">
              {mediaBrowserVisibleAssets.slice(0, 24).map((item) => {
                const previewUnavailableMessage = item.previewUnavailableReason || "Preview unavailable.";
                const isChecked = checkedMediaAssetLookup.has(item.assetId.toLowerCase());
                return (
                  <article
                    key={`migration-media-browser-item-${item.assetId}`}
                    className={
                      item.candidateQuality === "useful"
                        ? "migration-media-row migration-media-card"
                        : "migration-media-row migration-media-card migration-media-row-deemphasized"
                    }
                    data-testid={`migration-media-row-${item.assetId}`}
                  >
                    <div className="migration-media-card-preview-shell">
                      {item.previewUrl ? (
                        /* eslint-disable-next-line @next/next/no-img-element */
                        <img
                          src={item.previewUrl}
                          alt={item.previewAlt}
                          className="migration-media-card-thumbnail"
                          loading="lazy"
                          decoding="async"
                        />
                      ) : (
                        <div className="migration-media-card-preview-unavailable" data-testid={`migration-media-preview-unavailable-${item.assetId}`}>
                          {previewUnavailableMessage}
                        </div>
                      )}
                    </div>
                    <div className="migration-media-row-header">
                      <div className="migration-media-row-title">
                        <span className="text-strong">{item.displayName}</span>
                      </div>
                      {item.compactReasonLabel ? (
                        <span
                          className={item.isBlocked ? "hint warning" : item.candidateQuality === "low_value" ? "hint warning" : "hint muted"}
                          data-testid={`migration-media-compact-reason-${item.assetId}`}
                        >
                          {item.compactReasonLabel}
                        </span>
                      ) : null}
                    </div>
                    <div className="row-wrap-tight migration-media-card-badges">
                      <span className="badge badge-muted">{item.sourceBadgeLabel}</span>
                      {item.candidateQuality === "low_value" ? <span className="badge badge-warn">Quality warning</span> : null}
                      {item.isBlocked ? <span className="badge badge-error">Blocked</span> : null}
                      {item.selected ? <span className="badge badge-success">Included in draft</span> : null}
                      {item.metadataStatusLabel ? (
                        <span className={item.metadataStatusLabel === "Analysis unavailable" ? "badge badge-warn" : "badge badge-success"}>
                          {item.metadataStatusLabel}
                        </span>
                      ) : null}
                    </div>
                    <label className="link-row" data-testid={`migration-media-use-checkbox-${item.assetId}`}>
                      <input
                        type="checkbox"
                        checked={isChecked}
                        onChange={(event) => handleToggleMediaDraftCheck(item.assetId, event.target.checked)}
                        disabled={isActionInFlight || item.isBlocked}
                      />
                      <span>Use in draft</span>
                    </label>
                    <div className="row-wrap-tight">
                      {!item.isBlocked ? (
                        <button
                          type="button"
                          className={item.primaryAction === "use_in_draft_anyway" ? "button button-secondary" : "button button-primary"}
                          data-testid={`migration-media-primary-action-${item.assetId}`}
                          onClick={() => void handleUseMediaAssetsInDraft({ assetIds: [item.assetId] })}
                          disabled={isActionInFlight}
                        >
                          {item.primaryAction === "use_in_draft_anyway" ? "Use in draft anyway" : "Use in draft"}
                        </button>
                      ) : null}
                      {item.lifecycleAction !== "none" && item.lifecycleActionLabel ? (
                        <button
                          type="button"
                          className="button button-tertiary"
                          data-testid={`migration-media-lifecycle-action-${item.assetId}`}
                          onClick={() =>
                            void handleMediaLifecycleAction(
                              item.assetId,
                              item.lifecycleAction as Extract<MediaLifecycleAction, "remove" | "ignore">,
                            )
                          }
                          disabled={isActionInFlight}
                        >
                          {item.lifecycleActionLabel}
                        </button>
                      ) : null}
                    </div>
                    <details className="migration-media-details" data-testid={`migration-media-details-${item.assetId}`}>
                      <summary>Image details</summary>
                      <div className="stack-tight">
                        <span className="hint muted">Analysis status: {toMediaSuggestionStatusLabel(item.suggestionStatus)}</span>
                        {item.suggestionReason ? <span className="hint muted">{item.suggestionReason}</span> : null}
                        {item.analysisUnavailableInRuntime ? (
                          <span className="hint muted">Analysis unavailable in this environment.</span>
                        ) : null}
                        {item.blockedReasonCode ? (
                          <span className="hint warning">Blocked reason: {item.blockedReasonCode}</span>
                        ) : null}
                        <span className="hint muted">Provenance: {item.provenance || "unknown"}</span>
                        {item.normalizedUrl ? <span className="hint muted">URL: {item.normalizedUrl}</span> : null}
                        {item.sourcePageUrl ? <span className="hint muted">Source page: {item.sourcePageUrl}</span> : null}
                      </div>
                    </details>
                  </article>
                );
              })}
            </div>
          ) : (
            <WorkspaceEmptyStateCard data-testid="migration-media-empty-state">
              <p className="hint muted">No images match the current filter.</p>
            </WorkspaceEmptyStateCard>
          )}
        </div>
      </div>

      <div className="panel stack workspace-section-block" data-testid="migration-operator-requirements">
        <h3>Operator Requirements</h3>
        <span className="hint muted">
          Operator Requirements are the source of truth for draft intent. AI suggestion drafts are optional helpers and
          do not affect draft generation until you move them into the operator field and save requirements.
        </span>
        <span className="hint muted">
          Suggestions use bounded source content, recommendations, audit findings, competitor context, selected media
          summary, and existing business/site context.
        </span>
        <span className="hint muted" data-testid="migration-requirements-image-reference-hint">
          Selected usable Site Images are included automatically in draft context and materialized into artifact assets.
          You do not need to paste manual @image references for normal image usage.
        </span>
        <span className="hint muted" data-testid="migration-requirements-image-reference-hint-secondary">
          Use requirements text for placement intent only (for example, hero vs gallery). Generated HTML must use
          artifact paths such as <code>assets/images/&lt;filename&gt;</code>.
        </span>
        <div className="migration-requirement-grid">
          {requirementFieldConfigs.map((config) => {
            const suggestionState = requirementSuggestions[config.field] || createEmptyRequirementSuggestionState();
            const suggestionText = suggestionState.value.trim();
            const suggestionOpen = suggestionState.open;
            return (
              <div
                key={`migration-requirement-${config.field}`}
                className="migration-requirement-field"
                data-testid={`migration-requirement-field-${config.field}`}
              >
                <label className="stack-tight">
                  <span className="hint muted">{config.label}</span>
                  <textarea
                    value={config.value}
                    onChange={(event) => config.onChange(event.target.value)}
                    rows={config.rows}
                    data-testid={`migration-requirement-operator-${config.field}`}
                  />
                </label>
                <div className="row-wrap-tight">
                  <button
                    type="button"
                    className="button button-tertiary"
                    onClick={() => void handleSuggestRequirementField(config.field)}
                    data-testid={`migration-requirement-suggest-${config.field}`}
                    disabled={busyAction === "load" || suggestionState.status === "loading"}
                  >
                    {suggestionState.status === "loading" ? "Suggesting..." : "Suggest requirement text"}
                  </button>
                  <span className="hint muted">
                    Status: {toRequirementSuggestionStatusLabel(suggestionState.status)}
                  </span>
                </div>
                <details
                  className="workspace-details-shell migration-requirement-suggestion-shell"
                  open={suggestionOpen}
                  onToggle={(event) => {
                    const open = event.currentTarget.open;
                    updateRequirementSuggestion(config.field, (current) => ({
                      ...current,
                      open,
                    }));
                  }}
                  data-testid={`migration-requirement-scratchpad-details-${config.field}`}
                >
                  <summary>AI suggestion draft</summary>
                  <div className="stack-tight">
                    <span className="hint muted">
                      Review or edit this suggestion, then copy, append, or replace the requirement field.
                    </span>
                    <textarea
                      value={suggestionState.value}
                      onChange={(event) =>
                        updateRequirementSuggestion(config.field, (current) => ({
                          ...current,
                          value: event.target.value,
                          open: true,
                        }))
                      }
                      rows={4}
                      placeholder="No suggestion yet. Click Suggest requirement text."
                      data-testid={`migration-requirement-scratchpad-${config.field}`}
                    />
                    {suggestionState.errorMessage ? (
                      <span
                        className="hint warning"
                        data-testid={`migration-requirement-suggestion-error-${config.field}`}
                      >
                        {suggestionState.errorMessage}
                      </span>
                    ) : null}
                    {suggestionState.reasonCode ? (
                      <span
                        className="hint muted"
                        data-testid={`migration-requirement-suggestion-reason-${config.field}`}
                      >
                        Reason code: {suggestionState.reasonCode}
                      </span>
                    ) : null}
                    {suggestionState.contextSourcesUsed.length > 0 ? (
                      <span className="hint muted">
                        Context sources: {suggestionState.contextSourcesUsed.join(", ")}
                      </span>
                    ) : null}
                    <div className="row-wrap-tight">
                      <button
                        type="button"
                        className="button button-secondary"
                        onClick={() => void handleRequirementSuggestionCopy(config.field)}
                        data-testid={`migration-requirement-copy-${config.field}`}
                        disabled={!suggestionText}
                      >
                        Copy
                      </button>
                      <button
                        type="button"
                        className="button button-secondary"
                        onClick={() => handleRequirementSuggestionAppend(config.field)}
                        data-testid={`migration-requirement-append-${config.field}`}
                        disabled={!suggestionText}
                      >
                        Append to field
                      </button>
                      <button
                        type="button"
                        className="button button-secondary"
                        onClick={() => handleRequirementSuggestionReplace(config.field)}
                        data-testid={`migration-requirement-replace-${config.field}`}
                        disabled={!suggestionText}
                      >
                        Replace field
                      </button>
                      <button
                        type="button"
                        className="button button-tertiary"
                        onClick={() => handleRequirementSuggestionDismiss(config.field)}
                        data-testid={`migration-requirement-dismiss-${config.field}`}
                        disabled={!suggestionText && suggestionState.status === "idle"}
                      >
                        Dismiss
                      </button>
                    </div>
                  </div>
                </details>
              </div>
            );
          })}
          <label className="stack-tight">
            <span className="hint muted">Additional requirements notes</span>
            <textarea value={requirementsNotes} onChange={(event) => setRequirementsNotes(event.target.value)} rows={4} />
          </label>
        </div>
        <WorkspaceActionBar variant="secondary">
          <button
            type="button"
            className="button button-secondary"
            onClick={() => void handleSaveRequirements()}
            disabled={busyAction === "save_requirements" || busyAction === "load"}
          >
            {busyAction === "save_requirements" ? "Saving..." : "Save Requirements"}
          </button>
        </WorkspaceActionBar>
      </div>

      <div className="panel stack workspace-section-block" data-testid="migration-reused-context">
        <h3>Reused MBSRN Context</h3>
        <span className="hint muted">
          Informational context availability summary. Operator actions remain in workflow sections above.
        </span>
        <div className="migration-compact-inline-list" data-testid="migration-reused-context-compact">
          <div className="migration-compact-inline-item">
            <span className="migration-compact-label">Audit</span>
            <span
              className={
                auditContextStatus === "Available"
                  ? "badge badge-success"
                  : auditContextStatus === "Stale"
                    ? "badge badge-warn"
                    : "badge badge-muted"
              }
              data-testid="migration-reused-context-audit-status"
            >
              {auditContextStatus}
            </span>
            <span className="hint muted" data-testid="migration-reused-context-audit-last-run">
              Last run: {auditContextLastRun || "n/a"}
            </span>
          </div>
          <div className="migration-compact-inline-item">
            <span className="migration-compact-label">Recommendations</span>
            <span
              className={
                recommendationContextStatus === "Available"
                  ? "badge badge-success"
                  : recommendationContextStatus === "Stale"
                    ? "badge badge-warn"
                    : "badge badge-muted"
              }
              data-testid="migration-reused-context-recommendations-status"
            >
              {recommendationContextStatus}
            </span>
            <span className="hint muted" data-testid="migration-reused-context-recommendations-last-run">
              Last run: {recommendationContextLastRun || "n/a"}
            </span>
          </div>
          <div className="migration-compact-inline-item">
            <span className="migration-compact-label">Competitors</span>
            <span
              className={
                competitorContextStatus === "Available"
                  ? "badge badge-success"
                  : competitorContextStatus === "Stale"
                    ? "badge badge-warn"
                    : "badge badge-muted"
              }
              data-testid="migration-reused-context-competitors-status"
            >
              {competitorContextStatus}
            </span>
            <span className="hint muted" data-testid="migration-reused-context-competitors-last-run">
              Last run: {competitorContextLastRun || "n/a"}
            </span>
          </div>
        </div>
        <details className="workspace-details-shell migration-context-details">
          <summary className="hint muted">Show context detail</summary>
          <div className="stack-tight">
            <span className="hint">Audit: {auditContextLabel}</span>
            <span className="hint">Recommendations: {recommendationContextLabel}</span>
            <span className="hint">Competitors: {competitorContextLabel}</span>
          </div>
        </details>
      </div>

      <div className="panel stack workspace-section-block" data-testid="migration-draft-input-summary">
        <h3>Draft Inputs / AI Context</h3>
        <span className="hint muted">
          Informational bounded metadata only. This summary excludes raw secrets and media bytes.
        </span>
        <div className="migration-compact-summary-grid">
          <div className="panel panel-compact stack-tight migration-compact-summary-block" data-testid="migration-draft-input-context-signals">
            <strong>Context Signals</strong>
            <div className="migration-compact-kv">
              <span className="migration-compact-kv-row">
                <span className="migration-compact-kv-label">Recommendation context</span>
                <span className="migration-compact-kv-value">
                  {(asNonNegativeInt(draftInputSummary.recommendations_included_count) ?? 0)}
                  {" of "}
                  {(asNonNegativeInt(draftInputSummary.recommendations_available_count)
                    ?? asNonNegativeInt(draftInputSummary.recommendations_included_count)
                    ?? 0)}
                  {" included"}
                </span>
              </span>
              <span className="migration-compact-kv-row">
                <span className="migration-compact-kv-label">Recommendation basis</span>
                <span className="migration-compact-kv-value">
                  {(asStringOrNull(draftInputSummary.recommendations_context_basis) || "interpreted_audit_context").replace(/_/g, " ")}
                </span>
              </span>
              <span className="migration-compact-kv-row">
                <span className="migration-compact-kv-label">Recommendation categories</span>
                <span className="migration-compact-kv-value">{recommendationCategoriesSummaryValue}</span>
              </span>
              <span className="migration-compact-kv-row" data-testid="migration-draft-input-top-recommendations">
                <span className="migration-compact-kv-label">Top recommendation titles</span>
                <span className="migration-compact-kv-value">{topRecommendationTitlesSummaryValue}</span>
              </span>
              <span className="migration-compact-kv-row">
                <span className="migration-compact-kv-label">GSC signals included</span>
                <span className="migration-compact-kv-value">
                  {formatBooleanStateLabel(asBooleanOrNull(draftInputSummary.gsc_signals_included))}
                </span>
              </span>
              <span className="migration-compact-kv-row">
                <span className="migration-compact-kv-label">GA4 signals included</span>
                <span className="migration-compact-kv-value">
                  {formatBooleanStateLabel(asBooleanOrNull(draftInputSummary.ga4_signals_included))}
                </span>
              </span>
              <span className="migration-compact-kv-row">
                <span className="migration-compact-kv-label">Competitor profiles included</span>
                <span className="migration-compact-kv-value">
                  {asNonNegativeInt(draftInputSummary.competitor_profiles_included_count) ?? 0}
                </span>
              </span>
              <span className="migration-compact-kv-row">
                <span className="migration-compact-kv-label">Operator requirements included</span>
                <span className="migration-compact-kv-value">
                  {formatBooleanStateLabel(asBooleanOrNull(draftInputSummary.operator_requirements_included))}
                </span>
              </span>
              <span className="migration-compact-kv-row">
                <span className="migration-compact-kv-label">Enriched supporting context included</span>
                <span className="migration-compact-kv-value">
                  {formatBooleanStateLabel(asBooleanOrNull(draftInputSummary.enriched_business_context_included))}
                </span>
              </span>
              <span className="migration-compact-kv-row">
                <span className="migration-compact-kv-label">Raw audit findings included</span>
                <span className="migration-compact-kv-value">
                  {(() => {
                    const rawAuditCount =
                      asNonNegativeInt(draftInputSummary.raw_audit_findings_included_count)
                      ?? asNonNegativeInt(draftInputSummary.audit_findings_included_count)
                      ?? 0;
                    const recommendationBasis = (
                      asStringOrNull(draftInputSummary.recommendations_context_basis)
                      || "interpreted_audit_context"
                    ).trim().toLowerCase();
                    if (rawAuditCount === 0 && recommendationBasis === "interpreted_audit_context") {
                      return "Not directly included";
                    }
                    return rawAuditCount;
                  })()}
                </span>
              </span>
            </div>
            {(asStringOrNull(draftInputSummary.raw_audit_findings_note)
              || "Recommendations summarize audit evidence for draft context.") ? (
              <span className="hint muted" data-testid="migration-draft-input-audit-context-note">
                {asStringOrNull(draftInputSummary.raw_audit_findings_note)
                  || "Recommendations summarize audit evidence for draft context."}
              </span>
            ) : null}
            {topRecommendationTitlesCompact.truncated ? (
              <details
                className="workspace-details-shell migration-compact-details"
                data-testid="migration-draft-input-top-recommendations-details"
              >
                <summary className="hint muted">Show full recommendation titles</summary>
                {topRecommendationTitles.length > 0 ? (
                  <ul className="stack-tight">
                    {topRecommendationTitles.map((title, index) => (
                      <li key={`draft-input-top-recommendation-${index}`} className="hint">
                        {title}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <span className="hint muted">No recommendation titles available.</span>
                )}
              </details>
            ) : null}
          </div>
          <div className="panel panel-compact stack-tight migration-compact-summary-block" data-testid="migration-draft-input-bounded-provenance">
            <strong>Bounded Provenance</strong>
            <div className="migration-compact-kv">
              <span className="migration-compact-kv-row">
                <span className="migration-compact-kv-label">Media context included</span>
                <span className="migration-compact-kv-value">
                  {formatBooleanStateLabel(asBooleanOrNull(draftInputSummary.media_context_included))}
                </span>
              </span>
              <span className="migration-compact-kv-row">
                <span className="migration-compact-kv-label">Media context trimmed</span>
                <span className="migration-compact-kv-value">
                  {formatBooleanStateLabel(asBooleanOrNull(draftInputSummary.media_context_trimmed))}
                </span>
              </span>
              <span className="migration-compact-kv-row">
                <span className="migration-compact-kv-label">AI context blocks included</span>
                <span className="migration-compact-kv-value">
                  {asNonNegativeInt(draftInputSummary.ai_context_source_count) ?? 0}
                </span>
              </span>
              <span className="migration-compact-kv-row">
                <span className="migration-compact-kv-label">AI context trimmed</span>
                <span className="migration-compact-kv-value">
                  {formatBooleanStateLabel(asBooleanOrNull(draftInputSummary.ai_context_trimmed))}
                </span>
              </span>
              <span className="migration-compact-kv-row" data-testid="migration-draft-input-recommendation-trimmed">
                <span className="migration-compact-kv-label">Recommendation context trimmed</span>
                <span className="migration-compact-kv-value">
                  {formatBooleanStateLabel(asBooleanOrNull(draftInputSummary.recommendations_context_trimmed))}
                </span>
              </span>
              <span className="migration-compact-kv-row" data-testid="migration-draft-input-context-budget-summary">
                <span className="migration-compact-kv-label">Draft context trimmed</span>
                <span className="migration-compact-kv-value">
                  {formatBooleanStateLabel(
                    asBooleanOrNull(draftInputSummary.ai_context_trimmed)
                    || asBooleanOrNull(draftInputSummary.media_context_trimmed)
                    || asBooleanOrNull(draftInputSummary.recommendations_context_trimmed),
                  )}
                </span>
              </span>
              <span className="migration-compact-kv-row" data-testid="migration-draft-input-generation-budget-profile">
                <span className="migration-compact-kv-label">Generation budget</span>
                <span className="migration-compact-kv-value">
                  {asStringOrNull(draftInputSummary.generation_budget_profile) || "standard"}
                </span>
              </span>
              <span className="migration-compact-kv-row" data-testid="migration-draft-input-variation-level">
                <span className="migration-compact-kv-label">Variation level</span>
                <span className="migration-compact-kv-value">
                  {asStringOrNull(draftInputSummary.generation_variation_level) || "balanced"}
                </span>
              </span>
              <span className="migration-compact-kv-row" data-testid="migration-draft-input-generation-context-budget">
                <span className="migration-compact-kv-label">Context budget</span>
                <span className="migration-compact-kv-value">
                  {(() => {
                    const value = asNonNegativeInt(draftInputSummary.generation_context_budget_chars);
                    return value && value > 0 ? `${value.toLocaleString()} chars` : "default";
                  })()}
                </span>
              </span>
              <span className="migration-compact-kv-row" data-testid="migration-draft-input-page-file-limit">
                <span className="migration-compact-kv-label">Page/file limit</span>
                <span className="migration-compact-kv-value">
                  {(() => {
                    const pageLimit = asNonNegativeInt(draftInputSummary.generation_page_limit);
                    const fileLimit = asNonNegativeInt(draftInputSummary.generation_file_limit);
                    if ((pageLimit || 0) > 0 || (fileLimit || 0) > 0) {
                      return `${pageLimit || 0}/${fileLimit || 0}`;
                    }
                    return "default";
                  })()}
                </span>
              </span>
              <span className="migration-compact-kv-row" data-testid="migration-draft-input-generation-safety-profile">
                <span className="migration-compact-kv-label">Generation safety profile</span>
                <span className="migration-compact-kv-value">{generationSafetyProfile.replace(/_/g, " ")}</span>
              </span>
              <span className="migration-compact-kv-row" data-testid="migration-draft-input-generation-provider-timeout">
                <span className="migration-compact-kv-label">Provider timeout</span>
                <span className="migration-compact-kv-value">
                  {generationProviderTimeoutSeconds !== null ? `${generationProviderTimeoutSeconds}s` : "default"}
                </span>
              </span>
              <span className="migration-compact-kv-row" data-testid="migration-draft-input-generation-preflight-mode">
                <span className="migration-compact-kv-label">Preflight mode</span>
                <span className="migration-compact-kv-value">
                  {(generationPreflightMode || "compact_fallback").replace(/_/g, " ")}
                </span>
              </span>
              <span className="migration-compact-kv-row" data-testid="migration-draft-input-generation-max-final-input">
                <span className="migration-compact-kv-label">Max final input chars</span>
                <span className="migration-compact-kv-value">
                  {generationMaxFinalInputChars !== null ? generationMaxFinalInputChars.toLocaleString() : "n/a"}
                </span>
              </span>
              <span className="migration-compact-kv-row" data-testid="migration-draft-input-generation-max-difficulty">
                <span className="migration-compact-kv-label">Max difficulty score</span>
                <span className="migration-compact-kv-value">
                  {generationMaxDifficultyScore !== null ? generationMaxDifficultyScore : "n/a"}
                </span>
              </span>
              <span className="migration-compact-kv-row" data-testid="migration-draft-input-generation-compact-limits">
                <span className="migration-compact-kv-label">Compact limits (pages/media/reco)</span>
                <span className="migration-compact-kv-value">
                  {generationCompactPageLimit !== null ||
                  generationCompactMediaAssetLimit !== null ||
                  generationCompactRecommendationLimit !== null
                    ? `${generationCompactPageLimit ?? 0}/${generationCompactMediaAssetLimit ?? 0}/${generationCompactRecommendationLimit ?? 0}`
                    : "default"}
                </span>
              </span>
              <span className="migration-compact-kv-row" data-testid="migration-draft-input-generation-compact-enabled">
                <span className="migration-compact-kv-label">Compact fallback enabled</span>
                <span className="migration-compact-kv-value">
                  {formatBooleanStateLabel(generationCompactFallbackEnabled)}
                </span>
              </span>
              <span className="migration-compact-kv-row" data-testid="migration-draft-input-generation-compact-attempted">
                <span className="migration-compact-kv-label">Compact fallback attempted</span>
                <span className="migration-compact-kv-value">
                  {formatBooleanStateLabel(generationCompactFallbackAttempted)}
                </span>
              </span>
              <span className="migration-compact-kv-row" data-testid="migration-draft-input-generation-budget-capped">
                <span className="migration-compact-kv-label">Budget capped</span>
                <span className="migration-compact-kv-value">
                  {formatBooleanStateLabel(generationBudgetCapped)}
                </span>
              </span>
              {(generationBudgetCapped || generationBudgetCapReason) ? (
                <span className="migration-compact-kv-row" data-testid="migration-draft-input-generation-cap-reason">
                  <span className="migration-compact-kv-label">Cap reason</span>
                  <span className="migration-compact-kv-value">
                    {generationBudgetCapReason
                      ? generationBudgetCapReason.replace(/_/g, " ")
                      : "backend cap applied"}
                  </span>
                </span>
              ) : null}
              {generationPreflightBlocked ? (
                <span className="migration-compact-kv-row" data-testid="migration-draft-input-generation-preflight-blocked">
                  <span className="migration-compact-kv-label">Preflight blocked</span>
                  <span className="migration-compact-kv-value">
                    Yes{generationPreflightBlockReason ? ` (${generationPreflightBlockReason.replace(/_/g, " ")})` : ""}
                  </span>
                </span>
              ) : null}
              {draftAILargestContextBlock ? (
                <span className="migration-compact-kv-row" data-testid="migration-draft-input-largest-block">
                  <span className="migration-compact-kv-label">Largest included block</span>
                  <span className="migration-compact-kv-value">
                    {draftAILargestContextBlock.replace(/_/g, " ")}
                    {typeof draftAILargestContextBlockSizeChars === "number"
                      ? ` (${draftAILargestContextBlockSizeChars.toLocaleString()} chars)`
                      : ""}
                  </span>
                </span>
              ) : null}
              {generationBlockedReasonSummary ? (
                <span className="migration-compact-kv-row" data-testid="migration-draft-input-budget-blocked-reason">
                  <span className="migration-compact-kv-label">Blocked because</span>
                  <span className="migration-compact-kv-value">{generationBlockedReasonSummary}</span>
                </span>
              ) : null}
            </div>
            {generationPreflightBlockedMessage ? (
              <span className="hint warning" data-testid="migration-draft-input-generation-preflight-blocked-message">
                {generationPreflightBlockedMessage}
              </span>
            ) : null}
            {providerTimeoutActionMessage ? (
              <span className="hint warning" data-testid="migration-draft-input-provider-timeout-message">
                {providerTimeoutActionMessage}
              </span>
            ) : null}
          </div>
        </div>
        <span className="hint" data-testid="migration-selected-media-context-summary">
          Included in next draft: {selectedUsableMediaAssetsCount} selected usable image
          {selectedUsableMediaAssetsCount === 1 ? "" : "s"}.
        </span>
        <span className="hint" data-testid="migration-artifact-media-materialization-summary">
          Materialized into artifact files: {artifactMediaMaterializedAssetsCount} of {artifactMediaSelectedAssetsCount}
          {" "}selected image{artifactMediaSelectedAssetsCount === 1 ? "" : "s"}.
        </span>
        <span className="hint" data-testid="migration-artifact-media-reference-summary">
          Referenced by generated pages: {artifactMediaReferencedPathsCount}. Unresolved references: {artifactMediaUnresolvedReferencesCount}.
        </span>
        {artifactMediaSelectedNotMaterializedCount > 0 ? (
          <span className="hint warning" data-testid="migration-artifact-media-not-materialized-warning">
            {artifactMediaSelectedNotMaterializedCount} selected image
            {artifactMediaSelectedNotMaterializedCount === 1 ? "" : "s"} were not materialized into artifact assets.
          </span>
        ) : null}
        {artifactMediaUnresolvedReferencesCount > 0 ? (
          <span className="hint warning" data-testid="migration-artifact-media-unresolved-warning">
            Generated HTML still contains unresolved image references. Publish/deploy remains blocked until resolved.
          </span>
        ) : null}
        {artifactMediaUnreferencedMaterializedCount > 0 ? (
          <span className="hint muted" data-testid="migration-artifact-media-unreferenced-note">
            {artifactMediaUnreferencedMaterializedCount} materialized image asset
            {artifactMediaUnreferencedMaterializedCount === 1 ? "" : "s"} are currently unused by generated pages.
          </span>
        ) : null}
        {artifactMediaReadyForPublishDeploy === false && artifactMediaBlockerCodes.length > 0 ? (
          <span className="hint warning" data-testid="migration-artifact-media-readiness-blockers">
            Media readiness blockers: {artifactMediaBlockerCodes.slice(0, 4).join(", ").replace(/_/g, " ")}.
          </span>
        ) : null}
        <span className="hint muted">
          Media counts/actions are managed in Section B. Provider execution metadata is available in Advanced Diagnostics.
        </span>
      </div>

      </MigrationMediaSection>

      <MigrationDraftReadinessSection>

      <div className="panel stack workspace-section-block">
        <h3>Draft Artifact Generation</h3>
        <span className="hint muted">
          Operator Actions: generate/retry draft here. Approval, publish, and deploy actions remain explicit in later sections.
        </span>
        <div className="panel panel-compact stack-tight" data-testid="migration-draft-readiness">
          <strong>Preflight Readiness</strong>
          <span className="hint">Status: {draftReadinessStatusLabel}</span>
          <span className="hint">Readiness score: {draftReadiness.score}/100</span>
          <span className={draftReadinessToneClass}>{draftReadiness.summary}</span>
          {mediaRequiredByOperator && !mediaRequirementSatisfied ? (
            <span className="hint warning" data-testid="migration-media-required-readiness-warning">
              {usefulDiscoveredButNotImportedOrSelected
                ? "Useful source images were discovered. Use images in draft before approving the draft."
                : "Real/existing media was requested, but no usable included image is in draft context yet."}
            </span>
          ) : null}
          {mediaRequiredByOperator ? (
            <span className="hint muted">
              Usable images included in draft: {selectedUsableMediaAssetsCount}
            </span>
          ) : null}
          {draftReadiness.reasons.length > 0 ? (
            <ul>
              {draftReadiness.reasons.slice(0, 6).map((reason) => (
                <li key={`${reason.severity}-${reason.code || reason.message}`}>{reason.message}</li>
              ))}
            </ul>
          ) : null}
        </div>
        <div className="panel panel-compact stack-tight" data-testid="migration-provider-compatibility">
          <strong>Provider Compatibility</strong>
          <span className="hint">Status: {draftProviderCompatibilityStatusLabel}</span>
          <span className={draftProviderCompatibilityToneClass}>
            {draftProviderCompatibility.operatorMessage}
          </span>
        </div>
        <WorkspaceActionBar variant="primary">
          <button
            type="button"
            className="button button-primary"
            onClick={() => void handleGenerateArtifacts()}
            disabled={busyAction === "generate" || busyAction === "load" || draftGenerationBlocked}
          >
            {busyAction === "generate" ? "Generating..." : "Generate Draft Mockup"}
          </button>
        </WorkspaceActionBar>
        {draftGenerationBlocked ? (
          <span className="hint warning">{draftGenerationBlockedMessage}</span>
        ) : null}
      </div>

      </MigrationDraftReadinessSection>

      <MigrationArtifactReviewSection>

      <div className="panel stack workspace-section-block" data-testid="migration-artifact-review-section">
        <h3>Draft Artifact Review</h3>
        <label className="stack-tight">
          <span className="hint muted">Selected artifact version</span>
          <select
            aria-label="Artifact version"
            value={selectedArtifactVersionId}
            onChange={(event) => {
              setSelectedArtifactVersionId(event.target.value);
              setSelectedFilePath("");
            }}
          >
            <option value="">Select...</option>
            {artifactVersions.map((artifact) => (
              <option key={artifact.id} value={artifact.id}>
                v{artifact.version} - {artifact.status} - approval {artifact.approval_status}
              </option>
            ))}
          </select>
        </label>
        {selectedArtifact ? (
          <>
            <div className="row-wrap-tight" data-testid="migration-draft-review-actions-row">
              <button
                type="button"
                className="button button-primary"
                onClick={() => setDraftPreviewOpen((current) => !current)}
                disabled={!draftPreview.available}
                data-testid="migration-preview-draft-button"
              >
                {draftPreviewOpen ? "Hide preview" : "Show preview"}
              </button>
              <button
                type="button"
                className="button button-secondary"
                onClick={() => void handleApproveSelectedArtifact()}
                disabled={isActionInFlight || !canApproveSelectedArtifact}
                data-testid="migration-approve-draft-button"
              >
                {busyAction === "approve" ? "Approving..." : "Approve Selected Draft"}
              </button>
              <button
                type="button"
                className="button button-tertiary"
                onClick={() => void handleDeleteSelectedArtifact()}
                disabled={isActionInFlight || !canDeleteSelectedArtifact}
                data-testid="migration-delete-draft-button"
              >
                {busyAction === "delete_draft" ? "Deleting..." : "Delete Selected Draft"}
              </button>
            </div>
            <div className="panel panel-compact stack-tight" data-testid="migration-artifact-quality-summary">
              <strong>Artifact Quality Summary</strong>
              {artifactQualitySummary ? (
                <>
                  <span
                    className={artifactQualityBadgeClass(artifactQualitySummary.qualityStatus)}
                    data-testid="migration-artifact-quality-status"
                  >
                    Quality: {artifactQualityStatusLabel(artifactQualitySummary.qualityStatus)}
                  </span>
                  <span className="hint">{artifactQualitySummary.operatorSummary}</span>
                  {requiredMediaQualityIssue ? (
                    <span className="hint warning" data-testid="migration-artifact-quality-required-media-warning">
                      {requiredMediaQualityIssue.description}
                    </span>
                  ) : null}
                  {artifactQualitySummary.issues.length > 0 ? (
                    <>
                      <strong className="hint muted">Top issues</strong>
                      <ul className="migration-quality-issue-list" data-testid="migration-artifact-quality-issues">
                        {artifactQualitySummary.issues.slice(0, 3).map((issue, index) => (
                          <li className="migration-quality-issue-item" key={`artifact-quality-top-${index}-${issue.type}`}>
                            <span className="migration-quality-issue-type">{toArtifactQualityIssueTypeLabel(issue.type)}</span>
                            <span>{issue.description}</span>
                          </li>
                        ))}
                      </ul>
                      {artifactQualitySummary.issues.length > 3 ? (
                        <details className="migration-quality-details">
                          <summary className="hint muted">
                            Show all issues ({artifactQualitySummary.issues.length})
                          </summary>
                          <ul className="migration-quality-issue-list">
                            {artifactQualitySummary.issues.slice(3).map((issue, index) => (
                              <li className="migration-quality-issue-item" key={`artifact-quality-all-${index}-${issue.type}`}>
                                <span className="migration-quality-issue-type">{toArtifactQualityIssueTypeLabel(issue.type)}</span>
                                <span>{issue.description}</span>
                              </li>
                            ))}
                          </ul>
                        </details>
                      ) : null}
                    </>
                  ) : (
                    <span className="hint muted">No quality issues detected.</span>
                  )}
                </>
              ) : (
                <span className="hint muted">No artifact quality evaluation available.</span>
              )}
            </div>
            <span className="hint muted">
              {draftPreview.available
                ? "Draft preview only. Not published and not deployed."
                : draftPreview.reason || "Preview unavailable for this artifact."}
            </span>
            {!canDeleteSelectedArtifact && selectedArtifact ? (
              <span className="hint muted">{selectedArtifactDeleteBlockedReason}</span>
            ) : null}
            <div className="panel panel-compact stack-tight">
              <strong>Strategy Summary</strong>
              <p>{selectedArtifact.strategy_summary || "No strategy summary provided."}</p>
              {selectedArtifact.status === "partial" ? (
                <span className="hint warning" data-testid="migration-partial-draft-indicator">
                  Partial draft generated.
                </span>
              ) : null}
            </div>
            <div className="panel panel-compact stack-tight migration-draft-inspection-surface" data-testid="migration-draft-inspection-surface">
              <strong>Draft Preview</strong>
              <span className="hint muted">
                One read-only preview surface. Choose a page/file in the left rail and review the sandboxed web output.
              </span>
              <span className="hint muted" data-testid="migration-draft-preview-auth-guidance">
                Draft preview route requires operator session context. External or app-auth links are blocked inside preview.
              </span>
              {draftPreviewOpen && draftPreview.available ? (
                <div className="migration-draft-preview-layout" data-testid="migration-draft-preview-layout">
                  <div className="panel panel-compact stack-tight migration-draft-preview-rail" data-testid="migration-file-tree">
                    <strong>Pages and files</strong>
                    {previewEntries.length > 0 ? (
                      <div className="migration-draft-preview-rail-list" data-testid="migration-page-map-list">
                        {previewEntries.map((entry) => (
                          (() => {
                            const normalizedTitle = entry.title.trim();
                            const normalizedPath = entry.path.trim();
                            const hasSecondaryPath =
                              normalizedTitle.length > 0
                              && normalizedPath.length > 0
                              && normalizedTitle.toLowerCase() !== normalizedPath.toLowerCase();
                            return (
                          <button
                            key={entry.path}
                            type="button"
                            className={
                              entry.path === (activeDraftPreviewPage?.path || "")
                                ? "button button-tertiary migration-draft-preview-rail-item active"
                                : "button button-tertiary migration-draft-preview-rail-item"
                            }
                            onClick={() => handleSelectArtifactFile(entry.path)}
                            data-testid={`migration-preview-entry-${entry.path}`}
                          >
                            <span className="migration-draft-preview-entry-title">
                              {normalizedTitle || normalizedPath}
                            </span>
                            {hasSecondaryPath ? (
                              <span className="migration-draft-preview-entry-path">{normalizedPath}</span>
                            ) : null}
                          </button>
                            );
                          })()
                        ))}
                      </div>
                    ) : (
                      <WorkspaceEmptyStateCard compact={true}>
                        <p className="hint muted">No previewable pages.</p>
                      </WorkspaceEmptyStateCard>
                    )}
                  </div>
                  <div className="panel panel-compact stack-tight migration-draft-preview-pane" data-testid="migration-file-preview">
                    <strong>Web Preview</strong>
                    <span className="hint muted">
                      {activeDraftPreviewPage ? `Selected file: ${activeDraftPreviewPage.path}` : "Select a page to preview."}
                    </span>
                    {activeDraftPreviewPage ? (
                      <iframe
                        ref={draftPreviewFrameRef}
                        title="Migration generated file preview"
                        className="migration-draft-preview-frame"
                        sandbox=""
                        srcDoc={activeDraftPreviewPage.html || ""}
                        referrerPolicy="no-referrer"
                        data-testid="migration-file-preview-iframe"
                      />
                    ) : (
                      <WorkspaceEmptyStateCard compact={true}>
                        <p className="hint muted">Preview unavailable for this artifact.</p>
                      </WorkspaceEmptyStateCard>
                    )}
                  </div>
                </div>
              ) : (
                <span className="hint muted">Preview hidden. Click Show preview to inspect generated pages.</span>
              )}
            </div>
          </>
        ) : (
          <WorkspaceEmptyStateCard data-testid="migration-artifact-review-empty-state">
            <p className="hint muted">No artifact version selected.</p>
          </WorkspaceEmptyStateCard>
        )}
      </div>

      </MigrationArtifactReviewSection>

      <MigrationPublishDeploySection>

      <div className="panel stack workspace-section-block" data-testid="migration-publish-deploy-section">
        <h3>Publish and Deploy Controls</h3>
        <div className="workspace-status-callout stack-tight">
          <span className="hint muted">
            Rollback is explicit: select a previously approved artifact and run publish/deploy again.
          </span>
          <span className="hint muted">
            Publish writes approved artifacts to GitHub only. Deploy remains a separate explicit request.
          </span>
        </div>
        <div className="migration-publish-deploy-layout-stack">
          <div className="panel panel-compact migration-publish-deploy-layout" data-testid="migration-publish-layout">
            <div className="migration-publish-deploy-column stack" data-testid="migration-publish-layout-left">
              <div className="panel panel-compact stack" data-testid="migration-destination-summary">
                <strong>Destination Summary</strong>
                <div className="panel panel-compact stack-tight migration-publish-deploy-summary-card">
                  <strong>Publish Destination</strong>
                  <span className="hint">Repository: {effectivePublishRepository || "Not configured"}</span>
                  <span className="hint">Branch: {effectivePublishBranch || "Not configured"}</span>
                  <span className="hint">Artifact root: {effectivePublishArtifactRoot || "/"}</span>
                  <span className="hint">State: {publishTargetStateLabel}</span>
                  <span className="hint">
                    Expected URL: {destinationSummary.publishExpectedPublishedUrl || destinationSummary.deployExpectedPublishUrl || "Not available"}
                  </span>
                  {publishPrimaryBlockerMessage ? (
                    <span className="hint warning" data-testid="migration-destination-publish-blocker">
                      {publishPrimaryBlockerMessage}
                    </span>
                  ) : null}
                  {publishPrimaryWarningMessage ? (
                    <span className="hint warning" data-testid="migration-destination-publish-warning">
                      Warning: {publishPrimaryWarningMessage}
                    </span>
                  ) : null}
                </div>
                <span className="hint muted">
                  Full destination/runtime/config evidence is available under Advanced Diagnostics.
                </span>
              </div>

              <div className="panel panel-compact stack" data-testid="migration-publish-readiness">
                <strong>Publish Readiness</strong>
                <span className="hint">Ready: {publishReady ? "Yes" : "No"}</span>
                <span
                  className={publishReady ? "hint success" : "hint warning"}
                  data-testid="migration-publish-readiness-primary-action"
                >
                  {publishReady
                    ? "Action: Publish the selected approved draft when operator review is complete."
                    : `Blocker: ${publishPrimaryReadinessMessage || "Publish target is not ready."}`}
                </span>
                {!publishReady && publishFailureCategory ? (
                  <span className="hint warning">Failure category: {toFailureCategoryLabel(publishFailureCategory)}</span>
                ) : null}
                {!publishReady && publishSecondaryFailureMessage ? (
                  <span className="hint warning">{publishSecondaryFailureMessage}</span>
                ) : null}
                {publishReady && publishPrimaryWarningMessage ? (
                  <span className="hint warning" data-testid="migration-publish-readiness-warning">
                    {publishPrimaryWarningMessage}
                  </span>
                ) : null}
              </div>
            </div>

            <div className="migration-publish-deploy-column stack" data-testid="migration-publish-layout-right">
              <div className="panel panel-compact stack" data-testid="migration-publish-target-summary">
                <strong>GitHub Publish Target</strong>
                <span className="hint muted" data-testid="migration-publish-target-admin-boundary">
                  Admin controls GitHub account/owner. Operators control repository name and optional branch override.
                </span>
                <span className="hint">{adminPublishReadyLabel}</span>
                <label className="stack-tight">
                  <span className="hint muted">Repository name (Operator-owned)</span>
                  <input
                    value={publishRepoName}
                    onChange={(event) => setPublishRepoName(event.target.value)}
                    placeholder="tnmfire"
                  />
                </label>
                <label className="stack-tight">
                  <span className="hint muted">Branch override (optional)</span>
                  <input value={publishBranch} onChange={(event) => setPublishBranch(event.target.value)} placeholder="main" />
                </label>
                <button
                  type="button"
                  className="button button-secondary"
                  onClick={() => void handleSavePublishConfig()}
                  disabled={busyAction === "save_publish_config" || busyAction === "load"}
                >
                  {busyAction === "save_publish_config" ? "Saving..." : "Save Publish Repository"}
                </button>
              </div>

              <div className="panel panel-compact stack" data-testid="migration-publish-actions">
                <strong>Publish</strong>
                {publishRepoAdoptionRequired ? (
                  <div className="panel panel-compact stack-tight" data-testid="migration-repo-adoption-panel">
                    <span className="hint warning">
                      This repository exists but is not marked as MBSRN-managed. Adopt it to allow MBSRN to publish into it.
                    </span>
                    <button
                      type="button"
                      className="button button-secondary"
                      onClick={() => void handleAdoptPublishRepository()}
                      disabled={isActionInFlight}
                      data-testid="migration-adopt-repository-button"
                    >
                      {busyAction === "adopt_repository" ? "Adopting..." : "Adopt repository"}
                    </button>
                    <span className="hint muted">
                      This writes an MBSRN management marker to the repository. After adoption, MBSRN may update managed site files.
                    </span>
                  </div>
                ) : null}
                <label className="link-row">
                  <input type="checkbox" checked={publishDryRun} onChange={(event) => setPublishDryRun(event.target.checked)} />
                  <span>Dry run only</span>
                </label>
                <input
                  value={publishCommitMessage}
                  onChange={(event) => setPublishCommitMessage(event.target.value)}
                  placeholder="Commit message (optional)"
                />
                <input
                  value={publishAnalyticsOverride}
                  onChange={(event) => setPublishAnalyticsOverride(event.target.value)}
                  placeholder="GA measurement override (optional)"
                />
                <button
                  type="button"
                  className="button button-primary"
                  onClick={() => void handlePublishSelectedArtifact()}
                  disabled={isActionInFlight || !canPublishSelectedArtifact}
                >
                  {busyAction === "publish" ? "Publishing..." : "Publish Approved Draft to GitHub"}
                </button>
              </div>
            </div>
          </div>

          <div className="panel panel-compact migration-publish-deploy-layout" data-testid="migration-deploy-layout">
            <div className="migration-publish-deploy-column stack" data-testid="migration-deploy-layout-left">
              <div className="panel panel-compact stack" data-testid="migration-deploy-target-summary">
                <strong>GKE Deploy Target</strong>
                <span className="hint muted" data-testid="migration-deploy-target-admin-boundary">
                  Admin controls deploy repository/workflow routing. Operators can enable deploy for this workspace and
                  review effective target diagnostics.
                </span>
                <WorkspaceMetadataGrid data-testid="migration-deploy-target-readonly">
                  <WorkspaceMetadataItem label="Effective repository">
                    {deployTraceRepo || effectivePublishRepository || "Not configured"}
                  </WorkspaceMetadataItem>
                  <WorkspaceMetadataItem label="Effective ref / branch">
                    {deployTraceRef || effectivePublishBranch || "Not configured"}
                  </WorkspaceMetadataItem>
                  <WorkspaceMetadataItem label="Workflow identifier">
                    {deployWorkflowIdentifier || "Not configured"}
                  </WorkspaceMetadataItem>
                  <WorkspaceMetadataItem label="Target environment key">
                    {deployTargetEnvironmentKey || "Not available"}
                  </WorkspaceMetadataItem>
                  <WorkspaceMetadataItem label="Preview URL">
                    {destinationSummary.deployPreviewUrl || destinationSummary.publishExpectedPublishedUrl || "Not available"}
                  </WorkspaceMetadataItem>
                  <WorkspaceMetadataItem label="Deploy evidence state">
                    {deployTargetStateLabel}
                  </WorkspaceMetadataItem>
                  <WorkspaceMetadataItem label="Live URL (current)">
                    {currentLiveUrl || destinationSummary.deployResolvedLiveUrl || "Not yet confirmed"}
                  </WorkspaceMetadataItem>
                  <WorkspaceMetadataItem label="Current evidence source">
                    {currentLiveRuntimeSource || destinationSummary.deployUrlSource || "unknown"}
                  </WorkspaceMetadataItem>
                  <WorkspaceMetadataItem label="Current HTTPS ready">
                    {formatBooleanStateLabel(currentDeployHttpsReady ?? deployHttpsReady)}
                  </WorkspaceMetadataItem>
                </WorkspaceMetadataGrid>
                {currentLiveHealthySelectedWorkflowFailureNote ? (
                  <span className="hint" data-testid="migration-deploy-current-live-note">
                    {currentLiveHealthySelectedWorkflowFailureNote}
                  </span>
                ) : null}
                {deploySummaryBlockerMessage ? (
                  <span className="hint warning" data-testid="migration-destination-deploy-blocker">
                    {deploySummaryBlockerMessage}
                  </span>
                ) : null}
              </div>

              <div className="panel panel-compact stack" data-testid="migration-deploy-readiness">
                <strong>Deploy Readiness</strong>
                <span className="hint">Ready: {deployReady ? "Yes" : "No"}</span>
                <span
                  className={deployReady ? "hint success" : "hint warning"}
                  data-testid="migration-deploy-readiness-primary-action"
                >
                  {deployReady
                    ? "Action: Run deploy for the selected approved and published draft."
                    : `Blocker: ${deployPrimaryReadinessMessage || "Deploy target is not ready."}`}
                </span>
                {currentLiveHealthySelectedWorkflowFailureNote ? (
                  <span className="hint" data-testid="migration-deploy-readiness-current-live-note">
                    {currentLiveHealthySelectedWorkflowFailureNote}
                  </span>
                ) : null}
                {!deployReady ? (
                  <>
                    {managedGkeConfigGuidance ? (
                      <span className="hint warning" data-testid="migration-managed-gke-config-guidance-readiness">
                        {managedGkeConfigGuidance}
                      </span>
                    ) : null}
                    {privateImageAuthRequired !== null ? (
                      <span className="hint" data-testid="migration-private-image-auth-required-readiness">
                        Private managed image auth required: {formatBooleanStateLabel(privateImageAuthRequired)}
                      </span>
                    ) : null}
                    {privateImageCredentialsAvailableInControlPlane !== null ? (
                      <span className="hint" data-testid="migration-private-image-credentials-control-plane-readiness">
                        Control-plane GHCR credentials available:{" "}
                        {formatBooleanStateLabel(privateImageCredentialsAvailableInControlPlane)}
                      </span>
                    ) : null}
                    {targetRepoSecretsNotRequired !== null ? (
                      <span className="hint muted" data-testid="migration-target-repo-secrets-not-required-readiness">
                        Target repo image-pull secrets required:{" "}
                        {targetRepoSecretsNotRequired ? "No (control-plane provisioned)" : "Unknown"}
                      </span>
                    ) : null}
                    {deployAuthMode ? (
                      <span className="hint" data-testid="migration-deploy-auth-mode-readiness">
                        Deploy auth mode: {formatReasonCodeLabel(deployAuthMode)}
                      </span>
                    ) : null}
                    {targetRepoDeploySecretRequired !== null ? (
                      <span className="hint" data-testid="migration-target-repo-deploy-secret-required-readiness">
                        Target repo deploy secret required: {formatBooleanStateLabel(targetRepoDeploySecretRequired)}
                      </span>
                    ) : null}
                    {targetRepoDeploySecretName ? (
                      <span className="hint" data-testid="migration-target-repo-deploy-secret-name-readiness">
                        Target repo deploy secret name: {targetRepoDeploySecretName}
                      </span>
                    ) : null}
                    {targetRepoDeploySecretPresent !== null ? (
                      <span className="hint" data-testid="migration-target-repo-deploy-secret-present-readiness">
                        Target repo deploy secret present: {formatBooleanStateLabel(targetRepoDeploySecretPresent)}
                      </span>
                    ) : null}
                    {imagePullSecretNotProvisioned ? (
                      <span className="hint warning" data-testid="migration-image-pull-secret-not-provisioned-readiness">
                        Namespace pull secret is not yet confirmed. Control-plane provisioning runs before deploy.
                      </span>
                    ) : null}
                    {imagePullSecretProvisioningUnavailable ? (
                      <span className="hint warning" data-testid="migration-image-pull-secret-provisioning-unavailable-readiness">
                        Namespace pull-secret provisioning is currently unavailable. Resolve control-plane credentials or managed
                        GKE config blockers before deploy.
                      </span>
                    ) : null}
                    {managedSiteRolloutState ? (
                      <span className="hint" data-testid="migration-managed-site-rollout-state-readiness">
                        Managed site rollout state: {formatManagedSiteRolloutStateLabel(managedSiteRolloutState)}
                      </span>
                    ) : null}
                    {managedSiteRolloutMessage ? (
                      <span
                        className={managedSiteRolloutFixActive ? "hint" : managedSiteRolloutStaleEvidence ? "hint muted" : "hint warning"}
                        data-testid="migration-managed-site-rollout-guidance-readiness"
                      >
                        {managedSiteRolloutStaleEvidence
                          ? `Previous deploy evidence (deploy not rerun yet): ${managedSiteRolloutMessage}`
                          : managedSiteRolloutMessage}
                      </span>
                    ) : null}
                    {managedSiteExpectedImageRepository ? (
                      <span className="hint" data-testid="migration-managed-site-rollout-expected-image-readiness">
                        Expected site-scoped image repository: {managedSiteExpectedImageRepository}
                      </span>
                    ) : null}
                    {managedSiteManifestImageReference ? (
                      <span className="hint" data-testid="migration-managed-site-rollout-manifest-image-readiness">
                        Managed manifest runtime image: {managedSiteManifestImageReference}
                      </span>
                    ) : null}
                    {managedSiteObservedDeployImageReference ? (
                      <span className="hint" data-testid="migration-managed-site-rollout-observed-image-readiness">
                        Last observed deploy runtime image: {managedSiteObservedDeployImageReference}
                      </span>
                    ) : null}
                    {managedSiteObservedDeployImageDigestDisplay ? (
                      <span className="hint" data-testid="migration-managed-site-rollout-observed-digest-readiness">
                        Last observed deploy image digest: {managedSiteObservedDeployImageDigestDisplay}
                      </span>
                    ) : null}
                    {managedSiteRolloutFixActive !== null ? (
                      <span
                        className={managedSiteRolloutFixActive ? "hint" : "hint warning"}
                        data-testid="migration-managed-site-rollout-fix-status-readiness"
                      >
                        Fix active:{" "}
                        {managedSiteRolloutFixActive
                          ? "Yes. Observed deployment image matches expected site-scoped image."
                          : "No. The fix is not active until observed deployment image matches expected site-scoped image."}
                      </span>
                    ) : null}
                    {showManagedGkeConfigSourceHint ? (
                      <span className="hint muted" data-testid="migration-managed-gke-config-source-readiness">
                        Managed deploy resolves admin platform config first; repo vars/secrets are legacy fallback only.
                      </span>
                    ) : null}
                  </>
                ) : null}
              </div>

              {hasGa4OutcomeSnapshot ? (
                <div className="panel panel-compact stack" data-testid="migration-ga4-outcome-snapshot">
                  <strong>GA4 outcome snapshot</strong>
                  <span className="hint muted">{ga4OutcomeSnapshotSubtitle}</span>
                  <span
                    className={
                      ga4OutcomeSnapshotStatus === "available"
                        ? "hint success"
                        : ga4OutcomeSnapshotStatus === "pending_after_window"
                          ? "hint"
                          : "hint warning"
                    }
                  >
                    Status: {toGa4OutcomeStatusLabel(ga4OutcomeSnapshotStatus)}
                  </span>
                  {ga4OutcomeSnapshotStatus === "available" ? (
                    <>
                      <span className="hint">
                        Before sessions: {formatMetricCount(ga4OutcomeSnapshotBeforeSessions)} | After sessions:{" "}
                        {formatMetricCount(ga4OutcomeSnapshotAfterSessions)}
                      </span>
                      <span className="hint">
                        Before users: {formatMetricCount(ga4OutcomeSnapshotBeforeUsers)} | After users:{" "}
                        {formatMetricCount(ga4OutcomeSnapshotAfterUsers)}
                      </span>
                      <span className="hint">
                        Before engagement: {formatEngagementRatePercent(ga4OutcomeSnapshotBeforeEngagementRate)} | After engagement:{" "}
                        {formatEngagementRatePercent(ga4OutcomeSnapshotAfterEngagementRate)}
                      </span>
                      <span className="hint">
                        Sessions delta: {formatPercentDelta(ga4OutcomeSnapshotSessionsDeltaPercent)} | Engagement delta:{" "}
                        {formatPointsDelta(ga4OutcomeSnapshotEngagementDeltaPoints)} | Organic delta:{" "}
                        {formatPercentDelta(ga4OutcomeSnapshotOrganicDeltaPercent)}
                      </span>
                    </>
                  ) : null}
                  {ga4OutcomeSnapshotOutcomeDirection ? (
                    <span className="hint">
                      Observed direction: {formatReasonCodeLabel(ga4OutcomeSnapshotOutcomeDirection)}
                    </span>
                  ) : null}
                  {ga4OutcomeSnapshotOperatorHint ? (
                    <span
                      className={
                        ga4OutcomeSnapshotStatus === "available" || ga4OutcomeSnapshotStatus === "pending_after_window"
                          ? "hint"
                          : "hint warning"
                      }
                    >
                      {ga4OutcomeSnapshotOperatorHint}
                    </span>
                  ) : null}
                </div>
              ) : null}
            </div>

            <div className="migration-publish-deploy-column stack" data-testid="migration-deploy-layout-right">
              <div className="panel panel-compact stack" data-testid="migration-deploy-controls">
                <strong>Deploy Controls</strong>
                <label className="link-row">
                  <input type="checkbox" checked={deployEnabled} onChange={(event) => setDeployEnabled(event.target.checked)} />
                  <span>Deploy enabled for this site workspace</span>
                </label>
                <button
                  type="button"
                  className="button button-secondary"
                  onClick={() => void handleSaveDeployConfig()}
                  disabled={busyAction === "save_deploy_config" || busyAction === "load"}
                >
                  {busyAction === "save_deploy_config" ? "Saving..." : "Save Deploy Availability"}
                </button>
                <label className="link-row">
                  <input type="checkbox" checked={deployDryRun} onChange={(event) => setDeployDryRun(event.target.checked)} />
                  <span>Dry run only</span>
                </label>
                <button
                  type="button"
                  className="button button-primary"
                  onClick={() => void handleDeploySelectedArtifact()}
                  disabled={isActionInFlight || !canDeploySelectedArtifact}
                >
                  {busyAction === "deploy" ? "Submitting..." : "Request GKE Deploy"}
                </button>
                <button
                  type="button"
                  className="button button-secondary"
                  onClick={() => void handleRefreshDeployStatus()}
                  disabled={isActionInFlight || !selectedArtifactVersionIdTrimmed}
                  data-testid="migration-refresh-deploy-status-button"
                >
                  {busyAction === "refresh_deploy_status" ? "Refreshing..." : "Refresh Deploy Status"}
                </button>
                <span className="hint muted">
                  Re-checks the dispatched workflow run and captures confirmed live URL evidence when available.
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>

      </MigrationPublishDeploySection>

      <MigrationAdvancedDiagnosticsSection>

      <div className="panel stack workspace-section-block">
        <h3>Advanced Diagnostics &amp; History</h3>
        <details className="migration-advanced-details workspace-details-shell">
          <summary className="hint muted">Show detailed migration failure diagnostics</summary>
          <div className="stack">
            <div className="migration-diagnostics-shell" data-testid="migration-action-diagnostics-shell">
              <div className="panel panel-compact stack-tight migration-diagnostics-shell-panel" data-testid="migration-action-diagnostics">
                <strong>Action Diagnostics Snapshot</strong>
                <span className="hint muted">
                  Latest action status snapshot for draft generation, publish, and deploy.
                </span>
                <span className="hint">
                  Last draft generation status: {asString(migrationDiagnostics.last_draft_generation_status) || "n/a"}
                </span>
                <span className="hint">Last publish status: {asString(migrationDiagnostics.last_publish_status) || "n/a"}</span>
                <span className="hint">Last deploy status: {asString(migrationDiagnostics.last_deploy_status) || "n/a"}</span>
              </div>
            </div>

            <div className="migration-diagnostics-shell" data-testid="migration-draft-provider-diagnostics-shell">
              <div className="panel panel-compact stack-tight migration-diagnostics-shell-panel" data-testid="migration-draft-provider-diagnostics">
                <strong>Draft / Provider Diagnostics</strong>
                <span className="hint muted">
                  Draft/provider troubleshooting is separated from the primary generation path.
                </span>
                <details className="workspace-details-shell" data-testid="migration-provider-execution-details">
                  <summary className="hint muted">Show provider execution details</summary>
                  <div className="panel panel-compact stack-tight">
                    <WorkspaceMetadataGrid data-testid="migration-ai-execution-metadata">
                      <WorkspaceMetadataItem label="AI execution">
                        <span className="hint" data-testid="migration-ai-execution-summary">
                          AI execution: {aiExecutionSummaryLabel}
                        </span>
                      </WorkspaceMetadataItem>
                      <WorkspaceMetadataItem label="Generated using">
                        <span className="hint" data-testid="migration-ai-model-used">
                          Generated using: {draftAIExecution.modelUsed || draftAIExecution.modelResolved || "n/a"}
                        </span>
                      </WorkspaceMetadataItem>
                      <WorkspaceMetadataItem label="Request profile">
                        <span className="hint" data-testid="migration-ai-request-profile">
                          Request profile: {requestProfileLabel}
                        </span>
                      </WorkspaceMetadataItem>
                      {requestContractStatusLabel ? (
                        <WorkspaceMetadataItem label="Request contract">
                          <span className="hint" data-testid="migration-request-contract-status">
                            Request contract: {requestContractStatusLabel}
                          </span>
                        </WorkspaceMetadataItem>
                      ) : null}
                      {artifactResultLabel ? (
                        <WorkspaceMetadataItem label="Artifact result">
                          <span className="hint" data-testid="migration-artifact-result">
                            Artifact result: {artifactResultLabel}
                          </span>
                        </WorkspaceMetadataItem>
                      ) : null}
                      {draftDurationLabel ? (
                        <WorkspaceMetadataItem label="Duration">
                          <span className="hint" data-testid="migration-ai-duration">
                            Duration: {draftDurationLabel}
                          </span>
                        </WorkspaceMetadataItem>
                      ) : null}
                      {showDraftTimeout ? (
                        <WorkspaceMetadataItem label="Timeout">
                          <span className="hint" data-testid="migration-draft-timeout">
                            Timeout: {draftTimeoutLabel}
                            {draftAIExecution.timeoutSource ? ` (${draftAIExecution.timeoutSource})` : ""}
                          </span>
                        </WorkspaceMetadataItem>
                      ) : null}
                      {draftFailureSourceLabel ? (
                        <WorkspaceMetadataItem label="Failure source">
                          <span className="hint warning" data-testid="migration-draft-failure-source">
                            Failure source: {draftFailureSourceLabel}
                          </span>
                        </WorkspaceMetadataItem>
                      ) : null}
                      <WorkspaceMetadataItem label="Provider source">
                        {asStringOrNull(draftInputSummary.provider_source) || "unknown"}{" "}
                        {asBooleanOrNull(draftInputSummary.mocked_source) ? "(mocked)" : ""}
                      </WorkspaceMetadataItem>
                    </WorkspaceMetadataGrid>
                  </div>
                </details>
              </div>
            </div>

            <details className="workspace-details-shell migration-diagnostics-shell" data-testid="migration-media-diagnostics-shell">
              <summary className="hint muted">Show media diagnostics</summary>
              <div className="panel panel-compact stack-tight migration-diagnostics-shell-panel" data-testid="migration-media-diagnostics">
                <strong>Media Diagnostics</strong>
                <span className="hint muted">
                  Failed image fetch/import reasons and safety rejections are shown here (not in primary media workflow cards).
                </span>
                {mediaDiagnostics.length > 0 ? (
                  <ul className="stack-tight">
                    {mediaDiagnostics.slice(0, 20).map((item, index) => (
                      <li key={`migration-media-diagnostic-${index}`} className="hint warning">
                        {item}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <span className="hint muted">No media diagnostics recorded.</span>
                )}
              </div>
            </details>

            <details
              className="workspace-details-shell migration-diagnostics-shell"
              data-testid="migration-publish-history-shell"
              onToggle={(event) => {
                if (event.currentTarget.open) {
                  void loadPublishHistory();
                }
              }}
            >
              <summary className="hint muted">Show publish history</summary>
              <div className="panel panel-compact stack migration-diagnostics-shell-panel" data-testid="migration-publish-history">
                <strong>Publish History</strong>
                <span className="hint muted">
                  Attempt history is grouped by reason in compact form; expand full history for raw per-attempt detail.
                </span>
                {publishHistoryRecords.length > 0 ? (
                  <label className="stack-tight">
                    <span className="hint muted">Selected publish attempt diagnostics</span>
                    <select
                      value={selectedPublishHistoryIdentity}
                      onChange={(event) => setSelectedPublishHistoryIdentity(event.target.value)}
                      data-testid="migration-publish-history-select"
                    >
                      {publishHistoryRecords
                        .slice(-10)
                        .reverse()
                        .map((record, index) => {
                          const identity = historyRecordIdentity(record);
                          const timestamp = asString(record.timestamp) || "n/a";
                          const status = asString(record.status) || "unknown";
                          const artifactVersion = asString(record.artifact_version) || asString(record.artifact_version_id) || "n/a";
                          return (
                            <option key={`publish-history-select-${identity}-${index}`} value={identity}>
                              {timestamp} - {status} - artifact {artifactVersion}
                            </option>
                          );
                        })}
                    </select>
                  </label>
                ) : null}
                {publishHistoryRecords.length > 0 ? (
                  <span className="hint muted" data-testid="migration-publish-diagnostics-scope">
                    Showing diagnostics for selected publish attempt:{" "}
                    {asString(selectedPublishHistoryRecord.timestamp) || "n/a"} ·{" "}
                    {asString(selectedPublishHistoryRecord.status) || "unknown"}.
                  </span>
                ) : null}
                {publishHistoryRecords.length > 0 ? (
                  <>
                    <span className="hint muted">
                      Selected/latest artifact:{" "}
                      {asString(selectedPublishHistoryRecord.artifact_version)
                        || asString(selectedPublishHistoryRecord.artifact_version_id)
                        || "n/a"}
                    </span>
                    <div className="migration-diagnostic-history-list" data-testid="migration-publish-history-latest">
                      <strong className="hint muted">Latest attempts (up to 5)</strong>
                      <ul className="stack-tight">
                        {publishHistoryLatestAttempts.map((record, index) => (
                          <li key={`publish-history-latest-${index}`} className="hint">
                            {formatAttemptTimestamp(asStringOrNull(record.timestamp))} ·{" "}
                            {asString(record.status) || "unknown"}
                          </li>
                        ))}
                      </ul>
                    </div>
                    {publishHistoryGroupedFailures.length > 0 ? (
                      <div className="migration-diagnostic-history-list" data-testid="migration-publish-history-grouped">
                        <strong className="hint muted">Grouped failure reasons</strong>
                        <ul className="stack-tight">
                          {publishHistoryGroupedFailures.map((group) => (
                            <li key={`publish-history-group-${group.key}`} className="hint">
                              {group.label} - {group.count} attempt{group.count === 1 ? "" : "s"} · latest{" "}
                              {formatAttemptTimestamp(group.latestTimestamp)}
                              {group.nextAction ? ` · ${group.nextAction}` : ""}
                            </li>
                          ))}
                        </ul>
                      </div>
                    ) : null}
                    <details
                      className="workspace-details-shell migration-compact-details"
                      data-testid="migration-publish-history-full-details"
                    >
                      <summary className="hint muted">Show full publish history</summary>
                      <ul className="stack-tight">
                        {publishHistoryRecords.slice().reverse().map((record, index) => {
                          const artifactVersion =
                            asString(record.artifact_version) || asString(record.artifact_version_id) || "n/a";
                          const failureReason = asStringOrNull(record.failure_reason);
                          return (
                            <li key={`publish-history-full-${index}`} className="hint">
                              {formatAttemptTimestamp(asStringOrNull(record.timestamp))} ·{" "}
                              {asString(record.status) || "unknown"} · artifact {artifactVersion}
                              {failureReason ? ` · ${formatReasonCodeLabel(failureReason)}` : ""}
                            </li>
                          );
                        })}
                      </ul>
                    </details>
                  </>
                ) : (
                  <span className="hint muted">No publish actions yet.</span>
                )}
              </div>
            </details>

            <details
              className="workspace-details-shell migration-diagnostics-shell"
              data-testid="migration-deploy-history-shell"
              onToggle={(event) => {
                if (event.currentTarget.open) {
                  void loadDeployHistory();
                }
              }}
            >
              <summary className="hint muted">Show deploy history</summary>
              <div className="panel panel-compact stack migration-diagnostics-shell-panel" data-testid="migration-deploy-history">
                <strong>Deploy History</strong>
                <span className="hint muted">
                  Attempt history is grouped by reason in compact form; expand full history for raw per-attempt detail.
                </span>
                {deployHistoryRecords.length > 0 ? (
                  <label className="stack-tight">
                    <span className="hint muted">Selected deploy attempt diagnostics</span>
                    <select
                      value={selectedDeployHistoryIdentity}
                      onChange={(event) => setSelectedDeployHistoryIdentity(event.target.value)}
                      data-testid="migration-deploy-history-select"
                    >
                      {deployHistoryRecords
                        .slice(-10)
                        .reverse()
                        .map((record, index) => {
                          const identity = historyRecordIdentity(record);
                          const timestamp = asString(record.timestamp) || "n/a";
                          const status = asString(record.status) || "unknown";
                          const artifactVersion = asString(record.artifact_version) || asString(record.artifact_version_id) || "n/a";
                          return (
                            <option key={`deploy-history-select-${identity}-${index}`} value={identity}>
                              {timestamp} - {status} - artifact {artifactVersion}
                            </option>
                          );
                        })}
                    </select>
                  </label>
                ) : null}
                {deployHistoryRecords.length > 0 ? (
                  <span className="hint muted" data-testid="migration-deploy-diagnostics-scope">
                    Showing diagnostics for selected deploy attempt:{" "}
                    {asString(selectedDeployHistoryRecord.timestamp) || "n/a"} ·{" "}
                    {asString(selectedDeployHistoryRecord.status) || "unknown"}.
                  </span>
                ) : null}
                {deployHistoryRecords.length > 0 ? (
                  <>
                    <span className="hint muted">
                      Selected/latest artifact:{" "}
                      {asString(selectedDeployHistoryRecord.artifact_version)
                        || asString(selectedDeployHistoryRecord.artifact_version_id)
                        || "n/a"}
                    </span>
                    <div className="migration-diagnostic-history-list" data-testid="migration-deploy-history-latest">
                      <strong className="hint muted">Latest attempts (up to 5)</strong>
                      <ul className="stack-tight">
                        {deployHistoryLatestAttempts.map((record, index) => (
                          <li key={`deploy-history-latest-${index}`} className="hint">
                            {formatAttemptTimestamp(asStringOrNull(record.timestamp))} ·{" "}
                            {asString(record.status) || "unknown"}
                          </li>
                        ))}
                      </ul>
                    </div>
                    {deployHistoryGroupedFailures.length > 0 ? (
                      <div className="migration-diagnostic-history-list" data-testid="migration-deploy-history-grouped">
                        <strong className="hint muted">Grouped failure reasons</strong>
                        <ul className="stack-tight">
                          {deployHistoryGroupedFailures.map((group) => (
                            <li key={`deploy-history-group-${group.key}`} className="hint">
                              {group.label} - {group.count} attempt{group.count === 1 ? "" : "s"} · latest{" "}
                              {formatAttemptTimestamp(group.latestTimestamp)}
                              {group.nextAction ? ` · ${group.nextAction}` : ""}
                            </li>
                          ))}
                        </ul>
                      </div>
                    ) : null}
                    <details
                      className="workspace-details-shell migration-compact-details"
                      data-testid="migration-deploy-history-full-details"
                    >
                      <summary className="hint muted">Show full deploy history</summary>
                      <ul className="stack-tight">
                        {deployHistoryRecords.slice().reverse().map((record, index) => {
                          const status = asString(record.status) || "unknown";
                          const failureReason = asStringOrNull(record.failure_reason);
                          const failureStage = asStringOrNull(record.failure_stage);
                          const artifactVersion =
                            asString(record.artifact_version) || asString(record.artifact_version_id) || "n/a";
                          return (
                            <li key={`deploy-history-full-${index}`} className="hint">
                              {formatAttemptTimestamp(asStringOrNull(record.timestamp))} · {status} · artifact {artifactVersion}
                              {failureStage ? ` · ${formatDispatchStageLabel(failureStage)}` : ""}
                              {failureReason ? ` · ${formatReasonCodeLabel(failureReason)}` : ""}
                            </li>
                          );
                        })}
                      </ul>
                    </details>
                  </>
                ) : (
                  <span className="hint muted">No deploy actions yet.</span>
                )}
              </div>
            </details>

            {(hasDestinationAdditionalDiagnostics ||
              Boolean(deploySiteWorkflowFilePath) ||
              Boolean(deployKubernetesNamespace) ||
              deployWorkflowNamespaceAligned !== null ||
              deployManifestNamespaceAligned !== null ||
              managedResourceQuotaExpected !== null ||
              managedLimitRangeExpected !== null ||
              managedNetworkPolicyExpected !== null ||
              managedNamespacePoliciesAligned !== null) ? (
              <details
                className="workspace-details-shell migration-diagnostics-shell"
                data-testid="migration-destination-secondary-details"
              >
                <summary className="hint muted">Show full destination diagnostics</summary>
                <div
                  className="panel panel-compact stack-tight migration-diagnostics-shell-panel"
                  data-testid="migration-destination-config-diagnostics"
                >
                  <strong>Destination / Config Diagnostics</strong>
                  <div className="migration-diagnostic-groups">
                    <div className="panel panel-compact stack-tight migration-diagnostic-group-card">
                      <strong>Draft artifact</strong>
                      <span className="hint">Draft preview: {toDestinationStateLabel(destinationSummary.draftPreviewState)}</span>
                      <span className="hint">Draft entry file: {destinationSummary.draftPreviewEntryPath || "Not available"}</span>
                      <span className="hint">Publish runtime: {publishRuntimeStatusLabel}</span>
                      <span className="hint">Deploy runtime: {deployRuntimeStatusLabel}</span>
                    </div>
                    <div className="panel panel-compact stack-tight migration-diagnostic-group-card">
                      <strong>Repository / workflow</strong>
                      <span className="hint">Workflow identifier / path: {deployWorkflowIdentifier || "Not configured"}</span>
                      <span className="hint">Workflow source: {deployResolvedWorkflowSource || "Not available"}</span>
                      <span className="hint">Deploy workflow mode: {deployWorkflowMode || "Not available"}</span>
                      {publishRepositoryProvisioningGuidance ? (
                        <span className="hint warning">Repository provisioning: {publishRepositoryProvisioningGuidance}</span>
                      ) : null}
                      <details className="workspace-details-shell migration-diagnostic-group-details">
                        <summary className="hint muted">Show repository/workflow details</summary>
                        {deploySiteWorkflowFilePath ? (
                          <span className="hint">Site workflow file: {deploySiteWorkflowFilePath}</span>
                        ) : null}
                        {deployTargetEnvironmentSource ? (
                          <span className="hint">Target environment source: {deployTargetEnvironmentSource}</span>
                        ) : null}
                      </details>
                    </div>
                    <div className="panel panel-compact stack-tight migration-diagnostic-group-card">
                      <strong>Kubernetes runtime</strong>
                      <span className="hint">Kubernetes namespace: {deployKubernetesNamespace || "Not available"}</span>
                      <span className="hint">Namespace source: {deployNamespaceSource || "Not available"}</span>
                      <span className="hint">Namespace model status: {deployNamespaceModelStatus || "Not available"}</span>
                      <span className="hint">
                        Policy alignment:{" "}
                        {managedNamespacePoliciesAligned === null
                          ? "Unknown"
                          : formatBooleanStateLabel(managedNamespacePoliciesAligned)}
                      </span>
                      <details className="workspace-details-shell migration-diagnostic-group-details">
                        <summary className="hint muted">Show Kubernetes policy diagnostics</summary>
                        {deployWorkflowNamespaceAligned !== null ? (
                          <span className="hint">
                            Workflow namespace aligned: {formatBooleanStateLabel(deployWorkflowNamespaceAligned)}
                          </span>
                        ) : null}
                        {deployManifestNamespaceAligned !== null ? (
                          <span className="hint">
                            Manifest namespace aligned: {formatBooleanStateLabel(deployManifestNamespaceAligned)}
                          </span>
                        ) : null}
                        {managedResourceQuotaExpected !== null ? (
                          <span className="hint">
                            Managed ResourceQuota:{" "}
                            {managedResourceQuotaExpected ? formatBooleanStateLabel(managedResourceQuotaPresent) : "Not enabled"}
                          </span>
                        ) : null}
                        {managedLimitRangeExpected !== null ? (
                          <span className="hint">
                            Managed LimitRange:{" "}
                            {managedLimitRangeExpected ? formatBooleanStateLabel(managedLimitRangePresent) : "Not enabled"}
                          </span>
                        ) : null}
                        {managedNetworkPolicyExpected !== null ? (
                          <span className="hint">
                            Managed NetworkPolicy:{" "}
                            {managedNetworkPolicyExpected ? formatBooleanStateLabel(managedNetworkPolicyPresent) : "Not enabled"}
                          </span>
                        ) : null}
                      </details>
                    </div>
                    <div className="panel panel-compact stack-tight migration-diagnostic-group-card">
                      <strong>Domain / URL</strong>
                      <span className="hint">Current site URL: {destinationSummary.currentSiteUrl || "Not available"}</span>
                      <span className="hint">
                        URL source: {destinationSummary.deployUrlSource || destinationSummary.publishUrlSource || "unknown"}
                      </span>
                      <span className="hint">
                        URL source detail:{" "}
                        {destinationSummary.deployUrlSourceDetail || destinationSummary.publishUrlSourceDetail || "Not available"}
                      </span>
                    </div>
                    <div className="panel panel-compact stack-tight migration-diagnostic-group-card">
                      <strong>Preview / deployment evidence</strong>
                      <span className="hint">
                        Preview deployment:{" "}
                        {destinationSummary.deployPreviewState === "active_live"
                          ? "Preview deployed"
                          : destinationSummary.deployPreviewUrl
                            ? "Preview pending deployment evidence"
                            : "Preview target not configured"}
                      </span>
                      <span className="hint">
                        Customer domain status:{" "}
                        {destinationSummary.deployCustomerDomainState === "active_live"
                          ? "Production domain connected"
                          : destinationSummary.deployCustomerDomainState === "pending_cutover"
                            ? "Production domain not yet connected"
                            : "Production domain not configured"}
                      </span>
                      <span className="hint">Live URL (confirmed): {destinationSummary.deployResolvedLiveUrl || "Not yet confirmed"}</span>
                    </div>
                  </div>
                </div>
              </details>
            ) : null}

            <div className="grid grid-2">
              <div className="migration-diagnostics-shell" data-testid="migration-publish-diagnostics-shell">
                <div className="panel panel-compact stack-tight migration-diagnostics-shell-panel" data-testid="migration-publish-diagnostics">
                  <div className="migration-diagnostic-card-header">
                    <strong>Publish Diagnostics</strong>
                    <span className={diagnosticStatusBadgeClass(publishDiagnosticsStatus)}>
                      {toDiagnosticStatusLabel(publishDiagnosticsStatus)}
                    </span>
                  </div>
                  <span className="hint muted">
                    {publishHistoryRecords.length > 0
                      ? "Context: selected publish attempt"
                      : "Context: latest publish summary"}
                  </span>
                  <span className="hint muted">
                    Attempt:{" "}
                    {publishDiagnosticsSelectedTimestamp ? formatAttemptTimestamp(publishDiagnosticsSelectedTimestamp) : "n/a"} ·{" "}
                    {publishDiagnosticsAttemptStatusRaw || "unknown"}
                  </span>
                  <span className={publishDiagnosticsStatus === "failed" || publishDiagnosticsStatus === "blocked" ? "hint warning" : "hint"}>
                    Reason: {publishDiagnosticsReasonSummary}
                  </span>
                  <span className="hint">Next action: {publishDiagnosticsNextAction}</span>
                  {publishDiagnosticsUsingSummaryFallback ? (
                    <span className="hint muted" data-testid="migration-publish-diagnostics-fallback-note">
                      Selected-attempt diagnostics include latest-summary fallback for missing fields.
                    </span>
                  ) : null}
                  <details className="workspace-details-shell migration-compact-details" data-testid="migration-publish-diagnostics-raw-details">
                    <summary className="hint muted">Show raw publish diagnostics fields</summary>
                    {publishDiagnosticsFailureCategory ? (
                      <span className="hint warning">
                        Publish failure category: {toFailureCategoryLabel(publishDiagnosticsFailureCategory)}
                      </span>
                    ) : (
                      <span className="hint muted">No publish failure recorded.</span>
                    )}
                    {publishDiagnosticsFailureMessage ? (
                      <span className="hint warning">{publishDiagnosticsFailureMessage}</span>
                    ) : null}
                    {publishDiagnosticsFailureReasonCode ? (
                      <span className="hint warning">
                        Publish failure reason: {formatReasonCodeLabel(publishDiagnosticsFailureReasonCode)}
                      </span>
                    ) : null}
                    {publishFailureStageFromSelected || publishFailureStageFromSummary ? (
                      <span className="hint">
                        Publish failure stage: {formatDispatchStageLabel(publishFailureStageFromSelected || publishFailureStageFromSummary)}
                      </span>
                    ) : null}
                    <span className="hint">
                      Workflow remediation attempted: {formatBooleanStateLabel(publishWorkflowRemediationAttempted)}
                    </span>
                    <span className="hint">
                      Workflow remediation outcome: {formatWorkflowRemediationOutcomeLabel(publishWorkflowRemediationOutcome)}
                    </span>
                    {publishWorkflowRemediationGuidance ? (
                      <span className="hint warning">Next step guidance: {publishWorkflowRemediationGuidance}</span>
                    ) : null}
                  </details>
                </div>
              </div>

              <div className="migration-diagnostics-shell" data-testid="migration-deploy-diagnostics-shell">
                <div className="panel panel-compact stack-tight migration-diagnostics-shell-panel" data-testid="migration-deploy-diagnostics">
                  <div className="migration-diagnostic-card-header">
                    <strong>Deploy Diagnostics</strong>
                    <span className={diagnosticStatusBadgeClass(deployDiagnosticsStatus)}>
                      {toDiagnosticStatusLabel(deployDiagnosticsStatus)}
                    </span>
                  </div>
                  <span className="hint muted">
                    {deployHistoryRecords.length > 0
                      ? "Context: selected deploy attempt"
                      : "Context: latest deploy summary"}
                  </span>
                  <span className="hint muted">
                    Attempt:{" "}
                    {deployDiagnosticsSelectedTimestamp ? formatAttemptTimestamp(deployDiagnosticsSelectedTimestamp) : "n/a"} ·{" "}
                    {deployDiagnosticsAttemptStatusRaw || "unknown"}
                  </span>
                  <span className="hint muted">
                    Selected workflow attempt: {selectedWorkflowAttemptStatus || "unknown"} ·{" "}
                    {selectedWorkflowAttemptConclusion || "unknown"}
                  </span>
                  {selectedWorkflowFailureReason || selectedWorkflowFailureStage || selectedWorkflowFailedStep ? (
                    <span className="hint muted">
                      Selected workflow failure:{" "}
                      {selectedWorkflowFailureReason ? formatReasonCodeLabel(selectedWorkflowFailureReason) : "Not available"}
                      {selectedWorkflowFailureStage ? ` @ ${formatReasonCodeLabel(selectedWorkflowFailureStage)}` : ""}
                      {selectedWorkflowFailedStep ? ` (${selectedWorkflowFailedStep})` : ""}
                    </span>
                  ) : null}
                  <span className={deployDiagnosticsStatus === "failed" || deployDiagnosticsStatus === "blocked" ? "hint warning" : "hint"}>
                    Reason: {deployDiagnosticsReasonSummary}
                  </span>
                  <span className="hint">Next action: {deployDiagnosticsNextAction}</span>
                  <div className="panel panel-compact stack-tight" data-testid="migration-current-live-runtime-evidence">
                    <strong>Current Live Runtime Evidence</strong>
                    <span className="hint">
                      HTTPS Ready: {formatBooleanStateLabel(currentDeployHttpsReady ?? deployHttpsReady)}
                    </span>
                    <span className="hint">Host reachable: {formatBooleanStateLabel(currentHostReachable)}</span>
                    <span className="hint">Scheme: {currentHostReachabilityScheme || "Not available"}</span>
                    <span className="hint">Live URL: {currentLiveUrl || destinationSummary.deployResolvedLiveUrl || "Not available"}</span>
                    <span className="hint">
                      Cert identity valid: {formatBooleanStateLabel(currentCertIdentityValid ?? certIdentityValid)}
                    </span>
                    <span className="hint">
                      Checked at: {currentLiveEvidenceCheckedAt ? formatAttemptTimestamp(currentLiveEvidenceCheckedAt) : "Not available"}
                    </span>
                    <span className="hint">Source: {currentLiveRuntimeSource || "Not available"}</span>
                    {currentHttpsProbeStatusCode !== null ? (
                      <span className="hint">HTTPS probe status: {currentHttpsProbeStatusCode}</span>
                    ) : null}
                    {currentDeployHttpsReady === false && currentHttpsProbeErrorSummary ? (
                      <span className="hint warning">Probe summary: {currentHttpsProbeErrorSummary}</span>
                    ) : null}
                    {currentLiveHealthySelectedWorkflowFailureNote ? (
                      <span className="hint">{currentLiveHealthySelectedWorkflowFailureNote}</span>
                    ) : null}
                  </div>
                  {deployDiagnosticsUsingSummaryFallback ? (
                    <span className="hint muted" data-testid="migration-deploy-diagnostics-fallback-note">
                      Selected-attempt diagnostics include latest-summary fallback for missing fields.
                    </span>
                  ) : null}
                  {managedSiteRolloutState ? (
                    <span className="hint" data-testid="migration-managed-site-rollout-state-diagnostics">
                      Managed site rollout state: {formatManagedSiteRolloutStateLabel(managedSiteRolloutState)}
                    </span>
                  ) : null}
                  {managedSiteRolloutMessage ? (
                    <span
                      className={managedSiteRolloutFixActive ? "hint" : managedSiteRolloutStaleEvidence ? "hint muted" : "hint warning"}
                      data-testid="migration-managed-site-rollout-guidance-diagnostics"
                    >
                      {managedSiteRolloutStaleEvidence
                        ? `Previous deploy evidence (deploy not rerun yet): ${managedSiteRolloutMessage}`
                        : managedSiteRolloutMessage}
                    </span>
                  ) : null}
                  {managedSiteExpectedImageRepository ? (
                    <span className="hint" data-testid="migration-managed-site-rollout-expected-image-diagnostics">
                      Expected site-scoped image repository: {managedSiteExpectedImageRepository}
                    </span>
                  ) : null}
                  {managedSiteManifestImageReference ? (
                    <span className="hint" data-testid="migration-managed-site-rollout-manifest-image-diagnostics">
                      Managed manifest runtime image: {managedSiteManifestImageReference}
                    </span>
                  ) : null}
                  {managedSiteObservedDeployImageReference ? (
                    <span className="hint" data-testid="migration-managed-site-rollout-observed-image-diagnostics">
                      Last observed deploy runtime image: {managedSiteObservedDeployImageReference}
                    </span>
                  ) : null}
                  {managedSiteObservedDeployImageDigestDisplay ? (
                    <span className="hint" data-testid="migration-managed-site-rollout-observed-digest-diagnostics">
                      Last observed deploy image digest: {managedSiteObservedDeployImageDigestDisplay}
                    </span>
                  ) : null}
                  {managedSiteRolloutFixActive !== null ? (
                    <span
                      className={managedSiteRolloutFixActive ? "hint" : "hint warning"}
                      data-testid="migration-managed-site-rollout-fix-status-diagnostics"
                    >
                      Fix active:{" "}
                      {managedSiteRolloutFixActive
                        ? "Yes. Observed deployment image matches expected site-scoped image."
                        : "No. The fix is not active until observed deployment image matches expected site-scoped image."}
                    </span>
                  ) : null}
                  {managedGkeConfigGuidance ? (
                    <span className="hint warning" data-testid="migration-managed-gke-config-guidance-diagnostics">
                      {managedGkeConfigGuidance}
                    </span>
                  ) : null}
                  {showManagedGkeConfigSourceHint ? (
                    <span className="hint muted" data-testid="migration-managed-gke-config-source-diagnostics">
                      Managed deploy resolves admin platform config first; repo vars/secrets are legacy fallback only.
                    </span>
                  ) : null}
                  <div className="migration-diagnostics-shell migration-diagnostics-shell-nested" data-testid="migration-deploy-consistency-shell">
                    <div className="panel panel-compact stack-tight migration-diagnostics-shell-panel" data-testid="migration-deploy-consistency">
                      <strong>Deploy consistency checks</strong>
                      <span className="hint muted">
                        Grouped status checks use selected-attempt evidence first, then latest summary fallback.
                      </span>
                      {deployConsistencyGrouping.sharedWarnings.length > 0 ? (
                        <div className="stack-tight">
                          {deployConsistencyGrouping.sharedWarnings.map((warning) => (
                            <span key={`deploy-consistency-warning-${warning.key}`} className="hint warning">
                              {warning.message} Affected: {warning.affectedChecks.join(", ")}.
                            </span>
                          ))}
                        </div>
                      ) : null}
                      <div className="migration-diagnostic-status-grid">
                        {deployConsistencyGrouping.checks.map((check) => (
                          <div
                            key={`deploy-consistency-${check.key}`}
                            className="migration-diagnostic-status-row"
                            data-testid={`migration-deploy-consistency-gate-${check.key}`}
                          >
                            <span>{check.label}</span>
                            <span className={deployConsistencyStatusBadgeClass(check.status)}>
                              {toDeployConsistencyStatusLabel(check.status)}
                            </span>
                            {check.reason ? (
                              <span className="hint muted">{check.reason}</span>
                            ) : null}
                          </div>
                        ))}
                      </div>
                      {deployConsistencyRemediationHints.length > 0 ? (
                        <div className="stack-tight" data-testid="migration-deploy-consistency-remediation">
                          <span className="hint warning">Operator remediation</span>
                          <ul>
                            {deployConsistencyRemediationHints.map((hint, index) => (
                              <li key={`deploy-consistency-remediation-${index}`} className="hint warning">
                                {hint}
                              </li>
                            ))}
                          </ul>
                        </div>
                      ) : null}
                      <details className="workspace-details-shell migration-compact-details" data-testid="migration-deploy-consistency-raw-details">
                        <summary className="hint muted">Show raw deploy consistency fields</summary>
                        <span className="hint" data-testid="migration-deploy-consistency-dns-match">
                          dns_record_matches_ingress: {formatBooleanStateLabel(dnsRecordMatchesIngress)}
                        </span>
                        <span className="hint" data-testid="migration-deploy-consistency-dns-expected-ip">
                          dns_expected_ip: {dnsExpectedIp || "Not available"}
                        </span>
                        <span className="hint" data-testid="migration-deploy-consistency-dns-observed-ip">
                          dns_observed_ip: {dnsObservedIp || "Not available"}
                        </span>
                        <span className="hint" data-testid="migration-deploy-consistency-expected-static-ip-address">
                          expected_static_ip_address: {expectedStaticIpAddress || "Not available"}
                        </span>
                        <span className="hint" data-testid="migration-deploy-consistency-static-ip-status">
                          static_ip_status: {staticIpStatus || "Not available"}
                        </span>
                        <span className="hint" data-testid="migration-deploy-consistency-ingress-status-ip">
                          ingress_status_ip: {ingressStatusIp || "Not available"}
                        </span>
                        <span className="hint" data-testid="migration-deploy-consistency-ingress-status-ip-matches-static-ip">
                          ingress_status_ip_matches_static_ip: {formatBooleanStateLabel(ingressStatusIpMatchesStaticIp)}
                        </span>
                        <span className="hint" data-testid="migration-deploy-consistency-static-ip-forwarding-rule-bound">
                          static_ip_bound_to_expected_forwarding_rule:{" "}
                          {formatBooleanStateLabel(staticIpBoundToExpectedForwardingRule)}
                        </span>
                        <span className="hint" data-testid="migration-deploy-consistency-tls-certificate-status">
                          tls_certificate_status: {tlsCertificateStatus || "Not available"}
                        </span>
                        <span className="hint" data-testid="migration-deploy-consistency-tls-domain-status">
                          tls_domain_status: {tlsDomainStatus || "Not available"}
                        </span>
                        <span className="hint" data-testid="migration-deploy-consistency-observed-managed-certificate-status">
                          observed_managed_certificate_status: {observedManagedCertificateStatus || "Not available"}
                        </span>
                        <span className="hint" data-testid="migration-deploy-consistency-observed-managed-certificate-domain-status">
                          observed_managed_certificate_domain_status:{" "}
                          {observedManagedCertificateDomainStatus || "Not available"}
                        </span>
                        <span className="hint" data-testid="migration-deploy-consistency-observed-managed-certificate-domains">
                          observed_managed_certificate_domains: {observedManagedCertificateDomains || "Not available"}
                        </span>
                        <span className="hint" data-testid="migration-deploy-consistency-ingress-ip">
                          ingress_ip: {ingressIp || "Not available"}
                        </span>
                        <span className="hint" data-testid="migration-deploy-consistency-ingress-conflict">
                          ingress_conflict_detected: {formatBooleanStateLabel(ingressConflictDetected)}
                        </span>
                        <span className="hint" data-testid="migration-deploy-consistency-cert-identity">
                          cert_identity_valid: {formatBooleanStateLabel(certIdentityValid)}
                        </span>
                        <span className="hint" data-testid="migration-deploy-consistency-https-ready">
                          deploy_https_ready: {formatBooleanStateLabel(deployHttpsReady)}
                        </span>
                        <span className="hint" data-testid="migration-deploy-consistency-gce-backend-health-status">
                          gce_backend_health_status: {gceBackendHealthStatus || "Not available"}
                        </span>
                        <span className="hint" data-testid="migration-deploy-consistency-preview-https-status">
                          preview_https_status: {previewHttpsStatus !== null ? String(previewHttpsStatus) : "Not available"}
                        </span>
                        <span className="hint" data-testid="migration-deploy-consistency-preview-http-status">
                          preview_http_status: {previewHttpStatus !== null ? String(previewHttpStatus) : "Not available"}
                        </span>
                        <span className="hint" data-testid="migration-deploy-consistency-service-probe-status">
                          service_probe_status: {serviceProbeStatus || "Not available"}
                        </span>
                        <span className="hint" data-testid="migration-deploy-consistency-endpoint-probe-status">
                          endpoint_probe_status: {endpointProbeStatus || "Not available"}
                        </span>
                        <span className="hint" data-testid="migration-deploy-consistency-runtime-probe-status">
                          runtime_probe_status: {runtimeProbeStatus || "Not available"}
                        </span>
                        <span className="hint" data-testid="migration-deploy-consistency-current-live-url">
                          current_live_url: {currentLiveUrl || "Not available"}
                        </span>
                        <span className="hint" data-testid="migration-deploy-consistency-current-host-reachable">
                          current_host_reachable: {formatBooleanStateLabel(currentHostReachable)}
                        </span>
                        <span className="hint" data-testid="migration-deploy-consistency-current-https-ready">
                          current_deploy_https_ready: {formatBooleanStateLabel(currentDeployHttpsReady)}
                        </span>
                        <span className="hint" data-testid="migration-deploy-consistency-current-cert-identity">
                          current_cert_identity_valid: {formatBooleanStateLabel(currentCertIdentityValid)}
                        </span>
                        <span className="hint" data-testid="migration-deploy-consistency-current-runtime-source">
                          current_live_runtime_source: {currentLiveRuntimeSource || "Not available"}
                        </span>
                        <span className="hint" data-testid="migration-deploy-consistency-workflow-integrity-status">
                          workflow_integrity_status: {workflowIntegrityStatus || "Not available"}
                        </span>
                        <span className="hint" data-testid="migration-deploy-consistency-workflow-integrity-reason-code">
                          workflow_integrity_reason_code: {workflowIntegrityReasonCode || "Not available"}
                        </span>
                      </details>
                    </div>
                  </div>
                  <details className="workspace-details-shell migration-compact-details" data-testid="migration-deploy-diagnostics-raw-details">
                    <summary className="hint muted">Show raw deploy diagnostics fields</summary>
                    <span className="hint">
                      Deploy failure category:{" "}
                      {deployDiagnosticsFailureCategory ? toFailureCategoryLabel(deployDiagnosticsFailureCategory) : "Not available"}
                    </span>
                    <span className="hint">
                      Deploy failure reason:{" "}
                      {deployFailureReasonCode ? formatReasonCodeLabel(deployFailureReasonCode) : "Not available"}
                    </span>
                    <span className="hint">
                      Deploy failure stage: {deployFailureStage ? formatDispatchStageLabel(deployFailureStage) : "Not available"}
                    </span>
                    <span className="hint">
                      Requested workflow identifier: {deployWorkflowIdentifierRequested || "Not available"}
                    </span>
                    <span className="hint">Resolved workflow path: {deployWorkflowFilePath || "Not available"}</span>
                    <span className="hint">
                      Workflow exists:{" "}
                      {formatBooleanStateLabel(deployWorkflowExists, {
                        trueLabel: "Yes",
                        falseLabel: "No",
                      })}
                    </span>
                    <span className="hint">
                      Workflow resolution source: {deployWorkflowDispatchResolutionSource || "Not available"}
                    </span>
                    <span className="hint">
                      Dispatch service reason: {formatReasonCodeLabel(dispatchServiceReasonCode)}
                    </span>
                    <span className="hint">deploy_auth_mode: {deployAuthMode || "Not available"}</span>
                    <span className="hint">
                      target_repo_deploy_secret_required:{" "}
                      {formatBooleanStateLabel(targetRepoDeploySecretRequired)}
                    </span>
                    <span className="hint">
                      target_repo_deploy_secret_name: {targetRepoDeploySecretName || "Not available"}
                    </span>
                    <span className="hint">
                      target_repo_deploy_secret_present:{" "}
                      {formatBooleanStateLabel(targetRepoDeploySecretPresent)}
                    </span>
                    <span className="hint">Dispatch ref sent: {dispatchRefSent || "Not available"}</span>
                    <span className="hint">
                      Workflow input keys (configured):{" "}
                      {workflowInputsConfiguredKeys.length > 0 ? workflowInputsConfiguredKeys.join(", ") : "None"}
                    </span>
                    <span className="hint">
                      Workflow input keys (sent): {workflowInputsSentKeys.length > 0 ? workflowInputsSentKeys.join(", ") : "None"}
                    </span>
                    <span className="hint">
                      Workflow run lookup attempted: {formatBooleanStateLabel(workflowRunLookupAttempted)}
                    </span>
                    <span className="hint">Workflow run found: {formatBooleanStateLabel(workflowRunFound)}</span>
                    <span className="hint">
                      Workflow job failure detected: {formatBooleanStateLabel(workflowJobFailureDetected)}
                    </span>
                    <span className="hint">Workflow run status: {workflowRunStatus || "Not available"}</span>
                    <span className="hint">Workflow run conclusion: {workflowRunConclusion || "Not available"}</span>
                    <span className="hint">
                      selected_workflow_attempt_status: {selectedWorkflowAttemptStatus || "Not available"}
                    </span>
                    <span className="hint">
                      selected_workflow_attempt_conclusion: {selectedWorkflowAttemptConclusion || "Not available"}
                    </span>
                    <span className="hint">
                      selected_workflow_failure_reason:{" "}
                      {selectedWorkflowFailureReason ? formatReasonCodeLabel(selectedWorkflowFailureReason) : "Not available"}
                    </span>
                    <span className="hint">
                      selected_workflow_failure_stage:{" "}
                      {selectedWorkflowFailureStage ? formatReasonCodeLabel(selectedWorkflowFailureStage) : "Not available"}
                    </span>
                    <span className="hint">
                      selected_workflow_failed_step: {selectedWorkflowFailedStep || "Not available"}
                    </span>
                    <span className="hint">Post-dispatch state: {postDispatchState || "Not available"}</span>
                    <span className="hint">
                      Post-conformance stage: {formatReasonCodeLabel(postConformanceStage)}
                    </span>
                    <span className="hint">
                      Post-conformance detail: {postConformanceReasonText || "Not available"}
                    </span>
                    {postConformanceGuidance ? (
                      <span className="hint warning">Next step guidance: {postConformanceGuidance}</span>
                    ) : null}
                    <span className="hint">
                      Workflow run failure reason:{" "}
                      {deployRunFailureReasonCode ? formatReasonCodeLabel(deployRunFailureReasonCode) : "Not available"}
                    </span>
                    <span className="hint">
                      Workflow run failure stage:{" "}
                      {deployRunFailureStage ? formatReasonCodeLabel(deployRunFailureStage) : "Not available"}
                    </span>
                    <span className="hint">
                      Workflow run failed step: {deployRunFailureStep || "Not available"}
                    </span>
                    {deployRunFailureHint ? (
                      <span className="hint warning">Workflow run guidance: {deployRunFailureHint}</span>
                    ) : null}
                    <span className="hint">
                      Deploy evidence contract status: {deployEvidenceContractStatus || "Not available"}
                    </span>
                    <span className="hint">
                      Deploy evidence contract reasons:{" "}
                      {deployEvidenceContractReasons.length > 0 ? deployEvidenceContractReasons.join(", ") : "Not available"}
                    </span>
                    <span className="hint">
                      Expected workflow outputs: {expectedWorkflowOutputs.length > 0 ? expectedWorkflowOutputs.join(", ") : "Not available"}
                    </span>
                    <span className="hint">
                      current_live_runtime_status: {currentLiveRuntimeStatus || "Not available"}
                    </span>
                    <span className="hint">
                      current_live_runtime_source: {currentLiveRuntimeSource || "Not available"}
                    </span>
                    <span className="hint">current_live_url: {currentLiveUrl || "Not available"}</span>
                    <span className="hint">
                      current_host_reachable: {formatBooleanStateLabel(currentHostReachable)}
                    </span>
                    <span className="hint">
                      current_host_reachability_scheme: {currentHostReachabilityScheme || "Not available"}
                    </span>
                    <span className="hint">
                      current_deploy_https_ready: {formatBooleanStateLabel(currentDeployHttpsReady)}
                    </span>
                    <span className="hint">
                      current_cert_identity_valid: {formatBooleanStateLabel(currentCertIdentityValid)}
                    </span>
                    <span className="hint">
                      current_https_probe_status_code:{" "}
                      {currentHttpsProbeStatusCode !== null ? String(currentHttpsProbeStatusCode) : "Not available"}
                    </span>
                    <span className="hint">
                      current_https_probe_error_summary: {currentHttpsProbeErrorSummary || "Not available"}
                    </span>
                    <span className="hint">
                      preview_https_status: {previewHttpsStatus !== null ? String(previewHttpsStatus) : "Not available"}
                    </span>
                    <span className="hint">
                      preview_http_status: {previewHttpStatus !== null ? String(previewHttpStatus) : "Not available"}
                    </span>
                    <span className="hint">
                      preview_probe_attempt: {previewProbeAttempt !== null ? String(previewProbeAttempt) : "Not available"}
                    </span>
                    <span className="hint">
                      preview_probe_elapsed_seconds:{" "}
                      {previewProbeElapsedSeconds !== null ? String(previewProbeElapsedSeconds) : "Not available"}
                    </span>
                    <span className="hint">expected_static_ip_address: {expectedStaticIpAddress || "Not available"}</span>
                    <span className="hint">static_ip_status: {staticIpStatus || "Not available"}</span>
                    <span className="hint">
                      static_ip_describe_attempts: {staticIpDescribeAttempts !== null ? String(staticIpDescribeAttempts) : "Not available"}
                    </span>
                    <span className="hint">
                      static_ip_list_fallback_attempted: {formatBooleanStateLabel(staticIpListFallbackAttempted)}
                    </span>
                    <span className="hint">
                      static_ip_list_fallback_match_count:{" "}
                      {staticIpListFallbackMatchCount !== null ? String(staticIpListFallbackMatchCount) : "Not available"}
                    </span>
                    <span className="hint">
                      static_ip_list_fallback_address_present: {formatBooleanStateLabel(staticIpListFallbackAddressPresent)}
                    </span>
                    <span className="hint">
                      static_ip_list_fallback_response_keys:{" "}
                      {staticIpListFallbackResponseKeys.length > 0 ? staticIpListFallbackResponseKeys.join(", ") : "Not available"}
                    </span>
                    <span className="hint">ingress_status_ip: {ingressStatusIp || "Not available"}</span>
                    <span className="hint">
                      ingress_status_ip_matches_static_ip: {formatBooleanStateLabel(ingressStatusIpMatchesStaticIp)}
                    </span>
                    <span className="hint">
                      static_ip_bound_to_expected_forwarding_rule:{" "}
                      {formatBooleanStateLabel(staticIpBoundToExpectedForwardingRule)}
                    </span>
                    <span className="hint">
                      observed_managed_certificate_status: {observedManagedCertificateStatus || "Not available"}
                    </span>
                    <span className="hint">
                      observed_managed_certificate_domain_status:{" "}
                      {observedManagedCertificateDomainStatus || "Not available"}
                    </span>
                    <span className="hint">
                      observed_managed_certificate_domains: {observedManagedCertificateDomains || "Not available"}
                    </span>
                    <span className="hint">
                      gce_backend_health_status: {gceBackendHealthStatus || "Not available"}
                    </span>
                    <span className="hint">service_probe_status: {serviceProbeStatus || "Not available"}</span>
                    <span className="hint">
                      in_cluster_service_status_code:{" "}
                      {inClusterServiceStatusCode !== null ? String(inClusterServiceStatusCode) : "Not available"}
                    </span>
                    <span className="hint">endpoint_probe_status: {endpointProbeStatus || "Not available"}</span>
                    <span className="hint">
                      endpoint_probe_status_code:{" "}
                      {endpointProbeStatusCode !== null ? String(endpointProbeStatusCode) : "Not available"}
                    </span>
                    <span className="hint">runtime_probe_status: {runtimeProbeStatus || "Not available"}</span>
                    <span className="hint">pod_restart_detected: {formatBooleanStateLabel(podRestartDetected)}</span>
                    <span className="hint">
                      current_live_evidence_checked_at:{" "}
                      {currentLiveEvidenceCheckedAt ? formatAttemptTimestamp(currentLiveEvidenceCheckedAt) : "Not available"}
                    </span>
                    <span className="hint">
                      current_live_evidence_source: {currentLiveEvidenceSource || "Not available"}
                    </span>
                    {workflowContractAdvisory ? (
                      <span className="hint warning">Workflow contract advisory: {workflowContractAdvisory}</span>
                    ) : null}
                    {deployFailureMessage ? <span className="hint warning">{deployFailureMessage}</span> : null}
                    {deployFailureRemediationHintDisplay ? (
                      <span className="hint warning">Remediation hint: {deployFailureRemediationHintDisplay}</span>
                    ) : null}
                  </details>
                </div>
              </div>
            </div>

            <div className="migration-diagnostics-shell" data-testid="migration-draft-diagnostics-shell">
              <div className="panel panel-compact stack-tight migration-diagnostics-shell-panel" data-testid="migration-draft-diagnostics">
                <strong>Draft Diagnostics</strong>
                <span className="hint muted">
                  {selectedArtifact
                    ? `Context: selected draft artifact v${selectedArtifact.version}`
                    : "Context: latest draft summary"}
                </span>
                {draftDiagnosticsUsingSummaryFallback ? (
                  <span className="hint muted" data-testid="migration-draft-diagnostics-fallback-note">
                    Selected artifact lacks draft-failure details; showing latest draft summary diagnostics.
                  </span>
                ) : null}
                {asString(migrationDiagnostics.last_draft_failure_category) ? (
                  <span className="hint warning">
                    Draft failure category: {toFailureCategoryLabel(asString(migrationDiagnostics.last_draft_failure_category))}
                  </span>
                ) : (
                  <span className="hint muted">No draft failure recorded.</span>
                )}
                {draftFailureMessage ? (
                  <span className="hint warning">{draftFailureMessage}</span>
                ) : null}
                {draftFailureSourceLabel ? (
                  <span className="hint warning">Draft failure source: {draftFailureSourceLabel}</span>
                ) : null}
                {draftAuthIntegrationGuidance ? (
                  <span className="hint warning" data-testid="migration-draft-auth-guidance">
                    {draftAuthIntegrationGuidance}
                  </span>
                ) : null}
                {draftAIFailureCategory || draftAIFailureReason || draftAIHint ? (
                  <span className="hint">
                    AI diagnostics: {draftAIFailureCategory ? toFailureCategoryLabel(draftAIFailureCategory) : "n/a"}
                    {draftAIFailureReason ? ` / ${formatReasonCodeLabel(draftAIFailureReason)}` : ""}
                    {draftAIHint ? ` — ${draftAIHint}` : ""}
                  </span>
                ) : null}
                {draftAIFailureSource || draftAIBudgetOutcome || draftAIRetrySuppressed !== null ? (
                  <span className="hint muted">
                    AI execution: source {draftAIFailureSource ? formatReasonCodeLabel(draftAIFailureSource) : "n/a"}
                    {draftAIBudgetOutcome ? `; budget ${formatReasonCodeLabel(draftAIBudgetOutcome)}` : ""}
                    {draftAIRetrySuppressed !== null
                      ? `; retry suppressed ${draftAIRetrySuppressed ? "yes" : "no"}`
                      : ""}
                    {draftAITrimmingPassCount !== null ? `; trim passes ${draftAITrimmingPassCount}` : ""}
                    {draftAIDifficultyBucket ? `; difficulty ${formatReasonCodeLabel(draftAIDifficultyBucket)}` : ""}
                    {draftAIInputSizeBucket ? `; input ${formatReasonCodeLabel(draftAIInputSizeBucket)}` : ""}
                    {draftAIDegradedState ? `; degraded ${formatReasonCodeLabel(draftAIDegradedState)}` : ""}
                    {draftAIRetryable !== null ? `; retryable ${draftAIRetryable ? "yes" : "no"}` : ""}
                  </span>
                ) : null}
                {draftContractStatus ? (
                  <span className="hint">Draft contract status: {draftContractStatus.replace(/_/g, " ")}</span>
                ) : null}
                {draftContractIssueFocus ? (
                  <span className="hint warning" data-testid="migration-draft-contract-issue-focus">
                    Contract diagnosis: {draftContractIssueFocus}
                  </span>
                ) : null}
                {draftContractRetryGuidance ? (
                  <span className="hint warning" data-testid="migration-draft-contract-retry-guidance">
                    Retry guidance: {draftContractRetryGuidance}
                  </span>
                ) : null}
                {draftContractReasonCodes.length > 0 ? (
                  <span className="hint">
                    Contract reason codes: {draftContractReasonCodes.map((item) => formatReasonCodeLabel(item)).join(", ")}
                  </span>
                ) : null}
                {draftContractWarningCodes.length > 0 ? (
                  <span className="hint">
                    Contract warning codes: {draftContractWarningCodes.map((item) => formatReasonCodeLabel(item)).join(", ")}
                  </span>
                ) : null}
                {draftContractCandidateItemCount !== null ||
                draftContractNormalizedItemCount !== null ||
                draftContractDroppedItemCount !== null ? (
                  <span className="hint">
                    Candidate items: {draftContractCandidateItemCount ?? "n/a"}; normalized:{" "}
                    {draftContractNormalizedItemCount ?? "n/a"}; dropped: {draftContractDroppedItemCount ?? "n/a"}
                  </span>
                ) : null}
                {draftContractRequiredFilesExpected.length > 0 ? (
                  <span className="hint">
                    Required files expected: {draftContractRequiredFilesExpected.join(", ")}
                  </span>
                ) : null}
                {draftContractRequiredFilesPresent.length > 0 ? (
                  <span className="hint">
                    Required files present: {draftContractRequiredFilesPresent.join(", ")}
                  </span>
                ) : null}
                {draftContractMissingRequiredFiles.length > 0 ? (
                  <span className="hint warning">
                    Missing required files: {draftContractMissingRequiredFiles.join(", ")}
                  </span>
                ) : null}
                {draftContractContentDensityFailuresByFile.length > 0 ? (
                  <span className="hint warning">
                    Content density failures by file: {draftContractContentDensityFailuresByFile.join(", ")}
                  </span>
                ) : null}
                {Object.keys(draftContractParserRejectionReasonCounts).length > 0 ? (
                  <span className="hint warning">
                    Parser rejection reasons: {draftContractParserRejectionSummary}
                  </span>
                ) : null}
                {draftContractPrimaryFileDetected !== null ? (
                  <span className="hint">
                    Primary file detected:{" "}
                    {formatBooleanStateLabel(draftContractPrimaryFileDetected, { trueLabel: "Yes", falseLabel: "No" })}
                  </span>
                ) : null}
              </div>
            </div>
          </div>
        </details>
      </div>
      </MigrationAdvancedDiagnosticsSection>
    </div>
  );
}
