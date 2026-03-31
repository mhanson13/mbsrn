import Link from "next/link";
import type { ReactNode } from "react";

import { SectionCard } from "./SectionCard";
import { SectionHeader } from "./SectionHeader";

type DetailFocusNextStep = {
  label: string;
  href?: string;
  note?: ReactNode;
};

export type DetailFocusFact = {
  label: string;
  value: ReactNode;
  tone?: "neutral" | "success" | "warning" | "danger";
};

type DetailFocusPanelProps = {
  title?: string;
  takeaway: ReactNode;
  nextStep?: DetailFocusNextStep | null;
  facts?: DetailFocusFact[] | null;
  detailHint?: ReactNode;
  "data-testid"?: string;
};

export function DetailFocusPanel({
  title = "What matters now",
  takeaway,
  nextStep,
  facts,
  detailHint,
  "data-testid": dataTestId,
}: DetailFocusPanelProps) {
  const visibleFacts = (facts || []).filter(
    (item) => item.label.trim().length > 0,
  );

  return (
    <SectionCard
      variant="summary"
      className="role-surface-support detail-focus-surface"
      data-testid={dataTestId}
    >
      <SectionHeader
        title={title}
        subtitle="Quick summary before diving into full detail."
        headingLevel={2}
        compact
        variant="support"
      />
      <p className="detail-focus-line">
        <span className="text-strong">Top takeaway:</span> {takeaway}
      </p>
      {nextStep ? (
        <p className="detail-focus-line">
          <span className="text-strong">Likely next action:</span>{" "}
          {nextStep.href ? <Link href={nextStep.href}>{nextStep.label}</Link> : nextStep.label}
          {nextStep.note ? <span className="detail-focus-note">{nextStep.note}</span> : null}
        </p>
      ) : null}
      {visibleFacts.length > 0 ? (
        <dl className="detail-focus-facts">
          {visibleFacts.map((fact) => (
            <div
              key={fact.label}
              className={`detail-focus-fact detail-focus-fact-${fact.tone || "neutral"}`}
            >
              <dt>{fact.label}</dt>
              <dd>{fact.value}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      {detailHint ? (
        <p className="detail-focus-line hint muted">
          <span className="text-strong">Where detail lives:</span> {detailHint}
        </p>
      ) : null}
    </SectionCard>
  );
}
