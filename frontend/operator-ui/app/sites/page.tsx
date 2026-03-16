"use client";

import { useOperatorContext } from "../../components/useOperatorContext";

export default function SitesPage() {
  const context = useOperatorContext();

  if (context.loading) {
    return <section className="panel">Loading sites...</section>;
  }
  if (context.error) {
    return <section className="panel">Error: {context.error}</section>;
  }

  return (
    <section className="panel stack">
      <h1>SEO Sites</h1>
      <p>Business: <code>{context.businessId}</code></p>
      <table className="table">
        <thead>
          <tr>
            <th>Display Name</th>
            <th>Base URL</th>
            <th>Domain</th>
            <th>Primary</th>
            <th>Active</th>
          </tr>
        </thead>
        <tbody>
          {context.sites.map((site) => (
            <tr key={site.id}>
              <td>{site.display_name}</td>
              <td>{site.base_url}</td>
              <td>{site.normalized_domain}</td>
              <td>{site.is_primary ? "yes" : "no"}</td>
              <td>{site.is_active ? "yes" : "no"}</td>
            </tr>
          ))}
          {context.sites.length === 0 ? (
            <tr>
              <td colSpan={5}>No sites configured for this business.</td>
            </tr>
          ) : null}
        </tbody>
      </table>
    </section>
  );
}
