import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import SitesPage from "./page";
import type {
  AuthPrincipal,
  GoogleBusinessProfileConnectionStatusResponse,
  SEOSite,
  SiteAnalyticsSummaryResponse,
} from "../../lib/api/types";

type OperatorContextMockValue = {
  loading: boolean;
  error: string | null;
  token: string;
  businessId: string;
  sites: SEOSite[];
  selectedSiteId: string | null;
  setSelectedSiteId: jest.Mock;
  refreshSites: jest.Mock<Promise<SEOSite[]>, []>;
};

const mockUseOperatorContext = jest.fn<OperatorContextMockValue, []>();
const mockUseAuth = jest.fn<{ principal: AuthPrincipal | null }, []>();
const mockUseSearchParams = jest.fn<URLSearchParams, []>();
const mockDeactivateSite = jest.fn<Promise<SEOSite>, unknown[]>();
const mockActivateSite = jest.fn<Promise<SEOSite>, unknown[]>();
const mockFetchGoogleBusinessProfileConnection = jest.fn<
  Promise<GoogleBusinessProfileConnectionStatusResponse>,
  unknown[]
>();
const mockFetchGoogleBusinessProfileLocations = jest.fn<Promise<{ locations: Array<unknown> }>, unknown[]>();
const mockFetchSiteAnalyticsSummary = jest.fn<Promise<SiteAnalyticsSummaryResponse>, unknown[]>();
const mockFetchMigrationWorkspaceSummary = jest.fn<Promise<unknown>, unknown[]>();
const mockUpdateMigrationAnalyticsConfig = jest.fn<Promise<unknown>, unknown[]>();
const mockUpsertMigrationWorkspace = jest.fn<Promise<unknown>, unknown[]>();
const mockStartGoogleBusinessProfileConnect = jest.fn<Promise<{ authorization_url: string }>, unknown[]>();
const mockDisconnectGoogleBusinessProfile = jest.fn<Promise<unknown>, unknown[]>();
const mockUpdateSite = jest.fn<Promise<SEOSite>, unknown[]>();

jest.mock("../../components/useOperatorContext", () => ({
  useOperatorContext: () => mockUseOperatorContext(),
}));

jest.mock("next/navigation", () => {
  const actual = jest.requireActual("next/navigation");
  return {
    ...actual,
    useSearchParams: () => mockUseSearchParams(),
  };
});

jest.mock("../../components/AuthProvider", () => ({
  useAuth: () => mockUseAuth(),
}));

