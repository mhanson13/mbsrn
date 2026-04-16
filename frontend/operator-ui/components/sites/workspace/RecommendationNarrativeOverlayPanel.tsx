import Link from "next/link";
import type { ReactNode } from "react";

import type {
  AIDiagnosticsSummary,
  OperatorResponseContractSummary,
  RecommendationEEATCategory,
  RecommendationNarrative,
  RecommendationTuningImpactPreview,
  RecommendationTuningSuggestion,
} from "../../../lib/api/types";

interface NarrativeActionSummaryViewLike {
  primaryAction: string;
  whyItMatters: string | null;
  firstStep: string | null;
  evidence: string[];
}

interface NarrativeCompetitorInfluenceViewLike {
  summary: string | null;
  topOpportunities: string[];
  competitorNames: string[];
}

interface NarrativeSignalSummaryViewLike {
  supportLevel: "low" | "medium" | "high";
  evidenceSources: string[];
  siteSignalUsed: boolean;
  competitorSignalUsed: boolean;
  referenceSignalUsed: boolean;
}

interface RecommendationEEATGapSummaryViewLike {
  categories: RecommendationEEATCategory[];
  message: string;
  supportingSignals: string[];
}

interface RecommendationApplyOutcomeViewLike {
  source: string | null;
  appliedRecommendationTitle: string | null;
  appliedRecommendationId: string | null;
  appliedChangeSummary: string | null;
  appliedPreviewSummary: string | null;
  nextRefreshExpectation: string | null;
  appliedAt: string | null;
}

interface RecommendationAnalysisFreshnessViewLike {
  status: "fresh" | "pending_refresh" | "unknown";
  message: string;
  analysisGeneratedAt: string | null;
  lastApplyAt: string | null;
}

interface CompetitorContextHealthCheckViewLike {
  key: string;
  label: string;
  status: "strong" | "weak";
  detail: string;
}

interface CompetitorContextHealthViewLike {
  status: "strong" | "mixed" | "weak";
  checks: CompetitorContextHealthCheckViewLike[];
  message: string;
}

interface RecentTuningChangeLike {
  id: string;
  applied_at: string;
  setting_label: string;
  previous_value: number;
  next_value: number;
  ai_attribution: { recommendation_title: string } | null;
}

