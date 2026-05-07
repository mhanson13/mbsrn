import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import BusinessProfilePage from "./page";
import type { GoogleBusinessProfileConnectionStatusResponse, SiteAnalyticsSummaryResponse } from "../../lib/api/types";

type OperatorContextMockValue = {
  loading: boolean;
  error: string | null;
  token: string;
  businessId: string;
  sites: Array<{
    id: string;
    display_name: string;
    normalized_domain?: string;
    business_id?: string;
    ga4_property_id?: string | null;
  }>;
  selectedSiteId: string | null;
  setSelectedSiteId: jest.Mock;
  refreshSites: jest.Mock;
};

const mockUseOperatorContext = jest.fn<OperatorContextMockValue, []>();
const mockFetchGoogleBusinessProfileConnection = jest.fn<
  Promise<GoogleBusinessProfileConnectionStatusResponse>,
  unknown[]
>();
const mockFetchGoogleBusinessProfileLocations = jest.fn<
  Promise<{ locations: Array<unknown> }>,
  unknown[]
>();
const mockFetchSiteAnalyticsSummary = jest.fn<Promise<SiteAnalyticsSummaryResponse>, unknown[]>();
const mockFetchMigrationWorkspaceSummary = jest.fn<Promise<unknown>, unknown[]>();
const mockUpdateMigrationAnalyticsConfig = jest.fn<Promise<unknown>, unknown[]>();
const mockUpsertMigrationWorkspace = jest.fn<Promise<unknown>, unknown[]>();

jest.mock("../../components/useOperatorContext", () => ({
  useOperatorContext: () => mockUseOperatorContext(),
}));

jest.mock("../../lib/api/client", () => {
  const actual = jest.requireActual("../../lib/api/client");
  return {
    ...actual,
    fetchGoogleBusinessProfileConnection: (...args: unknown[]) => mockFetchGoogleBusinessProfileConnection(...args),
    fetchGoogleBusinessProfileLocations: (...args: unknown[]) => mockFetchGoogleBusinessProfileLocations(...args),
    fetchSiteAnalyticsSummary: (...args: unknown[]) => mockFetchSiteAnalyticsSummary(...args),
    fetchMigrationWorkspaceSummary: (...args: unknown[]) => mockFetchMigrationWorkspaceSummary(...args),
    updateMigrationAnalyticsConfig: (...args: unknown[]) => mockUpdateMigrationAnalyticsConfig(...args),
    upsertMigrationWorkspace: (...args: unknown[]) => mockUpsertMigrationWorkspace(...args),
  };
});

function buildDisconnectedConnection(
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
    ...overrides,
  };
}

function buildSiteAnalyticsSummary(
  overrides: Partial<SiteAnalyticsSummaryResponse> = {},
): SiteAnalyticsSummaryResponse {
  return {
    business_id: "biz-1",
    site_id: "site-1",
    available: false,
    status: "not_configured",
    ga4_status: "not_configured",
    ga4_error_reason: "not_configured",
    ga4_last_successful_fetch_at: null,
    ga4_last_data_timestamp: null,
    ga4_data_freshness_status: "unknown",
    ga4_health: {
      ga4_configured: false,
      ga4_property_id_present: false,
      ga4_property_verified: null,
      ga4_reachable: null,
      ga4_data_available: null,
      ga4_last_checked_at: null,
      ga4_health_status: "not_configured",
      ga4_health_reason: "not_configured",
      ga4_health_message: "Add a GA4 property ID for this site.",
      ga4_health_source: "unavailable",
    },
    message: "Google Analytics property is not configured for this site.",
    data_source: null,
    site_metrics_summary: null,
    top_pages_summary: [],
    ...overrides,
  };
}

