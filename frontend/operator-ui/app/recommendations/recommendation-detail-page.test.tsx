import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";

import RecommendationDetailPage from "./[id]/page";
import { ApiRequestError } from "../../lib/api/client";
import type { Recommendation } from "../../lib/api/types";

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

type Deferred<T> = {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (reason?: unknown) => void;
};

const detailNavigationState = {
  params: { id: "rec-detail-1" },
  searchParams: new URLSearchParams("site_id=site-1&status=open&sort=newest&page=2&page_size=50"),
};

const mockUseOperatorContext = jest.fn<OperatorContextMockValue, []>();
const mockFetchRecommendation = jest.fn<Promise<Recommendation>, unknown[]>();
const mockUpdateRecommendationStatus = jest.fn<Promise<Recommendation>, unknown[]>();

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
  useParams: () => detailNavigationState.params,
  useSearchParams: () => detailNavigationState.searchParams,
}));

jest.mock("../../components/useOperatorContext", () => ({
  useOperatorContext: () => mockUseOperatorContext(),
}));

jest.mock("../../lib/api/client", () => {
  const actual = jest.requireActual("../../lib/api/client");
  return {
    ...actual,
    fetchRecommendation: (...args: unknown[]) => mockFetchRecommendation(...args),
    updateRecommendationStatus: (...args: unknown[]) => mockUpdateRecommendationStatus(...args),
  };
});

function createDeferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function createRecommendation(overrides: Partial<Recommendation> = {}): Recommendation {
  return {
    id: "rec-detail-1",
    business_id: "biz-1",
    site_id: "site-1",
    recommendation_run_id: "rec-run-1",
    audit_run_id: null,
    comparison_run_id: null,
    status: "open",
    category: "SEO",
    severity: "warning",
    priority_score: 82,
    priority_band: "high",
    effort_bucket: "small",
    title: "Improve title tags",
    rationale: "Pages are missing target keyword in title tags.",
    eeat_categories: [],
    primary_eeat_category: null,
    decision_reason: null,
    created_at: "2026-03-20T00:00:00Z",
    updated_at: "2026-03-20T00:00:00Z",
    ...overrides,
  };
}

function baseOperatorContext(): OperatorContextMockValue {
  return {
    loading: false,
    error: null,
    token: "token-1",
    businessId: "biz-1",
    sites: [{ id: "site-1", display_name: "Site One" }],
    selectedSiteId: "site-1",
    setSelectedSiteId: jest.fn(),
    refreshSites: jest.fn(),
  };
}

beforeEach(() => {
  jest.clearAllMocks();
  detailNavigationState.params = { id: "rec-detail-1" };
  detailNavigationState.searchParams = new URLSearchParams(
    "site_id=site-1&status=open&sort=newest&page=2&page_size=50",
  );
  mockUseOperatorContext.mockReturnValue(baseOperatorContext());
});

describe("recommendation detail optimistic single-item updates", () => {
  it("updates status immediately and reconciles state on successful save", async () => {
    mockFetchRecommendation.mockResolvedValueOnce(createRecommendation());
    const updateDeferred = createDeferred<Recommendation>();
    mockUpdateRecommendationStatus.mockImplementationOnce(() => updateDeferred.promise);

    const user = userEvent.setup();
    render(<RecommendationDetailPage />);

    await screen.findByText("Status: open");
    expect(screen.getByTestId("recommendation-detail-workflow-context")).toBeInTheDocument();
    const detailFocus = screen.getByTestId("recommendation-detail-focus");
    expect(detailFocus).toBeInTheDocument();
    expect(screen.getByText("Recommendation outcome snapshot")).toBeInTheDocument();
    expect(screen.getByText("Why this matters now")).toBeInTheDocument();
    expect(screen.getByText("Can I act now")).toBeInTheDocument();
    expect(screen.getByText("Blocking state")).toBeInTheDocument();
    expect(screen.getByText("After action")).toBeInTheDocument();
    expect(screen.getByText("Evidence preview")).toBeInTheDocument();
    expect(screen.getByText("Evidence trust")).toBeInTheDocument();
    expect(
      screen.getByText("High-value next step based on current priority and open status."),
    ).toBeInTheDocument();
    expect(screen.getByText("Support cue: operator review required")).toBeInTheDocument();
    expect(
      screen.getByText("Yes. Open actions below and choose accept or dismiss."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Yes. Review the recommendation and choose accept or dismiss."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("No downstream visibility change until an apply action is recorded."),
    ).toBeInTheDocument();
    const recommendationContextHeading = screen.getByRole("heading", { name: "Recommendation Context" });
    expect(detailFocus.compareDocumentPosition(recommendationContextHeading) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByRole("link", { name: "Parent Recommendation Run" })).toBeInTheDocument();
    await user.type(screen.getByLabelText("Operator Note"), "Ship this next sprint");
    await user.click(screen.getByRole("button", { name: "Accept" }));

    expect(screen.getByText("Status: accepted")).toBeInTheDocument();
    expect(screen.getByText("Recommendation is marked accepted for this site.")).toBeInTheDocument();
    expect(screen.getByText("Yes. Confirm this change in the next analysis refresh.")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Ship this next sprint")).toBeInTheDocument();

    await act(async () => {
      updateDeferred.resolve(
        createRecommendation({
          status: "accepted",
          decision_reason: "Backend normalized note",
          updated_at: "2026-03-20T01:00:00Z",
        }),
      );
      await Promise.resolve();
    });

    await screen.findByText("Recommendation marked as accepted.");
    expect(screen.getByText("Status: accepted")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Backend normalized note")).toBeInTheDocument();
    expect(screen.getByText("Apply is complete and now needs visibility confirmation.")).toBeInTheDocument();
    expect(screen.getByText("No. Wait for refresh, then verify outcome.")).toBeInTheDocument();
    expect(mockUpdateRecommendationStatus).toHaveBeenCalledWith(
      "token-1",
      "biz-1",
      "site-1",
      "rec-detail-1",
      {
        status: "accepted",
        note: "Ship this next sprint",
      },
    );
  });

  it("rolls back optimistic status and shows safe error when save fails", async () => {
    mockFetchRecommendation.mockResolvedValueOnce(createRecommendation());
    const updateDeferred = createDeferred<Recommendation>();
    mockUpdateRecommendationStatus.mockImplementationOnce(() => updateDeferred.promise);

    const user = userEvent.setup();
    render(<RecommendationDetailPage />);

    await screen.findByText("Status: open");
    await user.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(screen.getByText("Status: dismissed")).toBeInTheDocument();

    await act(async () => {
      updateDeferred.reject(
        new ApiRequestError("invalid transition", {
          status: 422,
          detail: null,
        }),
      );
      await Promise.resolve();
    });

    await screen.findByText("Recommendation update is not allowed in the current state.");
    expect(screen.getByText("Status: open")).toBeInTheDocument();
  });
});
