function buildSiteScopedHref(pathname: string, siteId: string): string {
  const params = new URLSearchParams();
  params.set("site_id", siteId);
  return `${pathname}?${params.toString()}`;
}

export function buildCompetitorSetHref(setId: string, siteId: string): string {
  return buildSiteScopedHref(`/competitors/${setId}`, siteId);
}

export function buildComparisonRunHref(
  comparisonRunId: string,
  siteId: string,
  setId?: string,
): string {
  const params = new URLSearchParams();
  params.set("site_id", siteId);
  if (setId) {
    params.set("set_id", setId);
  }
  return `/competitors/comparison-runs/${comparisonRunId}?${params.toString()}`;
}

export function buildSnapshotRunHref(snapshotRunId: string, siteId: string, setId: string): string {
  const params = new URLSearchParams();
  params.set("site_id", siteId);
  params.set("set_id", setId);
  return `/competitors/snapshot-runs/${snapshotRunId}?${params.toString()}`;
}

export function buildRecommendationDetailHref(recommendationId: string, siteId: string): string {
  return buildSiteScopedHref(`/recommendations/${recommendationId}`, siteId);
}

export function buildRecommendationRunHref(recommendationRunId: string, siteId: string): string {
  return buildSiteScopedHref(`/recommendations/runs/${recommendationRunId}`, siteId);
}

export function buildNarrativeHistoryHref(recommendationRunId: string, siteId: string): string {
  return buildSiteScopedHref(`/recommendations/runs/${recommendationRunId}/narratives`, siteId);
}

export function buildNarrativeDetailHref(
  recommendationRunId: string,
  narrativeId: string,
  siteId: string,
): string {
  return buildSiteScopedHref(
    `/recommendations/runs/${recommendationRunId}/narratives/${narrativeId}`,
    siteId,
  );
}

export function buildAutomationPageHref(siteId: string): string {
  return buildSiteScopedHref("/automation", siteId);
}
