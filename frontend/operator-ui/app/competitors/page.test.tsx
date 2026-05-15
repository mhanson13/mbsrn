import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";

import CompetitorsPage from "./page";
import type {
  CompetitorDomainFeedback,
  CompetitorProfileGenerationRunDetailResponse,
  ReviewedCompetitorListResponse,
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

const navigationState = {
  searchParams: new URLSearchParams(),
};

const mockUseOperatorContext = jest.fn<OperatorContextMockValue, []>();
const mockFetchReviewedCompetitorList = jest.fn<Promise<ReviewedCompetitorListResponse>, unknown[]>();
const mockCreateCompetitorProfileGenerationRun = jest.fn<
  Promise<CompetitorProfileGenerationRunDetailResponse>,
  unknown[]
>();
const mockUpsertCompetitorDomainFeedback = jest.fn<Promise<CompetitorDomainFeedback>, unknown[]>();
const mockCreateCompetitorDomainManualSeed = jest.fn<Promise<CompetitorDomainFeedback>, unknown[]>();

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
  useSearchParams: () => navigationState.searchParams,
}));

jest.mock("../../components/useOperatorContext", () => ({
  useOperatorContext: () => mockUseOperatorContext(),
}));

jest.mock("../../lib/api/client", () => {
  const actual = jest.requireActual("../../lib/api/client");
  return {
    ...actual,
    fetchReviewedCompetitorList: (...args: unknown[]) => mockFetchReviewedCompetitorList(...args),
    createCompetitorProfileGenerationRun: (...args: unknown[]) => mockCreateCompetitorProfileGenerationRun(...args),
    upsertCompetitorDomainFeedback: (...args: unknown[]) => mockUpsertCompetitorDomainFeedback(...args),
    createCompetitorDomainManualSeed: (...args: unknown[]) => mockCreateCompetitorDomainManualSeed(...args),
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

function buildReviewedResponse(overrides: Partial<ReviewedCompetitorListResponse> = {}): ReviewedCompetitorListResponse {
  return {
    business_id: "biz-1",
    site_id: "site-1",
    summary: {
      total: 2,
      accepted_useful: 1,
      needs_review: 1,
      excluded: 0,
      manual_seeds: 1,
      last_suggestion_status: "completed",
    },
    latest_suggestion: {
      run_id: "run-1",
      run_status: "completed",
      local_seeds_considered: 1,
      suggestions_returned: 4,
      added_to_review_list: 2,
      already_known: 1,
      rejected_by_quality_gate: 1,
      excluded_by_operator_feedback: 0,
      failure_reason: null,
    },
    quality_summary: {
      status: "partial",
      operator_message: "Competitor snapshot is partial. Some candidates were excluded.",
      total_candidates_returned: 4,
      accepted_candidates: 2,
      rejected_candidates: 2,
      final_active_domains_count: 2,
      top_reason: "insufficient_candidates",
      reason_counts: {
        valid: 2,
        insufficient_candidates: 1,
      },
    },
    diagnostics: {
      competitor_set_count: 2,
      active_set_count: 1,
      latest_snapshot_run: {
        id: "snapshot-1",
        status: "completed",
        competitor_set_id: "set-1",
        competitor_set_name: "Front Range",
        created_at: "2026-05-14T00:00:00Z",
        updated_at: "2026-05-14T00:01:00Z",
        completed_at: "2026-05-14T00:01:00Z",
      },
      latest_comparison_run: {
        id: "comparison-1",
        status: "completed",
        competitor_set_id: "set-1",
        competitor_set_name: "Front Range",
        created_at: "2026-05-14T00:02:00Z",
        updated_at: "2026-05-14T00:03:00Z",
        completed_at: "2026-05-14T00:03:00Z",
      },
    },
    items: [
      {
        domain: "alpha.example",
        display_name: "Alpha",
        review_state: "useful",
        provenance: "existing",
        confidence_score: 0.78,
        reason_selected: "Strong local overlap.",
        is_synthetic: false,
        is_excluded: false,
        is_accepted_or_useful: true,
        updated_at: "2026-05-14T00:03:00Z",
        operator_note: null,
        source_set_id: "set-1",
        source_generation_run_id: null,
      },
      {
        domain: "beta.example",
        display_name: "Beta",
        review_state: "generated_suggestion",
        provenance: "ai_suggested",
        confidence_score: 0.61,
        reason_selected: "Competes in overlapping services.",
        is_synthetic: false,
        is_excluded: false,
        is_accepted_or_useful: false,
        updated_at: "2026-05-14T00:04:00Z",
        operator_note: null,
        source_set_id: null,
        source_generation_run_id: "run-1",
      },
    ],
    ...overrides,
  };
}

beforeEach(() => {
  jest.clearAllMocks();
  navigationState.searchParams = new URLSearchParams();
  mockUseOperatorContext.mockReturnValue(baseOperatorContext());
  mockFetchReviewedCompetitorList.mockResolvedValue(buildReviewedResponse());
  mockCreateCompetitorProfileGenerationRun.mockResolvedValue({
    run: {
      id: "run-2",
      business_id: "biz-1",
      site_id: "site-1",
      status: "queued",
      requested_candidate_count: 10,
      generated_draft_count: 0,
      provider_name: "openai",
      model_name: "gpt-5",
      prompt_version: "v1",
      failure_category: null,
      error_summary: null,
      completed_at: null,
      created_by_principal_id: "principal-1",
      created_at: "2026-05-14T00:05:00Z",
      updated_at: "2026-05-14T00:05:00Z",
    },
    drafts: [],
    total_drafts: 0,
  });
  mockUpsertCompetitorDomainFeedback.mockResolvedValue({
    id: "feedback-1",
    business_id: "biz-1",
    site_id: "site-1",
    domain: "beta.example",
    feedback_status: "useful",
    display_name: "Beta",
    operator_note: null,
    created_by_principal_id: "principal-1",
    updated_by_principal_id: "principal-1",
    created_at: "2026-05-14T00:05:00Z",
    updated_at: "2026-05-14T00:05:00Z",
  });
  mockCreateCompetitorDomainManualSeed.mockResolvedValue({
    id: "feedback-2",
    business_id: "biz-1",
    site_id: "site-1",
    domain: "seeded.example",
    feedback_status: "manually_seeded",
    display_name: "Seeded",
    operator_note: null,
    created_by_principal_id: "principal-1",
    updated_by_principal_id: "principal-1",
    created_at: "2026-05-14T00:05:00Z",
    updated_at: "2026-05-14T00:05:00Z",
  });
});

describe("competitors page list-first workflow", () => {
  it("renders a reviewed-list-first heading, summary metrics, and row actions", async () => {
    render(<CompetitorsPage />);

    expect(await screen.findByRole("heading", { name: "Competitors" })).toBeInTheDocument();
    expect(screen.getByText("AI can suggest competitors, but humans choose who counts.")).toBeInTheDocument();
    expect(screen.getByText("Total")).toBeInTheDocument();
    expect(screen.getByText("Accepted/useful")).toBeInTheDocument();
    expect(screen.getByText("Needs review")).toBeInTheDocument();
    expect(screen.getByText("Excluded")).toBeInTheDocument();
    expect(screen.getAllByText("Manual seeds").length).toBeGreaterThan(0);
    expect(screen.getByText("Last suggestion")).toBeInTheDocument();
    expect(screen.queryByText("Snapshot status")).not.toBeInTheDocument();
    expect(screen.queryByText("Comparison status")).not.toBeInTheDocument();

    expect(screen.getByTestId("competitors-admin-governance-hint")).toHaveTextContent(
      "Suggestions use Admin-configured relevance, local alignment, exclusion, timeout, and prompt-governance rules.",
    );
    expect(screen.getByText("Reviewed competitor list")).toBeInTheDocument();
    expect(screen.getByText("alpha.example")).toBeInTheDocument();
    expect(screen.getByText("beta.example")).toBeInTheDocument();
    expect(screen.getAllByText("Mark accepted/useful").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Mark not useful").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Exclude").length).toBeGreaterThan(0);
  });

  it("renders advanced diagnostics as a secondary disclosure", async () => {
    render(<CompetitorsPage />);

    expect(await screen.findByTestId("competitors-advanced-diagnostics")).toBeInTheDocument();
    expect(screen.getByText("Advanced diagnostics")).toBeInTheDocument();
    expect(screen.getByText("Show advanced diagnostics")).toBeInTheDocument();
  });

  it("starts competitor suggestions, shows lifecycle feedback, and refetches list data", async () => {
    render(<CompetitorsPage />);
    const user = userEvent.setup();

    await screen.findByText("Reviewed competitor list");
    await user.click(screen.getByTestId("competitors-generate-set-button"));

    expect(mockCreateCompetitorProfileGenerationRun).toHaveBeenCalledWith("token-1", "biz-1", "site-1", {});
    expect(await screen.findByTestId("competitors-generation-success")).toHaveTextContent(
      "Competitor suggestion started (run run-2, queued).",
    );
    await waitFor(() => {
      expect(mockFetchReviewedCompetitorList).toHaveBeenCalledTimes(2);
    });
  });

  it("submits feedback actions and shows bounded success", async () => {
    render(<CompetitorsPage />);
    const user = userEvent.setup();

    await screen.findByText("beta.example");
    await user.click(screen.getAllByText("Mark not useful")[0]);

    expect(mockUpsertCompetitorDomainFeedback).toHaveBeenCalledWith(
      "token-1",
      "biz-1",
      "site-1",
      {
        domain: "alpha.example",
        feedback_status: "not_useful",
        display_name: "Alpha",
      },
    );
    expect(await screen.findByTestId("competitors-feedback-success")).toHaveTextContent(
      "Saved feedback for beta.example: Useful.",
    );
  });

  it("submits manual seed and refreshes the reviewed list", async () => {
    render(<CompetitorsPage />);
    const user = userEvent.setup();

    await screen.findByTestId("competitors-manual-seed-form");
    await user.type(screen.getByTestId("competitors-manual-seed-domain-input"), "seeded.example");
    await user.type(screen.getByTestId("competitors-manual-seed-display-name-input"), "Seeded Competitor");
    await user.click(screen.getByTestId("competitors-manual-seed-submit"));

    expect(mockCreateCompetitorDomainManualSeed).toHaveBeenCalledWith(
      "token-1",
      "biz-1",
      "site-1",
      {
        domain: "seeded.example",
        display_name: "Seeded Competitor",
        operator_note: null,
      },
    );
    expect(await screen.findByTestId("competitors-feedback-success")).toHaveTextContent(
      "Manual seed saved for seeded.example.",
    );
  });

  it("keeps legacy/synthetic rows out of accepted/useful counts", async () => {
    mockFetchReviewedCompetitorList.mockResolvedValueOnce(
      buildReviewedResponse({
        summary: {
          total: 1,
          accepted_useful: 0,
          needs_review: 0,
          excluded: 0,
          manual_seeds: 0,
          last_suggestion_status: "completed",
        },
        items: [
          {
            domain: "review-scaffold-1.invalid",
            display_name: "Review Scaffold",
            review_state: "legacy_synthetic",
            provenance: "legacy",
            confidence_score: null,
            reason_selected: null,
            is_synthetic: true,
            is_excluded: false,
            is_accepted_or_useful: false,
            updated_at: "2026-05-14T00:05:00Z",
            operator_note: null,
            source_set_id: null,
            source_generation_run_id: "run-1",
          },
        ],
      }),
    );

    render(<CompetitorsPage />);

    expect(await screen.findByText("review-scaffold-1.invalid")).toBeInTheDocument();
    expect(screen.getByText("Legacy/synthetic")).toBeInTheDocument();
    expect(screen.getByText("Accepted/useful").closest(".summary-stat-card")).toHaveTextContent("0");
    expect(screen.getByText("Exclude")).toBeInTheDocument();
  });
});