interface RecommendationNarrativeOverlayPanelProps {
  promptPreviewContent: ReactNode;
  latestCompletedRecommendationNarrative: RecommendationNarrative | null;
  latestNarrativeDetailHref: string | null;
  narrativeResponseContractSummary: OperatorResponseContractSummary | null;
  narrativeAIDiagnosticsSummary: AIDiagnosticsSummary | null;
  narrativeActionSummary: NarrativeActionSummaryViewLike | null;
  narrativeEEATFocusCategories: RecommendationEEATCategory[];
  narrativeCompetitorInfluence: NarrativeCompetitorInfluenceViewLike | null;
  narrativeSignalSummary: NarrativeSignalSummaryViewLike | null;
  recommendationEEATGapSummary: RecommendationEEATGapSummaryViewLike | null;
  recommendationApplyOutcome: RecommendationApplyOutcomeViewLike | null;
  recommendationAnalysisFreshness: RecommendationAnalysisFreshnessViewLike | null;
  siteLocationContextSource: "explicit_location" | "service_area" | "zip_capture" | "fallback" | null;
  competitorContextHealth: CompetitorContextHealthViewLike | null;
  tuningApplyMessage: string | null;
  latestCompletedTuningSuggestions: RecommendationTuningSuggestion[];
  recentTuningChanges: RecentTuningChangeLike[];
  runId: string;
  startHereFocusedTargetId: string | null;
  aiActionFocusedTargetId: string | null;
  tuningPreviewByKey: Record<string, RecommendationTuningImpactPreview>;
  tuningPreviewErrorByKey: Record<string, string>;
  tuningApplyErrorByKey: Record<string, string>;
  tuningPreviewLoadingKey: string | null;
  tuningApplyLoadingKey: string | null;
  onPreviewTuningSuggestion: (suggestion: RecommendationTuningSuggestion) => void;
  onApplyTuningSuggestion: (suggestion: RecommendationTuningSuggestion) => void;
  buildTuningPreviewKey: (runId: string, suggestion: RecommendationTuningSuggestion) => string;
  tuningSuggestionCardId: (runId: string, suggestion: RecommendationTuningSuggestion) => string;
  currentSuggestionValue: (suggestion: RecommendationTuningSuggestion) => number;
  formatDateTime: (value: string | null) => string;
  formatResponseContractStatus: (status: OperatorResponseContractSummary["status"]) => string;
  responseContractSummaryHintClass: (summary: OperatorResponseContractSummary) => string;
  formatEEATCategory: (value: RecommendationEEATCategory) => string;
  formatNarrativeSupportLevel: (value: "low" | "medium" | "high") => string;
  analysisFreshnessBadgeClass: (status: "fresh" | "pending_refresh" | "unknown") => string;
  analysisFreshnessLabel: (status: "fresh" | "pending_refresh" | "unknown") => string;
  formatLocationContextSourceLabel: (
    value: "explicit_location" | "service_area" | "zip_capture" | "fallback" | null,
  ) => string | null;
  competitorContextHealthBadgeClass: (status: "strong" | "mixed" | "weak") => string;
  competitorContextHealthLabel: (status: "strong" | "mixed" | "weak") => string;
  competitorContextHealthCheckBadgeClass: (status: "strong" | "weak") => string;
  formatTuningSettingLabel: (setting: RecommendationTuningSuggestion["setting"]) => string;
  formatSignedDelta: (value: number) => string;
}

function formatAIDiagnosticsSecondarySummary(summary: AIDiagnosticsSummary): string | null {
  const parts: string[] = [];
  if (summary.failure_source) {
    parts.push(`source ${summary.failure_source.replace(/_/g, " ")}`);
  }
  if (summary.budget_outcome) {
    parts.push(`budget ${summary.budget_outcome.replace(/_/g, " ")}`);
  }
  if (typeof summary.retry_suppressed === "boolean") {
    parts.push(`retry suppressed ${summary.retry_suppressed ? "yes" : "no"}`);
  }
  if (typeof summary.trimming_pass_count === "number") {
    parts.push(`trim passes ${summary.trimming_pass_count}`);
  }
  if (summary.difficulty_bucket) {
    parts.push(`difficulty ${summary.difficulty_bucket.replace(/_/g, " ")}`);
  }
  if (summary.input_size_bucket) {
    parts.push(`input ${summary.input_size_bucket.replace(/_/g, " ")}`);
  }
  if (summary.degraded_state) {
    parts.push(`state ${summary.degraded_state.replace(/_/g, " ")}`);
  }
  return parts.length > 0 ? parts.join("; ") : null;
}

