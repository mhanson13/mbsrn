import "./globals.css";
import type { Metadata } from "next";
import { AuthProvider } from "../components/AuthProvider";
import { NavShell } from "../components/NavShell";

export const metadata: Metadata = {
  title: "My Business Sucks Right Now | Operator Workspace",
  description: "Operator workspace for My Business Sucks Right Now (MBSRN)",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <AuthProvider>
          <NavShell>{children}</NavShell>
        </AuthProvider>
      </body>
    </html>
  );
}
