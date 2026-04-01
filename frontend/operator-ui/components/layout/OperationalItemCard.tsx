import type { ReactNode } from "react";
import { useId, useState } from "react";

import { SectionCard } from "./SectionCard";

type OperationalItemCardProps = {
  title: ReactNode;
  identity?: ReactNode;
  chips?: ReactNode;
  summary?: ReactNode;
  primaryAction?: ReactNode;
  secondaryMeta?: ReactNode;
  expandedDetail?: ReactNode;
  defaultExpanded?: boolean;
  expandLabel?: string;
  collapseLabel?: string;
  className?: string;
  "data-testid"?: string;
};

export function OperationalItemCard({
  title,
  identity,
  chips,
  summary,
  primaryAction,
  secondaryMeta,
  expandedDetail,
  defaultExpanded = false,
  expandLabel = "Show details",
  collapseLabel = "Hide details",
  className = "",
  "data-testid": dataTestId,
}: OperationalItemCardProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const detailId = useId();
  const classes = ["operational-item-card", className].filter(Boolean).join(" ");

  return (
    <SectionCard
      as="article"
      variant="summary"
      className={classes}
      data-testid={dataTestId}
    >
      <div className="operational-item-header">
        <div className="operational-item-title-stack">
          <h3 className="operational-item-title">{title}</h3>
          {identity ? <p className="hint muted operational-item-identity">{identity}</p> : null}
        </div>
        {chips ? <div className="operational-item-chip-group">{chips}</div> : null}
      </div>
      {summary ? <p className="hint operational-item-summary">{summary}</p> : null}
      <div className="operational-item-actions">
        {primaryAction ? <div className="operational-item-action-primary">{primaryAction}</div> : null}
        {expandedDetail ? (
          <button
            type="button"
            className="button button-tertiary button-inline"
            aria-expanded={expanded}
            aria-controls={detailId}
            onClick={() => setExpanded((value) => !value)}
          >
            {expanded ? collapseLabel : expandLabel}
          </button>
        ) : null}
      </div>
      {secondaryMeta ? <div className="operational-item-secondary">{secondaryMeta}</div> : null}
      {expanded && expandedDetail ? (
        <div id={detailId} className="operational-item-expanded">
          {expandedDetail}
        </div>
      ) : null}
    </SectionCard>
  );
}
