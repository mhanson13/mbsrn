import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import RecommendationsPage from "./page";
import { ApiRequestError } from "../../lib/api/client";
import type {
  Recommendation,
  RecommendationActionStatus,
  RecommendationListResponse,
} from "../../lib/api/types";

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

const navigationState = {
  pathname: "/recommendations",
  searchParams: new URLSearchParams(),
  push: jest.fn(),
  replace: jest.fn(),
};

const mockUseOperatorContext = jest.fn<OperatorContextMockValue, []>();
const mockFetchRecommendations = jest.fn<Promise<RecommendationListResponse>, unknown[]>();
const mockUpdateRecommendationStatus = jest.fn<Promise<Recommendation>, unknown[]>();

jest.mock("next/navigation", () => ({
  useRouter: () => ({
    push: navigationState.push,
    replace: navigationState.replace,
  }),
  usePathname: () => navigationState.pathname,
  useSearchParams: () => navigationState.searchParams,
}));

jest.mock("../../components/useOperatorContext", () => ({
  useOperatorContext: () => mockUseOperatorContext(),
}));

jest.mock("../../lib/api/client", () => {
  const actual = jest.requireActual("../../lib/api/client");
  return {
    ...actual,
    fetchRecommendations: (...args: unknown[]) => mockFetchRecommendations(...args),
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

function createRecommendation(
  id: string,
  status: string,
  priorityBand: "low" | "medium" | "high" | "critical",
  title: string,
): Recommendation {
  return {
    id,
    business_id: "biz-1",
    site_id: "site-1",
    recommendation_run_id: "rec-run-1",
    audit_run_id: null,
    comparison_run_id: null,
    status,
    category: "SEO",
    severity: "warning",
    priority_score: priorityBand === "critical" ? 95 : priorityBand === "high" ? 80 : 50,
    priority_band: priorityBand,
    effort_bucket: "small",
    title,
    rationale: `Rationale for ${title}`,
    eeat_categories: [],
    primary_eeat_category: null,
    decision_reason: null,
    created_at: "2026-03-20T00:00:00Z",
    updated_at: "2026-03-20T00:00:00Z",
  };
}

function createListResponse(
  items: Recommendation[],
  filteredSummary: RecommendationListResponse["filtered_summary"],
  total = items.length,
): RecommendationListResponse {
  return {
    items,
    total,
    filtered_summary: filteredSummary,
  };
}

function getSummaryValue(label: string): string {
  const labelNode = screen
    .getAllByText(label)
    .find((node) => node.tagName.toLowerCase() === "span");
  if (!labelNode) {
    throw new Error(`No summary label found for: ${label}`);
  }
  const card = labelNode.closest("div");
  if (!card) {
    throw new Error(`No summary card found for label: ${label}`);
  }
  const valueNode = within(card).getByText(/^\d+$/);
  return valueNode.textContent || "";
}

function getRecommendationRow(title: string): HTMLElement {
  const titleCell = screen.getByText(title);
  const row = titleCell.closest("tr");
  if (!row) {
    throw new Error(`No recommendation row found for title: ${title}`);
  }
  return row;
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
  mockFetchRecommendations.mockReset();
  mockUpdateRecommendationStatus.mockReset();
  mockUseOperatorContext.mockReset();
  navigationState.pathname = "/recommendations";
  navigationState.searchParams = new URLSearchParams();
  mockUseOperatorContext.mockReturnValue(baseOperatorContext());
});

describe("recommendations queue optimistic workflows", () => {
  it("updates selected visible rows immediately, rolls back failures, and re-selects failed rows", async () => {
    navigationState.searchParams = new URLSearchParams("sort=newest&page=1&page_size=25");
    const recOne = createRecommendation("rec-1", "open", "high", "Recommendation One");
    const recTwo = createRecommendation("rec-2", "open", "medium", "Recommendation Two");
    const refreshed = createListResponse(
      [
        {
          ...recOne,
          status: "dismissed",
          updated_at: "2026-03-20T02:00:00Z",
        },
        recTwo,
      ],
      {
        total: 2,
        open: 1,
        accepted: 0,
        dismissed: 1,
        high_priority: 1,
      },
    );
    mockFetchRecommendations
      .mockResolvedValueOnce(
        createListResponse([recOne, recTwo], {
          total: 2,
          open: 2,
          accepted: 0,
          dismissed: 0,
          high_priority: 1,
        }),
      )
      .mockResolvedValueOnce(refreshed);

    const firstUpdate = createDeferred<Recommendation>();
    const secondUpdate = createDeferred<Recommendation>();
    mockUpdateRecommendationStatus
      .mockImplementationOnce(() => firstUpdate.promise)
      .mockImplementationOnce(() => secondUpdate.promise);

    const user = userEvent.setup();
    render(<RecommendationsPage />);

    await screen.findByText("Recommendation One");
    await screen.findByText("Recommendation Two");
    expect(screen.getByTestId("recommendation-queue-outcome-focus")).toBeInTheDocument();
    expect(screen.getByText("Recommendation outcome snapshot")).toBeInTheDocument();
    expect(screen.getByText("Why this matters now")).toBeInTheDocument();
    expect(screen.getByText("Current status")).toBeInTheDocument();
    expect(screen.getByText("Lifecycle stage")).toBeInTheDocument();
    expect(screen.getByText("Revisit timing")).toBeInTheDocument();
    expect(screen.getByText("Freshness posture")).toBeInTheDocument();
    expect(screen.getByText("Refresh check")).toBeInTheDocument();
    expect(screen.getByText("Choice support")).toBeInTheDocument();
    expect(screen.getByText("Effort signal")).toBeInTheDocument();
    expect(screen.getByText("Can I act now")).toBeInTheDocument();
    expect(screen.getByText("Blocking state")).toBeInTheDocument();
    expect(screen.getByText("After action")).toBeInTheDocument();
    expect(screen.getByText("Evidence preview")).toBeInTheDocument();
    expect(screen.getByText("Evidence trust")).toBeInTheDocument();
    expect(
      screen.getByText("Yes. Ready-now recommendations still need an operator decision."),
    ).toBeInTheDocument();
    const decisivenessCellOne = screen.getByTestId("recommendation-decisiveness-rec-1");
    expect(decisivenessCellOne).toHaveTextContent("Ready now");
    expect(decisivenessCellOne).toHaveTextContent("Quick win");
    expect(decisivenessCellOne).toHaveTextContent("Blocked by operator review");
    expect(decisivenessCellOne).toHaveTextContent("Why now:");
    expect(decisivenessCellOne).not.toHaveTextContent("After action:");
    const recOneExpandButton = within(decisivenessCellOne).getByRole("button", { name: "View details" });
    expect(recOneExpandButton).toHaveAttribute("aria-expanded", "false");
    await user.click(recOneExpandButton);
    expect(within(decisivenessCellOne).getByRole("button", { name: "Hide details" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(decisivenessCellOne).toHaveTextContent("High-value next step");
    expect(decisivenessCellOne).toHaveTextContent("Best immediate move");
    expect(decisivenessCellOne).toHaveTextContent("Needs review / pending");
    expect(decisivenessCellOne).toHaveTextContent("Fresh enough to act");
    expect(decisivenessCellOne).toHaveTextContent("No refresh required before acting.");
    expect(decisivenessCellOne).toHaveTextContent("Blocked by operator review");
    expect(decisivenessCellOne).toHaveTextContent("After action:");
    expect(decisivenessCellOne).toHaveTextContent("Evidence:");
    expect(decisivenessCellOne).toHaveTextContent("Support cue:");
    expect(decisivenessCellOne).toHaveTextContent("Revisit:");
    expect(decisivenessCellOne).toHaveTextContent("operator review required");
    const decisivenessCellTwo = screen.getByTestId("recommendation-decisiveness-rec-2");
    expect(decisivenessCellTwo).toHaveTextContent("Ready now");
    expect(decisivenessCellTwo).toHaveTextContent("Quick win");
    expect(decisivenessCellTwo).toHaveTextContent("Blocked by operator review");
    expect(decisivenessCellTwo).not.toHaveTextContent("Needs review / pending");
    expect(decisivenessCellTwo).not.toHaveTextContent("Fresh enough to act");
    expect(
      screen.getByText(/Queue controls and recommendation details below show action history/i),
    ).toBeInTheDocument();

    await user.click(screen.getByLabelText("Select all displayed recommendations"));
    expect(screen.getByText("2 selected on this page")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Dismiss Selected" }));

    expect(getRecommendationRow("Recommendation One")).toHaveTextContent("dismissed");
    expect(getRecommendationRow("Recommendation Two")).toHaveTextContent("dismissed");

    await act(async () => {
      firstUpdate.resolve({
        ...recOne,
        status: "dismissed",
        updated_at: "2026-03-20T01:00:00Z",
      });
      secondUpdate.reject(
        new ApiRequestError("state invalid", {
          status: 422,
          detail: null,
        }),
      );
      await Promise.resolve();
    });

    await screen.findByText("Recommendation Two");
    expect(getRecommendationRow("Recommendation One")).toHaveTextContent("dismissed");
    expect(getRecommendationRow("Recommendation Two")).toHaveTextContent("open");
    expect(screen.getByText("1 selected on this page")).toBeInTheDocument();
    expect(screen.getAllByText("Updated 1 recommendation to dismissed.").length).toBeGreaterThan(0);
    expect(
      screen.getByText(
        "One or more recommendation updates are not allowed in the current state. 1 update failed.",
      ),
    ).toBeInTheDocument();
  });

  it("shows waiting/manual/deferred choice cues for accepted and dismissed recommendations", async () => {
    const accepted = createRecommendation("rec-21", "accepted", "high", "Accepted Recommendation");
    const dismissed = createRecommendation("rec-22", "dismissed", "low", "Dismissed Recommendation");
    mockFetchRecommendations.mockResolvedValueOnce(
      createListResponse(
        [accepted, dismissed],
        {
          total: 2,
          open: 0,
          accepted: 1,
          dismissed: 1,
          high_priority: 1,
        },
        2,
      ),
    );
    const user = userEvent.setup();

    render(<RecommendationsPage />);

    await screen.findByText("Accepted Recommendation");
    const acceptedDecisiveness = screen.getByTestId("recommendation-decisiveness-rec-21");
    expect(acceptedDecisiveness).toHaveTextContent("Manual follow-up required");
    expect(acceptedDecisiveness).toHaveTextContent("Quick win");
    expect(acceptedDecisiveness).not.toHaveTextContent("Applied / completed");
    await user.click(within(acceptedDecisiveness).getByRole("button", { name: "View details" }));
    expect(acceptedDecisiveness).toHaveTextContent("Waiting on visibility");
    expect(acceptedDecisiveness).toHaveTextContent("Applied / completed");
    expect(acceptedDecisiveness).toHaveTextContent("Pending refresh");
    expect(acceptedDecisiveness).toHaveTextContent("Revisit after visibility refresh");

    const dismissedDecisiveness = screen.getByTestId("recommendation-decisiveness-rec-22");
    expect(dismissedDecisiveness).toHaveTextContent("No immediate action");
    expect(dismissedDecisiveness).toHaveTextContent("Quick win");
    expect(dismissedDecisiveness).not.toHaveTextContent("No blocker");
    expect(dismissedDecisiveness).not.toHaveTextContent("Background item / revisit later");
    await user.click(within(dismissedDecisiveness).getByRole("button", { name: "View details" }));
    expect(dismissedDecisiveness).toHaveTextContent("Lower-immediacy background item");
    expect(dismissedDecisiveness).toHaveTextContent("Background item / revisit later");
    expect(dismissedDecisiveness).toHaveTextContent("Review soon");
    expect(dismissedDecisiveness).toHaveTextContent("Ignore for now unless context changes");
  });

  it("removes rows excluded by status filter and reconciles summary to backend truth after refresh", async () => {
    navigationState.searchParams = new URLSearchParams("status=open&page=1&page_size=25");
    const recOne = createRecommendation("rec-11", "open", "high", "Recommendation Eleven");
    const recTwo = createRecommendation("rec-12", "open", "medium", "Recommendation Twelve");
    const recThree = createRecommendation("rec-13", "open", "low", "Recommendation Thirteen");
    const refreshResponse = createDeferred<RecommendationListResponse>();

    mockFetchRecommendations
      .mockResolvedValueOnce(
        createListResponse([recOne, recTwo], {
          total: 2,
          open: 2,
          accepted: 0,
          dismissed: 0,
          high_priority: 1,
        }),
      )
      .mockImplementationOnce(() => refreshResponse.promise);

    const firstUpdate = createDeferred<Recommendation>();
    const secondUpdate = createDeferred<Recommendation>();
    mockUpdateRecommendationStatus
      .mockImplementationOnce(() => firstUpdate.promise)
      .mockImplementationOnce(() => secondUpdate.promise);

    const user = userEvent.setup();
    render(<RecommendationsPage />);

    await screen.findByText("Recommendation Eleven");
    await screen.findByText("Recommendation Twelve");
    await user.click(screen.getByLabelText("Select all displayed recommendations"));
    await user.click(screen.getByRole("button", { name: "Accept Selected" }));

    expect(screen.getByText("No recommendations match the current filters.")).toBeInTheDocument();
    expect(getSummaryValue("Total Filtered")).toBe("0");
    expect(getSummaryValue("Open")).toBe("0");
    expect(getSummaryValue("High Priority")).toBe("0");

    await act(async () => {
      firstUpdate.resolve({
        ...recOne,
        status: "accepted",
        updated_at: "2026-03-20T01:05:00Z",
      });
      secondUpdate.reject(
        new ApiRequestError("state invalid", {
          status: 422,
          detail: null,
        }),
      );
      await Promise.resolve();
    });

    await screen.findByText("Recommendation Twelve");
    expect(screen.queryByText("Recommendation Eleven")).not.toBeInTheDocument();
    expect(screen.getByText("1 selected on this page")).toBeInTheDocument();
    expect(getSummaryValue("Total Filtered")).toBe("1");
    expect(getSummaryValue("Open")).toBe("1");

    await act(async () => {
      refreshResponse.resolve(
        createListResponse(
          [recTwo, recThree],
          {
            total: 2,
            open: 2,
            accepted: 0,
            dismissed: 0,
            high_priority: 0,
          },
          2,
        ),
      );
      await Promise.resolve();
    });

    await screen.findByText("Recommendation Thirteen");
    expect(getSummaryValue("Total Filtered")).toBe("2");
    expect(getSummaryValue("Open")).toBe("2");
    expect(getSummaryValue("Accepted")).toBe("0");
  });

  it("preserves URL-backed queue context through bulk actions", async () => {
    navigationState.searchParams = new URLSearchParams("category=SEO&sort=oldest&page=3&page_size=50");
    const recFive = createRecommendation("rec-5", "open", "high", "Recommendation Five");
    mockFetchRecommendations
      .mockResolvedValueOnce(
        createListResponse(
          [recFive],
          {
            total: 150,
            open: 150,
            accepted: 0,
            dismissed: 0,
            high_priority: 60,
          },
          150,
        ),
      )
      .mockResolvedValueOnce(
        createListResponse(
          [{ ...recFive, status: "accepted", updated_at: "2026-03-20T03:00:00Z" }],
          {
            total: 150,
            open: 149,
            accepted: 1,
            dismissed: 0,
            high_priority: 60,
          },
          150,
        ),
      );
    mockUpdateRecommendationStatus.mockResolvedValueOnce({
      ...recFive,
      status: "accepted",
      updated_at: "2026-03-20T02:00:00Z",
    });

    const user = userEvent.setup();
    render(<RecommendationsPage />);

    await screen.findByText("Recommendation Five");
    const decisivenessCell = screen.getByTestId("recommendation-decisiveness-rec-5");
    expect(decisivenessCell).toHaveTextContent("Ready now");
    expect(decisivenessCell).toHaveTextContent("Quick win");
    expect(decisivenessCell).toHaveTextContent("Blocked by operator review");
    await user.click(screen.getByLabelText("Select recommendation rec-5"));
    await user.click(screen.getByRole("button", { name: "Accept Selected" }));

    await screen.findAllByText("Updated 1 recommendation to accepted.");
    await waitFor(() =>
      expect(mockFetchRecommendations).toHaveBeenLastCalledWith(
        "token-1",
        "biz-1",
        "site-1",
        expect.objectContaining({
          category: "SEO",
          sort_by: "created_at",
          sort_order: "asc",
          page: 3,
          page_size: 50,
        }),
      ),
    );
    expect(navigationState.push).not.toHaveBeenCalled();
    expect(navigationState.replace).not.toHaveBeenCalled();

    await user.click(screen.getByText("Recommendation Five"));
    expect(navigationState.push).toHaveBeenCalledWith(
      "/recommendations/rec-5?site_id=site-1&category=SEO&sort=oldest&page=3&page_size=50",
    );
  });
});
