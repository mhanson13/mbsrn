import { render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import userEvent from "@testing-library/user-event";

import RecommendationRunDetailPage from "./page";
import { ApiRequestError } from "../../../../lib/api/client";
import type {
  ActionLineageResponse,
  AutomationRunListResponse,
  Recommendation,
  RecommendationNarrative,
  RecommendationRun,
  RecommendationRunReport,
} from "../../../../lib/api/types";

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
  params: { run_id: "run-1" },
  searchParams: new URLSearchParams("site_id=site-1"),
};

const mockUseOperatorContext = jest.fn<OperatorContextMockValue, []>();
const mockFetchRecommendationRunReport = jest.fn<Promise<RecommendationRunReport>, unknown[]>();
const mockFetchLatestRecommendationRunNarrative = jest.fn<Promise<RecommendationNarrative>, unknown[]>();
const mockFetchAutomationRuns = jest.fn<Promise<AutomationRunListResponse>, unknown[]>();
const mockFetchCompetitorComparisonReport = jest.fn();
const mockBindActionExecutionItemAutomation = jest.fn<Promise<unknown>, unknown[]>();
const mockRunActionExecutionItemAutomation = jest.fn<Promise<unknown>, unknown[]>();

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
  useParams: () => navigationState.params,
  useSearchParams: () => navigationState.searchParams,
}));

jest.mock("../../../../components/useOperatorContext", () => ({
  useOperatorContext: () => mockUseOperatorContext(),
}));

jest.mock("../../../../lib/api/client", () => {
  const actual = jest.requireActual("../../../../lib/api/client");
  return {
    ...actual,
    fetchRecommendationRunReport: (...args: unknown[]) => mockFetchRecommendationRunReport(...args),
    fetchLatestRecommendationRunNarrative: (...args: unknown[]) =>
      mockFetchLatestRecommendationRunNarrative(...args),
    fetchAutomationRuns: (...args: unknown[]) => mockFetchAutomationRuns(...args),
    fetchCompetitorComparisonReport: (...args: unknown[]) => mockFetchCompetitorComparisonReport(...args),
    bindActionExecutionItemAutomation: (...args: unknown[]) =>
      mockBindActionExecutionItemAutomation(...args),
    runActionExecutionItemAutomation: (...args: unknown[]) =>
      mockRunActionExecutionItemAutomation(...args),
  };
});

function baseContext(overrides: Partial<OperatorContextMockValue> = {}): OperatorContextMockValue {
  return {
    loading: false,
    error: null,
    token: "token-1",
    businessId: "biz-1",
    sites: [{ id: "site-1", display_name: "Main Site" }],
    selectedSiteId: "site-1",
    setSelectedSiteId: jest.fn(),
    refreshSites: jest.fn(),
    ...overrides,
  };
}

function buildRecommendation(id: string, title: string): Recommendation {
  return {
    id,
    business_id: "biz-1",
    site_id: "site-1",
    recommendation_run_id: "run-1",
    audit_run_id: "audit-1",
    comparison_run_id: null,
    status: "open",
    category: "SEO",
    severity: "warning",
    priority_score: 80,
    priority_band: "high",
    effort_bucket: "small",
    title,
    rationale: `Rationale for ${title}`,
    eeat_categories: [],
    primary_eeat_category: null,
    decision_reason: null,
    created_at: "2026-03-21T10:00:00Z",
    updated_at: "2026-03-21T10:00:00Z",
  };
}

function buildRun(overrides: Partial<RecommendationRun> = {}): RecommendationRun {
  return {
    id: "run-1",
    business_id: "biz-1",
    site_id: "site-1",
    audit_run_id: "audit-1",
    comparison_run_id: null,
    status: "completed",
    total_recommendations: 2,
    critical_recommendations: 0,
    warning_recommendations: 2,
    info_recommendations: 0,
    category_counts_json: { SEO: 2 },
    effort_bucket_counts_json: { small: 2 },
    started_at: "2026-03-21T10:00:00Z",
    completed_at: "2026-03-21T10:05:00Z",
    duration_ms: 300000,
    error_summary: null,
    created_by_principal_id: "principal-1",
    created_at: "2026-03-21T09:59:00Z",
    updated_at: "2026-03-21T10:05:00Z",
    ...overrides,
  };
}

