import type {
  Recommendation,
  RecommendationEEATCategory,
  RecommendationEEATGapSummary,
  RecommendationNarrative,
  RecommendationNarrativeSignalSummary,
  RecommendationOrderingExplanation,
  RecommendationPriorityReason,
  RecommendationTargetContext,
  RecommendationTheme,
  RecommendationThemeGroup,
} from "../../../lib/api/types";

// Pure recommendation-domain helpers only. Keep orchestration/state ownership in page containers.
function truncateOptionalText(value: string | null | undefined, limit: number): string | null {
  if (!value) {
    return null;
  }
  const collapsed = value.replace(/\s+/g, " ").trim();
  if (!collapsed) {
    return null;
  }
  if (collapsed.length <= limit) {
    return collapsed;
  }
  return `${collapsed.slice(0, Math.max(0, limit - 1))}…`;
}

export function normalizeBoundedStringList(
  values: string[] | null | undefined,
  limit: number,
  itemLimit: number,
): string[] {
  if (!Array.isArray(values) || limit <= 0) {
    return [];
  }
  const result: string[] = [];
  const seen = new Set<string>();
  for (const value of values) {
    if (typeof value !== "string") {
      continue;
    }
    const normalized = value.replace(/\s+/g, " ").trim();
    if (!normalized) {
      continue;
    }
    const bounded = normalized.length <= itemLimit ? normalized : `${normalized.slice(0, itemLimit - 1)}…`;
    const dedupeKey = bounded.toLowerCase();
    if (seen.has(dedupeKey)) {
      continue;
    }
    result.push(bounded);
    seen.add(dedupeKey);
    if (result.length >= limit) {
      break;
    }
  }
  return result;
}

export function recommendationImpactLabel(
  item: Recommendation,
  index: number,
): "HIGH IMPACT" | "QUICK WIN" | "NEEDS REVIEW" | null {
  if (index === 0) {
    return "HIGH IMPACT";
  }
  if (index === 1) {
    if (item.effort_bucket === "small" && item.status === "open") {
      return "QUICK WIN";
    }
    if (!["accepted", "dismissed", "resolved"].includes(item.status)) {
      return "NEEDS REVIEW";
    }
  }
  return null;
}

export function recommendationImpactBadgeClass(
  label: ReturnType<typeof recommendationImpactLabel>,
): string {
  switch (label) {
    case "HIGH IMPACT":
      return "badge badge-error";
    case "QUICK WIN":
      return "badge badge-success";
    case "NEEDS REVIEW":
      return "badge badge-warn";
    default:
      return "badge badge-muted";
  }
}

const EEAT_CATEGORY_ORDER: RecommendationEEATCategory[] = [
  "experience",
  "expertise",
  "authoritativeness",
  "trustworthiness",
];

export function formatEEATCategory(category: RecommendationEEATCategory): string {
  switch (category) {
    case "experience":
      return "Experience";
    case "expertise":
      return "Expertise";
    case "authoritativeness":
      return "Authoritativeness";
    case "trustworthiness":
      return "Trustworthiness";
    default:
      return category;
  }
}

export function normalizeEEATCategories(
  categories: RecommendationEEATCategory[] | null | undefined,
  limit = 4,
): RecommendationEEATCategory[] {
  if (!Array.isArray(categories) || limit <= 0) {
    return [];
  }
  const seen = new Set<string>();
  const normalized: RecommendationEEATCategory[] = [];
  for (const category of EEAT_CATEGORY_ORDER) {
    if (!categories.includes(category)) {
      continue;
    }
    if (seen.has(category)) {
      continue;
    }
    seen.add(category);
    normalized.push(category);
    if (normalized.length >= limit) {
      break;
    }
  }
  return normalized;
}

export function normalizeRecommendationEEATGapSummary(
  value: RecommendationEEATGapSummary | null | undefined,
): {
  categories: RecommendationEEATCategory[];
  supportingSignals: string[];
  message: string;
} | null {
  if (!value) {
    return null;
  }
  const categories = normalizeEEATCategories(value.top_gap_categories, 4);
  const supportingSignals = normalizeBoundedStringList(value.supporting_signals, 6, 120);
  const message = truncateOptionalText(value.message, 260);
  if (!message || categories.length === 0) {
    return null;
  }
  return {
    categories,
    supportingSignals,
    message,
  };
}

const PRIORITY_REASON_ORDER: RecommendationPriorityReason[] = [
  "competitor_gap",
  "trust_gap",
  "authority_gap",
  "experience_gap",
  "expertise_gap",
  "high_clarity_action",
  "pending_refresh_context",
  "general",
];

export function formatPriorityReason(reason: RecommendationPriorityReason): string {
  switch (reason) {
    case "competitor_gap":
      return "Competitor gap";
    case "trust_gap":
      return "Trust gap";
    case "authority_gap":
      return "Authority gap";
    case "experience_gap":
      return "Experience gap";
    case "expertise_gap":
      return "Expertise gap";
    case "high_clarity_action":
      return "Clear next step";
    case "pending_refresh_context":
      return "Pending refresh context";
    case "general":
      return "General";
    default:
      return reason;
  }
}

