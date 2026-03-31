"use client";

import Link from "next/link";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { DetailFocusPanel, type DetailFocusFact } from "../../components/layout/DetailFocusPanel";
import { PageContainer } from "../../components/layout/PageContainer";
import { SectionCard } from "../../components/layout/SectionCard";
import { SectionHeader } from "../../components/layout/SectionHeader";
import { SummaryStatCard } from "../../components/layout/SummaryStatCard";
import { useOperatorContext } from "../../components/useOperatorContext";
import {
  ApiRequestError,
  fetchRecommendations,
  updateRecommendationStatus,
} from "../../lib/api/client";
import type {
  RecommendationFilteredSummary,
  Recommendation,
  RecommendationActionStatus,
  RecommendationListFilters,
  RecommendationListResponse,
} from "../../lib/api/types";

type FilterState = {
  status: "" | NonNullable<RecommendationListFilters["status"]>;
  priorityBand: "" | NonNullable<RecommendationListFilters["priority_band"]>;
  category: "" | NonNullable<RecommendationListFilters["category"]>;
};

type SortState = "priority_desc" | "priority_asc" | "newest" | "oldest";
type QueuePresetKey = "all_recommendations" | "open_high_priority" | "accepted" | "dismissed";
type QueuePresetSelection = QueuePresetKey | "__custom__";
type QueueSummary = {
  total: number;
  open: number;
  accepted: number;
  dismissed: number;
  highPriority: number;
};
type OptimisticBulkQueueState = {
  items: Recommendation[];
  totalRecommendations: number | null;
  queueSummary: QueueSummary;
};

const DEFAULT_FILTERS: FilterState = {
  status: "",
  priorityBand: "",
  category: "",
};

const DEFAULT_SORT: SortState = "priority_desc";
const DEFAULT_PAGE = 1;
const PAGE_SIZE_OPTIONS = [25, 50, 100] as const;
const DEFAULT_PAGE_SIZE = PAGE_SIZE_OPTIONS[0];
const EMPTY_QUEUE_SUMMARY: QueueSummary = {
  total: 0,
  open: 0,
  accepted: 0,
  dismissed: 0,
  highPriority: 0,
};

const SORT_OPTIONS: Array<{ label: string; value: SortState }> = [
  { label: "Priority: High to Low", value: "priority_desc" },
  { label: "Priority: Low to High", value: "priority_asc" },
  { label: "Newest First", value: "newest" },
  { label: "Oldest First", value: "oldest" },
];

const STATUS_FILTER_OPTIONS: Array<{ label: string; value: FilterState["status"] }> = [
  { label: "All statuses", value: "" },
  { label: "Open", value: "open" },
  { label: "In Progress", value: "in_progress" },
  { label: "Accepted", value: "accepted" },
  { label: "Dismissed", value: "dismissed" },
  { label: "Snoozed", value: "snoozed" },
  { label: "Resolved", value: "resolved" },
];

const PRIORITY_FILTER_OPTIONS: Array<{ label: string; value: FilterState["priorityBand"] }> = [
  { label: "All priorities", value: "" },
  { label: "Critical", value: "critical" },
  { label: "High", value: "high" },
  { label: "Medium", value: "medium" },
  { label: "Low", value: "low" },
];

const CATEGORY_FILTER_OPTIONS: Array<{ label: string; value: FilterState["category"] }> = [
  { label: "All categories", value: "" },
  { label: "SEO", value: "SEO" },
  { label: "Content", value: "CONTENT" },
  { label: "Structure", value: "STRUCTURE" },
  { label: "Technical", value: "TECHNICAL" },
];

const QUEUE_PRESETS: Array<{
  key: QueuePresetKey;
  label: string;
  filters: FilterState;
  sort: SortState;
}> = [
  {
    key: "all_recommendations",
    label: "All Recommendations",
    filters: DEFAULT_FILTERS,
    sort: DEFAULT_SORT,
  },
  {
    key: "open_high_priority",
    label: "Open High Priority",
    filters: {
      status: "open",
      priorityBand: "high",
      category: "",
    },
    sort: "priority_desc",
  },
  {
    key: "accepted",
    label: "Accepted",
    filters: {
      status: "accepted",
      priorityBand: "",
      category: "",
    },
    sort: "newest",
  },
  {
    key: "dismissed",
    label: "Dismissed",
    filters: {
      status: "dismissed",
      priorityBand: "",
      category: "",
    },
    sort: "newest",
  },
];

function parseStatusFilter(value: string | null): FilterState["status"] {
  if (!value) {
    return "";
  }
  const normalized = value.trim().toLowerCase();
  const allowedValues = new Set(STATUS_FILTER_OPTIONS.map((option) => option.value));
  if (!allowedValues.has(normalized as FilterState["status"])) {
    return "";
  }
  return normalized as FilterState["status"];
}

function parsePriorityFilter(value: string | null): FilterState["priorityBand"] {
  if (!value) {
    return "";
  }
  const normalized = value.trim().toLowerCase();
  const allowedValues = new Set(PRIORITY_FILTER_OPTIONS.map((option) => option.value));
  if (!allowedValues.has(normalized as FilterState["priorityBand"])) {
    return "";
  }
  return normalized as FilterState["priorityBand"];
}

