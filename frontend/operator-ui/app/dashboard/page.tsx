"use client";

import Link from "next/link";
import { useOperatorContext } from "../../components/useOperatorContext";

export default function DashboardPage() {
  const context = useOperatorContext();

  if (context.loading) {
    return <section className="panel">Loading dashboard...</section>;
  }
  if (context.error) {
    return <section className="panel">Error: {context.error}</section>;
  }

  return (
    <section className="stack">
      <div className="panel stack">
        <h1>Dashboard</h1>
        <p>
          Business scope: <code>{context.businessId}</code>
        </p>
        <p>
          Tracked SEO sites: <strong>{context.sites.length}</strong>
        </p>
      </div>

      <div className="panel stack">
        <h2>Operator Navigation</h2>
        <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
          <Link href="/sites">Sites</Link>
          <Link href="/audits">Audit Runs</Link>
          <Link href="/competitors">Competitor Intelligence</Link>
          <Link href="/recommendations">Recommendations</Link>
          <Link href="/automation">Automation Runs</Link>
          <Link href="/business-profile">Google Business Profile</Link>
        </div>
      </div>
    </section>
  );
}