export function normalizeRecommendationPriorityReasons(
  value: RecommendationPriorityReason[] | null | undefined,
  limit = 4,
): RecommendationPriorityReason[] {
  if (!Array.isArray(value) || limit <= 0) {
    return [];
  }
  const seen = new Set<string>();
  const normalized: RecommendationPriorityReason[] = [];
  for (const reason of PRIORITY_REASON_ORDER) {
    if (!value.includes(reason)) {
      continue;
    }
    if (seen.has(reason)) {
      continue;
    }
    seen.add(reason);
    normalized.push(reason);
    if (normalized.length >= limit) {
      break;
    }
  }
  return normalized;
}

export function normalizeRecommendationOrderingExplanation(
  value: RecommendationOrderingExplanation | null | undefined,
): {
  message: string;
  contextReasons: RecommendationPriorityReason[];
} | null {
  if (!value) {
    return null;
  }
  const message = truncateOptionalText(value.message, 320);
  if (!message) {
    return null;
  }
  const contextReasons = normalizeRecommendationPriorityReasons(value.context_reasons, 4);
  return {
    message,
    contextReasons,
  };
}

export function formatRecommendationThemeLabel(theme: RecommendationTheme): string {
  switch (theme) {
    case "trust_and_legitimacy":
      return "Trust & legitimacy";
    case "experience_and_proof":
      return "Experience & proof";
    case "authority_and_visibility":
      return "Authority & visibility";
    case "expertise_and_process":
      return "Expertise & process";
    case "general_site_improvement":
      return "General site improvement";
  }
}

export function formatRecommendationThemeSummary(theme: RecommendationTheme): string {
  switch (theme) {
    case "trust_and_legitimacy":
      return "Improve visible business trust signals like reviews, verification, and contact legitimacy.";
    case "experience_and_proof":
      return "Show proof of real work with testimonials, project examples, and outcome evidence.";
    case "authority_and_visibility":
      return "Strengthen external credibility through citations, listings, and recognized signals.";
    case "expertise_and_process":
      return "Clarify how you work and what makes your process credible and capable.";
    case "general_site_improvement":
      return "Improve core site clarity and fundamentals that support overall performance.";
  }
}

export function formatRecommendationTargetContext(context: RecommendationTargetContext): string {
  switch (context) {
    case "homepage":
      return "Homepage";
    case "service_pages":
      return "Service pages";
    case "contact_about":
      return "Contact/About";
    case "location_pages":
      return "Location pages";
    case "sitewide":
      return "Sitewide";
    case "general":
    default:
      return "General";
  }
}

export function formatLocationContextSourceLabel(
  source: "explicit_location" | "service_area" | "zip_capture" | "fallback" | null,
): string | null {
  if (!source) {
    return null;
  }
  switch (source) {
    case "explicit_location":
      return "Explicit location";
    case "service_area":
      return "Service area";
    case "zip_capture":
      return "ZIP provided";
    case "fallback":
      return "Fallback";
  }
}

export function normalizeRecommendationThemeSections(
  recommendations: Recommendation[],
  grouped: RecommendationThemeGroup[] | null | undefined,
): Array<{
  theme: RecommendationTheme;
  label: string;
  items: Recommendation[];
}> {
  if (recommendations.length === 0) {
    return [];
  }

  const byId = new Map<string, Recommendation>();
  recommendations.forEach((recommendation) => {
    byId.set(recommendation.id, recommendation);
  });

  const sections: Array<{
    theme: RecommendationTheme;
    label: string;
    items: Recommendation[];
  }> = [];
  const consumed = new Set<string>();
  if (Array.isArray(grouped) && grouped.length > 0) {
    for (const group of grouped) {
      if (!group || !Array.isArray(group.recommendation_ids)) {
        continue;
      }
      const sectionItems: Recommendation[] = [];
      for (const recommendationId of group.recommendation_ids) {
        const item = byId.get(recommendationId);
        if (!item || consumed.has(item.id)) {
          continue;
        }
        consumed.add(item.id);
        sectionItems.push(item);
      }
      if (sectionItems.length === 0) {
        continue;
      }
      sections.push({
        theme: group.theme,
        label: truncateOptionalText(group.label, 80) || formatRecommendationThemeLabel(group.theme),
        items: sectionItems,
      });
    }
  }

  const ungrouped = recommendations.filter((recommendation) => !consumed.has(recommendation.id));
  if (ungrouped.length > 0) {
    sections.push({
      theme: "general_site_improvement",
      label: formatRecommendationThemeLabel("general_site_improvement"),
      items: ungrouped,
    });
  }

  if (sections.length === 0) {
    return [
      {
        theme: "general_site_improvement",
        label: formatRecommendationThemeLabel("general_site_improvement"),
        items: recommendations,
      },
    ];
  }
  return sections;
}

