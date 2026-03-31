import type { ReactNode } from "react";

type SummaryStatCardTone = "neutral" | "success" | "warning" | "danger";
type SummaryStatCardVariant = "default" | "elevated" | "focus";

type SummaryStatCardProps = {
  label: string;
  value: ReactNode;
  detail?: ReactNode;
  tone?: SummaryStatCardTone;
  variant?: SummaryStatCardVariant;
  "data-testid"?: string;
};

export function SummaryStatCard({
  label,
  value,
  detail,
  tone = "neutral",
  variant = "default",
  "data-testid": dataTestId,
}: SummaryStatCardProps) {
  const variantClassName = variant === "default" ? "" : `summary-stat-card-variant-${variant}`;
  return (
    <article
      className={`summary-stat-card summary-stat-card-${tone}${variantClassName ? ` ${variantClassName}` : ""}`}
      data-testid={dataTestId}
    >
      <span className="summary-stat-label">{label}</span>
      <strong className="summary-stat-value">{value}</strong>
      {detail ? <span className="summary-stat-detail">{detail}</span> : null}
    </article>
  );
}
