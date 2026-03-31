"use client";

import Link from "next/link";
import { useOperatorContext } from "../../components/useOperatorContext";
import { useAuth } from "../../components/AuthProvider";
import { PageContainer } from "../../components/layout/PageContainer";
import { SectionCard } from "../../components/layout/SectionCard";
import { SectionHeader } from "../../components/layout/SectionHeader";
import { SummaryStatCard } from "../../components/layout/SummaryStatCard";

export default function DashboardPage() {
  const context = useOperatorContext();
  const { principal } = useAuth();

  if (context.loading) {
    return (
      <PageContainer>
        <SectionCard as="div" variant="support" className="role-surface-support">
          <SectionHeader
            title="Dashboard"
            subtitle="Loading dashboard overview and role-scoped status."
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
            title="Dashboard"
            subtitle={`Error: ${context.error}`}
            headingLevel={1}
            variant="support"
          />
        </SectionCard>
      </PageContainer>
    );
  }

  const hasSites = context.sites.length > 0;
  const hasUnauditedSite = context.sites.some((site) => !site.last_audit_run_id);
  const hasCompletedAudit = context.sites.some(
    (site) => (site.last_audit_status || "").trim().toLowerCase() === "completed",
  );

  return (
    <PageContainer>
      <div className="role-dashboard-landing">
        <SectionCard variant="primary" className="role-dashboard-hero">
          <SectionHeader
            title="Dashboard"
            subtitle="Role-aware workspace status and next-step navigation."
            headingLevel={1}
            variant="hero"
            meta={(
              <>
                <span className="hint muted">Business scope: <code>{context.businessId}</code></span>
                {principal ? <span className="hint muted">Role: {principal.role}</span> : null}
              </>
            )}
          />
          <div className="workspace-summary-strip role-summary-strip">
            <SummaryStatCard
              label="Tracked sites"
              value={context.sites.length}
              detail={hasSites ? "Configured and available" : "No sites configured yet"}
              tone={hasSites ? "success" : "warning"}
              variant="elevated"
            />
            <SummaryStatCard
              label="Audit coverage"
              value={hasCompletedAudit ? "Available" : "Missing"}
              detail={hasCompletedAudit ? "Completed audit data found" : "Run first audit from Sites"}
              tone={hasCompletedAudit ? "success" : "warning"}
              variant="elevated"
            />
            <SummaryStatCard
              label="Action state"
              value={hasUnauditedSite ? "Review needed" : "Stable"}
              detail={hasUnauditedSite ? "At least one site has no audit run" : "All tracked sites have audit history"}
              tone={hasUnauditedSite ? "warning" : "neutral"}
              variant="elevated"
            />
          </div>
          {!hasSites ? <p className="hint warning">No sites configured yet. Start by adding your first site.</p> : null}
          {hasSites && hasUnauditedSite ? (
            <p className="hint warning">At least one site has not been audited yet. Run your first audit from Sites.</p>
          ) : null}
          {hasCompletedAudit ? (
            <p className="hint muted">Audit data is available. Next step: review recommendations.</p>
          ) : null}
        </SectionCard>
      </div>

      <SectionCard variant="summary" className="role-surface-support recommendation-outcome-surface">
        <SectionHeader
          title="Recommendation decisiveness cues"
          subtitle="Use this short scan order: why now, blocker, then after-action visibility."
          headingLevel={2}
          variant="support"
          actions={<Link href="/recommendations">Open Recommendations</Link>}
        />
        <p className="hint">
          <span className="text-strong">Why now:</span>{" "}
          <span className="badge badge-warn">High-value next step</span>{" "}
          <span className="badge badge-success">Ready now</span>{" "}
          indicates the top item to review first.
        </p>
        <p className="hint">
          <span className="text-strong">Blocking:</span>{" "}
          <span className="badge badge-warn">Waiting on visibility</span>{" "}
          or{" "}
          <span className="badge badge-warn">Manual follow-up required</span>{" "}
          means action is recorded but confirmation is still pending.
        </p>
        <p className="hint">
          <span className="text-strong">After action:</span>{" "}
          <span className="badge badge-muted">Review before applying</span>{" "}
          for undecided items; after apply, verify visibility on the next refresh.
        </p>
        <p className="hint">
          <span className="text-strong">Evidence preview:</span> queue/detail views show one compact proof line plus a trust-safe support cue.
        </p>
      </SectionCard>

      <SectionCard variant="summary" className="role-surface-support">
        <SectionHeader
          title="Operator Navigation"
          subtitle="Open the primary workflow surfaces for this role."
          headingLevel={2}
          variant="support"
        />
        <div className="link-row">
          <Link href="/sites">Sites</Link>
          <Link href="/audits">Audit Runs</Link>
          <Link href="/competitors">Competitor Intelligence</Link>
          <Link href="/recommendations">Recommendations</Link>
          <Link href="/automation">Automation Runs</Link>
          <Link href="/business-profile">Google Business Profile</Link>
        </div>
      </SectionCard>

      <SectionCard variant="support" className="role-surface-support">
        <SectionHeader title="Admin" headingLevel={2} variant="support" />
        {principal?.role === "admin" ? (
          <p className="hint muted">
            Business administration is available. Open <Link href="/admin">Admin</Link> to manage principals and settings.
          </p>
        ) : (
          <p className="hint muted">Business administration is restricted to admin principals.</p>
        )}
      </SectionCard>
    </PageContainer>
  );
}
