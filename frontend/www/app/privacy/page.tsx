import type { Metadata } from "next";
import { supportEmail } from "../../lib/siteContent";

export const metadata: Metadata = {
  title: "Privacy Policy",
  description: "MBSRN privacy policy for the public site and operator SaaS application.",
  alternates: {
    canonical: "/privacy",
  },
  openGraph: {
    title: "MBSRN Privacy Policy",
    description: "How MBSRN handles operator account, workspace, and authorized integration data.",
    url: "https://www.mbsrn.com/privacy",
    siteName: "MBSRN",
    type: "article",
  },
};

export default function PrivacyPage() {
  return (
    <div className="page-shell page-shell-narrow">
      <section className="legal-page">
        <p className="eyebrow">Legal</p>
        <h1>Privacy Policy</h1>
        <p className="legal-updated">Last updated: April 6, 2026</p>

        <h2>1. What this policy covers</h2>
        <p>
          This policy covers the MBSRN public website and operator application. It explains what
          information may be processed, why it is processed, and how operators can request support.
        </p>

        <h2>2. Information we may collect</h2>
        <ul>
          <li>
            <strong>Account and authentication data:</strong> identity details required to sign in and
            authorize workspace access.
          </li>
          <li>
            <strong>Workspace and configuration data:</strong> business/site records, workflow settings,
            and operator-entered metadata.
          </li>
          <li>
            <strong>Usage and diagnostic data:</strong> application logs, run outcomes, status indicators,
            and operational diagnostics needed to keep the service reliable.
          </li>
          <li>
            <strong>Connected Google data (when authorized):</strong> limited Google integration data used
            by enabled product features.
          </li>
        </ul>

        <h2>3. How we use information</h2>
        <ul>
          <li>Provide and secure operator workflows.</li>
          <li>Run SEO analysis and recommendation surfaces requested by the operator.</li>
          <li>Provide integration health and diagnostics.</li>
          <li>Maintain service reliability, abuse prevention, and platform operations.</li>
        </ul>

        <h2>4. Google data usage boundary</h2>
        <p>
          Connected Google data is used only to provide authorized functionality requested by the user
          or workspace admin. We do not use connected Google data for unrelated advertising purposes.
        </p>

        <h2>5. Sharing and service providers</h2>
        <p>
          We may use infrastructure and service providers needed to operate MBSRN (for example cloud
          hosting, observability, and API infrastructure). We do not sell personal information.
        </p>

        <h2>6. Retention and security</h2>
        <p>
          Data is retained according to operational requirements and platform policies. MBSRN applies
          reasonable technical and organizational safeguards for a SaaS environment. No system can be
          guaranteed 100% secure.
        </p>

        <h2>7. Your choices and requests</h2>
        <p>
          Workspace admins can update site-level integration settings from the operator app. For data
          access, correction, or deletion requests, contact support.
        </p>

        <h2>8. Contact</h2>
        <p>
          Contact: <strong>{supportEmail}</strong>
        </p>

        <h2>9. Policy updates</h2>
        <p>
          We may update this policy as the product evolves. Material updates will be posted on this page
          with an updated effective date.
        </p>

        <p className="legal-note">
          Starter policy notice: this page is practical product copy and should be reviewed by legal
          counsel before long-term production use.
        </p>
      </section>
    </div>
  );
}