function parseCategoryFilter(value: string | null): FilterState["category"] {
  if (!value) {
    return "";
  }
  const normalized = value.trim().toUpperCase();
  const allowedValues = new Set(CATEGORY_FILTER_OPTIONS.map((option) => option.value));
  if (!allowedValues.has(normalized as FilterState["category"])) {
    return "";
  }
  return normalized as FilterState["category"];
}

function parseSortOption(
  sortValue: string | null,
  sortByValue: string | null,
  sortOrderValue: string | null,
): SortState {
  const allowedSortValues = new Set(SORT_OPTIONS.map((option) => option.value));
  const normalizedSort = (sortValue || "").trim().toLowerCase();
  if (allowedSortValues.has(normalizedSort as SortState)) {
    return normalizedSort as SortState;
  }

  const sortBy = (sortByValue || "").trim().toLowerCase();
  const sortOrder = (sortOrderValue || "").trim().toLowerCase();
  if (sortBy === "created_at") {
    return sortOrder === "asc" ? "oldest" : "newest";
  }
  if (sortBy === "priority_score" && sortOrder === "asc") {
    return "priority_asc";
  }
  return DEFAULT_SORT;
}

function parsePage(value: string | null): number {
  if (!value) {
    return DEFAULT_PAGE;
  }
  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed) || parsed < DEFAULT_PAGE) {
    return DEFAULT_PAGE;
  }
  return parsed;
}

function parsePageSize(value: string | null): number {
  if (!value) {
    return DEFAULT_PAGE_SIZE;
  }
  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed)) {
    return DEFAULT_PAGE_SIZE;
  }
  if (!PAGE_SIZE_OPTIONS.includes(parsed as (typeof PAGE_SIZE_OPTIONS)[number])) {
    return DEFAULT_PAGE_SIZE;
  }
  return parsed;
}

function totalPagesFor(totalItems: number, pageSize: number): number {
  if (totalItems <= 0) {
    return 1;
  }
  return Math.ceil(totalItems / pageSize);
}

function mapSortToApi(sort: SortState): Pick<RecommendationListFilters, "sort_by" | "sort_order"> {
  if (sort === "newest") {
    return { sort_by: "created_at", sort_order: "desc" };
  }
  if (sort === "oldest") {
    return { sort_by: "created_at", sort_order: "asc" };
  }
  if (sort === "priority_asc") {
    return { sort_by: "priority_score", sort_order: "asc" };
  }
  return { sort_by: "priority_score", sort_order: "desc" };
}

function matchesPresetState(filters: FilterState, sort: SortState, preset: (typeof QUEUE_PRESETS)[number]): boolean {
  return (
    preset.sort === sort &&
    preset.filters.status === filters.status &&
    preset.filters.priorityBand === filters.priorityBand &&
    preset.filters.category === filters.category
  );
}

function deriveSourceType(item: Recommendation): string {
  if (item.audit_run_id && item.comparison_run_id) {
    return "mixed";
  }
  if (item.audit_run_id) {
    return "audit";
  }
  if (item.comparison_run_id) {
    return "comparison";
  }
  return "unknown";
}

function isHighPriority(item: Recommendation): boolean {
  return item.priority_band === "high" || item.priority_band === "critical";
}

function summarizeQueueFromItems(items: Recommendation[]): QueueSummary {
  return items.reduce(
    (summary, item) => {
      summary.total += 1;
      if (item.status === "open") {
        summary.open += 1;
      }
      if (item.status === "accepted") {
        summary.accepted += 1;
      }
      if (item.status === "dismissed") {
        summary.dismissed += 1;
      }
      if (isHighPriority(item)) {
        summary.highPriority += 1;
      }
      return summary;
    },
    { ...EMPTY_QUEUE_SUMMARY },
  );
}

function adjustSummaryStatusCount(summary: QueueSummary, status: string, delta: number): void {
  if (status === "open") {
    summary.open = Math.max(0, summary.open + delta);
    return;
  }
  if (status === "accepted") {
    summary.accepted = Math.max(0, summary.accepted + delta);
    return;
  }
  if (status === "dismissed") {
    summary.dismissed = Math.max(0, summary.dismissed + delta);
  }
}

function applyOptimisticBulkStatusToQueueState(params: {
  baselineItems: Recommendation[];
  baselineTotalRecommendations: number | null;
  baselineQueueSummary: QueueSummary;
  selectedItemIds: string[];
  nextStatus: RecommendationActionStatus;
  statusFilter: FilterState["status"];
}): OptimisticBulkQueueState {
  const {
    baselineItems,
    baselineTotalRecommendations,
    baselineQueueSummary,
    selectedItemIds,
    nextStatus,
    statusFilter,
  } = params;

  const selectedIdSet = new Set(selectedItemIds);
  let nextTotalRecommendations = baselineTotalRecommendations;
  const nextQueueSummary: QueueSummary = { ...baselineQueueSummary };
  const nextItems: Recommendation[] = [];

  for (const item of baselineItems) {
    if (!selectedIdSet.has(item.id)) {
      nextItems.push(item);
      continue;
    }

    const updatedItem: Recommendation = {
      ...item,
      status: nextStatus,
    };

    const remainsInFilteredView = !statusFilter || statusFilter === nextStatus;
    if (statusFilter && statusFilter !== nextStatus) {
      if (nextTotalRecommendations !== null) {
        nextTotalRecommendations = Math.max(0, nextTotalRecommendations - 1);
      }
      nextQueueSummary.total = Math.max(0, nextQueueSummary.total - 1);
      adjustSummaryStatusCount(nextQueueSummary, item.status, -1);
      if (isHighPriority(item)) {
        nextQueueSummary.highPriority = Math.max(0, nextQueueSummary.highPriority - 1);
      }
    } else if (item.status !== nextStatus) {
      adjustSummaryStatusCount(nextQueueSummary, item.status, -1);
      adjustSummaryStatusCount(nextQueueSummary, nextStatus, 1);
    }

    if (remainsInFilteredView) {
      nextItems.push(updatedItem);
    }
  }

  return {
    items: nextItems,
    totalRecommendations: nextTotalRecommendations,
    queueSummary: nextQueueSummary,
  };
}