function buildRunReport(recommendations: Recommendation[] = [buildRecommendation("rec-1", "Recommendation One")]): RecommendationRunReport {
  return {
    recommendation_run: buildRun({
      total_recommendations: recommendations.length,
      warning_recommendations: recommendations.length,
    }),
    rollups: {
      by_category: { SEO: recommendations.length },
      by_severity: { warning: recommendations.length },
      by_effort_bucket: { small: recommendations.length },
    },
    recommendations: {
      items: recommendations,
      total: recommendations.length,
      by_status: { open: recommendations.length },
    },
  };
}

beforeEach(() => {
  jest.clearAllMocks();
  navigationState.params = { run_id: "run-1" };
  navigationState.searchParams = new URLSearchParams("site_id=site-1");
  mockUseOperatorContext.mockReturnValue(baseContext());
  mockFetchAutomationRuns.mockResolvedValue({ items: [], total: 0 });
  mockBindActionExecutionItemAutomation.mockReset();
  mockRunActionExecutionItemAutomation.mockReset();
  mockBindActionExecutionItemAutomation.mockResolvedValue({
    action_execution_item_id: "run-1",
    automation_binding_state: "bound",
    bound_automation_id: "automation-config-1",
    automation_bound_at: "2026-03-21T10:06:00Z",
    automation_ready: true,
    automation_template_key: "performance_check_followup",
  });
  mockRunActionExecutionItemAutomation.mockResolvedValue({
    action_execution_item_id: "run-1",
    automation_binding_state: "bound",
    bound_automation_id: "automation-config-1",
    automation_bound_at: "2026-03-21T10:06:00Z",
    automation_execution_state: "requested",
    automation_execution_requested_at: "2026-03-21T10:07:00Z",
    last_automation_run_id: "automation-run-4",
    automation_last_executed_at: null,
    automation_ready: true,
    automation_template_key: "performance_check_followup",
  });
});