export function recommendationHasAiSource(item: Recommendation): boolean {
  const sourceValue = (item as unknown as { source?: unknown }).source;
  return typeof sourceValue === "string" && sourceValue.trim().toLowerCase() === "ai";
}

export function recommendationSourceType(item: Recommendation): string {
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

export function recommendationExpectedOutcome(item: Recommendation): string {
  const sourceType = recommendationSourceType(item);
  const normalizedSeverity = item.severity.trim().toLowerCase() || "unknown";
  const normalizedCategory = item.category.trim() || "General";
  let scopeLabel = "site recommendation quality";
  if (sourceType === "audit") {
    scopeLabel = "audit issue coverage";
  } else if (sourceType === "comparison") {
    scopeLabel = "competitive gap coverage";
  } else if (sourceType === "mixed") {
    scopeLabel = "audit and competitive gap coverage";
  }
  return `${normalizedCategory} improvement with ${item.priority_band} priority (${item.priority_score}) and ${item.effort_bucket} effort, likely improving ${scopeLabel} and reducing ${normalizedSeverity} risk.`;
}

export function narrativeSummaryText(narrative: RecommendationNarrative | null): string | null {
  if (!narrative) {
    return null;
  }
  const sections = narrative.sections_json;
  if (sections && typeof sections === "object" && !Array.isArray(sections)) {
    const summaryValue = (sections as Record<string, unknown>).summary;
    if (typeof summaryValue === "string" && summaryValue.trim()) {
      return summaryValue.trim();
    }
  }
  const narrativeText = (narrative.narrative_text || "").trim();
  return narrativeText || null;
}

export function normalizeNarrativeActionSummary(
  narrative: RecommendationNarrative | null,
): {
  primaryAction: string;
  whyItMatters: string | null;
  firstStep: string | null;
  evidence: string[];
} | null {
  const rawActionSummary = narrative?.action_summary;
  if (!rawActionSummary) {
    return null;
  }
  const primaryAction = truncateOptionalText(rawActionSummary.primary_action, 180);
  if (!primaryAction) {
    return null;
  }
  const whyItMatters = truncateOptionalText(rawActionSummary.why_it_matters, 220);
  const firstStep = truncateOptionalText(rawActionSummary.first_step, 180);
  const evidence = normalizeBoundedStringList(rawActionSummary.evidence, 4, 120);
  return {
    primaryAction,
    whyItMatters,
    firstStep,
    evidence,
  };
}

export function normalizeNarrativeCompetitorInfluence(
  narrative: RecommendationNarrative | null,
): {
  summary: string | null;
  topOpportunities: string[];
  competitorNames: string[];
} | null {
  const rawInfluence = narrative?.competitor_influence;
  if (!rawInfluence || !rawInfluence.used) {
    return null;
  }
  const summary = truncateOptionalText(rawInfluence.summary, 220);
  const topOpportunities = normalizeBoundedStringList(rawInfluence.top_opportunities, 3, 100);
  const competitorNames = normalizeBoundedStringList(rawInfluence.competitor_names, 5, 80);
  if (!summary && topOpportunities.length === 0 && competitorNames.length === 0) {
    return null;
  }
  return {
    summary,
    topOpportunities,
    competitorNames,
  };
}

type NarrativeSignalEvidenceSource = RecommendationNarrativeSignalSummary["evidence_sources"][number];

export function normalizeNarrativeSignalSummary(
  narrative: RecommendationNarrative | null,
): {
  supportLevel: "low" | "medium" | "high";
  evidenceSources: NarrativeSignalEvidenceSource[];
  competitorSignalUsed: boolean;
  siteSignalUsed: boolean;
  referenceSignalUsed: boolean;
} | null {
  const rawSignalSummary = narrative?.signal_summary;
  if (!rawSignalSummary) {
    return null;
  }
  const supportLevel =
    rawSignalSummary.support_level === "low" ||
    rawSignalSummary.support_level === "medium" ||
    rawSignalSummary.support_level === "high"
      ? rawSignalSummary.support_level
      : null;
  if (!supportLevel) {
    return null;
  }
  const sourceCandidates = normalizeBoundedStringList(rawSignalSummary.evidence_sources, 4, 32);
  const evidenceSources = sourceCandidates
    .filter(
      (
        value,
      ): value is NarrativeSignalEvidenceSource =>
        value === "site" || value === "competitors" || value === "references" || value === "themes",
    );
  const competitorSignalUsed = Boolean(rawSignalSummary.competitor_signal_used);
  const siteSignalUsed = Boolean(rawSignalSummary.site_signal_used);
  const referenceSignalUsed = Boolean(rawSignalSummary.reference_signal_used);
  if (
    evidenceSources.length === 0 &&
    !competitorSignalUsed &&
    !siteSignalUsed &&
    !referenceSignalUsed
  ) {
    return null;
  }
  return {
    supportLevel,
    evidenceSources,
    competitorSignalUsed,
    siteSignalUsed,
    referenceSignalUsed,
  };
}
