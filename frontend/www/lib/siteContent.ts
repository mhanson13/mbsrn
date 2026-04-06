export const appUrl = "https://app.mbsrn.com";
export const supportEmail = "support@mbsrn.com";

export const homeContent = {
  hero: {
    eyebrow: "My Business Sucks Right Now (MBSRN)",
    heading: "My Business Sucks Right Now helps you fix weak website visibility with an operator workflow you can actually run.",
    subheading:
      "MBSRN gives small business operators practical SEO operations: audit visibility, competitor pressure signals, Google-connected measurement, and clear next actions.",
  },
  audience: {
    title: "Who this is for",
    items: [
      "Small business owners and operators who know their website is underperforming",
      "Teams without a full-time SEO specialist but with real execution responsibility",
      "Businesses that need clear priorities, not another analytics dashboard",
    ],
  },
  problem: {
    title: "What problem it solves",
    body:
      "Most small businesses can see traffic is weak, but they cannot see where to focus first. MBSRN turns scattered SEO signals into a prioritized operations queue with concrete follow-through.",
  },
};

export const outcomes = [
  {
    title: "See what is broken first",
    body: "Audit and workspace visibility make it obvious where site health and search readiness are weak.",
  },
  {
    title: "Understand competitive pressure",
    body: "Competitor intelligence shows where similar businesses are covering topics better or more completely.",
  },
  {
    title: "Know what to do next",
    body: "Recommendation detail emphasizes rationale, evidence, readiness, and implementation guidance.",
  },
];

export const coreFeatureHighlights = [
  {
    title: "Site visibility and audit workspace",
    body: "Run deterministic audits, review issue summaries, and track operational activity in one place.",
  },
  {
    title: "Competitor intelligence",
    body: "Discover, compare, and review competitor context with conservative trust boundaries and quality filters.",
  },
  {
    title: "Recommendation operations",
    body: "Use priority rationale, evidence strength, execution readiness, and implementation steps to move from insight to action.",
  },
  {
    title: "Google measurement context",
    body: "Connect GA4 and Search Console to monitor directional outcomes and integration health signals.",
  },
];

export const howItWorksSteps = [
  "Connect a site and establish a baseline of SEO health.",
  "Run audits and competitor discovery to expose practical gaps.",
  "Review prioritized recommendations with clear why-now and next-action guidance.",
  "Track directional measurement context and iterate operator actions.",
];

export const trustSignals = [
  "Operator-reviewed workflow by default, with explicit action checkpoints.",
  "Deterministic explanation fields for priority, evidence, and readiness.",
  "Google data is used as contextual signal support, not attribution proof.",
  "No unsupported claims of automatic ranking wins or guaranteed outcomes.",
];

export type FeatureGroup = {
  title: string;
  description: string;
  bullets: string[];
};

export const featureGroups: FeatureGroup[] = [
  {
    title: "Site visibility and audit workspace",
    description:
      "Understand what is happening on your site before guessing at fixes.",
    bullets: [
      "Business-scoped site management and deterministic audit runs",
      "Audit findings and workspace summaries with activity timelines",
      "Outcome/status visibility across workspace, recommendation, and automation surfaces",
    ],
  },
  {
    title: "Competitor intelligence",
    description:
      "See market pressure and topic gaps with conservative, reviewable competitor signals.",
    bullets: [
      "Competitor discovery with weak-site fallback for sparse customer content",
      "Comparison reporting and operator review workflow with trust tiers",
      "Candidate deduplication, filtering, and explicit exclusion reasoning",
    ],
  },
  {
    title: "Recommendation engine and actionability",
    description:
      "Move from generic SEO advice to practical, bounded operator actions.",
    bullets: [
      "Priority rationale, evidence strength, why-now, and next-action summaries",
      "Content-to-update targets with page/context guidance where available",
      "Execution-readiness cues and deterministic action-plan guidance",
      "Competitor-informed differentiation when evidence is strong enough",
    ],
  },
  {
    title: "Google integrations and measurement context",
    description:
      "Use Google-connected context to understand trend direction without overclaiming causation.",
    bullets: [
      "Google Business Profile status visibility and reconnect guidance",
      "GA4 diagnostics and freshness signals (last data seen / sync health)",
      "Search Console diagnostics and page/topic visibility context",
      "Directional recommendation measurement context (not attribution)",
    ],
  },
  {
    title: "Operator workflow and action tracking",
    description:
      "Keep execution state and follow-up expectations visible across the workflow.",
    bullets: [
      "Action lineage from recommendation to next-step draft to activated action",
      "Manual automation run initiation with explicit run history and step outcomes",
      "Clear blocked/waiting/output-ready status handling in operator UI",
    ],
  },
  {
    title: "Admin and tuning controls",
    description:
      "Maintain operational control over site settings, identity, and diagnostics.",
    bullets: [
      "Admin-managed site settings and integration property configuration",
      "User ID management separated from core platform settings",
      "Prompt/tuning and diagnostics surfaces with review-safe guardrails",
    ],
  },
];
