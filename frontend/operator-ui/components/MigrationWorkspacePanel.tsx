"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import {
  ApiRequestError,
  approveMigrationArtifactVersion,
  deployMigrationArtifactVersion,
  fetchMigrationArtifactFilePreview,
  fetchMigrationArtifactVersions,
  fetchMigrationDeployHistory,
  fetchMigrationPublishHistory,
  fetchMigrationWorkspaceSummary,
  generateMigrationDraftArtifacts,
  ingestMigrationSource,
  publishMigrationArtifactVersion,
  updateMigrationAnalyticsConfig,
  updateMigrationDeployConfig,
  updateMigrationEnrichedContent,
  updateMigrationPublishConfig,
  updateMigrationRequirements,
  upsertMigrationWorkspace,
} from "../lib/api/client";
import type {
  MigrationAnalyticsConfig,
  MigrationArtifactVersion,
  MigrationDeployConfig,
  MigrationEnrichedContentNotes,
  MigrationOperatorRequirements,
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
  | "save_enriched"
  | "save_publish_config"
  | "save_deploy_config"
  | "save_analytics_config"
  | "generate"
  | "approve"
  | "publish"
  | "deploy"
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

const EMPTY_ENRICHED_CONTENT: MigrationEnrichedContentNotes = {
  replacement_summary: null,
  homepage_value_proposition: null,
  about_business: null,
  service_highlights: [],
  trust_signals: [],
  faq_items: [],
  contact_overrides: {},
  additional_notes: null,
};

const EMPTY_PUBLISH_CONFIG: MigrationPublishConfig = {
  enabled: false,
  repo_owner: null,
  repo_name: null,
  branch: "main",
  artifact_root: "",
};

const EMPTY_DEPLOY_CONFIG: MigrationDeployConfig = {
  enabled: false,
  repo_owner: null,
  repo_name: null,
  workflow_id: "deploy-www-prod.yml",
  ref: "main",
  inputs: {},
};

const EMPTY_ANALYTICS_CONFIG: MigrationAnalyticsConfig = {
  enabled: true,
  ga_measurement_id: null,
  insertion_mode: "publish_and_deploy",
};

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
}

