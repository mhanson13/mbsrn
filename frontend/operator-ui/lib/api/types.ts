export type PrincipalRole = "admin" | "operator";

export interface AuthPrincipal {
  business_id: string;
  principal_id: string;
  display_name: string;
  role: PrincipalRole;
  is_active: boolean;
}

export interface Principal {
  business_id: string;
  id: string;
  display_name: string;
  created_by_principal_id: string | null;
  updated_by_principal_id: string | null;
  role: PrincipalRole;
  is_active: boolean;
  last_authenticated_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface PrincipalListResponse {
  items: Principal[];
  total: number;
}

export interface PrincipalIdentity {
  id: string;
  provider: string;
  provider_subject: string;
  business_id: string;
  principal_id: string;
  email: string | null;
  email_verified: boolean;
  is_active: boolean;
  last_authenticated_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface PrincipalIdentityListResponse {
  items: PrincipalIdentity[];
  total: number;
}

export interface PrincipalCreateRequest {
  principal_id: string;
  display_name?: string;
  role: PrincipalRole;
}

export interface PrincipalIdentityCreateRequest {
  provider: string;
  provider_subject: string;
  principal_id: string;
  email?: string;
  email_verified?: boolean;
  is_active?: boolean;
}

export interface AuthExchangeResponse {
  access_token: string;
  refresh_token: string;
  token_type: "bearer";
  expires_at: string;
  refresh_expires_at: string;
  auth_source: string;
  principal: AuthPrincipal;
}

export interface BusinessSettings {
  id: string;
  name: string;
  notification_phone: string | null;
  notification_email: string | null;
  sms_enabled: boolean;
  email_enabled: boolean;
  customer_auto_ack_enabled: boolean;
  contractor_alerts_enabled: boolean;
  seo_audit_crawl_max_pages: number;
  competitor_candidate_min_relevance_score: number;
  competitor_candidate_big_box_penalty: number;
  competitor_candidate_directory_penalty: number;
  competitor_candidate_local_alignment_bonus: number;
  competitor_primary_timeout_seconds: number | null;
  competitor_degraded_timeout_seconds: number | null;
  ai_prompt_text_competitor: string | null;
  ai_prompt_text_recommendations: string | null;
  timezone: string;
  created_at: string;
  updated_at: string;
}

export interface BusinessSettingsUpdateRequest {
  notification_phone?: string | null;
  notification_email?: string | null;
  sms_enabled?: boolean;
  email_enabled?: boolean;
  customer_auto_ack_enabled?: boolean;
  contractor_alerts_enabled?: boolean;
  seo_audit_crawl_max_pages?: number;
  competitor_candidate_min_relevance_score?: number;
  competitor_candidate_big_box_penalty?: number;
  competitor_candidate_directory_penalty?: number;
  competitor_candidate_local_alignment_bonus?: number;
  competitor_primary_timeout_seconds?: number | null;
  competitor_degraded_timeout_seconds?: number | null;
  ai_prompt_text_competitor?: string | null;
  ai_prompt_text_recommendations?: string | null;
  competitor_tuning_preview_event_id?: string;
  timezone?: string | null;
}

export interface GCPLogsQueryRequest {
  filter: string;
  page_size?: number;
  page_token?: string;
  start_time?: string;
  end_time?: string;
}

export interface GCPLogEntry {
  timestamp: string | null;
  severity: string | null;
  log_name: string | null;
  resource_type: string | null;
  labels: Record<string, string> | null;
  resource_labels: Record<string, string> | null;
  insert_id: string | null;
  text_payload_summary: string | null;
  json_payload_summary: string | null;
  proto_payload_summary: string | null;
}

export interface GCPLogsQueryResponse {
  entries: GCPLogEntry[];
  next_page_token: string | null;
  page_size: number;
  order_by: string;
  resource_scope: string[];
  effective_filter: string;
  default_time_range_applied: boolean;
}

export interface SEOSite {
  id: string;
  business_id: string;
  display_name: string;
  base_url: string;
  normalized_domain: string;
  industry?: string | null;
  primary_location?: string | null;
  primary_business_zip?: string | null;
  service_areas_json?: string[] | null;
  is_active: boolean;
  is_primary: boolean;
  last_audit_run_id: string | null;
  last_audit_status: string | null;
  last_audit_completed_at: string | null;
}

export interface SEOSiteCreateRequest {
  display_name: string;
  base_url: string;
}

export interface SEOSiteUpdateRequest {
  display_name?: string;
  base_url?: string;
  industry?: string | null;
  primary_location?: string | null;
  primary_business_zip?: string | null;
  service_areas?: string[] | null;
  is_active?: boolean;
  is_primary?: boolean;
}

export interface SEOSiteAdminUpdateRequest {
  name?: string;
  url?: string;
}

export interface SEOSiteListResponse {
  items: SEOSite[];
  total: number;
}

export interface SEOAuditRunCreateRequest {
  max_pages?: number;
  max_depth?: number;
}

export interface SEOAuditRun {
  id: string;
  business_id: string;
  site_id: string;
  status: string;
  max_pages: number;
  max_depth: number;
  pages_discovered: number;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  completed_at: string | null;
  crawl_duration_ms: number | null;
  error_summary: string | null;
  created_by_principal_id: string | null;
  pages_crawled: number;
  pages_skipped: number;
  duplicate_urls_skipped: number;
  errors_encountered: number;
}

export interface SEOAuditRunListResponse {
  items: SEOAuditRun[];
  total: number;
}

export interface SEOAuditRunSummary {
  run_id: string;
  business_id: string;
  site_id: string;
  status: string;
  total_pages: number;
  total_findings: number;
  critical_findings: number;
  warning_findings: number;
  info_findings: number;
  crawl_duration: number | null;
  health_score: number;
  by_category: Record<string, number>;
  by_severity: Record<string, number>;
}

export interface SEOAuditFinding {
  id: string;
  business_id: string;
  site_id: string;
  audit_run_id: string;
  page_id: string | null;
  finding_type: string;
  category: string;
  severity: string;
  title: string;
  details: string | null;
  rule_key: string;
  suggested_fix: string | null;
  created_at: string;
}

export interface SEOAuditFindingListResponse {
  items: SEOAuditFinding[];
  total: number;
  by_category: Record<string, number>;
  by_severity: Record<string, number>;
}

export interface CompetitorSet {
  id: string;
  business_id: string;
  site_id: string;
  name: string;
  city: string | null;
  state: string | null;
  is_active: boolean;
  created_by_principal_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface CompetitorSetListResponse {
  items: CompetitorSet[];
  total: number;
}

export interface CompetitorDomain {
  id: string;
  business_id: string;
  site_id: string;
  competitor_set_id: string;
  domain: string;
  base_url: string;
  display_name: string | null;
  source: string;
  verification_status?: "verified" | "unverified" | null;
  is_active: boolean;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface CompetitorDomainListResponse {
  items: CompetitorDomain[];
  total: number;
}

export interface CompetitorProfileGenerationRun {
  id: string;
  business_id: string;
  site_id: string;
  parent_run_id?: string | null;
  status: "queued" | "running" | "completed" | "failed";
  requested_candidate_count: number;
  generated_draft_count: number;
  provider_name: string;
  model_name: string;
  prompt_version: string;
  failure_category:
    | "timeout"
    | "provider_auth"
    | "provider_config"
    | "malformed_output"
    | "schema_validation"
    | "internal_error"
    | "provider_request"
    | "unknown"
    | null;
  error_summary: string | null;
  completed_at: string | null;
  created_by_principal_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface CompetitorProfileDraft {
  id: string;
  business_id: string;
  site_id: string;
  generation_run_id: string;
  suggested_name: string;
  suggested_domain: string;
  competitor_type: "direct" | "indirect" | "local" | "marketplace" | "informational" | "unknown";
  summary: string | null;
  why_competitor: string | null;
  evidence: string | null;
  confidence_score: number;
  source: string;
  confidence_level?: "high" | "medium" | "low" | null;
  source_type?: "search" | "places" | "fallback" | "synthetic" | null;
  provenance_classification?: "places_ai_enriched" | "ai_only" | "synthetic_fallback" | null;
  provenance_explanation?: string | null;
  operator_evidence_summary?: string | null;
  forced_inclusion?: boolean;
  forced_reason?: string | null;
  review_status: "pending" | "edited" | "accepted" | "rejected";
  edited_fields_json: Record<string, unknown> | null;
  review_notes: string | null;
  reviewed_by_principal_id: string | null;
  reviewed_at: string | null;
  accepted_competitor_set_id: string | null;
  accepted_competitor_domain_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface CompetitorProfileGenerationRunListResponse {
  items: CompetitorProfileGenerationRun[];
  total: number;
}

export type CompetitorCandidateIneligibilityReason =
  | "parked_domain"
  | "no_live_site"
  | "weak_business_identity"
  | "out_of_market"
  | "excluded_domain_pattern"
  | "insufficient_overlap_evidence"
  | "missing_domain"
  | "malformed_url"
  | "missing_business_name"
  | "unsupported_type"
  | "invalid_confidence_score"
  | "low_usefulness_unknown";

export type CompetitorCandidateTuningExclusionReason =
  | "below_minimum_relevance_score"
  | "directory_or_aggregator_penalty"
  | "big_box_mismatch_penalty"
  | "insufficient_local_alignment";

export interface RejectedCompetitorCandidateDebug {
  domain: string;
  reasons: CompetitorCandidateIneligibilityReason[];
  summary: string | null;
}

export interface TuningRejectedCompetitorCandidateDebug {
  domain: string;
  reasons: CompetitorCandidateTuningExclusionReason[];
  final_score: number | null;
  summary: string | null;
}

export interface CompetitorCandidatePipelineSummary {
  proposed_candidate_count: number;
  rejected_by_eligibility_count: number;
  eligible_candidate_count: number;
  rejected_by_tuning_count: number;
  survived_tuning_count: number;
  removed_by_existing_domain_match_count: number;
  removed_by_deduplication_count: number;
  removed_by_final_limit_count: number;
  final_candidate_count: number;
  relaxed_filtering_applied?: boolean;
}

export interface CompetitorProviderAttemptDebug {
  attempt_number: number;
  execution_mode?: string | null;
  provider_call_type?: string | null;
  degraded_mode: boolean;
  reduced_context_mode: boolean;
  requested_candidate_count: number;
  outcome: string;
  failure_kind: string | null;
  malformed_output_reason?: string | null;
  request_duration_ms: number | null;
  timeout_seconds: number | null;
  web_search_enabled: boolean | null;
  prompt_size_risk: string | null;
  prompt_total_chars: number | null;
  context_json_chars: number | null;
  user_prompt_chars: number | null;
  endpoint_path: string | null;
  search_escalation_triggered?: boolean;
  escalation_reason?: string | null;
}

export type CompetitorRunOutcomeStatusLevel = "normal" | "recovered" | "degraded" | "failed";

export interface CompetitorRunOutcomeSummary {
  status_level: CompetitorRunOutcomeStatusLevel;
  message: string;
  used_synthetic_fallback: boolean;
  used_timeout_recovery: boolean;
  had_schema_repair_or_discard: boolean;
  used_google_places_seeds: boolean;
}

export interface CompetitorProfileGenerationRunDetailResponse {
  run: CompetitorProfileGenerationRun;
  drafts: CompetitorProfileDraft[];
  total_drafts: number;
  rejected_candidate_count?: number;
  rejected_candidates?: RejectedCompetitorCandidateDebug[];
  tuning_rejected_candidate_count?: number;
  tuning_rejected_candidates?: TuningRejectedCompetitorCandidateDebug[];
  tuning_rejection_reason_counts?: Partial<Record<CompetitorCandidateTuningExclusionReason, number>>;
  candidate_pipeline_summary?: CompetitorCandidatePipelineSummary | null;
  outcome_summary?: CompetitorRunOutcomeSummary | null;
  provider_attempt_count?: number;
  provider_degraded_retry_used?: boolean;
  provider_attempts?: CompetitorProviderAttemptDebug[];
}

export interface CompetitorProfileGenerationSummaryResponse {
  business_id: string;
  site_id: string;
  lookback_days: number;
  window_start: string;
  window_end: string;
  queued_count: number;
  running_count: number;
  completed_count: number;
  failed_count: number;
  retry_child_runs: number;
  retried_parent_runs: number;
  failed_runs_retried: number;
  failure_category_counts: Record<string, number>;
  total_runs: number;
  total_raw_candidate_count: number;
  total_included_candidate_count: number;
  total_excluded_candidate_count: number;
  exclusion_counts_by_reason: Record<
    | "duplicate"
    | "low_relevance"
    | "directory_or_aggregator"
    | "big_box_mismatch"
    | "existing_domain_match"
    | "invalid_candidate",
    number
  >;
  preview_accuracy_rate?: number | null;
  avg_error_margin?: number | null;
  last_n_preview_accuracy?: {
    window_size: number;
    sample_size: number;
    direction_correct_count: number;
    accuracy_rate: number | null;
    avg_error_margin: number | null;
  } | null;
  latest_run_created_at: string | null;
  latest_run_completed_at: string | null;
  latest_completed_run_completed_at: string | null;
  latest_failed_run_completed_at: string | null;
}

export interface CompetitorProfileGenerationRunCreateRequest {
  candidate_count?: number;
}

export interface CompetitorProfileDraftEditRequest {
  suggested_name?: string;
  suggested_domain?: string;
  competitor_type?: "direct" | "indirect" | "local" | "marketplace" | "informational" | "unknown";
  summary?: string | null;
  why_competitor?: string | null;
  evidence?: string | null;
  confidence_score?: number;
}

export interface CompetitorProfileDraftAcceptRequest extends CompetitorProfileDraftEditRequest {
  competitor_set_id?: string;
  confirm_synthetic_scaffold?: boolean;
  accept_as_unverified?: boolean;
  review_notes?: string | null;
}

export interface CompetitorProfileDraftRejectRequest {
  reason?: string | null;
}

export interface CompetitorSnapshotRun {
  id: string;
  business_id: string;
  site_id: string;
  competitor_set_id: string;
  client_audit_run_id: string | null;
  status: string;
  max_domains: number;
  max_pages_per_domain: number;
  max_depth: number;
  same_domain_only: boolean;
  domains_targeted: number;
  domains_completed: number;
  pages_attempted: number;
  pages_captured: number;
  pages_skipped: number;
  errors_encountered: number;
  started_at: string | null;
  completed_at: string | null;
  duration_ms: number | null;
  error_summary: string | null;
  created_by_principal_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface CompetitorSnapshotRunListResponse {
  items: CompetitorSnapshotRun[];
  total: number;
}

export interface CompetitorSnapshotPage {
  id: string;
  business_id: string;
  site_id: string;
  competitor_set_id: string;
  snapshot_run_id: string;
  competitor_domain_id: string;
  url: string;
  status_code: number | null;
  title: string | null;
  meta_description: string | null;
  canonical_url: string | null;
  h1_json: string[] | null;
  h2_json: string[] | null;
  word_count: number | null;
  internal_link_count: number | null;
  fetched_at: string;
  error_summary: string | null;
  created_at: string;
  updated_at: string;
}

export interface CompetitorSnapshotPageListResponse {
  items: CompetitorSnapshotPage[];
  total: number;
}

export interface CompetitorComparisonRun {
  id: string;
  business_id: string;
  site_id: string;
  competitor_set_id: string;
  snapshot_run_id: string;
  baseline_audit_run_id: string | null;
  status: string;
  total_findings: number;
  critical_findings: number;
  warning_findings: number;
  info_findings: number;
  client_pages_analyzed: number;
  competitor_pages_analyzed: number;
  finding_type_counts_json: Record<string, number>;
  category_counts_json: Record<string, number>;
  severity_counts_json: Record<string, number>;
  started_at: string | null;
  completed_at: string | null;
  duration_ms: number | null;
  error_summary: string | null;
  created_by_principal_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface CompetitorComparisonRunListResponse {
  items: CompetitorComparisonRun[];
  total: number;
}

export interface CompetitorComparisonFinding {
  id: string;
  business_id: string;
  site_id: string;
  competitor_set_id: string;
  comparison_run_id: string;
  finding_type: string;
  category: string;
  severity: string;
  title: string;
  details: string | null;
  rule_key: string;
  client_value: string | null;
  competitor_value: string | null;
  gap_direction: string | null;
  evidence_json: Record<string, unknown> | null;
  created_at: string;
}

export interface CompetitorComparisonFindingListResponse {
  items: CompetitorComparisonFinding[];
  total: number;
  by_category: Record<string, number>;
  by_severity: Record<string, number>;
}

export interface CompetitorComparisonMetricRollup {
  key: string;
  title: string;
  category: string;
  unit: string;
  higher_is_better: boolean;
  client_value: number;
  competitor_value: number;
  delta: number;
  severity: string;
  gap_direction: string;
}

export interface CompetitorComparisonRunRollups {
  client_pages_analyzed: number;
  competitor_pages_analyzed: number;
  findings_by_type: Record<string, number>;
  findings_by_category: Record<string, number>;
  findings_by_severity: Record<string, number>;
  metric_rollups: CompetitorComparisonMetricRollup[];
}

export interface CompetitorComparisonReport {
  run: CompetitorComparisonRun;
  rollups: CompetitorComparisonRunRollups;
  findings: CompetitorComparisonFindingListResponse;
}

export interface RecommendationRun {
  id: string;
  business_id: string;
  site_id: string;
  audit_run_id: string | null;
  comparison_run_id: string | null;
  status: string;
  total_recommendations: number;
  critical_recommendations: number;
  warning_recommendations: number;
  info_recommendations: number;
  category_counts_json: Record<string, number>;
  effort_bucket_counts_json: Record<string, number>;
  started_at: string | null;
  completed_at: string | null;
  duration_ms: number | null;
  error_summary: string | null;
  created_by_principal_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface RecommendationRunListResponse {
  items: RecommendationRun[];
  total: number;
}

export interface RecommendationRunCreateRequest {
  audit_run_id?: string;
  comparison_run_id?: string;
}

export interface RecommendationRunReport {
  recommendation_run: RecommendationRun;
  rollups: {
    by_category: Record<string, number>;
    by_severity: Record<string, number>;
    by_effort_bucket: Record<string, number>;
  };
  recommendations: RecommendationListResponse;
}

export interface RecommendationNarrative {
  id: string;
  business_id: string;
  site_id: string;
  recommendation_run_id: string;
  version: number;
  status: "completed" | "failed";
  narrative_text: string | null;
  top_themes_json: string[];
  sections_json: Record<string, unknown> | null;
  provider_name: string;
  model_name: string;
  prompt_version: string;
  error_message: string | null;
  competitor_influence?: RecommendationNarrativeCompetitorInfluence | null;
  action_summary?: RecommendationNarrativeActionSummary | null;
  signal_summary?: RecommendationNarrativeSignalSummary | null;
  created_by_principal_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface RecommendationNarrativeCompetitorInfluence {
  used: boolean;
  summary: string;
  top_opportunities: string[];
  competitor_names: string[];
}

export interface RecommendationNarrativeActionSummary {
  primary_action: string;
  why_it_matters: string;
  evidence: string[];
  first_step: string;
}

export interface RecommendationNarrativeSignalSummary {
  support_level: "low" | "medium" | "high";
  evidence_sources: Array<"site" | "competitors" | "references" | "themes">;
  competitor_signal_used: boolean;
  site_signal_used: boolean;
  reference_signal_used: boolean;
}

export type RecommendationEEATCategory =
  | "experience"
  | "expertise"
  | "authoritativeness"
  | "trustworthiness";
export type RecommendationPriorityReason =
  | "competitor_gap"
  | "trust_gap"
  | "authority_gap"
  | "experience_gap"
  | "expertise_gap"
  | "high_clarity_action"
  | "pending_refresh_context"
  | "general";
export type RecommendationTheme =
  | "trust_and_legitimacy"
  | "experience_and_proof"
  | "authority_and_visibility"
  | "expertise_and_process"
  | "general_site_improvement";
export type RecommendationTargetContext =
  | "homepage"
  | "service_pages"
  | "contact_about"
  | "location_pages"
  | "sitewide"
  | "general";

export interface RecommendationApplyOutcome {
  applied: boolean;
  applied_at: string | null;
  applied_recommendation_id?: string | null;
  applied_recommendation_title?: string | null;
  applied_change_summary?: string | null;
  applied_preview_summary?: string | null;
  next_refresh_expectation?: string | null;
  recommendation_label: string | null;
  expected_change: string | null;
  reflected_on_next_run: string | null;
  source: "recommendation" | "manual" | null;
}

export interface WorkspaceTrustSummary {
  latest_competitor_status?: CompetitorRunOutcomeStatusLevel | null;
  used_google_places_seeds?: boolean | null;
  used_synthetic_fallback?: boolean | null;
  latest_recommendation_apply_title?: string | null;
  latest_recommendation_apply_change_summary?: string | null;
  next_refresh_expectation?: string | null;
  freshness_note?: string | null;
}

export type RecommendationAnalysisFreshnessStatus = "fresh" | "pending_refresh" | "unknown";
export type RecommendationProgressStatus =
  | "suggested"
  | "applied_pending_refresh"
  | "reflected_in_latest_analysis";
export type RecommendationLifecycleState =
  | "active"
  | "applied_waiting_validation"
  | "reflected_still_relevant"
  | "likely_resolved";

export interface RecommendationAnalysisFreshness {
  status: RecommendationAnalysisFreshnessStatus;
  analysis_generated_at: string | null;
  last_apply_at: string | null;
  message: string;
}

export type CompetitorContextHealthStatus = "strong" | "mixed" | "weak";
export type CompetitorContextHealthCheckKey =
  | "location_context"
  | "industry_context"
  | "service_focus"
  | "target_customer_context";
export type CompetitorContextHealthCheckStatus = "strong" | "weak";

export interface CompetitorContextHealthCheck {
  key: CompetitorContextHealthCheckKey;
  label: string;
  status: CompetitorContextHealthCheckStatus;
  detail: string;
}

export interface CompetitorContextHealth {
  status: CompetitorContextHealthStatus;
  checks: CompetitorContextHealthCheck[];
  message: string;
}

export interface AIPromptPreview {
  available: boolean;
  prompt_type: "competitor" | "recommendation";
  system_prompt: string;
  user_prompt: string;
  model: string | null;
  // Effective prompt version extracted from the resolved prompt body when available.
  prompt_version: string | null;
  // Operator-facing effective prompt identity label.
  prompt_label?: string | null;
  source?: "admin_config" | "env" | "default" | null;
  truncated: boolean;
  // Debug-safe bounded metrics (counts/lengths only).
  prompt_metrics?: Record<string, number> | null;
}

export type CompetitorCandidateExclusionReason =
  | "duplicate"
  | "low_relevance"
  | "directory_or_aggregator"
  | "big_box_mismatch"
  | "existing_domain_match"
  | "invalid_candidate";

export type RecommendationTuningSuggestionSetting =
  | "competitor_candidate_min_relevance_score"
  | "competitor_candidate_big_box_penalty"
  | "competitor_candidate_directory_penalty"
  | "competitor_candidate_local_alignment_bonus";

export type RecommendationTuningSuggestionConfidence = "low" | "medium" | "high";

export interface RecommendationTuningSuggestion {
  setting: RecommendationTuningSuggestionSetting;
  current_value: number;
  recommended_value: number;
  reason: string;
  linked_recommendation_ids: string[];
  confidence: RecommendationTuningSuggestionConfidence;
}

export interface RecommendationTuningValuesPatch {
  competitor_candidate_min_relevance_score?: number;
  competitor_candidate_big_box_penalty?: number;
  competitor_candidate_directory_penalty?: number;
  competitor_candidate_local_alignment_bonus?: number;
}

export interface RecommendationTuningValues {
  competitor_candidate_min_relevance_score: number;
  competitor_candidate_big_box_penalty: number;
  competitor_candidate_directory_penalty: number;
  competitor_candidate_local_alignment_bonus: number;
}

export interface RecommendationTuningImpactPreviewRequest {
  current_values?: RecommendationTuningValuesPatch;
  proposed_values: RecommendationTuningValuesPatch;
  recommendation_run_id?: string;
  narrative_id?: string;
}

export interface RecommendationTuningImpactEstimate {
  insufficient_data: boolean;
  estimated_included_candidate_delta: number;
  estimated_excluded_candidate_delta: number;
  estimated_exclusion_reason_deltas: Record<CompetitorCandidateExclusionReason, number>;
  summary: string;
  risk_flags: string[];
}

export interface RecommendationTuningImpactPreview {
  business_id: string;
  site_id: string;
  preview_event_id: string | null;
  source_recommendation_run_id: string | null;
  source_narrative_id: string | null;
  current_values: RecommendationTuningValues;
  proposed_values: RecommendationTuningValues;
  telemetry_window: {
    lookback_days: number;
    total_runs: number;
    total_raw_candidate_count: number;
    total_included_candidate_count: number;
    total_excluded_candidate_count: number;
    exclusion_counts_by_reason: Record<CompetitorCandidateExclusionReason, number>;
  };
  estimated_impact: RecommendationTuningImpactEstimate;
  caveat: string;
}

export interface RecommendationNarrativeListResponse {
  items: RecommendationNarrative[];
  total: number;
}

export type RecommendationWorkspaceSummaryState =
  | "no_runs"
  | "no_completed_runs"
  | "completed_no_narrative"
  | "completed_with_narrative";

export type WorkspaceSectionFreshnessState = "fresh" | "pending_refresh" | "running" | "stale";
export type WorkspaceSectionFreshnessStateCode =
  | "fresh"
  | "pending_refresh"
  | "running"
  | "stale"
  | "possibly_outdated";

export interface WorkspaceSectionFreshness {
  state: WorkspaceSectionFreshnessState;
  message: string;
  state_code?: WorkspaceSectionFreshnessStateCode | null;
  state_label?: string | null;
  state_reason?: string | null;
  evaluated_at?: string | null;
  refresh_expected?: boolean | null;
}

export interface RecommendationWorkspaceSummaryResponse {
  business_id: string;
  site_id: string;
  state: RecommendationWorkspaceSummaryState;
  latest_run: RecommendationRun | null;
  latest_completed_run: RecommendationRun | null;
  recommendations: RecommendationListResponse;
  grouped_recommendations?: RecommendationThemeGroup[];
  latest_narrative: RecommendationNarrative | null;
  tuning_suggestions: RecommendationTuningSuggestion[];
  apply_outcome?: RecommendationApplyOutcome | null;
  workspace_trust_summary?: WorkspaceTrustSummary | null;
  competitor_section_freshness?: WorkspaceSectionFreshness | null;
  recommendation_section_freshness?: WorkspaceSectionFreshness | null;
  analysis_freshness?: RecommendationAnalysisFreshness | null;
  ordering_explanation?: RecommendationOrderingExplanation | null;
  start_here?: RecommendationStartHere | null;
  eeat_gap_summary?: RecommendationEEATGapSummary | null;
  competitor_context_health?: CompetitorContextHealth | null;
  competitor_prompt_preview?: AIPromptPreview | null;
  recommendation_prompt_preview?: AIPromptPreview | null;
  site_location_context?: string | null;
  site_primary_location?: string | null;
  site_primary_business_zip?: string | null;
  site_location_context_strength?: "strong" | "weak" | "unknown";
  site_location_context_source?: "explicit_location" | "service_area" | "zip_capture" | "fallback" | null;
}

export interface RecommendationOrderingExplanation {
  message: string;
  context_reasons: RecommendationPriorityReason[];
}

export interface RecommendationThemeGroup {
  theme: RecommendationTheme;
  label: string;
  count: number;
  recommendation_ids: string[];
}

export interface RecommendationStartHere {
  theme: RecommendationTheme;
  theme_label: string;
  recommendation_id: string;
  title: string;
  reason: string;
  context_flags: ("pending_refresh_context" | "competitor_backed")[];
}

export interface RecommendationEEATGapSummary {
  top_gap_categories: RecommendationEEATCategory[];
  supporting_signals: string[];
  message: string;
}

export interface RecommendationCompetitorEvidenceLink {
  competitor_draft_id: string;
  competitor_name: string;
  competitor_domain?: string | null;
  confidence_level?: "high" | "medium" | "low" | null;
  source_type?: "search" | "places" | "fallback" | "synthetic" | null;
  verification_status?: "verified" | "unverified" | null;
  trust_tier?: "trusted_verified" | "informational_unverified" | "informational_candidate" | null;
  evidence_trust_tier?: "trusted_verified" | "informational_unverified" | "informational_candidate" | null;
  evidence_summary?: string | null;
}

export interface RecommendationActionDelta {
  observed_competitor_pattern: string;
  observed_site_gap: string;
  recommended_operator_action: string;
  evidence_strength: "high" | "medium" | "low";
}

export interface RecommendationPriority {
  priority_level: "high" | "medium" | "low";
  priority_reason: string;
  effort_hint?: "quick_win" | "moderate" | "larger_change" | null;
}

export interface Recommendation {
  id: string;
  business_id: string;
  site_id: string;
  recommendation_run_id: string;
  audit_run_id: string | null;
  comparison_run_id: string | null;
  status: string;
  category: string;
  severity: string;
  priority_score: number;
  priority_band: string;
  effort_bucket: string;
  title: string;
  rationale: string;
  eeat_categories: RecommendationEEATCategory[];
  primary_eeat_category: RecommendationEEATCategory | null;
  priority_reasons?: RecommendationPriorityReason[];
  primary_priority_reason?: RecommendationPriorityReason | null;
  theme?: RecommendationTheme | null;
  theme_label?: string | null;
  recommendation_progress_status?: RecommendationProgressStatus;
  recommendation_progress_summary?: string | null;
  recommendation_lifecycle_state?: RecommendationLifecycleState;
  recommendation_lifecycle_summary?: string | null;
  recommendation_evidence_summary?: string | null;
  recommendation_observed_gap_summary?: string | null;
  recommendation_evidence_trace?: string[];
  recommendation_action_clarity?: string | null;
  recommendation_expected_outcome?: string | null;
  recommendation_target_context?: RecommendationTargetContext | null;
  recommendation_target_page_hints?: string[];
  competitor_evidence_links?: RecommendationCompetitorEvidenceLink[];
  competitor_linkage_summary?: string | null;
  recommendation_action_delta?: RecommendationActionDelta | null;
  recommendation_priority?: RecommendationPriority | null;
  decision_reason: string | null;
  created_at: string;
  updated_at: string;
}

export type RecommendationActionStatus = "accepted" | "dismissed";

export interface RecommendationWorkflowUpdatePayload {
  status?: RecommendationActionStatus;
  note?: string | null;
}

export interface RecommendationListFilters {
  status?: "open" | "in_progress" | "accepted" | "dismissed" | "snoozed" | "resolved";
  priority_band?: "low" | "medium" | "high" | "critical";
  category?: "SEO" | "CONTENT" | "STRUCTURE" | "TECHNICAL";
  source_type?: "audit" | "comparison" | "mixed";
  recommendation_run_id?: string;
  sort_by?: "priority_score" | "created_at" | "updated_at" | "due_at";
  sort_order?: "asc" | "desc";
  page?: number;
  page_size?: number;
}

export interface RecommendationFilteredSummary {
  total: number;
  open: number;
  accepted: number;
  dismissed: number;
  high_priority: number;
}

export interface RecommendationListResponse {
  items: Recommendation[];
  total: number;
  filtered_summary?: RecommendationFilteredSummary | null;
  by_status?: Record<string, number>;
  by_category?: Record<string, number>;
  by_severity?: Record<string, number>;
  by_effort_bucket?: Record<string, number>;
  by_priority_band?: Record<string, number>;
}

export type ActionControlType =
  | "review_recommendation"
  | "run_automation"
  | "view_automation_status"
  | "review_output"
  | "mark_completed"
  | "blocked";

export type ActionControlEmphasis = "primary" | "secondary" | "muted";

export type ActionDecision = "accepted" | "rejected" | "deferred";

export interface ActionOutputReview {
  outputId?: string | null;
  summary?: string | null;
  details?: string | null;
  sourceLabel?: string | null;
}

export interface ActionControl {
  type: ActionControlType;
  label: string;
  enabled: boolean;
  reason?: string;
  emphasis?: ActionControlEmphasis;
}

export type ActionExecutionStateCode =
  | "informational_only"
  | "recommendation_only_review"
  | "automation_output_ready"
  | "waiting_on_automation"
  | "blocked_unavailable"
  | "completed_acted";

export interface ActionExecutionItem {
  id: string;
  title: string;
  actionStateCode: ActionExecutionStateCode;
  priorityBand?: string | null;
  trustTier?: "trusted_verified" | "informational_unverified" | "informational_candidate" | null;
  automationAvailable?: boolean;
  automationInFlight?: boolean;
  linkedOutputId?: string | null;
  linkedNarrativeId?: string | null;
  blockedReason?: string | null;
  triggerSource?: string | null;
  outputReview?: ActionOutputReview | null;
  decision?: ActionDecision | null;
}

export interface AutomationRun {
  id: string;
  business_id: string;
  site_id: string;
  automation_config_id?: string;
  status: string;
  trigger_source: string;
  started_at: string | null;
  finished_at: string | null;
  error_message: string | null;
  steps_json?: AutomationRunStep[] | null;
  created_at?: string;
  updated_at?: string;
}

export type AutomationStepName =
  | "audit_run"
  | "audit_summary"
  | "competitor_snapshot_run"
  | "comparison_run"
  | "competitor_summary"
  | "recommendation_run"
  | "recommendation_narrative";

export interface AutomationRunStep {
  step_name: AutomationStepName | string;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  linked_output_id: string | null;
  error_message: string | null;
}

export interface AutomationRunListResponse {
  items: AutomationRun[];
  total: number;
}

export type GoogleBusinessProfileTokenStatus =
  | "usable"
  | "refresh_required"
  | "reconnect_required"
  | "insufficient_scope";

export interface GoogleBusinessProfileConnectionStatusResponse {
  provider: string;
  connected: boolean;
  business_id: string;
  granted_scopes: string[];
  refresh_token_present: boolean;
  expires_at: string | null;
  connected_at: string | null;
  last_refreshed_at: string | null;
  reconnect_required: boolean;
  required_scopes_satisfied: boolean;
  token_status: GoogleBusinessProfileTokenStatus;
}

export interface GoogleBusinessProfileConnectStartResponse {
  authorization_url: string;
  state_expires_at: string;
  provider: string;
  required_scope: string;
}

export interface GoogleBusinessProfileDisconnectResponse {
  status: string;
  connection: GoogleBusinessProfileConnectionStatusResponse;
}

export type GoogleBusinessProfileStateSummary = "verified" | "unverified" | "pending" | "unknown";
export type GoogleBusinessProfileNextAction =
  | "none"
  | "start_verification"
  | "complete_pending"
  | "resolve_access"
  | "reconnect_google";
export type GoogleBusinessProfileGuidanceVerificationState =
  | "verified"
  | "unverified"
  | "pending"
  | "unknown"
  | "in_progress"
  | "completed"
  | "failed";
export type GoogleBusinessProfileGuidanceRecommendedAction =
  | "verify_business"
  | "choose_method"
  | "enter_code"
  | "wait_for_code"
  | "retry_verification"
  | "reconnect_google"
  | "contact_support"
  | "no_action_needed"
  | "check_business_access"
  | "review_business_details"
  | "unknown";
export type GoogleBusinessProfileGuidancePriority = "high" | "medium" | "low" | "info";
export type GoogleBusinessProfileGuidanceCtaType =
  | "start_verification"
  | "choose_method"
  | "submit_code"
  | "reconnect"
  | "retry"
  | "refresh_status"
  | "none";

export interface GoogleBusinessProfileVerificationGuidance {
  verification_state: GoogleBusinessProfileGuidanceVerificationState;
  recommended_action: GoogleBusinessProfileGuidanceRecommendedAction;
  priority: GoogleBusinessProfileGuidancePriority;
  title: string;
  summary: string;
  instructions: string[];
  tips: string[];
  warnings: string[];
  troubleshooting: string[];
  estimated_time: string | null;
  cta_label: string | null;
  cta_type: GoogleBusinessProfileGuidanceCtaType;
  recommended_method: GoogleBusinessProfileVerificationMethod | null;
  recommendation_reason: string | null;
}

export interface GoogleBusinessProfileVerificationRecord {
  name: string | null;
  method: string | null;
  state: string | null;
  create_time: string | null;
  complete_time: string | null;
}

export interface GoogleBusinessProfileLocationVerification {
  has_voice_of_merchant: boolean | null;
  state_summary: GoogleBusinessProfileStateSummary;
  verification_methods: string[];
  verifications: GoogleBusinessProfileVerificationRecord[];
  recommended_next_action: GoogleBusinessProfileNextAction;
  guidance: GoogleBusinessProfileVerificationGuidance;
}

export interface GoogleBusinessProfileLocation {
  location_id: string;
  title: string;
  address: string | null;
  verification: GoogleBusinessProfileLocationVerification;
}

export interface GoogleBusinessProfileAccount {
  account_id: string;
  account_name: string;
  locations: GoogleBusinessProfileLocation[];
}

export interface GoogleBusinessProfileAccountsResponse {
  accounts: GoogleBusinessProfileAccount[];
}

export interface GoogleBusinessProfileFlatLocation {
  account_id: string;
  account_name: string;
  location_id: string;
  title: string;
  address: string | null;
  verification: GoogleBusinessProfileLocationVerification;
}

export interface GoogleBusinessProfileLocationsResponse {
  locations: GoogleBusinessProfileFlatLocation[];
}

export type GoogleBusinessProfileVerificationWorkflowState =
  | "unverified"
  | "pending"
  | "in_progress"
  | "completed"
  | "failed"
  | "unknown";

export type GoogleBusinessProfileVerificationActionRequired =
  | "none"
  | "choose_method"
  | "enter_code"
  | "wait"
  | "retry"
  | "reconnect_google"
  | "resolve_access";

export type GoogleBusinessProfileVerificationMethod =
  | "postcard"
  | "phone"
  | "sms"
  | "email"
  | "live_call"
  | "video"
  | "vetted_partner"
  | "address"
  | "other"
  | "unknown";

export type GoogleBusinessProfileVerificationErrorCode =
  | "reconnect_required"
  | "insufficient_scope"
  | "permission_denied"
  | "verification_not_supported"
  | "method_not_available"
  | "invalid_verification_state"
  | "invalid_code"
  | "provider_conflict"
  | "provider_error"
  | "not_found";

export interface GoogleBusinessProfileVerificationMethodOption {
  option_id: string;
  method: GoogleBusinessProfileVerificationMethod;
  provider_method: string;
  label: string;
  description: string | null;
  destination: string | null;
  requires_code: boolean;
  eligible: boolean;
}

export interface GoogleBusinessProfileVerificationStatusCurrent {
  verification_id: string;
  provider_state: string | null;
  method: GoogleBusinessProfileVerificationMethod;
  provider_method: string;
  create_time: string | null;
  complete_time: string | null;
  expires_at: string | null;
}

export interface GoogleBusinessProfileVerificationWorkflowContract {
  location_id: string;
  verification_state: GoogleBusinessProfileVerificationWorkflowState;
  action_required: GoogleBusinessProfileVerificationActionRequired;
  message: string;
  reconnect_required: boolean;
  guidance: GoogleBusinessProfileVerificationGuidance;
}

export interface GoogleBusinessProfileVerificationStatusResponse
  extends GoogleBusinessProfileVerificationWorkflowContract {
  current_verification: GoogleBusinessProfileVerificationStatusCurrent | null;
  available_methods: GoogleBusinessProfileVerificationMethodOption[];
}

export interface GoogleBusinessProfileVerificationOptionsResponse {
  location_id: string;
  current_verification_state: GoogleBusinessProfileVerificationWorkflowState;
  methods: GoogleBusinessProfileVerificationMethodOption[];
  guidance: GoogleBusinessProfileVerificationGuidance;
}

export interface GoogleBusinessProfileStartVerificationRequest {
  option_id?: string | null;
  selected_method?: GoogleBusinessProfileVerificationMethod | null;
  provider_method?: string | null;
  destination?: string | null;
  language_code?: string | null;
  mailer_contact?: string | null;
  vetted_partner_token?: string | null;
}

export interface GoogleBusinessProfileVerificationActionResponse
  extends GoogleBusinessProfileVerificationWorkflowContract {
  verification_id: string | null;
  expires_at: string | null;
  status: GoogleBusinessProfileVerificationStatusResponse;
}

export interface GoogleBusinessProfileCompleteVerificationRequest {
  verification_id?: string | null;
  code: string;
}

export interface GoogleBusinessProfileVerificationErrorDetail {
  code: GoogleBusinessProfileVerificationErrorCode;
  message: string;
  reconnect_required: boolean;
  guidance?: GoogleBusinessProfileVerificationGuidance | null;
}
