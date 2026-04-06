import type { Metadata } from "next";
import { SiteFooter } from "../components/SiteFooter";
import { SiteHeader } from "../components/SiteHeader";
import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "MBSRN | SEO Operations For Small Businesses",
    template: "%s | MBSRN",
  },
  description:
    "MBSRN helps small business operators run practical SEO workflows with audits, competitor intelligence, and actionable recommendations.",
  metadataBase: new URL("https://www.mbsrn.com"),
  alternates: {
    canonical: "/",
  },
  openGraph: {
    title: "MBSRN | SEO Operations For Small Businesses",
    description:
      "Operator-friendly SEO operations platform for audits, competitor pressure visibility, and clear next actions.",
    url: "https://www.mbsrn.com/",
    siteName: "MBSRN",
    locale: "en_US",
    type: "website",
    images: [
      {
        url: "/brand/mbsrn-logo-horizontal-dark.svg",
        width: 460,
        height: 96,
        alt: "MBSRN",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "MBSRN | SEO Operations For Small Businesses",
    description:
      "Audit visibility, competitor context, and recommendation workflows for operators.",
    images: ["/brand/mbsrn-logo-horizontal-dark.svg"],
  },
  icons: {
    icon: [
      { url: "/favicon.svg", type: "image/svg+xml" },
    ],
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <SiteHeader />
        <main>{children}</main>
        <SiteFooter />
      </body>
    </html>
  );
}
