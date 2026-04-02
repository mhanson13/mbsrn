"use client";

import type { SEOSite } from "../../lib/api/types";

interface WorkflowSiteSelectorProps {
  id: string;
  sites: SEOSite[];
  selectedSiteId: string | null;
  onChange: (siteId: string) => void;
  label?: string;
  className?: string;
  disabled?: boolean;
}

export function WorkflowSiteSelector({
  id,
  sites,
  selectedSiteId,
  onChange,
  label = "Site",
  className,
  disabled = false,
}: WorkflowSiteSelectorProps) {
  const hasSites = sites.length > 0;
  return (
    <div
      className={["workflow-site-selector", className].filter(Boolean).join(" ")}
      data-testid={`workflow-site-selector-${id}`}
    >
      <label htmlFor={id}>{label}</label>
      <select
        id={id}
        className="operator-select"
        value={selectedSiteId || ""}
        onChange={(event) => onChange(event.target.value)}
        disabled={!hasSites || disabled}
      >
        {hasSites ? (
          sites.map((site) => (
            <option key={site.id} value={site.id}>
              {site.display_name}
            </option>
          ))
        ) : (
          <option value="">No sites available</option>
        )}
      </select>
    </div>
  );
}
