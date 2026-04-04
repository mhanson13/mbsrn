import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import RecommendationsPage from "./page";
import { ApiRequestError } from "../../lib/api/client";
import type {
  ActionLineageResponse,
  AutomationRunListResponse,
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
const mockFetchAutomationRuns = jest.fn<Promise<AutomationRunListResponse>, unknown[]>();
const mockUpdateRecommendationStatus = jest.fn<Promise<Recommendation>, unknown[]>();
const mockBindActionExecutionItemAutomation = jest.fn<Promise<unknown>, unknown[]>();
const mockRunActionExecutionItemAutomation = jest.fn<Promise<unknown>, unknown[]>();

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
    fetchAutomationRuns: (...args: unknown[]) => mockFetchAutomationRuns(...args),
    updateRecommendationStatus: (...args: unknown[]) => mockUpdateRecommendationStatus(...args),
    bindActionExecutionItemAutomation: (...args: unknown[]) =>
      mockBindActionExecutionItemAutomation(...args),
    runActionExecutionItemAutomation: (...args: unknown[]) =>
      mockRunActionExecutionItemAutomation(...args),
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
    priority_rationale: `Priority rationale for ${title}.`,
    evidence_strength:
      priorityBand === "critical" || priorityBand === "high"
        ? "strong"
        : priorityBand === "medium"
          ? "moderate"
          : "limited",
    why_now: `Why now for ${title}.`,
    next_action: `Open the target page and apply the first change for ${title}.`,
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
  mockFetchAutomationRuns.mockReset();
  mockUpdateRecommendationStatus.mockReset();
  mockBindActionExecutionItemAutomation.mockReset();
  mockRunActionExecutionItemAutomation.mockReset();
  mockBindActionExecutionItemAutomation.mockResolvedValue({
    action_execution_item_id: "activated-51",
    automation_binding_state: "bound",
    bound_automation_id: "automation-config-51",
    automation_bound_at: "2026-03-20T00:22:00Z",
    automation_ready: true,
    automation_template_key: "performance_check_followup",
  });
  mockRunActionExecutionItemAutomation.mockResolvedValue({
    action_execution_item_id: "activated-51",
    automation_binding_state: "bound",
    bound_automation_id: "automation-config-51",
    automation_bound_at: "2026-03-20T00:22:00Z",
    automation_execution_state: "requested",
    automation_execution_requested_at: "2026-03-20T00:23:00Z",
    last_automation_run_id: "automation-run-62",
    automation_last_executed_at: null,
    automation_ready: true,
    automation_template_key: "performance_check_followup",
  });
  mockUseOperatorContext.mockReset();
  navigationState.pathname = "/recommendations";
  navigationState.searchParams = new URLSearchParams();
  mockUseOperatorContext.mockReturnValue(baseOperatorContext());
  mockFetchAutomationRuns.mockResolvedValue({ items: [], total: 0 });
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
    expect(screen.queryByLabelText("Site")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Preset")).toHaveClass("operator-select");
    expect(screen.getByLabelText("Status")).toHaveClass("operator-select");
    expect(screen.getByLabelText("Priority")).toHaveClass("operator-select");
    expect(screen.getByLabelText("Category")).toHaveClass("operator-select");
    expect(screen.getByLabelText("Sort")).toHaveClass("operator-select");
    expect(screen.getByLabelText("Results per page")).toHaveClass("operator-select");
    const recommendationTable = screen.getByRole("table");
    const headerCells = within(recommendationTable)
      .getAllByRole("columnheader")
      .map((headerCell) => headerCell.textContent?.trim() || "");
    expect(headerCells).toEqual([
      "",
      "Priority",
      "Title",
      "Summary",
      "Status",
      "Decisiveness",
      "Category",
      "Source",
      "Recommendation Run",
    ]);
    expect(headerCells).not.toContain("Business");
    expect(headerCells).not.toContain("Site");
    expect(document.querySelector(".page-container-width-full")).toBeTruthy();
    expect(screen.getByTestId("recommendation-quick-scan")).toBeInTheDocument();
    const quickScanItem = screen.getByTestId("recommendation-quick-scan-item-rec-1");
    expect(quickScanItem).toHaveTextContent("Recommendation-only review");
    expect(quickScanItem).toHaveTextContent("Ready now");
    expect(quickScanItem).toHaveTextContent("Quick win");
    expect(quickScanItem).toHaveTextContent("Blocked by operator review");
    expect(quickScanItem).toHaveTextContent("No automation linkage detected");
    const quickScanControls = screen.getByTestId("recommendation-action-controls-rec-1");
    expect(quickScanControls).toHaveTextContent("Review recommendation");
    expect(quickScanControls).toHaveTextContent("Run SEO automation");
    const quickScanToggle = within(quickScanItem).getByRole("button", { name: "Show details" });
    expect(quickScanToggle).toHaveAttribute("aria-expanded", "false");
    await user.click(quickScanToggle);
    expect(within(quickScanItem).getByRole("button", { name: "Hide details" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(quickScanItem).toHaveTextContent("After action:");
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
    const decisivenessBadges = decisivenessCellOne.querySelectorAll(".badge");
    expect(decisivenessBadges.length).toBeGreaterThanOrEqual(3);
    decisivenessBadges.forEach((badge) => {
      expect(badge.textContent).toBeTruthy();
    });
    expect(decisivenessCellOne).toHaveTextContent("Ready now");
    expect(decisivenessCellOne).toHaveTextContent("Quick win");
    expect(decisivenessCellOne).toHaveTextContent("Blocked by operator review");
    expect(decisivenessCellOne).toHaveTextContent("Why now:");
    expect(decisivenessCellOne).toHaveTextContent("Why now for Recommendation One.");
    expect(decisivenessCellOne).not.toHaveTextContent("After action:");
    const recOneExpandButton = within(decisivenessCellOne).getByRole("button", { name: "View details" });
    expect(recOneExpandButton).toHaveAttribute("aria-expanded", "false");
    await user.click(recOneExpandButton);
    expect(within(decisivenessCellOne).getByRole("button", { name: "Hide details" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    const recOneDetailRow = screen.getByTestId("recommendation-decisiveness-detail-row-rec-1");
    const recOneDetailPanel = screen.getByTestId("recommendation-decisiveness-detail-panel-rec-1");
    const recOneExpandedControls = screen.getByTestId("recommendation-expanded-action-controls-rec-1");
    expect(recOneExpandedControls).toHaveTextContent("Review recommendation");
    expect(recOneExpandedControls).toHaveTextContent("Run SEO automation");
    expect(recOneDetailRow).toBeInTheDocument();
    expect(recOneDetailPanel.closest("td")).toHaveAttribute("colspan", "9");
    expect(recOneDetailPanel).toHaveTextContent("High-value next step");
    expect(recOneDetailPanel).toHaveTextContent("Best immediate move");
    expect(recOneDetailPanel).toHaveTextContent("Needs review / pending");
    expect(recOneDetailPanel).toHaveTextContent("Fresh enough to act");
    expect(recOneDetailPanel).toHaveTextContent("No refresh required before acting.");
    expect(recOneDetailPanel).toHaveTextContent("No blocker detected.");
    expect(recOneDetailPanel).toHaveTextContent("Action state:");
    expect(recOneDetailPanel).toHaveTextContent("Next step:");
    expect(recOneDetailPanel).toHaveTextContent(
      "Open the target page and apply the first change for Recommendation One.",
    );
    expect(recOneDetailPanel).toHaveTextContent("Priority rationale for Recommendation One.");
    expect(recOneDetailPanel).toHaveTextContent("Strong evidence");
    expect(screen.queryByTestId("recommendation-competitor-influence-rec-1")).not.toBeInTheDocument();
    expect(recOneDetailPanel).toHaveTextContent("After action:");
    expect(recOneDetailPanel).toHaveTextContent("Evidence:");
    expect(recOneDetailPanel).toHaveTextContent("Support cue:");
    expect(recOneDetailPanel).toHaveTextContent("Revisit:");
    expect(recOneDetailPanel).toHaveTextContent("operator review required");
    expect(screen.getByTestId("recommendation-automation-origin-rec-1")).toHaveTextContent(
      "No automation linkage detected",
    );
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
    expect(screen.getByTestId("bulk-action-progress")).toHaveTextContent("Processing 0/2");

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
    expect(screen.getAllByText("Bulk dismissed complete: 1/2 succeeded, 1 failed.").length).toBeGreaterThan(0);
    expect(
      screen.getByText(
        "One or more recommendation updates are not allowed in the current state. 1 update failed.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("recommendation-error-toast")).not.toBeInTheDocument();
    expect(document.querySelector(".page-container-has-toast")).toBeNull();
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
    const acceptedDetailPanel = screen.getByTestId("recommendation-decisiveness-detail-panel-rec-21");
    expect(acceptedDetailPanel).toHaveTextContent("Waiting on visibility");
    expect(acceptedDetailPanel).toHaveTextContent("Applied / completed");
    expect(acceptedDetailPanel).toHaveTextContent("Pending refresh");
    expect(acceptedDetailPanel).toHaveTextContent("Revisit after visibility refresh");

    const dismissedDecisiveness = screen.getByTestId("recommendation-decisiveness-rec-22");
    expect(dismissedDecisiveness).toHaveTextContent("No immediate action");
    expect(dismissedDecisiveness).toHaveTextContent("Quick win");
    expect(dismissedDecisiveness).not.toHaveTextContent("No blocker");
    expect(dismissedDecisiveness).not.toHaveTextContent("Background item / revisit later");
    await user.click(within(dismissedDecisiveness).getByRole("button", { name: "View details" }));
    const dismissedDetailPanel = screen.getByTestId("recommendation-decisiveness-detail-panel-rec-22");
    expect(dismissedDetailPanel).toHaveTextContent("Lower-immediacy background item");
    expect(dismissedDetailPanel).toHaveTextContent("Background item / revisit later");
    expect(dismissedDetailPanel).toHaveTextContent("Review soon");
    expect(dismissedDetailPanel).toHaveTextContent("Ignore for now unless context changes");
  });

  it("renders content-to-update cues when recommendation content targets are present", async () => {
    const recommendation = {
      ...createRecommendation("rec-content-1", "open", "high", "Content Target Recommendation"),
      recommendation_target_content_types: [
        {
          type_key: "heading_h1",
          label: "Main heading",
          source_type: "audit_signal",
          targeting_strength: "high",
        },
        {
          type_key: "intro_paragraph",
          label: "Intro paragraph",
          source_type: "audit_signal",
          targeting_strength: "medium",
        },
      ],
      recommendation_target_content_summary: "Main heading and Intro paragraph",
      action_plan: {
        action_steps: [
          {
            step_number: 1,
            title: "Improve main heading clarity",
            instruction: "On Homepage, add one clear top heading that states the service and location.",
            target_type: "content",
            target_identifier: "Homepage",
            field: "h1",
            before_example: "Welcome",
            after_example: "Flooring Installation in Your Area | Trusted local support",
            confidence: 0.92,
          },
          {
            step_number: 2,
            title: "Expand intro paragraph",
            instruction: "On Homepage, add a short opening paragraph that explains the service and who it helps.",
            target_type: "content",
            target_identifier: "Homepage",
            field: "intro_paragraph",
            before_example: null,
            after_example: "We provide flooring in your area with clear scope, timeline, and next steps.",
            confidence: 0.8,
          },
        ],
      },
    } satisfies Recommendation;
    mockFetchRecommendations.mockResolvedValueOnce(
      createListResponse(
        [recommendation],
        {
          total: 1,
          open: 1,
          accepted: 0,
          dismissed: 0,
          high_priority: 1,
        },
      ),
    );

    const user = userEvent.setup();
    render(<RecommendationsPage />);

    await screen.findByText("Content Target Recommendation");
    expect(screen.getByTestId("recommendation-summary-content-target-rec-content-1")).toHaveTextContent(
      "Content to update: Main heading and Intro paragraph",
    );

    const decisivenessCell = screen.getByTestId("recommendation-decisiveness-rec-content-1");
    await user.click(within(decisivenessCell).getByRole("button", { name: "View details" }));
    expect(screen.getByTestId("recommendation-expanded-content-target-rec-content-1")).toHaveTextContent(
      "Content to update: Main heading and Intro paragraph",
    );
    expect(screen.getByTestId("recommendation-expanded-action-plan-rec-content-1")).toHaveTextContent(
      "How to implement:",
    );
    expect(screen.getByTestId("recommendation-expanded-action-plan-rec-content-1")).toHaveTextContent(
      "Step 1: Improve main heading clarity",
    );
    expect(screen.getByTestId("recommendation-expanded-action-plan-rec-content-1")).toHaveTextContent(
      "Before: Welcome",
    );
    expect(screen.getByTestId("recommendation-expanded-action-plan-rec-content-1")).toHaveTextContent(
      "After: Flooring Installation in Your Area | Trusted local support",
    );

    const quickScanItem = screen.getByTestId("recommendation-quick-scan-item-rec-content-1");
    await user.click(within(quickScanItem).getByRole("button", { name: "Show details" }));
    expect(screen.getByTestId("recommendation-content-target-rec-content-1")).toHaveTextContent(
      "Content to update: Main heading and Intro paragraph",
    );
    expect(screen.getByTestId("recommendation-action-plan-rec-content-1")).toHaveTextContent(
      "How to implement:",
    );
  });

  it("renders competitor insight only in expanded recommendation details", async () => {
    const recommendation = {
      ...createRecommendation("rec-insight-1", "open", "high", "Strengthen location-targeted service copy"),
      competitor_influence_level: "meaningful",
      competitor_insight:
        "Competing sites include clearer location-targeted content for this topic. Closing this gap can improve parity when customers compare local options.",
    } satisfies Recommendation;
    mockFetchRecommendations.mockResolvedValueOnce(
      createListResponse(
        [recommendation],
        {
          total: 1,
          open: 1,
          accepted: 0,
          dismissed: 0,
          high_priority: 1,
        },
      ),
    );

    const user = userEvent.setup();
    render(<RecommendationsPage />);

    await screen.findByText("Strengthen location-targeted service copy");
    expect(screen.queryByTestId("recommendation-competitor-insight-rec-insight-1")).not.toBeInTheDocument();

    const decisivenessCell = screen.getByTestId("recommendation-decisiveness-rec-insight-1");
    await user.click(within(decisivenessCell).getByRole("button", { name: "View details" }));

    const insightLine = await screen.findByTestId("recommendation-competitor-insight-rec-insight-1");
    expect(insightLine).toHaveTextContent("Competitor insight:");
    expect(insightLine).toHaveTextContent("location-targeted content");
    const influenceLine = await screen.findByTestId("recommendation-competitor-influence-rec-insight-1");
    expect(influenceLine).toHaveTextContent("Competitor influence:");
    expect(influenceLine).toHaveTextContent("Meaningful influence");
  });

  it("renders execution-readiness guidance only in expanded recommendation details", async () => {
    const recommendation = {
      ...createRecommendation("rec-execution-1", "open", "high", "Clarify metadata for service pages"),
      execution_type: "metadata_update",
      execution_scope: "Update meta title and meta description on Homepage and /services.",
      execution_inputs: [
        "Target page list (for example: Homepage, /services)",
        "Current title/meta values on the target pages",
      ],
      execution_readiness: "needs_review",
      blocking_reason: "Target scope is partially specified. Confirm final page/content details before implementing.",
    } satisfies Recommendation;
    mockFetchRecommendations.mockResolvedValueOnce(
      createListResponse(
        [recommendation],
        {
          total: 1,
          open: 1,
          accepted: 0,
          dismissed: 0,
          high_priority: 1,
        },
      ),
    );

    const user = userEvent.setup();
    render(<RecommendationsPage />);

    await screen.findByText("Clarify metadata for service pages");
    expect(screen.queryByTestId("recommendation-expanded-execution-readiness-rec-execution-1")).not.toBeInTheDocument();
    expect(screen.queryByText("Execution readiness:")).not.toBeInTheDocument();

    const decisivenessCell = screen.getByTestId("recommendation-decisiveness-rec-execution-1");
    await user.click(within(decisivenessCell).getByRole("button", { name: "View details" }));

    expect(screen.getByTestId("recommendation-expanded-execution-readiness-rec-execution-1")).toHaveTextContent(
      "Execution readiness: Needs review",
    );
    expect(screen.getByTestId("recommendation-expanded-execution-type-rec-execution-1")).toHaveTextContent(
      "Execution type: Metadata update",
    );
    expect(screen.getByTestId("recommendation-expanded-execution-scope-rec-execution-1")).toHaveTextContent(
      "Execution scope: Update meta title and meta description",
    );
    expect(screen.getByTestId("recommendation-expanded-execution-inputs-rec-execution-1")).toHaveTextContent(
      "Execution inputs:",
    );
    expect(screen.getByTestId("recommendation-expanded-execution-blocking-rec-execution-1")).toHaveTextContent(
      "Execution blocker: Target scope is partially specified.",
    );
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

    await screen.findAllByText("Bulk accepted complete: 1/1 succeeded, 0 failed.");
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

  it("caps bulk mutation concurrency and reports queue progress", async () => {
    const recommendations = Array.from({ length: 6 }, (_, index) =>
      createRecommendation(`rec-bulk-${index + 1}`, "open", "high", `Bulk Recommendation ${index + 1}`),
    );
    mockFetchRecommendations
      .mockResolvedValueOnce(
        createListResponse(
          recommendations,
          {
            total: 6,
            open: 6,
            accepted: 0,
            dismissed: 0,
            high_priority: 6,
          },
          6,
        ),
      )
      .mockResolvedValueOnce(
        createListResponse(
          recommendations.map((item) => ({
            ...item,
            status: "accepted",
            updated_at: "2026-03-20T05:00:00Z",
          })),
          {
            total: 6,
            open: 0,
            accepted: 6,
            dismissed: 0,
            high_priority: 6,
          },
          6,
        ),
      );

    const deferredById = new Map<string, Deferred<Recommendation>>();
    let inFlightRequests = 0;
    let maxInFlightRequests = 0;
    mockUpdateRecommendationStatus.mockImplementation(
      (...args: unknown[]) => {
        const recommendationId = String(args[3] || "");
        const deferred = createDeferred<Recommendation>();
        deferredById.set(recommendationId, deferred);
        inFlightRequests += 1;
        maxInFlightRequests = Math.max(maxInFlightRequests, inFlightRequests);
        deferred.promise.finally(() => {
          inFlightRequests -= 1;
        });
        return deferred.promise;
      },
    );

    const user = userEvent.setup();
    render(<RecommendationsPage />);

    await screen.findByText("Bulk Recommendation 1");
    await user.click(screen.getByLabelText("Select all displayed recommendations"));
    await user.click(screen.getByRole("button", { name: "Accept Selected" }));

    await waitFor(() => {
      expect(mockUpdateRecommendationStatus).toHaveBeenCalledTimes(4);
    });
    expect(maxInFlightRequests).toBeLessThanOrEqual(4);
    expect(screen.getByTestId("bulk-action-progress")).toHaveTextContent("Processing 0/6");

    const firstCallRecommendationId = String(mockUpdateRecommendationStatus.mock.calls[0]?.[3] || "");
    const secondCallRecommendationId = String(mockUpdateRecommendationStatus.mock.calls[1]?.[3] || "");
    deferredById.get(firstCallRecommendationId)?.resolve({
      ...recommendations[0],
      status: "accepted",
      updated_at: "2026-03-20T05:00:01Z",
    });
    deferredById.delete(firstCallRecommendationId);
    await waitFor(() => {
      expect(mockUpdateRecommendationStatus).toHaveBeenCalledTimes(5);
    });
    deferredById.get(secondCallRecommendationId)?.resolve({
      ...recommendations[1],
      status: "accepted",
      updated_at: "2026-03-20T05:00:02Z",
    });
    deferredById.delete(secondCallRecommendationId);
    await waitFor(() => {
      expect(mockUpdateRecommendationStatus).toHaveBeenCalledTimes(6);
    });
    expect(screen.getByTestId("bulk-action-progress")).toHaveTextContent("Processing 2/6");

    const pendingRecommendationIds = mockUpdateRecommendationStatus.mock.calls
      .map((call) => String(call[3]))
      .filter((recommendationId) => deferredById.has(recommendationId));
    for (const recommendationId of pendingRecommendationIds) {
      const recommendation = recommendations.find((item) => item.id === recommendationId);
      if (!recommendation) {
        continue;
      }
      deferredById.get(recommendationId)?.resolve({
        ...recommendation,
        status: "accepted",
        updated_at: "2026-03-20T05:00:10Z",
      });
      deferredById.delete(recommendationId);
    }

    await screen.findAllByText("Bulk accepted complete: 6/6 succeeded, 0 failed.");
    expect(maxInFlightRequests).toBeLessThanOrEqual(4);
    expect(mockFetchRecommendations).toHaveBeenCalledTimes(2);
  });

  it("renders automation-triggered provenance cues when recommendation run linkage is present", async () => {
    const recOne = createRecommendation("rec-1", "open", "high", "Recommendation One");
    mockFetchRecommendations.mockResolvedValueOnce(
      createListResponse(
        [recOne],
        {
          total: 1,
          open: 1,
          accepted: 0,
          dismissed: 0,
          high_priority: 1,
        },
      ),
    );
    mockFetchAutomationRuns.mockResolvedValueOnce({
      items: [
        {
          id: "automation-run-1",
          business_id: "biz-1",
          site_id: "site-1",
          status: "completed",
          trigger_source: "scheduled",
          started_at: "2026-03-20T00:00:00Z",
          finished_at: "2026-03-20T00:01:00Z",
          error_message: null,
          steps_json: [
            {
              step_name: "recommendation_run",
              status: "completed",
              started_at: "2026-03-20T00:00:10Z",
              finished_at: "2026-03-20T00:00:40Z",
              linked_output_id: "rec-run-1",
              error_message: null,
            },
          ],
        },
      ],
      total: 1,
    });

    render(<RecommendationsPage />);

    await screen.findByText("Recommendation One");
    const quickScanItem = screen.getByTestId("recommendation-quick-scan-item-rec-1");
    expect(quickScanItem).toHaveTextContent("Automation-triggered output");
    expect(quickScanItem).toHaveTextContent("Automation output ready");
    const quickScanControls = screen.getByTestId("recommendation-action-controls-rec-1");
    expect(quickScanControls).toHaveTextContent("Review output");
    expect(quickScanControls).toHaveTextContent("Mark completed");
    expect(screen.getByTestId("recommendation-automation-origin-rec-1")).toHaveTextContent(
      "Automation-triggered output",
    );
  });

  it("captures deferred output-review decisions locally without backend mutation", async () => {
    const recOne = createRecommendation("rec-31", "open", "high", "Deferred Output Recommendation");
    mockFetchRecommendations.mockResolvedValueOnce(
      createListResponse(
        [recOne],
        {
          total: 1,
          open: 1,
          accepted: 0,
          dismissed: 0,
          high_priority: 1,
        },
      ),
    );
    mockFetchAutomationRuns.mockResolvedValueOnce({
      items: [
        {
          id: "automation-run-31",
          business_id: "biz-1",
          site_id: "site-1",
          status: "completed",
          trigger_source: "scheduled",
          started_at: "2026-03-20T00:00:00Z",
          finished_at: "2026-03-20T00:01:00Z",
          error_message: null,
          steps_json: [
            {
              step_name: "recommendation_run",
              status: "completed",
              started_at: "2026-03-20T00:00:10Z",
              finished_at: "2026-03-20T00:00:40Z",
              linked_output_id: "rec-run-1",
              error_message: null,
            },
          ],
        },
      ],
      total: 1,
    });

    const user = userEvent.setup();
    render(<RecommendationsPage />);

    const quickScanItem = await screen.findByTestId("recommendation-quick-scan-item-rec-31");
    await user.click(within(quickScanItem).getByRole("button", { name: "Show details" }));

    const outputReview = await screen.findByTestId("recommendation-output-review-rec-31");
    await user.click(within(outputReview).getByRole("button", { name: "Defer" }));

    expect(mockUpdateRecommendationStatus).not.toHaveBeenCalled();
    expect(await screen.findByText("Decision captured: deferred")).toBeInTheDocument();
    expect(screen.getByTestId("recommendation-quick-scan-item-rec-31")).toHaveTextContent("Recommendation-only review");
    expect(screen.getByTestId("recommendation-quick-scan-item-rec-31")).toHaveTextContent(
      "Automation output review deferred.",
    );
  });

  it("captures rejected output-review decisions and persists dismissed status", async () => {
    const recOne = createRecommendation("rec-41", "open", "high", "Rejected Output Recommendation");
    mockFetchRecommendations.mockResolvedValueOnce(
      createListResponse(
        [recOne],
        {
          total: 1,
          open: 1,
          accepted: 0,
          dismissed: 0,
          high_priority: 1,
        },
      ),
    );
    mockFetchAutomationRuns.mockResolvedValueOnce({
      items: [
        {
          id: "automation-run-41",
          business_id: "biz-1",
          site_id: "site-1",
          status: "completed",
          trigger_source: "scheduled",
          started_at: "2026-03-20T00:00:00Z",
          finished_at: "2026-03-20T00:01:00Z",
          error_message: null,
          steps_json: [
            {
              step_name: "recommendation_run",
              status: "completed",
              started_at: "2026-03-20T00:00:10Z",
              finished_at: "2026-03-20T00:00:40Z",
              linked_output_id: "rec-run-1",
              error_message: null,
            },
          ],
        },
      ],
      total: 1,
    });
    mockUpdateRecommendationStatus.mockResolvedValueOnce({
      ...recOne,
      status: "dismissed",
      updated_at: "2026-03-20T02:00:00Z",
    });

    const user = userEvent.setup();
    render(<RecommendationsPage />);

    const quickScanItem = await screen.findByTestId("recommendation-quick-scan-item-rec-41");
    await user.click(within(quickScanItem).getByRole("button", { name: "Show details" }));

    const outputReview = await screen.findByTestId("recommendation-output-review-rec-41");
    await user.click(within(outputReview).getByRole("button", { name: "Reject" }));

    await waitFor(() =>
      expect(mockUpdateRecommendationStatus).toHaveBeenCalledWith(
        "token-1",
        "biz-1",
        "site-1",
        "rec-41",
        { status: "dismissed" },
      ),
    );
    expect(await screen.findByText("Decision captured: rejected")).toBeInTheDocument();
    expect(screen.getByTestId("recommendation-quick-scan-item-rec-41")).toHaveTextContent("Blocked / unavailable");
    expect(screen.getByTestId("recommendation-quick-scan-item-rec-41")).toHaveTextContent("Automation output rejected.");
  });

  it("renders canonical next-step lineage from recommendation payload", async () => {
    const lineageRecommendation = createRecommendation("rec-51", "open", "high", "Lineage Recommendation");
    lineageRecommendation.recommendation_action_clarity = "Review this recommendation output with chained lineage context.";
    const lineage: ActionLineageResponse = {
      source_action_id: "rec-51",
      chained_drafts: [
        {
          id: "draft-51",
          source_action_id: "rec-51",
          action_type: "measure_performance",
          title: "Measure performance after optimization",
          description: "Validate post-change performance metrics.",
          draft_state: "pending",
          activation_state: "activated",
          activated_action_id: "activated-51",
          automation_ready: true,
          automation_template_key: "performance_check_followup",
          created_at: "2026-03-20T00:20:00Z",
        },
      ],
      activated_actions: [
        {
          id: "activated-51",
          source_draft_id: "draft-51",
          source_action_id: "rec-51",
          action_type: "measure_performance",
          title: "Measure performance after optimization",
          description: "Validate post-change performance metrics.",
          state: "pending",
          automation_ready: true,
          automation_template_key: "performance_check_followup",
          created_at: "2026-03-20T00:21:00Z",
        },
      ],
      counts: {
        chained_draft_count: 1,
        activated_action_count: 1,
        automation_ready_count: 1,
      },
    };
    lineageRecommendation.action_lineage = lineage;

    mockFetchRecommendations.mockResolvedValueOnce(
      createListResponse(
        [lineageRecommendation],
        {
          total: 1,
          open: 1,
          accepted: 0,
          dismissed: 0,
          high_priority: 1,
        },
      ),
    );
    mockFetchAutomationRuns.mockResolvedValueOnce({ items: [], total: 0 });

    const user = userEvent.setup();
    render(<RecommendationsPage />);

    const quickScanItem = await screen.findByTestId("recommendation-quick-scan-item-rec-51");
    await user.click(within(quickScanItem).getByRole("button", { name: "Show details" }));

    const outputReview = await screen.findByTestId("recommendation-output-review-rec-51");
    expect(outputReview).toHaveTextContent("Next-step lineage:");
    expect(outputReview).toHaveTextContent("Activated");
    expect(outputReview).toHaveTextContent("Automation-ready");
    expect(outputReview).toHaveTextContent("Linked action activated-51 is currently pending.");
    expect(outputReview).toHaveTextContent("Uses template: performance_check_followup");
  });

  it("binds automation for an automation-ready activated lineage action", async () => {
    const lineageRecommendation = createRecommendation("rec-61", "open", "high", "Lineage Bind Recommendation");
    lineageRecommendation.recommendation_action_clarity = "Bind automation for the activated next step.";
    const lineage: ActionLineageResponse = {
      source_action_id: "rec-61",
      chained_drafts: [
        {
          id: "draft-61",
          source_action_id: "rec-61",
          action_type: "measure_performance",
          title: "Measure performance after optimization",
          description: "Validate post-change performance metrics.",
          draft_state: "pending",
          activation_state: "activated",
          activated_action_id: "activated-51",
          automation_ready: true,
          automation_template_key: "performance_check_followup",
          created_at: "2026-03-20T00:20:00Z",
        },
      ],
      activated_actions: [
        {
          id: "activated-51",
          source_draft_id: "draft-61",
          source_action_id: "rec-61",
          action_type: "measure_performance",
          title: "Measure performance after optimization",
          description: "Validate post-change performance metrics.",
          state: "pending",
          automation_ready: true,
          automation_template_key: "performance_check_followup",
          automation_binding_state: "unbound",
          bound_automation_id: null,
          automation_bound_at: null,
          created_at: "2026-03-20T00:21:00Z",
        },
      ],
      counts: {
        chained_draft_count: 1,
        activated_action_count: 1,
        automation_ready_count: 1,
      },
    };
    lineageRecommendation.action_lineage = lineage;

    mockFetchRecommendations.mockResolvedValueOnce(
      createListResponse(
        [lineageRecommendation],
        {
          total: 1,
          open: 1,
          accepted: 0,
          dismissed: 0,
          high_priority: 1,
        },
      ),
    );
    mockFetchAutomationRuns.mockResolvedValueOnce({
      items: [
        {
          id: "automation-run-61",
          business_id: "biz-1",
          site_id: "site-1",
          automation_config_id: "automation-config-51",
          status: "completed",
          trigger_source: "manual",
          started_at: "2026-03-20T00:00:00Z",
          finished_at: "2026-03-20T00:00:30Z",
          error_message: null,
          steps_json: [],
          created_at: "2026-03-20T00:00:00Z",
          updated_at: "2026-03-20T00:00:30Z",
        },
      ],
      total: 1,
    });

    const user = userEvent.setup();
    render(<RecommendationsPage />);

    const quickScanItem = await screen.findByTestId("recommendation-quick-scan-item-rec-61");
    await user.click(within(quickScanItem).getByRole("button", { name: "Show details" }));

    const outputReview = await screen.findByTestId("recommendation-output-review-rec-61");
    await user.click(within(outputReview).getByRole("button", { name: "Bind automation" }));

    await waitFor(() =>
      expect(mockBindActionExecutionItemAutomation).toHaveBeenCalledWith(
        "token-1",
        "biz-1",
        "site-1",
        "activated-51",
        "automation-config-51",
      ),
    );
  });

  it("requests automation execution for a bound activated lineage action", async () => {
    const lineageRecommendation = createRecommendation("rec-62", "open", "high", "Lineage Run Recommendation");
    lineageRecommendation.recommendation_action_clarity = "Run automation for this activated next step.";
    const initialLineage: ActionLineageResponse = {
      source_action_id: "rec-62",
      chained_drafts: [
        {
          id: "draft-62",
          source_action_id: "rec-62",
          action_type: "measure_performance",
          title: "Measure performance after optimization",
          description: "Validate post-change performance metrics.",
          draft_state: "pending",
          activation_state: "activated",
          activated_action_id: "activated-62",
          automation_ready: true,
          automation_template_key: "performance_check_followup",
          created_at: "2026-03-20T00:20:00Z",
        },
      ],
      activated_actions: [
        {
          id: "activated-62",
          source_draft_id: "draft-62",
          source_action_id: "rec-62",
          action_type: "measure_performance",
          title: "Measure performance after optimization",
          description: "Validate post-change performance metrics.",
          state: "pending",
          automation_ready: true,
          automation_template_key: "performance_check_followup",
          automation_binding_state: "bound",
          bound_automation_id: "automation-config-62",
          automation_bound_at: "2026-03-20T00:22:00Z",
          automation_execution_state: "not_requested",
          automation_execution_requested_at: null,
          last_automation_run_id: null,
          automation_last_executed_at: null,
          created_at: "2026-03-20T00:21:00Z",
        },
      ],
      counts: {
        chained_draft_count: 1,
        activated_action_count: 1,
        automation_ready_count: 1,
      },
    };
    const initialRecommendation = {
      ...lineageRecommendation,
      action_lineage: initialLineage,
    } satisfies Recommendation;
    const requestedRecommendation = {
      ...initialRecommendation,
      action_lineage: {
        ...initialLineage,
        activated_actions: [
          {
            ...initialLineage.activated_actions[0],
            automation_execution_state: "requested" as const,
            automation_execution_requested_at: "2026-03-20T00:23:00Z",
            last_automation_run_id: "automation-run-62",
          },
        ],
      },
    } satisfies Recommendation;

    mockFetchRecommendations
      .mockResolvedValueOnce(
        createListResponse(
          [initialRecommendation],
          {
            total: 1,
            open: 1,
            accepted: 0,
            dismissed: 0,
            high_priority: 1,
          },
        ),
      )
      .mockResolvedValue(
        createListResponse(
          [requestedRecommendation],
          {
            total: 1,
            open: 1,
            accepted: 0,
            dismissed: 0,
            high_priority: 1,
          },
        ),
      );
    mockFetchAutomationRuns.mockResolvedValue({
      items: [
        {
          id: "automation-run-62",
          business_id: "biz-1",
          site_id: "site-1",
          automation_config_id: "automation-config-62",
          status: "running",
          trigger_source: "manual",
          started_at: "2026-03-20T00:23:00Z",
          finished_at: null,
          error_message: null,
          steps_json: [],
          created_at: "2026-03-20T00:23:00Z",
          updated_at: "2026-03-20T00:23:00Z",
        },
      ],
      total: 1,
    });
    mockRunActionExecutionItemAutomation.mockResolvedValueOnce({
      action_execution_item_id: "activated-62",
      automation_binding_state: "bound",
      bound_automation_id: "automation-config-62",
      automation_bound_at: "2026-03-20T00:22:00Z",
      automation_execution_state: "requested",
      automation_execution_requested_at: "2026-03-20T00:23:00Z",
      last_automation_run_id: "automation-run-62",
      automation_last_executed_at: null,
      automation_ready: true,
      automation_template_key: "performance_check_followup",
    });

    const user = userEvent.setup();
    render(<RecommendationsPage />);

    const quickScanItem = await screen.findByTestId("recommendation-quick-scan-item-rec-62");
    await user.click(within(quickScanItem).getByRole("button", { name: "Show details" }));

    const outputReview = await screen.findByTestId("recommendation-output-review-rec-62");
    await user.click(within(outputReview).getByRole("button", { name: "Run SEO automation" }));

    await waitFor(() =>
      expect(mockRunActionExecutionItemAutomation).toHaveBeenCalledWith(
        "token-1",
        "biz-1",
        "site-1",
        "activated-62",
      ),
    );
    expect(await screen.findByText("Execution requested")).toBeInTheDocument();
    expect(screen.getByText(/Automation run request is already in progress/i)).toBeInTheDocument();
    expect(screen.getByTestId("recommendation-execution-polling-status")).toBeInTheDocument();
  });

  it("renders failed execution status and failure signal from lineage payload", async () => {
    const lineageRecommendation = createRecommendation("rec-63", "open", "high", "Lineage Failure Recommendation");
    lineageRecommendation.recommendation_action_clarity = "Show failed automation output review feedback.";
    lineageRecommendation.action_lineage = {
      source_action_id: "rec-63",
      chained_drafts: [
        {
          id: "draft-63",
          source_action_id: "rec-63",
          action_type: "measure_performance",
          title: "Measure performance after optimization",
          description: "Validate post-change performance metrics.",
          draft_state: "pending",
          activation_state: "activated",
          activated_action_id: "activated-63",
          automation_ready: true,
          automation_template_key: "performance_check_followup",
          created_at: "2026-03-20T00:30:00Z",
        },
      ],
      activated_actions: [
        {
          id: "activated-63",
          source_draft_id: "draft-63",
          source_action_id: "rec-63",
          action_type: "measure_performance",
          title: "Measure performance after optimization",
          description: "Validate post-change performance metrics.",
          state: "pending",
          automation_ready: true,
          automation_template_key: "performance_check_followup",
          automation_binding_state: "bound",
          bound_automation_id: "automation-config-63",
          automation_bound_at: "2026-03-20T00:32:00Z",
          automation_execution_state: "failed",
          automation_execution_requested_at: "2026-03-20T00:33:00Z",
          last_automation_run_id: "automation-run-63",
          automation_last_executed_at: "2026-03-20T00:36:00Z",
          automation_run_status: "failed",
          automation_run_started_at: "2026-03-20T00:34:00Z",
          automation_run_completed_at: "2026-03-20T00:36:00Z",
          automation_run_error_summary: "Execution pipeline timed out.",
          created_at: "2026-03-20T00:31:00Z",
        },
      ],
      counts: {
        chained_draft_count: 1,
        activated_action_count: 1,
        automation_ready_count: 1,
      },
    };

    mockFetchRecommendations.mockResolvedValueOnce(
      createListResponse(
        [lineageRecommendation],
        {
          total: 1,
          open: 1,
          accepted: 0,
          dismissed: 0,
          high_priority: 1,
        },
      ),
    );
    mockFetchAutomationRuns.mockResolvedValue({ items: [], total: 0 });

    const user = userEvent.setup();
    render(<RecommendationsPage />);

    const quickScanItem = await screen.findByTestId("recommendation-quick-scan-item-rec-63");
    await user.click(within(quickScanItem).getByRole("button", { name: "Show details" }));

    const outputReview = await screen.findByTestId("recommendation-output-review-rec-63");
    expect(within(outputReview).getByText("Failed")).toBeInTheDocument();
    expect(within(outputReview).getByText("Failure signal: Execution pipeline timed out.")).toBeInTheDocument();
  });
});
