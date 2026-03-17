export type PrincipalRole = "admin" | "operator";

export interface AuthPrincipal {
  business_id: string;
  principal_id: string;
  display_name: string;
  role: PrincipalRole;
  is_active: boolean;
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

export interface SEOSite {
  id: string;
  business_id: string;
  display_name: string;
  base_url: string;
  normalized_domain: string;
  is_active: boolean;
  is_primary: boolean;
}

export interface SEOSiteListResponse {
  items: SEOSite[];
  total: number;
}

export interface SEOAuditRun {
  id: string;
  business_id: string;
  site_id: string;
  status: string;
  started_at: string | null;
  completed_at: string | null;
  pages_crawled: number;
  pages_skipped: number;
  crawl_errors_count: number;
}

export interface SEOAuditRunListResponse {
  items: SEOAuditRun[];
  total: number;
}

export interface CompetitorSet {
  id: string;
  business_id: string;
  site_id: string;
  name: string;
  description: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface CompetitorSetListResponse {
  items: CompetitorSet[];
  total: number;
}

export interface Recommendation {
  id: string;
  business_id: string;
  site_id: string;
  recommendation_run_id: string;
  status: string;
  category: string;
  severity: string;
  priority_score: number;
  priority_band: string;
  effort_bucket: string;
  title: string;
  rationale: string;
  created_at: string;
  updated_at: string;
}

export interface RecommendationListResponse {
  items: Recommendation[];
  total: number;
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
