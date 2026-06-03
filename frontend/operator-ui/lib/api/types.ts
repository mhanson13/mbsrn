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

export interface GoogleAuthStartResponse {
  state: string;
  expires_at: string;
  flow: string;
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
  migration_draft_timeout_seconds?: number | null;
  ai_prompt_text_competitor: string | null;
  ai_prompt_text_recommendations: string | null;
  default_ai_model: string | null;
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
  migration_draft_timeout_seconds?: number | null;
  ai_prompt_text_competitor?: string | null;
  ai_prompt_text_recommendations?: string | null;
  default_ai_model?: string | null;
  competitor_tuning_preview_event_id?: string;
  timezone?: string | null;
}

export interface GitHubPublishConfig {
  id?: number | null;
  owner: string;
  repository?: string;
  default_branch: string;
  base_path: string;
  deploy_workflow_mode: string;
  target_environment_key: string;
  target_environment_source: string;
  github_repository_auto_create_enabled: boolean;
  managed_gke_cluster_name?: string | null;
  managed_gke_cluster_location?: string | null;
  managed_gke_project_id?: string | null;
  managed_gcp_deploy_key_configured?: boolean;
  managed_gcp_deploy_key_updated_at?: string | null;
  namespace_isolation_defaults: GitHubNamespaceIsolationDefaults;
  namespace_isolation_effective_defaults?: GitHubNamespaceIsolationDefaults | null;
  namespace_isolation_cap_reasons?: Record<string, string> | null;
  enabled: boolean;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface GitHubNamespaceResourceQuotaDefaults {
  enabled: boolean;
  requests_cpu: string;
  requests_memory: string;
  limits_cpu: string;
  limits_memory: string;
  pods: number;
  services: number;
  configmaps: number;
  secrets: number;
  persistentvolumeclaims: number;
}

export interface GitHubNamespaceLimitRangeDefaults {
  enabled: boolean;
  default_cpu: string;
  default_memory: string;
  default_request_cpu: string;
  default_request_memory: string;
  min_cpu: string;
  min_memory: string;
  max_cpu: string;
  max_memory: string;
}

export interface GitHubNamespaceNetworkPolicyDefaults {
  enabled: boolean;
  mode: string;
}

export interface GitHubManagedPreviewEndpointDefaults {
  mode: "auto" | "preview_shared_gateway" | "dedicated_static_ip" | string;
  shared_preview_static_ip_name: string | null;
}

export interface MigrationGenerationBudgetConfig {
  migration_context_budget_chars: number;
  migration_recommendation_limit: number;
  migration_competitor_limit: number;
  migration_source_page_summary_limit: number;
  migration_media_asset_limit: number;
  migration_generated_page_limit: number;
  migration_generated_file_limit: number;
  migration_generation_depth: "compact" | "standard" | "expanded" | string;
  migration_variation_level: "conservative" | "balanced" | "differentiated" | string;
  migration_require_page_variety: boolean;
  migration_require_design_variation: boolean;
}

export interface MigrationGenerationSafetyConfig {
  migration_provider_timeout_seconds: number;
  migration_preflight_mode: "compact_fallback" | "block_before_provider" | string;
  migration_max_final_input_chars: number;
  migration_max_difficulty_score: number;
  migration_compact_fallback_enabled: boolean;
  migration_compact_page_limit: number;
  migration_compact_media_asset_limit: number;
  migration_compact_recommendation_limit: number;
}

export interface GitHubNamespaceIsolationDefaults {
  resource_quota: GitHubNamespaceResourceQuotaDefaults;
  limit_range: GitHubNamespaceLimitRangeDefaults;
  network_policy: GitHubNamespaceNetworkPolicyDefaults;
  managed_preview_endpoint: GitHubManagedPreviewEndpointDefaults;
  migration_generation_budget: MigrationGenerationBudgetConfig;
  migration_generation_safety: MigrationGenerationSafetyConfig;
}

export interface GitHubPublishConfigUpdateRequest {
  owner?: string | null;
  repository?: string | null;
  default_branch?: string | null;
  base_path?: string | null;
  deploy_workflow_mode?: string | null;
  target_environment_key?: string | null;
  github_repository_auto_create_enabled?: boolean;
  managed_gke_cluster_name?: string | null;
  managed_gke_cluster_location?: string | null;
  managed_gke_project_id?: string | null;
  managed_gcp_deploy_key_value?: string | null;
  managed_gcp_deploy_key_clear?: boolean;
  namespace_isolation_defaults?: GitHubNamespaceIsolationDefaults | null;
  enabled: boolean;
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
  search_console_property_url?: string | null;
  search_console_enabled?: boolean;
  ga4_onboarding_status?: string;
  ga4_account_id?: string | null;
  ga4_property_id?: string | null;
  ga4_data_stream_id?: string | null;
  ga4_measurement_id?: string | null;
  is_active: boolean;
  is_primary: boolean;
  last_audit_run_id: string | null;
  last_audit_status: string | null;
  last_audit_completed_at: string | null;
}

export interface SEOSiteCreateRequest {
  display_name: string;
  base_url: string;
  search_console_property_url?: string | null;
  search_console_enabled?: boolean | null;
  ga4_account_id?: string | null;
  ga4_property_id?: string | null;
  ga4_data_stream_id?: string | null;
  ga4_measurement_id?: string | null;
}

export interface SEOSiteUpdateRequest {
  display_name?: string;
  base_url?: string;
  industry?: string | null;
  primary_location?: string | null;
  primary_business_zip?: string | null;
  service_areas?: string[] | null;
  search_console_property_url?: string | null;
  search_console_enabled?: boolean | null;
  ga4_account_id?: string | null;
  ga4_property_id?: string | null;
  ga4_data_stream_id?: string | null;
  ga4_measurement_id?: string | null;
  is_active?: boolean;
  is_primary?: boolean;
}

export interface SEOSiteAdminUpdateRequest {
  name?: string;
  url?: string;
  search_console_property_url?: string | null;
  search_console_enabled?: boolean | null;
  ga4_account_id?: string | null;
  ga4_property_id?: string | null;
  ga4_data_stream_id?: string | null;
  ga4_measurement_id?: string | null;
}

export interface SEOSiteListResponse {
  items: SEOSite[];
  total: number;
}

export interface MigrationOperatorRequirements {
  business_objectives: string[];
  requested_pages: string[];
  must_include: string[];
  must_avoid: string[];
  tone_preferences: string[];
  calls_to_action: string[];
  additional_notes: string | null;
}

export interface MigrationEnrichedContentNotes {
  replacement_summary: string | null;
  homepage_value_proposition: string | null;
  about_business: string | null;
  service_highlights: string[];
  trust_signals: string[];
  faq_items: string[];
  contact_overrides: Record<string, string>;
  additional_notes: string | null;
}

export interface MigrationPublishConfig {
  enabled: boolean;
  repo_owner: string | null;
  repo_name: string | null;
  branch: string | null;
  artifact_root: string | null;
}

export interface MigrationDeployConfig {
  enabled: boolean;
  repo_owner: string | null;
  repo_name: string | null;
  workflow_id: string | null;
  ref: string | null;
  inputs: Record<string, string>;
}

export interface MigrationDeployConfigUpdate {
  enabled?: boolean;
  repo_owner?: string | null;
  repo_name?: string | null;
  workflow_id?: string | null;
  ref?: string | null;
  inputs?: Record<string, string>;
}

export interface MigrationAnalyticsConfig {
  enabled: boolean;
  ga_measurement_id: string | null;
  insertion_mode: "publish_only" | "publish_and_deploy";
}

export interface MigrationWorkspaceCreateOrUpdateRequest {
  source_url?: string | null;
  operator_requirements?: MigrationOperatorRequirements | null;
  enriched_content_notes?: MigrationEnrichedContentNotes | null;
  publish_config?: MigrationPublishConfig | null;
  deploy_config?: MigrationDeployConfig | null;
  analytics_config?: MigrationAnalyticsConfig | null;
}

export interface MigrationSourceIngestRequest {
  source_url?: string | null;
}

export interface MigrationRequirementsUpdateRequest {
  operator_requirements: MigrationOperatorRequirements;
}

export type MigrationRequirementSuggestionField =
  | "business_objectives"
  | "requested_pages"
  | "must_include"
  | "must_avoid"
  | "tone"
  | "calls_to_action"
  | "additional_notes";

export interface MigrationRequirementsSuggestionRequest {
  field: MigrationRequirementSuggestionField;
  current_value?: string | string[] | null;
  force_refresh?: boolean;
}

export interface MigrationRequirementsSuggestionResponse {
  field: string;
  suggestion_status: "completed" | "failed" | "not_available" | string;
  suggested_value: string | string[] | null;
  reason_code: string;
  context_sources_used: string[];
  retryable: boolean;
  generated_at: string | null;
}

export interface MigrationEnrichedContentUpdateRequest {
  enriched_content_notes: MigrationEnrichedContentNotes;
}

export interface MigrationPublishConfigUpdateRequest {
  publish_config: MigrationPublishConfig;
}

export interface MigrationDeployConfigUpdateRequest {
  deploy_config: MigrationDeployConfigUpdate;
}

export interface MigrationAnalyticsConfigUpdateRequest {
  analytics_config: MigrationAnalyticsConfig;
}

export interface MigrationDraftGenerateRequest {
  force_new_version?: boolean;
}

export interface MigrationArtifactApproveRequest {
  approval_notes?: string | null;
}

export interface MigrationPublishRequest {
  artifact_version_id: string;
  dry_run?: boolean;
  commit_message?: string | null;
  analytics_measurement_id?: string | null;
}

export interface MigrationDeployRequest {
  artifact_version_id: string;
  dry_run?: boolean;
}

export interface MigrationDeployStatusRefreshRequest {
  artifact_version_id: string;
}

export interface MigrationSourceSnapshot {
  fetched_at?: string | null;
  final_url?: string | null;
  status_code?: number | null;
  content_type?: string | null;
  title?: string | null;
  meta_description?: string | null;
  canonical_url?: string | null;
  headings: string[];
  contact_signals: string[];
  phone_numbers: string[];
  emails: string[];
  addresses: string[];
  internal_links: string[];
  service_blocks: string[];
  pages_scanned_count?: number | null;
  pages_scanned?: string[];
  asset_references: Record<string, string[]>;
  discovered_images?: Array<Record<string, unknown>>;
  cleaned_text_blocks: string[];
  warnings: string[];
}

export interface MigrationMediaAsset {
  asset_id?: string | null;
  artifact_path?: string | null;
  display_filename?: string | null;
  content_type?: string | null;
  fetch_status?: string | null;
  validation_checked_at?: string | null;
  size_bytes?: number | null;
  width?: number | null;
  height?: number | null;
  provenance?: string | null;
  selected_for_draft?: boolean;
  import_status?: string | null;
  category?: string | null;
  alt_text?: string | null;
  description?: string | null;
  usage_note?: string | null;
  page_assignment?: string | null;
  normalized_url?: string | null;
  source_page_url?: string | null;
  preview_url?: string | null;
  created_at?: string | null;
  workspace_status?: "active" | "ignored" | "removed" | string | null;
  metadata_suggestion?: MigrationMediaMetadataSuggestion | null;
  metadata_suggestion_applied?: boolean;
  metadata_suggestion_applied_at?: string | null;
  candidate_quality?: "useful" | "low_value" | "rejected" | string | null;
  quality_reason?: string | null;
}

export interface MigrationMediaAssetListResponse {
  source_discovered: MigrationMediaAsset[];
  operator_uploaded: MigrationMediaAsset[];
  selected_assets: MigrationMediaAsset[];
  source_discovered_count: number;
  pages_scanned_count?: number | null;
  source_imported_count: number;
  operator_uploaded_count: number;
  selected_assets_count: number;
  media_asset_categories: string[];
  selected_assets_trimmed: boolean;
  diagnostics: string[];
}

export interface MigrationMediaMetadataSuggestion {
  suggested_category?: string | null;
  suggested_alt_text?: string | null;
  suggested_description?: string | null;
  suggested_usage_note?: string | null;
  suggested_page_assignment?: string | null;
  confidence?: number | null;
  suggestion_source?: string | null;
  suggestion_status?: "pending" | "completed" | "failed" | "not_available" | null;
  reason_code?: string | null;
  generated_at?: string | null;
}

export interface MigrationMediaAssetUpdateRequest {
  selected_for_draft?: boolean | null;
  apply_suggested_metadata?: boolean | null;
  category?: string | null;
  alt_text?: string | null;
  description?: string | null;
  usage_note?: string | null;
  page_assignment?: string | null;
}

export interface MigrationMediaMetadataSuggestionBatchRequest {
  asset_ids: string[];
  force_refresh?: boolean;
}

export interface MigrationMediaMetadataSuggestionBatchResult {
  asset_id: string;
  suggestion_status: "pending" | "completed" | "failed" | "not_available";
  reason_code?: string | null;
  retryable: boolean;
  metadata_suggestion?: MigrationMediaMetadataSuggestion | null;
}

export interface MigrationMediaMetadataSuggestionBatchResponse {
  batch_status: "completed" | "partial_success" | "failed";
  results: MigrationMediaMetadataSuggestionBatchResult[];
  completed_count: number;
  failed_count: number;
  skipped_count: number;
}

export interface MigrationDiscoveredMediaImportRequest {
  discovered_image_ids?: string[];
  normalized_urls?: string[];
  selected_for_draft?: boolean | null;
  allow_quality_override?: boolean;
}

export interface MigrationDiscoveredMediaImportResult {
  asset_id?: string | null;
  normalized_url?: string | null;
  status: "imported" | "skipped" | "failed" | "disabled";
  reason_code?: string | null;
  media_asset?: MigrationMediaAsset | null;
}

export interface MigrationDiscoveredMediaImportResponse {
  batch_status: "completed" | "partial_success" | "failed";
  results: MigrationDiscoveredMediaImportResult[];
  imported_count: number;
  failed_count: number;
  skipped_count: number;
  disabled_count: number;
}

export interface MigrationMediaAssetLifecycleRequest {
  action: "remove" | "ignore";
}

export interface MigrationMediaAssetLifecycleResponse {
  asset_id?: string | null;
  status: string;
  reason_code?: string | null;
  media_asset?: MigrationMediaAsset | null;
}

export interface MigrationArtifactFile {
  path: string;
  media_type: string;
  size_bytes: number;
  content?: string | null;
}

export interface MigrationArtifactVersion {
  id: string;
  business_id: string;
  site_id: string;
  workspace_id: string;
  version: number;
  status: string;
  strategy_summary: string | null;
  page_map_json: Array<Record<string, unknown>> | null;
  homepage_structure_json: Array<Record<string, unknown>> | null;
  service_page_suggestions_json: Array<Record<string, unknown>> | null;
  cta_contact_structure_json: Record<string, unknown> | null;
  seo_meta_suggestions_json: Record<string, unknown> | null;
  redirect_suggestions_json: Array<Record<string, unknown>> | null;
  analytics_placeholders_json: Array<Record<string, unknown>> | null;
  generated_files_json: Array<Record<string, unknown>> | null;
  artifact_quality_evaluation?: Record<string, unknown> | null;
  artifact_quality_evaluation_json: Record<string, unknown> | null;
  file_count: number;
  total_bytes: number;
  provider_name: string;
  model_name: string;
  prompt_version: string;
  parse_warnings_json: string[] | null;
  error_summary: string | null;
  approval_status: string;
  approved_by_principal_id: string | null;
  approved_at: string | null;
  approval_notes: string | null;
  publish_status: string;
  deploy_status: string;
  last_published_commit_sha: string | null;
  last_published_at: string | null;
  last_publish_error_summary: string | null;
  last_deployed_at: string | null;
  last_deploy_error_summary: string | null;
  created_by_principal_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface MigrationArtifactVersionListResponse {
  items: MigrationArtifactVersion[];
  total: number;
}

export interface MigrationPromptPreview {
  provider_name: string;
  model_name: string;
  prompt_version: string;
  context_json: Record<string, unknown>;
  system_prompt: string;
  user_prompt: string;
}

export interface MigrationWorkspace {
  id: string;
  business_id: string;
  site_id: string;
  source_url: string | null;
  source_site_status: string;
  migration_status: string;
  operator_requirements_json: Record<string, unknown> | null;
  enriched_content_notes_json: Record<string, unknown> | null;
  brand_business_facts_snapshot_json: Record<string, unknown> | null;
  imported_source_snapshot_json: Record<string, unknown> | null;
  latest_generated_artifact_version_id: string | null;
  latest_generated_artifact_version_number: number | null;
  latest_approved_artifact_version_id: string | null;
  latest_approved_artifact_version_number: number | null;
  publish_config_json: Record<string, unknown> | null;
  deploy_config_json: Record<string, unknown> | null;
  analytics_config_json: Record<string, unknown> | null;
  publish_status: string;
  deploy_status: string;
  last_published_artifact_version_id: string | null;
  last_published_artifact_version_number: number | null;
  last_published_commit_sha: string | null;
  last_published_at: string | null;
  last_published_by_principal_id: string | null;
  last_deployed_artifact_version_id: string | null;
  last_deployed_artifact_version_number: number | null;
  last_deployed_at: string | null;
  last_deployed_by_principal_id: string | null;
  publish_history_json: Array<Record<string, unknown>> | null;
  deploy_history_json: Array<Record<string, unknown>> | null;
  created_by_principal_id: string | null;
  updated_by_principal_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface MigrationDraftReadinessReason {
  code: string;
  severity: "warning" | "blocking";
  message: string;
}

export interface MigrationDraftReadinessSignals {
  source_site_ingested: boolean;
  operator_requirements_present: boolean;
  enriched_content_present: boolean;
  audit_available: boolean;
  recommendations_available: boolean;
  competitors_available: boolean;
  draft_provider_configured?: boolean;
}

export interface MigrationDraftReadiness {
  status: "ready" | "ready_with_warnings" | "not_ready";
  score: number;
  hard_blocked: boolean;
  summary: string;
  reasons: MigrationDraftReadinessReason[];
  signals: MigrationDraftReadinessSignals;
}

export interface MigrationDraftGenerationDiagnosticContext {
  failure_category?: string | null;
  failure_reason?: string | null;
  correlation_id?: string | null;
  workspace_id?: string | null;
  artifact_version_id?: string | null;
  provider_name?: string | null;
  model_name?: string | null;
  prompt_version?: string | null;
  timeout_seconds?: number | null;
  timeout_source?: string | null;
}

export interface MigrationDraftGenerationErrorDetail {
  message: string;
  reason_code: string;
  error_code: string;
  retryable: boolean;
  operator_action: string;
  reconnect_target?: string | null;
  diagnostic_context?: MigrationDraftGenerationDiagnosticContext | null;
  failure_category?: string | null;
  failure_reason?: string | null;
  correlation_id?: string | null;
  workspace_id?: string | null;
  artifact_version_id?: string | null;
  provider_name?: string | null;
  model_name?: string | null;
  prompt_version?: string | null;
  timeout_seconds?: number | null;
  timeout_source?: string | null;
}

export interface MigrationDraftReadinessPreflight {
  ready: boolean;
  blocking_reason_codes: string[];
  warning_reason_codes: string[];
  app_auth_ready: boolean;
  google_integration_ready: boolean | null;
  google_reconnect_required: boolean;
  live_google_data_required: boolean;
  draft_context_ready: boolean;
  recommendations_available_count: number;
  competitor_profiles_available_count: number;
  selected_media_assets_count: number;
  source_site_images_discovered_count: number;
  media_required_by_operator: boolean;
  media_requirement_sources: string[];
  usable_media_assets_count: number;
  useful_discovered_images_count: number;
  low_value_discovered_images_count: number;
  rejected_discovered_images_count: number;
  selected_usable_media_assets_count: number;
  media_requirement_satisfied: boolean;
  media_requirement_warning_reason?: string | null;
  operator_action: string;
}

export interface MigrationDraftProviderCompatibility {
  supported: boolean;
  reason_code: string;
  operator_message: string;
  retryable: boolean;
  provider_name: string;
  model_name: string;
  endpoint_path?: string | null;
  execution_mode?: string | null;
  web_search_enabled?: boolean;
  degraded_mode?: boolean;
  response_format_mode?: string | null;
  request_body_mode?: string | null;
  admin_summary?: string | null;
}

export interface MigrationAIExecutionSummary {
  model_requested?: string | null;
  model_resolved?: string | null;
  model_used?: string | null;
  endpoint_path?: string | null;
  request_body_mode?: string | null;
  compatibility_decision?: "allowed" | "blocked_local_preflight" | string | null;
  failure_source?: "local_preflight" | "remote_provider" | "local_validation" | "unknown" | string | null;
  request_contract_status?: "accepted" | "accepted_with_warnings" | "blocked" | "rejected" | string | null;
  provider_execution_status?: "accepted" | "rejected" | "not_called" | "unknown" | string | null;
  artifact_status?: "completed" | "partial" | "failed" | string | null;
  artifact_result?: "succeeded" | "partial" | "failed" | string | null;
  duration_ms?: number | null;
  timeout_seconds?: number | null;
  timeout_source?: "admin" | "default" | string | null;
}

export interface MigrationDraftGenerationState {
  status:
    | "ready"
    | "ready_with_warnings"
    | "blocked_by_workspace"
    | "blocked_by_provider"
    | "generation_failed"
    | "generation_partial"
    | "generation_succeeded";
  summary: string;
  readiness_status?: "ready" | "ready_with_warnings" | "not_ready" | string;
  readiness_hard_blocked?: boolean;
  provider_compatibility_supported?: boolean;
  provider_compatibility_reason_code?: string;
  latest_generation_status?: string | null;
  latest_failure_category?: string | null;
  latest_failure_reason?: string | null;
  retryable?: boolean | null;
}

export interface MigrationDestinationPreviewSummary {
  state: "available" | "unavailable" | string;
  artifact_version_id?: string | null;
  artifact_version_number?: number | null;
  entry_path?: string | null;
}

export interface MigrationDestinationPublishSummary {
  state: "configured" | "unknown" | string;
  repository?: string | null;
  branch?: string | null;
  artifact_root?: string | null;
  expected_location?: string | null;
  expected_publish_url?: string | null;
  url_source?: string | null;
  url_source_detail?: string | null;
  expected_url?: string | null;
  is_published?: boolean;
  last_published_at?: string | null;
}

export interface MigrationDestinationDeploySummary {
  state: "active_live" | "expected_after_deploy" | "unknown" | string;
  expected_publish_url?: string | null;
  resolved_live_url?: string | null;
  expected_url?: string | null;
  active_url?: string | null;
  preview_hostname?: string | null;
  preview_url?: string | null;
  preview_state?: string | null;
  customer_domain_url?: string | null;
  customer_domain_state?: string | null;
  customer_domain_live_url?: string | null;
  url_source?: string | null;
  url_source_detail?: string | null;
  is_deployed?: boolean;
  last_deployed_at?: string | null;
  target_repository?: string | null;
  workflow_id?: string | null;
  resolved_workflow_path?: string | null;
  deploy_workflow_mode?: string | null;
  target_environment_key?: string | null;
  target_environment_source?: string | null;
  site_workflow_file_path?: string | null;
  kubernetes_namespace?: string | null;
  namespace_source?: string | null;
  namespace_model_status?: string | null;
  workflow_namespace_aligned?: boolean | null;
  manifest_namespace_aligned?: boolean | null;
  managed_resource_quota_expected?: boolean | null;
  managed_resource_quota_present?: boolean | null;
  managed_limit_range_expected?: boolean | null;
  managed_limit_range_present?: boolean | null;
  managed_network_policy_expected?: boolean | null;
  managed_network_policy_present?: boolean | null;
  managed_namespace_policies_aligned?: boolean | null;
  ref?: string | null;
}

export interface MigrationDestinationSummary {
  draft_preview?: MigrationDestinationPreviewSummary;
  publish_destination?: MigrationDestinationPublishSummary;
  deploy_destination?: MigrationDestinationDeploySummary;
  current_site_url?: string | null;
}

export interface MigrationContextSummary extends Record<string, unknown> {
  has_source_snapshot?: boolean;
  has_operator_requirements?: boolean;
  has_enriched_content_notes?: boolean;
  has_audit_summary?: boolean;
  has_recommendation_summary?: boolean;
  has_competitor_summary?: boolean;
  ai_execution?: MigrationAIExecutionSummary;
  draft_generation_readiness?: MigrationDraftReadiness;
  draft_provider_compatibility?: MigrationDraftProviderCompatibility;
  draft_generation_state?: MigrationDraftGenerationState;
  destination_summary?: MigrationDestinationSummary;
  draft_input_summary?: Record<string, unknown>;
  media_assets?: MigrationMediaAssetListResponse;
}

export interface MigrationWorkspaceSummary {
  workspace: MigrationWorkspace;
  source_snapshot: MigrationSourceSnapshot | null;
  context_summary: MigrationContextSummary;
  latest_artifact: MigrationArtifactVersion | null;
  publish_readiness: Record<string, unknown>;
  deploy_readiness: Record<string, unknown>;
  publish_history: Array<Record<string, unknown>>;
  deploy_history: Array<Record<string, unknown>>;
  ga4_outcome_snapshot?: RecommendationGA4OutcomeSnapshot | null;
  draft_only_notice: string;
}

export interface MigrationArtifactFilePreview {
  artifact_version_id: string;
  path: string;
  media_type: string;
  content: string;
}

export interface MigrationPublishActionResponse {
  workspace: MigrationWorkspace;
  artifact: MigrationArtifactVersion;
  readiness: Record<string, unknown>;
  result: Record<string, unknown>;
}

export interface MigrationDeployActionResponse {
  workspace: MigrationWorkspace;
  artifact: MigrationArtifactVersion;
  readiness: Record<string, unknown>;
  result: Record<string, unknown>;
}

export interface MigrationRepositoryAdoptActionResponse {
  workspace: MigrationWorkspace;
  readiness: Record<string, unknown>;
  result: Record<string, unknown>;
}

export interface MigrationArtifactDeleteActionResponse {
  workspace: MigrationWorkspace;
  deleted_artifact_version_id: string;
  deleted_artifact_version_number: number;
}

export interface MigrationHistoryListResponse {
  items: Array<Record<string, unknown>>;
  total: number;
}

export interface SiteAnalyticsMetricWindow {
  current: number;
  previous: number;
  delta_absolute: number;
  delta_percent: number | null;
}

export interface SiteAnalyticsMetricsSummary {
  current_period_start: string;
  current_period_end: string;
  previous_period_start: string;
  previous_period_end: string;
  users: SiteAnalyticsMetricWindow;
  sessions: SiteAnalyticsMetricWindow;
  pageviews: SiteAnalyticsMetricWindow;
  organic_search_sessions: SiteAnalyticsMetricWindow;
}

export interface SiteAnalyticsTopPageSummary {
  page_path: string;
  pageviews: number;
  sessions: number;
  pageviews_previous: number;
  sessions_previous: number;
  pageviews_delta_absolute: number;
  sessions_delta_absolute: number;
  pageviews_delta_percent: number | null;
  sessions_delta_percent: number | null;
}

export interface SiteGA4Health {
  ga4_configured: boolean;
  ga4_property_id_present: boolean;
  ga4_property_verified: boolean | null;
  ga4_reachable: boolean | null;
  ga4_data_available: boolean | null;
  ga4_last_checked_at: string | null;
  ga4_health_status:
    | "configured"
    | "not_configured"
    | "reachable"
    | "unavailable"
    | "missing_oauth_scope"
    | "permission_denied"
    | "invalid_property"
    | "no_data"
    | "unknown";
  ga4_health_reason: string | null;
  ga4_health_message: string | null;
  ga4_health_source: "site_property" | "unavailable";
  ga4_scope_granted: boolean | null;
  ga4_required_scope: string;
  ga4_auth_mode: "user_oauth" | "service_account" | "adc" | "mock" | "unavailable" | "unknown";
}

export interface SiteGA4TopLandingPageInsight {
  path?: string | null;
  title?: string | null;
  sessions?: number | null;
  active_users?: number | null;
  views?: number | null;
  engagement_rate?: number | null;
  average_engagement_time_seconds?: number | null;
  trend_label?: "improving" | "declining" | "steady" | "unknown" | null;
  operator_hint?: string | null;
}

export interface SiteGA4TrafficTrendInsight {
  current_sessions?: number | null;
  previous_sessions?: number | null;
  sessions_delta_percent?: number | null;
  current_active_users?: number | null;
  previous_active_users?: number | null;
  active_users_delta_percent?: number | null;
  trend_label?: "improving" | "declining" | "steady" | "unknown" | null;
  operator_hint?: string | null;
}

export interface SiteGA4EngagementTrendInsight {
  current_engagement_rate?: number | null;
  previous_engagement_rate?: number | null;
  engagement_rate_delta_percent?: number | null;
  current_average_engagement_time_seconds?: number | null;
  previous_average_engagement_time_seconds?: number | null;
  trend_label?: "improving" | "declining" | "steady" | "unknown" | null;
  operator_hint?: string | null;
}

export interface SiteGA4Insights {
  status:
    | "available"
    | "not_configured"
    | "missing_oauth_scope"
    | "permission_denied"
    | "invalid_property"
    | "no_data"
    | "unavailable"
    | "unknown";
  source?: "site_property" | "unavailable" | null;
  date_range_label?: string | null;
  checked_at?: string | null;
  top_landing_pages?: SiteGA4TopLandingPageInsight[] | null;
  traffic_trend?: SiteGA4TrafficTrendInsight | null;
  engagement_trend?: SiteGA4EngagementTrendInsight | null;
  message?: string | null;
}

export interface SiteGA4AcquisitionChannelInsight {
  channel_group: string;
  sessions?: number | null;
  users?: number | null;
  engagement_rate?: number | null;
}

export interface SiteGA4AcquisitionSourceInsight {
  source: string;
  medium?: string | null;
  sessions?: number | null;
  users?: number | null;
}

export interface SiteGA4OrganicSearchSummary {
  sessions?: number | null;
  share_percent?: number | null;
  trend_direction?: "improving" | "declining" | "steady" | "unknown" | null;
}

export interface SiteGA4ReferralSummary {
  sessions?: number | null;
  top_referrers?: string[] | null;
}

export interface SiteGA4DirectSummary {
  sessions?: number | null;
  share_percent?: number | null;
}

export interface SiteGA4PaidSummary {
  detected?: boolean | null;
  sessions?: number | null;
}

export interface SiteGA4AcquisitionInsights {
  status:
    | "available"
    | "not_configured"
    | "missing_oauth_scope"
    | "permission_denied"
    | "invalid_property"
    | "no_data"
    | "unavailable"
    | "unknown";
  source?: "site_scoped_ga4" | "unavailable" | null;
  lookback_days?: number | null;
  top_channels?: SiteGA4AcquisitionChannelInsight[] | null;
  top_sources?: SiteGA4AcquisitionSourceInsight[] | null;
  organic_search_summary?: SiteGA4OrganicSearchSummary | null;
  referral_summary?: SiteGA4ReferralSummary | null;
  direct_summary?: SiteGA4DirectSummary | null;
  paid_summary?: SiteGA4PaidSummary | null;
  operator_hints?: string[] | null;
  message?: string | null;
}

export interface SiteAnalyticsSummaryResponse {
  business_id: string;
  site_id: string;
  available: boolean;
  status: "ok" | "not_configured" | "unavailable";
  ga4_status: "not_configured" | "configured" | "connected" | "error";
  ga4_error_reason:
    | "not_configured"
    | "missing_oauth_scope"
    | "permission_denied"
    | "access_denied"
    | "property_not_found"
    | "invalid_property_format"
    | "no_data"
    | "unknown_error"
    | null;
  ga4_last_successful_fetch_at?: string | null;
  ga4_last_data_timestamp?: string | null;
  ga4_data_freshness_status?: "fresh" | "stale" | "unknown";
  ga4_health?: SiteGA4Health | null;
  ga4_insights?: SiteGA4Insights | null;
  ga4_acquisition_insights?: SiteGA4AcquisitionInsights | null;
  message: string | null;
  data_source: string | null;
  site_metrics_summary: SiteAnalyticsMetricsSummary | null;
  top_pages_summary: SiteAnalyticsTopPageSummary[];
}

export interface GA4AccessibleAccountSummary {
  account_id: string;
  display_name: string;
  property_count: number;
}

export interface GA4AccessibleAccountsResponse {
  business_id: string;
  site_id: string;
  available: boolean;
  status: "ok" | "not_configured" | "unavailable";
  message: string | null;
  data_source: string | null;
  accounts: GA4AccessibleAccountSummary[];
}

export interface GA4SiteOnboardingStatusResponse {
  business_id: string;
  site_id: string;
  ga4_onboarding_status:
    | "not_connected"
    | "account_available"
    | "property_configured"
    | "stream_configured"
    | "incomplete"
    | "unavailable";
  ga4_account_id: string | null;
  ga4_property_id: string | null;
  ga4_data_stream_id: string | null;
  ga4_measurement_id: string | null;
  account_discovery_available: boolean;
  discovered_account_count: number;
  auto_provisioning_eligible: boolean;
  message: string | null;
}

export interface SearchConsoleMetricWindow {
  current: number;
  previous: number;
  delta_absolute: number;
  delta_percent: number | null;
}

export interface SearchConsoleSiteMetricsSummary {
  current_period_start: string;
  current_period_end: string;
  previous_period_start: string;
  previous_period_end: string;
  clicks: SearchConsoleMetricWindow;
  impressions: SearchConsoleMetricWindow;
  ctr_current: number;
  ctr_previous: number;
  ctr_delta_absolute: number;
  average_position_current: number;
  average_position_previous: number;
  average_position_delta_absolute: number;
}

export interface SearchConsoleTopPageSummary {
  page_path: string;
  clicks: number;
  clicks_previous: number;
  clicks_delta_absolute: number;
  clicks_delta_percent: number | null;
  impressions: number;
  impressions_previous: number;
  impressions_delta_absolute: number;
  impressions_delta_percent: number | null;
  ctr: number;
  ctr_previous: number;
  ctr_delta_absolute: number;
  average_position: number;
  average_position_previous: number;
  average_position_delta_absolute: number;
}

export interface SearchConsoleTopQuerySummary {
  query: string;
  clicks: number;
  impressions: number;
  ctr: number;
  average_position: number;
}

export interface SearchConsoleSiteSummaryResponse {
  business_id: string;
  site_id: string;
  available: boolean;
  status: "ok" | "not_configured" | "unavailable";
  diagnostic_status?:
    | "missing_config"
    | "invalid_credentials"
    | "adc_unavailable"
    | "access_denied"
    | "property_not_accessible"
    | "api_unavailable"
    | null;
  sc_last_successful_fetch_at?: string | null;
  sc_last_data_timestamp?: string | null;
  sc_data_freshness_status?: "fresh" | "stale" | "unknown";
  message: string | null;
  data_source: string | null;
  site_metrics_summary: SearchConsoleSiteMetricsSummary | null;
  top_pages_summary: SearchConsoleTopPageSummary[];
  top_queries_summary: SearchConsoleTopQuerySummary[];
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

export type CompetitorDomainFeedbackStatus = "useful" | "not_useful" | "excluded" | "manually_seeded";

export interface CompetitorDomainFeedback {
  id: string;
  business_id: string;
  site_id: string;
  domain: string;
  feedback_status: CompetitorDomainFeedbackStatus;
  display_name: string | null;
  operator_note: string | null;
  created_by_principal_id: string | null;
  updated_by_principal_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface CompetitorDomainFeedbackListResponse {
  items: CompetitorDomainFeedback[];
  total: number;
}

export type ReviewedCompetitorState =
  | "accepted"
  | "useful"
  | "not_useful"
  | "excluded"
  | "needs_review"
  | "manual_seed"
  | "generated_suggestion"
  | "legacy_synthetic";

export type ReviewedCompetitorProvenance = "ai_suggested" | "manual_seed" | "existing" | "legacy";

export interface ReviewedCompetitorRow {
  domain: string;
  display_name: string | null;
  review_state: ReviewedCompetitorState;
  provenance: ReviewedCompetitorProvenance;
  confidence_score: number | null;
  reason_selected: string | null;
  is_synthetic: boolean;
  is_excluded: boolean;
  is_accepted_or_useful: boolean;
  updated_at: string | null;
  operator_note: string | null;
  source_set_id: string | null;
  source_generation_run_id: string | null;
}

export interface ReviewedCompetitorListSummary {
  total: number;
  accepted_useful: number;
  needs_review: number;
  excluded: number;
  manual_seeds: number;
  last_suggestion_status: "queued" | "running" | "completed" | "failed" | null;
}

export interface ReviewedCompetitorLatestSuggestion {
  run_id: string | null;
  run_status: "queued" | "running" | "completed" | "failed" | null;
  local_seeds_considered: number;
  suggestions_returned: number;
  added_to_review_list: number;
  already_known: number;
  rejected_by_quality_gate: number;
  excluded_by_operator_feedback: number;
  failure_reason: string | null;
}

export interface ReviewedCompetitorAdvancedRunReference {
  id: string;
  status: string;
  competitor_set_id: string;
  competitor_set_name: string;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

export interface ReviewedCompetitorDiagnostics {
  competitor_set_count: number;
  active_set_count: number;
  latest_snapshot_run: ReviewedCompetitorAdvancedRunReference | null;
  latest_comparison_run: ReviewedCompetitorAdvancedRunReference | null;
}

export interface ReviewedCompetitorListResponse {
  business_id: string;
  site_id: string;
  summary: ReviewedCompetitorListSummary;
  latest_suggestion: ReviewedCompetitorLatestSuggestion;
  quality_summary: CompetitorGenerationQualitySummary | null;
  diagnostics: ReviewedCompetitorDiagnostics;
  items: ReviewedCompetitorRow[];
}

export interface CompetitorDomainFeedbackUpsertRequest {
  domain: string;
  feedback_status: CompetitorDomainFeedbackStatus;
  display_name?: string | null;
  operator_note?: string | null;
}

export interface CompetitorDomainManualSeedCreateRequest {
  domain: string;
  display_name?: string | null;
  operator_note?: string | null;
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

export type AIResponseContractStatus = "accepted" | "accepted_with_warnings" | "salvaged" | "rejected";

export interface OperatorResponseContractSummary {
  status: AIResponseContractStatus;
  summary: string;
  retryable: boolean;
}

export type CompetitorGenerationQualityStatus = "ready" | "partial" | "blocked";

export type CompetitorGenerationQualityReason =
  | "valid"
  | "duplicate_domain"
  | "self_domain"
  | "malformed_domain"
  | "low_relevance"
  | "missing_required_fields"
  | "insufficient_candidates"
  | "provider_unparseable"
  | "provider_returned_empty"
  | "provider_schema_invalid"
  | "prompt_override_contract_invalid";

export interface CompetitorGenerationQualitySummary {
  status: CompetitorGenerationQualityStatus;
  operator_message: string;
  total_candidates_returned: number;
  accepted_candidates: number;
  rejected_candidates: number;
  final_active_domains_count: number;
  top_reason: CompetitorGenerationQualityReason | null;
  reason_counts: Partial<Record<CompetitorGenerationQualityReason, number>>;
}

export interface AIDiagnosticsSummary {
  failure_category?: string | null;
  failure_reason?: string | null;
  failure_source?: string | null;
  retryable?: boolean | null;
  hint?: string | null;
  budget_outcome?: string | null;
  retry_suppressed?: boolean | null;
  trimming_pass_count?: number | null;
  difficulty_bucket?: string | null;
  input_size_bucket?: string | null;
  degraded_state?: string | null;
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
  response_contract_summary?: OperatorResponseContractSummary | null;
  quality_summary?: CompetitorGenerationQualitySummary | null;
  ai_diagnostics_summary?: AIDiagnosticsSummary | null;
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
  response_contract_summary?: OperatorResponseContractSummary | null;
  ai_diagnostics_summary?: AIDiagnosticsSummary | null;
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
export type RecommendationTargetContentTypeKey =
  | "heading_h1"
  | "heading_h2"
  | "intro_paragraph"
  | "service_description"
  | "internal_links"
  | "meta_title"
  | "meta_description"
  | "faq_block"
  | "image_alt_text"
  | "canonical_tag"
  | "page_title_block"
  | "call_to_action"
  | "location_copy";
export type RecommendationTargetContentSourceType =
  | "deterministic_rule"
  | "audit_signal"
  | "evidence_mapping";

export interface RecommendationTargetContentType {
  type_key: RecommendationTargetContentTypeKey;
  label: string;
  source_type: RecommendationTargetContentSourceType;
  targeting_strength?: "high" | "medium" | "low" | null;
}

export type RecommendationActionPlanTargetType = "page" | "content";

export interface RecommendationActionPlanStep {
  step_number: number;
  title: string;
  instruction: string;
  target_type: RecommendationActionPlanTargetType;
  target_identifier: string;
  field?: string | null;
  before_example?: string | null;
  after_example?: string | null;
  confidence: number;
}

export interface RecommendationActionPlan {
  action_steps: RecommendationActionPlanStep[];
}

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

export interface RecommendationMeasurementMetricWindow {
  current: number;
  previous: number;
  delta_absolute: number;
  delta_percent: number | null;
}

export interface RecommendationMeasurementWindowSummary {
  start_date: string;
  end_date: string;
  users: number;
  sessions: number;
  pageviews: number;
}

export interface RecommendationMeasurementDeltaSummary {
  users_delta_absolute: number;
  users_delta_percent: number | null;
  sessions_delta_absolute: number;
  sessions_delta_percent: number | null;
  pageviews_delta_absolute: number;
  pageviews_delta_percent: number | null;
}

export interface RecommendationMeasurementContext {
  measurement_status: "available" | "no_match" | "unavailable" | "not_configured";
  matched_page_path?: string | null;
  comparison_scope?: "page" | "site" | null;
  sessions?: RecommendationMeasurementMetricWindow | null;
  pageviews?: RecommendationMeasurementMetricWindow | null;
  before_window_summary?: RecommendationMeasurementWindowSummary | null;
  after_window_summary?: RecommendationMeasurementWindowSummary | null;
  delta_summary?: RecommendationMeasurementDeltaSummary | null;
}

export interface RecommendationSearchConsoleWindowSummary {
  start_date: string;
  end_date: string;
  clicks: number;
  impressions: number;
  ctr: number;
  average_position: number;
}

export interface RecommendationSearchConsoleDeltaSummary {
  clicks_delta_absolute: number;
  clicks_delta_percent: number | null;
  impressions_delta_absolute: number;
  impressions_delta_percent: number | null;
  ctr_delta_absolute: number;
  average_position_delta_absolute: number;
}

export interface RecommendationSearchConsoleTopQuery {
  query: string;
  clicks: number;
  impressions: number;
  ctr: number;
  average_position: number;
}

export interface RecommendationSearchConsoleContext {
  search_console_status: "available" | "no_match" | "unavailable" | "not_configured";
  matched_page_path?: string | null;
  comparison_scope?: "page" | "site" | null;
  current_window_summary?: RecommendationSearchConsoleWindowSummary | null;
  previous_window_summary?: RecommendationSearchConsoleWindowSummary | null;
  delta_summary?: RecommendationSearchConsoleDeltaSummary | null;
  top_queries_summary?: RecommendationSearchConsoleTopQuery[];
}

export interface RecommendationEffectivenessContext {
  effectiveness_status: "available" | "partial" | "insufficient";
  traffic_direction: "up" | "down" | "flat" | "unknown";
  search_visibility_direction: "up" | "down" | "flat" | "unknown";
  effectiveness_trend?: "improving" | "flat" | "declining" | "insufficient_data";
  effectiveness_confidence?: "high" | "moderate" | "low";
  summary?: string | null;
}

export interface RecommendationGA4OutcomeWindow {
  start_date: string;
  end_date: string;
  sessions: number;
  users: number;
  engagement_rate?: number | null;
  organic_sessions?: number | null;
}

export interface RecommendationGA4OutcomeDelta {
  sessions_delta: number;
  sessions_delta_percent: number | null;
  engagement_rate_delta_points?: number | null;
  organic_sessions_delta_percent?: number | null;
}

export interface RecommendationGA4OutcomeSnapshot {
  status:
    | "unavailable"
    | "not_configured"
    | "missing_scope"
    | "permission_denied"
    | "insufficient_data"
    | "pending_after_window"
    | "available";
  source?: string;
  anchor_type?:
    | "recommendation_completed"
    | "recommendation_accepted"
    | "migration_published"
    | "migration_deployed"
    | "unknown";
  anchor_timestamp?: string | null;
  before_window?: RecommendationGA4OutcomeWindow | null;
  after_window?: RecommendationGA4OutcomeWindow | null;
  delta?: RecommendationGA4OutcomeDelta | null;
  outcome_direction?: "improved" | "declined" | "mixed" | "no_clear_change" | "insufficient_data" | null;
  operator_hint?: string | null;
}

export interface ActionLineageDraft {
  id: string;
  source_action_id: string;
  action_type: string;
  title: string;
  description: string;
  draft_state: string;
  activation_state: "pending" | "activated";
  activated_action_id?: string | null;
  automation_ready?: boolean;
  automation_template_key?: string | null;
  created_at?: string | null;
}

export interface ActionLineageActivatedAction {
  id: string;
  source_draft_id: string;
  source_action_id: string;
  action_type: string;
  title: string;
  description: string;
  state: string;
  automation_ready?: boolean;
  automation_template_key?: string | null;
  automation_binding_state?: "unbound" | "bound";
  bound_automation_id?: string | null;
  automation_bound_at?: string | null;
  automation_execution_state?: "not_requested" | "requested" | "running" | "succeeded" | "failed";
  automation_execution_requested_at?: string | null;
  last_automation_run_id?: string | null;
  automation_last_executed_at?: string | null;
  automation_run_status?: string | null;
  automation_run_started_at?: string | null;
  automation_run_completed_at?: string | null;
  automation_run_error_summary?: string | null;
  automation_run_terminal_outcome?: "completed" | "completed_with_skips" | "failed" | "partial" | null;
  automation_run_summary_title?: string | null;
  automation_run_summary_text?: string | null;
  automation_run_steps_completed_count?: number | null;
  automation_run_steps_skipped_count?: number | null;
  automation_run_steps_failed_count?: number | null;
  automation_run_pages_analyzed_count?: number | null;
  automation_run_issues_found_count?: number | null;
  automation_run_recommendations_generated_count?: number | null;
  created_at?: string | null;
}

export interface ActionLineageCounts {
  chained_draft_count: number;
  activated_action_count: number;
  automation_ready_count: number;
}

export interface ActionLineageResponse {
  source_action_id: string;
  chained_drafts: ActionLineageDraft[];
  activated_actions: ActionLineageActivatedAction[];
  counts: ActionLineageCounts;
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
  priority_rationale?: string | null;
  evidence_strength?: "strong" | "moderate" | "limited";
  competitor_influence_level?: "none" | "supporting" | "meaningful";
  why_now?: string | null;
  next_action?: string | null;
  competitor_insight?: string | null;
  execution_type?:
    | "content_update"
    | "page_update"
    | "metadata_update"
    | "internal_linking"
    | "local_seo"
    | "technical_fix"
    | "mixed";
  execution_scope?: string | null;
  execution_inputs?: string[];
  execution_readiness?: "ready" | "needs_review" | "needs_more_input";
  blocking_reason?: string | null;
  recommendation_target_context?: RecommendationTargetContext | null;
  recommendation_target_page_hints?: string[];
  recommendation_target_content_types?: RecommendationTargetContentType[];
  recommendation_target_content_summary?: string | null;
  action_plan?: RecommendationActionPlan | null;
  competitor_evidence_links?: RecommendationCompetitorEvidenceLink[];
  competitor_linkage_summary?: string | null;
  recommendation_action_delta?: RecommendationActionDelta | null;
  recommendation_priority?: RecommendationPriority | null;
  recommendation_measurement_context?: RecommendationMeasurementContext | null;
  recommendation_search_console_context?: RecommendationSearchConsoleContext | null;
  recommendation_effectiveness_context?: RecommendationEffectivenessContext | null;
  ga4_priority_context_available?: boolean;
  ga4_priority_signal?: "top_landing_page" | "traffic_decline" | "engagement_decline" | null;
  ga4_priority_hint?: string | null;
  ga4_supporting_page_path?: string | null;
  ga4_supporting_metric_summary?: string | null;
  ga4_context_source?: string | null;
  ga4_outcome_snapshot?: RecommendationGA4OutcomeSnapshot | null;
  source_basis?: Array<
    | "audit_findings"
    | "comparison_findings"
    | "accepted_competitors"
    | "ga4_insights"
    | "search_console_insights"
    | "gbp_insights"
  >;
  competitor_context_summary?: string | null;
  competitor_exclusion_summary?: string | null;
  gbp_context_summary?: string | null;
  duplicate_count?: number | null;
  duplicate_group_key?: string | null;
  latest_duplicate_created_at?: string | null;
  grouped_from_runs_count?: number | null;
  is_duplicate_representative?: boolean | null;
  duplicate_representative_id?: string | null;
  action_lineage?: ActionLineageResponse | null;
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
  group_duplicates?: boolean;
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

export interface ActionOutputReviewStep {
  stepName: string;
  status: string;
  reasonSummary?: string | null;
  pagesAnalyzedCount?: number | null;
  issuesFoundCount?: number | null;
  recommendationsGeneratedCount?: number | null;
}

export interface ActionOutputReview {
  outputId?: string | null;
  summary?: string | null;
  details?: string | null;
  sourceLabel?: string | null;
  stepDetails?: ActionOutputReviewStep[] | null;
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
  actionLineage?: ActionLineageResponse | null;
  outputReview?: ActionOutputReview | null;
  decision?: ActionDecision | null;
}

export interface BindActionAutomationResponse {
  action_execution_item_id: string;
  automation_binding_state: "unbound" | "bound";
  bound_automation_id?: string | null;
  automation_bound_at?: string | null;
  automation_ready?: boolean;
  automation_template_key?: string | null;
}

export interface RunActionAutomationResponse {
  action_execution_item_id: string;
  automation_binding_state: "unbound" | "bound";
  bound_automation_id?: string | null;
  automation_bound_at?: string | null;
  automation_execution_state: "not_requested" | "requested" | "running" | "succeeded" | "failed";
  automation_execution_requested_at?: string | null;
  last_automation_run_id?: string | null;
  automation_last_executed_at?: string | null;
  automation_ready?: boolean;
  automation_template_key?: string | null;
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
  outcome_summary?: AutomationRunOutcomeSummary | null;
  steps_json?: AutomationRunStep[] | null;
  created_at?: string;
  updated_at?: string;
}

export interface AutomationRunOutcomeSummary {
  summary_title: string;
  summary_text: string;
  pages_analyzed_count?: number | null;
  issues_found_count?: number | null;
  recommendations_generated_count?: number | null;
  steps_completed_count: number;
  steps_skipped_count: number;
  steps_failed_count: number;
  terminal_outcome: "completed" | "completed_with_skips" | "failed" | "partial";
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
  reason_summary?: string | null;
  pages_analyzed_count?: number | null;
  issues_found_count?: number | null;
  recommendations_generated_count?: number | null;
}

export interface AutomationRunListResponse {
  items: AutomationRun[];
  total: number;
}

export interface AutomationConfig {
  id: string;
  business_id: string;
  site_id: string;
  config_source: "default" | "site";
  is_enabled: boolean;
  cadence_type: "manual" | "interval_minutes";
  cadence_minutes: number | null;
  trigger_audit: boolean;
  trigger_audit_summary: boolean;
  trigger_competitor_snapshot: boolean;
  trigger_comparison: boolean;
  trigger_competitor_summary: boolean;
  trigger_recommendations: boolean;
  trigger_recommendation_narrative: boolean;
  last_run_at: string | null;
  next_run_at: string | null;
  last_status: string | null;
  last_error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface AutomationStatusResponse {
  business_id: string;
  site_id: string;
  config: AutomationConfig;
  latest_run: AutomationRun | null;
}

export interface AutomationConfigPatchRequest {
  trigger_audit?: boolean;
  trigger_audit_summary?: boolean;
  trigger_competitor_snapshot?: boolean;
  trigger_comparison?: boolean;
  trigger_competitor_summary?: boolean;
  trigger_recommendations?: boolean;
  trigger_recommendation_narrative?: boolean;
}

export type GoogleBusinessProfileTokenStatus =
  | "usable"
  | "refresh_required"
  | "reconnect_required"
  | "insufficient_scope";

export type GoogleBusinessProfileConnectionState =
  | "not_connected"
  | "oauth_connected"
  | "usable"
  | "missing_scope"
  | "permission_denied"
  | "no_accounts"
  | "no_locations"
  | "location_not_mapped"
  | "unavailable"
  | "unknown";

export type GoogleBusinessProfileProviderErrorClass =
  | "none"
  | "token_refresh_failed"
  | "missing_required_scope"
  | "provider_unauthorized"
  | "provider_permission_denied"
  | "provider_api_disabled_or_unavailable"
  | "provider_rate_limited"
  | "provider_quota_or_access_not_granted"
  | "provider_not_found"
  | "provider_unavailable"
  | "provider_unknown";

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
  ga4_scope_granted?: boolean | null;
  required_ga4_scope?: string | null;
  connected_google_identity?: string | null;
  gbp_connection_state?: GoogleBusinessProfileConnectionState;
  gbp_required_scope?: string | null;
  gbp_required_scope_granted?: boolean | null;
  gbp_accounts_count?: number | null;
  gbp_locations_count?: number | null;
  gbp_selected_location_present?: boolean | null;
  gbp_status_reason?: string | null;
  gbp_next_action?: string | null;
  gbp_provider_error_class?: GoogleBusinessProfileProviderErrorClass;
  gbp_provider_http_status?: number | null;
  gbp_diagnostic_hint?: string | null;
}

export interface GoogleBusinessProfileConnectStartResponse {
  authorization_url: string;
  state_expires_at: string;
  provider: string;
  required_scope: string;
  required_scopes?: string[] | null;
  ga4_scope_requested?: boolean | null;
  required_ga4_scope?: string | null;
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
