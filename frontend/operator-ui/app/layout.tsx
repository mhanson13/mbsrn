import "./globals.css";
import type { Metadata } from "next";
import { AuthProvider } from "../components/AuthProvider";
import { NavShell } from "../components/NavShell";
import { getPublicAppVersion } from "../lib/runtimeMetadata";

const PUBLIC_APP_VERSION = getPublicAppVersion();

export const metadata: Metadata = {
  title: "My Business Sucks Right Now | Operator Workspace",
  description: "Operator workspace for My Business Sucks Right Now (MBSRN)",
  other: {
    "mbsrn-ui-version": PUBLIC_APP_VERSION,
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body data-mbsrn-ui-version={PUBLIC_APP_VERSION}>
        <AuthProvider>
          <NavShell>{children}</NavShell>
        </AuthProvider>
      </body>
    </html>
  );
}