function toFailureCategoryLabel(value: string | null): string {
  if (!value) {
    return "unknown";
  }
  return value.replace(/_/g, " ");
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
  if (normalized.includes("not configured") || normalized.includes("configuration")) {
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
  let retryable: boolean | null = null;
  let correlationId: string | null = null;
  let timeoutSeconds: number | null = null;
  if (error instanceof ApiRequestError) {
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
  } else if (category === "config_missing" || reason === "authentication_failed" || reason === "unsupported_configuration") {
    hint = "Check AI provider configuration.";
  } else if (
    category === "artifact_invalid" ||
    reason === "malformed_response" ||
    reason === "empty_response" ||
    reason === "validation_failed"
  ) {
    hint = "The provider returned an invalid draft payload.";
  } else if (retryable) {
    hint = "This looks retryable.";
  }
  return {
    message,
    hint,
    correlationId,
  };
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

function asStringList(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((item) => String(item || "").trim())
    .filter((item) => item.length > 0);
}

function parseInputsText(value: string): Record<string, string> {
  const lines = splitLines(value);
  const result: Record<string, string> = {};
  for (const line of lines) {
    const [rawKey, ...rest] = line.split("=");
    const key = (rawKey || "").trim();
    const entryValue = rest.join("=").trim();
    if (!key || !entryValue) {
      continue;
    }
    result[key] = entryValue;
  }
  return result;
}

function stringifyInputsMap(value: unknown): string {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return "";
  }
  return Object.entries(value as Record<string, unknown>)
    .map(([key, item]) => `${String(key).trim()}=${String(item || "").trim()}`)
    .filter((line) => line !== "=")
    .join("\n");
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

function toDraftReadinessStatusLabel(value: DraftReadinessStatus): string {
  if (value === "ready") {
    return "Ready";
  }
  if (value === "ready_with_warnings") {
    return "Ready with warnings";
  }
  return "Not ready";
}

function parseDraftReadiness(contextSummary: Record<string, unknown>): DraftReadinessEvaluation {
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
    enriched_content_present: Boolean(contextSummary.has_enriched_content_notes),
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
  if (!fallbackSignals.enriched_content_present) {
    fallbackReasons.push({
      code: "enriched_content_required",
      severity: "blocking",
      message: "Add enriched replacement content notes before generating a draft.",
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
    fallbackScore += 15;
  }
  if (fallbackSignals.operator_requirements_present) {
    fallbackScore += 25;
  }
  if (fallbackSignals.enriched_content_present) {
    fallbackScore += 25;
  }
  if (fallbackSignals.audit_available) {
    fallbackScore += 10;
  }
  if (fallbackSignals.recommendations_available) {
    fallbackScore += 10;
  }
  if (fallbackSignals.competitors_available) {
    fallbackScore += 10;
  }
  if (
    fallbackSignals.source_site_ingested &&
    fallbackSignals.operator_requirements_present &&
    fallbackSignals.enriched_content_present &&
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
        : "Not ready yet — add enriched content and operator requirements first.";

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
      summary: draftReadiness.summary || "Not ready yet — resolve blocking migration readiness issues.",
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
  };
}

function toDraftFailureSourceLabel(value: string | null): string | null {
  const normalized = (value || "").trim().toLowerCase();
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

function parseGeneratedPaths(artifact: MigrationArtifactVersion | null): string[] {
  if (!artifact || !Array.isArray(artifact.generated_files_json)) {
    return [];
  }
  return artifact.generated_files_json
    .map((item) => {
      if (!item || typeof item !== "object") {
        return "";
      }
      return String((item as Record<string, unknown>).path || "").trim();
    })
    .filter((path) => path.length > 0);
}

interface ReusedContextEntry {
  available: boolean | null;
  source: string | null;
  timestamp: string | null;
  count: number | null;
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

  const [sourceUrl, setSourceUrl] = useState("");
  const [businessObjectives, setBusinessObjectives] = useState("");
  const [requestedPages, setRequestedPages] = useState("");
  const [mustInclude, setMustInclude] = useState("");
  const [mustAvoid, setMustAvoid] = useState("");
  const [tonePreferences, setTonePreferences] = useState("");
  const [callsToAction, setCallsToAction] = useState("");
  const [requirementsNotes, setRequirementsNotes] = useState("");

  const [replacementSummary, setReplacementSummary] = useState("");
  const [homepageValueProposition, setHomepageValueProposition] = useState("");
  const [aboutBusiness, setAboutBusiness] = useState("");
  const [serviceHighlights, setServiceHighlights] = useState("");
  const [trustSignals, setTrustSignals] = useState("");
  const [faqItems, setFaqItems] = useState("");
  const [contactOverrides, setContactOverrides] = useState("");
  const [enrichedNotes, setEnrichedNotes] = useState("");

  const [publishEnabled, setPublishEnabled] = useState(false);
  const [publishRepoOwner, setPublishRepoOwner] = useState("");
  const [publishRepoName, setPublishRepoName] = useState("");
  const [publishBranch, setPublishBranch] = useState("main");
  const [publishArtifactRoot, setPublishArtifactRoot] = useState("");

  const [deployEnabled, setDeployEnabled] = useState(false);
  const [deployRepoOwner, setDeployRepoOwner] = useState("");
  const [deployRepoName, setDeployRepoName] = useState("");
  const [deployWorkflowId, setDeployWorkflowId] = useState("deploy-www-prod.yml");
  const [deployRef, setDeployRef] = useState("main");
  const [deployInputsText, setDeployInputsText] = useState("");

  const [analyticsEnabled, setAnalyticsEnabled] = useState(true);
  const [analyticsMeasurementId, setAnalyticsMeasurementId] = useState("");
  const [analyticsMode, setAnalyticsMode] = useState<"publish_only" | "publish_and_deploy">("publish_and_deploy");

  const [selectedArtifactVersionId, setSelectedArtifactVersionId] = useState("");
  const [approvalNotes, setApprovalNotes] = useState("");
  const [publishDryRun, setPublishDryRun] = useState(true);
  const [publishCommitMessage, setPublishCommitMessage] = useState("");
  const [publishAnalyticsOverride, setPublishAnalyticsOverride] = useState("");
  const [deployDryRun, setDeployDryRun] = useState(true);

  const [selectedFilePath, setSelectedFilePath] = useState("");
  const [filePreviewContent, setFilePreviewContent] = useState("");
  const [filePreviewMediaType, setFilePreviewMediaType] = useState("");

  const selectedArtifact = useMemo(() => {
    if (!selectedArtifactVersionId) {
      return null;
    }
    return artifactVersions.find((item) => item.id === selectedArtifactVersionId) || null;
  }, [artifactVersions, selectedArtifactVersionId]);

  const sourceSnapshot = summary?.source_snapshot || null;
  const publishReadiness = asRecord(summary?.publish_readiness || {});
  const deployReadiness = asRecord(summary?.deploy_readiness || {});
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
  const publishConfigPrerequisites = asRecord(publishReadiness.config_prerequisites);
  const deployConfigPrerequisites = asRecord(deployReadiness.config_prerequisites);
  const publishFailureCategory = asString(publishReadiness.last_failure_category || publishReadiness.failure_category) || null;
  const deployFailureCategory = asString(deployReadiness.last_failure_category || deployReadiness.failure_category) || null;
  const publishFailureMessage = asString(publishReadiness.last_failure_message) || null;
  const deployFailureMessage = asString(deployReadiness.last_failure_message) || null;
  const contextSummary = asRecord(summary?.context_summary);
  const migrationDiagnostics = asRecord(contextSummary.migration_diagnostics);
  const draftReadiness = parseDraftReadiness(contextSummary);
  const draftProviderCompatibility = parseDraftProviderCompatibility(contextSummary, migrationDiagnostics);
  const draftGenerationState = parseDraftGenerationState({
    contextSummary,
    draftReadiness,
    draftProviderCompatibility,
    migrationDiagnostics,
  });
  const draftAIExecution = parseDraftAIExecutionSummary(contextSummary, migrationDiagnostics);
  const draftFailureSourceLabel = toDraftFailureSourceLabel(
    asStringOrNull(migrationDiagnostics.last_draft_failure_source) || draftAIExecution.failureSource,
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
  const draftProviderCompatibilityStatusLabel = draftProviderCompatibility.supported ? "Supported" : "Unsupported";
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

    const rawEnriched = asRecord(workspace.enriched_content_notes_json);
    setReplacementSummary(asString(rawEnriched.replacement_summary));
    setHomepageValueProposition(asString(rawEnriched.homepage_value_proposition));
    setAboutBusiness(asString(rawEnriched.about_business));
    setServiceHighlights(joinLines(asStringList(rawEnriched.service_highlights)));
    setTrustSignals(joinLines(asStringList(rawEnriched.trust_signals)));
    setFaqItems(joinLines(asStringList(rawEnriched.faq_items)));
    setContactOverrides(stringifyInputsMap(rawEnriched.contact_overrides));
    setEnrichedNotes(asString(rawEnriched.additional_notes));

    const rawPublishConfig = asRecord(workspace.publish_config_json);
    setPublishEnabled(Boolean(rawPublishConfig.enabled));
    setPublishRepoOwner(asString(rawPublishConfig.repo_owner));
    setPublishRepoName(asString(rawPublishConfig.repo_name));
    setPublishBranch(asString(rawPublishConfig.branch) || "main");
    setPublishArtifactRoot(asString(rawPublishConfig.artifact_root));

    const rawDeployConfig = asRecord(workspace.deploy_config_json);
    setDeployEnabled(Boolean(rawDeployConfig.enabled));
    setDeployRepoOwner(asString(rawDeployConfig.repo_owner));
    setDeployRepoName(asString(rawDeployConfig.repo_name));
    setDeployWorkflowId(asString(rawDeployConfig.workflow_id) || "deploy-www-prod.yml");
    setDeployRef(asString(rawDeployConfig.ref) || "main");
    setDeployInputsText(stringifyInputsMap(rawDeployConfig.inputs));

    const rawAnalyticsConfig = asRecord(workspace.analytics_config_json);
    setAnalyticsEnabled(rawAnalyticsConfig.enabled !== false);
    setAnalyticsMeasurementId(asString(rawAnalyticsConfig.ga_measurement_id));
    const mode = asString(rawAnalyticsConfig.insertion_mode);
    if (mode === "publish_only" || mode === "publish_and_deploy") {
      setAnalyticsMode(mode);
    } else {
      setAnalyticsMode("publish_and_deploy");
    }
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
        const [workspaceSummary, versionList, publishHistoryResponse, deployHistoryResponse] = await Promise.all([
          fetchMigrationWorkspaceSummary(token, businessId, siteId),
          fetchMigrationArtifactVersions(token, businessId, siteId),
          fetchMigrationPublishHistory(token, businessId, siteId),
          fetchMigrationDeployHistory(token, businessId, siteId),
        ]);
        setSummary(workspaceSummary);
        setArtifactVersions(versionList.items || []);
        setPublishHistory(publishHistoryResponse.items || workspaceSummary.publish_history || []);
        setDeployHistory(deployHistoryResponse.items || workspaceSummary.deploy_history || []);
        hydrateFromSummary(workspaceSummary);
        const fallbackArtifactId =
          workspaceSummary.workspace.latest_approved_artifact_version_id ||
          workspaceSummary.workspace.latest_generated_artifact_version_id ||
          versionList.items?.[0]?.id ||
          "";
        setSelectedArtifactVersionId((current) => current || fallbackArtifactId);
      } catch (error) {
        setErrorHint(null);
        setErrorMessage(toErrorMessage(error, "Failed to load migration workspace."));
      } finally {
        setBusyAction(null);
      }
    },
    [businessId, hydrateFromSummary, siteId, token],
  );

  useEffect(() => {
    void loadWorkspaceData(true);
  }, [loadWorkspaceData]);

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

  const handleSaveEnrichedContent = async (): Promise<void> => {
    const payload: MigrationEnrichedContentNotes = {
      ...EMPTY_ENRICHED_CONTENT,
      replacement_summary: asStringOrNull(replacementSummary),
      homepage_value_proposition: asStringOrNull(homepageValueProposition),
      about_business: asStringOrNull(aboutBusiness),
      service_highlights: splitLines(serviceHighlights),
      trust_signals: splitLines(trustSignals),
      faq_items: splitLines(faqItems),
      contact_overrides: parseInputsText(contactOverrides),
      additional_notes: asStringOrNull(enrichedNotes),
    };
    setBusyAction("save_enriched");
    setErrorMessage(null);
    setErrorHint(null);
    setStatusMessage(null);
    try {
      await updateMigrationEnrichedContent(token, businessId, siteId, {
        enriched_content_notes: payload,
      });
      setStatusMessage("Enriched replacement content saved.");
      await loadWorkspaceData(false);
    } catch (error) {
      setErrorHint(null);
      setErrorMessage(toErrorMessage(error, "Failed to save enriched content."));
    } finally {
      setBusyAction(null);
    }
  };

  const handleSavePublishConfig = async (): Promise<void> => {
    const payload: MigrationPublishConfig = {
      ...EMPTY_PUBLISH_CONFIG,
      enabled: publishEnabled,
      repo_owner: asStringOrNull(publishRepoOwner),
      repo_name: asStringOrNull(publishRepoName),
      branch: publishBranch.trim() || "main",
      artifact_root: publishArtifactRoot.trim(),
    };
    setBusyAction("save_publish_config");
    setErrorMessage(null);
    setErrorHint(null);
    setStatusMessage(null);
    try {
      await updateMigrationPublishConfig(token, businessId, siteId, {
        publish_config: payload,
      });
      setStatusMessage("Publish target configuration saved.");
      await loadWorkspaceData(false);
    } catch (error) {
      setErrorHint(null);
      setErrorMessage(toErrorMessage(error, "Failed to save publish target."));
    } finally {
      setBusyAction(null);
    }
  };

  const handleSaveDeployConfig = async (): Promise<void> => {
    const payload: MigrationDeployConfig = {
      ...EMPTY_DEPLOY_CONFIG,
      enabled: deployEnabled,
      repo_owner: asStringOrNull(deployRepoOwner),
      repo_name: asStringOrNull(deployRepoName),
      workflow_id: asStringOrNull(deployWorkflowId),
      ref: asStringOrNull(deployRef),
      inputs: parseInputsText(deployInputsText),
    };
    setBusyAction("save_deploy_config");
    setErrorMessage(null);
    setErrorHint(null);
    setStatusMessage(null);
    try {
      await updateMigrationDeployConfig(token, businessId, siteId, {
        deploy_config: payload,
      });
      setStatusMessage("Deploy target configuration saved.");
      await loadWorkspaceData(false);
    } catch (error) {
      setErrorHint(null);
      setErrorMessage(toErrorMessage(error, "Failed to save deploy target."));
    } finally {
      setBusyAction(null);
    }
  };

  const handleSaveAnalyticsConfig = async (): Promise<void> => {
    const payload: MigrationAnalyticsConfig = {
      ...EMPTY_ANALYTICS_CONFIG,
      enabled: analyticsEnabled,
      ga_measurement_id: asStringOrNull(analyticsMeasurementId),
      insertion_mode: analyticsMode,
    };
    setBusyAction("save_analytics_config");
    setErrorMessage(null);
    setErrorHint(null);
    setStatusMessage(null);
    try {
      await updateMigrationAnalyticsConfig(token, businessId, siteId, {
        analytics_config: payload,
      });
      setStatusMessage("Analytics insertion rules saved.");
      await loadWorkspaceData(false);
    } catch (error) {
      setErrorHint(null);
      setErrorMessage(toErrorMessage(error, "Failed to save analytics rules."));
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
      await publishMigrationArtifactVersion(token, businessId, siteId, {
        artifact_version_id: selectedArtifactVersionId,
        dry_run: publishDryRun,
        commit_message: asStringOrNull(publishCommitMessage),
        analytics_measurement_id: asStringOrNull(publishAnalyticsOverride),
      });
      setStatusMessage(publishDryRun ? "Publish dry-run completed." : "Publish to GitHub completed.");
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

  const handleSelectArtifactFile = async (path: string): Promise<void> => {
    if (!selectedArtifactVersionId || !path) {
      return;
    }
    setSelectedFilePath(path);
    setErrorMessage(null);
    setErrorHint(null);
    try {
      const preview = await fetchMigrationArtifactFilePreview(
        token,
        businessId,
        siteId,
        selectedArtifactVersionId,
        path,
      );
      setFilePreviewMediaType(preview.media_type);
      setFilePreviewContent(preview.content);
    } catch (error) {
      setFilePreviewMediaType("text/plain");
      setFilePreviewContent("");
      setErrorHint(null);
      setErrorMessage(toErrorMessage(error, "Failed to load artifact file preview."));
    }
  };

  const filePaths = useMemo(() => parseGeneratedPaths(selectedArtifact), [selectedArtifact]);

  if (busyAction === "load" && !summary) {
    return <p className="hint muted">Loading migration workspace...</p>;
  }

  return (
    <div className="stack" data-testid="migration-workspace-panel">
      <div className="panel panel-compact stack" data-testid="migration-draft-banner">
        <strong>Draft-only mode: generated files are review artifacts pending explicit approval/publish/deploy.</strong>
        <span className="hint">
          Legacy source content may be incomplete or poor quality. Operator requirements and enriched content can
          override weak source material.
        </span>
        <span className="hint warning">GitHub publish does not equal production deployment. Deploy remains explicit.</span>
      </div>

      <div className="panel panel-compact stack-tight" data-testid="migration-current-state">
        <strong>Current Migration State</strong>
        <span className="hint">State: {draftGenerationStateLabel}</span>
        <span className={draftGenerationStateToneClass}>{draftGenerationState.summary}</span>
        <span className="hint" data-testid="migration-ai-execution-summary">
          AI execution: {aiExecutionSummaryLabel}
        </span>
        <span className="hint" data-testid="migration-ai-model-used">
          Generated using: {draftAIExecution.modelUsed || draftAIExecution.modelResolved || "n/a"}
        </span>
        <span className="hint" data-testid="migration-ai-request-profile">
          Request profile: {requestProfileLabel}
        </span>
        {requestContractStatusLabel ? (
          <span className="hint" data-testid="migration-request-contract-status">
            Request contract: {requestContractStatusLabel}
          </span>
        ) : null}
        {artifactResultLabel ? (
          <span className="hint" data-testid="migration-artifact-result">
            Artifact result: {artifactResultLabel}
          </span>
        ) : null}
        {draftDurationLabel ? (
          <span className="hint" data-testid="migration-ai-duration">
            Duration: {draftDurationLabel}
          </span>
        ) : null}
        {showDraftTimeout ? (
          <span className="hint" data-testid="migration-draft-timeout">
            Timeout: {draftTimeoutLabel}
            {draftAIExecution.timeoutSource ? ` (${draftAIExecution.timeoutSource})` : ""}
          </span>
        ) : null}
        {draftFailureSourceLabel ? (
          <span className="hint warning" data-testid="migration-draft-failure-source">
            Failure source: {draftFailureSourceLabel}
          </span>
        ) : null}
      </div>

      {errorMessage ? <p className="hint warning">{errorMessage}</p> : null}
      {errorMessage && errorHint ? (
        <p className="hint muted" data-testid="migration-error-hint">
          {errorHint}
        </p>
      ) : null}
      {statusMessage ? <p className="hint success">{statusMessage}</p> : null}

      <div className="panel stack">
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
        <button
          type="button"
          className="button button-primary"
          onClick={() => void handleIngestSource()}
          disabled={busyAction === "ingest" || busyAction === "load"}
        >
          {busyAction === "ingest" ? "Ingesting..." : "Ingest / Refresh Source"}
        </button>
      </div>

      <div className="panel stack" data-testid="migration-source-summary">
        <h3>Source Snapshot Summary</h3>
        {sourceSnapshot ? (
          <div className="stack-tight">
            <span className="hint">Title: {asString(sourceSnapshot.title) || "-"}</span>
            <span className="hint">Description: {asString(sourceSnapshot.meta_description) || "-"}</span>
            <span className="hint">Canonical: {asString(sourceSnapshot.canonical_url) || "-"}</span>
            <span className="hint">Headings: {asStringList(sourceSnapshot.headings).length}</span>
            <span className="hint">Internal links: {asStringList(sourceSnapshot.internal_links).length}</span>
          </div>
        ) : (
          <p className="hint muted">No source snapshot ingested yet.</p>
        )}
      </div>

      <div className="grid grid-2">
        <div className="panel stack">
          <h3>Operator Requirements</h3>
          <label className="stack-tight">
            <span className="hint muted">Business objectives (one per line)</span>
            <textarea value={businessObjectives} onChange={(event) => setBusinessObjectives(event.target.value)} rows={5} />
          </label>
          <label className="stack-tight">
            <span className="hint muted">Requested pages (one per line)</span>
            <textarea value={requestedPages} onChange={(event) => setRequestedPages(event.target.value)} rows={3} />
          </label>
          <label className="stack-tight">
            <span className="hint muted">Must include (one per line)</span>
            <textarea value={mustInclude} onChange={(event) => setMustInclude(event.target.value)} rows={3} />
          </label>
          <label className="stack-tight">
            <span className="hint muted">Must avoid (one per line)</span>
            <textarea value={mustAvoid} onChange={(event) => setMustAvoid(event.target.value)} rows={3} />
          </label>
          <label className="stack-tight">
            <span className="hint muted">Tone preferences (one per line)</span>
            <textarea value={tonePreferences} onChange={(event) => setTonePreferences(event.target.value)} rows={3} />
          </label>
          <label className="stack-tight">
            <span className="hint muted">Calls to action (one per line)</span>
            <textarea value={callsToAction} onChange={(event) => setCallsToAction(event.target.value)} rows={3} />
          </label>
          <label className="stack-tight">
            <span className="hint muted">Additional requirements notes</span>
            <textarea value={requirementsNotes} onChange={(event) => setRequirementsNotes(event.target.value)} rows={4} />
          </label>
          <button
            type="button"
            className="button button-secondary"
            onClick={() => void handleSaveRequirements()}
            disabled={busyAction === "save_requirements" || busyAction === "load"}
          >
            {busyAction === "save_requirements" ? "Saving..." : "Save Requirements"}
          </button>
        </div>

        <div className="panel stack">
          <h3>Enriched Replacement Content</h3>
          <label className="stack-tight">
            <span className="hint muted">Replacement summary</span>
            <textarea value={replacementSummary} onChange={(event) => setReplacementSummary(event.target.value)} rows={4} />
          </label>
          <label className="stack-tight">
            <span className="hint muted">Homepage value proposition</span>
            <textarea
              value={homepageValueProposition}
              onChange={(event) => setHomepageValueProposition(event.target.value)}
              rows={3}
            />
          </label>
          <label className="stack-tight">
            <span className="hint muted">About business</span>
            <textarea value={aboutBusiness} onChange={(event) => setAboutBusiness(event.target.value)} rows={3} />
          </label>
          <label className="stack-tight">
            <span className="hint muted">Service highlights (one per line)</span>
            <textarea value={serviceHighlights} onChange={(event) => setServiceHighlights(event.target.value)} rows={3} />
          </label>
          <label className="stack-tight">
            <span className="hint muted">Trust signals (one per line)</span>
            <textarea value={trustSignals} onChange={(event) => setTrustSignals(event.target.value)} rows={3} />
          </label>
          <label className="stack-tight">
            <span className="hint muted">FAQ items (one per line)</span>
            <textarea value={faqItems} onChange={(event) => setFaqItems(event.target.value)} rows={3} />
          </label>
          <label className="stack-tight">
            <span className="hint muted">Contact overrides (`key=value` per line)</span>
            <textarea value={contactOverrides} onChange={(event) => setContactOverrides(event.target.value)} rows={3} />
          </label>
          <label className="stack-tight">
            <span className="hint muted">Additional enriched notes</span>
            <textarea value={enrichedNotes} onChange={(event) => setEnrichedNotes(event.target.value)} rows={4} />
          </label>
          <button
            type="button"
            className="button button-secondary"
            onClick={() => void handleSaveEnrichedContent()}
            disabled={busyAction === "save_enriched" || busyAction === "load"}
          >
            {busyAction === "save_enriched" ? "Saving..." : "Save Enriched Content"}
          </button>
        </div>
      </div>

      <div className="panel stack" data-testid="migration-reused-context">
        <h3>Reused MBSRN Context</h3>
        <div className="grid grid-3">
          <div className="panel panel-compact stack-tight">
            <strong>Audit</strong>
            <span className="hint" data-testid="migration-reused-context-audit-status">{auditContextLabel}</span>
          </div>
          <div className="panel panel-compact stack-tight">
            <strong>Recommendations</strong>
            <span className="hint" data-testid="migration-reused-context-recommendations-status">{recommendationContextLabel}</span>
          </div>
          <div className="panel panel-compact stack-tight">
            <strong>Competitors</strong>
            <span className="hint" data-testid="migration-reused-context-competitors-status">{competitorContextLabel}</span>
          </div>
        </div>
      </div>

      <div className="panel stack">
        <h3>Draft Artifact Generation</h3>
        <div className="panel panel-compact stack-tight" data-testid="migration-draft-readiness">
          <strong>Preflight Readiness</strong>
          <span className="hint">Status: {draftReadinessStatusLabel}</span>
          <span className="hint">Readiness score: {draftReadiness.score}/100</span>
          <span className={draftReadinessToneClass}>{draftReadiness.summary}</span>
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
          <span className={draftProviderCompatibility.supported ? "hint success" : "hint warning"}>
            {draftProviderCompatibility.operatorMessage}
          </span>
        </div>
        <button
          type="button"
          className="button button-primary"
          onClick={() => void handleGenerateArtifacts()}
          disabled={busyAction === "generate" || busyAction === "load" || draftGenerationBlocked}
        >
          {busyAction === "generate" ? "Generating..." : "Generate Draft Mockup"}
        </button>
        {draftGenerationBlocked ? (
          <span className="hint warning">{draftGenerationBlockedMessage}</span>
        ) : null}
      </div>

      <div className="panel stack">
        <h3>Draft Artifact Review</h3>
        <label className="stack-tight">
          <span className="hint muted">Selected artifact version</span>
          <select
            value={selectedArtifactVersionId}
            onChange={(event) => {
              setSelectedArtifactVersionId(event.target.value);
              setSelectedFilePath("");
              setFilePreviewContent("");
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
            <div className="panel panel-compact stack-tight">
              <strong>Strategy Summary</strong>
              <p>{selectedArtifact.strategy_summary || "No strategy summary provided."}</p>
              {selectedArtifact.status === "partial" ? (
                <span className="hint warning" data-testid="migration-partial-draft-indicator">
                  Partial draft generated.
                </span>
              ) : null}
            </div>
            <div className="panel panel-compact stack-tight">
              <strong>Page Map</strong>
              {Array.isArray(selectedArtifact.page_map_json) && selectedArtifact.page_map_json.length > 0 ? (
                <ul>
                  {selectedArtifact.page_map_json.slice(0, 12).map((item, index) => {
                    const row = asRecord(item);
                    const path = asString(row.path) || "-";
                    const title = asString(row.title) || asString(row.name) || "Untitled";
                    return <li key={`page-map-${index}`}>{path} - {title}</li>;
                  })}
                </ul>
              ) : (
                <p className="hint muted">No page map entries.</p>
              )}
            </div>
            <div className="grid grid-2">
              <div className="panel panel-compact stack-tight" data-testid="migration-file-tree">
                <strong>Generated Files</strong>
                {filePaths.length > 0 ? (
                  filePaths.map((path) => (
                    <button
                      key={path}
                      type="button"
                      className={path === selectedFilePath ? "button button-tertiary button-inline active" : "button button-tertiary button-inline"}
                      onClick={() => void handleSelectArtifactFile(path)}
                    >
                      {path}
                    </button>
                  ))
                ) : (
                  <p className="hint muted">No files available.</p>
                )}
              </div>
              <div className="panel panel-compact stack-tight" data-testid="migration-file-preview">
                <strong>File Preview</strong>
                <span className="hint muted">{filePreviewMediaType || "Select a file to preview."}</span>
                <pre>{filePreviewContent || ""}</pre>
              </div>
            </div>
          </>
        ) : (
          <p className="hint muted">No artifact version selected.</p>
        )}
      </div>

      <div className="panel stack">
        <h3>Publish and Deploy Controls</h3>
        <span className="hint muted">
          Rollback is explicit: select a previously approved artifact and run publish/deploy again.
        </span>
        <span className="hint muted">
          Publish writes approved artifacts to GitHub only. Deploy remains a separate explicit request.
        </span>
        <div className="grid grid-2">
          <div className="panel panel-compact stack">
            <strong>GitHub Publish Target</strong>
            <label className="link-row">
              <input type="checkbox" checked={publishEnabled} onChange={(event) => setPublishEnabled(event.target.checked)} />
              <span>Publish enabled for this site workspace</span>
            </label>
            <input value={publishRepoOwner} onChange={(event) => setPublishRepoOwner(event.target.value)} placeholder="Repo owner" />
            <input value={publishRepoName} onChange={(event) => setPublishRepoName(event.target.value)} placeholder="Repo name" />
            <input value={publishBranch} onChange={(event) => setPublishBranch(event.target.value)} placeholder="Branch" />
            <input value={publishArtifactRoot} onChange={(event) => setPublishArtifactRoot(event.target.value)} placeholder="Artifact root (optional)" />
            <button
              type="button"
              className="button button-secondary"
              onClick={() => void handleSavePublishConfig()}
              disabled={busyAction === "save_publish_config" || busyAction === "load"}
            >
              {busyAction === "save_publish_config" ? "Saving..." : "Save Publish Target"}
            </button>
          </div>

          <div className="panel panel-compact stack">
            <strong>GKE Deploy Target</strong>
            <label className="link-row">
              <input type="checkbox" checked={deployEnabled} onChange={(event) => setDeployEnabled(event.target.checked)} />
              <span>Deploy enabled for this site workspace</span>
            </label>
            <input value={deployRepoOwner} onChange={(event) => setDeployRepoOwner(event.target.value)} placeholder="Repo owner (optional override)" />
            <input value={deployRepoName} onChange={(event) => setDeployRepoName(event.target.value)} placeholder="Repo name (optional override)" />
            <input value={deployWorkflowId} onChange={(event) => setDeployWorkflowId(event.target.value)} placeholder="Workflow ID" />
            <input value={deployRef} onChange={(event) => setDeployRef(event.target.value)} placeholder="Workflow ref" />
            <textarea
              value={deployInputsText}
              onChange={(event) => setDeployInputsText(event.target.value)}
              rows={4}
              placeholder="workflow inputs as key=value per line"
            />
            <button
              type="button"
              className="button button-secondary"
              onClick={() => void handleSaveDeployConfig()}
              disabled={busyAction === "save_deploy_config" || busyAction === "load"}
            >
              {busyAction === "save_deploy_config" ? "Saving..." : "Save Deploy Target"}
            </button>
          </div>
        </div>

        <div className="panel panel-compact stack">
          <strong>Analytics Insertion Rules</strong>
          <label className="link-row">
            <input type="checkbox" checked={analyticsEnabled} onChange={(event) => setAnalyticsEnabled(event.target.checked)} />
            <span>Enable controlled GA4 insertion</span>
          </label>
          <input
            value={analyticsMeasurementId}
            onChange={(event) => setAnalyticsMeasurementId(event.target.value)}
            placeholder="GA measurement ID (G-XXXX)"
          />
          <select
            value={analyticsMode}
            onChange={(event) =>
              setAnalyticsMode(event.target.value === "publish_only" ? "publish_only" : "publish_and_deploy")
            }
          >
            <option value="publish_and_deploy">Insert during publish and deploy</option>
            <option value="publish_only">Insert during publish only</option>
          </select>
          <button
            type="button"
            className="button button-secondary"
            onClick={() => void handleSaveAnalyticsConfig()}
            disabled={busyAction === "save_analytics_config" || busyAction === "load"}
          >
            {busyAction === "save_analytics_config" ? "Saving..." : "Save Analytics Rules"}
          </button>
        </div>

        <div className="grid grid-2">
          <div className="panel panel-compact stack" data-testid="migration-publish-readiness">
            <strong>Publish Readiness</strong>
            <span className="hint">Ready: {Boolean(publishReadiness.ready) ? "Yes" : "No"}</span>
            <span className="hint">
              Runtime config: {Boolean(publishConfigPrerequisites.github_publisher_configured) ? "Ready" : "Missing/invalid"}
            </span>
            {Array.isArray(publishReadiness.reasons) && publishReadiness.reasons.length > 0 ? (
              <ul>
                {(publishReadiness.reasons as unknown[]).map((reason, index) => (
                  <li key={`publish-reason-${index}`}>{String(reason)}</li>
                ))}
              </ul>
            ) : null}
            {publishFailureCategory ? (
              <span className="hint warning">Last failure category: {toFailureCategoryLabel(publishFailureCategory)}</span>
            ) : null}
            {publishFailureMessage ? <span className="hint warning">{publishFailureMessage}</span> : null}
          </div>
          <div className="panel panel-compact stack" data-testid="migration-deploy-readiness">
            <strong>Deploy Readiness</strong>
            <span className="hint">Ready: {Boolean(deployReadiness.ready) ? "Yes" : "No"}</span>
            <span className="hint">
              Runtime config: {Boolean(deployConfigPrerequisites.github_publisher_configured) ? "Ready" : "Missing/invalid"}
            </span>
            {Array.isArray(deployReadiness.reasons) && deployReadiness.reasons.length > 0 ? (
              <ul>
                {(deployReadiness.reasons as unknown[]).map((reason, index) => (
                  <li key={`deploy-reason-${index}`}>{String(reason)}</li>
                ))}
              </ul>
            ) : null}
            {deployFailureCategory ? (
              <span className="hint warning">Last failure category: {toFailureCategoryLabel(deployFailureCategory)}</span>
            ) : null}
            {deployFailureMessage ? <span className="hint warning">{deployFailureMessage}</span> : null}
          </div>
        </div>

        <div className="panel panel-compact stack-tight" data-testid="migration-action-diagnostics">
          <strong>Action Diagnostics</strong>
          <span className="hint">Last draft generation status: {asString(migrationDiagnostics.last_draft_generation_status) || "n/a"}</span>
          <span className="hint">Last publish status: {asString(migrationDiagnostics.last_publish_status) || "n/a"}</span>
          <span className="hint">Last deploy status: {asString(migrationDiagnostics.last_deploy_status) || "n/a"}</span>
          {asString(migrationDiagnostics.last_draft_failure_category) ? (
            <span className="hint warning">
              Draft failure category: {toFailureCategoryLabel(asString(migrationDiagnostics.last_draft_failure_category))}
            </span>
          ) : null}
          {asString(migrationDiagnostics.last_draft_failure_message) ? (
            <span className="hint warning">{asString(migrationDiagnostics.last_draft_failure_message)}</span>
          ) : null}
          {draftFailureSourceLabel ? (
            <span className="hint warning">Draft failure source: {draftFailureSourceLabel}</span>
          ) : null}
          {asString(migrationDiagnostics.last_publish_failure_category) ? (
            <span className="hint warning">
              Publish failure category: {toFailureCategoryLabel(asString(migrationDiagnostics.last_publish_failure_category))}
            </span>
          ) : null}
          {asString(migrationDiagnostics.last_deploy_failure_category) ? (
            <span className="hint warning">
              Deploy failure category: {toFailureCategoryLabel(asString(migrationDiagnostics.last_deploy_failure_category))}
            </span>
          ) : null}
        </div>

        <div className="grid grid-3">
          <div className="panel panel-compact stack">
            <strong>Approve</strong>
            <textarea
              value={approvalNotes}
              onChange={(event) => setApprovalNotes(event.target.value)}
              rows={3}
              placeholder="Approval notes (optional)"
            />
            <button
              type="button"
              className="button button-secondary"
              onClick={() => void handleApproveSelectedArtifact()}
              disabled={isActionInFlight || !canApproveSelectedArtifact}
            >
              {busyAction === "approve" ? "Approving..." : "Approve Selected Draft"}
            </button>
          </div>
          <div className="panel panel-compact stack">
            <strong>Publish</strong>
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
          <div className="panel panel-compact stack">
            <strong>Deploy</strong>
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
          </div>
        </div>

        <div className="grid grid-2">
          <div className="panel panel-compact stack" data-testid="migration-publish-history">
            <strong>Publish History</strong>
            {publishHistory.length > 0 ? (
              <ul>
                {publishHistory.slice(-10).reverse().map((item, index) => {
                  const record = asRecord(item);
                  return (
                    <li key={`publish-history-${index}`}>
                      {asString(record.timestamp) || "n/a"} - {asString(record.status) || "unknown"} - artifact{" "}
                      {asString(record.artifact_version) || asString(record.artifact_version_id) || "n/a"}
                    </li>
                  );
                })}
              </ul>
            ) : (
              <span className="hint muted">No publish actions yet.</span>
            )}
          </div>
          <div className="panel panel-compact stack" data-testid="migration-deploy-history">
            <strong>Deploy History</strong>
            {deployHistory.length > 0 ? (
              <ul>
                {deployHistory.slice(-10).reverse().map((item, index) => {
                  const record = asRecord(item);
                  return (
                    <li key={`deploy-history-${index}`}>
                      {asString(record.timestamp) || "n/a"} - {asString(record.status) || "unknown"} - artifact{" "}
                      {asString(record.artifact_version) || asString(record.artifact_version_id) || "n/a"}
                    </li>
                  );
                })}
              </ul>
            ) : (
              <span className="hint muted">No deploy actions yet.</span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
