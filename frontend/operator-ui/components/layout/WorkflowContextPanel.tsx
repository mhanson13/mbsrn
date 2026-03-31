import Link from "next/link";
import type { ReactNode } from "react";

import { SectionCard } from "./SectionCard";
import { SectionHeader } from "./SectionHeader";

type WorkflowContextLink = {
  href: string;
  label: string;
};

type WorkflowContextNextStep = {
  href: string;
  label: string;
  note?: string;
};

type WorkflowContextPanelProps = {
  title?: string;
  subtitle?: ReactNode;
  lineage?: ReactNode;
  links: WorkflowContextLink[];
  nextStep?: WorkflowContextNextStep | null;
  "data-testid"?: string;
};

export function WorkflowContextPanel({
  title = "Workflow context",
  subtitle,
  lineage,
  links,
  nextStep,
  "data-testid": dataTestId,
}: WorkflowContextPanelProps) {
  const visibleLinks = links.filter((item) => item.href.trim().length > 0 && item.label.trim().length > 0);

  if (visibleLinks.length === 0 && !lineage && !nextStep) {
    return null;
  }

  return (
    <SectionCard
      variant="support"
      className="role-surface-support workflow-context-surface"
      data-testid={dataTestId}
    >
      <SectionHeader
        title={title}
        subtitle={subtitle || "Use these links to move between parent and adjacent workflow steps."}
        headingLevel={2}
        compact
        variant="support"
      />
      {lineage ? <p className="hint muted workflow-context-lineage">{lineage}</p> : null}
      {visibleLinks.length > 0 ? (
        <div className="link-row workflow-context-link-row">
          {visibleLinks.map((item) => (
            <Link key={`${item.href}:${item.label}`} href={item.href}>
              {item.label}
            </Link>
          ))}
        </div>
      ) : null}
      {nextStep ? (
        <p className="hint workflow-context-next-step">
          <span className="text-strong">Next step:</span>
          <Link href={nextStep.href}>{nextStep.label}</Link>
          {nextStep.note ? <span className="workflow-context-next-note">{nextStep.note}</span> : null}
        </p>
      ) : null}
    </SectionCard>
  );
}
