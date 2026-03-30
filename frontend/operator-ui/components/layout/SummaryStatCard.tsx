import type { ReactNode } from "react";

type SummaryStatCardTone = "neutral" | "success" | "warning" | "danger";

type SummaryStatCardProps = {
  label: string;
  value: ReactNode;
  detail?: ReactNode;
  tone?: SummaryStatCardTone;
  "data-testid"?: string;
};

export function SummaryStatCard({
  label,
  value,
  detail,
  tone = "neutral",
  "data-testid": dataTestId,
}: SummaryStatCardProps) {
  return (
    <article className={`summary-stat-card summary-stat-card-${tone}`} data-testid={dataTestId}>
      <span className="summary-stat-label">{label}</span>
      <strong className="summary-stat-value">{value}</strong>
      {detail ? <span className="summary-stat-detail">{detail}</span> : null}
    </article>
  );
}