describe("recommendation run detail page presentation", () => {
  it("renders shared support loading framing when tenant context is loading", () => {
    mockUseOperatorContext.mockReturnValue(baseContext({ loading: true }));

    render(<RecommendationRunDetailPage />);

    expect(screen.getByRole("heading", { name: "Recommendation Run Detail" })).toBeInTheDocument();
    expect(
      screen.getByText("Loading recommendation run detail for the selected business context."),
    ).toBeInTheDocument();
  });

  it("renders missing identifier support state when run id is absent", () => {
    navigationState.params = { run_id: "" };

    render(<RecommendationRunDetailPage />);

    expect(screen.getByRole("heading", { name: "Recommendation Run Detail" })).toBeInTheDocument();
    expect(screen.getByText("Recommendation run identifier is missing.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to Recommendations" })).toBeInTheDocument();
  });

  it("renders hero summary strip and no-narrative no-data state", async () => {
    mockFetchRecommendationRunReport.mockResolvedValueOnce(buildRunReport());
    mockFetchLatestRecommendationRunNarrative.mockRejectedValueOnce(
      new ApiRequestError("not found", { status: 404, detail: null }),
    );
    mockFetchAutomationRuns.mockResolvedValueOnce({
      items: [
        {
          id: "automation-run-1",
          business_id: "biz-1",
          site_id: "site-1",
          status: "completed",
          trigger_source: "scheduled",
          started_at: "2026-03-21T09:58:00Z",
          finished_at: "2026-03-21T10:00:00Z",
          error_message: null,
          steps_json: [
            {
              step_name: "recommendation_run",
              status: "completed",
              started_at: "2026-03-21T09:58:30Z",
              finished_at: "2026-03-21T09:59:10Z",
              linked_output_id: "run-1",
              error_message: null,
            },
          ],
        },
      ],
      total: 1,
    });

    render(<RecommendationRunDetailPage />);

    await screen.findByTestId("recommendation-run-detail-hero");
    expect(screen.getByTestId("recommendation-run-detail-summary-strip")).toBeInTheDocument();
    expect(screen.getByText("Run origin")).toBeInTheDocument();
    expect(screen.getByText("Operator action state")).toBeInTheDocument();
    expect(screen.getByText("Automation-triggered")).toBeInTheDocument();
    expect(screen.getAllByText("Automation output ready").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Automation run automation-run-1 (scheduled)").length).toBeGreaterThan(0);
    const actionControls = screen.getByTestId("recommendation-run-action-controls");
    expect(actionControls).toHaveTextContent("Review output");
    expect(actionControls).toHaveTextContent("Mark completed");
    expect(screen.getByTestId("recommendation-run-workflow-context")).toBeInTheDocument();
    const detailFocus = screen.getByTestId("recommendation-run-detail-focus");
    expect(detailFocus).toBeInTheDocument();
    expect(screen.getByText("Run outcome snapshot")).toBeInTheDocument();
    expect(screen.getByText("Action state")).toBeInTheDocument();
    expect(screen.getByText("Next step cue")).toBeInTheDocument();
    expect(screen.getByText("Why this matters now")).toBeInTheDocument();
    expect(screen.getByText("Can I act now")).toBeInTheDocument();
    expect(screen.getByText("Blocking state")).toBeInTheDocument();
    expect(screen.getByText("After action")).toBeInTheDocument();
    expect(screen.getByText("Evidence preview")).toBeInTheDocument();
    expect(screen.getByText("Evidence trust")).toBeInTheDocument();
    expect(screen.getByText("Lifecycle stage")).toBeInTheDocument();
    expect(screen.getByText("Revisit timing")).toBeInTheDocument();
    expect(screen.getByText("Freshness posture")).toBeInTheDocument();
    expect(screen.getByText("Refresh check")).toBeInTheDocument();
    expect(screen.getAllByText("Choice support").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Effort signal").length).toBeGreaterThan(0);
    expect(
      screen.getByText("Run produced actionable recommendations that should be reviewed now."),
    ).toBeInTheDocument();
    expect(screen.getByText("Support cue: operator review required")).toBeInTheDocument();
    expect(screen.getAllByText("Best immediate move").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Quick win").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Needs review / pending").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Fresh enough to act").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Revisit now.").length).toBeGreaterThan(0);
    expect(screen.getAllByText("No refresh required before acting.").length).toBeGreaterThan(0);
    expect(
      screen.getByText("Yes. Review recommendations and start with the highest-priority items."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Run produced 1 recommendation for operator review."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Yes. Review and apply high-priority recommendations."),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Run output is visible now; applied impact appears after the next analysis refresh.",
      ),
    ).toBeInTheDocument();
    const runContextHeading = screen.getByRole("heading", { name: "Run Context" });
    expect(detailFocus.compareDocumentPosition(runContextHeading) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByRole("link", { name: "Recommendation Queue" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Linked Automation Run" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Narrative History" })).toBeInTheDocument();
    expect(screen.getByText("Run status")).toBeInTheDocument();
    expect(screen.getByText("Recommendations")).toBeInTheDocument();
    expect(screen.getByText("Latest Narrative")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Choice support" })).toBeInTheDocument();
    expect(
      screen.getByText("No generated narrative is currently available for this recommendation run."),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Run Context" })).toBeInTheDocument();
  });

  it("renders content-to-update values in produced recommendations table", async () => {
    const recommendation = {
      ...buildRecommendation("rec-content-run-1", "Recommendation Content Target"),
      recommendation_target_content_types: [
        {
          type_key: "meta_title",
          label: "Meta title",
          source_type: "audit_signal",
          targeting_strength: "high",
        },
        {
          type_key: "meta_description",
          label: "Meta description",
          source_type: "audit_signal",
          targeting_strength: "high",
        },
      ],
      recommendation_target_content_summary: "Meta title and Meta description",
      action_plan: {
        action_steps: [
          {
            step_number: 1,
            title: "Update page title",
            instruction: "On /services, replace the page title with a clear service + location title.",
            target_type: "page",
            target_identifier: "/services",
            field: "title",
            before_example: "Home",
            after_example: "Flooring Services in Your Area | Trusted local support",
            confidence: 0.92,
          },
        ],
      },
    } satisfies Recommendation;

    mockFetchRecommendationRunReport.mockResolvedValueOnce(buildRunReport([recommendation]));
    mockFetchLatestRecommendationRunNarrative.mockRejectedValueOnce(
      new ApiRequestError("not found", { status: 404, detail: null }),
    );
    mockFetchAutomationRuns.mockResolvedValueOnce({ items: [], total: 0 });

    render(<RecommendationRunDetailPage />);

    await screen.findByRole("columnheader", { name: "Content to update" });
    expect(screen.getByRole("columnheader", { name: "How to implement" })).toBeInTheDocument();
    expect(screen.getByText("Meta title and Meta description")).toBeInTheDocument();
    expect(screen.getByTestId("recommendation-run-action-plan-rec-content-run-1")).toHaveTextContent(
      "Step 1:",
    );
    expect(screen.getByTestId("recommendation-run-action-plan-rec-content-run-1")).toHaveTextContent(
      "Update page title",
    );
  });

  it("captures local output-review decisions for run-level action control", async () => {
    const user = userEvent.setup();
    mockFetchRecommendationRunReport.mockResolvedValueOnce(buildRunReport());
    mockFetchLatestRecommendationRunNarrative.mockRejectedValueOnce(
      new ApiRequestError("not found", { status: 404, detail: null }),
    );
    mockFetchAutomationRuns.mockResolvedValueOnce({
      items: [
        {
          id: "automation-run-2",
          business_id: "biz-1",
          site_id: "site-1",
          status: "completed",
          trigger_source: "scheduled",
          started_at: "2026-03-21T09:58:00Z",
          finished_at: "2026-03-21T10:00:00Z",
          error_message: null,
          steps_json: [
            {
              step_name: "recommendation_run",
              status: "completed",
              started_at: "2026-03-21T09:58:30Z",
              finished_at: "2026-03-21T09:59:10Z",
              linked_output_id: "run-1",
              error_message: null,
            },
          ],
        },
      ],
      total: 1,
    });

    render(<RecommendationRunDetailPage />);

    const outputReview = await screen.findByTestId("recommendation-run-output-review");
    await user.click(within(outputReview).getByRole("button", { name: "Defer" }));

    expect(await screen.findByText("Decision captured: deferred")).toBeInTheDocument();
    expect(screen.getByTestId("recommendation-run-detail-summary-strip")).toHaveTextContent(
      "Recommendation-only review",
    );
    expect(screen.getByTestId("recommendation-run-detail-summary-strip")).toHaveTextContent(
      "Return later to review this output before acting.",
    );
    expect(screen.getByTestId("recommendation-run-output-review")).toHaveTextContent(
      "Automation output review deferred.",
    );
  });

  it("binds automation for an automation-ready activated run-level lineage action", async () => {
    const recommendationWithLineage = buildRecommendation("rec-lineage-1", "Lineage Recommendation");
    const actionLineage: ActionLineageResponse = {
      source_action_id: "rec-lineage-1",
      chained_drafts: [
        {
          id: "draft-lineage-1",
          source_action_id: "rec-lineage-1",
          action_type: "measure_performance",
          title: "Measure performance after rollout",
          description: "Track outcome after applying the recommendation.",
          draft_state: "pending",
          activation_state: "activated",
          activated_action_id: "activated-lineage-1",
          automation_ready: true,
          automation_template_key: "performance_check_followup",
          created_at: "2026-03-21T10:01:00Z",
        },
      ],
      activated_actions: [
        {
          id: "activated-lineage-1",
          source_draft_id: "draft-lineage-1",
          source_action_id: "rec-lineage-1",
          action_type: "measure_performance",
          title: "Measure performance after rollout",
          description: "Track outcome after applying the recommendation.",
          state: "pending",
          automation_ready: true,
          automation_template_key: "performance_check_followup",
          automation_binding_state: "unbound",
          bound_automation_id: null,
          automation_bound_at: null,
          created_at: "2026-03-21T10:02:00Z",
        },
      ],
      counts: {
        chained_draft_count: 1,
        activated_action_count: 1,
        automation_ready_count: 1,
      },
    };
    recommendationWithLineage.action_lineage = actionLineage;
    const user = userEvent.setup();
    mockFetchRecommendationRunReport.mockResolvedValueOnce(buildRunReport([recommendationWithLineage]));
    mockFetchLatestRecommendationRunNarrative.mockRejectedValueOnce(
      new ApiRequestError("not found", { status: 404, detail: null }),
    );
    mockFetchAutomationRuns.mockResolvedValueOnce({
      items: [
        {
          id: "automation-run-3",
          business_id: "biz-1",
          site_id: "site-1",
          automation_config_id: "automation-config-1",
          status: "completed",
          trigger_source: "scheduled",
          started_at: "2026-03-21T09:58:00Z",
          finished_at: "2026-03-21T10:00:00Z",
          error_message: null,
          steps_json: [
            {
              step_name: "recommendation_run",
              status: "completed",
              started_at: "2026-03-21T09:58:30Z",
              finished_at: "2026-03-21T09:59:10Z",
              linked_output_id: "run-1",
              error_message: null,
            },
          ],
        },
      ],
      total: 1,
    });

    render(<RecommendationRunDetailPage />);

    const outputReview = await screen.findByTestId("recommendation-run-output-review");
    await user.click(within(outputReview).getByRole("button", { name: "Bind automation" }));

    expect(mockBindActionExecutionItemAutomation).toHaveBeenCalledWith(
      "token-1",
      "biz-1",
      "site-1",
      "activated-lineage-1",
      "automation-config-1",
    );
  });

  it("requests automation execution for a bound activated run-level lineage action", async () => {
    const recommendationWithLineage = buildRecommendation("rec-lineage-2", "Lineage Run Recommendation");
    const actionLineage: ActionLineageResponse = {
      source_action_id: "rec-lineage-2",
      chained_drafts: [
        {
          id: "draft-lineage-2",
          source_action_id: "rec-lineage-2",
          action_type: "measure_performance",
          title: "Measure performance after rollout",
          description: "Track outcome after applying the recommendation.",
          draft_state: "pending",
          activation_state: "activated",
          activated_action_id: "activated-lineage-2",
          automation_ready: true,
          automation_template_key: "performance_check_followup",
          created_at: "2026-03-21T10:01:00Z",
        },
      ],
      activated_actions: [
        {
          id: "activated-lineage-2",
          source_draft_id: "draft-lineage-2",
          source_action_id: "rec-lineage-2",
          action_type: "measure_performance",
          title: "Measure performance after rollout",
          description: "Track outcome after applying the recommendation.",
          state: "pending",
          automation_ready: true,
          automation_template_key: "performance_check_followup",
          automation_binding_state: "bound",
          bound_automation_id: "automation-config-2",
          automation_bound_at: "2026-03-21T10:06:00Z",
          automation_execution_state: "not_requested",
          automation_execution_requested_at: null,
          last_automation_run_id: null,
          automation_last_executed_at: null,
          created_at: "2026-03-21T10:02:00Z",
        },
      ],
      counts: {
        chained_draft_count: 1,
        activated_action_count: 1,
        automation_ready_count: 1,
      },
    };
    recommendationWithLineage.action_lineage = actionLineage;

    const requestedRecommendation = {
      ...recommendationWithLineage,
      action_lineage: {
        ...actionLineage,
        activated_actions: [
          {
            ...actionLineage.activated_actions[0],
            automation_execution_state: "requested" as const,
            automation_execution_requested_at: "2026-03-21T10:07:00Z",
            last_automation_run_id: "automation-run-4",
          },
        ],
      },
    } satisfies Recommendation;

    const user = userEvent.setup();
    mockFetchRecommendationRunReport
      .mockResolvedValueOnce(buildRunReport([recommendationWithLineage]))
      .mockResolvedValueOnce(buildRunReport([requestedRecommendation]));
    mockFetchLatestRecommendationRunNarrative.mockRejectedValue(
      new ApiRequestError("not found", { status: 404, detail: null }),
    );
    mockFetchAutomationRuns.mockResolvedValue({
      items: [
        {
          id: "automation-run-4",
          business_id: "biz-1",
          site_id: "site-1",
          automation_config_id: "automation-config-2",
          status: "running",
          trigger_source: "manual",
          started_at: "2026-03-21T10:07:00Z",
          finished_at: null,
          error_message: null,
          steps_json: [],
          created_at: "2026-03-21T10:07:00Z",
          updated_at: "2026-03-21T10:07:00Z",
        },
      ],
      total: 1,
    });
    mockRunActionExecutionItemAutomation.mockResolvedValueOnce({
      action_execution_item_id: "activated-lineage-2",
      automation_binding_state: "bound",
      bound_automation_id: "automation-config-2",
      automation_bound_at: "2026-03-21T10:06:00Z",
      automation_execution_state: "requested",
      automation_execution_requested_at: "2026-03-21T10:07:00Z",
      last_automation_run_id: "automation-run-4",
      automation_last_executed_at: null,
      automation_ready: true,
      automation_template_key: "performance_check_followup",
    });

    render(<RecommendationRunDetailPage />);

    const outputReview = await screen.findByTestId("recommendation-run-output-review");
    await user.click(within(outputReview).getByRole("button", { name: "Run SEO automation" }));

    await waitFor(() =>
      expect(mockRunActionExecutionItemAutomation).toHaveBeenCalledWith(
        "token-1",
        "biz-1",
        "site-1",
        "activated-lineage-2",
      ),
    );
    expect(await screen.findByText("Execution requested")).toBeInTheDocument();
    expect(screen.getByTestId("recommendation-run-execution-polling-status")).toBeInTheDocument();
  });
});