function toQueueSummary(summary: RecommendationFilteredSummary | null | undefined): QueueSummary | null {
  if (!summary) {
    return null;
  }
  return {
    total: summary.total,
    open: summary.open,
    accepted: summary.accepted,
    dismissed: summary.dismissed,
    highPriority: summary.high_priority,
  };
}

function deriveQueueSummary(response: RecommendationListResponse): QueueSummary {
  const providedSummary = toQueueSummary(response.filtered_summary);
  if (providedSummary) {
    return providedSummary;
  }
  return summarizeQueueFromItems(response.items);
}

function safeRecommendationsErrorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) {
    if (error.status === 401) {
      return "Session expired. Sign in again.";
    }
    if (error.status === 403) {
      return "You are not authorized to view recommendations.";
    }
    if (error.status === 404) {
      return "Recommendation data for the selected site was not found.";
    }
  }
  return "Unable to load recommendations right now. Please try again.";
}

function safeBulkRecommendationErrorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) {
    if (error.status === 401) {
      return "Session expired. Sign in again.";
    }
    if (error.status === 403) {
      return "You are not authorized to update one or more recommendations.";
    }
    if (error.status === 404) {
      return "One or more recommendations were not found in your tenant scope.";
    }
    if (error.status === 422) {
      return "One or more recommendation updates are not allowed in the current state.";
    }
  }
  return "Unable to update one or more recommendations right now. Please try again.";
}