jest.mock("../../lib/api/client", () => {
  const actual = jest.requireActual("../../lib/api/client");
  return {
    ...actual,
    deactivateSite: (...args: unknown[]) => mockDeactivateSite(...args),
    activateSite: (...args: unknown[]) => mockActivateSite(...args),
    fetchGoogleBusinessProfileConnection: (...args: unknown[]) => mockFetchGoogleBusinessProfileConnection(...args),
    fetchGoogleBusinessProfileLocations: (...args: unknown[]) => mockFetchGoogleBusinessProfileLocations(...args),
    fetchSiteAnalyticsSummary: (...args: unknown[]) => mockFetchSiteAnalyticsSummary(...args),
    fetchMigrationWorkspaceSummary: (...args: unknown[]) => mockFetchMigrationWorkspaceSummary(...args),
    updateMigrationAnalyticsConfig: (...args: unknown[]) => mockUpdateMigrationAnalyticsConfig(...args),
    upsertMigrationWorkspace: (...args: unknown[]) => mockUpsertMigrationWorkspace(...args),
    startGoogleBusinessProfileConnect: (...args: unknown[]) => mockStartGoogleBusinessProfileConnect(...args),
    disconnectGoogleBusinessProfile: (...args: unknown[]) => mockDisconnectGoogleBusinessProfile(...args),
    updateSite: (...args: unknown[]) => mockUpdateSite(...args),
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
    last_audit_run_id: null,
    last_audit_status: null,
    last_audit_completed_at: null,
    ga4_property_id: "123456789",
    ...overrides,
  };
}

function buildConnection(
  overrides: Partial<GoogleBusinessProfileConnectionStatusResponse> = {},
): GoogleBusinessProfileConnectionStatusResponse {
  return {
    provider: "google_business_profile",
    connected: false,
    business_id: "biz-1",
    granted_scopes: [],
    refresh_token_present: false,
    expires_at: null,
    connected_at: null,
    last_refreshed_at: null,
    reconnect_required: false,
    required_scopes_satisfied: false,
    token_status: "reconnect_required",
    ga4_scope_granted: false,
    required_ga4_scope: "https://www.googleapis.com/auth/analytics.readonly",
    gbp_connection_state: "not_connected",
    gbp_required_scope_granted: null,
    gbp_accounts_count: null,
    gbp_locations_count: null,
    gbp_selected_location_present: null,
    gbp_status_reason: "not_connected",
    gbp_next_action: "Connect Google Profile for this business before loading Business Profile locations.",
    ...overrides,
  };
}

function buildSiteAnalyticsSummary(
  overrides: Partial<SiteAnalyticsSummaryResponse> = {},
): SiteAnalyticsSummaryResponse {
  return {
    business_id: "biz-1",
    site_id: "site-1",
    available: true,
    status: "ok",
    ga4_status: "connected",
    ga4_error_reason: null,
    ga4_last_successful_fetch_at: "2026-05-01T12:00:00Z",
    ga4_last_data_timestamp: "2026-05-01T12:00:00Z",
    ga4_data_freshness_status: "fresh",
    ga4_health: {
      ga4_configured: true,
      ga4_property_id_present: true,
      ga4_property_verified: true,
      ga4_reachable: true,
      ga4_data_available: true,
      ga4_last_checked_at: "2026-05-01T12:00:00Z",
      ga4_health_status: "reachable",
      ga4_health_reason: null,
      ga4_health_message: "GA4 is available for recommendation context.",
      ga4_health_source: "site_property",
      ga4_scope_granted: true,
      ga4_required_scope: "https://www.googleapis.com/auth/analytics.readonly",
      ga4_auth_mode: "service_account",
    },
    message: "ok",
    data_source: "ga4",
    site_metrics_summary: null,
    top_pages_summary: [],
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
    selectedSiteId: "site-1",
    setSelectedSiteId: jest.fn(),
    refreshSites: jest.fn<Promise<SEOSite[]>, []>().mockResolvedValue([buildSite()]),
    ...overrides,
  };
}

function setPrincipal(role: "admin" | "operator") {
  mockUseAuth.mockReturnValue({
    principal: {
      business_id: "biz-1",
      principal_id: role === "admin" ? "admin-1" : "operator-1",
      display_name: role === "admin" ? "Admin One" : "Operator One",
      role,
      is_active: true,
    },
  });
}

beforeEach(() => {
  jest.clearAllMocks();
  mockUseSearchParams.mockReturnValue(new URLSearchParams());
  mockUseOperatorContext.mockReturnValue(baseContext());
  setPrincipal("admin");
  mockFetchGoogleBusinessProfileConnection.mockResolvedValue(buildConnection());
  mockFetchGoogleBusinessProfileLocations.mockResolvedValue({ locations: [] });
  mockFetchSiteAnalyticsSummary.mockResolvedValue(buildSiteAnalyticsSummary());
  mockFetchMigrationWorkspaceSummary.mockResolvedValue({
    workspace: {
      analytics_config_json: {
        enabled: true,
        ga_measurement_id: "G-AAAA1111",
        insertion_mode: "publish_and_deploy",
      },
    },
    publish_readiness: {},
    deploy_readiness: {},
  });
  mockUpdateMigrationAnalyticsConfig.mockResolvedValue({});
  mockUpsertMigrationWorkspace.mockResolvedValue({});
  mockStartGoogleBusinessProfileConnect.mockResolvedValue({
    authorization_url: "https://accounts.google.com/o/oauth2/v2/auth?scope=scope",
  });
  mockDisconnectGoogleBusinessProfile.mockResolvedValue({ connection: buildConnection() });
  mockUpdateSite.mockResolvedValue(buildSite({ ga4_property_id: "987654321" }));
});

async function renderSitesPageAndWaitForSetupEffects() {
  render(<SitesPage />);
  await waitFor(() =>
    expect(mockFetchGoogleBusinessProfileConnection).toHaveBeenCalledWith("token-1", { includeStatusDetails: true })
  );
}

describe("sites page inventory + setup boundaries", () => {
  it("renders sites inventory and selected-site setup while removing old intelligence tables", async () => {
    await renderSitesPageAndWaitForSetupEffects();

    expect(screen.getByRole("heading", { name: "Configured Sites" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Selected Site Setup" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Selected Site Routing" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Site Intelligence" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /Prioritized Findings/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /^Recommendations$/i })).not.toBeInTheDocument();

    expect(await screen.findByRole("button", { name: "Save GA4 Property" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save Analytics Rules" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Refresh" })).toBeInTheDocument();
  });

  it("supports disconnect and refresh actions from Sites selected-site setup", async () => {
    mockFetchGoogleBusinessProfileConnection.mockResolvedValueOnce(
      buildConnection({
        connected: true,
        token_status: "usable",
        required_scopes_satisfied: true,
        refresh_token_present: true,
      }),
    );
    mockFetchGoogleBusinessProfileLocations.mockResolvedValueOnce({
      locations: [
        {
          account_id: "acct-1",
          account_name: "Account 1",
          location_id: "loc-1",
          title: "Main Location",
          address: "123 Main St",
          state: "verified",
          verification: {
            state_summary: "verified",
            recommended_next_action: "none",
            guidance: {
              title: "Verified",
              summary: "Already verified.",
              cta_label: "No action needed",
            },
          },
        },
      ],
    });

    await renderSitesPageAndWaitForSetupEffects();

    const disconnect = await screen.findByRole("button", { name: "Disconnect" });
    fireEvent.click(disconnect);
    await waitFor(() => expect(mockDisconnectGoogleBusinessProfile).toHaveBeenCalledWith("token-1"));

    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await waitFor(() => expect(mockFetchGoogleBusinessProfileConnection).toHaveBeenCalled());
  });

  it("saves GA4 property and analytics insertion rules from Sites setup panel", async () => {
    await renderSitesPageAndWaitForSetupEffects();

    const ga4Input = await screen.findByLabelText("GA4 property ID (numeric)");
    fireEvent.change(ga4Input, { target: { value: "987654321" } });
    fireEvent.click(screen.getByRole("button", { name: "Save GA4 Property" }));
    await waitFor(() =>
      expect(mockUpdateSite).toHaveBeenCalledWith("token-1", "biz-1", "site-1", {
        ga4_property_id: "987654321",
      }),
    );

    const measurementInput = screen.getByLabelText("GA measurement ID");
    fireEvent.change(measurementInput, { target: { value: "G-BBBB2222" } });
    fireEvent.click(screen.getByRole("button", { name: "Save Analytics Rules" }));
    await waitFor(() =>
      expect(mockUpdateMigrationAnalyticsConfig).toHaveBeenCalledWith("token-1", "biz-1", "site-1", {
        analytics_config: {
          enabled: true,
          ga_measurement_id: "G-BBBB2222",
          insertion_mode: "publish_and_deploy",
        },
      }),
    );
  });

  it("keeps inventory actions for add site, workspace launch, run audit, integration setup, and admin deactivate", async () => {
    const confirmSpy = jest.spyOn(window, "confirm").mockReturnValue(false);

    await renderSitesPageAndWaitForSetupEffects();

    expect(screen.getByRole("button", { name: "Add Site" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open Workspace" })).toHaveAttribute("href", "/sites/site-1");
    expect(screen.getByRole("button", { name: "Run First Audit" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Manage Integrations" })).toHaveAttribute(
      "href",
      "/sites?site_id=site-1#selected-site-setup",
    );

    fireEvent.click(screen.getByRole("button", { name: "Deactivate Site" }));
    expect(confirmSpy).toHaveBeenCalled();
    expect(mockDeactivateSite).not.toHaveBeenCalled();

    confirmSpy.mockRestore();
  });

  it("hides site deactivate controls for non-admin principals", async () => {
    setPrincipal("operator");
    await renderSitesPageAndWaitForSetupEffects();
    expect(screen.queryByRole("button", { name: "Deactivate Site" })).not.toBeInTheDocument();
    expect(screen.queryByText("Admin Action")).not.toBeInTheDocument();
  });

  it("treats gbp_connect=success as return hint only when final state is still not connected", async () => {
    mockUseSearchParams.mockReturnValue(new URLSearchParams("gbp_connect=success"));
    mockFetchGoogleBusinessProfileConnection.mockResolvedValueOnce(
      buildConnection({
        connected: false,
        reconnect_required: true,
        token_status: "reconnect_required",
      }),
    );

    await renderSitesPageAndWaitForSetupEffects();

    expect(screen.getByText("Not connected")).toBeInTheDocument();
    expect(
      screen.getByText("Google returned successfully, but no usable Google Business Profile connection was detected."),
    ).toBeInTheDocument();
    expect(screen.queryByText("Google returned successfully and Google Profile is connected.")).not.toBeInTheDocument();
  });

  it("shows denied state when oauth succeeds but GBP access is denied", async () => {
    mockUseSearchParams.mockReturnValue(new URLSearchParams("gbp_connect=success"));
    mockFetchGoogleBusinessProfileConnection.mockResolvedValueOnce(
      buildConnection({
        connected: true,
        reconnect_required: false,
        required_scopes_satisfied: true,
        token_status: "usable",
        gbp_connection_state: "permission_denied",
        gbp_status_reason: "permission_denied",
      }),
    );

    await renderSitesPageAndWaitForSetupEffects();

    expect(screen.getByText("Access denied")).toBeInTheDocument();
    expect(
      screen.getByText("Google returned successfully, but Google Business Profile access is denied for this account."),
    ).toBeInTheDocument();
    expect(screen.queryByText("Google returned successfully and Google Profile is connected.")).not.toBeInTheDocument();
  });

  it("shows connected success only when connection is actually usable", async () => {
    mockUseSearchParams.mockReturnValue(new URLSearchParams("gbp_connect=success"));
    mockFetchGoogleBusinessProfileConnection.mockResolvedValueOnce(
      buildConnection({
        connected: true,
        reconnect_required: false,
        required_scopes_satisfied: true,
        token_status: "usable",
        gbp_connection_state: "usable",
        gbp_status_reason: "usable",
      }),
    );

    await renderSitesPageAndWaitForSetupEffects();

    expect(screen.getByText("Connected")).toBeInTheDocument();
    expect(screen.getByText("Google returned successfully and Google Profile is connected.")).toBeInTheDocument();
  });

  it("shows neutral checking message while oauth success state is still loading", async () => {
    mockUseSearchParams.mockReturnValue(new URLSearchParams("gbp_connect=success"));
    mockFetchSiteAnalyticsSummary.mockReturnValueOnce(new Promise(() => undefined));
    mockFetchMigrationWorkspaceSummary.mockReturnValueOnce(new Promise(() => undefined));
    let resolveConnection: ((value: GoogleBusinessProfileConnectionStatusResponse) => void) | null = null;
    mockFetchGoogleBusinessProfileConnection.mockReturnValueOnce(
      new Promise<GoogleBusinessProfileConnectionStatusResponse>((resolve) => {
        resolveConnection = resolve;
      }),
    );

    render(<SitesPage />);
    expect(screen.getByText("Returned from Google; checking connection status.")).toBeInTheDocument();

    expect(resolveConnection).not.toBeNull();
    resolveConnection!(buildConnection());
    await waitFor(() =>
      expect(mockFetchGoogleBusinessProfileConnection).toHaveBeenCalledWith("token-1", { includeStatusDetails: true })
    );
  });

  it("shows missing-scope guidance from backend status without contradictory success text", async () => {
    mockUseSearchParams.mockReturnValue(new URLSearchParams("gbp_connect=success"));
    mockFetchGoogleBusinessProfileConnection.mockResolvedValueOnce(
      buildConnection({
        connected: true,
        reconnect_required: true,
        required_scopes_satisfied: false,
        token_status: "insufficient_scope",
        gbp_connection_state: "missing_scope",
        gbp_status_reason: "missing_scope",
      }),
    );

    await renderSitesPageAndWaitForSetupEffects();

    expect(screen.getByText("Scope missing")).toBeInTheDocument();
    expect(
      screen.getAllByText("Reconnect Google Profile to grant the required Business Profile readonly scope.").length,
    ).toBeGreaterThan(0);
    expect(screen.queryByText("Google returned successfully and Google Profile is connected.")).not.toBeInTheDocument();
  });

  it("shows no-accounts state when oauth succeeded but provider returned no accounts", async () => {
    mockUseSearchParams.mockReturnValue(new URLSearchParams("gbp_connect=success"));
    mockFetchGoogleBusinessProfileConnection.mockResolvedValueOnce(
      buildConnection({
        connected: true,
        reconnect_required: false,
        required_scopes_satisfied: true,
        token_status: "usable",
        gbp_connection_state: "no_accounts",
        gbp_accounts_count: 0,
        gbp_locations_count: 0,
        gbp_status_reason: "no_accounts",
      }),
    );

    await renderSitesPageAndWaitForSetupEffects();

    expect(screen.getByText("No accounts")).toBeInTheDocument();
    expect(
      screen.getAllByText("Google account is linked, but no Business Profile accounts were returned.").length,
    ).toBeGreaterThan(0);
    expect(screen.queryByText("Google returned successfully and Google Profile is connected.")).not.toBeInTheDocument();
  });

  it("shows no-locations state when oauth succeeded but provider returned no locations", async () => {
    mockUseSearchParams.mockReturnValue(new URLSearchParams("gbp_connect=success"));
    mockFetchGoogleBusinessProfileConnection.mockResolvedValueOnce(
      buildConnection({
        connected: true,
        reconnect_required: false,
        required_scopes_satisfied: true,
        token_status: "usable",
        gbp_connection_state: "no_locations",
        gbp_accounts_count: 1,
        gbp_locations_count: 0,
        gbp_status_reason: "no_locations",
      }),
    );

    await renderSitesPageAndWaitForSetupEffects();

    expect(screen.getByText("No locations")).toBeInTheDocument();
    expect(
      screen.getAllByText("Google account is linked, but no Business Profile locations were returned.").length,
    ).toBeGreaterThan(0);
    expect(screen.queryByText("Google returned successfully and Google Profile is connected.")).not.toBeInTheDocument();
  });
});
