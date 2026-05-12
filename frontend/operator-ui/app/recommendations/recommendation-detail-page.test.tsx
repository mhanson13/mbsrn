import { act, render, screen, within } from "@testing-library/react";
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
    audit_run_id: "audit-run-1",
    comparison_run_id: null,
    status: "open",
    category: "SEO",
    severity: "warning",
    priority_score: 82,
    priority_band: "high",
    effort_bucket: "small",
    title: "Improve title tags",
    rationale: "Pages are missing target keyword in title tags.",
    why_now: "The homepage ranks for high-volume intent and needs a stronger title signal.",
    next_action: "Update the homepage title and re-check in the next crawl.",
    blocking_reason: "Operator review required before publish.",
    evidence_strength: "strong",
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

describe("recommendation detail decision-first layout", () => {
  it("renders compact decision-first sections and reconciles optimistic accept saves", async () => {
    mockFetchRecommendation.mockResolvedValueOnce(createRecommendation());
    const updateDeferred = createDeferred<Recommendation>();
    mockUpdateRecommendationStatus.mockImplementationOnce(() => updateDeferred.promise);

    const user = userEvent.setup();
    render(<RecommendationDetailPage />);

    const header = await screen.findByTestId("recommendation-detail-header");
    const statusStrip = screen.getByTestId("recommendation-detail-status-strip");
    const decisionSummary = screen.getByTestId("recommendation-detail-decision-summary");
    const actionsCard = screen.getByTestId("recommendation-detail-actions");
    const lineageCard = screen.getByTestId("recommendation-detail-lineage-scope");

    expect(header).toBeInTheDocument();
    expect(within(statusStrip).getByText("open")).toBeInTheDocument();
    expect(screen.queryByTestId("recommendation-detail-workflow-context")).not.toBeInTheDocument();
    expect(screen.queryByTestId("recommendation-detail-focus")).not.toBeInTheDocument();
    expect(screen.queryByText("Recommendation outcome snapshot")).not.toBeInTheDocument();
    expect(screen.queryByText("Lifecycle stage")).not.toBeInTheDocument();
    expect(screen.queryByText("Refresh check")).not.toBeInTheDocument();
    expect(screen.queryByText("Choice support")).not.toBeInTheDocument();

    expect(within(decisionSummary).getByText("What this is")).toBeInTheDocument();
    expect(within(decisionSummary).getByText("Why it matters")).toBeInTheDocument();
    expect(within(decisionSummary).getByText("Recommended next action")).toBeInTheDocument();
    expect(within(decisionSummary).getByText("Blocked by")).toBeInTheDocument();
    expect(within(decisionSummary).getByText("Evidence confidence")).toBeInTheDocument();
    expect(within(decisionSummary).getByText("Measurement availability")).toBeInTheDocument();
    expect(decisionSummary.querySelectorAll("dt")).toHaveLength(6);

    expect(actionsCard.compareDocumentPosition(lineageCard) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByRole("link", { name: "Back to Recommendations" })).toHaveAttribute(
      "href",
      "/recommendations?status=open&sort=newest&page=2&page_size=50",
    );
    expect(screen.getByRole("link", { name: "Parent Recommendation Run" })).toHaveAttribute(
      "href",
      "/recommendations/runs/rec-run-1?site_id=site-1",
    );
    expect(screen.getByRole("link", { name: "Linked Audit Run" })).toHaveAttribute("href", "/audits/audit-run-1");

    await user.type(screen.getByLabelText("Operator Note"), "Ship this next sprint");
    await user.click(screen.getByRole("button", { name: "Accept" }));

    expect(within(statusStrip).getByText("accepted")).toBeInTheDocument();
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
    expect(within(statusStrip).getByText("accepted")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Backend normalized note")).toBeInTheDocument();
    expect(screen.getByTestId("recommendation-detail-saved-note")).toHaveTextContent("Saved note: Backend normalized note");
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
    mockUpdateRecommendationStatus.mockRejectedValueOnce(
      new ApiRequestError("invalid transition", {
        status: 422,
        detail: null,
      }),
    );

    const user = userEvent.setup();
    render(<RecommendationDetailPage />);

    const statusStrip = await screen.findByTestId("recommendation-detail-status-strip");
    expect(within(statusStrip).getByText("open")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Dismiss" }));

    expect(mockUpdateRecommendationStatus).toHaveBeenCalledTimes(1);
    await screen.findByText("Recommendation update is not allowed in the current state.");
    expect(within(statusStrip).getByText("open")).toBeInTheDocument();
  });
});
