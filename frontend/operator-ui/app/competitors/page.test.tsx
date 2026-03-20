import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";

import CompetitorsPage from "./page";
import type { CompetitorDomainListResponse, CompetitorSetListResponse } from "../../lib/api/types";

type OperatorContextMockValue = {
  loading: boolean;
  error: string | null;
  token: string;
  businessId: string;
  sites: Array<{ id: string; display_name: string }>;
  selectedSiteId: string | null;
  setSelectedSiteId: jest.Mock;
  refreshSites: jest.Mock;
};

const navigationState = {
  searchParams: new URLSearchParams(),
  push: jest.fn(),
};

const mockUseOperatorContext = jest.fn<OperatorContextMockValue, []>();
const mockFetchCompetitorSets = jest.fn<Promise<CompetitorSetListResponse>, unknown[]>();
const mockFetchCompetitorDomains = jest.fn<Promise<CompetitorDomainListResponse>, unknown[]>();

jest.mock("next/link", () => {
  return function MockLink({
    href,
    children,
  }: {
    href: string;
    children: ReactNode;
  }) {
    return <a href={href}>{children}</a>;
  };
});

jest.mock("next/navigation", () => ({
  useRouter: () => ({
    push: navigationState.push,
  }),
  useSearchParams: () => navigationState.searchParams,
}));

jest.mock("../../components/useOperatorContext", () => ({
  useOperatorContext: () => mockUseOperatorContext(),
}));

jest.mock("../../lib/api/client", () => {
  const actual = jest.requireActual("../../lib/api/client");
  return {
    ...actual,
    fetchCompetitorSets: (...args: unknown[]) => mockFetchCompetitorSets(...args),
    fetchCompetitorDomains: (...args: unknown[]) => mockFetchCompetitorDomains(...args),
  };
});

function baseOperatorContext(overrides: Partial<OperatorContextMockValue> = {}): OperatorContextMockValue {
  return {
    loading: false,
    error: null,
    token: "token-1",
    businessId: "biz-1",
    sites: [{ id: "site-1", display_name: "Site One" }],
    selectedSiteId: "site-1",
    setSelectedSiteId: jest.fn(),
    refreshSites: jest.fn(),
    ...overrides,
  };
}

beforeEach(() => {
  jest.clearAllMocks();
  navigationState.searchParams = new URLSearchParams();
  mockUseOperatorContext.mockReturnValue(baseOperatorContext());
});

describe("competitors page site-scoped loading", () => {
  it("renders competitor sets for the selected configured site", async () => {
    mockFetchCompetitorSets.mockResolvedValueOnce({
      items: [
        {
          id: "set-1",
          business_id: "biz-1",
          site_id: "site-1",
          name: "Front Range",
          city: "Denver",
          state: "CO",
          is_active: true,
          created_by_principal_id: "principal-1",
          created_at: "2026-03-20T00:00:00Z",
          updated_at: "2026-03-20T00:00:00Z",
        },
      ],
      total: 1,
    });
    mockFetchCompetitorDomains.mockResolvedValueOnce({
      items: [
        {
          id: "domain-1",
          business_id: "biz-1",
          site_id: "site-1",
          competitor_set_id: "set-1",
          domain: "competitor.example",
          base_url: "https://competitor.example/",
          display_name: "Competitor",
          source: "manual",
          is_active: true,
          notes: null,
          created_at: "2026-03-20T00:00:00Z",
          updated_at: "2026-03-20T00:00:00Z",
        },
      ],
      total: 1,
    });

    render(<CompetitorsPage />);

    await screen.findByText("Front Range");
    expect(mockFetchCompetitorSets).toHaveBeenCalledWith("token-1", "biz-1", "site-1");
    expect(screen.getByText("Competitor Sets: 1")).toBeInTheDocument();
  });

  it("applies URL site_id context so competitors load for the linked site", async () => {
    navigationState.searchParams = new URLSearchParams("site_id=site-2");
    const contextState = baseOperatorContext({
      sites: [
        { id: "site-1", display_name: "Site One" },
        { id: "site-2", display_name: "Site Two" },
      ],
      selectedSiteId: "site-1",
    });
    contextState.setSelectedSiteId.mockImplementation((nextSiteId: string) => {
      contextState.selectedSiteId = nextSiteId;
    });
    mockUseOperatorContext.mockImplementation(() => contextState);

    mockFetchCompetitorSets.mockImplementation(async (_token, _businessId, siteId) => {
      if (siteId === "site-2") {
        return {
          items: [
            {
              id: "set-2",
              business_id: "biz-1",
              site_id: "site-2",
              name: "Metro Competitors",
              city: "Aurora",
              state: "CO",
              is_active: true,
              created_by_principal_id: "principal-2",
              created_at: "2026-03-20T00:00:00Z",
              updated_at: "2026-03-20T00:00:00Z",
            },
          ],
          total: 1,
        };
      }
      return { items: [], total: 0 };
    });
    mockFetchCompetitorDomains.mockResolvedValue({
      items: [],
      total: 0,
    });

    const view = render(<CompetitorsPage />);

    await waitFor(() => expect(contextState.setSelectedSiteId).toHaveBeenCalledWith("site-2"));

    view.rerender(<CompetitorsPage />);
    await screen.findByText("Metro Competitors");
    expect(mockFetchCompetitorSets).toHaveBeenCalledWith("token-1", "biz-1", "site-2");
  });
});