export function RecommendationNarrativeOverlayPanel({
  promptPreviewContent,
  latestCompletedRecommendationNarrative,
  latestNarrativeDetailHref,
  narrativeResponseContractSummary,
  narrativeAIDiagnosticsSummary,
  narrativeActionSummary,
  narrativeEEATFocusCategories,
  narrativeCompetitorInfluence,
  narrativeSignalSummary,
  recommendationEEATGapSummary,
  recommendationApplyOutcome,
  recommendationAnalysisFreshness,
  siteLocationContextSource,
  competitorContextHealth,
  tuningApplyMessage,
  latestCompletedTuningSuggestions,
  recentTuningChanges,
  runId,
  startHereFocusedTargetId,
  aiActionFocusedTargetId,
  tuningPreviewByKey,
  tuningPreviewErrorByKey,
  tuningApplyErrorByKey,
  tuningPreviewLoadingKey,
  tuningApplyLoadingKey,
  onPreviewTuningSuggestion,
  onApplyTuningSuggestion,
  buildTuningPreviewKey,
  tuningSuggestionCardId,
  currentSuggestionValue,
  formatDateTime,
  formatResponseContractStatus,
  responseContractSummaryHintClass,
  formatEEATCategory,
  formatNarrativeSupportLevel,
  analysisFreshnessBadgeClass,
  analysisFreshnessLabel,
  formatLocationContextSourceLabel,
  competitorContextHealthBadgeClass,
  competitorContextHealthLabel,
  competitorContextHealthCheckBadgeClass,
  formatTuningSettingLabel,
  formatSignedDelta,
}: RecommendationNarrativeOverlayPanelProps): JSX.Element {
  const narrativeAIDiagnosticsSecondarySummary = narrativeAIDiagnosticsSummary
    ? formatAIDiagnosticsSecondarySummary(narrativeAIDiagnosticsSummary)
    : null;

  return (
    <>
      <h4>AI Narrative Overlay</h4>
      {promptPreviewContent}
      {latestCompletedRecommendationNarrative ? (
        <div className="stack">
          <p className="hint muted">
            Narrative v{latestCompletedRecommendationNarrative.version} (
            {latestCompletedRecommendationNarrative.status}) | Provider{" "}
            {latestCompletedRecommendationNarrative.provider_name} | Model{" "}
            {latestCompletedRecommendationNarrative.model_name} | Template{" "}
            {latestCompletedRecommendationNarrative.prompt_version}
          </p>
          {latestNarrativeDetailHref ? (
            <p>
              <Link href={latestNarrativeDetailHref}>Open latest narrative</Link>
            </p>
          ) : null}
          {narrativeResponseContractSummary ? (
            <p
              className={responseContractSummaryHintClass(narrativeResponseContractSummary)}
              data-testid="recommendation-response-contract-summary"
            >
              <strong>Quality gate:</strong> {formatResponseContractStatus(narrativeResponseContractSummary.status)}.{" "}
              {narrativeResponseContractSummary.summary}
              {narrativeResponseContractSummary.retryable
              && narrativeResponseContractSummary.status !== "accepted"
                ? " This looks retryable."
                : ""}
            </p>
          ) : null}
          {narrativeAIDiagnosticsSummary ? (
            <p className="hint muted" data-testid="recommendation-ai-diagnostics-summary">
              <strong>AI diagnostics:</strong>{" "}
              {narrativeAIDiagnosticsSummary.failure_category || "n/a"}
              {narrativeAIDiagnosticsSummary.failure_reason ? ` / ${narrativeAIDiagnosticsSummary.failure_reason}` : ""}
              {narrativeAIDiagnosticsSummary.hint ? ` — ${narrativeAIDiagnosticsSummary.hint}` : ""}
              {typeof narrativeAIDiagnosticsSummary.retryable === "boolean"
                ? ` (retryable: ${narrativeAIDiagnosticsSummary.retryable ? "yes" : "no"})`
                : ""}
            </p>
          ) : null}
          {narrativeAIDiagnosticsSecondarySummary ? (
            <p className="hint muted" data-testid="recommendation-ai-diagnostics-secondary-summary">
              <strong>AI execution:</strong> {narrativeAIDiagnosticsSecondarySummary}
            </p>
          ) : null}
          {narrativeActionSummary ? (
            <div className="panel panel-compact stack" data-testid="narrative-action-summary">
              <span className="hint muted">Next best move</span>
              <strong>{narrativeActionSummary.primaryAction}</strong>
              {narrativeActionSummary.whyItMatters ? (
                <span className="hint">Why this matters: {narrativeActionSummary.whyItMatters}</span>
              ) : null}
              {narrativeEEATFocusCategories.length > 0 ? (
                <span className="hint muted">
                  EEAT focus: {narrativeEEATFocusCategories.map((category) => formatEEATCategory(category)).join(", ")}
                </span>
              ) : null}
              {narrativeActionSummary.firstStep ? (
                <span className="hint success">Start here: {narrativeActionSummary.firstStep}</span>
              ) : null}
              {narrativeActionSummary.evidence.length > 0 ? (
                <div className="stack-tight">
                  <span className="hint muted">Evidence</span>
                  <div className="link-row">
                    {narrativeActionSummary.evidence.map((evidenceItem) => (
                      <span key={evidenceItem} className="badge badge-muted">
                        {evidenceItem}
                      </span>
                    ))}
                  </div>
                </div>
              ) : null}
            </div>
          ) : null}
          {narrativeCompetitorInfluence ? (
            <div className="panel panel-compact stack-tight" data-testid="narrative-competitor-influence">
              <span className="hint muted">Competitor-informed</span>
              {narrativeCompetitorInfluence.summary ? (
                <span className="hint">{narrativeCompetitorInfluence.summary}</span>
              ) : null}
              {narrativeCompetitorInfluence.topOpportunities.length > 0 ? (
                <span className="hint muted">
                  Top opportunities: {narrativeCompetitorInfluence.topOpportunities.join(", ")}
                </span>
              ) : null}
              {narrativeCompetitorInfluence.competitorNames.length > 0 ? (
                <span className="hint muted">
                  Nearby competitors: {narrativeCompetitorInfluence.competitorNames.join(", ")}
                </span>
              ) : null}
            </div>
          ) : null}
          {narrativeSignalSummary ? (
            <div className="panel panel-compact stack-tight" data-testid="narrative-signal-summary">
              <span className="hint muted">Backed by</span>
              <span className="hint">
                Support level: {formatNarrativeSupportLevel(narrativeSignalSummary.supportLevel)}
              </span>
              {narrativeSignalSummary.evidenceSources.length > 0 ? (
                <div className="link-row">
                  {narrativeSignalSummary.evidenceSources.map((source) => (
                    <span key={source} className="badge badge-muted">
                      {source}
                    </span>
                  ))}
                </div>
              ) : null}
              <span className="hint muted">
                Signal check: site {narrativeSignalSummary.siteSignalUsed ? "yes" : "no"}; competitors{" "}
                {narrativeSignalSummary.competitorSignalUsed ? "yes" : "no"}; references{" "}
                {narrativeSignalSummary.referenceSignalUsed ? "yes" : "no"}.
              </span>
            </div>
          ) : null}
          {recommendationEEATGapSummary ? (
            <div className="panel panel-compact stack-tight" data-testid="narrative-eeat-gap-summary">
              <span className="hint muted">EEAT gap summary</span>
              <div className="link-row">
                {recommendationEEATGapSummary.categories.map((category) => (
                  <span key={`eeat-gap-${category}`} className="badge badge-warn">
                    {formatEEATCategory(category)}
                  </span>
                ))}
              </div>
              <span className="hint">{recommendationEEATGapSummary.message}</span>
              {recommendationEEATGapSummary.supportingSignals.length > 0 ? (
                <div className="stack-tight">
                  <span className="hint muted">Supporting signals</span>
                  <div className="link-row">
                    {recommendationEEATGapSummary.supportingSignals.map((signal) => (
                      <span key={signal} className="badge badge-muted">
                        {signal}
                      </span>
                    ))}
                  </div>
                </div>
              ) : null}
            </div>
          ) : null}
          {recommendationApplyOutcome ? (
            <div className="panel panel-compact stack-tight operator-summary-callout" data-testid="narrative-apply-outcome">
              <span className="hint muted">Latest apply outcome</span>
              <span className="hint success">Applied</span>
              {recommendationApplyOutcome.appliedRecommendationTitle ? (
                <span className="hint">
                  Recommendation: {recommendationApplyOutcome.appliedRecommendationTitle}
                  {recommendationApplyOutcome.appliedRecommendationId
                    ? ` (${recommendationApplyOutcome.appliedRecommendationId})`
                    : ""}
                </span>
              ) : null}
              {recommendationApplyOutcome.appliedChangeSummary ? (
                <span className="hint muted">What changed: {recommendationApplyOutcome.appliedChangeSummary}</span>
              ) : null}
              {recommendationApplyOutcome.appliedPreviewSummary ? (
                <span className="hint muted">Preview used: {recommendationApplyOutcome.appliedPreviewSummary}</span>
              ) : null}
              {recommendationApplyOutcome.nextRefreshExpectation ? (
                <span className="hint muted">
                  You should see this after: {recommendationApplyOutcome.nextRefreshExpectation}
                </span>
              ) : null}
              {recommendationApplyOutcome.appliedAt ? (
                <span className="hint muted">Applied at: {formatDateTime(recommendationApplyOutcome.appliedAt)}</span>
              ) : null}
              {recommendationApplyOutcome.source === "recommendation" ? (
                <span className="hint muted">Source: recommendation-guided tuning action.</span>
              ) : null}
            </div>
          ) : null}
          {recommendationAnalysisFreshness ? (
            <div className="panel panel-compact stack-tight" data-testid="narrative-analysis-freshness">
              <span className="hint muted">Analysis freshness</span>
              <span className={analysisFreshnessBadgeClass(recommendationAnalysisFreshness.status)}>
                {analysisFreshnessLabel(recommendationAnalysisFreshness.status)}
              </span>
              <span className="hint">{recommendationAnalysisFreshness.message}</span>
              {recommendationAnalysisFreshness.analysisGeneratedAt ? (
                <span className="hint muted">
                  Analysis generated at: {formatDateTime(recommendationAnalysisFreshness.analysisGeneratedAt)}
                </span>
              ) : null}
              {recommendationAnalysisFreshness.lastApplyAt ? (
                <span className="hint muted">
                  Last apply at: {formatDateTime(recommendationAnalysisFreshness.lastApplyAt)}
                </span>
              ) : null}
              {formatLocationContextSourceLabel(siteLocationContextSource) ? (
                <span className="hint muted">
                  Location source: {formatLocationContextSourceLabel(siteLocationContextSource)}
                </span>
              ) : null}
            </div>
          ) : null}
          {competitorContextHealth ? (
            <div className="panel panel-compact stack-tight" data-testid="competitor-context-health">
              <span className="hint muted">Competitor context health</span>
              <span className={competitorContextHealthBadgeClass(competitorContextHealth.status)}>
                {competitorContextHealthLabel(competitorContextHealth.status)}
              </span>
              <span className="hint">{competitorContextHealth.message}</span>
              {competitorContextHealth.checks.length > 0 ? (
                <div className="stack-tight">
                  {competitorContextHealth.checks.map((check) => (
                    <div key={`competitor-context-health-${check.key}`} className="link-row">
                      <span className={competitorContextHealthCheckBadgeClass(check.status)}>
                        {check.status === "strong" ? "Strong" : "Weak"}
                      </span>
                      <span className="hint">
                        {check.label}: {check.detail}
                      </span>
                    </div>
                  ))}
                </div>
              ) : null}
            </div>
          ) : null}
          {latestCompletedRecommendationNarrative.narrative_text ? (
            <p>{latestCompletedRecommendationNarrative.narrative_text}</p>
          ) : null}
          {!latestCompletedRecommendationNarrative.narrative_text
          && latestCompletedRecommendationNarrative.status === "completed" ? (
            <p className="hint muted">Narrative completed without summary text.</p>
          ) : null}
          {latestCompletedRecommendationNarrative.status === "failed" ? (
            <p className="hint warning">
              Narrative generation failed.
              {latestCompletedRecommendationNarrative.error_message
                ? ` ${latestCompletedRecommendationNarrative.error_message}`
                : ""}
            </p>
          ) : null}
          <span className="hint muted">AI-Assisted Tuning Suggestions</span>
          {tuningApplyMessage ? <span className="hint success">{tuningApplyMessage}</span> : null}
          {latestCompletedTuningSuggestions.length > 0 ? (
            latestCompletedTuningSuggestions.map((suggestion) => {
              const previewKey = buildTuningPreviewKey(runId, suggestion);
              const suggestionCardId = tuningSuggestionCardId(runId, suggestion);
              const currentValue = currentSuggestionValue(suggestion);
              const alreadyApplied = currentValue === suggestion.recommended_value;
              const preview = tuningPreviewByKey[previewKey];
              return (
                <div
                  key={`${runId}-${suggestion.setting}-${suggestion.recommended_value}`}
                  id={suggestionCardId}
                  className={
                    startHereFocusedTargetId === suggestionCardId || aiActionFocusedTargetId === suggestionCardId
                      ? "panel panel-compact stack start-here-target-active"
                      : "panel panel-compact stack"
                  }
                  data-testid="tuning-suggestion-card"
                >
                  <strong>{formatTuningSettingLabel(suggestion.setting)}</strong>
                  <span className="hint">
                    Current -&gt; Suggested: <strong>{currentValue}</strong> -&gt;{" "}
                    <strong>{suggestion.recommended_value}</strong>
                  </span>
                  <span className="hint muted">{suggestion.reason}</span>
                  <span className="hint muted">Confidence: {suggestion.confidence}</span>
                  <button
                    type="button"
                    className="button button-tertiary button-inline"
                    onClick={() => onPreviewTuningSuggestion(suggestion)}
                    disabled={tuningPreviewLoadingKey === previewKey}
                  >
                    {tuningPreviewLoadingKey === previewKey ? "Previewing..." : "Preview Impact"}
                  </button>
                  <button
                    type="button"
                    className="button button-primary button-inline"
                    onClick={() => onApplyTuningSuggestion(suggestion)}
                    disabled={alreadyApplied || tuningApplyLoadingKey === previewKey}
                  >
                    {alreadyApplied
                      ? "Applied"
                      : tuningApplyLoadingKey === previewKey
                        ? "Applying..."
                        : "Apply Suggestion"}
                  </button>
                  {tuningPreviewErrorByKey[previewKey] ? (
                    <span className="hint warning">{tuningPreviewErrorByKey[previewKey]}</span>
                  ) : null}
                  {tuningApplyErrorByKey[previewKey] ? (
                    <span className="hint warning">{tuningApplyErrorByKey[previewKey]}</span>
                  ) : null}
                  {preview ? (
                    <>
                      <span className="hint">
                        Impact hint: {formatSignedDelta(preview.estimated_impact.estimated_included_candidate_delta)}{" "}
                        candidates included
                      </span>
                      <span className="hint muted">{preview.estimated_impact.summary}</span>
                      <span className="hint muted">
                        Included delta:{" "}
                        {formatSignedDelta(preview.estimated_impact.estimated_included_candidate_delta)};
                        excluded delta:{" "}
                        {formatSignedDelta(preview.estimated_impact.estimated_excluded_candidate_delta)}
                      </span>
                    </>
                  ) : null}
                </div>
              );
            })
          ) : (
            <span className="hint muted">No tuning adjustments suggested for current data.</span>
          )}
          {recentTuningChanges.length > 0 ? (
            <div className="panel panel-compact stack" data-testid="recent-changes-panel">
              <span className="hint muted">Recent Changes</span>
              <ul>
                {recentTuningChanges.map((change) => (
                  <li key={change.id}>
                    <span className="hint">
                      {change.setting_label}: {change.previous_value} -&gt; {change.next_value} (
                      {formatDateTime(change.applied_at)})
                    </span>
                    {change.ai_attribution ? (
                      <>
                        <br />
                        <span className="badge badge-muted">From AI Recommendation</span>
                        <span className="hint muted"> {change.ai_attribution.recommendation_title}</span>
                      </>
                    ) : null}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      ) : (
        <p className="hint muted">
          No narrative has been generated for the latest completed recommendation run yet.
        </p>
      )}
    </>
  );
}
