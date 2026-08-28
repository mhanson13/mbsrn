"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo } from "react";

import { MigrationWorkspacePanel } from "../../../../components/MigrationWorkspacePanel";
import {
  OperatorPageHero,
  OperatorPageSectionStack,
} from "../../../../components/layout/OperatorPageSurface";
import { OperatorRouteSupportState } from "../../../../components/layout/OperatorRouteSupportState";
import { PageContainer } from "../../../../components/layout/PageContainer";
import { RouteActionCluster } from "../../../../components/layout/RouteActionCluster";
import { SummaryStatCard } from "../../../../components/layout/SummaryStatCard";
import { useOperatorContext } from "../../../../components/useOperatorContext";

export default function SiteMigrationWorkflowPage(): JSX.Element {
  const params = useParams<{ site_id: string }>();
  const siteId = decodeURIComponent(params?.site_id || "");
  const context = useOperatorContext();

  const selectedSite = useMemo(
    () => context.sites.find((candidate) => candidate.id === siteId) || null,
    [context.sites, siteId],
  );

  useEffect(() => {
    if (!siteId || context.selectedSiteId === siteId) {
      return;
    }
    context.setSelectedSiteId(siteId);
  }, [context, siteId]);

  if (context.loading) {
    return (
      <OperatorRouteSupportState
        title="Loading migration workspace"
        subtitle="Loading site migration workflow context."
        backHref="/sites"
        backLabel="Back to Sites"
      />
    );
  }

  if (!context.token || !context.businessId) {
    return (
      <OperatorRouteSupportState
        title="Sign in required"
        subtitle="Sign in to access the migration workflow."
      />
    );
  }

  if (!siteId || !selectedSite) {
    return (
      <OperatorRouteSupportState
        title="Migration workflow unavailable"
        subtitle="The selected site could not be loaded for migration workflow operations."
        backHref="/sites"
        backLabel="Return to Sites"
      />
    );
  }

  return (
    <PageContainer width="full" density="compact">
      <OperatorPageHero
        title="Migration Workflow"
        subtitle="Dedicated workflow console for source ingest, draft lifecycle, diagnostics, publish, and deploy."
        headingLevel={1}
        actions={(
          <RouteActionCluster
            secondaryActions={
              <>
                <Link href={`/sites/${encodeURIComponent(selectedSite.id)}`}>Back to Site Workspace</Link>
                <Link href="/sites">All Sites</Link>
              </>
            }
          />
        )}
        summary={(
          <>
            <SummaryStatCard
              label="Site"
              value={selectedSite.display_name}
              detail={selectedSite.normalized_domain}
              tone="neutral"
              variant="elevated"
              data-testid="migration-page-summary-site"
            />
            <SummaryStatCard
              label="Workflow ownership"
              value="Migration route"
              detail="Draft generation, review, publish, and deploy are isolated from the main site workspace."
              tone="success"
              variant="elevated"
              data-testid="migration-page-summary-ownership"
            />
          </>
        )}
      />

      <OperatorPageSectionStack>
        <MigrationWorkspacePanel
          key={`${context.businessId}:${selectedSite.id}`}
          token={context.token}
          businessId={context.businessId}
          siteId={selectedSite.id}
          initialPreviewSlug={selectedSite.preview_slug || null}
          initialPreviewSlugLockedAt={selectedSite.preview_slug_locked_at || null}
          isAdmin={context.principalRole === "admin"}
        />
      </OperatorPageSectionStack>
    </PageContainer>
  );
}