function RecommendationsPageContent() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const context = useOperatorContext();
  const [items, setItems] = useState<Recommendation[]>([]);
  const [totalRecommendations, setTotalRecommendations] = useState<number | null>(null);
  const [queueSummary, setQueueSummary] = useState<QueueSummary>(EMPTY_QUEUE_SUMMARY);
  const [loadingItems, setLoadingItems] = useState(false);
  const [itemsError, setItemsError] = useState<string | null>(null);
  const [selectedRecommendationIds, setSelectedRecommendationIds] = useState<string[]>([]);
  const [bulkActionInFlight, setBulkActionInFlight] = useState<RecommendationActionStatus | null>(null);
  const [bulkActionSuccess, setBulkActionSuccess] = useState<string | null>(null);
  const [bulkActionError, setBulkActionError] = useState<string | null>(null);
  const [bulkRefreshNonce, setBulkRefreshNonce] = useState(0);

  const filters = useMemo<FilterState>(() => {
    return {
      status: parseStatusFilter(searchParams.get("status")),
      priorityBand: parsePriorityFilter(searchParams.get("priority") || searchParams.get("priority_band")),
      category: parseCategoryFilter(searchParams.get("category")),
    };
  }, [searchParams]);
  const sort = useMemo<SortState>(() => {
    return parseSortOption(
      searchParams.get("sort"),
      searchParams.get("sort_by"),
      searchParams.get("sort_order"),
    );
  }, [searchParams]);
  const currentPage = useMemo<number>(() => parsePage(searchParams.get("page")), [searchParams]);
  const pageSize = useMemo<number>(() => parsePageSize(searchParams.get("page_size")), [searchParams]);
  const activePreset = useMemo<QueuePresetSelection>(() => {
    const matchedPreset = QUEUE_PRESETS.find((preset) => matchesPresetState(filters, sort, preset));
    return matchedPreset ? matchedPreset.key : "__custom__";
  }, [filters, sort]);
  const selectedSite = useMemo(
    () => context.sites.find((site) => site.id === context.selectedSiteId) || null,
    [context.selectedSiteId, context.sites],
  );

  const resolvedTotalRecommendations = totalRecommendations ?? 0;
  const totalPages = useMemo<number>(() => {
    if (totalRecommendations === null) {
      return currentPage;
    }
    return totalPagesFor(totalRecommendations, pageSize);
  }, [currentPage, pageSize, totalRecommendations]);
  const activePage = useMemo<number>(() => {
    if (totalRecommendations === null) {
      return currentPage;
    }
    return Math.min(currentPage, totalPages);
  }, [currentPage, totalPages, totalRecommendations]);
  const hasVisibleRows = resolvedTotalRecommendations > 0 && items.length > 0;
  const firstVisiblePosition = hasVisibleRows ? (activePage - DEFAULT_PAGE) * pageSize + 1 : 0;
  const lastVisiblePosition = hasVisibleRows ? firstVisiblePosition + items.length - 1 : 0;

  const hasActiveFilters = Boolean(filters.status || filters.priorityBand || filters.category);
  const displayedRecommendationIds = useMemo(() => items.map((item) => item.id), [items]);
  const displayedRecommendationIdSet = useMemo(() => new Set(displayedRecommendationIds), [displayedRecommendationIds]);
  const selectedCount = selectedRecommendationIds.length;
  const allDisplayedSelected =
    displayedRecommendationIds.length > 0 &&
    displayedRecommendationIds.every((id) => selectedRecommendationIds.includes(id));
  const buildRecommendationDetailHref = useCallback((item: Recommendation): string => {
    const params = new URLSearchParams();
    params.set("site_id", item.site_id);
    if (filters.status) {
      params.set("status", filters.status);
    }
    if (filters.priorityBand) {
      params.set("priority", filters.priorityBand);
    }
    if (filters.category) {
      params.set("category", filters.category);
    }
    if (sort !== DEFAULT_SORT) {
      params.set("sort", sort);
    }
    if (activePage > DEFAULT_PAGE) {
      params.set("page", String(activePage));
    }
    if (pageSize !== DEFAULT_PAGE_SIZE) {
      params.set("page_size", String(pageSize));
    }
    return `/recommendations/${item.id}?${params.toString()}`;
  }, [activePage, filters.category, filters.priorityBand, filters.status, pageSize, sort]);
  const topReadyRecommendation = useMemo(() => {
    const openItems = items.filter((item) => item.status === "open" || item.status === "in_progress");
    if (openItems.length === 0) {
      return null;
    }
    return [...openItems].sort((left, right) => {
      if (right.priority_score !== left.priority_score) {
        return right.priority_score - left.priority_score;
      }
      return right.created_at.localeCompare(left.created_at);
    })[0] || null;
  }, [items]);
  const recommendationQueueTakeaway = useMemo(() => {
    if (loadingItems) {
      return "Recommendation queue status is still loading.";
    }
    if (queueSummary.open > 0) {
      return `${queueSummary.open} recommendation${queueSummary.open === 1 ? "" : "s"} are ready for action now.`;
    }
    if (queueSummary.accepted > 0) {
      return `No ready-now items in this view; ${queueSummary.accepted} recommendation${queueSummary.accepted === 1 ? "" : "s"} are already applied/completed.`;
    }
    return "No immediate recommendation action is required for the current queue filters.";
  }, [loadingItems, queueSummary.accepted, queueSummary.open]);
  const recommendationQueueNextStep = useMemo(() => {
    if (topReadyRecommendation) {
      return {
        href: buildRecommendationDetailHref(topReadyRecommendation),
        label: "Open top ready recommendation",
        note: "Review what changed and confirm whether follow-up is still required.",
      };
    }
    if (queueSummary.accepted > 0 && items.length > 0) {
      return {
        href: buildRecommendationDetailHref(items[0]),
        label: "Review latest applied recommendation",
        note: "Confirm pending visibility timing and downstream follow-up.",
      };
    }
    return {
      href: "/sites",
      label: "Open site workspace",
      note: "Run or refresh recommendations when new analysis context is available.",
    };
  }, [buildRecommendationDetailHref, items, queueSummary.accepted, topReadyRecommendation]);
  const recommendationQueueFacts = useMemo<DetailFocusFact[]>(() => {
    if (loadingItems) {
      return [];
    }
    const manualFollowUpText = queueSummary.open > 0
      ? "Yes. Ready-now recommendations still need an operator decision."
      : queueSummary.accepted > 0
        ? "Yes. Validate accepted recommendation visibility after the next refresh."
        : "No immediate follow-up is required for the current view.";
    const visibilityTimingText = queueSummary.accepted > 0
      ? "Accepted items may need one refresh cycle before downstream visibility fully updates."
      : "Queue status updates immediately for this view.";

    return [
      {
        label: "Current status",
        value: queueSummary.open > 0 ? "Needs review / pending" : "Applied / completed",
        tone: queueSummary.open > 0 ? "warning" : "success",
      },
      {
        label: "What changed",
        value: bulkActionSuccess || "No recent queue status change in this session.",
        tone: bulkActionSuccess ? "success" : "neutral",
      },
      {
        label: "Manual follow-up",
        value: manualFollowUpText,
        tone: queueSummary.open > 0 || queueSummary.accepted > 0 ? "warning" : "neutral",
      },
      {
        label: "Expected visibility",
        value: visibilityTimingText,
        tone: queueSummary.accepted > 0 ? "warning" : "neutral",
      },
    ];
  }, [bulkActionSuccess, loadingItems, queueSummary.accepted, queueSummary.open]);

  function updateQueueParams(nextFilters: FilterState, nextSort: SortState) {
    const params = new URLSearchParams(searchParams.toString());
    if (nextFilters.status) {
      params.set("status", nextFilters.status);
    } else {
      params.delete("status");
    }
    if (nextFilters.priorityBand) {
      params.set("priority", nextFilters.priorityBand);
    } else {
      params.delete("priority");
    }
    params.delete("priority_band");
    if (nextFilters.category) {
      params.set("category", nextFilters.category);
    } else {
      params.delete("category");
    }
    if (nextSort === DEFAULT_SORT) {
      params.delete("sort");
    } else {
      params.set("sort", nextSort);
    }
    params.delete("preset");
    params.delete("sort_by");
    params.delete("sort_order");
    params.delete("page");
    const query = params.toString();
    router.push(query ? `${pathname}?${query}` : pathname, { scroll: false });
  }

  function updateFilterParams(nextFilters: FilterState) {
    updateQueueParams(nextFilters, sort);
  }

  function updateSortParam(nextSort: SortState) {
    updateQueueParams(filters, nextSort);
  }

  function applyPreset(presetKey: QueuePresetKey) {
    const preset = QUEUE_PRESETS.find((item) => item.key === presetKey);
    if (!preset) {
      return;
    }
    updateQueueParams(preset.filters, preset.sort);
  }

  function updatePaginationParams(nextPage: number, nextPageSize: number) {
    const params = new URLSearchParams(searchParams.toString());
    if (nextPage > DEFAULT_PAGE) {
      params.set("page", String(nextPage));
    } else {
      params.delete("page");
    }
    if (nextPageSize !== DEFAULT_PAGE_SIZE) {
      params.set("page_size", String(nextPageSize));
    } else {
      params.delete("page_size");
    }
    const query = params.toString();
    router.push(query ? `${pathname}?${query}` : pathname, { scroll: false });
  }

  function updatePageSizeParam(nextPageSize: number) {
    updatePaginationParams(DEFAULT_PAGE, nextPageSize);
  }

  function goToPage(nextPage: number) {
    const boundedPage = Math.min(Math.max(nextPage, DEFAULT_PAGE), totalPages);
    updatePaginationParams(boundedPage, pageSize);
  }

  function buildRecommendationRunDetailHref(item: Recommendation): string {
    const params = new URLSearchParams();
    params.set("site_id", item.site_id);
    if (filters.status) {
      params.set("status", filters.status);
    }
    if (filters.priorityBand) {
      params.set("priority", filters.priorityBand);
    }
    if (filters.category) {
      params.set("category", filters.category);
    }
    if (sort !== DEFAULT_SORT) {
      params.set("sort", sort);
    }
    if (activePage > DEFAULT_PAGE) {
      params.set("page", String(activePage));
    }
    if (pageSize !== DEFAULT_PAGE_SIZE) {
      params.set("page_size", String(pageSize));
    }
    return `/recommendations/runs/${item.recommendation_run_id}?${params.toString()}`;
  }

  function toggleRecommendationSelection(recommendationId: string) {
    setSelectedRecommendationIds((current) => {
      if (current.includes(recommendationId)) {
        return current.filter((value) => value !== recommendationId);
      }
      return [...current, recommendationId];
    });
  }

  function toggleSelectAllDisplayed(checked: boolean) {
    if (checked) {
      setSelectedRecommendationIds(displayedRecommendationIds);
      return;
    }
    setSelectedRecommendationIds([]);
  }

  async function handleBulkStatusUpdate(status: RecommendationActionStatus) {
    if (!context.selectedSiteId || selectedRecommendationIds.length === 0 || bulkActionInFlight) {
      return;
    }

    const selectedItems = items.filter((item) => selectedRecommendationIds.includes(item.id));
    if (selectedItems.length === 0) {
      return;
    }
    const selectedItemIds = selectedItems.map((item) => item.id);
    const statusFilter = filters.status;
    const baselineItems = items;
    const baselineQueueSummary = queueSummary;
    const baselineTotalRecommendations = totalRecommendations;
    const optimisticState = applyOptimisticBulkStatusToQueueState({
      baselineItems,
      baselineTotalRecommendations,
      baselineQueueSummary,
      selectedItemIds,
      nextStatus: status,
      statusFilter,
    });

    setBulkActionInFlight(status);
    setBulkActionSuccess(null);
    setBulkActionError(null);
    setItems(optimisticState.items);
    setTotalRecommendations(optimisticState.totalRecommendations);
    setQueueSummary(optimisticState.queueSummary);
    setSelectedRecommendationIds([]);

    try {
      const results = await Promise.allSettled(
        selectedItems.map((item) =>
          updateRecommendationStatus(context.token, context.businessId, item.site_id, item.id, { status }),
        ),
      );
      const successfulItems: Recommendation[] = [];
      const successfulItemIds: string[] = [];
      const failedItems: Recommendation[] = [];
      const failedErrors: unknown[] = [];
      results.forEach((result, index) => {
        const selectedItem = selectedItems[index];
        if (!selectedItem) {
          return;
        }
        if (result.status === "fulfilled") {
          successfulItems.push(result.value);
          successfulItemIds.push(selectedItem.id);
          return;
        }
        failedItems.push(selectedItem);
        failedErrors.push(result.reason);
      });

      const successfulCount = successfulItems.length;
      const failedCount = failedItems.length;
      const reconciledState = applyOptimisticBulkStatusToQueueState({
        baselineItems,
        baselineTotalRecommendations,
        baselineQueueSummary,
        selectedItemIds: successfulItemIds,
        nextStatus: status,
        statusFilter,
      });
      const successfulItemById = new Map(successfulItems.map((item) => [item.id, item]));
      const reconciledItems = reconciledState.items.map((item) => successfulItemById.get(item.id) || item);

      setItems(reconciledItems);
      setTotalRecommendations(reconciledState.totalRecommendations);
      setQueueSummary(reconciledState.queueSummary);

      if (successfulCount > 0) {
        setBulkActionSuccess(
          `Updated ${successfulCount} recommendation${successfulCount === 1 ? "" : "s"} to ${status}.`,
        );
        setBulkRefreshNonce((current) => current + 1);
      }

      if (failedCount > 0) {
        const firstError = failedErrors[0];
        const baseErrorMessage = safeBulkRecommendationErrorMessage(firstError ?? null);
        setBulkActionError(
          `${baseErrorMessage} ${failedCount} update${failedCount === 1 ? "" : "s"} failed.`,
        );
        const failedIdSet = new Set(failedItems.map((item) => item.id));
        setSelectedRecommendationIds(reconciledItems.filter((item) => failedIdSet.has(item.id)).map((item) => item.id));
      }
    } finally {
      setBulkActionInFlight(null);
    }
  }

  useEffect(() => {
    if (totalRecommendations === null || currentPage === activePage) {
      return;
    }
    const params = new URLSearchParams(searchParams.toString());
    if (activePage > DEFAULT_PAGE) {
      params.set("page", String(activePage));
    } else {
      params.delete("page");
    }
    if (pageSize !== DEFAULT_PAGE_SIZE) {
      params.set("page_size", String(pageSize));
    } else {
      params.delete("page_size");
    }
    const query = params.toString();
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
  }, [activePage, currentPage, pageSize, pathname, router, searchParams, totalRecommendations]);

  useEffect(() => {
    setSelectedRecommendationIds((current) => current.filter((id) => displayedRecommendationIdSet.has(id)));
  }, [displayedRecommendationIdSet]);

  useEffect(() => {
    if (context.loading || context.error || !context.selectedSiteId) {
      setItems([]);
      setTotalRecommendations(null);
      setQueueSummary(EMPTY_QUEUE_SUMMARY);
      setItemsError(null);
      setLoadingItems(false);
      setSelectedRecommendationIds([]);
      setBulkActionInFlight(null);
      setBulkActionSuccess(null);
      setBulkActionError(null);
      return;
    }
    let cancelled = false;
    const selectedSiteId = context.selectedSiteId;

    async function loadRecommendations() {
      setLoadingItems(true);
      setItemsError(null);
      try {
        const activeFilters: RecommendationListFilters = {};
        if (filters.status) {
          activeFilters.status = filters.status;
        }
        if (filters.priorityBand) {
          activeFilters.priority_band = filters.priorityBand;
        }
        if (filters.category) {
          activeFilters.category = filters.category;
        }
        const sortConfig = mapSortToApi(sort);
        activeFilters.sort_by = sortConfig.sort_by;
        activeFilters.sort_order = sortConfig.sort_order;
        activeFilters.page = currentPage;
        activeFilters.page_size = pageSize;
        const response = await fetchRecommendations(context.token, context.businessId, selectedSiteId, activeFilters);
        if (!cancelled) {
          setItems(response.items);
          setTotalRecommendations(response.total);
          setQueueSummary(deriveQueueSummary(response));
        }
      } catch (err) {
        if (!cancelled) {
          setItemsError(safeRecommendationsErrorMessage(err));
          setQueueSummary(EMPTY_QUEUE_SUMMARY);
        }
      } finally {
        if (!cancelled) {
          setLoadingItems(false);
        }
      }
    }
    void loadRecommendations();
    return () => {
      cancelled = true;
    };
  }, [
    context.businessId,
    context.error,
    context.loading,
    context.selectedSiteId,
    context.token,
    filters.status,
    filters.priorityBand,
    filters.category,
    sort,
    currentPage,
    pageSize,
    bulkRefreshNonce,
  ]);

  if (context.loading) {
    return (
      <PageContainer>
        <SectionCard as="div" variant="support" className="role-surface-support">
          <SectionHeader
            title="Recommendation Workflow"
            subtitle="Loading recommendation queue state for your selected site."
            headingLevel={1}
            variant="support"
          />
        </SectionCard>
      </PageContainer>
    );
  }
  if (context.error) {
    return (
      <PageContainer>
        <SectionCard as="div" variant="support" className="role-surface-support">
          <SectionHeader
            title="Recommendation Workflow"
            subtitle="Unable to load tenant context. Refresh and sign in again."
            headingLevel={1}
            variant="support"
          />
        </SectionCard>
      </PageContainer>
    );
  }
  if (context.sites.length === 0) {
    return (
      <PageContainer>
        <SectionCard variant="support" className="role-surface-support">
          <SectionHeader
            title="Recommendation Workflow"
            subtitle="No SEO sites are configured yet. Add a site first to view recommendations."
            headingLevel={1}
            variant="support"
          />
        </SectionCard>
      </PageContainer>
    );
  }

  return (
    <PageContainer>
      <div className="role-dashboard-landing">
        <SectionCard variant="primary" className="role-dashboard-hero">
          <SectionHeader
            title="Recommendation Workflow"
            subtitle="Review priorities, update recommendation status, and keep action flow moving."
            headingLevel={1}
            variant="hero"
            meta={(
              <span className="hint muted">
                Selected site: <code>{selectedSite?.display_name || context.selectedSiteId || "none"}</code>
              </span>
            )}
          />
          <div className="workspace-summary-strip role-summary-strip">
            <SummaryStatCard
              label="Filtered recommendations"
              value={queueSummary.total}
              detail={hasActiveFilters ? "Current filter set" : "All statuses"}
              tone={queueSummary.total > 0 ? "neutral" : "warning"}
              variant="elevated"
            />
            <SummaryStatCard
              label="Ready now"
              value={queueSummary.open}
              detail="Open recommendations awaiting action"
              tone={queueSummary.open > 0 ? "success" : "neutral"}
              variant="elevated"
            />
            <SummaryStatCard
              label="Applied / completed"
              value={queueSummary.accepted}
              detail="Accepted recommendations in current view"
              tone={queueSummary.accepted > 0 ? "success" : "neutral"}
              variant="elevated"
            />
            <SummaryStatCard
              label="High priority"
              value={queueSummary.highPriority}
              detail="High or critical priorities in current view"
              tone={queueSummary.highPriority > 0 ? "warning" : "neutral"}
              variant="elevated"
            />
          </div>
        </SectionCard>
      </div>

      <DetailFocusPanel
        data-testid="recommendation-queue-outcome-focus"
        title="Recommendation outcome snapshot"
        takeaway={recommendationQueueTakeaway}
        nextStep={recommendationQueueNextStep}
        facts={recommendationQueueFacts}
        detailHint="Queue controls and recommendation details below show action history, rationale, and lineage."
      />

      <SectionCard variant="summary" className="role-surface-support">
        <SectionHeader
          title="Recommendation queue"
          subtitle="Filter, sort, batch update, and open recommendation details."
          headingLevel={2}
          variant="support"
        />
        <label htmlFor="site-picker-recommendations">Site</label>
        <select
          id="site-picker-recommendations"
          value={context.selectedSiteId || ""}
          onChange={(event) => context.setSelectedSiteId(event.target.value)}
        >
          {context.sites.map((site) => (
            <option key={site.id} value={site.id}>
              {site.display_name}
            </option>
          ))}
        </select>

        <div className="grid-fit-180">
          <div className="stack-tight">
          <label htmlFor="recommendation-preset">Preset</label>
          <select
            id="recommendation-preset"
            value={activePreset}
            onChange={(event) => {
              const selectedValue = event.target.value as QueuePresetSelection;
              if (selectedValue !== "__custom__") {
                applyPreset(selectedValue);
              }
            }}
          >
            <option value="__custom__">Custom View</option>
            {QUEUE_PRESETS.map((preset) => (
              <option key={preset.key} value={preset.key}>
                {preset.label}
              </option>
            ))}
          </select>
          </div>
          <div className="stack-tight">
          <label htmlFor="recommendation-filter-status">Status</label>
          <select
            id="recommendation-filter-status"
            value={filters.status}
            onChange={(event) =>
              updateFilterParams({
                ...filters,
                status: event.target.value as FilterState["status"],
              })
            }
          >
            {STATUS_FILTER_OPTIONS.map((option) => (
              <option key={option.label} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          </div>
          <div className="stack-tight">
          <label htmlFor="recommendation-filter-priority">Priority</label>
          <select
            id="recommendation-filter-priority"
            value={filters.priorityBand}
            onChange={(event) =>
              updateFilterParams({
                ...filters,
                priorityBand: event.target.value as FilterState["priorityBand"],
              })
            }
          >
            {PRIORITY_FILTER_OPTIONS.map((option) => (
              <option key={option.label} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          </div>
          <div className="stack-tight">
          <label htmlFor="recommendation-filter-category">Category</label>
          <select
            id="recommendation-filter-category"
            value={filters.category}
            onChange={(event) =>
              updateFilterParams({
                ...filters,
                category: event.target.value as FilterState["category"],
              })
            }
          >
            {CATEGORY_FILTER_OPTIONS.map((option) => (
              <option key={option.label} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          </div>
          <div className="stack-tight">
          <label htmlFor="recommendation-sort">Sort</label>
          <select
            id="recommendation-sort"
            value={sort}
            onChange={(event) => updateSortParam(event.target.value as SortState)}
          >
            {SORT_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          </div>
          <button
            type="button"
            className="button button-secondary"
            onClick={() => updateFilterParams(DEFAULT_FILTERS)}
            disabled={loadingItems || !hasActiveFilters}
          >
            Clear Filters
          </button>
        </div>

        <div className="grid-fit-120">
          <div className="panel stack panel-metric stack-micro">
          <span className="hint muted">Total Filtered</span>
          <strong>{queueSummary.total}</strong>
          </div>
          <div className="panel stack panel-metric stack-micro">
          <span className="hint muted">Open</span>
          <strong>{queueSummary.open}</strong>
          </div>
          <div className="panel stack panel-metric stack-micro">
          <span className="hint muted">Accepted</span>
          <strong>{queueSummary.accepted}</strong>
          </div>
          <div className="panel stack panel-metric stack-micro">
          <span className="hint muted">Dismissed</span>
          <strong>{queueSummary.dismissed}</strong>
          </div>
          <div className="panel stack panel-metric stack-micro">
          <span className="hint muted">High Priority</span>
          <strong>{queueSummary.highPriority}</strong>
          </div>
        </div>
        <p className="hint muted">Summary cards reflect all filtered results across pages.</p>

        <div className="row-wrap-end">
          <div className="stack-tight min-width-140">
          <label htmlFor="recommendation-page-size">Results per page</label>
          <select
            id="recommendation-page-size"
            value={pageSize}
            onChange={(event) => updatePageSizeParam(Number.parseInt(event.target.value, 10))}
          >
            {PAGE_SIZE_OPTIONS.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
          </div>
          <div className="row-wrap-tight">
          <button
            type="button"
            className="button button-secondary button-inline"
            onClick={() => goToPage(activePage - 1)}
            disabled={loadingItems || activePage <= DEFAULT_PAGE}
          >
            Previous
          </button>
          <span className="hint muted">
            Page {activePage} of {totalPages}
          </span>
          <button
            type="button"
            className="button button-secondary button-inline"
            onClick={() => goToPage(activePage + 1)}
            disabled={loadingItems || activePage >= totalPages}
          >
            Next
          </button>
          </div>
          <span className="hint muted push-right">
          Showing {firstVisiblePosition}-{lastVisiblePosition} of {resolvedTotalRecommendations}
          </span>
        </div>

        {loadingItems ? <p className="hint muted">Loading recommendations...</p> : null}
        {itemsError ? <p className="hint error">{itemsError}</p> : null}
        {bulkActionSuccess ? <p className="hint">{bulkActionSuccess}</p> : null}
        {bulkActionError ? <p className="hint error">{bulkActionError}</p> : null}

        <div className="row-wrap-tight">
          <button
            type="button"
            className="button button-primary"
            disabled={selectedCount === 0 || bulkActionInFlight !== null}
            onClick={() => {
              void handleBulkStatusUpdate("accepted");
            }}
          >
            {bulkActionInFlight === "accepted" ? "Applying..." : "Accept Selected"}
          </button>
          <button
            type="button"
            className="button button-secondary"
            disabled={selectedCount === 0 || bulkActionInFlight !== null}
            onClick={() => {
              void handleBulkStatusUpdate("dismissed");
            }}
          >
            {bulkActionInFlight === "dismissed" ? "Applying..." : "Dismiss Selected"}
          </button>
          <span className="hint muted">{selectedCount} selected on this page</span>
        </div>

        <div className="table-container">
          <table className="table">
            <thead>
              <tr>
                <th>
                  <input
                    type="checkbox"
                    aria-label="Select all displayed recommendations"
                    checked={allDisplayedSelected}
                    onChange={(event) => toggleSelectAllDisplayed(event.target.checked)}
                    disabled={items.length === 0 || bulkActionInFlight !== null}
                  />
                </th>
                <th>Title</th>
                <th>Summary</th>
                <th>Status</th>
                <th>Category</th>
                <th>Priority</th>
                <th>Source</th>
                <th>Recommendation Run</th>
                <th>Business</th>
                <th>Site</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr
                  key={item.id}
                  role="link"
                  tabIndex={0}
                  className="clickable-row"
                  onClick={() => router.push(buildRecommendationDetailHref(item))}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      router.push(buildRecommendationDetailHref(item));
                    }
                  }}
                >
                  <td>
                    <input
                      type="checkbox"
                      aria-label={`Select recommendation ${item.id}`}
                      checked={selectedRecommendationIds.includes(item.id)}
                      disabled={bulkActionInFlight !== null}
                      onClick={(event) => event.stopPropagation()}
                      onKeyDown={(event) => event.stopPropagation()}
                      onChange={() => toggleRecommendationSelection(item.id)}
                    />
                  </td>
                  <td>{item.title}</td>
                  <td>{item.rationale}</td>
                  <td>{item.status}</td>
                  <td>{item.category}</td>
                  <td>
                    {item.priority_score} ({item.priority_band})
                  </td>
                  <td>{deriveSourceType(item)}</td>
                  <td>
                    <Link
                      href={buildRecommendationRunDetailHref(item)}
                      onClick={(event) => event.stopPropagation()}
                      onKeyDown={(event) => event.stopPropagation()}
                    >
                      <code>{item.recommendation_run_id}</code>
                    </Link>
                  </td>
                  <td>{item.business_id}</td>
                  <td>{item.site_id}</td>
                </tr>
              ))}
              {items.length === 0 && !loadingItems ? (
                <tr>
                  <td colSpan={10}>
                    {hasActiveFilters
                      ? "No recommendations match the current filters."
                      : "No recommendations found for this site."}
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </SectionCard>
    </PageContainer>
  );
}

export default function RecommendationsPage() {
  return (
    <Suspense
      fallback={
        <PageContainer>
          <SectionCard as="div" variant="support" className="role-surface-support">
            <SectionHeader
              title="Recommendation Workflow"
              subtitle="Loading recommendation queue state for your selected site."
              headingLevel={1}
              variant="support"
            />
          </SectionCard>
        </PageContainer>
      }
    >
      <RecommendationsPageContent />
    </Suspense>
  );
}
