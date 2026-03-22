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
  timezone?: string | null;
}

export interface SEOSite {
  id: string;
  business_id: string;
  display_name: string;
  base_url: string;
  normalized_domain: string;
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

export interface CompetitorProfileGenerationRunDetailResponse {
  run: CompetitorProfileGenerationRun;
  drafts: CompetitorProfileDraft[];
  total_drafts: number;
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
  created_by_principal_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface RecommendationNarrativeListResponse {
  items: RecommendationNarrative[];
  total: number;
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

export interface AutomationRun {
  id: string;
  business_id: string;
  site_id: string;
  status: string;
  trigger_source: string;
  started_at: string | null;
  finished_at: string | null;
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
