import type { Metadata } from "next";
import { supportEmail } from "../../lib/siteContent";

export const metadata: Metadata = {
  title: "Terms of Service",
  description: "MBSRN terms of service for operator SaaS usage.",
  alternates: {
    canonical: "/terms",
  },
  openGraph: {
    title: "MBSRN Terms of Service",
    description: "Plain-English baseline terms for use of the MBSRN platform.",
    url: "https://www.mbsrn.com/terms",
    siteName: "MBSRN",
    type: "article",
  },
};

export default function TermsPage() {
  return (
    <div className="page-shell page-shell-narrow">
      <section className="legal-page">
        <p className="eyebrow">Legal</p>
        <h1>Terms of Service</h1>
        <p className="legal-updated">Last updated: April 6, 2026</p>

        <h2>1. Acceptance of terms</h2>
        <p>
          By accessing or using MBSRN, you agree to these terms. If you do not agree, do not use the service.
        </p>

        <h2>2. Service description</h2>
        <p>
          MBSRN is an operator-focused SEO platform for audits, recommendations, competitor context, and
          workflow visibility. It is intended to support decision-making and execution by business operators.
        </p>

        <h2>3. Account responsibilities</h2>
        <ul>
          <li>Keep account credentials secure.</li>
          <li>Ensure users in your workspace are authorized by your business.</li>
          <li>You are responsible for activity under your workspace accounts.</li>
        </ul>

        <h2>4. Acceptable use</h2>
        <ul>
          <li>No unlawful use or abuse of integrations.</li>
          <li>No attempts to bypass security, scope, or access controls.</li>
          <li>No use that materially degrades platform availability for others.</li>
        </ul>

        <h2>5. Third-party integrations</h2>
        <p>
          Some features use third-party services (including Google APIs) when configured. You must have
          rights and authority to connect those accounts and properties.
        </p>

        <h2>6. Availability and changes</h2>
        <p>
          We may modify, suspend, or improve features as needed for security, reliability, and product evolution.
        </p>

        <h2>7. No warranty baseline</h2>
        <p>
          The service is provided on an “as is” and “as available” basis to the maximum extent allowed by law.
          MBSRN does not guarantee specific SEO rankings, traffic increases, or business outcomes.
        </p>

        <h2>8. Limitation of liability</h2>
        <p>
          To the maximum extent permitted by law, MBSRN will not be liable for indirect, incidental,
          special, consequential, or punitive damages arising from use of the service.
        </p>

        <h2>9. Fees and subscriptions</h2>
        <p>
          If you use a paid plan, billing cadence, renewal, and cancellation terms are provided at the
          time of purchase and in your plan documentation. If no paid plan applies, available free or
          trial access is still governed by these terms.
        </p>

        <h2>10. Termination</h2>
        <p>
          We may suspend or terminate access for material violations of these terms. You may stop using the
          service at any time.
        </p>

        <h2>11. Contact and updates</h2>
        <p>
          Contact: <strong>{supportEmail}</strong>
        </p>
        <p>
          We may revise these terms from time to time. Updated versions will be posted on this page with the
          revised date.
        </p>

        <p className="legal-note">
          Starter terms notice: this page is a plain-English SaaS baseline and requires legal review before
          long-term production use.
        </p>
      </section>
    </div>
  );
}