describe("business profile callback notice UX", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    window.history.pushState({}, "", "/business-profile");

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
    mockFetchGoogleBusinessProfileConnection.mockResolvedValue(buildDisconnectedConnection());
    mockFetchGoogleBusinessProfileLocations.mockResolvedValue({ locations: [] });
    mockFetchSiteAnalyticsSummary.mockResolvedValue(buildSiteAnalyticsSummary());
    mockFetchMigrationWorkspaceSummary.mockResolvedValue({
      workspace: {
        analytics_config_json: {
          enabled: true,
          ga_measurement_id: null,
          insertion_mode: "publish_and_deploy",
        },
      },
      publish_readiness: {},
      deploy_readiness: {},
    });
    mockUpdateMigrationAnalyticsConfig.mockResolvedValue({});
    mockUpsertMigrationWorkspace.mockResolvedValue({});
  });

  it("renders success callback notice when gbp_connect=success", async () => {
    window.history.pushState({}, "", "/business-profile?gbp_connect=success");

    render(<BusinessProfilePage />);

    await waitFor(() =>
      expect(mockFetchGoogleBusinessProfileConnection).toHaveBeenCalledWith("token-1"),
    );
    expect(document.querySelector(".page-container-width-wide")).toBeTruthy();
    expect(screen.queryByLabelText("Site")).not.toBeInTheDocument();
    expect(
      await screen.findByText("Google Profile connected successfully."),
    ).toBeInTheDocument();
  });

  it("renders reconnect-required error callback notice safely", async () => {
    window.history.pushState(
      {},
      "",
      "/business-profile?gbp_connect=error&gbp_reconnect_required=true&gbp_connect_error=token_exchange_failed&gbp_raw=provider_detail",
    );

    render(<BusinessProfilePage />);

    await waitFor(() =>
      expect(mockFetchGoogleBusinessProfileConnection).toHaveBeenCalledWith("token-1"),
    );
    expect(
      await screen.findByText("Google Profile connection requires reauthorization. Please reconnect."),
    ).toBeInTheDocument();
    expect(screen.queryByText(/token_exchange_failed/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/provider_detail/i)).not.toBeInTheDocument();
  });

  it("renders generic error callback notice when reconnect flag is absent", async () => {
    window.history.pushState(
      {},
      "",
      "/business-profile?gbp_connect=error&gbp_connect_error=access_denied&gbp_error_description=raw_oauth_error",
    );

    render(<BusinessProfilePage />);

    await waitFor(() =>
      expect(mockFetchGoogleBusinessProfileConnection).toHaveBeenCalledWith("token-1"),
    );
    expect(
      await screen.findByText("Google Profile connection did not complete. Please try connecting again."),
    ).toBeInTheDocument();
    expect(screen.queryByText(/raw_oauth_error/i)).not.toBeInTheDocument();
  });

  it("does not render callback notice when no callback query params are present", async () => {
    window.history.pushState({}, "", "/business-profile");

    render(<BusinessProfilePage />);

    await waitFor(() =>
      expect(mockFetchGoogleBusinessProfileConnection).toHaveBeenCalledWith("token-1"),
    );
    await screen.findByRole("heading", { name: "Google Profile" });
    expect(screen.queryByText("Google Profile connected successfully.")).not.toBeInTheDocument();
    expect(
      screen.queryByText("Google Profile connection did not complete. Please try connecting again."),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText("Google Profile connection requires reauthorization. Please reconnect."),
    ).not.toBeInTheDocument();
  });

  it("renders analytics insertion rules and saves migration analytics config for the selected site", async () => {
    mockUseOperatorContext.mockReturnValue({
      loading: false,
      error: null,
      token: "token-1",
      businessId: "biz-1",
      sites: [
        {
          id: "site-1",
          display_name: "Main Site",
          normalized_domain: "example.com",
          business_id: "biz-1",
          ga4_property_id: "123456789",
        },
      ],
      selectedSiteId: "site-1",
      setSelectedSiteId: jest.fn(),
      refreshSites: jest.fn(),
    });
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

    render(<BusinessProfilePage />);

    expect(await screen.findByRole("heading", { name: "Analytics Insertion Rules" })).toBeInTheDocument();
    expect(await screen.findByDisplayValue("G-AAAA1111")).toBeInTheDocument();

    const measurementInput = screen.getByLabelText("GA measurement ID");
    fireEvent.change(measurementInput, { target: { value: "G-BBBB2222" } });

    const modeSelect = screen.getByLabelText("Insertion mode");
    fireEvent.change(modeSelect, { target: { value: "publish_only" } });

    fireEvent.click(screen.getByRole("button", { name: "Save Analytics Rules" }));

    await waitFor(() =>
      expect(mockUpdateMigrationAnalyticsConfig).toHaveBeenCalledWith(
        "token-1",
        "biz-1",
        "site-1",
        {
          analytics_config: {
            enabled: true,
            ga_measurement_id: "G-BBBB2222",
            insertion_mode: "publish_only",
          },
        },
      ),
    );
  });

  it("renders compact GA4 property health for the selected site", async () => {
    mockUseOperatorContext.mockReturnValue({
      loading: false,
      error: null,
      token: "token-1",
      businessId: "biz-1",
      sites: [
        {
          id: "site-1",
          display_name: "Main Site",
          normalized_domain: "example.com",
          business_id: "biz-1",
          ga4_property_id: "123456789",
        },
      ],
      selectedSiteId: "site-1",
      setSelectedSiteId: jest.fn(),
      refreshSites: jest.fn(),
    });
    mockFetchSiteAnalyticsSummary.mockResolvedValue(
      buildSiteAnalyticsSummary({
        available: true,
        status: "ok",
        ga4_status: "connected",
        ga4_error_reason: null,
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
        },
      }),
    );

    render(<BusinessProfilePage />);

    await waitFor(() =>
      expect(mockFetchSiteAnalyticsSummary).toHaveBeenCalledWith("token-1", "biz-1", "site-1"),
    );
    expect(await screen.findByTestId("google-profile-ga4-health")).toBeInTheDocument();
    expect(screen.getByText("GA4 property health")).toBeInTheDocument();
    expect(screen.getByText("Reachable")).toBeInTheDocument();
    expect(screen.getByText("GA4 is available for recommendation context.")).toBeInTheDocument();
  });
});
