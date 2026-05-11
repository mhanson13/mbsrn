import type { ReactNode } from "react";

import { SectionCard } from "../../../components/layout/SectionCard";
import { SectionHeader } from "../../../components/layout/SectionHeader";

interface AdminSectionWithChildrenProps {
  children?: ReactNode;
}

interface AdminGroupHeadingProps {
  id: string;
  title: string;
  description: string;
}

interface AdminOverviewSectionProps {
  mode: "all" | "admin" | "userMgmt";
  businessId: string;
  principalRole: string | null;
  children: ReactNode;
}

function AdminGroupHeading({ id, title, description }: AdminGroupHeadingProps) {
  return (
    <SectionCard id={id} variant="support" className="role-surface-support">
      <SectionHeader title={title} subtitle={description} headingLevel={2} variant="support" />
    </SectionCard>
  );
}

export function AdminOverviewSection({ mode, businessId, principalRole, children }: AdminOverviewSectionProps) {
  return (
    <SectionCard
      id="admin-group-overview"
      variant="primary"
      className={[
        "role-dashboard-hero",
        mode === "admin" ? "admin-layout-shell-flat" : "",
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <SectionHeader
        title={mode === "userMgmt" ? "User Mgmt" : "Admin Overview"}
        subtitle={
          mode === "userMgmt"
            ? "Create users, link identities, and manage principal access for this business."
            : "Manage platform settings, diagnostics, and site controls for this business."
        }
        headingLevel={1}
        variant="hero"
        meta={(
          <>
            <span className="hint muted">
              Business: <code>{businessId}</code>
            </span>
            {principalRole ? <span className="hint muted">Role: {principalRole}</span> : null}
          </>
        )}
      />
      {children}
    </SectionCard>
  );
}

export function AdminSectionNav() {
  return (
    <nav className="link-row" aria-label="Admin section navigation">
      <a href="#admin-group-overview" className="hint muted">
        Overview
      </a>
      <a href="#admin-group-audit-crawl" className="hint muted">
        Audit & Crawl
      </a>
      <a href="#admin-group-competitor-generation" className="hint muted">
        Competitor Generation
      </a>
      <a href="#admin-group-ai-governance" className="hint muted">
        AI Governance
      </a>
      <a href="#admin-group-publish-deploy" className="hint muted">
        Publish & Deploy
      </a>
      <a href="#admin-group-namespace-policy" className="hint muted">
        Namespace Policy
      </a>
      <a href="#admin-group-site-registry" className="hint muted">
        Site Registry
      </a>
      <a href="#admin-group-diagnostics-logs" className="hint muted">
        Diagnostics
      </a>
    </nav>
  );
}

export function AuditCrawlSettingsSection({ children }: AdminSectionWithChildrenProps) {
  return (
    <>
      <AdminGroupHeading
        id="admin-group-audit-crawl"
        title="Audit & Crawl Settings"
        description="Audit and crawl controls tune deterministic discovery depth and evidence collection behavior."
      />
      {children}
    </>
  );
}

export function CompetitorGenerationSettingsSection({ children }: AdminSectionWithChildrenProps) {
  return (
    <>
      <AdminGroupHeading
        id="admin-group-competitor-generation"
        title="Competitor Generation Settings"
        description="Competitor generation controls tune deterministic candidate quality and timeout behavior."
      />
      {children}
    </>
  );
}

export function AiPromptGovernanceSection({ children }: AdminSectionWithChildrenProps) {
  return (
    <>
      <AdminGroupHeading
        id="admin-group-ai-governance"
        title="AI Provider & Prompt Governance"
        description="AI prompt and model changes affect generated recommendations, competitors, and migration drafts."
      />
      {children}
    </>
  );
}

export function PublishDeploymentConfigSection({ children }: AdminSectionWithChildrenProps) {
  return (
    <>
      <AdminGroupHeading
        id="admin-group-publish-deploy"
        title="Publish & Deployment Configuration"
        description="Deployment configuration controls publish/deploy target behavior across managed workflows."
      />
      {children}
    </>
  );
}

export function ManagedNamespacePolicySection({ children }: AdminSectionWithChildrenProps) {
  return (
    <div id="admin-group-namespace-policy" className="panel panel-compact stack-tight">
      <strong>Managed Namespace Policy</strong>
      <p className="hint muted">
        Namespace policy controls managed site Kubernetes defaults for new managed site namespaces.
      </p>
      {children}
    </div>
  );
}

export function SiteRegistryManagementSection({ children }: AdminSectionWithChildrenProps) {
  return (
    <>
      <AdminGroupHeading
        id="admin-group-site-registry"
        title="Site Registry Management"
        description="Site Registry changes affect active site records and destructive deletion controls."
      />
      {children}
    </>
  );
}

export function AdminDiagnosticsLogsSection({ children }: AdminSectionWithChildrenProps) {
  return (
    <>
      <AdminGroupHeading
        id="admin-group-diagnostics-logs"
        title="Diagnostics & Logs"
        description="Diagnostics is read-only log investigation for runtime troubleshooting."
      />
      {children}
    </>
  );
}
